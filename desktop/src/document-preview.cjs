'use strict';
const { randomUUID } = require('node:crypto');
const { spawn } = require('node:child_process');
const path = require('node:path');
const MAX_BYTES = 64 * 1024 * 1024;
const HOST = 'inspectorpro-document.invalid';
// Chromium's bundled PDF viewer, observed in the pinned Electron native run.
const PDF_VIEWER = 'chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai';
const viewerResource = raw => { try { const u = new URL(raw); return (u.protocol === 'chrome-extension:' && u.host === PDF_VIEWER.split('://')[1]) || (u.protocol === 'chrome:' && u.host === 'resources'); } catch (_) { return false; } };
const fail = code => Object.assign(new Error(code), { code });
const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' })[c]);

function documentURL(raw, origin) {
  const url = new URL(raw);
  if (url.origin !== origin || url.username || url.password || url.pathname === '/') throw fail('document_address_rejected');
  if (!/^\/(?:generated|static)\//.test(url.pathname)
      && !/^\/api\/(?:parts-manual|operations-manual|specification-sheet|work-instructions|documentation|reports?|drawing-pdf|edit-sessions)\//.test(url.pathname)
      && !/\.(?:pdf|docx|xlsx|pptx|png|jpe?g|gif|webp|svg|txt|csv|md|html?)$/i.test(url.pathname)) throw fail('document_address_rejected');
  return url.href;
}
async function boundedBody(response) {
  if (+response.headers.get('content-length') > MAX_BYTES) throw fail('document_too_large');
  const chunks = []; let bytes = 0;
  for await (const chunk of response.body) {
    bytes += chunk.byteLength;
    if (bytes > MAX_BYTES) throw fail('document_too_large');
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}
function officeText(bytes, kind, python) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, [path.join(__dirname, '../runtime/document_text.py'), kind], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '', error = '', oversized = false;
    const timer = setTimeout(() => { child.kill(); }, 15000);
    child.stdout.on('data', chunk => { output += chunk; if (output.length > 2 * 1024 * 1024) { oversized = true; child.kill(); } });
    child.stderr.on('data', chunk => { error = (error + chunk).slice(-1000); });
    child.on('error', cause => { clearTimeout(timer); reject(cause); });
    child.on('close', code => { clearTimeout(timer); code === 0 && !oversized ? resolve(output) : reject(fail('document_text_unavailable')); });
    child.stdin.on('error', () => {});
    child.stdin.end(bytes);
  });
}

