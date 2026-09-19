'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createRuntimeNetwork } = require('../src/runtime-network.cjs');
const { createRuntimePeer } = require('../src/runtime-peer.cjs');
const { canonicalOrigin, parseRuntimeOptions, validateRuntime } = require('../src/runtime-settings.cjs');
const { childEnvironment } = require('../src/runtime-supervisor.cjs');

const origin = 'http://127.0.0.1:8421';
function networkFixture() {
  const mainFrame = { detached: false }, contents = { id: 42, mainFrame }, win = { isDestroyed: () => false, webContents: contents };
  const policy = createRuntimeNetwork({ origin, getWindow: () => win, getCredentials: () => 'a'.repeat(64), getRequestId: () => 'req-1', getOwnerSession: () => 'owner-1' });
  const request = { id: 1, url: origin + '/api/profiles', webContentsId: 42, frame: mainFrame, resourceType: 'xhr', requestHeaders: { Authorization: 'untrusted', Cookie: 'untrusted', 'x-inspectorpro-desktop-token': 'forged' } };
  return { policy, request, mainFrame };
}
test('credential attaches only to attributable main-frame exact-origin requests', () => {
  const { policy, request } = networkFixture();
  const result = policy.headers(request);
  assert.equal(result.cancel, false); assert.equal(result.requestHeaders['X-InspectorPro-Desktop-Token'], 'a'.repeat(64));
  assert.equal(result.requestHeaders.Authorization, undefined); assert.equal(result.requestHeaders.Cookie, undefined);
  assert.equal(result.requestHeaders['X-InspectorPro-Desktop-Request-Id'], 'req-1');
  for (const change of [{ url: 'https://example.test/' }, { url: origin + '.example.test/' }, { url: 'http://localhost:8421/' },
    { webContentsId: 9 }, { frame: null }, { frame: {} }, { resourceType: 'subFrame' }, { resourceType: 'webSocket' },
    { url: origin + '/private.pdf', resourceType: 'mainFrame' }]) {
    const refused = policy.headers({ ...request, ...change }); assert.equal(refused.cancel, true, JSON.stringify(change));
    assert.equal(Object.keys(refused.requestHeaders).some(key => /token|authorization|cookie/i.test(key)), false);
  }
});
test('recovery revokes all page network authority and permits explicit verified resume', () => {
  const { policy, request } = networkFixture(); policy.setEnabled(false); assert.equal(policy.headers(request).cancel, true);
  policy.setEnabled(true); assert.equal(policy.headers(request).cancel, false);
});
test('all redirects are refused and identifiers cleaned on completion', () => {
  const { policy, request } = networkFixture(); const handlers = {};
  policy.install({ webRequest: Object.fromEntries(['onBeforeRequest','onBeforeSendHeaders','onBeforeRedirect','onCompleted','onErrorOccurred'].map(name => [name, fn => handlers[name] = fn])),
    setPermissionCheckHandler() {}, setPermissionRequestHandler() {}, on() {} });
  handlers.onBeforeRedirect(request); assert.equal(policy.allowed(request), false);
  handlers.onCompleted(request); assert.equal(policy.allowed(request), true);
});
test('same-origin blob/data resources carry no backend credential', () => {
  const { policy, request } = networkFixture();
  for (const url of ['blob:' + origin + '/asset', 'data:image/png;base64,AAAA']) {
    const result = policy.headers({ ...request, url, resourceType: 'image' }); assert.equal(result.cancel, false);
    assert.equal(Object.keys(result.requestHeaders).some(key => /token|session|request-id/i.test(key)), false);
  }
});
test('canonical profile origins reject aliases, credentials and silent origin changes', () => {
  assert.equal(canonicalOrigin(origin), origin);
  for (const value of ['http://localhost:8421','http://127.0.0.1:8421/','http://127.0.0.1:8421/?x=1','http://127.0.0.1:80','http://user@127.0.0.1:8421','https://127.0.0.1:8421']) assert.throws(() => canonicalOrigin(value));
  assert.throws(() => parseRuntimeOptions(['--profile-file','relative','--python','relative']));
  assert.throws(() => parseRuntimeOptions(['--arbitrary','x']));
});
test('private runtime verification binds principal, instance, store and capability scope', () => {
  const profile = { backendId: 'backend', storeId: 'store', profileId: 'profile', origin, acceptanceLayoutId: 'fl-test' };
  const value = { schemaVersion: 1, product: 'InspectorPro', mode: 'desktop-managed', backendId: 'backend', storeId: 'store', principalId: 'local-user',
    profileId: 'profile', origin, processId: 23, instanceId: 'instance', storeBinding: 'a'.repeat(64), owner: { sessionId: 's', ownerId: 'o' },
    document: { tenantId: 'local', siteId: 'site-local', documentId: 'fl-test' },
    capabilities: { generalEditing: false, researchBrowsing: false, facilityAcceptance: true } };
  assert.equal(validateRuntime(value, profile, 'instance').document.documentId, 'fl-test');
  for (const change of [{ storeId: 'other' }, { instanceId: 'old' }, { origin: 'http://127.0.0.1:8422' }, { capabilities: { ...value.capabilities, generalEditing: true } }]) assert.throws(() => validateRuntime({ ...value, ...change }, profile, 'instance'));
  for (const document of [{ ...value.document, tenantId: 'foreign' }, { ...value.document, siteId: 'foreign' }, { ...value.document, documentId: 'fl-other' }, null]) {
    assert.throws(() => validateRuntime({ ...value, document }, profile, 'instance'), { code: 'desktop_runtime_document_mismatch' });
  }
});
test('owned backend environment strips provider secrets, proxies and rollout/native overrides', () => {
  const env = childEnvironment({}, process.execPath, { PATH: 'untrusted', OPENAI_API_KEY: 'private', PYTHONPATH: 'private', HTTP_PROXY: 'private', INSPECTORPKG_CLI: 'private', SystemRoot: 'C:\\Windows' });
  for (const key of ['OPENAI_API_KEY','PYTHONPATH','HTTP_PROXY','INSPECTORPKG_CLI']) assert.equal(env[key], undefined);
  assert.equal(env.PYTHON_DOTENV_DISABLED, '1'); assert.ok(!env.PATH.includes('untrusted'));
});
test('renderer RPC rejects foreign replies, correlates one result and sends no generic commands', async () => {
  const sent = [], contents = { isDestroyed: () => false, send: (channel, value) => sent.push({ channel, value }) };
  const peer = createRuntimePeer({ getContents: () => contents }); const promise = peer.run('snapshot');
  assert.equal(peer.reply({ requestId: 'foreign', ok: true, result: 'bad' }), false);
  const requestId = sent[0].value.requestId; peer.reply({ requestId, ok: true, result: { exact: true } }); assert.deepEqual(await promise, { exact: true });
  assert.equal(peer.reply({ requestId, ok: true, result: 'late' }), false);
  await assert.rejects(peer.run('executeJavaScript'), { code: 'desktop_renderer_rpc_unavailable' }); peer.dispose();
});
test('RPC cancellation rejects immediately and revokes queued renderer command', async () => {
  const sent = [], controller = new AbortController();
  const peer = createRuntimePeer({ getContents: () => ({ isDestroyed: () => false, send: (channel, value) => sent.push({ channel, value }) }) });
  const promise = peer.run('freeze', { intentId: 'intent' }, { signal: controller.signal, assertCurrent() { if (controller.signal.aborted) throw controller.signal.reason; } });
  controller.abort(Object.assign(new Error('cancelled'), { code: 'cancelled' })); await assert.rejects(promise, { code: 'cancelled' });
  assert.equal(sent[1].channel, 'desktop-runtime:facility-cancel'); assert.equal(sent[0].value.requestId, sent[1].value.requestId); assert.equal(peer.pendingCount, 0); peer.dispose();
});
test('RPC timeout retains typed failure and revokes the renderer request', async () => {
  const sent = [], peer = createRuntimePeer({ getContents: () => ({ isDestroyed: () => false, send: (channel, value) => sent.push({ channel, value }) }), timeoutMs: 5 });
  await assert.rejects(peer.run('snapshot'), { code: 'desktop_renderer_rpc_timeout' }); assert.equal(sent[1].channel, 'desktop-runtime:facility-cancel'); peer.dispose();
});
