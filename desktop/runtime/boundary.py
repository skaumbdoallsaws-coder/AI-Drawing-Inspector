"""Outer authentication and capability boundary for the developer desktop host.

The normal web server never imports this module. No request can reach that app
until the exact origin, launch authority and current milestone capability pass.
"""
from __future__ import annotations
import asyncio
from http.cookies import CookieError, SimpleCookie
import hmac
import json
import os
import re
import secrets
import time

from starlette.responses import HTMLResponse, JSONResponse
from desktop.runtime.transaction_journal import TransactionJournal

IDENTITY_PATH = '/api/desktop-shell/identity'
RUNTIME_PATH = '/api/desktop-shell/runtime'
PAIR_PATH = '/__desktop__/pair'
PAIRED_PATH = '/__desktop__/paired'
CSRF_PATH = '/__desktop__/csrf'
LOOKUP_PATH = '/api/desktop-shell/recovery/transaction'
TOKEN_HEADER = b'x-inspectorpro-desktop-token'
REQUEST_HEADER = b'x-inspectorpro-desktop-request-id'
COOKIE_NAME = 'inspectorpro_desktop_session'
READ_ROUTES = {'/', '/favicon.ico', '/api/profiles', '/api/facility-layout-bootstrap',
               '/api/industrial-assets', '/api/agent/chat/streaming-status'}


def permitted(profile, method, path):
    if method in {'GET', 'HEAD'}:
        return path in READ_ROUTES or path.startswith(('/static/', '/generated/')) or (
            profile.layout_id is not None and path == '/api/facility-layouts/site-local/' + profile.layout_id)
    if method != 'POST' or profile.layout_id is None: return False
    if path == '/api/facility-layouts/site-local/' + profile.layout_id + '/preview': return True
    prefix = '/api/facility-layout-design/site-local/' + profile.layout_id
    return bool(re.fullmatch(re.escape(prefix) + r'/(?:proposals/[A-Za-z0-9_-]+/apply/prepare|transactions/[A-Za-z0-9_-]+/(?:apply/(?:commit|acknowledge)|undo/(?:prepare|acknowledge)))', path))


