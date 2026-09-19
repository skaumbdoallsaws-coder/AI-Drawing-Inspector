"""Private-control lifecycle contract; no application/backend process starts."""
import asyncio
from contextlib import asynccontextmanager
import io
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

from desktop.runtime.profile import RuntimeProfile
from desktop.runtime.managed_backend import PrivateControl, serve, install_runtime_guard, configure_environment


class DesktopRuntimeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='desktop lifecycle '); self.addCleanup(self.temp.cleanup)
        data = Path(self.temp.name); (data / 'library').mkdir(); (data / 'facility').mkdir()
        value = {'profileId': 'isolated', 'origin': 'http://127.0.0.1:8198', 'dataRoot': str(data), 'backendId': str(uuid.uuid4()), 'storeId': str(uuid.uuid4()), 'acceptanceLayoutId': None}
        self.profile = RuntimeProfile(value, {'storeBinding': 'b' * 64, 'owner': {'sessionId': 'session-owned', 'ownerId': 'owner-owned'}}, data)
        self.events = []
        @asynccontextmanager
        async def lifecycle(app):
            self.events.append('lifespan-entered'); yield; self.events.append('lifespan-exited')
        self.app = SimpleNamespace(router=SimpleNamespace(lifespan_context=lifecycle))
        self.host = SimpleNamespace(root=data / 'facility', principal=lambda: SimpleNamespace(tenant_id='local', principal_id='principal-local'), close=Mock())
        self.server_module = SimpleNamespace(app=self.app, LIBRARY_DIR=data / 'library', _FACILITY_LAYOUT_HOST=self.host,
            _reset_agent_memory_runtime_for_tests=Mock(), _SKILL_ROUTE_SHADOW_EXECUTOR=SimpleNamespace(shutdown=Mock()), _VIEWPORT_INTENT_EXECUTOR=SimpleNamespace(shutdown=Mock()))
        self.private = {'credential': 'a' * 64, 'instanceId': str(uuid.uuid4())}

    def test_runtime_guard_limits_python_writes_and_denies_helpers_without_installing_global_hook(self):
        with patch('sys.addaudithook') as add:
            install_runtime_guard(self.profile.data)
        audit = add.call_args.args[0]
        audit('open', (str(self.profile.data / 'local.json'), 'w', os.O_WRONLY))
        audit('open', (str(Path(self.temp.name).parent / 'read-only.json'), 'r', 0))
        audit('sqlite3.connect', (':memory:',))
        for event, args in [('open', (str(self.profile.data.parent / 'foreign.json'), 'w', os.O_WRONLY)),
                            ('os.rename', (str(self.profile.data / 'owned'), str(self.profile.data.parent / 'foreign'))),
                            ('subprocess.Popen', ('native-helper',)), ('os.system', ('any-command',))]:
            with self.subTest(event=event), self.assertRaises(PermissionError): audit(event, args)

    def test_runtime_environment_removes_provider_credentials_and_pins_actual_roots(self):
        import sys
        previous = sys.dont_write_bytecode
        try:
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-do-not-inherit', 'PYTHONPATH': 'foreign-search-path', 'INSPECTORPRO_FACILITY_LAYOUT_ROOT': 'foreign-root'}):
                configure_environment(self.profile)
                self.assertNotIn('OPENAI_API_KEY', os.environ)
                self.assertNotIn('PYTHONPATH', os.environ)
                self.assertEqual(os.environ['INSPECTORPRO_FACILITY_LAYOUT_ROOT'], str(self.profile.data / 'facility'))
                self.assertEqual(os.environ['INSPECTORPRO_LIBRARY_DIR'], str(self.profile.data / 'library'))
                self.assertEqual(os.environ['PYTHON_DOTENV_DISABLED'], '1')
                self.assertEqual(os.environ['INSPECTORPRO_FACILITY_LAYOUT_CONSTRUCTION_SAGE'], '0')
                self.assertTrue(sys.dont_write_bytecode)
        finally: sys.dont_write_bytecode = previous

    def test_ready_follows_listening_and_shutdown_receipt_follows_actual_cleanup(self):
        control = PrivateControl(io.BytesIO()); outputs = []
        events, application = self.events, self.app
        class Server:
            def __init__(self, config): self.started = False; self.should_exit = False
            async def serve(self):
                async with application.router.lifespan_context(application):
                    events.append('listener-bound'); self.started = True
                    while not self.should_exit: await asyncio.sleep(0.001)
        def emit(kind, value):
            outputs.append((kind, value)); events.append(kind)
            if kind == 'READY': control.reason = 'private-channel-shutdown'; control.request_id = str(uuid.uuid4()); control.stop.set()
        with patch.dict('sys.modules', {'server': self.server_module, 'uvicorn': SimpleNamespace(Config=lambda *args, **kwargs: None, Server=Server)}), patch('desktop.runtime.managed_backend.emit', emit):
            asyncio.run(serve(self.profile, self.private, control))
        self.assertLess(events.index('listener-bound'), events.index('READY'))
        self.assertLess(events.index('lifespan-exited'), events.index('SHUTDOWN'))
        receipt = outputs[-1][1]
        self.assertTrue(receipt['resourcesClosed']); self.assertTrue(receipt['lifespanStopped'])
        self.assertEqual(receipt['requestId'], control.request_id)
        self.assertNotIn('credential', str(outputs)); self.assertNotIn('a' * 64, str(outputs))
        self.host.close.assert_called_once()
        self.server_module._SKILL_ROUTE_SHADOW_EXECUTOR.shutdown.assert_called_once_with(wait=True, cancel_futures=True)

    def test_failed_cleanup_cannot_emit_successful_receipt(self):
        self.host.close.side_effect = RuntimeError('private context must not appear in receipt')
        control = PrivateControl(io.BytesIO()); outputs = []; application = self.app
        class Server:
            def __init__(self, config): self.started = False; self.should_exit = False
            async def serve(self):
                async with application.router.lifespan_context(application):
                    self.started = True
                    while not self.should_exit: await asyncio.sleep(0.001)
        def emit(kind, value):
            outputs.append((kind, value))
            if kind == 'READY': control.stop.set()
        with patch.dict('sys.modules', {'server': self.server_module, 'uvicorn': SimpleNamespace(Config=lambda *args, **kwargs: None, Server=Server)}), patch('desktop.runtime.managed_backend.emit', emit):
            with self.assertRaises(RuntimeError): asyncio.run(serve(self.profile, self.private, control))
        self.assertFalse(outputs[-1][1]['resourcesClosed'])
        self.assertEqual(outputs[-1][1]['cleanupErrors'], ['RuntimeError'])
        self.assertNotIn('private context', str(outputs))
