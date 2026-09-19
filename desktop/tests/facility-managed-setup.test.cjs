'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { setupError, setupStep, editLabelInRenderer } = require('../tools/facility-managed-setup.cjs');
const { runManagedScenarios, atomicJson } = require('../tools/facility-managed-recovery-scenarios.cjs');

const secret = 'PRIVATE_RESPONSE_BODY_OR_CREDENTIAL_SENTINEL';
const clone = value => JSON.parse(JSON.stringify(value));
function spatialError() {
  return Object.assign(new Error('Facility Layout spatial execution exceeded its time limit.'), {
    code: 'spatial_execution_timeout', status: 504,
    details: { jobId: 'spatial-job-00000007', body: secret, headers: { authorization: secret }, unrelated: secret },
    body: secret, headers: { authorization: secret }, response: { text: secret },
  });
}
const publicError = {
  message: 'Facility Layout spatial execution exceeded its time limit.',
  code: 'spatial_execution_timeout', status: 504, details: { jobId: 'spatial-job-00000007' },
};
function renderer(session) {
  const context = vm.createContext({ window: { __facilityHarness: { session } }, unexpectedMutation: false });
  let evaluations = 0;
  return { context, get evaluations() { return evaluations; },
    evaluate: expression => { evaluations += 1; return vm.runInContext(expression, context); } };
}
async function directory(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'facility-managed-setup-test-'));
  t.after(async () => {
    const resolved = path.resolve(root);
    assert.equal(path.dirname(resolved), path.resolve(os.tmpdir()));
    assert.ok(path.basename(resolved).startsWith('facility-managed-setup-test-'));
    await fs.rm(resolved, { recursive: true, force: true });
  });
  return root;
}
function assertTiming(step) {
  assert.ok(Number.isFinite(step.elapsedMs) && step.elapsedMs >= 0);
  assert.ok(Number.isFinite(Date.parse(step.startedAt)));
  assert.ok(Number.isFinite(Date.parse(step.finishedAt)));
}

test('generated renderer edit selects and edits once with literal IDs and labels', async () => {
  const id = 'zone-"\n${globalThis.unexpectedMutation = true}//';
  const label = 'Operator "A"\n` ${globalThis.unexpectedMutation = true}';
  const calls = [];
  const r = renderer({ select: value => calls.push(['select', value]),
    editZoneLabel: async (...values) => { calls.push(['edit', ...values]); } });
  assert.equal(await editLabelInRenderer(r.evaluate, id, label), undefined);
  assert.equal(r.evaluations, 1);
  assert.deepEqual(calls, [['select', id], ['edit', id, label]]);
  assert.equal(r.context.unexpectedMutation, false);
});

test('renderer edit errors retain code, HTTP status and spatial job ID without body, headers or unrelated details', async () => {
  let edits = 0;
  const r = renderer({ select() {}, async editZoneLabel() { edits += 1; throw spatialError(); } });
  await assert.rejects(editLabelInRenderer(r.evaluate, 'zone-a', 'Renamed'), error => {
    assert.deepEqual(setupError(error), publicError);
    assert.deepEqual(error.details, { jobId: 'spatial-job-00000007' });
    for (const key of ['body', 'headers', 'response', 'unrelated']) assert.equal(error[key], undefined);
    assert.equal(JSON.stringify(error).includes(secret), false);
    return true;
  });
  assert.equal(edits, 1);
  assert.equal(r.evaluations, 1, 'Error diagnostics must never retry the edit');
});

test('a selection failure prevents the edit and preserves its public error fields', async () => {
  let edits = 0;
  const r = renderer({ select() { throw spatialError(); }, async editZoneLabel() { edits += 1; } });
  await assert.rejects(editLabelInRenderer(r.evaluate, 'zone-a', 'Renamed'), error => {
    assert.deepEqual(setupError(error), publicError); return true;
  });
  assert.equal(edits, 0);
  assert.equal(r.evaluations, 1);
});

test('renderer error diagnostics bound text and reject unrelated or malformed job details', async () => {
  const r = renderer({ select() {}, async editZoneLabel() {
    throw Object.assign(new Error('m'.repeat(5000)), { code: 'c'.repeat(600), status: '504',
      details: { jobId: '../private-layout', body: secret }, headers: { authorization: secret } });
  } });
  await assert.rejects(editLabelInRenderer(r.evaluate, 'zone-a', 'Renamed'), error => {
    assert.equal(error.message.length, 1024);
    assert.equal(error.code.length, 128);
    assert.equal(error.status, undefined);
    assert.equal(error.details, undefined);
    assert.equal(JSON.stringify(error).includes(secret), false);
    return true;
  });
});

