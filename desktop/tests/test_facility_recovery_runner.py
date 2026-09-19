"""Owned-process and report gates only; these tests launch no child or GUI."""
import copy
from contextlib import ExitStack
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import urllib.error
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'run-facility-recovery-check.py'
spec = importlib.util.spec_from_file_location('facility_recovery_runner', SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def passing_report(phase=1, mode='engine'):
    prefix = '/api/facility-layout-design/site-local/fl-test'
    calls = {}
    for number in (1, 2):
        calls[prefix + f'/proposals/p-{number}/apply/prepare'] = 1
        for step in ('commit', 'acknowledge'):
            calls[prefix + f'/transactions/t-{number}/apply/{step}'] = 1
    for number in range(1, phase + 1):
        for step in ('prepare', 'acknowledge'):
            calls[prefix + f'/transactions/t-{number}/undo/{step}'] = 1
    checks = set(runner.PHASE_CHECKS[phase])
    if mode == 'native' and phase == 1:
        checks.add('loadedAssets')
    return {'revision': 'facility-recovery-acceptance-v1', 'status': 'passed', 'phase': phase,
            'mode': runner.MODES[mode], 'checks': dict.fromkeys(checks, 'passed'),
            'saveRequests': 0, 'transactionCalls': calls}


class Child:
    def __init__(self, events, *, exit_code=0, timeout=False, kill_failure=False):
        self.pid = 4242
        self.stdout = io.BytesIO(b'worker output\n')
        self.returncode = None
        self.exit_code = exit_code
        self.timeout = timeout
        self.kill_failure = kill_failure
        self.events = events
        self.stopping = False

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.events.append(('wait', timeout))
        if self.timeout and (not self.stopping or self.kill_failure):
            raise subprocess.TimeoutExpired('owned-worker', timeout)
        self.returncode = self.exit_code
        return self.returncode

    def terminate(self):
        self.events.append('terminate')
        self.stopping = True

    def kill(self):
        self.events.append('kill')
        if self.kill_failure:
            raise OSError('owned kill failed')
        self.returncode = -9


class Reader:
    def __init__(self, events, alive=False):
        self.events = events
        self.alive = alive

    def join(self, timeout):
        self.events.append(('join', timeout))

    def is_alive(self):
        return self.alive


class FacilityRecoveryRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.stage = self.directory / 'phase-1'
        self.stage.mkdir()
        self.events = []
        self.child = Child(self.events)
        self.reader = Reader(self.events)
        self.pipe = {'eof': True, 'closed': True, 'error': None}
        self.report = passing_report()
        self.store_report()

    def tearDown(self):
        self.temp.cleanup()

    def store_report(self):
        (self.stage / 'report.json').write_text(json.dumps(self.report), encoding='utf-8')

    def run_stage(self, factory=None):
        return runner.run_worker_stage(['fake-runtime', 'entry', 'config'], self.stage,
            env={}, phase=1, mode='engine', layout_id='fl-test',
            process_factory=factory or Mock(return_value=self.child), timeout=0.01, drain_timeout=0)

    def receipt(self, stage=None):
        return json.loads(((stage or self.stage) / 'process-result.json').read_text())

    def test_report_requires_exact_phase_mode_checks_and_transaction_inventory(self):
        self.assertIs(runner.validate_stage_report(self.report, 1, 'engine', 'fl-test'), self.report)
        for change in (
            lambda r: r.update(phase=2), lambda r: r.update(mode=runner.MODES['native']),
            lambda r: r.update(checks={}), lambda r: r['checks'].pop('closeDuringPendingUndo'),
            lambda r: r.update(saveRequests=1), lambda r: r.update(saveRequests=False),
            lambda r: r.update(transactionCalls={}),
            lambda r: r['transactionCalls'].pop(next(iter(r['transactionCalls']))),
            lambda r: r['transactionCalls'].update({next(iter(r['transactionCalls'])): 2}),
            lambda r: r['transactionCalls'].update({'/foreign/transaction': 1}),
        ):
            broken = copy.deepcopy(self.report)
            change(broken)
            with self.subTest(report=broken), self.assertRaises(ValueError):
                runner.validate_stage_report(broken, 1, 'engine', 'fl-test')
        native = passing_report(mode='native')
        native['checks'].pop('loadedAssets')
        with self.assertRaises(ValueError):
            runner.validate_stage_report(native, 1, 'native', 'fl-test')

    def test_phase_two_must_preserve_every_prior_endpoint(self):
        second = passing_report(phase=2)
        runner.validate_stage_report(second, 2, 'engine', 'fl-test', self.report['transactionCalls'])
        key = next(key for key in second['transactionCalls'] if '/proposals/' in key)
        second['transactionCalls'][key.replace('/p-1/', '/replacement/')] = second['transactionCalls'].pop(key)
        with self.assertRaises(ValueError):
            runner.validate_stage_report(second, 2, 'engine', 'fl-test', self.report['transactionCalls'])

    def test_success_requires_owned_exit_and_drained_closed_error_free_pipe(self):
        with patch.object(runner.render, 'start_pipe_capture', return_value=(self.reader, self.pipe)):
            result, report = self.run_stage()
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['terminationConfirmed'])
        self.assertTrue(result['stdioEOFVerified'])
        self.assertTrue(result['stdioClosed'])
        self.assertFalse(result['descendantTerminationVerified'])
        self.assertEqual(report, self.report)
        self.assertEqual(self.events, [('wait', 0.01), ('join', 0)])

    def test_eof_without_pipe_close_or_successful_log_persistence_cannot_pass(self):
        for changes, alive in (({'closed': False}, False), ({'error': 'fsync failed'}, False), ({'eof': False}, False), ({}, True)):
            self.child = Child(self.events)
            pipe = dict(self.pipe, **changes)
            reader = Reader(self.events, alive=alive)
            with self.subTest(changes=changes, alive=alive), patch.object(runner.render, 'start_pipe_capture', return_value=(reader, pipe)):
                with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
                    self.run_stage()
                self.assertEqual(self.receipt()['status'], 'failed')

    def test_pipe_setup_failure_stops_owned_worker_and_closes_only_untouched_read_handle(self):
        with patch.object(runner.render, 'start_pipe_capture', side_effect=RuntimeError('reader setup failed')):
            with self.assertRaisesRegex(RuntimeError, 'reader setup failed'):
                self.run_stage()
        self.assertIn('terminate', self.events)
        self.assertTrue(self.child.stdout.closed)
        self.assertTrue(self.receipt()['terminationConfirmed'])
        self.assertFalse(self.receipt()['stdioEOFVerified'])

    def test_phase_two_spawn_failure_never_reuses_phase_one_eof(self):
        with patch.object(runner.render, 'start_pipe_capture', return_value=(self.reader, self.pipe)) as capture:
            self.run_stage()
            second = self.directory / 'phase-2'
            second.mkdir()
            with self.assertRaisesRegex(OSError, 'spawn refused'):
                runner.run_worker_stage(['fake'], second, env={}, phase=2, mode='engine', layout_id='fl-test',
                    process_factory=Mock(side_effect=OSError('spawn refused')))
            self.assertEqual(capture.call_count, 1)
        self.assertEqual(self.receipt(second)['status'], 'spawn-error')
        self.assertFalse(self.receipt(second)['stdioEOFVerified'])
        self.assertFalse(self.receipt(second)['terminationConfirmed'])

    def test_timeout_retains_deadline_error_after_bounded_owned_cleanup_failure(self):
        self.child = Child(self.events, timeout=True, kill_failure=True)
        pipe = {'eof': False, 'closed': False, 'error': None}
        with patch.object(runner.render, 'start_pipe_capture', return_value=(self.reader, pipe)):
            with self.assertRaisesRegex(RuntimeError, 'deadline') as caught:
                self.run_stage()
        result = caught.exception.facility_process_result
        self.assertEqual(result['status'], 'timed-out')
        self.assertIn('owned kill failed', result['cleanupError'])
        self.assertFalse(result['terminationConfirmed'])
        self.assertIn(('join', 0), self.events)
        self.assertEqual(self.events.count('terminate'), 1)
        self.assertEqual(self.events.count('kill'), 1)

    def test_nonzero_exit_is_recorded_after_drain(self):
        self.child = Child(self.events, exit_code=17)
        with patch.object(runner.render, 'start_pipe_capture', return_value=(self.reader, self.pipe)):
            with self.assertRaisesRegex(RuntimeError, 'exit code 17'):
                self.run_stage()
        result = self.receipt()
        self.assertEqual(result['code'], 17)
        self.assertTrue(result['stdioClosed'])
        self.assertEqual(result['status'], 'failed')

    def test_final_replace_failure_preserves_primary_and_writes_unique_diagnostics(self):
        self.child = Child(self.events, exit_code=17)
        original = runner.write
        def write(target, value):
            if target.name == 'process-result.json' and value.get('finishedAt'):
                raise PermissionError('report target is held by a reader')
            original(target, value)
        with patch.object(runner, 'write', side_effect=write), patch.object(runner.render, 'start_pipe_capture', return_value=(self.reader, self.pipe)):
            with self.assertRaisesRegex(RuntimeError, 'exit code 17'):
                self.run_stage()
        diagnostics = list(self.stage.glob('process-result.final-diagnostic-*.json'))
        self.assertEqual(len(diagnostics), 1)
        receipt = json.loads(diagnostics[0].read_text())
        self.assertIn('exit code 17', receipt['error'])
        self.assertTrue(receipt['terminationConfirmed'])
        self.assertIn('held by a reader', receipt['diagnosticWriteError'])

    def test_report_with_passed_status_but_missing_checks_is_rejected(self):
        self.report = {'status': 'passed'}
        self.store_report()
        with patch.object(runner.render, 'start_pipe_capture', return_value=(self.reader, self.pipe)):
            with self.assertRaises(ValueError):
                self.run_stage()
        self.assertTrue(self.receipt()['terminationConfirmed'])
        self.assertTrue(self.receipt()['stdioClosed'])

    def test_fallback_write_failure_cannot_replace_primary(self):
        with patch.object(runner, 'write', side_effect=OSError('replace failure')), patch.object(Path, 'open', side_effect=OSError('disk full')):
            runner.final_write(self.directory / 'check.json', {'status': 'failed'}, RuntimeError('primary'))

    def test_final_report_write_failure_on_an_otherwise_successful_run_is_not_a_pass(self):
        with patch.object(runner, 'write', side_effect=OSError('replace failure')):
            with self.assertRaisesRegex(OSError, 'replace failure'):
                runner.final_write(self.directory / 'check.json', {'status': 'passed'}, None)
        diagnostic = next(self.directory.glob('check.final-diagnostic-*.json'))
        self.assertEqual(json.loads(diagnostic.read_text())['status'], 'failed')

    def execute_fixture(self, patches, *, mode='backend-only', startup_error=None):
        data = self.directory / 'data'
        source = self.directory / 'source'
        data.mkdir(); source.mkdir()
        payload = b'{"layoutId":"fl-test"}\n'
        (source / 'manual.json').write_bytes(payload)
        (data / 'manual.json').write_bytes(payload)
        identity = {'origin': 'http://127.0.0.1:8199', 'profileId': 'test'}
        manifest = {'identity': identity, 'source': {'root': str(source), 'layoutRelativePath': 'manual.json'},
                    'layout': {'layoutId': 'fl-test', 'relativePath': 'manual.json', 'revision': runner.render.file_hash(source / 'manual.json')}, 'assets': []}
        (data / 'facility-recovery-fixture.json').write_text(json.dumps(manifest))
        args = SimpleNamespace(data_root=data, output=self.directory / 'execute-output', port=8199, mode=mode)
        state = {}
        def spawn(*unused, **kwargs):
            state['instance'] = kwargs['env']['INSPECTORPRO_DESKTOP_INSTANCE_ID']
            self.events.append('backend-spawn')
            return self.child
        def stop(process):
            self.assertIs(process, self.child)
            self.events.append('backend-stop')
            process.returncode = 0
            (data / 'shutdown.json').write_text(json.dumps({'schemaVersion': 1, 'instanceId': state['instance'],
                'status': 'lifespan-stopped', 'resourcesClosed': True}))
        def http(origin, route, token=None):
            if token is None:
                raise urllib.error.HTTPError(origin + route, 403, 'denied', {}, None)
            return io.BytesIO(json.dumps({'assetCatalog': []} if route.endswith('bootstrap') else {'assets': []}).encode())
        for target, name, replacement in (
            (runner.base, 'no_links', lambda value: Path(value)),
            (runner.base, 'prepare_fixture', Mock(return_value=(data / 'library', identity))),
            (runner.base, 'child_environment', lambda env, *_: dict(env)),
            (runner.base, 'wait_ready', Mock(side_effect=startup_error)),
            (runner.base, 'stop_child', stop),
            (runner.base, 'shutdown_receipt_path', lambda *_: data / 'shutdown.json'),
            (runner.subprocess, 'Popen', spawn),
            (runner, 'http', http),
        ):
            patches.enter_context(patch.object(target, name, replacement))
        return args

    def test_backend_only_verifies_cleanup_without_claiming_recovery_scenarios(self):
        with ExitStack() as patches:
            args = self.execute_fixture(patches)
            result = runner.execute(args)
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(result['recoveryScenariosExecuted'])
        self.assertTrue(result['backend']['resourceCleanupVerified'])
        self.assertTrue(result['backend']['terminationConfirmed'])
        self.assertTrue(result['manualLayoutUnchanged'])
        self.assertEqual(self.events, ['backend-spawn', 'backend-stop'])

    def test_startup_failure_and_final_replace_failure_keep_primary_and_cleanup_receipt(self):
        with ExitStack() as patches:
            args = self.execute_fixture(patches, startup_error=RuntimeError('original startup failure'))
            original = runner.write
            def write(target, value):
                if target.name == 'check.json' and value.get('finishedAt'):
                    raise PermissionError('aggregate report held by reader')
                original(target, value)
            patches.enter_context(patch.object(runner, 'write', side_effect=write))
            with self.assertRaisesRegex(RuntimeError, 'original startup failure'):
                runner.execute(args)
        final = next(args.output.glob('check.final-diagnostic-*.json'))
        receipt = json.loads(final.read_text())
        self.assertEqual(receipt['error'], 'original startup failure')
        self.assertTrue(receipt['backend']['resourceCleanupVerified'])
        self.assertTrue(receipt['manualLayoutUnchanged'])

    def test_failed_worker_receipt_is_retained_before_backend_cleanup(self):
        with ExitStack() as patches:
            args = self.execute_fixture(patches, mode='engine')
            failure = RuntimeError('worker failed after drain')
            failure.facility_process_result = {'status': 'failed', 'terminationConfirmed': True, 'stdioClosed': True, 'stdioEOFVerified': True}
            def stage(*unused, **kwargs):
                self.events.append('worker-drained')
                raise failure
            patches.enter_context(patch.object(runner.shutil, 'which', return_value='fake-node'))
            patches.enter_context(patch.object(runner, 'run_worker_stage', side_effect=stage))
            with self.assertRaisesRegex(RuntimeError, 'worker failed after drain'):
                runner.execute(args)
        receipt = json.loads((args.output / 'check.json').read_text())
        self.assertEqual(receipt['stages']['1'], failure.facility_process_result)
        self.assertTrue(receipt['backend']['terminationConfirmed'])
        self.assertEqual(self.events, ['backend-spawn', 'worker-drained', 'backend-stop'])


if __name__ == '__main__':
    unittest.main()
