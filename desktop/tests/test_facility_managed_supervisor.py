"""Managed supervisor boundaries; no real application, backend, or GUI launch."""
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch
import uuid

SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'run-facility-managed-recovery.py'
spec = importlib.util.spec_from_file_location('managed_facility_supervisor_tests', SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def identity():
    return {'schemaVersion': 1, 'product': 'InspectorPro', 'mode': 'rendering-spike',
            'backendId': str(uuid.uuid4()), 'storeId': str(uuid.uuid4()), 'profileId': 'test-profile',
            'researchBrowsing': False, 'interactive': False, 'origin': 'http://127.0.0.1:8199'}


def runtime(public, instance=None, pid=123):
    return {'identity': {key: public[key] for key in ('backendId', 'storeId')} | {'principalId': 'local'},
            'document': {'tenantId': 'local', 'siteId': 'site-local', 'documentId': 'fl-test'},
            'owner': {'sessionId': 's-test', 'ownerId': 'o-test'},
            'origin': public['origin'], 'instanceId': instance or str(uuid.uuid4()),
            'processId': pid, 'mode': 'facility-managed-backend-recovery-test'}


def control_request(case='apply-success'):
    suffix = case.split('-', 1)[1]
    return {'schemaVersion': 1, 'requestId': 'control-1', 'action': 'restart',
            'fault': {'failed-restart': 'startup-failure', 'identity-mismatch': 'identity-mismatch'}.get(suffix, 'none'),
            'leaseFault': {'lease-expired': 'expired', 'other-writer': 'other-writer'}.get(suffix, 'none'),
            'pendingOperation': {'requestId': 'operation-1', 'transactionId': 'transaction-1'}}


class ManagedSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.public = identity()
        self.before = runtime(self.public)
        self.after = runtime(self.public, pid=456)

    def tearDown(self):
        self.temp.cleanup()

    def supervisor(self):
        token = self.root / 'token.txt'
        token.write_text('secret-fixture-token')
        return runner.BackendSupervisor(self.root, self.root, self.public, self.root, token)

    def fake_manager(self):
        return SimpleNamespace(identity=self.public, token='secret-fixture-token',
            initial_runtime=self.before, stop=Mock(return_value={'terminationConfirmed': True, 'resourceCleanupVerified': True}),
            start=Mock(return_value=self.after))

    def store(self, control, value):
        runner.write(control.directory / 'request.json', value)

    def test_all_ten_bounded_cases_are_available(self):
        self.assertEqual(len(runner.CASES), 10)
        for case in runner.CASES:
            self.assertEqual(runner.validate_control(control_request(case), case), control_request(case))

    def test_public_mismatch_never_sends_fixture_credential(self):
        wrong = runner.base.public_identity(self.public) | {'storeId': str(uuid.uuid4())}
        with patch.object(runner, 'request_json', return_value=(wrong, {})) as request:
            with self.assertRaisesRegex(ValueError, 'no credential'):
                runner.verified_runtime(self.public, self.before['instanceId'], 123, 'secret-fixture-token')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args, (self.public['origin'], runner.base.IDENTITY_PATH))

    def test_correct_public_identity_with_wrong_instance_never_sends_credential(self):
        public = runner.base.public_identity(self.public)
        with patch.object(runner, 'request_json', return_value=(public, {'X-InspectorPro-Rendering-Instance': 'old-instance'})) as request:
            with self.assertRaises(ValueError):
                runner.verified_runtime(self.public, self.before['instanceId'], 123, 'secret')
        self.assertEqual(request.call_count, 1)

    def test_credential_requests_never_follow_http_redirect(self):
        parent = Mock()
        redirect = runner.NoRedirect()
        redirect.add_parent(parent)
        request = urllib.request.Request('http://127.0.0.1:8199' + runner.RUNTIME_PATH,
            headers={'X-InspectorPro-Recovery-Test': 'secret'})
        response = io.BytesIO(b'redirect')
        with self.assertRaisesRegex(urllib.error.HTTPError, 'may not redirect') as caught:
            redirect.http_error_302(request, response, 302, 'Found', {'location': 'http://127.0.0.1:8999/foreign'})
        parent.open.assert_not_called()
        caught.exception.close()
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(request.full_url, 302, 'redirect denied', {}, io.BytesIO())
        with patch.object(runner.urllib.request, 'build_opener', return_value=opener) as build:
            with self.assertRaises(urllib.error.HTTPError):
                runner.request_json('http://127.0.0.1:8199', runner.RUNTIME_PATH, 'secret')
        self.assertTrue(any(isinstance(item, runner.NoRedirect) for item in build.call_args.args))
        self.assertEqual(opener.open.call_count, 1)

    def test_private_runtime_follows_public_check_and_requires_owned_process(self):
        replies = [(runner.base.public_identity(self.public), {'X-InspectorPro-Rendering-Instance': self.after['instanceId']}),
                   (self.after, {})]
        with patch.object(runner, 'request_json', side_effect=replies) as request:
            actual = runner.verified_runtime(self.public, self.after['instanceId'], 456, 'secret', self.before)
        self.assertEqual(actual, self.after)
        self.assertEqual(request.call_args_list[1].args, (self.public['origin'], runner.RUNTIME_PATH, 'secret'))
        with self.assertRaises(ValueError):
            runner.same_runtime(self.before, self.after, instance_id=self.after['instanceId'], process_id=999)

    def test_logical_identity_document_owner_and_origin_cannot_change(self):
        for key in ('identity', 'document', 'owner', 'origin'):
            broken = deepcopy(self.after)
            broken[key] = {} if isinstance(broken[key], dict) else 'http://127.0.0.1:9999'
            with self.subTest(key=key), self.assertRaises(ValueError):
                runner.same_runtime(self.before, broken, instance_id=self.after['instanceId'], process_id=456)

    def test_supervisor_refuses_unowned_handle_even_with_same_pid_or_equal_record(self):
        manager = self.supervisor()
        owned = {'process': Mock(pid=123)}
        manager.records.append(owned)
        for foreign in ({'process': Mock(pid=123)}, dict(owned)):
            with self.subTest(foreign=foreign), patch.object(runner, 'stop_owned_process') as stop:
                with self.assertRaisesRegex(ValueError, 'not created'):
                    manager.stop(foreign)
                stop.assert_not_called()

    def test_owned_stop_checks_matching_receipt_and_never_touches_unrelated_handle(self):
        manager = self.supervisor()
        child, unrelated = Mock(pid=123), Mock(pid=456)
        child.poll.return_value = 0
        instance = str(uuid.uuid4())
        record = {'process': child, 'instanceId': instance, 'folder': self.root,
                  'evidence': {}, 'startupFailureInjected': False}
        manager.records.append(record)
        receipt_path = runner.base.shutdown_receipt_path(self.root, instance)
        runner.write(receipt_path, {'schemaVersion': 1, 'instanceId': instance,
            'status': 'lifespan-stopped', 'resourcesClosed': True})
        with patch.object(runner, 'stop_owned_process') as stop, patch.object(runner, 'finish_pipe',
                return_value={'stdioEOFVerified': True, 'stdioClosed': True}):
            result = manager.stop(record)
        stop.assert_called_once_with(child, graceful=True)
        self.assertTrue(result['terminationConfirmed'])
        self.assertTrue(result['resourceCleanupVerified'])
        unrelated.assert_not_called()
        self.assertEqual(unrelated.mock_calls, [])

    def test_missing_receipt_cannot_claim_graceful_resource_cleanup(self):
        manager = self.supervisor()
        child = Mock()
        child.poll.return_value = 0
        record = {'process': child, 'instanceId': str(uuid.uuid4()), 'folder': self.root,
                  'evidence': {}, 'startupFailureInjected': False}
        manager.records.append(record)
        with patch.object(runner, 'stop_owned_process'), patch.object(runner, 'finish_pipe',
                return_value={'stdioEOFVerified': True, 'stdioClosed': True}):
            with self.assertRaisesRegex(RuntimeError, 'receipt'):
                manager.stop(record)
        self.assertTrue(record['evidence']['terminationConfirmed'])
        self.assertNotEqual(record['evidence'].get('resourceCleanupVerified'), True)

    def start_with_diagnostic_fixture(self, manager, ready_error=None):
        child = Mock(pid=123)
        child.poll.return_value = None

        def spawn(*args, **kwargs):
            event = {'schemaVersion': 1, 'pid': child.pid, 'timeUnixMs': 1234,
                     'instanceId': kwargs['env']['INSPECTORPRO_DESKTOP_INSTANCE_ID'],
                     'phase': 'application-lifespan-startup-completed', 'sequence': 1, 'elapsedMs': 1200}
            child.stdout = io.BytesIO(runner.render.BACKEND_CHECKPOINT_PREFIX + json.dumps(event).encode() + b'\n')
            return child

        def capture(stream, log):
            log.write_bytes(stream.getvalue())
            reader = Mock()
            reader.is_alive.return_value = False
            return reader, {'eof': True, 'closed': True}

        manager.process_factory = spawn
        with patch.object(runner.base, 'child_environment', return_value={}), \
             patch.object(runner.render, 'start_pipe_capture', side_effect=capture), \
             patch.object(runner.base, 'wait_ready', side_effect=ready_error) as wait, \
             patch.object(runner, 'verified_runtime', side_effect=lambda public, instance, pid, *rest: runtime(public, instance, pid)) as verify:
            if ready_error:
                with self.assertRaises(type(ready_error)) as caught:
                    manager.start()
                self.assertIs(caught.exception, ready_error)
                verify.assert_not_called()
            else:
                manager.start()
                verify.assert_called_once()
        wait.assert_called_once_with(child, self.public, 45, manager.current['instanceId'])
        return manager.current

    def test_startup_timeout_retains_phase_and_timing_without_granting_readiness_or_cleanup(self):
        manager = self.supervisor()
        record = self.start_with_diagnostic_fixture(manager, RuntimeError('original readiness timeout'))
        evidence = json.loads((record['folder'] / 'result.json').read_text())
        self.assertEqual(evidence['startupStage'], 'public-readiness')
        self.assertEqual(evidence['startupTimeoutSeconds'], 45)
        self.assertGreaterEqual(evidence['startupElapsedMs'], evidence['spawnDurationMs'])
        self.assertGreaterEqual(evidence['readinessWaitElapsedMs'], 0)
        self.assertEqual(evidence['startupDiagnosticsAtFailure']['lastCheckpoint']['phase'], 'application-lifespan-startup-completed')
        self.assertFalse(evidence['applicationStarted'])
        self.assertFalse(evidence['resourceCleanupVerified'])
        record['process'].poll.return_value = 0
        with patch.object(runner, 'stop_owned_process'):
            with self.assertRaisesRegex(RuntimeError, 'receipt'):
                manager.stop(record)
        self.assertEqual(record['evidence']['error'], 'original readiness timeout')
        self.assertFalse(record['evidence']['resourceCleanupVerified'])
        self.assertEqual(record['evidence']['startupDiagnostics']['checkpointCountInTail'], 1)

    def test_verified_startup_records_observed_timings_without_replacing_runtime_check(self):
        manager = self.supervisor()
        record = self.start_with_diagnostic_fixture(manager)
        evidence = record['evidence']
        self.assertEqual(evidence['status'], 'ready')
        self.assertEqual(evidence['startupStage'], 'ready')
        self.assertTrue(evidence['applicationStarted'])
        for key in ('spawnRequestedAt', 'spawnReturnedAt', 'readinessWaitStartedAt', 'publicReadinessVerifiedAt', 'runtimeVerifiedAt'):
            self.assertTrue(evidence[key])
        self.assertEqual(evidence['startupDiagnosticsAtReadiness']['lastCheckpoint']['instanceId'], record['instanceId'])
        self.assertFalse(evidence['resourceCleanupVerified'])

    def test_diagnostic_projection_failure_does_not_replace_startup_failure(self):
        manager = self.supervisor()
        with patch.object(runner.render, 'backend_startup_evidence', side_effect=OSError('private diagnostic detail')):
            record = self.start_with_diagnostic_fixture(manager, RuntimeError('original readiness timeout'))
        self.assertEqual(record['evidence']['error'], 'original readiness timeout')
        self.assertEqual(record['evidence']['startupDiagnosticsAtFailure'],
                         {'revision': 'backend-startup-v1', 'readErrorType': 'OSError'})

    def test_injected_prestart_exit_has_no_fabricated_application_cleanup_receipt(self):
        manager = self.supervisor()
        child = Mock()
        child.poll.return_value = 73
        record = {'process': child, 'instanceId': str(uuid.uuid4()), 'folder': self.root,
                  'evidence': {}, 'startupFailureInjected': True}
        manager.records.append(record)
        with patch.object(runner, 'stop_owned_process') as stop, patch.object(runner, 'finish_pipe',
                return_value={'stdioEOFVerified': True, 'stdioClosed': True}):
            evidence = manager.stop(record)
        stop.assert_called_once_with(child, graceful=False)
        self.assertTrue(evidence['terminationConfirmed'])
        self.assertNotEqual(evidence.get('resourceCleanupVerified'), True)
        self.assertIn('before application import', evidence['resourceCleanupNotApplicable'])

    def test_reader_setup_failure_closes_only_untouched_pipe_without_claiming_eof(self):
        stream = io.BytesIO(b'unread log')
        result = runner.finish_pipe({'reader': None, 'pipe': None, 'stream': stream})
        self.assertTrue(stream.closed)
        self.assertEqual(result, {'stdioEOFVerified': False, 'stdioClosed': False})

    def test_stale_control_directory_and_mutated_or_second_request_are_rejected(self):
        path = self.root / 'control'
        path.mkdir()
        with self.assertRaisesRegex(ValueError, 'stale'):
            runner.RestartControl(self.fake_manager(), path, 'apply-success')
        control = runner.RestartControl(self.fake_manager(), self.root / 'new-control', 'apply-success')
        request = control_request()
        self.store(control, request)
        self.assertTrue(control.poll())
        self.assertFalse(control.poll())
        control.supervisor.start.assert_called_once()
        request['requestId'] = 'control-2'
        self.store(control, request)
        with self.assertRaisesRegex(ValueError, 'one immutable'):
            control.poll()
        control.supervisor.start.assert_called_once()

    def test_wrong_case_invalid_path_and_pending_identity_are_rejected_before_shutdown(self):
        control = runner.RestartControl(self.fake_manager(), self.root / 'control', 'apply-success')
        mutations = [lambda r: r.update(fault='startup-failure'), lambda r: r.update(requestId='../escape'),
                     lambda r: r.update(pendingOperation={}), lambda r: r.update(schemaVersion=True),
                     lambda r: r.update(extra='unexpected')]
        for mutate in mutations:
            request = control_request()
            mutate(request)
            self.store(control, request)
            with self.subTest(request=request), self.assertRaises(ValueError):
                control.poll()
        control.supervisor.stop.assert_not_called()

    def test_failed_restart_returns_failed_without_granting_authority_or_touching_server(self):
        manager = self.fake_manager()
        manager.start.side_effect = RuntimeError('Injected managed backend restart failed before application startup')
        control = runner.RestartControl(manager, self.root / 'control', 'apply-failed-restart')
        self.store(control, control_request('apply-failed-restart'))
        with patch.object(runner, 'request_json') as request, patch.object(runner, 'Sentinel') as sentinel:
            self.assertTrue(control.poll())
        self.assertEqual(control.response['status'], 'failed')
        self.assertFalse(control.response['writeAuthority'])
        self.assertNotIn('afterRuntime', control.response)
        request.assert_not_called()
        sentinel.assert_not_called()
        manager.start.assert_called_once_with(startup_failure=True)

    def test_identity_mismatch_retains_sentinel_and_never_enrolls_or_stops_it(self):
        manager = self.fake_manager()
        control = runner.RestartControl(manager, self.root / 'control', 'undo-identity-mismatch')
        self.store(control, control_request('undo-identity-mismatch'))
        fake_sentinel = Mock(spec=['assert_survived', 'close'])
        fake_sentinel.assert_survived.return_value = {'survivedRecovery': True, 'credentialRequests': 0}
        with patch.object(runner, 'Sentinel', return_value=fake_sentinel), patch.object(runner, 'verified_runtime',
                side_effect=ValueError('Public backend identity mismatch; no credential was sent')):
            control.poll()
        self.assertEqual(control.response['status'], 'identity-mismatch')
        self.assertFalse(control.response['writeAuthority'])
        manager.start.assert_not_called()
        manager.stop.assert_called_once_with()
        fake_sentinel.close.assert_not_called()
        fake_sentinel.assert_survived.assert_called_once()

    def test_lease_fault_is_sent_only_after_verified_restart_with_exact_pending_identity(self):
        manager = self.fake_manager()
        control = runner.RestartControl(manager, self.root / 'control', 'undo-other-writer')
        self.store(control, control_request('undo-other-writer'))
        with patch.object(runner, 'request_json', return_value=({'fault': 'takeover', 'writeAuthority': False}, {})) as request:
            control.poll()
        payload = request.call_args.args[3]
        self.assertEqual(payload['requestId'], 'operation-1')
        self.assertEqual(payload['transactionId'], 'transaction-1')
        self.assertEqual(payload['fault'], 'takeover')
        for key in ('identity', 'document', 'owner'):
            self.assertEqual(payload[key], self.after[key])
        self.assertEqual(control.response['status'], 'ready')
        self.assertFalse(control.response['writeAuthority'])

    def test_duplicate_execution_save_and_worker_registry_disagreement_fail_acceptance(self):
        prefix = '/api/facility-layout-design/site-local/fl-test'
        calls = {prefix + '/proposals/p-test/apply/prepare': 1}
        calls.update({prefix + '/transactions/t-test/' + step: 1
                      for step in ('apply/commit', 'apply/acknowledge', 'undo/prepare', 'undo/acknowledge')})
        registry = {'calls': calls, 'deniedSaveCalls': 0}
        report = {'revision': 'facility-managed-recovery-v1', 'status': 'passed', 'case': 'apply-success',
                  'mode': 'engine', 'checks': dict.fromkeys(runner.REQUIRED_CHECKS | {'exactUndoHistoryRestoration'}, 'passed'),
                  'saveRequests': 0, 'transactionCalls': registry['calls'],
                  'manualFrameHash': 'a' * 64, 'pendingFrameHash': 'b' * 64, 'afterFrameHash': 'c' * 64,
                  'expectedAfterFrameHash': 'c' * 64, 'verifiedProposalTransitionOnly': True,
                  'pendingOperation': {'kind': 'apply', 'requestId': 'op-1', 'transactionId': 't-test',
                      'holdPoint': 'after-backend-acknowledgment-before-client-reply'},
                  'retainedHandle': {'handle': {'requestId': 'op-1', 'transactionId': 't-test'}},
                  'beforeRuntime': self.before,
                  'restart': {'schemaVersion': 1, 'requestId': 'control-1', 'beforeRuntime': self.before,
                              'afterRuntime': self.after, 'status': 'ready', 'writeAuthority': False},
                  'reconciliationLookups': [{'lookupDiagnostics': {'instanceId': self.after['instanceId'],
                       'readOnly': True, 'registryReloaded': True, 'applicationDispatches': 0}}],
                  'recovery': {'status': 'reconciled'}}
        runner.validate_worker_report(report, 'apply-success', 'engine', registry)
        for broken in ({'calls': {'/transaction/endpoint': 2}, 'deniedSaveCalls': 0},
                       {'calls': {'/transaction/endpoint': 1}, 'deniedSaveCalls': 1},
                       {'calls': {'/other/endpoint': 1}, 'deniedSaveCalls': 0}):
            with self.subTest(registry=broken), self.assertRaises(ValueError):
                runner.validate_worker_report(report, 'apply-success', 'engine', broken)
        for change in (lambda r: r.update(afterFrameHash='d' * 64),
                       lambda r: r.update(mode='native'),
                       lambda r: r['checks'].pop('exactUndoHistoryRestoration'),
                       lambda r: r.update(reconciliationLookups=[]),
                       lambda r: r['restart']['afterRuntime'].update(instanceId=self.before['instanceId'])):
            broken = deepcopy(report)
            change(broken)
            with self.subTest(report=broken), self.assertRaises(ValueError):
                runner.validate_worker_report(broken, 'apply-success', 'engine', registry)


if __name__ == '__main__':
    unittest.main()
