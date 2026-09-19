'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { createRuntimeLifecycle } = require('../src/runtime-lifecycle.cjs');
const { createFacilityRecoveryAdapter } = require('../src/facility-recovery-adapter.cjs');
const Session = require('../../static/facility_layout_session.js');
const base = require('../../tests/fixtures/facility_layout/empty_cell.json');
const clone = value => JSON.parse(JSON.stringify(value));
const { capture, WORKFLOWS } = require('../../static/desktop_workflow_observation.js');
const emptyWorkflows = () => Object.fromEntries(Object.keys(WORKFLOWS).map(id =>
  [id, { loaded: false, dirty: false, busy: false, pending: false }]));

async function fixture(t, options = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'runtime-attach-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const runtime = { schemaVersion: 1, mode: 'desktop-managed', identity: { backendId: 'backend', storeId: 'store', principalId: 'principal' },
    owner: { sessionId: 'session', ownerId: 'owner' }, document: { tenantId: 'local', siteId: 'site-local', documentId: base.layoutId },
    instanceId: 'process-one', origin: 'http://127.0.0.1:8099', capabilities: { facilityAcceptance: true, generalEditing: false, researchBrowsing: false } };
  const session = Session.createSession({ previewOperations: async () => { throw new Error('No edit transport during attach'); },
    applyOperations: async () => { throw new Error('Save forbidden'); } });
  session.load({ layout: clone(base), revision: 'saved-revision' });
  const facade = session.installDesktopRecovery({ startupRecoveryPending: true, allowSave: false,
    persistOperation: async () => { throw new Error('No operation during attach'); }, clearOperation: async () => { throw new Error('No operation during attach'); } });
  const initial = facade.snapshot(); let locks = 0, factories = 0, preparations = 0, commits = 0;
  const otherWorkflows = emptyWorkflows(); let observations = 0;
  const editor = Object.fromEntries(Object.keys(facade).map(name => [name, async (args, control) => {
    if (control) control.assertCurrent();
    return name === 'snapshot' ? clone(facade.snapshot()) : clone(facade[name](args));
  }]));
  const lifecycle = createRuntimeLifecycle({ profile: { dataRoot: directory },
    inspectOtherWorkflows: options.missingCoverage ? undefined : async () => {
      observations++; if (options.onObservation) options.onObservation(otherWorkflows, observations);
      return capture(otherWorkflows, initial.rendererGeneration);
    },
    supervisor: { getState: () => ({ status: 'ready', runtime }), request: async () => { throw new Error('No transaction lookup'); } }, editor,
    setBackendAccess() {}, lockInput() { locks++; }, closeConnections: async () => {}, commitWindow: async () => { commits++; }, decideClose: async () => 'cancel',
    adapterFactory: async value => { factories++; const adapter = await createFacilityRecoveryAdapter(value);
      if (options.afterConstruct) await options.afterConstruct({ facade, session, editor, runtime });
      return { ...adapter, prepare: async reason => { preparations++; const result = await adapter.prepare(reason);
        if (options.afterPrepare) options.afterPrepare(otherWorkflows); return result; } }; } });
  const binding = { schemaVersion: 1, identity: clone(runtime.identity), owner: clone(runtime.owner),
    document: { ...runtime.document, ...initial.document }, runtimeInstanceId: runtime.instanceId,
    rendererGeneration: initial.rendererGeneration, stateSequence: initial.stateSequence };
  return { lifecycle, initial, binding, facade, session, editor, runtime, directory, otherWorkflows,
    get locks() { return locks; }, get factories() { return factories; },
    get preparations() { return preparations; }, get commits() { return commits; } };
}

test('uncovered workflow blocks Close and Restart before freeze, backend access changes or commit', async t => {
  const f = await fixture(t); await f.lifecycle.attach(f.binding);
  const before = f.facade.snapshot(); f.otherWorkflows.processMap.dirty = true;
  await assert.rejects(f.lifecycle.close(), { code: 'desktop_workflow_recovery_not_enabled' });
  await assert.rejects(f.lifecycle.restart(), { code: 'desktop_workflow_recovery_not_enabled' });
  assert.deepEqual(f.facade.snapshot(), before);
  assert.equal(f.preparations + f.commits + f.locks, 0);
});

test('missing coverage is not clean', async t => {
  const f = await fixture(t, { missingCoverage: true }); await f.lifecycle.attach(f.binding);
  await assert.rejects(f.lifecycle.close(), { code: 'desktop_workflow_coverage_unavailable' });
  assert.equal(f.preparations + f.commits, 0);
});