class DesktopBoundary:
    def __init__(self, app, profile, credential, instance_id, host, *, clock=time.monotonic):
        self.app, self.profile, self.instance_id, self.host = app, profile, instance_id, host
        if not isinstance(credential, str) or not re.fullmatch(r'[a-f0-9]{64}', credential):
            raise ValueError('Desktop launch credential is invalid')
        self._credential = credential.encode()
        self.clock, self.sessions, self.pair_failures = clock, {}, []
        self.journal = TransactionJournal(profile, host, instance_id)
        self.dispatch_lock = asyncio.Lock()

    def runtime(self):
        principal = self.host.principal()
        identity = {key: self.profile.value[key] for key in ('backendId', 'storeId')}
        identity['principalId'] = principal.principal_id
        return {**self.profile.identity(self.instance_id), 'identity': identity, 'principalId': principal.principal_id,
                'origin': self.profile.origin, 'processId': os.getpid(), 'owner': self.profile.owner,
                'document': {'tenantId': principal.tenant_id, 'siteId': 'site-local', 'documentId': self.profile.layout_id}}

    @staticmethod
    def headers(scope):
        result = {}
        for key, value in scope.get('headers', []):
            key = key.lower()
            if key in {b'host', b'origin', TOKEN_HEADER, REQUEST_HEADER, b'cookie', b'x-inspectorpro-csrf', b'x-inspectorpro-session'} and key in result:
                raise ValueError('Ambiguous desktop request authority')
            result[key] = value
        return result

    def valid_target(self, scope, headers):
        path = scope.get('path', '')
        raw = scope.get('raw_path', path.encode()).lower()
        return (headers.get(b'host') == self.profile.origin.removeprefix('http://').encode()
                and headers.get(b'origin') in {None, self.profile.origin.encode()}
                and headers.get(b'sec-fetch-site') not in {b'cross-site'}
                and path.startswith('/') and '\\' not in path and '\x00' not in path and '//' not in path
                and not any(part in {'.', '..'} for part in path.split('/'))
                and not any(fragment in raw for fragment in (b'%2e', b'%2f', b'%5c', b'%00')))

    def authority(self, headers, method):
        presented = headers.get(TOKEN_HEADER)
        if presented is not None:
            return ('launch', None) if hmac.compare_digest(presented, self._credential) else (None, None)
        try:
            cookies = SimpleCookie(); cookies.load(headers.get(b'cookie', b'').decode('ascii'))
            cookie = cookies.get(COOKIE_NAME)
            session = self.sessions.get(cookie.value) if cookie else None
        except (UnicodeError, ValueError, CookieError): session = None
        if not session or session['expires'] <= self.clock(): return None, None
        if method not in {'GET', 'HEAD'} and (headers.get(b'origin') != self.profile.origin.encode()
                or not hmac.compare_digest(headers.get(b'x-inspectorpro-csrf', b''), session['csrf'].encode())):
            return None, None
        return 'paired', session

    @staticmethod
    async def body(receive, limit):
        body = bytearray()
        while True:
            message = await asyncio.wait_for(receive(), 10)
            if message['type'] != 'http.request': raise ValueError('Desktop request disconnected')
            body.extend(message.get('body', b''))
            if len(body) > limit: raise ValueError('Desktop request exceeds its body limit')
            if not message.get('more_body'): return bytes(body)

    def pair_page(self):
        nonce = secrets.token_urlsafe(24)
        html = '''<!doctype html><html><head><meta charset="utf-8"><title>Pair InspectorPro</title></head>
<body><main><h1>Pair this browser with InspectorPro</h1><p>This page supports an authorized local development check. Browser access to the application is not available.</p>
<form id="pair"><label>Pairing credential <input id="token" type="password" autocomplete="off" required></label><button>Pair browser</button></form><p id="status" role="status"></p></main>
<script nonce="''' + nonce + '''">document.getElementById('pair').addEventListener('submit',async e=>{e.preventDefault();const input=document.getElementById('token');const token=input.value;input.value='';try{const r=await fetch('/__desktop__/pair',{method:'POST',redirect:'error',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});if(!r.ok)throw Error('Pairing failed. Check the credential and try again.');location.replace('/__desktop__/paired');}catch(error){document.getElementById('status').textContent=error.message;}});</script></body></html>'''
        return HTMLResponse(html, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'none'; script-src 'nonce-" + nonce + "'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})

    @staticmethod
    def paired_page():
        return HTMLResponse('''<!doctype html><html><head><meta charset="utf-8"><title>InspectorPro browser pairing</title></head>
<body><main><h1>Browser pairing verified</h1><p>This read-only page confirms the local pairing check.</p>
<p>Application access, editing, recovery actions, and embedded browsing remain disabled for this browser. Credential delivery through the desktop interface is not available yet.</p>
<p>You may close this tab.</p></main></body></html>''', headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan': return await self.app(scope, receive, send)
        if scope['type'] not in {'http', 'websocket'}: return
        def response(code, status=403):
            return JSONResponse({'error': {'code': code}}, status_code=status, headers={'Cache-Control': 'no-store'})
        try: headers = self.headers(scope)
        except ValueError: headers = {}; target_valid = False
        else: target_valid = self.valid_target(scope, headers)
        if scope['type'] == 'websocket':
            # Streaming and browser sockets have no accepted developer capability
            # yet. No unauthenticated or authenticated WS reaches application code.
            return await send({'type': 'websocket.close', 'code': 1008})
        path, method = scope['path'], scope['method']
        if not target_valid: return await response('desktop_origin_rejected')(scope, receive, send)
        if path == IDENTITY_PATH and method == 'GET':
            return await JSONResponse(self.profile.identity(self.instance_id), headers={'Cache-Control': 'no-store'})(scope, receive, send)
        if path == PAIR_PATH and method == 'GET': return await self.pair_page()(scope, receive, send)
        if path == PAIR_PATH and method == 'POST':
            self.pair_failures = [item for item in self.pair_failures if item > self.clock() - 60]
            if len(self.pair_failures) >= 8: return await response('desktop_pairing_rate_limited', 429)(scope, receive, send)
            try:
                if headers.get(b'origin') != self.profile.origin.encode() or headers.get(b'content-type', b'').split(b';')[0].strip() != b'application/json':
                    raise ValueError('Pairing requires a same-origin JSON exchange')
                value = json.loads(await self.body(receive, 1024))
                if set(value) != {'token'} or not isinstance(value['token'], str) or not hmac.compare_digest(value['token'].encode(), self._credential):
                    raise ValueError('Pairing credential did not match')
            except (ValueError, TypeError, asyncio.TimeoutError):
                self.pair_failures.append(self.clock())
                return await response('desktop_pairing_rejected', 401)(scope, receive, send)
            self.sessions = {key: value for key, value in self.sessions.items() if value['expires'] > self.clock()}
            if len(self.sessions) >= 16: return await response('desktop_pairing_limit', 429)(scope, receive, send)
            cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.sessions[cookie] = {'csrf': csrf, 'expires': self.clock() + 8 * 60 * 60}
            result = JSONResponse({'paired': True, 'csrfToken': csrf, 'principalId': self.host.principal().principal_id,
                                   'nextPath': PAIRED_PATH, 'applicationAccess': False}, headers={'Cache-Control': 'no-store'})
            result.set_cookie(COOKIE_NAME, cookie, httponly=True, samesite='strict', path='/', max_age=8 * 60 * 60)
            return await result(scope, receive, send)
        authority, paired = self.authority(headers, method)
        if authority is None: return await response('desktop_authentication_required', 401)(scope, receive, send)
        if path == RUNTIME_PATH and method == 'GET':
            return await JSONResponse(self.runtime(), headers={'Cache-Control': 'no-store'})(scope, receive, send)
        if path == CSRF_PATH and method == 'GET':
            return await JSONResponse({'csrfToken': paired['csrf'] if paired else None}, headers={'Cache-Control': 'no-store'})(scope, receive, send)
        if path == PAIRED_PATH and method == 'GET':
            return await self.paired_page()(scope, receive, send)
        # Pairing verifies the boundary only. Ordinary browser clients do not
        # have the desktop preload's input lock or recovery lifecycle; never
        # let a direct URL turn the read-only confirmation into application access.
        if authority == 'paired':
            return await response('desktop_paired_application_not_accepted')(scope, receive, send)
        if path == LOOKUP_PATH and method == 'POST' and self.profile.layout_id is not None:
            try:
                value = json.loads(await self.body(receive, 16 * 1024 * 1024))
                result = self.journal.lookup(value)
                return await JSONResponse(result, headers={'Cache-Control': 'no-store'})(scope, receive, send)
            except Exception:
                return await response('desktop_recovery_unresolved', 409)(scope, receive, send)
        if not permitted(self.profile, method, path): return await response('desktop_capability_not_accepted')(scope, receive, send)
        if method == 'POST' and path.startswith('/api/facility-layout-design/'):
            try:
                body = await self.body(receive, 16 * 1024 * 1024)
                value = json.loads(body)
                if not isinstance(value, dict): raise ValueError('Transaction body must be an object')
                request_id = headers.get(REQUEST_HEADER, b'').decode('ascii')
                session_id = headers.get(b'x-inspectorpro-session', b'').decode('ascii')
                async with self.dispatch_lock:
                    tracked, replay = self.journal.prepare_dispatch(path, value, request_id, session_id)
                    if replay is not None:
                        return await JSONResponse(replay['body'], status_code=replay['status'], headers={'Cache-Control': 'no-store', 'X-InspectorPro-Durable-Reply': 'true'})(scope, receive, send)
                    delivered = False
                    async def replay_receive():
                        nonlocal delivered
                        if not delivered:
                            delivered = True
                            return {'type': 'http.request', 'body': body, 'more_body': False}
                        return await receive()
                    messages, size = [], 0
                    async def capture(message):
                        nonlocal size
                        size += len(message.get('body', b''))
                        if size > 32 * 1024 * 1024: raise ValueError('Transaction reply exceeds the durable journal limit')
                        messages.append(message)
                    await self.app(scope, replay_receive, capture)
                    status = next(item['status'] for item in messages if item['type'] == 'http.response.start')
                    result = json.loads(b''.join(item.get('body', b'') for item in messages if item['type'] == 'http.response.body'))
                    self.journal.finish_dispatch(path, tracked, status, result)
                    for message in messages: await send(message)
                    return
            except Exception:
                return await response('desktop_transaction_recovery_required', 409)(scope, receive, send)
        return await self.app(scope, receive, send)
