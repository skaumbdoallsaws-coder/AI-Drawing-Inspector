"""Fixed-metadata startup diagnostics for the explicitly executed facility fixture."""
import argparse
import asyncio
import builtins
from contextlib import asynccontextmanager
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'facility-recovery-backend.py'


def load_wrapper(name='facility_startup_diagnostics_test'):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = load_wrapper()


class FacilityStartupDiagnosticsTests(unittest.TestCase):
    def test_ordinary_import_with_serve_argument_stays_silent_and_does_not_import_app(self):
        output = io.StringIO()
        original_import = builtins.__import__

        def prevent_application_import(name, *args, **kwargs):
            if name in {'server', 'uvicorn'}:
                raise AssertionError('Ordinary fixture import must not load the application')
            return original_import(name, *args, **kwargs)

        with patch.object(sys, 'argv', [str(SCRIPT), '--serve']), \
             patch.object(sys, 'stderr', output), \
             patch.object(builtins, '__import__', side_effect=prevent_application_import):
            imported = load_wrapper('facility_nonexecuted_wrapper')
            imported.base.startup_checkpoint('must-stay-silent')
        self.assertEqual(output.getvalue(), '')
        self.assertFalse(imported._STARTUP_DIAGNOSTICS_ENABLED)
        self.assertFalse(imported.base._STARTUP_CHECKPOINTS_ENABLED)
        self.assertEqual(imported.CONFIG, {})

    def test_executed_wrapper_flushes_bootstrap_before_bulk_imports(self):
        output = io.StringIO()
        output.flush = Mock(wraps=output.flush)
        original_import = builtins.__import__

        def stop_at_bulk_import(name, *args, **kwargs):
            if name == 'argparse':
                self.assertEqual(output.getvalue(), 'INSPECTORPRO_DESKTOP_BACKEND_BOOTSTRAP_ENTERED\n')
                output.flush.assert_called_once()
                raise RuntimeError('controlled stop before wrapper bulk imports')
            return original_import(name, *args, **kwargs)

        with patch.object(sys, 'argv', [str(SCRIPT), '--serve']), patch.object(sys, 'stderr', output), \
             patch.object(builtins, '__import__', side_effect=stop_at_bulk_import):
            with self.assertRaisesRegex(RuntimeError, 'controlled stop'):
                exec(compile(SCRIPT.read_text(), str(SCRIPT), 'exec'), {'__name__': '__main__'})

    def test_executed_wrapper_explicitly_enables_base_checkpoints_from_wrapper_entry(self):
        output = io.StringIO()
        namespace = {'__name__': '__main__', '__file__': str(SCRIPT)}
        with patch.object(sys, 'argv', [str(SCRIPT), '--serve', '--token-file', 'not-for-logs']), \
             patch.object(sys, 'stderr', output), \
             patch.object(argparse, 'ArgumentParser', side_effect=RuntimeError('stop before parsing')):
            with self.assertRaisesRegex(RuntimeError, 'stop before parsing'):
                exec(compile(SCRIPT.read_text(), str(SCRIPT), 'exec'), namespace)
        backend = namespace['base']
        self.assertTrue(backend._STARTUP_CHECKPOINTS_ENABLED)
        self.assertEqual(backend._STARTUP_STARTED, namespace['_WRAPPER_STARTED'])
        records = [json.loads(line.removeprefix(backend.STARTUP_CHECKPOINT_PREFIX))
                   for line in output.getvalue().splitlines()
                   if line.startswith(backend.STARTUP_CHECKPOINT_PREFIX)]
        self.assertEqual([value['phase'] for value in records], [
            'facility-wrapper-imports-completed', 'facility-main-entered', 'facility-arguments-parsing'])
        self.assertEqual([value['sequence'] for value in records], [1, 2, 3])
        self.assertTrue(all(value['elapsedMs'] >= 0 for value in records))
        self.assertNotIn('not-for-logs', output.getvalue())

    def test_explicit_opt_in_is_silent_until_checkpoint_and_validates_monotonic_origin(self):
        backend = load_wrapper('facility_explicit_checkpoint_opt_in').base
        output = io.StringIO()
        with patch.object(backend.time, 'monotonic', return_value=20.25), patch.object(sys, 'stderr', output):
            backend.enable_startup_checkpoints(started_at=10)
            self.assertEqual(output.getvalue(), '')
            backend.startup_checkpoint('serve-entered')
            for invalid in (True, '10', -1, 21, float('nan'), float('inf')):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    backend.enable_startup_checkpoints(started_at=invalid)
        record = json.loads(output.getvalue().removeprefix(backend.STARTUP_CHECKPOINT_PREFIX))
        self.assertEqual(record['elapsedMs'], 10250)
        self.assertEqual(record['phase'], 'serve-entered')

    def test_boundary_checkpoints_bracket_real_initialization_order_and_catalog_failure(self):
        for fail_catalog in (False, True):
            with self.subTest(fail_catalog=fail_catalog), tempfile.TemporaryDirectory() as temporary:
                trace = []
                catalog = [{'assetId': 'copied-test-asset', 'assetDefinitionRevision': 'revision-1'}]
                host = SimpleNamespace()
                app = SimpleNamespace(router=SimpleNamespace(routes=[]))

                def build_catalog(root):
                    trace.append('build-catalog')
                    if fail_catalog:
                        raise RuntimeError('controlled catalog failure')
                    return catalog

                def static_files(**kwargs):
                    trace.append('construct-static-mount')
                    return kwargs

                modules = {
                    'server': SimpleNamespace(_FACILITY_LAYOUT_HOST=host),
                    'starlette.routing': SimpleNamespace(Mount=lambda *args, **kwargs: kwargs),
                    'starlette.staticfiles': SimpleNamespace(StaticFiles=static_files),
                    'ai_inspector.facility_layout.host': SimpleNamespace(
                        build_private_local_asset_catalog=build_catalog, LOCAL_ASSET_CATALOG=[]),
                }
                config = {'data_root': Path(temporary), 'layout_id': 'test-layout',
                          'token': 'secret-should-not-be-logged', 'owner': {'ownerId': 'test-owner'}}
                with patch.dict(sys.modules, modules), patch.dict(wrapper.CONFIG, config, clear=True), \
                     patch.object(wrapper.base, 'startup_checkpoint', side_effect=trace.append), \
                     patch.object(wrapper.RecoveryBoundary, 'initialize_managed_restart',
                                  side_effect=lambda: trace.append('initialize-managed')):
                    if fail_catalog:
                        with self.assertRaisesRegex(RuntimeError, 'controlled catalog failure'):
                            wrapper.RecoveryBoundary(app, {})
                    else:
                        wrapper.RecoveryBoundary(app, {})
                for before, during, after in (
                        ('recovery-managed-initialization-starting', 'initialize-managed',
                         'recovery-managed-initialization-completed'),
                        ('recovery-catalog-build-starting', 'build-catalog',
                         'recovery-catalog-build-completed')):
                    self.assertLess(trace.index(before), trace.index(during))
                    if after in trace:
                        self.assertLess(trace.index(during), trace.index(after))
                if fail_catalog:
                    self.assertEqual(trace[-1], 'build-catalog')
                    self.assertFalse(hasattr(host, '_catalog'))
                    self.assertEqual(app.router.routes, [])
                    self.assertNotIn('recovery-boundary-completed', trace)
                else:
                    self.assertEqual(trace[-1], 'recovery-boundary-completed')
                    self.assertLess(trace.index('recovery-asset-mount-starting'), trace.index('construct-static-mount'))
                    self.assertLess(trace.index('construct-static-mount'), trace.index('recovery-asset-mount-completed'))
                    self.assertEqual(host._catalog, {catalog[0]['assetId']: catalog[0]})
                    self.assertEqual(len(app.router.routes), 1)
                self.assertNotIn(config['token'], '\n'.join(trace))

    def test_failed_diagnostic_stream_cannot_change_lifespan_cleanup_or_receipt_requirements(self):
        backend = load_wrapper('facility_checkpoint_cleanup').base
        for fail_startup in (False, True):
            with self.subTest(fail_startup=fail_startup), tempfile.TemporaryDirectory() as temporary:
                data = Path(temporary)
                library = data / 'library'
                library.mkdir()
                trace = []

                @asynccontextmanager
                async def lifespan(app):
                    trace.append('original-startup')
                    if fail_startup:
                        raise RuntimeError('controlled startup failure')
                    yield
                    trace.append('original-shutdown')

                app = SimpleNamespace(router=SimpleNamespace(lifespan_context=lifespan))
                server = SimpleNamespace(app=app, LIBRARY_DIR=library,
                    _FACILITY_LAYOUT_HOST=SimpleNamespace(close=lambda: trace.append('facility-close')),
                    _reset_agent_memory_runtime_for_tests=lambda: trace.append('memory-close'),
                    _SKILL_ROUTE_SHADOW_EXECUTOR=SimpleNamespace(shutdown=lambda **kw: trace.append('skill-close')),
                    _VIEWPORT_INTENT_EXECUTOR=SimpleNamespace(shutdown=lambda **kw: trace.append('viewport-close')))

                async def run_app(boundary):
                    async with boundary.app.router.lifespan_context(app):
                        trace.append('request-loop')

                instance = '18d6cd63-07c9-4fb1-ad2a-6835c7342ed9'
                env = {'PYTHON_DOTENV_DISABLED': '1', 'INSPECTORPRO_LIBRARY_DIR': str(library),
                       'INSPECTORPRO_DESKTOP_PYTHON_SITES': '[]', 'INSPECTORPRO_DESKTOP_INSTANCE_ID': instance}
                broken_log = Mock(write=Mock(side_effect=OSError('controlled log failure')))
                with patch.dict(sys.modules, {'server': server, 'uvicorn': SimpleNamespace(
                        run=lambda boundary, **kw: asyncio.run(run_app(boundary)))}), \
                     patch.dict(backend.os.environ, env, clear=True), patch.object(backend.os, 'chdir'), \
                     patch.object(sys, 'path', list(sys.path)), patch.object(sys, 'stderr', broken_log), \
                     patch.object(backend, 'install_fixture_write_guard'):
                    backend.enable_startup_checkpoints()
                    if fail_startup:
                        with self.assertRaisesRegex(RuntimeError, 'controlled startup failure'):
                            backend.serve(SimpleNamespace(data_root=data, port=8191), library, {})
                    else:
                        backend.serve(SimpleNamespace(data_root=data, port=8191), library, {})
                self.assertGreater(broken_log.write.call_count, 10)
                self.assertEqual(trace[-4:], ['facility-close', 'memory-close', 'skill-close', 'viewport-close'])
                receipt = backend.shutdown_receipt_path(data, instance)
                self.assertEqual(receipt.exists(), not fail_startup)
                if not fail_startup:
                    self.assertTrue(json.loads(receipt.read_text())['resourcesClosed'])


if __name__ == '__main__':
    unittest.main()
