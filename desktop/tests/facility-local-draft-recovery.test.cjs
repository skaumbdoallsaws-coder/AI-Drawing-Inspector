'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { execFileSync } = require('node:child_process');
const Session = require('../../static/facility_layout_session.js');
const { createFacilityRecoveryAdapter } = require('../src/facility-recovery-adapter.cjs');
const { createRecoveryStore } = require('../src/recovery-store.cjs');
const { createRuntimeLifecycle } = require('../src/runtime-lifecycle.cjs');
const base = require('../../tests/fixtures/facility_layout/empty_cell.json');
const project = path.resolve(__dirname, '../..');
const clone = value => JSON.parse(JSON.stringify(value));
const identity = { backendId: 'backend', storeId: 'store', principalId: 'principal' };
const document = { tenantId: 'local', siteId: 'site-local', documentId: base.layoutId };
const owner = { sessionId: 'session', ownerId: 'owner' };
const binding = { identity, document, owner };
const program = ['import json,sys', 'from ai_inspector.facility_layout.canonical import layout_revision',
  'from ai_inspector.facility_layout.operations import apply_facility_layout_operations', 'r=json.load(sys.stdin)',
  'v=apply_facility_layout_operations(r["layout"],r["operations"],base_revision=layout_revision(r["layout"]))',
  'print(json.dumps({"layout":v["document"],"revision":layout_revision(v["document"]),"changed":v["changed"]}))'].join('\n');
const cache = new Map();
function kernel(layout, operations) {
  const key = JSON.stringify({ layout, operations });
  if (!cache.has(key)) cache.set(key, JSON.parse(execFileSync(process.env.CONSTRUCTION_TEST_PYTHON || 'python', ['-c', program],
    { cwd: project, input: key, encoding: 'utf8', timeout: 20000 })));
  return clone(cache.get(key));
}
function initial() { return kernel(base, [{ op: 'add_zone', zone: { zoneId: 'zn-local', label: 'Original', zoneType: 'workcell',
  boundary: [{ x: 0, z: 0 }, { x: 4, z: 0 }, { x: 4, z: 4 }, { x: 0, z: 4 }], floorElevation: 0, anchors: [], evidence: [] } }]); }
async function directory(t) { const value = await fs.mkdtemp(path.join(os.tmpdir(), 'facility-local-draft-'));
  t.after(() => fs.rm(value, { recursive: true, force: true })); await fs.writeFile(path.join(value, 'saved-layout.json'), JSON.stringify(initial())); return value; }
async function open(directory, options = {}) {
  const receipt = initial(); let saves = 0, lookups = 0, commits = 0, finalized = null;
  const session = Session.createSession({ previewOperations: async request => kernel(receipt.layout, request.operations),
    applyOperations: async () => { saves++; throw new Error('Save forbidden'); } });
  session.load(receipt);
  if (options.beforeInstall) await options.beforeInstall(session);
  const selectedOwner = options.owner || owner;
  const selectedBinding = { identity, document, owner: selectedOwner };
  const facade = session.installDesktopRecovery({ startupRecoveryPending: true, allowSave: false, binding: selectedBinding,
    persistOperation: async record => adapter.persistOperation(record), clearOperation: async record => adapter.clearOperation(record) });
  const store = options.store || await createRecoveryStore({ directory: path.join(directory, 'journal'), identity });
  const adapter = await createFacilityRecoveryAdapter({ authorizedDesktopRuntime: { schemaVersion: 1, mode: 'desktop-managed',
    verified: true, facilityAcceptance: true, instanceId: options.instanceId || 'process', ...selectedBinding }, ...selectedBinding,
    editor: facade, recoveryStore: store, lookupOperation: async () => { lookups++; throw new Error('Plain drafts require no transaction lookup'); },
    commitLifecycle: async (request, control, finalizeDiscard) => {
      commits++; control.assertCurrent();
      if (options.commit) return options.commit({ request, control, finalizeDiscard, store });
      finalized = await finalizeDiscard();
    } });
  return { adapter, facade, session, store, directory, get saves() { return saves; }, get lookups() { return lookups; }, get commits() { return commits; }, get finalized() { return finalized; } };
}
async function edit(f) { f.session.select('zn-local'); await f.session.editZoneLabel('zn-local', 'Edit one'); await f.session.editZoneLabel('zn-local', 'Edit two'); }
async function prepared(f) { const value = await f.adapter.prepare('close'); assert.equal(value.status, 'needsDecision'); return value; }
const expected = f => { const value = f.facade.snapshot(); return { expectedRendererGeneration: value.rendererGeneration, expectedStateSequence: value.stateSequence }; };
async function currentEntry(f) { return (await f.adapter.listRecovery()).find(entry => !entry.supersededBy && !entry.retiredBy && entry.type !== 'discard'); }
async function restore(f) { const entry = await currentEntry(f); return f.adapter.recover({ key: entry.key, expectedCheckpointId: entry.checkpointId, ...expected(f) }); }
async function discard(f, intent) { return f.adapter.commit({ intentId: intent.intentId, rendererGeneration: intent.rendererGeneration,
  stateSequence: intent.stateSequence, discardDocumentIds: [document.documentId] }); }
