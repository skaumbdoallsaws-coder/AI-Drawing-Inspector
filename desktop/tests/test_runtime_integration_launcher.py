import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import contextlib
import io


def diagnostic_receipt():
    cleanup = {'instanceId': 'owned-instance', 'processId': 4242, 'terminationConfirmed': True, 'stdioClosed': True,
               'resourcesClosed': True, 'forced': False, 'exitCode': 0}
    return {'schemaVersion': 1, 'mode': 'managed-backend-startup-diagnostics', 'status': 'passed',
            'startupDiagnosticsOnly': True, 'runtimeVerified': True, 'startupDeadlineMs': 45000,
            'nativeAcceptance': False, 'applicationLoaded': False, 'facilityAttached': False,
            'editorExercised': False, 'screenshotCaptured': False, 'generalEditing': False,
            'researchBrowsing': False, 'saveCalls': 0, 'error': None,
            'isolation': {'sandbox': True, 'contextIsolation': True, 'nodeIntegration': False, 'webSecurity': True},
            'cleanup': cleanup, 'backends': [{'instanceId': 'owned-instance', 'processId': 4242, 'startupDiagnosticsEnabled': True,
                'runtime': {'instanceId': 'owned-instance', 'processId': 4242}, 'cleanup': cleanup,
                'failure': None, 'diagnosticErrors': [], 'diagnosticErrorCounts': {'invalidCount': 0, 'foreignCount': 0, 'truncatedCount': 0},
                'startupElapsedMs': 22, 'importTimingLines': 12, 'timings': {'spawnStartedUnixMs': 12345, 'readyObservedElapsedMs': 20,
                    'runtimeVerifiedElapsedMs': 22, 'shutdownRequestedElapsedMs': 25, 'processExitElapsedMs': 30, 'stdioClosedElapsedMs': 31},
                'startupCheckpoints': {'invalidCount': 0, 'foreignCount': 0, 'truncatedCount': 0,
                    'records': [{'phase': 'application-ready', 'instanceId': 'owned-instance', 'processId': 4242,
                                 'sequence': 1, 'elapsedMs': 19, 'observedElapsedMs': 20}], 'lastPhase': 'application-ready'}, 'diagnosticsFiles': {
                    'stacks': {'path': 'stacks.log', 'exists': True, 'sizeBytes': 256, 'baselinePresent': True},
                    'imports': {'path': 'imports.json', 'exists': True, 'metadataValid': True}}}]}