test('a renderer transport rejection propagates without evaluating the edit again', async () => {
  const primary = Object.assign(new Error('Renderer disconnected'), { code: 'renderer_unavailable' });
  let evaluations = 0;
  await assert.rejects(editLabelInRenderer(async () => { evaluations += 1; throw primary; }, 'zone-a', 'Renamed'),
    error => error === primary);
  assert.equal(evaluations, 1);
});

test('an absent renderer reply never counts as a successful edit', async () => {
  let evaluations = 0;
  await assert.rejects(editLabelInRenderer(async () => { evaluations += 1; return undefined; }, 'zone-a', 'Renamed'),
    /Renderer edit returned no result/);
  assert.equal(evaluations, 1);
});

test('setupStep persists running before work and completion afterward without adding acceptance checks', async t => {
  const root = await directory(t);
  const file = path.join(root, 'report.json');
  const report = { checks: { existingAcceptance: 'passed' } };
  const saved = [];
  const save = async () => { await atomicJson(file, report); saved.push(JSON.parse(await fs.readFile(file, 'utf8'))); };
  const output = { snapshot: 'editor-frame' };
  const result = await setupStep(report, save, 'initial-editor-snapshot', async () => {
    const durable = JSON.parse(await fs.readFile(file, 'utf8'));
    assert.equal(durable.stage, 'initial-editor-snapshot');
    assert.deepEqual(durable.checks, report.checks);
    assert.equal(durable.setupSteps[0].status, 'running');
    assert.equal(durable.setupSteps[0].finishedAt, undefined);
    return output;
  });
  assert.equal(result, output);
  assert.deepEqual(saved.map(item => item.setupSteps[0].status), ['running', 'passed']);
  assert.deepEqual(report.checks, { existingAcceptance: 'passed' });
  const durable = JSON.parse(await fs.readFile(file, 'utf8'));
  assert.equal(durable.setupSteps[0].status, 'passed');
  assertTiming(durable.setupSteps[0]);
});

test('setupStep persists a failed stage with bounded error metadata and rethrows the original operation error', async t => {
  const root = await directory(t);
  const file = path.join(root, 'report.json');
  const report = { checks: {} };
  const primary = spatialError();
  let calls = 0;
  await assert.rejects(setupStep(report, () => atomicJson(file, report), 'manual-edit-1', async () => {
    calls += 1;
    assert.equal(JSON.parse(await fs.readFile(file, 'utf8')).setupSteps[0].status, 'running');
    throw primary;
  }), error => error === primary);
  const serialized = await fs.readFile(file, 'utf8');
  const durable = JSON.parse(serialized);
  assert.equal(durable.stage, 'manual-edit-1');
  assert.equal(durable.setupSteps[0].status, 'failed');
  assert.deepEqual(durable.setupSteps[0].error, publicError);
  assertTiming(durable.setupSteps[0]);
  assert.deepEqual(durable.checks, {});
  assert.equal(serialized.includes(secret), false);
  assert.equal(calls, 1);
});

test('failure to persist the running stage prevents setup work from starting', async () => {
  const primary = Object.assign(new Error('Cannot persist diagnostics'), { code: 'EIO' });
  let calls = 0;
  let saves = 0;
  const report = { checks: {} };
  await assert.rejects(setupStep(report, async () => { saves += 1; throw primary; }, 'manual-edit-1', async () => {
    calls += 1;
  }), error => error === primary);
  assert.equal(calls, 0);
  assert.equal(saves, 1);
  assert.deepEqual(report.checks, {});
});

for (const kind of ['normal', 'frozen', 'falsy']) {
  test('final diagnostic-save failure preserves a ' + kind + ' primary operation failure', async () => {
    const primary = kind === 'falsy' ? 0 : kind === 'frozen' ? Object.freeze(spatialError()) : spatialError();
    const secondary = Object.assign(new Error('Final diagnostic persistence failed'), { code: 'EIO' });
    let saves = 0;
    const report = { checks: {} };
    let caught = false;
    try {
      await setupStep(report, async () => { saves += 1; if (saves === 2) throw secondary; }, 'manual-edit-2',
        async () => { throw primary; });
    } catch (error) { caught = true; assert.equal(error, primary, 'Diagnostic write failure must not replace the operation failure'); }
    assert.equal(caught, true);
    assert.equal(saves, 2);
    assert.equal(report.setupSteps[0].status, 'failed');
    assertTiming(report.setupSteps[0]);
    assert.deepEqual(report.checks, {});
    if (kind !== 'falsy') assert.deepEqual(report.setupSteps[0].error, publicError);
  });
}

test('a successful operation is not acknowledged if its completion diagnostic cannot be persisted', async () => {
  const failure = Object.assign(new Error('Completion diagnostics not saved'), { code: 'EIO' });
  let saves = 0;
  let calls = 0;
  await assert.rejects(setupStep({ checks: {} }, async () => { saves += 1; if (saves === 2) throw failure; },
    'manual-edit-1', async () => { calls += 1; return 'completed'; }), error => error === failure);
  assert.equal(calls, 1);
  assert.equal(saves, 2);
});

