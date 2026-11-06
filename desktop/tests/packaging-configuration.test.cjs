'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { loadApplicationProfile } = require('../src/application-profile.cjs');
const { childEnvironment } = require('../src/runtime-supervisor.cjs');
const { isolatePackagingEnvironment } = require('../src/packaging-config.cjs');

async function fixture(t) {
  const parent = path.resolve(__dirname, '../.runtime/packaging-config-tests');
  await fs.mkdir(parent, { recursive: true });
  const root = await fs.mkdtemp(path.join(parent, 'case-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const profile = { schemaVersion: 1, mode: 'application', profileId: 'packaging-test',
    origin: 'http://127.0.0.1:8480', backendId: randomUUID(), storeId: randomUUID(), startupLayoutId: null };
  for (const key of ['dataRoot', 'facilityRoot', 'libraryRoot']) {
    profile[key] = path.join(root, key); await fs.mkdir(profile[key]);
  }
  const dependencyRoot = path.join(root, 'deps'), geometryPython = path.join(root, 'step-venv', 'python.exe');
  for (const name of ['py3dbp', 'trimesh', 'reportlab']) {
    await fs.mkdir(path.join(dependencyRoot, name), { recursive: true });
    await fs.writeFile(path.join(dependencyRoot, name, '__init__.py'), '');
  }
  await fs.mkdir(path.dirname(geometryPython)); await fs.writeFile(geometryPython, '');
  const config = { schemaVersion: 1, dependencyRoot, geometryPython }, file = path.join(root, 'profile.json');
  return { root, profile, config, async load(value) {
    await fs.writeFile(file, JSON.stringify(value)); return loadApplicationProfile(file);
  } };
}

test('Packaging is optional, keeps identity, and uses presence as startup URL opt-in', async t => {
  const f = await fixture(t), before = await f.load(f.profile);
  assert.equal(before.packagingRuntime, undefined);
  const enabled = await f.load({ ...f.profile, packagingRuntime: f.config });
  assert.deepEqual(enabled.packagingRuntime, f.config);
  assert.equal(Object.isFrozen(enabled.packagingRuntime), true);
  assert.equal(enabled.partition, before.partition);
  assert.equal(enabled.stateRoot, before.stateRoot);
  const { geometryPython, ...withoutStep } = f.config;
  assert.deepEqual((await f.load({ ...f.profile, packagingRuntime: withoutStep })).packagingRuntime, withoutStep);
  await assert.rejects(fs.stat(path.join(f.profile.dataRoot, 'packaging')), { code: 'ENOENT' });
});

test('Packaging rejects malformed schemas and paths with bounded errors', async t => {
  const f = await fixture(t);
  const invalid = [null, false, [], {}, { schemaVersion: 1 }, { dependencyRoot: f.config.dependencyRoot }];
  for (const [key, values] of Object.entries({
    schemaVersion: [true, false, 0, 2, 1.5, '1', null], enabled: [true, false], apiKey: ['synthetic-secret'],
    geometryPython: [null, false, 3, [], {}, '', 'relative.exe', '\\\\host\\share\\python.exe', '//host/share/python',
      '/\\host/share/python', '\\/host/share/python', '\\root-relative.exe', 'C:drive-relative.exe',
      '\\\\?\\C:\\python.exe', path.join(f.root, 'missing'), f.profile.dataRoot, f.config.geometryPython + '\0'],
    dependencyRoot: [null, false, 3, [], {}, '', 'relative', '\\\\host\\share\\deps', '//host/share/deps',
      '/\\host/share/deps', '\\/host/share/deps', '\\root-relative', 'C:drive-relative',
      path.join(f.root, 'missing'), f.config.geometryPython, f.config.dependencyRoot + path.sep + '..' + path.sep + 'deps'],
  })) for (const value of values) invalid.push({ ...f.config, [key]: value });
  for (const packagingRuntime of invalid) {
    await assert.rejects(f.load({ ...f.profile, packagingRuntime }), { message: 'desktop_packaging_config_invalid' });
  }
});

test('Every declared app package is required and must be a file', async t => {
  const f = await fixture(t);
  for (const name of ['py3dbp', 'trimesh', 'reportlab']) {
    const file = path.join(f.config.dependencyRoot, name, '__init__.py');
    await fs.unlink(file);
    await assert.rejects(f.load({ ...f.profile, packagingRuntime: f.config }));
    await fs.mkdir(file);
    await assert.rejects(f.load({ ...f.profile, packagingRuntime: f.config }));
    await fs.rmdir(file); await fs.writeFile(file, '');
  }
});

test('Packaging refuses linked dependencies/state and overlapping stores/geometry', async t => {
  const f = await fixture(t), link = path.join(f.root, 'linked-deps');
  await fs.symlink(f.config.dependencyRoot, link, 'junction');
  await assert.rejects(f.load({ ...f.profile, packagingRuntime: { ...f.config, dependencyRoot: link } }));
  for (const key of ['dataRoot', 'facilityRoot', 'libraryRoot']) {
    await assert.rejects(f.load({ ...f.profile, [key]: f.config.dependencyRoot, packagingRuntime: f.config }));
  }
  await assert.rejects(f.load({ ...f.profile, packagingRuntime: { ...f.config,
    geometryPython: path.join(f.config.dependencyRoot, 'py3dbp', '__init__.py') } }));
  const state = path.join(f.profile.dataRoot, 'packaging');
  await fs.symlink(f.profile.facilityRoot, state, 'junction');
  await assert.rejects(f.load({ ...f.profile, packagingRuntime: f.config }));
  await fs.unlink(state);
  await fs.mkdir(state);
  await fs.writeFile(path.join(state, 'step-jobs'), '');
  await assert.rejects(f.load({ ...f.profile, packagingRuntime: f.config }));
});

test('Child sanitization removes inherited Packaging but leaves Codex/ChatGPT isolation intact', () => {
  const source = { inspectorpro_packaging_enabled: '1', INSPECTORPRO_PACKAGING_ROOT: 'pilot-root',
    INSPECTORPRO_PACKAGING_GEOMETRY_PYTHON: 'pilot-python', INSPECTORPRO_PACKAGING_GEOMETRY_TMP: 'pilot-temp',
    INSPECTORPRO_PACKAGING_EASYPOST_KEY: 'synthetic-carrier', INSPECTORPRO_PACKAGING_UNKNOWN: '1',
    inspectorpro_codex_packaging: '1', INSPECTORPRO_CODEX_AUTH_MODE: 'chatgpt_plan',
    INSPECTORPRO_CHATGPT_TEST: 'synthetic-account', CODEX_HOME: 'personal', OPENAI_API_KEY: 'synthetic-legacy' };
  const original = { ...source }, isolated = isolatePackagingEnvironment(source);
  assert.equal(isolated.INSPECTORPRO_CODEX_AUTH_MODE, source.INSPECTORPRO_CODEX_AUTH_MODE);
  assert.equal(isolated.INSPECTORPRO_CHATGPT_TEST, source.INSPECTORPRO_CHATGPT_TEST);
  for (const mode of ['application', 'managed']) {
    const env = childEnvironment({ mode }, process.execPath, source);
    assert.equal(Object.keys(env).some(key => /^(INSPECTORPRO_PACKAGING_|INSPECTORPRO_CODEX_|INSPECTORPRO_CHATGPT_|CODEX_)/i.test(key)), false);
    assert.equal(env.OPENAI_API_KEY, mode === 'application' ? source.OPENAI_API_KEY : undefined);
  }
  assert.deepEqual(source, original);
});

test('App dependency path composes with gateway without using the STEP worker or changing parent', async t => {
  const f = await fixture(t), profile = await f.load({ ...f.profile, packagingRuntime: f.config });
  const source = { pythonpath: 'existing-deps', OPENAI_API_KEY: 'synthetic-legacy', INSPECTORPRO_PACKAGING_ENABLED: '1' };
  const original = { ...source };
  const env = childEnvironment({ ...profile, modelGateway: { configPath: 'gateway.json', dependencyRoot: 'gateway-deps' } }, process.execPath, source);
  assert.equal(env.PYTHONPATH, ['gateway-deps', 'existing-deps', f.config.dependencyRoot].join(path.delimiter));
  assert.equal(env.pythonpath, undefined);
  assert.equal(env.PYTHONPATH.includes('step-venv'), false);
  assert.equal(env.INSPECTORPRO_PACKAGING_ENABLED, undefined); // Python config owns the actual opt-in.
  assert.equal(env.INSPECTORPRO_LLM_GATEWAY_CONFIG, 'gateway.json');
  assert.deepEqual(source, original);
  const managed = childEnvironment({ ...profile, mode: 'managed' }, process.execPath, source);
  assert.equal(managed.PYTHONPATH, undefined);
});
