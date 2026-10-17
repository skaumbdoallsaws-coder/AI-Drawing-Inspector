'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { loadApplicationProfile } = require('../src/application-profile.cjs');
const { childEnvironment } = require('../src/runtime-supervisor.cjs');

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'ip-gateway-profile-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const configPath = path.join(root, 'gateway.json'), dependencyRoot = path.join(root, 'python');
  await fs.mkdir(path.join(dependencyRoot, 'litellm'), { recursive: true });
  await fs.writeFile(configPath, '{}');
  await fs.writeFile(path.join(dependencyRoot, 'litellm', '__init__.py'), '');
  const profile = { schemaVersion: 1, mode: 'application', profileId: 'test', origin: 'http://127.0.0.1:8480',
    dataRoot: root, backendId: randomUUID(), storeId: randomUUID(), facilityRoot: root, libraryRoot: root,
    startupLayoutId: 'fl-test' };
  const file = path.join(root, 'profile.json');
  return { profile, gateway: { configPath, dependencyRoot },
    async load(value) { await fs.writeFile(file, JSON.stringify(value)); return loadApplicationProfile(file); } };
}

test('optional gateway preserves existing profile identity and storage partition', async t => {
  const f = await fixture(t), original = await f.load(f.profile);
  const enabled = await f.load({ ...f.profile, modelGateway: f.gateway });
  assert.equal(enabled.partition, original.partition);
  assert.equal(enabled.stateRoot, original.stateRoot);
  assert.deepEqual(enabled.modelGateway, f.gateway);
  assert.equal(Object.isFrozen(enabled.modelGateway), true);
});

test('invalid gateway bindings reject startup rather than fall back', async t => {
  const f = await fixture(t);
  for (const modelGateway of [null, [], {}, { ...f.gateway, apiKey: 'not-allowed' },
    { ...f.gateway, configPath: 'relative.json' }, { ...f.gateway, dependencyRoot: path.join(f.profile.dataRoot, 'missing') }]) {
    await assert.rejects(f.load({ ...f.profile, modelGateway }));
  }
  await assert.rejects(f.load({ ...f.profile, unknown: true }));
});

test('native profile overrides inherited model route without mutating parent environment', async t => {
  const f = await fixture(t), profile = await f.load({ ...f.profile, modelGateway: f.gateway });
  const source = { INSPECTORPRO_LLM_GATEWAY_CONFIG: 'other.json', pythonpath: 'existing-packages', OPENAI_API_KEY: 'test-only' };
  const env = childEnvironment(profile, process.execPath, source);
  assert.equal(env.INSPECTORPRO_LLM_GATEWAY_CONFIG, f.gateway.configPath);
  assert.equal(env.PYTHONPATH, f.gateway.dependencyRoot + path.delimiter + 'existing-packages');
  assert.equal(env.pythonpath, undefined);
  assert.equal(env.OPENAI_API_KEY, 'test-only');
  assert.equal(source.INSPECTORPRO_LLM_GATEWAY_CONFIG, 'other.json');
  assert.equal(childEnvironment({ mode: 'application' }, process.execPath, source).INSPECTORPRO_LLM_GATEWAY_CONFIG, 'other.json');
});

test('restricted managed profiles cannot activate the gateway or inherit dependencies', () => {
  const env = childEnvironment({ mode: 'managed', modelGateway: { configPath: 'ignored', dependencyRoot: 'ignored' } },
    process.execPath, { INSPECTORPRO_LLM_GATEWAY_CONFIG: 'ignored', PYTHONPATH: 'ignored', OPENAI_API_KEY: 'test-only' });
  assert.equal(env.INSPECTORPRO_LLM_GATEWAY_CONFIG, undefined);
  assert.equal(env.PYTHONPATH, undefined);
  assert.equal(env.OPENAI_API_KEY, undefined);
});
