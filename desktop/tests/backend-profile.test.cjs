'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { validateIdentity, verifyBackend, bindProfile, parseOptions } = require('../src/backend-profile.cjs');
const identity = { schemaVersion: 1, product: 'InspectorPro', mode: 'rendering-spike',
  backendId: '4bb0c5bc-2db1-4a53-b5a4-81a2935af20c', storeId: '2e581369-e532-42b4-9198-b13ea598f0a8',
  profileId: 'test', researchBrowsing: false, interactive: false };
async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ip-desktop-profile-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const file = path.join(root, 'identity.json');
  await fs.writeFile(file, JSON.stringify({ ...identity, origin: 'http://127.0.0.1:8197' }));
  return { root, file };
}
test('identity refuses an ordinary server or expanded capability claims', () => {
  assert.deepEqual(validateIdentity(identity), identity);
  for (const changed of [{ interactive: true }, { researchBrowsing: true }, { mode: 'managed' }, { product: 'Other' }, { backendId: '../x' }, { backendId: [identity.backendId] }, { profileId: ['profile'] }]) {
    assert.throws(() => validateIdentity({ ...identity, ...changed }));
  }
});
test('handshake matches explicit marker, rejects redirects and foreign stores', async t => {
  const { file } = await fixture(t);
  let options;
  const good = await verifyBackend({ origin: 'http://127.0.0.1:8197', identityFile: file,
    fetchImpl: async (_url, opts) => { options = opts; return Response.json(identity); } });
  assert.equal(good.identity.backendId, identity.backendId); assert.equal(options.redirect, 'error');
  await assert.rejects(verifyBackend({ origin: good.origin, identityFile: file,
    fetchImpl: async () => Response.json({ ...identity, storeId: identity.backendId }) }), /mismatch/);
  await assert.rejects(verifyBackend({ origin: 'http://127.0.0.1:8198', identityFile: file }), /origin differs/);
});
test('oversized identity never gets accepted', async t => {
  const { file } = await fixture(t);
  await assert.rejects(verifyBackend({ origin: 'http://127.0.0.1:8197', identityFile: file,
    fetchImpl: async () => new Response(' '.repeat(16385)) }), /limit/);
});
test('profile persists exact origin/store and cannot silently switch storage', async t => {
  const { root } = await fixture(t);
  const directory = path.join(root, 'shell'); const verified = { origin: 'http://127.0.0.1:8197', identity };
  const one = await bindProfile(directory, verified); const two = await bindProfile(directory, verified);
  assert.deepEqual(one, two);
  await assert.rejects(bindProfile(directory, { ...verified, origin: 'http://127.0.0.1:8198' }), /another origin/);
  await assert.rejects(bindProfile(directory, { ...verified, identity: { ...identity, storeId: identity.backendId } }), /another origin/);
  const other = await bindProfile(path.join(root, 'other'), { ...verified, identity: { ...identity, storeId: identity.backendId } });
  assert.notEqual(one.partition, other.partition);
});
test('CLI needs explicit identity/origin and rejects unknown or repeated options', () => {
  const separated = parseOptions(['--', '--backend', 'http://127.0.0.1:8197', '--identity-file', 'id'], process.cwd());
  assert.equal(separated.origin, 'http://127.0.0.1:8197');
  assert.throws(() => parseOptions([], process.cwd()));
  assert.throws(() => parseOptions(['--backend', 'http://127.0.0.1:8197', '--identity-file', 'id', '--unsafe', 'yes'], process.cwd()));
  assert.throws(() => parseOptions(['--backend', 'http://127.0.0.1:8197', '--identity-file', 'id', '--backend', 'http://localhost'], process.cwd()));
});

test('rendering page kind is explicit and cannot enable another application mode', () => {
  const args = ['--backend', 'http://127.0.0.1:8197', '--identity-file', 'id'];
  assert.equal(parseOptions(args, process.cwd()).expectedPage, 'full-application');
  assert.equal(parseOptions([...args, '--smoke-output', 'out', '--expected-page', 'inert-fixture'], process.cwd()).expectedPage, 'inert-fixture');
  assert.throws(() => parseOptions([...args, '--expected-page', 'inert-fixture'], process.cwd()));
  assert.throws(() => parseOptions([...args, '--smoke-output', 'out', '--expected-page', 'interactive'], process.cwd()));
});