async function records(f) { const result = {}; for (const item of await f.store.list()) result[item.key] = await f.store.read(item.key); return result; }

test('two actual kernel edits, selection and complete Undo history restore across sessions as a bound local draft', async t => {
  const folder = await directory(t), first = await open(folder); await edit(first);
  const before = first.facade.snapshot(); await prepared(first);
  const next = await open(folder, { instanceId: 'process-next' });
  assert.equal(next.facade.snapshot().startupRecoveryPending, true);
  await restore(next);
  const after = next.facade.snapshot();
  assert.deepEqual(after.editorFrame, before.editorFrame); assert.deepEqual(after.camera, before.camera);
  assert.equal(after.pendingOperations.length, 0); assert.equal(after.recoveryOwned, false); assert.equal(after.startupRecoveryPending, false);
  await next.session.undo(); assert.equal(next.facade.snapshot().editorFrame.draftLayout.zones[0].label, 'Edit one');
  await next.session.redo();
  const replayed = next.facade.snapshot().editorFrame;
  assert.notEqual(replayed.editorGenerationId, before.editorFrame.editorGenerationId);
  assert.deepEqual({ ...replayed, editorGenerationId: before.editorFrame.editorGenerationId }, before.editorFrame);
  await assert.rejects(next.session.save(), { code: 'facility_desktop_save_disabled' });
  assert.equal(next.lookups + next.saves, 0); assert.equal(await fs.readFile(path.join(folder, 'saved-layout.json'), 'utf8'), JSON.stringify(initial()));
});

test('main recovery entry supplies current generation and sequence to the real local-draft adapter', async t => {
  const folder = await directory(t), first = await open(folder); await edit(first);
  const original = first.facade.snapshot(); await prepared(first);
  const next = await open(folder), state = next.facade.snapshot();
  const runtime = { ...binding, instanceId: 'next-process', origin: 'http://127.0.0.1:8099', capabilities: { facilityAcceptance: true } };
  const lifecycle = createRuntimeLifecycle({ profile: { dataRoot: folder }, supervisor: { getState: () => ({ status: 'ready', runtime }) },
    editor: next.facade, adapterFactory: async () => next.adapter, setBackendAccess() {}, lockInput() {}, closeConnections: async () => {},
    commitWindow: async () => {}, decideClose: async () => 'cancel' });
  const result = await lifecycle.attach({ schemaVersion: 1, ...binding, document: { ...document, ...state.document },
    runtimeInstanceId: runtime.instanceId, rendererGeneration: state.rendererGeneration, stateSequence: state.stateSequence });
  assert.equal(result.recoveryRequired, true);
  const entry = (await lifecycle.retainedRecovery()).find(item => item.needsRestore);
  const restored = await lifecycle.restoreRetained(entry.key, entry.checkpointId);
  assert.equal(restored.recoveryRequired, false); assert.deepEqual(next.facade.snapshot().editorFrame, original.editorFrame);
  assert.equal(next.lookups + next.saves, 0);
});

