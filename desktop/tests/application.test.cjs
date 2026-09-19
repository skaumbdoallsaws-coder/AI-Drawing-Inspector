'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createApplicationNetwork } = require('../src/application-network.cjs');
const { authorizeTransition } = require('../src/application-lifecycle.cjs');
const { childEnvironment } = require('../src/runtime-supervisor.cjs');
const origin = 'http://127.0.0.1:8480';
function fixture() {
  const mainFrame = { url: origin + '/', detached: false };
  const contents = { id: 3, mainFrame, getURL: () => origin + '/' };
  const w = { isDestroyed: () => false, webContents: contents };
  const net = createApplicationNetwork({ origin, getWindow: () => w, getCredential: () => 'a'.repeat(64), confirmPermission: async () => false });
  const request = { url: origin + '/api/agent/chat', webContentsId: 3, frame: mainFrame, resourceType: 'xhr', requestHeaders: { Authorization: 'application-auth' } };
  return { net, request, contents, mainFrame };
}
for (const endpoint of ['/api/agent/chat', '/api/facility-layouts/site-local/fl-manual', '/api/request-extraction', '/api/operations-manual/example/pdf', '/generated/industrial_assets/model.glb']) {
  test('normal app route remains reachable: ' + endpoint, () => {
    const { net, request } = fixture();
    const reply = net.headers({ ...request, url: origin + endpoint });
    assert.equal(reply.cancel, false); assert.equal(reply.requestHeaders.Authorization, 'application-auth');
    assert.equal(reply.requestHeaders['X-InspectorPro-Desktop-Token'], 'a'.repeat(64));
  });
}
test('remote fetches never receive a supplied or native private token', () => {
  const { net, request } = fixture();
  const reply = net.headers({ ...request, url: 'https://api.example.com/request', requestHeaders: { 'x-InspectorPro-Desktop-Token': 'forged' } });
  assert.deepEqual(reply, { cancel: false, requestHeaders: {} });
});
test('foreign, detached, remote subframes and unattributed workers cannot call the backend', () => {
  const { net, request, mainFrame } = fixture();
  for (const change of [{ webContentsId: 9 }, { frame: null }, { frame: { url: origin, detached: true } },
    { frame: { url: 'https://evil.invalid/', top: mainFrame, detached: false } }]) assert.equal(net.headers({ ...request, ...change }).cancel, true);
});
test('same origin dedicated worker and websocket retain private authentication', () => {
  const { net, request } = fixture();
  for (const change of [{ frame: null, initiator: origin }, { url: origin.replace('http:', 'ws:') + '/socket', resourceType: 'webSocket' }]) {
    assert.equal(net.headers({ ...request, ...change }).cancel, false);
  }
});
test('navigation and remote scripts remain outside the app authority', () => {
  const { net, request } = fixture();
  for (const change of [{ url: 'https://evil.invalid/', resourceType: 'mainFrame' }, { url: origin + '/api/agent/chat', resourceType: 'mainFrame' },
    { url: 'https://evil.invalid/inject.js', resourceType: 'script' }, { url: 'file:///C:/private.txt' }]) assert.equal(net.allowed({ ...request, ...change }), false);
  net.setEnabled(false); assert.equal(net.headers(request).cancel, true);
});
test('native permissions require exact application origin and main frame', () => {
  const { net, contents } = fixture();
  assert.equal(net.trustedPermission(contents, { requestingUrl: origin + '/', isMainFrame: true }), true);
  for (const d of [{ isMainFrame: false }, { requestingUrl: 'https://evil.invalid' }, { requestingOrigin: 'null' }]) assert.equal(net.trustedPermission(contents, d), false);
});
const clean = { schemaVersion: 1, dirty: false, busy: false, pending: false, affected: [], fingerprint: 'original' };
test('normal mode keeps provider settings and helper PATH; managed mode still strips them', () => {
  const source = { OPENAI_API_KEY: 'test-only', PATH: 'native-helpers', PYTHON_DOTENV_DISABLED: '1', ELECTRON_RUN_AS_NODE: '1' };
  const normal = childEnvironment({ mode: 'application' }, 'C:/Python/python.exe', source);
  assert.equal(normal.OPENAI_API_KEY, 'test-only'); assert.equal(normal.PATH, source.PATH);
  assert.equal(normal.PYTHON_DOTENV_DISABLED, undefined); assert.equal(normal.ELECTRON_RUN_AS_NODE, undefined);
  assert.equal(childEnvironment({ mode: 'managed' }, 'C:/Python/python.exe', source).OPENAI_API_KEY, undefined);
});
test('clean close, unsaved Cancel, and explicit discard', async () => {
  assert.equal((await authorizeTransition({ kind: 'close', observe: async () => clean })).allowed, true);
  const dirty = { ...clean, dirty: true, affected: ['facility'] };
  assert.equal((await authorizeTransition({ kind: 'close', observe: async () => dirty, confirmDiscard: async () => false })).cancelled, true);
  assert.equal((await authorizeTransition({ kind: 'close', observe: async () => dirty, confirmDiscard: async () => true })).allowed, true);
});
test('restart preserves dirty draft without requesting discard', async () => {
  assert.equal((await authorizeTransition({ kind: 'restart', observe: async () => ({ ...clean, dirty: true }), confirmDiscard: () => { throw Error('must not discard'); } })).allowed, true);
});
test('pending work and changes during confirmation block destructive lifecycle effects', async () => {
  for (const flag of ['busy', 'pending']) assert.equal((await authorizeTransition({ kind: 'restart', observe: async () => ({ ...clean, [flag]: true }) })).allowed, false);
  let calls = 0;
  assert.equal((await authorizeTransition({ kind: 'close', observe: async () => ({ ...clean, fingerprint: String(calls++) }) })).allowed, false);
  await assert.rejects(authorizeTransition({ kind: 'close', observe: async () => null }));
});
