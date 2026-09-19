"""One isolated pending-operation/owned-backend restart acceptance case.

This developer supervisor is never imported by normal desktop startup. It owns
only the exact Popen handles it creates, verifies public identity before sending
the fixture credential, and never discovers or stops processes through a port.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


prior = module('managed_recovery_common', 'run-facility-recovery-check.py')
render, base, write = prior.render, prior.base, prior.write
CASES = tuple(kind + '-' + suffix for kind in ('apply', 'undo') for suffix in
              ('success', 'failed-restart', 'identity-mismatch', 'lease-expired', 'other-writer'))
RUNTIME_PATH = '/__facility-recovery__/runtime'
REQUIRED_CHECKS = {'cancelBeforeRestartPreservesExactState', 'restartDuringPendingTransaction',
                   'durableLookupAndStableIdentity', 'zeroSaveAndNoDuplicateExecution'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(request.full_url, code,
            'Managed fixture requests may not redirect', headers, response)


def request_json(origin, route, token=None, body=None, timeout=5):
    headers = {'Content-Type': 'application/json'} if body is not None else {}
    if token is not None:
        headers['X-InspectorPro-Recovery-Test'] = token
    request = urllib.request.Request(origin + route, headers=headers,
        data=json.dumps(body).encode() if body is not None else None)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.load(response), dict(response.headers)
    except urllib.error.HTTPError as error:
        error.close()
        raise


def same_runtime(expected, actual, *, instance_id, process_id):
    if (not isinstance(actual, dict) or any(actual.get(key) != expected.get(key)
            for key in ('identity', 'document', 'owner', 'origin'))
            or actual.get('mode') != 'facility-managed-backend-recovery-test'
            or actual.get('instanceId') != instance_id or actual.get('processId') != process_id):
        raise ValueError('Managed runtime identity, owner, origin, or process instance changed')
    for key in ('backendId', 'storeId', 'principalId'):
        if not isinstance(actual.get('identity', {}).get(key), str) or not actual['identity'][key]:
            raise ValueError('Managed runtime logical identity is incomplete')
    return actual


def verified_runtime(identity, instance_id, process_id, token, expected=None):
    # No credential is supplied until both the logical public identity and the
    # unpredictable expected process-instance nonce have matched.
    public, headers = request_json(identity['origin'], base.IDENTITY_PATH)
    instance = next((value for key, value in headers.items()
                     if key.lower() == 'x-inspectorpro-rendering-instance'), None)
    if public != base.public_identity(identity) or instance != instance_id:
        raise ValueError('Public backend identity mismatch; no credential was sent')
    actual, _ = request_json(identity['origin'], RUNTIME_PATH, token)
    if expected is None:
        expected = dict(actual, origin=identity['origin'])
        if any(actual.get('identity', {}).get(key) != identity[key] for key in ('backendId', 'storeId')):
            raise ValueError('Private backend identity differs from verified public identity')
    return same_runtime(expected, actual, instance_id=instance_id, process_id=process_id)


def stop_owned_process(process, *, graceful=False):
    """Callers must already hold the original owned handle; no PID lookup."""
    if process.poll() is None:
        if graceful:
            base.stop_child(process)
        else:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
    if process.poll() is None:
        raise RuntimeError('Owned child termination was not confirmed')


def finish_pipe(record):
    reader, state = record.get('reader'), record.get('pipe')
    if reader is None:
        # If reader setup failed, no thread owns this untouched handle. Closing
        # our handle is cleanup only and is deliberately not described as EOF.
        stream = record.get('stream')
        if stream is not None:
            stream.close()
        return {'stdioEOFVerified': False, 'stdioClosed': False}
    reader.join(timeout=5)
    result = {'stdioEOFVerified': not reader.is_alive() and state.get('eof') is True,
              'stdioClosed': not reader.is_alive() and state.get('closed') is True}
    if state.get('error'):
        result['logError'] = state['error']
    return result


class BackendSupervisor:
    def __init__(self, data, output, identity, library, token_path, *, process_factory=None):
        self.data, self.output, self.identity, self.library = data, output, identity, library
        self.token_path = token_path
        self.token = token_path.read_text(encoding='ascii')
        self.process_factory = process_factory or subprocess.Popen
        self.records = []
        self.current = None
        self.initial_runtime = None

    def start(self, *, startup_failure=False):
        if self.current is not None and self.current['process'].poll() is None:
            raise RuntimeError('Cannot replace a live owned backend')
        instance = str(uuid.uuid4())
        number = len(self.records) + 1
        folder = self.output / ('backend-' + str(number))
        folder.mkdir()
        env = base.child_environment(dict(os.environ), self.data, self.library)
        env.update(INSPECTORPRO_DESKTOP_INSTANCE_ID=instance,
                   INSPECTORPRO_FACILITY_RECOVERY_HARNESS='1',
                   INSPECTORPRO_FACILITY_MANAGED_RESTART_HARNESS='1')
        from ai_inspector.facility_layout.feature_flags import FACILITY_LAYOUT_FEATURE_FLAGS, FACILITY_DESIGN_LOOP_FEATURE_FLAGS
        for name in FACILITY_LAYOUT_FEATURE_FLAGS:
            env[name] = '1'
        for name in FACILITY_DESIGN_LOOP_FEATURE_FLAGS:
            env[name] = '0' if name.endswith(('_LAB', '_SAGE')) else '1'
        command = [sys.executable, '-u', str(Path(__file__).with_name('facility-recovery-backend.py')),
                   '--serve', '--data-root', str(self.data), '--port', self.identity['origin'].rsplit(':', 1)[1],
                   '--profile-id', self.identity['profileId'], '--token-file', str(self.token_path)]
        if startup_failure:
            command = [sys.executable, '-u', '-c',
                       'import sys; print("INJECTED_MANAGED_BACKEND_PRESTART_FAILURE", flush=True); sys.exit(73)']
        record = {'instanceId': instance, 'process': None, 'reader': None, 'pipe': None,
                  'folder': folder, 'startupFailureInjected': startup_failure,
                  'evidence': {'instanceId': instance, 'status': 'starting', 'terminationConfirmed': False,
                               'resourceCleanupVerified': False, 'applicationStarted': False,
                               'startupTimeoutSeconds': 45, 'spawnRequestedAt': render.now()}}
        self.records.append(record)
        write(folder / 'result.json', record['evidence'])
        # Create the log before spawn; spawn failures retain a real diagnostic file.
        (folder / 'backend.log').touch()
        started = time.monotonic()
        wait_started = None
        try:
            process = self.process_factory(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **render.spawn_options())
            record['process'] = process
            record['stream'] = process.stdout
            self.current = record
            record['evidence']['pid'] = process.pid
            record['evidence'].update(spawnReturnedAt=render.now(),
                spawnDurationMs=round((time.monotonic() - started) * 1000, 3))
            record['reader'], record['pipe'] = render.start_pipe_capture(process.stdout, folder / 'backend.log')
            write(folder / 'result.json', record['evidence'])
            if startup_failure:
                process.wait(timeout=10)
                if process.returncode != 73:
                    raise RuntimeError('Injected pre-start failure did not exit with the expected code')
                raise RuntimeError('Injected managed backend restart failed before application startup')
            wait_started = time.monotonic()
            record['evidence'].update(startupStage='public-readiness', readinessWaitStartedAt=render.now())
            base.wait_ready(process, self.identity, 45, instance)
            record['evidence'].update(publicReadinessVerifiedAt=render.now(),
                readinessWaitElapsedMs=round((time.monotonic() - wait_started) * 1000, 3),
                startupStage='private-runtime-verification')
            runtime = verified_runtime(self.identity, instance, process.pid, self.token, self.initial_runtime)
            if self.initial_runtime is not None and runtime['instanceId'] == self.initial_runtime['instanceId']:
                raise ValueError('Restart reused the prior process-instance ID')
            record['runtime'] = runtime
            record['evidence'].update(status='ready', applicationStarted=True, runtime=runtime,
                startupStage='ready', runtimeVerifiedAt=render.now(),
                startupElapsedMs=round((time.monotonic() - started) * 1000, 3),
                startupDiagnosticsAtReadiness=self.startup_diagnostics(record))
            self.initial_runtime = self.initial_runtime or deepcopy(runtime)
            write(folder / 'result.json', record['evidence'])
            return runtime
        except BaseException as error:
            record['evidence'].update(status='failed', error=str(error), startupFailedAt=render.now(),
                startupElapsedMs=round((time.monotonic() - started) * 1000, 3),
                startupDiagnosticsAtFailure=self.startup_diagnostics(record))
            if wait_started is not None and 'readinessWaitElapsedMs' not in record['evidence']:
                record['evidence']['readinessWaitElapsedMs'] = round((time.monotonic() - wait_started) * 1000, 3)
            write(folder / 'result.json', record['evidence'])
            raise

    @staticmethod
    def startup_diagnostics(record):
        # Observations only: phase checkpoints never replace public/private
        # identity verification or the matching resource-cleanup receipt.
        try:
            return render.backend_startup_evidence(record['folder'] / 'backend.log',
                record['instanceId'], record['evidence'].get('pid'))
        except Exception as error:
            return {'revision': 'backend-startup-v1', 'readErrorType': type(error).__name__}

    def stop(self, record=None):
        record = record or self.current
        if record is None:
            return None
        if not any(record is owned for owned in self.records):
            raise ValueError('Refusing to stop a backend handle not created by this supervisor')
        evidence, process = record['evidence'], record['process']
        if evidence.get('cleanupCompleted'):
            return evidence
        error = None
        try:
            if process is not None:
                stop_owned_process(process, graceful=not record['startupFailureInjected'])
                evidence.update(exitCode=process.poll(), terminationConfirmed=True)
                evidence.update(finish_pipe(record))
                if not evidence.get('stdioEOFVerified') or not evidence.get('stdioClosed') or evidence.get('logError'):
                    raise RuntimeError('Owned backend diagnostic EOF/closure or log persistence was not confirmed')
                receipt_path = base.shutdown_receipt_path(self.data, record['instanceId'])
                receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
                expected = {'schemaVersion': 1, 'instanceId': record['instanceId'],
                            'status': 'lifespan-stopped', 'resourcesClosed': True}
                if record['startupFailureInjected']:
                    if process.poll() != 73 or receipt is not None:
                        raise RuntimeError('Pre-start fault cleanup evidence is inconsistent')
                    evidence['resourceCleanupNotApplicable'] = 'injected child exited before application import'
                else:
                    if receipt != expected:
                        raise RuntimeError('Owned backend resource-cleanup receipt missing or mismatched')
                    evidence['resourceCleanupVerified'] = True
            else:
                evidence['notSpawned'] = True
            evidence['cleanupCompleted'] = True
        except BaseException as caught:
            error = caught
            evidence.update(cleanupError=str(caught), status='failed')
            if process is not None:
                evidence.update(exitCode=process.poll(), terminationConfirmed=process.poll() is not None)
        finally:
            evidence['startupDiagnostics'] = self.startup_diagnostics(record)
            prior.final_write(record['folder'] / 'result.json', evidence, error)
        if error:
            raise error
        return evidence

    def close(self):
        errors = []
        for record in self.records:
            try:
                self.stop(record)
            except BaseException as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError('; '.join(errors))


def sentinel_main(arguments):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--identity-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(arguments)
    identity = json.loads(args.identity_file.read_text())
    state = {'schemaVersion': 1, 'pid': os.getpid(), 'identityRequests': 0,
             'credentialRequests': 0, 'otherRequests': 0, 'instanceId': str(uuid.uuid4())}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state['credentialRequests'] += int(self.headers.get('X-InspectorPro-Recovery-Test') is not None)
            state['identityRequests' if self.path == base.IDENTITY_PATH else 'otherRequests'] += 1
            write(args.output / 'sentinel-evidence.json', state)
            body = json.dumps(identity if self.path == base.IDENTITY_PATH else {'sentinel': True}).encode()
            self.send_response(200 if self.path in {base.IDENTITY_PATH, '/health'} else 403)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-InspectorPro-Rendering-Instance', state['instanceId'])
            self.end_headers()
            self.wfile.write(body)
        do_POST = do_GET
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', args.port), Handler)
    state['port'] = server.server_address[1]
    write(args.output / 'sentinel-ready.json', state)
    print('UNRELATED_SENTINEL_READY', flush=True)
    server.serve_forever(poll_interval=0.1)


class Sentinel:
    """Test-owned server whose handle is never given to BackendSupervisor."""
    def __init__(self, output, identity, port=0):
        self.folder = output
        output.mkdir()
        wrong = base.public_identity(identity)
        wrong['storeId'] = str(uuid.uuid4())
        identity_file = output / 'public-identity.json'
        write(identity_file, wrong)
        command = [sys.executable, '-u', str(Path(__file__).resolve()), '--sentinel', '--port', str(port),
                   '--identity-file', str(identity_file), '--output', str(output)]
        self.record = {'reader': None, 'pipe': None}
        self.process = None
        (output / 'sentinel.log').touch()
        try:
            self.process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **render.spawn_options())
            self.record['stream'] = self.process.stdout
            self.record['reader'], self.record['pipe'] = render.start_pipe_capture(self.process.stdout, output / 'sentinel.log')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError('Unrelated sentinel exited before readiness')
                ready = output / 'sentinel-ready.json'
                if ready.exists():
                    value = json.loads(ready.read_text())
                    self.origin = 'http://127.0.0.1:' + str(value['port'])
                    self.assert_survived()
                    return
                time.sleep(0.05)
            raise RuntimeError('Unrelated sentinel startup timed out')
        except BaseException:
            self.close()
            raise

    def assert_survived(self):
        if self.process.poll() is not None:
            raise RuntimeError('Recovery terminated an unrelated server')
        health, _ = request_json(self.origin, '/health')
        evidence = json.loads((self.folder / 'sentinel-evidence.json').read_text())
        if health != {'sentinel': True} or evidence['credentialRequests'] != 0:
            raise RuntimeError('Unrelated server received a fixture credential or failed its health check')
        return dict(evidence, survivedRecovery=True, terminationRequestedByRecovery=False)

    def close(self):
        if self.process is None:
            return
        stop_owned_process(self.process)
        evidence = dict(finish_pipe(self.record), exitCode=self.process.poll(), terminationConfirmed=True,
                        stoppedBy='explicit sentinel fixture teardown after recovery checks')
        write(self.folder / 'cleanup.json', evidence)
        if not evidence['stdioClosed'] or not evidence['stdioEOFVerified'] or evidence.get('logError'):
            raise RuntimeError('Sentinel fixture diagnostic cleanup failed')


def validate_control(value, case):
    fields = {'schemaVersion', 'requestId', 'action', 'fault', 'leaseFault', 'pendingOperation'}
    if (not isinstance(value, dict) or set(value) != fields or type(value.get('schemaVersion')) is not int
            or value['schemaVersion'] != 1 or value.get('action') != 'restart'
            or not isinstance(value.get('requestId'), str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value['requestId'])):
        raise ValueError('Malformed or stale managed restart request')
    suffix = case.split('-', 1)[1]
    expected_fault = {'failed-restart': 'startup-failure', 'identity-mismatch': 'identity-mismatch'}.get(suffix, 'none')
    expected_lease = {'lease-expired': 'expired', 'other-writer': 'other-writer'}.get(suffix, 'none')
    if value['fault'] != expected_fault or value['leaseFault'] != expected_lease:
        raise ValueError('Restart fault differs from the selected acceptance case')
    pending = value.get('pendingOperation')
    if (not isinstance(pending, dict) or set(pending) != {'requestId', 'transactionId'}
            or any(not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', item)
                   for item in pending.values())):
        raise ValueError('Restart must retain the pending transaction and request identity')
    return value


class RestartControl:
    def __init__(self, supervisor, directory, case):
        self.supervisor, self.directory, self.case = supervisor, directory, case
        if directory.exists():
            raise ValueError('Managed control directory must be new; stale requests are forbidden')
        directory.mkdir()
        self.accepted = None
        self.response = None
        self.sentinel = None

    def poll(self):
        target = base.no_links(self.directory / 'request.json')
        if not target.exists():
            return False
        if target.stat().st_size > 8192:
            raise ValueError('Managed restart request is oversized')
        value = validate_control(json.loads(target.read_text()), self.case)
        if self.accepted is not None:
            if value != self.accepted:
                raise ValueError('Only one immutable managed restart request is accepted')
            return False
        self.accepted = deepcopy(value)
        manager = self.supervisor
        response = {'schemaVersion': 1, 'requestId': value['requestId'], 'status': 'failed',
                    'beforeRuntime': deepcopy(manager.initial_runtime), 'writeAuthority': False}
        try:
            response['cleanup'] = deepcopy(manager.stop())
            if value['fault'] == 'identity-mismatch':
                self.sentinel = Sentinel(self.directory / 'mismatched-server', manager.identity,
                                         int(manager.identity['origin'].rsplit(':', 1)[1]))
                # A sentinel is deliberately NOT enrolled as an owned backend.
                try:
                    verified_runtime(manager.identity, str(uuid.uuid4()), -1, manager.token, manager.initial_runtime)
                    raise AssertionError('Mismatched server unexpectedly passed identity verification')
                except ValueError as error:
                    response.update(status='identity-mismatch', error=str(error),
                                    unrelatedServer=self.sentinel.assert_survived())
            else:
                try:
                    after = manager.start(startup_failure=value['fault'] == 'startup-failure')
                except RuntimeError as error:
                    if value['fault'] != 'startup-failure':
                        raise
                    response.update(error=str(error), restartCleanup=deepcopy(manager.stop()))
                else:
                    response.update(status='ready', afterRuntime=after)
                    if value['leaseFault'] != 'none':
                        payload = {key: after[key] for key in ('identity', 'document', 'owner')}
                        payload.update(value['pendingOperation'], fault='expire' if value['leaseFault'] == 'expired' else 'takeover')
                        fault, _ = request_json(manager.identity['origin'], '/__facility-recovery__/lease-fault', manager.token, payload)
                        response['leaseFault'] = fault
        except BaseException as error:
            response.update(status='failed', error=str(error))
            write(self.directory / ('response-' + value['requestId'] + '.json'), response)
            self.response = response
            raise
        write(self.directory / ('response-' + value['requestId'] + '.json'), response)
        self.response = response
        return True


def validate_worker_report(value, case, mode, registry, *, before_runtime=None, restart_response=None):
    suffix = case.split('-', 1)[1]
    success = suffix == 'success'
    conflict = suffix in {'lease-expired', 'other-writer'}
    checks = REQUIRED_CHECKS | ({'exactUndoHistoryRestoration'} if success else {'failurePreservesDraftAndBlocksSave'})
    if (not isinstance(value, dict) or value.get('revision') != 'facility-managed-recovery-v1'
            or value.get('status') != 'passed' or value.get('case') != case
            or value.get('mode') != mode
            or type(value.get('saveRequests')) is not int or value['saveRequests'] != 0
            or not isinstance(value.get('checks'), dict) or set(value['checks']) != checks
            or any(result != 'passed' for result in value['checks'].values())):
        raise ValueError('Managed worker report does not prove the selected case and zero Save')
    for key in ('manualFrameHash', 'pendingFrameHash', 'expectedAfterFrameHash', 'afterFrameHash'):
        if not isinstance(value.get(key), str) or not re.fullmatch(r'[a-f0-9]{64}', value[key]):
            raise ValueError('Managed report does not retain exact editor-frame fingerprints')
    if (value.get('verifiedProposalTransitionOnly') is not True
            or value['expectedAfterFrameHash'] != value['afterFrameHash']
            or (not success and value['pendingFrameHash'] != value['afterFrameHash'])):
        raise ValueError('Managed restart changed draft/history/selection beyond verified transaction metadata')
    pending = value.get('pendingOperation', {})
    handle = value.get('retainedHandle', {}).get('handle', {})
    if (pending.get('kind') != case.split('-', 1)[0]
            or pending.get('holdPoint') != ('before-acknowledgment-dispatch' if conflict else 'after-backend-acknowledgment-before-client-reply')
            or any(not pending.get(key) or handle.get(key) != pending[key] for key in ('requestId', 'transactionId'))):
        raise ValueError('Managed report lost the pending request/transaction or used the wrong hold point')
    initial = value.get('beforeRuntime')
    restart = value.get('restart')
    if (not isinstance(initial, dict) or not isinstance(restart, dict)
            or restart.get('schemaVersion') != 1 or restart.get('beforeRuntime') != initial
            or restart.get('writeAuthority') is not False
            or (before_runtime is not None and initial != before_runtime)
            or (restart_response is not None and restart != restart_response)):
        raise ValueError('Managed report runtime/restart differs from supervisor evidence')
    lookup = value.get('reconciliationLookups')
    recovery = value.get('recovery', {})
    if not isinstance(lookup, list):
        raise ValueError('Managed report lacks durable transaction lookup evidence')
    if success or conflict:
        current = restart.get('afterRuntime', {})
        if restart.get('status') != 'ready' or not current.get('instanceId') or not current.get('processId'):
            raise ValueError('Managed restart did not verify its new owned process')
        same_runtime(initial, current, instance_id=current['instanceId'], process_id=current['processId'])
        if current['instanceId'] == initial.get('instanceId') or current['processId'] == initial.get('processId'):
            raise ValueError('Managed restart did not replace the process instance')
        diagnostics = lookup[0].get('lookupDiagnostics', {}) if len(lookup) == 1 and isinstance(lookup[0], dict) else {}
        if (diagnostics.get('instanceId') != current['instanceId'] or diagnostics.get('readOnly') is not True
                or diagnostics.get('registryReloaded') is not True or type(diagnostics.get('applicationDispatches')) is not int
                or diagnostics['applicationDispatches'] != 0):
            raise ValueError('Managed reconciliation did not perform exactly one read-only durable lookup')
        if conflict and (lookup[0].get('status') != ('lease_expired' if suffix == 'lease-expired' else 'ownership_conflict')
                or lookup[0].get('writeAuthority') is not False or lookup[0].get('recoveryRequired') is not True):
            raise ValueError('Lease conflict was not retained as explicit recovery without write authority')
    elif (lookup or restart.get('status') != ('identity-mismatch' if suffix == 'identity-mismatch' else 'failed')
          or restart.get('afterRuntime') is not None):
        raise ValueError('Failed or mismatched restart performed a private lookup or accepted a runtime')
    if recovery.get('status') != ('reconciled' if success else 'requires-recovery'):
        raise ValueError('Managed recovery outcome differs from the acceptance case')
    if not success:
        explicit = value.get('explicitRecovery', {})
        if any(explicit.get(key) is not True for key in ('required', 'handleRetained')) or explicit.get('writeAuthority') is not False:
            raise ValueError('Managed failure did not retain its recovery handle and deny write authority')
    calls = registry.get('calls')
    if (not isinstance(calls, dict) or not calls or value.get('transactionCalls') != calls
            or any(type(count) is not int or count != 1 for count in calls.values())
            or type(registry.get('deniedSaveCalls')) is not int or registry['deniedSaveCalls'] != 0):
        raise ValueError('Durable endpoint registry does not prove one execution and zero Save calls')
    layout_id = initial.get('document', {}).get('documentId')
    if not isinstance(layout_id, str) or not re.fullmatch(r'fl-[A-Za-z0-9._-]+', layout_id):
        raise ValueError('Managed report document identity is invalid')
    prefix = '/api/facility-layout-design/site-local/' + layout_id
    pattern = re.compile(re.escape(prefix) + r'/(?:proposals/[A-Za-z0-9_-]+/(apply/prepare)|transactions/[A-Za-z0-9_-]+/(apply/commit|apply/acknowledge|undo/prepare|undo/acknowledge))')
    counted = {}
    for route in calls:
        match = pattern.fullmatch(route)
        if not match:
            raise ValueError('Durable registry contains an unexpected transaction route')
        step = next(part for part in match.groups() if part)
        counted[step] = counted.get(step, 0) + 1
    expected = {'apply/prepare': 1, 'apply/commit': 1}
    if not (case.startswith('apply-') and conflict):
        expected['apply/acknowledge'] = 1
    if success or case.startswith('undo-'):
        expected['undo/prepare'] = 1
        if not conflict:
            expected['undo/acknowledge'] = 1
    if counted != expected:
        raise ValueError('Durable registry is missing the expected transaction sequence')
    return value


def run_worker(command, output, control, env, timeout=300):
    worker = None
    record = {'reader': None, 'pipe': None}
    result = {'status': 'starting', 'terminationConfirmed': False}
    error = None
    (output / 'worker.log').touch()
    try:
        write(output / 'worker-result.json', result)
        worker = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **render.spawn_options())
        record['stream'] = worker.stdout
        result['pid'] = worker.pid
        record['reader'], record['pipe'] = render.start_pipe_capture(worker.stdout, output / 'worker.log')
        deadline = time.monotonic() + timeout
        while worker.poll() is None:
            if time.monotonic() >= deadline:
                raise RuntimeError('Managed recovery worker exceeded its deadline')
            control.poll()
            time.sleep(0.05)
        control.poll()  # A completed worker cannot smuggle a changed control request.
        if worker.returncode != 0:
            raise RuntimeError('Managed recovery worker failed with exit code ' + str(worker.returncode))
        if control.response is None:
            raise RuntimeError('Worker never exercised owned-backend restart')
        result['status'] = 'passed'
    except BaseException as caught:
        error = caught
        result.update(status='failed', error=str(caught))
    finally:
        try:
            if worker is not None:
                stop_owned_process(worker)
                result.update(exitCode=worker.poll(), terminationConfirmed=True)
                result.update(finish_pipe(record))
                if not result.get('stdioClosed') or not result.get('stdioEOFVerified') or result.get('logError'):
                    raise RuntimeError('Worker termination or diagnostic EOF/closure was not confirmed')
        except BaseException as caught:
            error = error or caught
            result.update(status='failed', cleanupError=str(caught))
        prior.final_write(output / 'worker-result.json', result, error)
    if error:
        raise error
    return result


def execute(args):
    data, output = base.no_links(args.data_root), base.no_links(args.output)
    manifest = json.loads((data / 'facility-recovery-fixture.json').read_text())
    identity = manifest['identity']
    if args.port != int(identity['origin'].rsplit(':', 1)[1]):
        raise ValueError('Port differs from prepared fixture')
    library, identity = base.prepare_fixture(ROOT, data, identity['profileId'], args.port)
    for name in ('recovery-harness-requests.json', 'facility-managed-check.json', 'facility-recovery-test-token.txt'):
        if (data / name).exists():
            raise ValueError('Use a freshly prepared isolated fixture for each managed restart case')
    output.mkdir(parents=True, exist_ok=False)
    source = Path(manifest['source']['root']) / manifest['source']['layoutRelativePath']
    isolated = data / manifest['layout']['relativePath']
    before = {'source': render.file_hash(source), 'isolated': render.file_hash(isolated)}
    if before['source'] != before['isolated'] or before['source'] != manifest['layout']['revision']:
        raise ValueError('Manual layout provenance mismatch')
    token_path = data / 'facility-recovery-test-token.txt'
    with token_path.open('x', encoding='ascii') as stream:
        stream.write(secrets.token_hex(32)); stream.flush(); os.fsync(stream.fileno())
    manager = BackendSupervisor(data, output, identity, library, token_path)
    control = None
    unrelated = None
    report = {'revision': 'facility-managed-recovery-v1', 'case': args.case, 'mode': args.mode,
              'status': 'starting', 'startedAt': render.now(), 'manualLayoutHashesBefore': before,
              'editingScope': 'explicit isolated managed-recovery harness only', 'researchBrowsing': False}
    primary = None
    try:
        write(output / 'check.json', report)
        unrelated = Sentinel(output / 'unrelated-server', identity)
        report['beforeRuntime'] = manager.start()
        control = RestartControl(manager, output / 'control', args.case)
        config = {'dataRoot': str(data), 'output': str(output), 'origin': identity['origin'],
                  'tokenFile': str(token_path), 'mode': args.mode, 'case': args.case,
                  'controlDirectory': str(control.directory)}
        config_path = data / 'facility-managed-check.json'
        write(config_path, config)
        if args.mode == 'native':
            binary = render.resolve_electron()
            executable = binary['executable']
            report['electron'] = binary
            if render.file_hash(Path(executable)) != binary['sha256']:
                raise ValueError('Pinned Electron executable changed before managed recovery')
        else:
            executable = shutil.which('node')
            if not executable:
                raise RuntimeError('Installed Node runtime required')
        entry = Path(__file__).with_name('facility-managed-recovery-' + args.mode + '.cjs')
        worker_env = dict(os.environ)
        worker_env.update(INSPECTORPRO_FACILITY_RECOVERY_HARNESS='1', INSPECTORPRO_FACILITY_MANAGED_RESTART_HARNESS='1')
        for name in ('ELECTRON_RUN_AS_NODE', 'ELECTRON_OVERRIDE_DIST_PATH', 'NODE_OPTIONS'):
            worker_env.pop(name, None)
        report['worker'] = run_worker([executable, str(entry), str(config_path)], output, control, worker_env)
        registry = json.loads((data / 'recovery-harness-requests.json').read_text())
        stage_path = output / 'report.json'
        if not stage_path.is_file() or stage_path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('Managed worker report missing or oversized')
        worker_report = validate_worker_report(json.loads(stage_path.read_text()), args.case, args.mode, registry,
            before_runtime=manager.initial_runtime, restart_response=control.response)
        report.update(status='passed', checks=worker_report['checks'], saveRequests=0,
                      transactionCalls=registry['calls'], restart=control.response)
        return report
    except BaseException as error:
        primary = error
        report.update(status='failed', error=str(error))
        raise
    finally:
        cleanup_errors = []
        for label, sentinel in (('unrelatedServer', unrelated), ('mismatchedServer', control.sentinel if control else None)):
            if sentinel:
                try:
                    report[label] = sentinel.assert_survived()
                except BaseException as error:
                    cleanup_errors.append(str(error))
                finally:
                    try:
                        sentinel.close()
                    except BaseException as error:
                        cleanup_errors.append(str(error))
        try:
            manager.close()
        except BaseException as error:
            cleanup_errors.append(str(error))
        report['backends'] = [record['evidence'] for record in manager.records]
        if control:
            report['restart'] = control.response
        try:
            after = {'source': render.file_hash(source), 'isolated': render.file_hash(isolated)}
            report.update(manualLayoutHashesAfter=after, manualLayoutUnchanged=before == after)
            if before != after:
                raise RuntimeError('Manual layout bytes changed')
            registry_path = data / 'recovery-harness-requests.json'
            if registry_path.exists():
                registry = json.loads(registry_path.read_text())
                report['durableEndpointEvidence'] = {'calls': registry['calls'], 'deniedSaveCalls': registry['deniedSaveCalls']}
                if registry['deniedSaveCalls'] != 0 or any(count != 1 for count in registry['calls'].values()):
                    raise RuntimeError('Durable registry recorded a Save or repeated transaction endpoint')
        except BaseException as error:
            cleanup_errors.append(str(error))
        if cleanup_errors:
            report.update(status='failed', cleanupErrors=cleanup_errors)
        report['finishedAt'] = render.now()
        final_error = primary or (RuntimeError('; '.join(cleanup_errors)) if cleanup_errors else None)
        prior.final_write(output / 'check.json', report, final_error)
        if primary is None and final_error:
            raise final_error


def main():
    if sys.argv[1:2] == ['--sentinel']:
        sentinel_main(sys.argv[2:])
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--mode', choices=('engine', 'native'), default='engine')
    parser.add_argument('--case', choices=CASES, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    try:
        report = execute(args)
        print(json.dumps({'status': report['status'], 'case': args.case, 'mode': args.mode, 'output': str(args.output)}))
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