PATH = Path(__file__).resolve().parents[1] / 'tools' / 'run-runtime-integration.py'
SPEC = importlib.util.spec_from_file_location('runtime_integration_launcher_test', PATH)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LauncherTest(unittest.TestCase):
    def test_research_receipt_cannot_substitute_flags_for_meshes_or_missing_captures(self):
        import copy
        report = {'schemaVersion': 1, 'status': 'pending-native-composite', 'stage': 'complete',
                  'engineChecksPassed': True, 'exactFrameRetained': True, 'localNetworkBlocked': True,
                  'saveCalls': 0, 'nativeAcceptance': False, 'nativeCompositeAvailable': False,
                  'checks': {key: True for key in ('publicHTTPSAndIsolation', 'boundsHideReopenAndOverlay', 'realMeshesAndLibrary')},
                  'isolation': {'sandbox': True, 'contextIsolation': True, 'webSecurity': True, 'nodeIntegration': False},
                  'network': [{'blocked': True}] * 4,
                  'meshes': {'realPlacements': 827, 'assetGroups': 37, 'transformAudit': {'status': 'match',
                       'auditedPlacementCount': 827, 'transformMismatchCount': 0, 'missingPlacementCount': 0}},
                  'library': {'open': True, 'cards': 38}}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            launcher.validate_research(report, output)
            for field in ('meshes', 'library', 'isolation', 'checks'):
                invalid = copy.deepcopy(report); invalid[field] = {}
                with self.subTest(field=field), self.assertRaises(ValueError):
                    launcher.validate_research(invalid, output)
            for key, value in [('saveCalls', True), ('saveCalls', 1), ('network', []), ('nativeAcceptance', True)]:
                with self.subTest(field=key), self.assertRaises(ValueError):
                    launcher.validate_research({**report, key: value}, output)
            accepted = {**report, 'status': 'passed', 'nativeAcceptance': True, 'nativeCompositeAvailable': True}
            with self.assertRaises(ValueError): launcher.validate_research(accepted, output)

    def test_read_only_import_has_no_launch(self):
        self.assertTrue(callable(launcher.main))
        self.assertTrue(callable(launcher.run_stage))

    def test_owned_cli_stage_persists_both_streams_and_confirms_shutdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'success'
            result = launcher.run_stage([sys.executable, '-c', 'import sys; print("stdout evidence",flush=True); print("stderr evidence",file=sys.stderr,flush=True)'], output, timeout=5)
            self.assertEqual(result['status'], 'passed')
            self.assertTrue(result['terminationConfirmed'] and result['stdoutClosed'] and result['stderrClosed'])
            self.assertIn('stdout evidence', (output / 'stdout.log').read_text())
            self.assertIn('stderr evidence', (output / 'stderr.log').read_text())
            self.assertEqual(json.loads((output / 'process-result.json').read_text())['exitCode'], 0)

    @unittest.skipUnless(os.name == 'nt', 'Windows startup visibility flags')
    def test_application_controls_first_show_but_helpers_remain_hidden(self):
        real_popen = subprocess.Popen
        with tempfile.TemporaryDirectory() as temporary:
            for application in (False, True):
                with mock.patch.object(launcher.subprocess, 'Popen', wraps=real_popen) as spawn:
                    result = launcher.run_stage([sys.executable, '-c', 'print("owned child")'],
                        Path(temporary) / str(application), timeout=5, application_window=application)
                self.assertEqual(result['status'], 'passed')
                options = spawn.call_args.kwargs
                self.assertEqual(options['creationflags'], subprocess.CREATE_NEW_PROCESS_GROUP)
                if application:
                    self.assertNotIn('startupinfo', options)
                    self.assertEqual(result['windowMode'], 'application-controlled')
                else:
                    self.assertTrue(options['startupinfo'].dwFlags & subprocess.STARTF_USESHOWWINDOW)
                    self.assertEqual(options['startupinfo'].wShowWindow, subprocess.SW_HIDE)
                    self.assertEqual(result['windowMode'], 'hidden-helper')

    def test_failed_spawn_keeps_diagnostics_without_inventing_process_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'spawn'
            result = launcher.run_stage([str(Path(temporary) / 'absent.exe')], output, timeout=1)
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['terminationConfirmed'])
            self.assertTrue((output / 'stdout.log').is_file() and (output / 'stderr.log').is_file())
            self.assertIn('error', json.loads((output / 'process-result.json').read_text()))

    def test_timeout_retains_flushed_output_and_owned_process_is_terminated(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'timeout'
            result = launcher.run_stage([sys.executable, '-u', '-c', 'import time;print("before timeout",flush=True);time.sleep(10)'], output, timeout=0.3)
            self.assertEqual(result['status'], 'failed')
            self.assertTrue(result['forced'] and result['terminationConfirmed'] and result['stdoutClosed'] and result['stderrClosed'])
            self.assertIn('before timeout', (output / 'stdout.log').read_text())

    def test_native_validation_requires_every_gate_zero_save_and_all_backend_cleanup(self):
        report = {'schemaVersion': 1, 'mode': 'normal-entry-full-application', 'status': 'passed', 'saveCalls': 0,
                  'generalEditing': False, 'researchBrowsing': False, 'checks': {key: 'passed' for key in launcher.CHECKS},
                  'isolation': {'sandbox': True, 'contextIsolation': True, 'nodeIntegration': False, 'webSecurity': True,
                                'renderer': {'requireType': 'undefined', 'processType': 'undefined'}}}
        report['checks']['recoveredScreenshot'] = 'captured-awaiting-visual-review'
        report['facilityInputChecks'] = [{'label': label, **{key: True for key in launcher.INPUT_TRUE},
                                          **{key: False for key in launcher.INPUT_FALSE}} for label in launcher.INPUT_LABELS]
        prefix = '/api/facility-layout-design/site-local/' + launcher.LAYOUT
        report['requests'] = {'saveCalls': 0, 'transactionRequests': {
            prefix + '/proposals/proposal/apply/prepare': 1,
            **{prefix + '/transactions/transaction/' + name: 1 for name in ('apply/commit', 'apply/acknowledge', 'undo/prepare', 'undo/acknowledge')}}}
        cleanup = {'terminationConfirmed': True, 'stdioClosed': True, 'resourcesClosed': True}
        final = {'schemaVersion': 1, 'status': 'passed', 'finalClose': 'closed-without-save', 'discardFinalized': True,
                 'cleanup': cleanup, 'saveCalls': 0, 'backends': [{'instanceId': str(index), 'cleanup': cleanup} for index in range(3)]}
        launcher.validate_native(report, final)
        for name, evidence in [('native', report), ('final', final)]:
            for value in ('missing', 1, None, False):
                changed = dict(evidence)
                if value == 'missing': changed.pop('saveCalls')
                else: changed['saveCalls'] = value
                with self.subTest(receipt=name, save_calls=value), self.assertRaises(ValueError):
                    launcher.validate_native(changed if name == 'native' else report, changed if name == 'final' else final)
        for field, value in [('saveCalls', 1), ('saveCalls', None), ('discardFinalized', False), ('backends', [])]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): launcher.validate_native(report, {**final, field: value})
        with self.assertRaises(ValueError): launcher.validate_native({**report, 'checks': {}}, final)
        with self.assertRaises(ValueError): launcher.validate_native(report, {**final, 'cleanup': {**cleanup, 'resourcesClosed': False}})
        with self.assertRaises(ValueError): launcher.validate_native({**report, 'facilityInputChecks': []}, final)
        for key in launcher.INPUT_TRUE + launcher.INPUT_FALSE:
            changed = json.loads(json.dumps(report)); changed['facilityInputChecks'][3][key] = not changed['facilityInputChecks'][3][key]
            with self.subTest(input_field=key), self.assertRaises(ValueError): launcher.validate_native(changed, final)
        changed = json.loads(json.dumps(report)); changed['requests']['transactionRequests'][prefix + '/transactions/transaction/undo/prepare'] = 2
        with self.assertRaises(ValueError): launcher.validate_native(changed, final)
        changed = json.loads(json.dumps(report)); changed['requests']['saveCalls'] = 1
        with self.assertRaises(ValueError): launcher.validate_native(changed, final)

    def test_environment_does_not_inherit_provider_secrets_or_unsafe_electron_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = launcher.environment(Path(temporary))
            self.assertNotIn('OPENAI_API_KEY', env)
            self.assertNotIn('NODE_OPTIONS', env)
            self.assertNotIn('ELECTRON_RUN_AS_NODE', env)
            self.assertEqual(env['PYTHON_DOTENV_DISABLED'], '1')
            self.assertTrue(str(Path(temporary)) in env['TEMP'])
            for key in ('APPDATA', 'USERPROFILE'):
                if key in os.environ: self.assertEqual(env[key], os.environ[key])

    def test_existing_python_user_site_dependencies_remain_discoverable_before_application_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = launcher.environment(Path(temporary))
            completed = subprocess.run([sys.executable, '-B', '-c',
                'import importlib.util; spec=importlib.util.find_spec("starlette"); assert spec is not None; print(spec.origin)'],
                env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn('starlette', completed.stdout)

    def test_native_command_selects_one_mode_without_changing_the_entry_python_or_security_flags(self):
        normal = launcher.native_command('pinned-electron.exe', Path('profile.json'), Path('native-output'))
        diagnostic = launcher.native_command('pinned-electron.exe', Path('profile.json'), Path('native-output'), startup_diagnostics_only=True)
        self.assertEqual(normal[:6], diagnostic[:6])
        self.assertEqual(normal[-2], '--acceptance-output')
        self.assertEqual(diagnostic[-2], '--startup-diagnostics-output')
        self.assertNotIn('--acceptance-output', diagnostic)
        self.assertEqual(diagnostic[diagnostic.index('--python') + 1], sys.executable)
        self.assertEqual(diagnostic[1], launcher.ROOT / 'desktop/src/entry.cjs')
        self.assertFalse(any('sandbox' in str(value) for value in diagnostic))

    def test_diagnostic_receipt_requires_optin_instrumentation_graceful_cleanup_and_no_acceptance(self):
        receipt = diagnostic_receipt(); launcher.validate_startup_diagnostics(receipt)
        mutations = [
            lambda item: item.update(status='failed'),
            lambda item: item.update(startupDeadlineMs=90000),
            lambda item: item.update(nativeAcceptance=True),
            lambda item: item.update(applicationLoaded=True),
            lambda item: item.update(facilityAttached=True),
            lambda item: item.update(editorExercised=True),
            lambda item: item.update(screenshotCaptured=True),
            lambda item: item.update(saveCalls=1),
            lambda item: item['cleanup'].update(resourcesClosed=False),
            lambda item: item['cleanup'].update(forced=True),
            lambda item: item['backends'][0].update(startupDiagnosticsEnabled=False),
            lambda item: item['backends'][0].update(instanceId='unrelated-instance'),
            lambda item: item['backends'][0]['diagnosticsFiles']['imports'].update(metadataValid=False),
            lambda item: item['backends'][0]['diagnosticsFiles']['stacks'].update(exists=False),
            lambda item: item['backends'][0].update(timings={}),
            lambda item: item['backends'][0].update(importTimingLines=0),
            lambda item: item['backends'][0].update(importTimingLines=True),
            lambda item: item['backends'][0]['startupCheckpoints'].update(records=[]),
            lambda item: item['backends'][0]['diagnosticErrors'].append({'operation': 'bind', 'errorType': 'OSError'}),
            lambda item: item['backends'][0]['diagnosticErrorCounts'].update(foreignCount=1),
            lambda item: item['backends'][0]['diagnosticsFiles']['stacks'].update(sizeBytes=0),
            lambda item: item['backends'][0]['diagnosticsFiles']['stacks'].update(baselinePresent=False),
            lambda item: item['backends'][0].update(processId=4343),
        ]
        for index, mutate in enumerate(mutations):
            changed = json.loads(json.dumps(receipt)); mutate(changed)
            with self.subTest(case=index), self.assertRaises(ValueError): launcher.validate_startup_diagnostics(changed)

    @unittest.skipUnless(os.name == 'nt', 'This exercises the existing Windows-only launcher orchestration with fake owned stages')
    def test_startup_only_orchestration_preserves_fixture_and_profile_but_skips_seed_editor_and_screenshot(self):
        import ctypes
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary); root = parent / 'snapshot'; source = parent / 'source'; output = parent / 'outputs'
            root.mkdir(); output.mkdir(); source.mkdir()
            for relative in ['desktop/src/entry.cjs', 'desktop/runtime/create_profile.py', 'desktop/tools/seed-runtime-proposal.py']:
                target = root / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_text('fixture')
            (root / 'desktop/package.json').write_text(json.dumps({'devDependencies': {'electron': '44.3.0'}}))
            (root / 'desktop-checkpoint.json').write_text(json.dumps({'source': str(source)}))
            original = source / '.runtime/facility-layout/layouts/local/site-local/layouts' / (launcher.LAYOUT + '.json')
            original.parent.mkdir(parents=True); original.write_text('unchanged saved layout')
            executable = parent / 'pinned-electron.exe'; executable.write_bytes(b'pin fixture')
            binary = {'version': '44.3.0', 'executable': str(executable), 'sha256': launcher.digest(executable)}
            common = SimpleNamespace(backend=SimpleNamespace(no_links=lambda value: value), resolve_electron=lambda _: binary)
            spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: module.__dict__.update(common.__dict__)))
            stages = []
            def fake_stage(command, destination, **kwargs):
                command = list(map(str, command)); stages.append((destination.name, command))
                destination.mkdir(parents=True)
                if destination.name == 'prepare-fixture':
                    data = Path(command[command.index('--data-root') + 1])
                    target = data / 'facility/layouts/local/site-local/layouts' / (launcher.LAYOUT + '.json')
                    target.parent.mkdir(parents=True); target.write_bytes(original.read_bytes())
                elif destination.name == 'create-profile':
                    Path(command[command.index('--profile-file') + 1]).write_text('{}')
                elif destination.name == 'native-process':
                    native = Path(command[command.index('--startup-diagnostics-output') + 1]); native.mkdir()
                    (native / 'startup-diagnostics-result.json').write_text(json.dumps(diagnostic_receipt()))
                else: self.fail('Unexpected stage in diagnostic-only run: ' + destination.name)
                return {'status': 'passed', 'terminationConfirmed': True, 'stdoutClosed': True, 'stderrClosed': True, 'exitCode': 0}
            with mock.patch.object(launcher, 'ROOT', root), mock.patch.object(launcher.importlib.util, 'spec_from_file_location', return_value=spec), \
                 mock.patch.object(launcher.importlib.util, 'module_from_spec', return_value=SimpleNamespace()), \
                 mock.patch.object(launcher, 'run_stage', side_effect=fake_stage), \
                 mock.patch.object(launcher, 'validate_native', side_effect=AssertionError('Full acceptance validator must not run')), \
                 mock.patch.object(ctypes.windll.shell32, 'IsUserAnAdmin', return_value=False), contextlib.redirect_stdout(io.StringIO()):
                result = launcher.main(['--electron-desktop', str(parent / 'installed'), '--output-root', str(output), '--startup-diagnostics-only'])
            self.assertEqual(result, 0)
            self.assertEqual([name for name, _ in stages], ['prepare-fixture', 'create-profile', 'native-process'])
            report = json.loads(next(output.glob('*/native-launch.json')).read_text())
            self.assertEqual(report['status'], 'passed'); self.assertTrue(report['savedLayoutsUnchanged'])
            self.assertTrue(report['startupDiagnosticsOnly']); self.assertFalse(report['nativeAcceptance'])
            self.assertEqual(report['visualReview'], 'not-applicable')
            self.assertNotIn('nativeReport', report); self.assertNotIn('finalReceipt', report)
            self.assertEqual(original.read_text(), 'unchanged saved layout')


if __name__ == '__main__': unittest.main()
