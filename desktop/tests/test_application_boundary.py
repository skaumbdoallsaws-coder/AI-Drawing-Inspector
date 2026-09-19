import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from desktop.runtime.application_profile import ApplicationProfile
from desktop.runtime.application_boundary import ApplicationBoundary


class ApplicationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.profile = ApplicationProfile({'schemaVersion': 1, 'mode': 'application', 'origin': 'http://127.0.0.1:8480',
            'profileId': 'test', 'backendId': 'backend', 'storeId': 'store', 'facilityRoot': str(Path.cwd()),
            'libraryRoot': str(Path.cwd()), 'startupLayoutId': 'fl-copy'})
        async def app(scope, receive, send):
            self.calls.append(scope)
            if scope['type'] == 'websocket': return await send({'type': 'websocket.accept'})
            await send({'type': 'http.response.start', 'status': 202, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'{}'})
        self.boundary = ApplicationBoundary(app, self.profile, 'a' * 64, 'instance',
            SimpleNamespace(principal=lambda: SimpleNamespace(tenant_id='local', principal_id='local')))

    def call(self, path, method='GET', token=True, extra=(), kind='http'):
        async def run():
            scope = {'type': kind, 'method': method, 'path': path, 'headers': [(b'host', b'127.0.0.1:8480'), *extra]}
            if token: scope['headers'].append((b'x-inspectorpro-desktop-token', b'a' * 64))
            result = []
            async def send(value): result.append(value)
            async def receive(): return {'type': 'http.request', 'body': b''}
            await self.boundary(scope, receive, send)
            return result
        return asyncio.run(run())

    def test_all_workflows_dispatch_with_private_authentication(self):
        for path, method in [('/api/agent/chat', 'POST'), ('/api/request-extraction', 'POST'),
                ('/api/facility-layouts/site-local/fl-copy', 'PUT'), ('/api/operations-manual/example/pdf', 'POST'),
                ('/api/profiles', 'GET'), ('/static/app.js', 'GET'), ('/generated/model.glb', 'GET')]:
            with self.subTest(path=path):
                self.assertEqual(self.call(path, method)[0]['status'], 202)
                self.assertFalse(any(k == b'x-inspectorpro-desktop-token' for k, _ in self.calls[-1]['headers']))
                self.assertEqual(self.call(path, method, token=False)[0]['status'], 401)

    def test_foreign_origins_and_duplicate_headers_fail_before_dispatch(self):
        for extra in [[(b'origin', b'https://evil.invalid')], [(b'sec-fetch-site', b'cross-site')],
                [(b'host', b'127.0.0.1:8480')], [(b'x-inspectorpro-desktop-token', b'a' * 64)]]:
            self.assertEqual(self.call('/', extra=extra)[0]['status'], 401)
        self.assertEqual(self.calls, [])

    def test_application_auth_headers_are_preserved(self):
        self.call('/api/agent/chat', extra=[(b'authorization', b'Bearer app-token'), (b'x-inspectorpro-session', b'normal-session')])
        self.assertIn((b'authorization', b'Bearer app-token'), self.calls[-1]['headers'])
        self.assertIn((b'x-inspectorpro-session', b'normal-session'), self.calls[-1]['headers'])

    def test_websockets_are_authenticated_too(self):
        self.assertEqual(self.call('/socket', kind='websocket', token=False)[0]['type'], 'websocket.close')
        self.assertEqual(self.call('/socket', kind='websocket')[0]['type'], 'websocket.accept')

    def test_private_runtime_binds_real_selected_stores_without_disclosing_token(self):
        value = json.loads(self.call('/api/desktop-shell/runtime')[1]['body'])
        self.assertEqual(value['stores']['facilityRoot'], self.profile.value['facilityRoot'])
        self.assertTrue(value['capabilities']['generalEditing'])
        self.assertNotIn('a' * 64, json.dumps(value))
        self.assertEqual(self.calls, [])


if __name__ == '__main__': unittest.main()