test('plain draft restore rejects stale generation, state, foreign owner and dirty-current replacement without loss', async t => {
  const folder = await directory(t), first = await open(folder); await edit(first); await prepared(first);
  const next = await open(folder), entry = await currentEntry(next), before = next.facade.snapshot();
  for (const change of [{ expectedRendererGeneration: 'foreign' }, { expectedStateSequence: before.stateSequence + 1 }]) {
    await assert.rejects(next.adapter.recover({ key: entry.key, expectedCheckpointId: entry.checkpointId, ...expected(next), ...change }), { code: 'facility_state_changed' });
    assert.deepEqual(next.facade.snapshot(), before);
  }
  await assert.rejects(open(folder, { owner: { ...owner, ownerId: 'other-writer' } }), { code: 'facility_recovery_owner_mismatch' });
  const dirty = await open(folder, { beforeInstall: session => session.editZoneLabel('zn-local', 'Current draft') });
  const retained = dirty.facade.snapshot(); await assert.rejects(restore(dirty), { code: 'facility_restore_would_replace_draft' });
  assert.deepEqual(dirty.facade.snapshot(), retained);
});

test('plain facade restore requires exact reconciled native binding and refuses invented, pending or altered checkpoint data', async t => {
  const folder = await directory(t), first = await open(folder); await edit(first); await prepared(first);
  const next = await open(folder), entry = await currentEntry(next), original = (await next.store.read(entry.key)).record;
  const before = next.facade.snapshot();
  const changes = [record => { record.identity.storeId = 'foreign'; }, record => { record.payload.owner.ownerId = 'foreign'; },
    record => { record.document.siteId = 'foreign'; }, record => { record.document.baseRevision = 'foreign'; },
    record => { record.handle.state = 'unknown'; }, record => { record.payload.snapshot.pendingOperations = [{ kind: 'apply', requestId: 'pending' }]; },
    record => { record.payload.snapshot.designProposalDraft = { transactionId: 'active-transaction', status: 'active' }; },
    record => { record.payload.snapshot.editorFrame.activeProposal = { transactionId: 'active-transaction', status: 'active' }; }];
  for (const change of changes) {
    const record = clone(original); change(record);
    assert.throws(() => next.facade.restoreRecovery({ record, snapshot: record.payload.snapshot, ...expected(next) }), { code: 'facility_desktop_recovery_binding' });
    assert.deepEqual(next.facade.snapshot(), before);
  }
  assert.throws(() => next.facade.restoreRecovery({ record: original, snapshot: { ...original.payload.snapshot, camera: { tampered: true } }, ...expected(next) }), { code: 'facility_desktop_recovery_binding' });
});

test('Close Cancel preserves exact current draft and leaves no retirement receipt', async t => {
  const f = await open(await directory(t)); await edit(f); const before = f.facade.snapshot(), intent = await prepared(f);
  assert.equal((await f.adapter.cancel(intent.intentId)).status, 'cancelled');
  assert.deepEqual(f.facade.snapshot(), before); assert.deepEqual(await records(f), {}); assert.equal(f.commits, 0);
});

test('explicit Close without Save atomically retires reconciled draft history and reopening starts from unchanged saved layout', async t => {
  const folder = await directory(t), f = await open(folder); await edit(f); const intent = await prepared(f), prior = await records(f);
  assert.equal((await discard(f, intent)).status, 'committed'); assert.equal(f.finalized.retired, 1);
  const after = await records(f); for (const [key, record] of Object.entries(prior)) assert.deepEqual(after[key], record);
  assert.equal(Object.values(after).filter(item => item.record.payload.type === 'discard').length, 1);
  const next = await open(folder, { instanceId: 'process-next' });
  assert.equal((await next.adapter.getSaveGate()).allowed, true); assert.equal(next.facade.snapshot().dirty, false);
  assert.equal((await next.adapter.listRecovery()).some(item => item.needsRestore), false);
  assert.deepEqual(next.facade.snapshot().editorFrame.draftLayout, initial().layout);
  await edit(next); const cancelled = await prepared(next); await next.adapter.cancel(cancelled.intentId);
  const third = await open(folder, { instanceId: 'process-third' }); assert.equal((await third.adapter.getSaveGate()).allowed, true);
  assert.equal(await fs.readFile(path.join(folder, 'saved-layout.json'), 'utf8'), JSON.stringify(initial()));
  assert.equal(f.saves + next.saves + third.saves, 0);
});

