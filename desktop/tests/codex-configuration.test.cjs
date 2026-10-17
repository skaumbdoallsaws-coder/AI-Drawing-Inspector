'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { childEnvironment } = require('../src/runtime-supervisor.cjs');
const { loadApplicationProfile } = require('../src/application-profile.cjs');

async function fixture(t) {
  const parent = path.resolve(__dirname, '../.runtime/codex-config-tests');
  await fs.mkdir(parent, { recursive: true });
  const root = await fs.mkdtemp(path.join(parent, 'case-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const dataRoot = path.join(root, 'data'), facilityRoot = path.join(root, 'facility'), libraryRoot = path.join(root, 'library');
  for (const dir of [dataRoot, facilityRoot, libraryRoot]) await fs.mkdir(dir);
  const dependencyRoot = path.join(root, 'deps'), binary = path.join(dependencyRoot, 'codex_cli_bin', 'bin', 'codex.exe');
  await fs.mkdir(path.dirname(binary), { recursive: true });
  await fs.writeFile(binary, 'test-binary');
  const value = { schemaVersion: 1, mode: 'application', profileId: 'test', origin: 'http://127.0.0.1:8480',
    dataRoot, facilityRoot, libraryRoot, backendId: randomUUID(), storeId: randomUUID(), startupLayoutId: 'fl-test' };
  const codexRuntime = { schemaVersion: 1, model: 'gpt-5.5', allowPaidInference: true, editPreviews: true,
    packageSha256: 'a'.repeat(64),
    dependencyRoot, binary, pilotRoot: path.join(dataRoot, 'codex-pilot'), credentialTarget: 'InspectorPro/Codex/test' };
  const file = path.join(root, 'profile.json');
  return { value, codexRuntime, async load(value) { await fs.writeFile(file, JSON.stringify(value)); return loadApplicationProfile(file); } };
}

test('Codex configuration preserves desktop partition and profile identity', async t => {
  const f = await fixture(t), before = await f.load(f.value);
  const after = await f.load({ ...f.value, codexRuntime: f.codexRuntime });
  assert.equal(after.partition, before.partition);
  assert.equal(after.stateRoot, before.stateRoot);
  assert.deepEqual(after.codexRuntime, f.codexRuntime);
  assert.equal(Object.isFrozen(after.codexRuntime), true);
});

test('subscription profile is explicit, identity-preserving and cannot enable API fallback', async t => {
  const f = await fixture(t), before = await f.load(f.value);
  const subscription = { ...f.codexRuntime, schemaVersion: 2, authMode: 'chatgpt_plan',
    model: 'gpt-6.1-sol', allowPaidInference: false, credentialTarget: 'InspectorPro/ChatGPT/test' };
  const after = await f.load({ ...f.value, codexRuntime: subscription });
  assert.equal(after.partition, before.partition);
  assert.deepEqual(after.codexRuntime, subscription);
  for (const change of [{allowPaidInference: true}, {authMode: 'api_key'}, {accessToken: 'secret'},
    {credentialTarget: f.codexRuntime.credentialTarget}]) {
    await assert.rejects(f.load({ ...f.value, codexRuntime: { ...subscription, ...change } }));
  }
});

test('Codex rejects arbitrary configuration, secrets, model/auth changes and overlapping stores', async t => {
  const f = await fixture(t);
  for (const codexRuntime of [null, [], {}, { ...f.codexRuntime, apiKey: 'secret-canary' },
    { ...f.codexRuntime, authMode: 'chatgpt' }, { ...f.codexRuntime, model: 'other' },
    { ...f.codexRuntime, allowPaidInference: false }, { ...f.codexRuntime, editPreviews: 1 },
    { ...f.codexRuntime, packageSha256: undefined }, { ...f.codexRuntime, packageSha256: 'bad' },
    { ...f.codexRuntime, credentialTarget: 'other' }, { ...f.codexRuntime, binary: 'relative' },
    { ...f.codexRuntime, pilotRoot: f.value.facilityRoot }]) {
    await assert.rejects(f.load({ ...f.value, codexRuntime }), error => {
      assert.equal(error.message, 'desktop_codex_config_invalid');
      assert.equal(error.message.includes('secret-canary'), false);
      return true;
    });
  }
});

test('application child receives no inherited Codex credential/config or personal Codex home', () => {
  const source = { INSPECTORPRO_CODEX_API_KEY: 'secret-canary', inspectorpro_codex_readonly_pilot: '1',
    INSPECTORPRO_CODEX_EDIT_PREVIEWS: '1', CODEX_HOME: 'personal', CODEX_AUTH: 'personal',
    OPENAI_API_KEY: 'legacy-only', PATH: 'normal-path' };
  const original = { ...source };
  for (const profile of [{ mode: 'application' }, { mode: 'application', codexRuntime: {} }, { mode: 'managed' }]) {
    const env = childEnvironment(profile, process.execPath, source);
    assert.equal(Object.keys(env).some(key => /^(inspectorpro_codex_|codex_)/i.test(key)), false);
    assert.equal(JSON.stringify(env).includes('secret-canary'), false);
  }
  assert.deepEqual(source, original);
  assert.equal(childEnvironment({ mode: 'application' }, process.execPath, source).OPENAI_API_KEY, 'legacy-only');
});

test('Codex dependencies never prepend to Python path or enter renderer/preload configuration', async t => {
  const f = await fixture(t), profile = await f.load({ ...f.value, codexRuntime: f.codexRuntime });
  const env = childEnvironment(profile, process.execPath, { PYTHONPATH: 'existing-app-deps' });
  assert.equal(env.PYTHONPATH, 'existing-app-deps');
  for (const file of ['application-preload.cjs', 'application-network.cjs']) {
    const source = await fs.readFile(path.join(__dirname, '../src', file), 'utf8');
    assert.equal(/CODEX_API_KEY|credentialTarget|codexRuntime/.test(source), false);
  }
});
