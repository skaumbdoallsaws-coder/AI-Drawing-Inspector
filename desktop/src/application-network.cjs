'use strict';
const PRIVATE = /^x-inspectorpro-desktop-/i;
function createApplicationNetwork({ origin, getWindow, getCredential, confirmPermission }) {
  let enabled = true;
  const evidence = { localRequests: 0, refused: 0, saveCalls: 0, refusedRequests: [], apiRequests: [], apiResponses: [] };
  const parse = value => { try { return new URL(value); } catch (_) { return null; } };
  function local(value) {
    const u = parse(value);
    return !!u && !u.username && !u.password && (u.origin === origin || u.origin === origin.replace('http:', 'ws:'));
  }
  function owned(contents) {
    const w = getWindow();
    return !!w && !w.isDestroyed() && contents === w.webContents;
  }
  function frameAllowed(d) {
    const w = getWindow();
    if (!w || w.isDestroyed() || d.webContentsId !== w.webContents.id) return false;
    if (d.frame) {
      if (d.frame.detached) return false;
      if (d.frame === w.webContents.mainFrame) return !d.frame.url || d.frame.url === 'about:blank' || local(d.frame.url);
      return d.frame.top === w.webContents.mainFrame && local(d.frame.url);
    }
    // Dedicated workers may omit frame metadata. Attribution to the owned
    // webContents and same-origin initiator are both required in that case.
    return d.initiator === origin;
  }
  function allowed(d) {
    if (!enabled || !frameAllowed(d)) return false;
    const u = parse(d.url);
    if (!u || u.username || u.password) return false;
    if (d.resourceType === 'mainFrame') return u.origin === origin && u.pathname === '/';
    if (local(d.url)) return true;
    if (d.url.startsWith('blob:' + origin + '/') || u.protocol === 'data:') return true;
    // Provider/browser fetches keep ordinary CORS. External content never gets
    // the private token, executes as app script, or navigates the app window.
    return ['https:', 'wss:'].includes(u.protocol) && ['xhr', 'webSocket', 'image', 'media', 'font'].includes(d.resourceType);
  }
  function headers(d) {
    const h = Object.fromEntries(Object.entries(d.requestHeaders || {}).filter(([k]) => !PRIVATE.test(k)));
    if (!allowed(d)) return { cancel: true, requestHeaders: h };
    if (local(d.url)) {
      const token = getCredential();
      if (!/^[a-f0-9]{64}$/.test(token || '')) return { cancel: true, requestHeaders: h };
      h['X-InspectorPro-Desktop-Token'] = token;
    }
    return { cancel: false, requestHeaders: h };
  }
  function trustedPermission(contents, details = {}) {
    return enabled && owned(contents) && local(contents.getURL())
      && details.isMainFrame !== false && (!details.requestingUrl || local(details.requestingUrl))
      && (!details.requestingOrigin || details.requestingOrigin === origin);
  }
  function install(session) {
    session.webRequest.onBeforeRequest((d, cb) => {
      const yes = allowed(d);
      if (!yes) {
        evidence.refused++;
        if (evidence.refusedRequests.length < 100) {
          const u = parse(d.url);
          evidence.refusedRequests.push({ resourceType: d.resourceType, method: d.method,
            destination: u ? u.origin + u.pathname : 'invalid', ownedFrame: frameAllowed(d), enabled });
        }
      }
      if (yes && local(d.url)) {
        evidence.localRequests++;
        if (new URL(d.url).pathname.startsWith('/api/') && evidence.apiRequests.length < 200) {
          evidence.apiRequests.push({ id: d.id, method: d.method, path: new URL(d.url).pathname, time: Date.now() });
        }
        if (d.method === 'PUT' && /^\/api\/facility-layouts\/[^/]+\/[^/]+$/.test(new URL(d.url).pathname)) evidence.saveCalls++;
      }
      cb({ cancel: !yes });
    });
    session.webRequest.onBeforeSendHeaders((d, cb) => cb(headers(d)));
    session.webRequest.onCompleted?.(d => {
      if (local(d.url) && new URL(d.url).pathname.startsWith('/api/') && evidence.apiResponses.length < 200) {
        evidence.apiResponses.push({ id: d.id, status: d.statusCode, path: new URL(d.url).pathname, time: Date.now() });
      }
    });
    session.setPermissionCheckHandler((c, permission, requestingOrigin, details) => trustedPermission(c, { ...details, requestingOrigin })
      && ['pointerLock', 'fullscreen', 'clipboard-sanitized-write', 'media', 'clipboard-read'].includes(permission));
    session.setPermissionRequestHandler(async (c, permission, cb, details) => {
      let yes = false;
      try {
        if (trustedPermission(c, details)) {
          if (['pointerLock', 'fullscreen', 'clipboard-sanitized-write'].includes(permission)) yes = true;
          else if (permission === 'clipboard-read') yes = await confirmPermission('Read the clipboard?');
          else if (permission === 'media' && details?.mediaTypes?.length
              && details.mediaTypes.every(t => t === 'audio')) yes = await confirmPermission('Use the microphone for voice input?');
        }
      } finally { cb(yes && trustedPermission(c, details)); }
    });
    session.on('will-download', (event, item, contents) => {
      const urls = item.getURLChain();
      if (!enabled || !owned(contents) || !urls.length || urls.some(u => !local(u) && !u.startsWith('blob:' + origin + '/'))) {
        event.preventDefault(); return;
      }
      item.setSaveDialogOptions({ title: 'Export from InspectorPro' });
    });
  }
  return { install, allowed, headers, local, trustedPermission, setEnabled(v) { enabled = v === true; },
    getEvidence: () => ({ ...evidence }) };
}
module.exports = { createApplicationNetwork };
