import asyncio
from copy import deepcopy
from http.cookies import SimpleCookie
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from desktop.runtime.profile import RuntimeProfile
from desktop.runtime.boundary import DesktopBoundary, COOKIE_NAME, IDENTITY_PATH, RUNTIME_PATH, PAIR_PATH, PAIRED_PATH, CSRF_PATH, LOOKUP_PATH


class DesktopRuntimeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='desktop boundary '); self.addCleanup(self.temp.cleanup)
        data = Path(self.temp.name)
        value = {'schemaVersion': 1, 'mode': 'managed', 'profileId': 'isolated', 'origin': 'http://127.0.0.1:8198',
                 'dataRoot': str(data), 'backendId': str(uuid.uuid4()), 'storeId': str(uuid.uuid4()), 'acceptanceLayoutId': 'fl-isolated'}
        self.profile = RuntimeProfile(value, {'storeBinding': 'b' * 64, 'owner': {'sessionId': 'session-owned', 'ownerId': 'owner-owned'}}, data)
        self.calls, self.now = [], 100.0
        self.host = SimpleNamespace(principal=lambda: SimpleNamespace(tenant_id='local', principal_id='principal-local'))
        async def app(scope, receive, send):
            self.calls.append(scope)
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'{"application":true}'})
        self.app = app
        self.boundary = DesktopBoundary(app, self.profile, 'a' * 64, str(uuid.uuid4()), self.host, clock=lambda: self.now)

    async def request(self, path='/', method='GET', *, token=False, value=None, cookie=None, csrf=None, origin=None, host='127.0.0.1:8198', extra=(), boundary=None, raw=None):
        headers = [(b'host', host.encode()), *extra]
        if token: headers.append((b'x-inspectorpro-desktop-token', ('a' * 64 if token is True else token).encode()))
        if origin is not None: headers.append((b'origin', origin.encode()))
        if cookie: headers.append((b'cookie', cookie.encode()))
        if csrf: headers.append((b'x-inspectorpro-csrf', csrf.encode()))
        if value is not None: headers.append((b'content-type', b'application/json'))
        scope = {'type': 'http', 'method': method, 'path': path, 'headers': headers, 'query_string': b''}
        if raw is not None: scope['raw_path'] = raw
        async def receive(): return {'type': 'http.request', 'body': json.dumps(value).encode() if value is not None else b'', 'more_body': False}
        messages = []
        async def send(message): messages.append(message)
        await (boundary or self.boundary)(scope, receive, send)
        response = next(item for item in messages if item['type'] == 'http.response.start')
        body = b''.join(item.get('body', b'') for item in messages if item['type'] == 'http.response.body')
        return response['status'], body, dict(response.get('headers', []))

    def call(self, *args, **kwargs): return asyncio.run(self.request(*args, **kwargs))

    def pair(self):
        status, body, headers = self.call(PAIR_PATH, 'POST', value={'token': 'a' * 64}, origin=self.profile.origin)
        self.assertEqual(status, 200)
        cookie = SimpleCookie(); cookie.load(headers[b'set-cookie'].decode())
        return COOKIE_NAME + '=' + cookie[COOKIE_NAME].value, json.loads(body)['csrfToken'], headers

    def test_every_private_surface_requires_authentication_before_dispatch(self):
        for path, method in [('/', 'GET'), ('/static/private.js', 'GET'), ('/generated/private.glb', 'HEAD'),
                             ('/api/profiles', 'GET'), ('/api/agent/chat/stream', 'POST'), (RUNTIME_PATH, 'GET'), (LOOKUP_PATH, 'POST')]:
            with self.subTest(path=path): self.assertEqual(self.call(path, method)[0], 401)
        self.assertEqual(self.calls, [])

    def test_public_identity_exposes_no_private_owner_principal_credential_or_paths(self):
        status, body, _ = self.call(IDENTITY_PATH)
        self.assertEqual(status, 200)
        value = json.loads(body)
        self.assertEqual(value['instanceId'], self.boundary.instance_id)
        for key in ('credential', 'owner', 'principalId', 'dataRoot', 'roots'): self.assertNotIn(key, value)
        self.assertNotIn(('a' * 64).encode(), body)
        self.assertEqual(self.calls, [])

    def test_header_authority_reads_actual_app_and_runtime_only_from_exact_origin(self):
        self.assertEqual(self.call('/static/app.js', token=True)[0], 200)
        self.assertEqual(len(self.calls), 1)
        status, body, _ = self.call(RUNTIME_PATH, token=True)
        self.assertEqual(status, 200); value = json.loads(body)
        self.assertEqual(value['owner'], self.profile.owner)
        self.assertEqual(value['identity']['principalId'], 'principal-local')
        for kwargs in [{'origin': 'http://evil.invalid'}, {'host': 'localhost:8198'}, {'token': 'b' * 64}, {'extra': [(b'sec-fetch-site', b'cross-site')]}]:
            changed = dict(token=True, **kwargs) if 'token' not in kwargs else kwargs
            self.assertIn(self.call(RUNTIME_PATH, **changed)[0], (401, 403))

    def test_unknown_reads_mutations_streams_and_native_routes_are_capability_denied(self):
        for path, method in [('/api/bridge/status', 'GET'), ('/api/admin/memory/health', 'GET'),
                             ('/api/agent/chat', 'POST'), ('/api/agent/chat/stream', 'GET'),
                             ('/api/request-extraction', 'POST'), ('/api/facility-layouts/site-local/fl-isolated', 'PUT'),
                             ('/__facility-recovery__/proposal', 'POST'), ('/api/desktop-shell/shutdown', 'POST')]:
            with self.subTest(path=path): self.assertEqual(self.call(path, method, token=True)[0], 403)
        self.assertEqual(self.calls, [])

    def test_acceptance_preview_is_exact_document_only_and_never_enables_save(self):
        self.assertEqual(self.call('/api/facility-layouts/site-local/fl-isolated/preview', 'POST', token=True, value={})[0], 200)
        self.assertEqual(self.call('/api/facility-layouts/site-local/fl-other/preview', 'POST', token=True, value={})[0], 403)
        no_acceptance = RuntimeProfile(dict(self.profile.value, acceptanceLayoutId=None), self.profile.marker, self.profile.data)
        closed = DesktopBoundary(self.app, no_acceptance, 'a' * 64, str(uuid.uuid4()), self.host)
        self.assertEqual(self.call('/api/facility-layouts/site-local/fl-isolated/preview', 'POST', token=True, value={}, boundary=closed)[0], 403)

    def test_websockets_are_denied_without_reaching_application_even_with_credential(self):
        for token in (False, True):
            messages = []
            async def send(message): messages.append(message)
            headers = [(b'host', b'127.0.0.1:8198')]
            if token: headers.append((b'x-inspectorpro-desktop-token', b'a' * 64))
            asyncio.run(self.boundary({'type': 'websocket', 'path': '/ws', 'headers': headers}, None, send))
            self.assertEqual(messages, [{'type': 'websocket.close', 'code': 1008}])
        self.assertEqual(self.calls, [])

    def test_pairing_uses_http_only_strict_cookie_and_csrf_never_launch_token_cookie(self):
        cookie, csrf, headers = self.pair()
        text = headers[b'set-cookie'].decode()
        self.assertIn('HttpOnly', text); self.assertIn('SameSite=strict', text); self.assertIn('Path=/', text)
        self.assertNotIn('a' * 64, text)
        self.assertEqual(self.call('/static/app.js', cookie=cookie)[0], 403)
        status, body, _ = self.call(CSRF_PATH, cookie=cookie)
        self.assertEqual(status, 200); self.assertEqual(json.loads(body)['csrfToken'], csrf)
        route = '/api/facility-layouts/site-local/fl-isolated/preview'
        for kwargs in [{}, {'csrf': csrf}, {'origin': self.profile.origin}, {'csrf': 'wrong', 'origin': self.profile.origin}]:
            self.assertEqual(self.call(route, 'POST', cookie=cookie, value={}, **kwargs)[0], 401)
        self.assertEqual(self.call(route, 'POST', cookie=cookie, csrf=csrf, origin=self.profile.origin, value={})[0], 403)
        self.assertEqual(self.calls, [])

    def test_successful_pairing_stops_at_protected_read_only_confirmation(self):
        self.assertEqual(self.call(PAIRED_PATH)[0], 401)
        status, body, _ = self.call(PAIR_PATH, 'POST', value={'token': 'a' * 64}, origin=self.profile.origin)
        value = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(value['nextPath'], PAIRED_PATH)
        self.assertIs(value['applicationAccess'], False)
        cookie, csrf, _ = self.pair()
        status, body, headers = self.call(PAIRED_PATH, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(b'Browser pairing verified', body)
        self.assertIn(b'remain disabled', body)
        self.assertNotIn(b'<script', body); self.assertNotIn(b'href=', body)
        self.assertIn(b"default-src 'none'", headers[b'content-security-policy'])
        self.assertNotIn(('a' * 64).encode(), body)
        self.assertEqual(self.call(RUNTIME_PATH, cookie=cookie)[0], 200)
        for path, method in [('/', 'GET'), ('/static/app.js', 'GET'), ('/generated/private.glb', 'GET'),
                             ('/api/profiles', 'GET'), (LOOKUP_PATH, 'POST'),
                             ('/api/facility-layout-design/site-local/fl-isolated/proposals/proposal-1/apply/prepare', 'POST')]:
            with self.subTest(path=path):
                status, body, _ = self.call(path, method, cookie=cookie, csrf=csrf, origin=self.profile.origin, value={} if method == 'POST' else None)
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(body)['error']['code'], 'desktop_paired_application_not_accepted')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.call('/', token=True)[0], 200)

    def test_pairing_rejects_cross_origin_nonjson_wrong_tokens_and_is_rate_limited(self):
        self.assertEqual(self.call(PAIR_PATH, 'POST', value={'token': 'a' * 64}, origin='http://evil.invalid')[0], 403)
        self.assertEqual(self.call(PAIR_PATH, 'POST', origin=self.profile.origin)[0], 401)
        for _ in range(7): self.assertEqual(self.call(PAIR_PATH, 'POST', value={'token': 'wrong'}, origin=self.profile.origin)[0], 401)
        self.assertEqual(self.call(PAIR_PATH, 'POST', value={'token': 'a' * 64}, origin=self.profile.origin)[0], 429)
        self.now += 61; self.pair()

    def test_paired_session_expires_and_is_not_inherited_by_new_backend_launch(self):
        cookie, _, _ = self.pair()
        restarted = DesktopBoundary(self.app, self.profile, 'b' * 64, str(uuid.uuid4()), self.host)
        self.assertEqual(self.call('/', cookie=cookie, boundary=restarted)[0], 401)
        self.now += 8 * 60 * 60 + 1
        self.assertEqual(self.call('/', cookie=cookie)[0], 401)

    def test_ambiguous_authority_and_encoded_traversal_are_rejected(self):
        for kwargs in [{'extra': [(b'host', b'evil.invalid')]}, {'extra': [(b'x-inspectorpro-desktop-token', b'a' * 64)]}, {'raw': b'/static/%2e%2e/private'}]:
            self.assertEqual(self.call('/static/file', token=True, **kwargs)[0], 403)
        for route in ['/static/../secret', '/static/..\\secret', '//api/profiles']:
            self.assertEqual(self.call(route, token=True)[0], 403)
        self.assertEqual(self.calls, [])

    def test_pair_page_has_no_credential_url_persistence_or_cross_origin_frame_access(self):
        status, body, headers = self.call(PAIR_PATH)
        self.assertEqual(status, 200)
        self.assertIn(b'frame-ancestors \'none\'', headers[b'content-security-policy'])
        self.assertIn(b'type="password"', body)
        self.assertIn(b"location.replace('/__desktop__/paired')", body)
        self.assertNotIn(b"location.replace('/')", body)
        self.assertNotIn(b'localStorage', body); self.assertNotIn(b'sessionStorage', body)
        self.assertNotIn(('a' * 64).encode(), body)
