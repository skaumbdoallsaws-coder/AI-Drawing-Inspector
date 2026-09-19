"""Authenticate the owned native renderer, then use the unchanged app routes.

The launch token is not a replacement for application authorization, feature
flags or transaction validation. It is stripped before entering the app.
"""
import hmac
import os
import re
from starlette.responses import JSONResponse
from desktop.runtime.boundary import DesktopBoundary, TOKEN_HEADER, RUNTIME_PATH


class ApplicationBoundary:
    headers = staticmethod(DesktopBoundary.headers)
    valid_target = DesktopBoundary.valid_target

    def __init__(self, app, profile, credential, instance_id, host):
        if not re.fullmatch(r'[a-f0-9]{64}', credential): raise ValueError('Invalid launch credential')
        self.app, self.profile, self.instance_id, self.host = app, profile, instance_id, host
        self._credential = credential.encode()

    def runtime(self):
        principal = self.host.principal()
        p = self.profile.value
        return {'schemaVersion': 1, 'product': 'InspectorPro', 'mode': 'desktop-application',
                'profileId': p['profileId'], 'origin': p['origin'], 'instanceId': self.instance_id,
                'processId': os.getpid(), 'identity': {'backendId': p['backendId'], 'storeId': p['storeId'],
                'principalId': principal.principal_id}, 'storeBinding': self.profile.store_binding,
                'stores': {k: p[k] for k in ('facilityRoot', 'libraryRoot')},
                'capabilities': {'generalEditing': True, 'applicationRoutes': True},
                'document': {'tenantId': principal.tenant_id, 'siteId': 'site-local', 'documentId': self.profile.layout_id}}

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan': return await self.app(scope, receive, send)
        if scope['type'] not in {'http', 'websocket'}: return
        try:
            headers = self.headers(scope)
            valid = self.valid_target(scope, headers) and hmac.compare_digest(headers.get(TOKEN_HEADER, b''), self._credential)
        except ValueError: valid = False
        if not valid:
            if scope['type'] == 'websocket': return await send({'type': 'websocket.close', 'code': 1008})
            return await JSONResponse({'error': {'code': 'desktop_authentication_required'}}, status_code=401,
                                      headers={'Cache-Control': 'no-store'})(scope, receive, send)
        if scope['type'] == 'http' and scope['path'] == RUNTIME_PATH and scope['method'] == 'GET':
            return await JSONResponse(self.runtime(), headers={'Cache-Control': 'no-store'})(scope, receive, send)
        clean_scope = {**scope, 'headers': [(k, v) for k, v in scope.get('headers', []) if k.lower() != TOKEN_HEADER]}
        return await self.app(clean_scope, receive, send)