test('new non-facility state during preparation cancels the facility freeze without discarding either', async t => {
  const f = await fixture(t, { afterPrepare: values => { values.agent.pending = true; } });
  await f.lifecycle.attach(f.binding); const before = f.facade.snapshot();
  await assert.rejects(f.lifecycle.close(), { code: 'desktop_workflow_recovery_not_enabled' });
  assert.deepEqual(f.facade.snapshot(), before); assert.equal(f.otherWorkflows.agent.pending, true);
  assert.equal(f.preparations, 1); assert.equal(f.commits, 0);
});

test('new state at the final commit guard releases the temporary freeze and never closes', async t => {
  const f = await fixture(t, { onObservation: (values, count) => { if (count === 3) values.agent.pending = true; } });
  await f.lifecycle.attach(f.binding); const before = f.facade.snapshot();
  const result = await f.lifecycle.close();
  assert.equal(result.status, 'blocked'); assert.ok(result.blockers.includes('desktop_workflow_recovery_not_enabled'));
  assert.deepEqual(f.facade.snapshot(), before); assert.equal(f.commits, 0);
});

test('main lifecycle plus real adapter and actual session accepts only its expected clean startup-gate transition', async t => {
  const f = await fixture(t); const result = await f.lifecycle.attach(f.binding);
  assert.equal(result.ready, true); assert.equal(result.recoveryRequired, false); assert.equal(f.lifecycle.hasFacility(), true);
  const after = f.facade.snapshot();
  assert.deepEqual(after, { ...f.initial, startupRecoveryPending: false, stateSequence: f.initial.stateSequence + 1 });
  assert.equal(f.factories, 1); assert.equal(f.locks, 0);
  await assert.rejects(f.session.save(), { code: 'facility_desktop_save_disabled' });
  assert.deepEqual(await f.lifecycle.attach(clone(f.binding)), result); assert.equal(f.factories, 1);
});

test('stale attach claim is rejected before real journal construction', async t => {
  const f = await fixture(t); f.binding.stateSequence++;
  await assert.rejects(f.lifecycle.attach(f.binding), { code: 'desktop_facility_attach_changed' });
  assert.equal(f.factories, 0); assert.equal(f.locks, 1); assert.equal(f.lifecycle.hasFacility(), false);
  assert.deepEqual(f.facade.snapshot(), f.initial);
  await assert.rejects(fs.access(path.join(f.directory, 'desktop-recovery')));
});

test('actual camera mutation after adapter construction is rejected and retained without grant', async t => {
  const f = await fixture(t, { afterConstruct: ({ session }) => session.setCameraState({ x: 1, z: 2, zoom: 1 }) });
  await assert.rejects(f.lifecycle.attach(f.binding), { code: 'desktop_facility_attach_changed' });
  assert.equal(f.factories, 1); assert.equal(f.locks, 1); assert.equal(f.lifecycle.hasFacility(), false);
  assert.notDeepEqual(f.facade.snapshot(), f.initial);
});

for (const field of ['document', 'editorFrame', 'pendingOperations']) {
  test('post-construction ' + field + ' discrepancy cannot be hidden by the expected gate sequence', async t => {
    const f = await fixture(t, { afterConstruct: ({ editor }) => {
      const snapshot = editor.snapshot;
      editor.snapshot = async () => {
        const state = await snapshot();
        if (field === 'document') state.document.draftRevision = 'foreign';
        if (field === 'editorFrame') state.editorFrame.selectedIds = ['foreign'];
        if (field === 'pendingOperations') state.pendingOperations = [{ kind: 'undo', requestId: 'unexpected' }];
        return state;
      };
    } });
    await assert.rejects(f.lifecycle.attach(f.binding), { code: 'desktop_facility_attach_changed' });
    assert.equal(f.lifecycle.hasFacility(), false); assert.equal(f.locks, 1);
  });
}

test('runtime process changing during guarded adapter construction rejects attachment', async t => {
  const f = await fixture(t, { afterConstruct: ({ runtime }) => { runtime.instanceId = 'different-process'; } });
  await assert.rejects(f.lifecycle.attach(f.binding), { code: 'desktop_facility_attach_changed' });
  assert.equal(f.lifecycle.hasFacility(), false); assert.equal(f.locks, 1);
});