test('retirement closes an adopted supersession chain so previous drafts cannot reappear', async t => {
  const folder = await directory(t), first = await open(folder); await edit(first); await prepared(first);
  const old = await currentEntry(first), previous = (await first.store.read(old.key)).record;
  const replacement = clone(previous); replacement.handle.requestId = 'close-later';
  replacement.payload.supersedes = [{ key: old.key, checkpointId: old.checkpointId,
    adoption: { rendererGeneration: first.facade.snapshot().rendererGeneration, stateSequence: first.facade.snapshot().stateSequence } }];
  await first.store.write({ key: 'later_draft', record: replacement });
  const next = await open(folder); await restore(next);
  const intent = await prepared(next); assert.equal((await discard(next, intent)).status, 'committed');
  assert.equal(next.finalized.retired, 3);
  const reopened = await open(folder); assert.equal((await reopened.adapter.getSaveGate()).allowed, true);
  assert.equal((await reopened.adapter.listRecovery()).filter(item => item.needsRestore).length, 0);
});

test('failed cleanup and missing finalization never retire valid records or call a late finalizer', async t => {
  for (const mode of ['cleanup-failure', 'missing-finalizer']) {
    const folder = await directory(t); let held;
    const f = await open(folder, { commit: async ({ finalizeDiscard }) => { held = finalizeDiscard;
      if (mode === 'cleanup-failure') throw Object.assign(new Error('cleanup'), { code: 'cleanup_failed' }); } });
    await edit(f); const intent = await prepared(f), before = await records(f);
    const result = await discard(f, intent); assert.equal(result.status, 'blocked');
    assert.equal(result.blockers[0], mode === 'cleanup-failure' ? 'cleanup_failed' : 'facility_discard_finalization_required');
    assert.deepEqual(await records(f), before);
    await assert.rejects(held(), error => error.code === 'lifecycle_callback_settled');
    assert.deepEqual(await records(f), before);
    const next = await open(folder); assert.equal((await next.adapter.getSaveGate()).allowed, false);
  }
});

test('checkpoint change after cleanup but before finalization blocks retirement and preserves the replacement', async t => {
  let changed;
  const folder = await directory(t), f = await open(folder, { commit: async ({ store, finalizeDiscard }) => {
    const item = (await store.list())[0], envelope = await store.read(item.key);
    changed = await store.write({ key: item.key, expectedCheckpointId: envelope.checkpointId, record: envelope.record });
    await finalizeDiscard();
  } });
  await edit(f); const result = await discard(f, await prepared(f)); assert.equal(result.status, 'blocked');
  assert.equal(result.blockers[0], 'facility_discard_checkpoint_conflict');
  const all = await records(f); assert.equal(Object.keys(all).length, 1); assert.equal(all[changed.key].checkpointId, changed.checkpointId);
});

test('receipt write failure leaves each valid checkpoint intact and recoverable', async t => {
  const folder = await directory(t), actual = await createRecoveryStore({ directory: path.join(folder, 'journal'), identity });
  const store = { ...actual, async write(input) { if (input.record.payload.type === 'discard') throw Object.assign(new Error('replacement'), { code: 'EPERM' }); return actual.write(input); } };
  const f = await open(folder, { store }); await edit(f); const intent = await prepared(f), before = await records(f);
  assert.deepEqual((await discard(f, intent)).blockers, ['EPERM']); assert.deepEqual(await records(f), before);
  const next = await open(folder); await restore(next); assert.equal(next.facade.snapshot().editorFrame.batches.length, 2);
});

test('another document record is never included or changed by this document discard', async t => {
  const f = await open(await directory(t)); await edit(f); const intent = await prepared(f), entry = await currentEntry(f);
  const other = clone((await f.store.read(entry.key)).record);
  other.document.documentId = 'fl-other'; other.payload.snapshot.document.documentId = 'fl-other';
  other.payload.owner = { sessionId: 'other-session', ownerId: 'other-owner' }; other.handle.state = 'unknown';
  const written = await f.store.write({ key: 'other_document', record: other });
  // Added other-document state is outside this adapter's recovery inventory.
  assert.equal((await discard(f, intent)).status, 'committed');
  assert.equal((await f.store.read(written.key)).checkpointId, written.checkpointId);
  const receipt = Object.values(await records(f)).find(item => item.record.payload.type === 'discard');
  assert.equal(receipt.record.payload.retiredCheckpoints.some(ref => ref.key === written.key), false);
});