async function createDocumentPreview({ electron, origin, getCredential, python, fetcher = fetch }) {
  const selected = electron.session.fromPartition('ip-documents-' + randomUUID());
  const records = new Map(), blocked = []; let disposed = false, heldBytes = 0;
  const known = raw => { try { const u = new URL(raw); return u.protocol === 'https:' && u.hostname === HOST && records.has(u.pathname); } catch (_) { return false; } };
  selected.protocol.handle('https', request => {
    if (disposed || !known(request.url) || !['GET', 'HEAD'].includes(request.method)) return new Response('Not available', { status: 404 });
    const item = records.get(new URL(request.url).pathname);
    return new Response(request.method === 'HEAD' ? null : item.bytes, { headers: {
      'Content-Type': item.mime, 'Content-Disposition': 'inline', 'X-Content-Type-Options': 'nosniff',
      'Content-Length': String(item.bytes.length),
      'Content-Security-Policy': "default-src 'none'; img-src data:; style-src 'unsafe-inline'" + (item.mime === 'application/pdf' ? ' ' + PDF_VIEWER : '') + "; script-src 'none'; frame-src 'self'" + (item.mime === 'application/pdf' ? ' ' + PDF_VIEWER : '') + "; object-src 'self'; form-action 'none'; base-uri 'none'",
      'Cache-Control': 'no-store',
    } });
  });
  selected.webRequest.onBeforeRequest((d, cb) => {
    const allowed = known(d.url) || viewerResource(d.url);
    if (!allowed && blocked.length < 30) { try { const u=new URL(d.url); blocked.push(u.protocol+'//'+u.host+u.pathname); } catch (_) {} }
    cb({ cancel: !allowed });
  });
  selected.webRequest.onBeforeSendHeaders((d, cb) => cb({ requestHeaders: Object.fromEntries(Object.entries(d.requestHeaders || {}).filter(([key]) => !/^(?:x-inspectorpro-|authorization|cookie)/i.test(key))) }));
  selected.setPermissionCheckHandler(() => false);
  selected.setPermissionRequestHandler((_c, _p, cb) => cb(false));
  selected.setDevicePermissionHandler(() => false);
  selected.setDisplayMediaRequestHandler((_r, cb) => cb({}));
  selected.on('will-download', event => event.preventDefault());
  return {
    session: selected, accepts: raw => { try { documentURL(raw, origin); return true; } catch (_) { return false; } }, known, viewerResource,
    async prepare(raw) {
      const url = documentURL(raw, origin);
      const token = getCredential();
      if (!/^[a-f0-9]{64}$/.test(token || '')) throw fail('document_backend_unavailable');
      // Never follow a backend redirect with a private credential attached.
      const response = await fetcher(url, { method: 'GET', redirect: 'error', signal: AbortSignal.timeout(30000), headers: { 'X-InspectorPro-Desktop-Token': token } });
      if (!response.ok) throw fail('document_http_' + response.status);
      let bytes = await boundedBody(response);
      let mime = (response.headers.get('content-type') || '').split(';')[0].toLowerCase();
      const disposition = response.headers.get('content-disposition') || '';
      let title = /filename="([^"]+)"/i.exec(disposition)?.[1] || new URL(url).pathname.split('/').pop() || 'Document';
      const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
      try { title = decodeURIComponent(encoded || title); } catch (_) {}
      title = title.split(/[\\/]/).pop().slice(0, 200);
      const office = /\.(docx|xlsx|pptx)$/i.exec(new URL(url).pathname)?.[1]?.toLowerCase()
        || ({ 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':'docx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':'xlsx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation':'pptx' })[mime];
      if (bytes.subarray(0, 5).toString() === '%PDF-') mime = 'application/pdf';
      else if (office) {
        const text = await officeText(bytes, office, python);
        bytes = Buffer.from(`<!doctype html><meta charset="utf-8"><title>${escape(title)}</title><style>body{font:14px system-ui;margin:28px;line-height:1.5}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}h1{font-size:18px}</style><h1>${escape(title)}</h1><p>Text preview</p><pre>${escape(text)}</pre>`);
        mime = 'text/html';
      } else if (!/^(?:image\/(?:png|jpeg|gif|webp|svg\+xml)|text\/(?:plain|html|csv|markdown)|application\/json)$/.test(mime)) {
        bytes = Buffer.from(`<!doctype html><meta charset="utf-8"><title>${escape(title)}</title><h1>${escape(title)}</h1><p>Preview unavailable for this file type.</p>`);
        mime = 'text/html';
      }
      if (disposed) throw fail('document_preview_closed');
      if (heldBytes + bytes.length > 128 * 1024 * 1024) throw fail('document_preview_memory_limit');
      const key = '/' + randomUUID() + (mime === 'application/pdf' ? '.pdf' : '');
      records.set(key, { bytes, mime }); heldBytes += bytes.length;
      return { url: 'https://' + HOST + key, title, mime, bytes: bytes.length };
    },
    release(raw) { const key = new URL(raw).pathname, item = records.get(key); if (item) { heldBytes -= item.bytes.length; records.delete(key); } },
    evidence: () => ({ snapshots: records.size, heldBytes, blocked: [...blocked] }),
    async dispose() { disposed = true; records.clear(); heldBytes = 0; selected.protocol.unhandle('https'); await selected.closeAllConnections(); await selected.clearStorageData(); },
  };
}
module.exports = { createDocumentPreview, documentURL, boundedBody, MAX_BYTES, viewerResource };
