import importlib.util
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.runtime.startup_diagnostics import StartupImportDiagnostics
from desktop.runtime import managed_backend


class FakeHandler:
    def __init__(self): self.calls = []; self.file = None
    def dump_traceback_later(self, timeout, **kwargs):
        self.calls.append(('arm', timeout, kwargs['repeat'], kwargs['exit']))
        self.file = kwargs['file']
    def cancel_dump_traceback_later(self):
        self.calls.append(('cancel', self.file is None or not self.file.closed))
    def dump_traceback(self, **kwargs):
        self.calls.append(('dump', kwargs['all_threads']))


class ImportDiagnosticsTests(unittest.TestCase):
    def test_opt_in_files_identity_and_cancel_before_close(self):
        with tempfile.TemporaryDirectory() as temp:
            handler = FakeHandler(); output = io.StringIO(); key = str(uuid.uuid4())
            diag = StartupImportDiagnostics(.1, handler=handler, stderr=output)
            diag.start(); diag.bind(Path(temp), key, os.getpid())
            stream = diag.stream
            diag.capture_shutdown(); diag.capture_shutdown(); diag.stop(); diag.stop()
            self.assertTrue(stream.closed)
            self.assertEqual([value for value in handler.calls if value[0] == 'arm'], [('arm', .1, False, False)] * 2)
            self.assertEqual([value for value in handler.calls if value[0] == 'dump'], [('dump', True)] * 2)
            self.assertTrue(all(value[1] for value in handler.calls if value[0] == 'cancel'))
            metadata = json.loads((Path(temp) / 'desktop-logs' / (key + '-import-diagnostics.json')).read_text())
            self.assertEqual(metadata['processId'], os.getpid()); self.assertEqual(metadata['instanceId'], key)
            self.assertFalse(metadata['recordsLocals']); self.assertFalse(metadata['recordsArguments'])
            self.assertEqual(set(Path(temp).rglob('*-import-stacks.log')).__len__(), 1)

    def test_previous_evidence_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            key = str(uuid.uuid4()); handler = FakeHandler(); diag = StartupImportDiagnostics(handler=handler)
            diag.start(); diag.bind(Path(temp), key, os.getpid()); diag.stop()
            files = {p: p.read_bytes() for p in Path(temp).rglob('*') if p.is_file()}
            retry = StartupImportDiagnostics(handler=FakeHandler()); retry.start()
            try:
                with self.assertRaises(FileExistsError): retry.bind(Path(temp), key, os.getpid())
            finally: retry.stop()
            self.assertEqual(files, {p: p.read_bytes() for p in files})

    def test_cancel_failure_retains_descriptor_until_successful_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            handler = FakeHandler(); diag = StartupImportDiagnostics(handler=handler)
            diag.start(); diag.bind(Path(temp), str(uuid.uuid4()), os.getpid()); stream = diag.stream
            with patch.object(handler, 'cancel_dump_traceback_later', side_effect=OSError('controlled')):
                with self.assertRaises(OSError): diag.stop()
            self.assertFalse(stream.closed); self.assertFalse(diag.stopped)
            diag.stop(); self.assertTrue(stream.closed)

    def test_diagnostic_failures_preserve_managed_lifecycle_and_primary_error(self):
        private = {'instanceId': str(uuid.uuid4()), 'credential': 'a' * 64}
        profile = SimpleNamespace(data=ROOT, value={'profileId': 'controlled'})
        for operation in ('start', 'bind', 'stop'):
            for application_fails in (False, True):
                with self.subTest(operation=operation, application_fails=application_fails), ExitStack() as patches:
                    diag = Mock(); getattr(diag, operation).side_effect = OSError('PRIVATE_ERROR_MUST_NOT_APPEAR')
                    primary = RuntimeError('controlled application failure')
                    application = AsyncMock(side_effect=primary if application_fails else None)
                    patches.enter_context(patch.dict(sys._xoptions, {'importtime': True}))
                    patches.enter_context(patch.object(sys, 'argv', ['controlled', '--profile-file', str(ROOT / 'unused.json')]))
                    patches.enter_context(patch('desktop.runtime.startup_diagnostics.StartupImportDiagnostics', return_value=diag))
                    patches.enter_context(patch.object(managed_backend, '_IMPORT_DIAGNOSTICS', None))
                    patches.enter_context(patch.object(managed_backend, '_IMPORT_DIAGNOSTICS_INSTANCE', None))
                    patches.enter_context(patch.object(managed_backend, '_DIAGNOSTIC_ERRORS', set()))
                    patches.enter_context(patch.object(managed_backend, 'bootstrap', return_value=private))
                    patches.enter_context(patch.object(managed_backend, 'load_profile', return_value=profile))
                    for target in ('configure_environment', 'install_runtime_guard', 'PrivateControl'):
                        patches.enter_context(patch.object(managed_backend, target))
                    patches.enter_context(patch.object(managed_backend.os, 'chdir'))
                    patches.enter_context(patch.object(managed_backend.threading, 'Thread'))
                    patches.enter_context(patch.object(managed_backend, 'serve', application))
                    output = patches.enter_context(patch.object(managed_backend, 'emit'))
                    if application_fails:
                        with self.assertRaises(RuntimeError) as error: managed_backend.main()
                        self.assertIs(error.exception, primary)
                    else: managed_backend.main()
                    application.assert_awaited_once()
                    diag.stop.assert_called_once()
                    failures = [call.args[1] for call in output.call_args_list if call.args[0] == 'DIAGNOSTIC_ERROR']
                    self.assertEqual(len(failures), 1)
                    self.assertEqual(failures[0]['operation'], operation)
                    self.assertNotIn('PRIVATE_ERROR', str(output.call_args_list))

    def test_nonpositive_or_unbounded_watchdog_refused(self):
        for value in (0, -1, 31, True, '30', float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError): StartupImportDiagnostics(value)

    def test_timed_checkpoints_do_not_expose_private_data(self):
        with patch.object(managed_backend, 'emit') as emit:
            managed_backend.checkpoint('test-one', 'instance'); managed_backend.checkpoint('test-two', 'instance')
        first, second = [call.args[1] for call in emit.call_args_list]
        self.assertGreater(second['sequence'], first['sequence'])
        self.assertGreaterEqual(second['elapsedMs'], first['elapsedMs'])
        self.assertEqual(second['previousPhase'], 'test-one')
        self.assertGreaterEqual(second['previousPhaseDurationMs'], 0)
        self.assertNotIn('credential', second)

    def test_actual_import_stack_and_python_timing_survive_owned_forced_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp); key = str(uuid.uuid4()); marker = 'PRIVATE_VALUE_MUST_NOT_APPEAR'
            (data / 'held_import.py').write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
            # Launch only a controlled import, under the real runtime write guard.
            # No application backend, Electron, model, or Save is invoked.
            code = '''import os,sys
from pathlib import Path
from desktop.runtime.startup_diagnostics import StartupImportDiagnostics
from desktop.runtime.managed_backend import install_runtime_guard
data=Path(sys.argv[1]);private_value=sys.argv[3]
d=StartupImportDiagnostics(.08);d.start();d.bind(data,sys.argv[2],os.getpid())
install_runtime_guard(data);sys.path.insert(0,str(data));import held_import
'''
            # Drain import timings from process start. An unread Windows pipe
            # can itself block startup before our controlled import is reached.
            with (data / 'timings.log').open('wb') as timing_output:
                process = subprocess.Popen([sys.executable, '-B', '-u', '-X', 'importtime', '-c', code, str(data), key, marker],
                    cwd=ROOT, stdout=subprocess.PIPE, stderr=timing_output)
                stack = data / 'desktop-logs' / (key + '-import-stacks.log')
                try:
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        if stack.exists() and 'held_import.py' in stack.read_text(errors='replace'): break
                        if process.poll() is not None: break
                        time.sleep(.025)
                    self.assertIsNone(process.poll(), 'Controlled import exited before forced-termination test')
                    self.assertTrue(stack.exists(), (data / 'timings.log').read_text(errors='replace'))
                    self.assertIn('held_import.py', stack.read_text(errors='replace'))
                finally:
                    if process.poll() is None: process.terminate()
                    stdout, _ = process.communicate(timeout=5)
            stderr = (data / 'timings.log').read_bytes()
            self.assertIsNotNone(process.returncode)
            self.assertIn(b'import time:', stderr)
            contents = stack.read_text(errors='replace')
            self.assertIn('Timeout', contents)
            self.assertNotIn(marker, contents + stderr.decode(errors='replace') + stdout.decode(errors='replace'))
            metadata = json.loads((stack.parent / (key + '-import-diagnostics.json')).read_text())
            self.assertEqual(metadata['processId'], process.pid); self.assertTrue(metadata['importTimeEnabled'])

    def test_completed_imports_report_timing_and_cancelled_watchdog_stays_quiet(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp); key = str(uuid.uuid4())
            (data / 'brief_import.py').write_text('import time\ntime.sleep(.03)\n', encoding='utf-8')
            code = '''import os,sys,time
from pathlib import Path
from desktop.runtime.startup_diagnostics import StartupImportDiagnostics
d=StartupImportDiagnostics(.3);d.start();d.bind(Path(sys.argv[1]),sys.argv[2],os.getpid())
sys.path.insert(0,sys.argv[1]);import brief_import;d.stop();time.sleep(.4)
'''
            result = subprocess.run([sys.executable, '-B', '-u', '-X', 'importtime', '-c', code, str(data), key],
                cwd=ROOT, capture_output=True, timeout=8)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertIn(b'brief_import', result.stderr)
            stack = data / 'desktop-logs' / (key + '-import-stacks.log')
            self.assertNotIn('Timeout', stack.read_text(errors='replace'))


if __name__ == '__main__': unittest.main()
