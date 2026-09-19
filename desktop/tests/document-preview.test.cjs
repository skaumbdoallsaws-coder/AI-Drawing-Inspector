'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { documentURL, boundedBody, createDocumentPreview, MAX_BYTES } = require('../src/document-preview.cjs');
const origin = 'http://127.0.0.1:8480';
for (const url of ['https://example.com/file.pdf', 'http://localhost:8480/file.pdf', origin + '/', origin + '/api/agent/chat', 'file:///secret.pdf', 'http://user:pass@127.0.0.1:8480/file.pdf']) {
  test('document previews reject unrelated authority: ' + url, () => assert.throws(() => documentURL(url, origin)));
}
test('document endpoint and filename references retain exact local identity', () => {
  for (const suffix of ['/api/parts-manual/MMLE-50D/artifacts/current', '/generated/report.pdf', '/static/logo.png']) assert.equal(documentURL(origin + suffix, origin), origin + suffix);
});
test('document read refuses oversized declared or streamed content', async () => {
  await assert.rejects(boundedBody(new Response('x', { headers: { 'content-length': String(MAX_BYTES + 1) } })), { code: 'document_too_large' });
  await assert.rejects(boundedBody({ headers: new Headers(), body: (async function* () { yield Buffer.alloc(MAX_BYTES); yield Buffer.from('x'); })() }), { code: 'document_too_large' });
});
function fixture(fetcher) {
  const selected = new EventEmitter(), handlers = {};
  selected.protocol = { handle: (name, handler) => { handlers.protocol = handler; }, unhandle() { handlers.removed = true; } };
  selected.webRequest = { onBeforeRequest: fn => { handlers.request = fn; }, onBeforeSendHeaders: fn => { handlers.headers = fn; } };
  for (const method of ['setPermissionCheckHandler','setPermissionRequestHandler','setDevicePermissionHandler','setDisplayMediaRequestHandler']) selected[method] = () => {};
  selected.closeAllConnections = selected.clearStorageData = async () => {};
  return { handlers, pending: createDocumentPreview({ electron: { session: { fromPartition: () => selected } }, origin, getCredential: () => 'a'.repeat(64), fetcher }) };
}
test('PDF snapshot exposes bytes without forwarding credentials or allowing network access', async () => {
  let request;
  const f = fixture(async (url, options) => { request = {url, options}; return new Response('%PDF-1.4\nfixture', { headers: { 'content-type': 'application/octet-stream' } }); });
  const service = await f.pending;
  try {
    const item = await service.prepare(origin + '/generated/file.pdf');
    assert.equal(request.options.redirect, 'error');
    assert.equal(request.options.headers['X-InspectorPro-Desktop-Token'], 'a'.repeat(64));
    assert.equal(item.mime, 'application/pdf'); assert.equal(service.known(item.url), true);
    const response = f.handlers.protocol({url:item.url,method:'GET'});
    assert.equal(response.headers.get('content-type'), 'application/pdf');
    assert.match(response.headers.get('content-security-policy'), /script-src 'none'/);
    assert.equal(await response.text(), '%PDF-1.4\nfixture');
    f.handlers.request({url:origin+'/api/profiles'}, result => assert.equal(result.cancel, true));
    f.handlers.request({url:'https://example.com'}, result => assert.equal(result.cancel, true));
    f.handlers.request({url:'chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html'}, result => assert.equal(result.cancel, false));
    f.handlers.request({url:'chrome-extension://untrusted/index.html'}, result => assert.equal(result.cancel, true));
    f.handlers.request({url:'chrome://settings'}, result => assert.equal(result.cancel, true));
    f.handlers.request({url:'chrome://resources/js/assert.js'}, result => assert.equal(result.cancel, false));
    f.handlers.headers({requestHeaders:{'X-InspectorPro-Desktop-Token':'secret',Cookie:'private',Authorization:'private',Accept:'application/pdf'}}, result => assert.deepEqual(result.requestHeaders,{Accept:'application/pdf'}));
    service.release(item.url); assert.equal(service.known(item.url), false);
  } finally { await service.dispose(); }
});
test('failed, redirected, or late document loads cannot fabricate a preview', async () => {
  const f = fixture(async () => new Response('missing', {status:404})); const service = await f.pending;
  await assert.rejects(service.prepare(origin+'/generated/missing.pdf'), {code:'document_http_404'});
  await service.dispose();
  let finish;
  const delayed = fixture(() => new Promise(resolve => {finish=resolve;})); const closed = await delayed.pending;
  const result = closed.prepare(origin+'/generated/late.pdf'); await closed.dispose();
  finish(new Response('%PDF-1.4')); await assert.rejects(result,{code:'document_preview_closed'});
});