for (const failingEdit of [1, 2]) {
  test('scenario failure on manual edit ' + failingEdit + ' records the exact stage and stops before proposal, restart or Save', async t => {
    const root = await directory(t);
    const output = path.join(root, 'output');
    const controlDirectory = path.join(root, 'control');
    const reportFile = path.join(output, 'report.json');
    const runtime = { identity: { backendId: 'backend-a', storeId: 'store-a', principalId: 'principal-a' },
      document: { tenantId: 'tenant-a', siteId: 'site-a', documentId: 'manual-copy' },
      owner: { sessionId: 'session-a', ownerId: 'owner-a' }, instanceId: 'instance-a', origin: 'http://127.0.0.1:48371' };
    const frame = { draftLayout: { zones: [{ zoneId: 'zone-a', label: 'Receiving' }] }, cursor: 0, batches: [], selectedIds: [] };
    const counters = { edits: 0, snapshots: 0, begin: 0, save: 0, restart: 0, listRecovery: 0 };
    const requests = [];
    const r = renderer({
      select(id) { frame.selectedIds = [id]; },
      async editZoneLabel(id, label) {
        counters.edits += 1;
        const durable = JSON.parse(await fs.readFile(reportFile, 'utf8'));
        assert.equal(durable.stage, 'manual-edit-' + counters.edits);
        assert.equal(durable.setupSteps.at(-1).status, 'running');
        assert.deepEqual(durable.checks, {});
        if (counters.edits === failingEdit) throw spatialError();
        frame.draftLayout.zones[0].label = label;
        frame.batches.push({ label: 'Rename zone', operations: [{ op: 'edit_zone', zoneId: id, patch: { label } }] });
        frame.cursor += 1;
      },
    });
    const driver = {
      mode: 'engine',
      async request(route) {
        requests.push(route);
        assert.equal(route, '/__facility-recovery__/runtime', 'Proposal or transaction endpoint must not be reached');
        return clone(runtime);
      },
      async snapshot() { counters.snapshots += 1; return { editorFrame: clone(frame) }; },
      editLabel: (id, label) => editLabelInRenderer(r.evaluate, id, label),
      async begin() { counters.begin += 1; throw new Error('Apply/Undo must not start'); },
      async assertSessionSaveBlocked() { counters.save += 1; throw new Error('Save must not be invoked during setup failure'); },
      setBackendAccess() { counters.restart += 1; throw new Error('Backend restart must not start'); },
      adapter: { async listRecovery() { counters.listRecovery += 1; throw new Error('Recovery must not start'); } },
    };
    await assert.rejects(runManagedScenarios(driver, { case: 'undo-success', dataRoot: root, output, controlDirectory }), error => {
      assert.deepEqual(setupError(error), publicError); return true;
    });
    const serialized = await fs.readFile(reportFile, 'utf8');
    const report = JSON.parse(serialized);
    assert.equal(report.status, 'failed');
    assert.equal(report.stage, 'manual-edit-' + failingEdit);
    assert.deepEqual(report.setupSteps.map(item => [item.name, item.status]), [
      ['initial-editor-snapshot', 'passed'],
      ...Array.from({ length: failingEdit }, (_, i) => ['manual-edit-' + (i + 1), i + 1 === failingEdit ? 'failed' : 'passed']),
    ]);
    report.setupSteps.forEach(assertTiming);
    assert.deepEqual(report.setupSteps.at(-1).error, publicError);
    assert.deepEqual(setupError(report.error), publicError);
    assert.deepEqual(report.checks, {}, 'Setup diagnostics must not inflate accepted recovery checks');
    assert.equal(report.manualFrameHash, undefined);
    assert.equal(report.pendingOperation, undefined);
    assert.equal(report.restart, undefined);
    assert.equal(report.generalEditing, false);
    assert.equal(report.researchBrowsing, false);
    assert.equal(serialized.includes(secret), false);
    assert.deepEqual(requests, ['/__facility-recovery__/runtime']);
    assert.deepEqual(counters, { edits: failingEdit, snapshots: 1, begin: 0, save: 0, restart: 0, listRecovery: 0 });
    assert.equal(r.evaluations, failingEdit);
    assert.equal(frame.cursor, failingEdit - 1);
    assert.equal(frame.batches.length, failingEdit - 1);
    assert.equal(frame.draftLayout.zones[0].label, failingEdit === 1 ? 'Receiving' : 'Receiving [managed edit 1]');
    await assert.rejects(fs.stat(controlDirectory), { code: 'ENOENT' });
  });
}
