'use strict';
const PRIVATE = ['x-inspectorpro-desktop-token','x-inspectorpro-desktop-request-id','x-inspectorpro-session','authorization','cookie'];
function cleanHeaders(headers = {}) { return Object.fromEntries(Object.entries(headers).filter(([key]) => !PRIVATE.includes(key.toLowerCase()))); }
function createRuntimeNetwork({ origin, getWindow, getCredentials, getRequestId = () => null, getOwnerSession = () => null }) {
  let enabled = true;
  const redirected = new Set();
  const requests = { saveCalls: 0, transactionRequests: {} };
  function frameAllowed(details) {
    const window = getWindow();
    if (!window || window.isDestroyed() || details.webContentsId !== window.webContents.id) return false;
    const frame = details.frame;
    // Requests without an attributable main frame (including service workers)
    // never receive application authority. Subframes are not supported here.
    return Boolean(frame && frame === window.webContents.mainFrame && !frame.detached);
  }
  function local(url) { try { const parsed = new URL(url); return parsed.protocol === 'http:' && parsed.origin === origin; } catch (_) { return false; } }
  function allowed(details) {
    if (!enabled || redirected.has(details.id) || !frameAllowed(details) || ['subFrame','webSocket','object'].includes(details.resourceType)) return false;
    if (local(details.url)) {
      const url = new URL(details.url);
      if (url.username || url.password) return false;
      return details.resourceType !== 'mainFrame' || (url.pathname === '/' && !url.hash);
    }
    return details.resourceType !== 'mainFrame' && (details.url.startsWith('blob:' + origin + '/') || details.url.startsWith('data:'));
  }
  function headers(details) {
    const requestHeaders = cleanHeaders(details.requestHeaders);
    if (!allowed(details)) return { cancel: true, requestHeaders };
    if (local(details.url)) {
      const credential = getCredentials();
      if (!/^[a-f0-9]{64}$/.test(credential || '')) return { cancel: true, requestHeaders };
      requestHeaders['X-InspectorPro-Desktop-Token'] = credential;
      const requestId = getRequestId();
      if (typeof requestId === 'string' && /^[A-Za-z0-9._-]{1,512}$/.test(requestId)) requestHeaders['X-InspectorPro-Desktop-Request-Id'] = requestId;
      const owner = getOwnerSession();
      if (typeof owner === 'string' && /^[A-Za-z0-9._-]{1,512}$/.test(owner)) requestHeaders['X-InspectorPro-Session'] = owner;
    }
    return { cancel: false, requestHeaders };
  }
  function install(session) {
    session.webRequest.onBeforeRequest((details, callback) => {
      if (local(details.url)) {
        const pathname = new URL(details.url).pathname;
        if (details.method === 'PUT' && /^\/api\/facility-layouts\/[^/]+\/[^/]+$/.test(pathname)) requests.saveCalls++;
        if (details.method === 'POST' && pathname.startsWith('/api/facility-layout-design/')) {
          requests.transactionRequests[pathname] = (requests.transactionRequests[pathname] || 0) + 1;
        }
      }
      callback({ cancel: !allowed(details) });
    });
    session.webRequest.onBeforeSendHeaders((details, callback) => callback(headers(details)));
    // Block a followed redirect even if its destination is same-origin. Never
    // carry the private credential into a different route or renderer.
    session.webRequest.onBeforeRedirect(details => redirected.add(details.id));
    session.webRequest.onCompleted(details => redirected.delete(details.id));
    session.webRequest.onErrorOccurred(details => redirected.delete(details.id));
    session.setPermissionCheckHandler(() => false);
    session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    session.on('will-download', event => event.preventDefault());
  }
  return { install, allowed, headers, getEvidence: () => JSON.parse(JSON.stringify(requests)),
    setEnabled(value) { enabled = value === true; }, get enabled() { return enabled; } };
}
module.exports = { createRuntimeNetwork, cleanHeaders };
