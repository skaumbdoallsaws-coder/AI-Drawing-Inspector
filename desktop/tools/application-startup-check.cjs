'use strict';
// Opt-in normal backend startup campaign on a prepared isolated application copy.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { loadApplicationProfile } = require('../src/application-profile.cjs');
const { createManagedRuntime } = require('../src/runtime-supervisor.cjs');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
async function main() {
  const [profileFile, python, output, count = '10'] = process.argv.slice(2);
  assert.ok([profileFile, python, output].every(value => typeof value === 'string' && path.isAbsolute(value)),
    'Usage: node application-startup-check.cjs ABS_PROFILE ABS_PYTHON ABS_OUTPUT [COUNT]');
  const samples = Number(count);
  assert.ok(Number.isSafeInteger(samples) && samples >= 2 && samples <= 20);
  const root = path.resolve(__dirname, '../..');
  const profile = await loadApplicationProfile(profileFile);
  const source = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'application-check-source.json'), 'utf8'));
  assert.equal(profile.facilityRoot, source.isolatedFacilityRoot);
  assert.notEqual(path.resolve(profile.facilityRoot), path.resolve(root, '.runtime/facility-layout'));
  assert.ok(path.resolve(output).startsWith(path.resolve(root, '.runtime') + path.sep));
  await fs.mkdir(output, { recursive: false });
  const copied = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', path.basename(source.originalPath));
  const before = { original: hash(await fs.readFile(source.originalPath)), isolated: hash(await fs.readFile(copied)) };
  assert.equal(before.original, source.originalSha256);
  assert.deepEqual(before, { original: source.originalSha256, isolated: source.originalSha256 });
  const report = { scope: 'real normal backend; isolated store; no provider, editing, Save or renderer',
    status: 'running', requestedSamples: samples, samples: [], before, startupDeadlineMs: 120000 };
  const runtime = createManagedRuntime({ profile, python, appRoot: root, startupTimeoutMs: 120000 });
  const persist = () => fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  try {
    for (let index = 0; index < samples; index++) {
      const identity = index ? await runtime.restart() : await runtime.start();
      assert.equal(runtime.getState().status, 'ready');
      assert.equal(identity.instanceId, runtime.getState().instanceId);
      assert.ok(!report.samples.some(sample => sample.instanceId === identity.instanceId));
      report.samples.push({ index, instanceId: identity.instanceId, startupMs: runtime.getEvidence().at(-1).startupMs });
      report.backends = runtime.getEvidence();
      await persist();
    }
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.failure = { code: error.code || null, message: error.message };
  } finally {
    report.cleanup = await runtime.stop();
    report.backends = runtime.getEvidence();
    report.after = { original: hash(await fs.readFile(source.originalPath)), isolated: hash(await fs.readFile(copied)) };
    report.savedUnchanged = JSON.stringify(before) === JSON.stringify(report.after);
    if (!report.savedUnchanged || !report.cleanup.terminationConfirmed || !report.cleanup.stdioClosed || !report.cleanup.resourcesClosed) report.status = 'failed';
    await persist();
  }
  console.log(JSON.stringify({ status: report.status, samples: report.samples, failure: report.failure || null }));
  process.exitCode = report.status === 'passed' ? 0 : 1;
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
