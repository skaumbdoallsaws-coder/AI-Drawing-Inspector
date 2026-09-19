'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createRecoveryStore } = require('../src/recovery-store.cjs');
const { createFacilityRecoveryAdapter } = require('../src/facility-recovery-adapter.cjs');

const identity = { backendId: 'backend-fixture', storeId: 'isolated-store', principalId: 'fixture-principal' };
const document = { tenantId: 'tenant-fixture', siteId: 'site-fixture', documentId: 'layout-fixture' };
const owner = { sessionId: 'backend-session-fixture', ownerId: 'lease-owner-fixture' };
const clone = value => JSON.parse(JSON.stringify(value));
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
function editorDouble(rendererGeneration = 'renderer-1') {
  let frozen = null;
  let state = { schemaVersion: 1, rendererGeneration, stateSequence: 0,
    document: { documentId: document.documentId, baseRevision: 'saved-1', draftRevision: 'draft-0' },
    dirty: false, busy: false, conflict: null, pendingOperations: [], activeJobs: [],
    editorFrame: { layout: { placements: [{ id: 'machine-a', x: 0, y: 0 }] }, selectedIds: [], batches: [], cursor: 0, redo: [] },
    designProposalDraft: null, camera: { x: 20, y: 30 }, ghost: null, proposal: null };
  const calls = { freeze: 0, unfreeze: 0, restore: 0, adopt: 0, save: 0, apply: 0, undo: 0 };
  function check(request) {
    assert.equal(request.expectedRendererGeneration, state.rendererGeneration);
    assert.equal(request.expectedStateSequence, state.stateSequence);
  }
  const editor = {
    snapshot: () => clone(state),
    freeze(request, control) {
      control.assertCurrent();
      assert.equal(request.rendererGeneration, state.rendererGeneration);
      assert.equal(request.stateSequence, state.stateSequence);
      assert.ok(!frozen || frozen === request.intentId);
      frozen = request.intentId; calls.freeze++;
    },
    unfreeze(request, control) { control.assertCurrent(); if (frozen === request.intentId) frozen = null; calls.unfreeze++; },
    restoreRecovery(request) {
      check(request);
      const nextSequence = state.stateSequence + 1;
      state = { ...clone(request.snapshot), rendererGeneration, stateSequence: nextSequence, busy: false };
      calls.restore++;
    },
    acceptReconciliation(request) {
      check(request); calls.adopt++;
      state.pendingOperations = state.pendingOperations.filter(op => op.requestId !== request.requestId);
      state.busy = false; state.stateSequence++;
      return clone(state);
    },
  };
  return { editor, calls, get frozen() { return frozen; },
    state: () => clone(state),
    change(fn) { fn(state); state.stateSequence++; },
    edit(axis, value) {
      assert.equal(frozen, null);
      state.editorFrame.layout.placements[0][axis] = value;
      state.editorFrame.selectedIds = ['machine-a'];
      state.editorFrame.batches.push({ label: 'Move ' + axis, operations: [{ axis, value }] });
      state.editorFrame.cursor++; state.dirty = true;
      state.document.draftRevision = 'draft-' + state.editorFrame.cursor;
      state.stateSequence++;
    },
  };
}
async function fixture(t, extra = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'facility-recovery-adapter-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const savedPath = path.join(directory, 'saved-layout.txt');
  await fs.writeFile(savedPath, 'saved layout remains unchanged');
  const recoveryDirectory = path.join(directory, 'journal');
  const store = await createRecoveryStore({ directory: recoveryDirectory, identity });
  const local = editorDouble();
  const lookups = [];
  const commits = [];
  let backend = null;
  const options = { authorizedIsolatedHarness: true, identity, document, owner, editor: local.editor, recoveryStore: store,
    lookupOperation: async request => { lookups.push(clone(request)); return clone(backend || { identity, document, owner,
      requestId: request.requestId, transactionId: request.transactionId || 'transaction-a', kind: request.kind, status: 'unknown' }); },
    commitLifecycle: async request => { commits.push(clone(request)); }, ...extra };
  const adapter = await createFacilityRecoveryAdapter(options);
  return { directory, recoveryDirectory, savedPath, store, local, lookups, commits, options, adapter,
    setBackend(value) { backend = value; },
    resolved(kind = 'apply', more = {}) { backend = { identity, document, owner, requestId: 'request-a', transactionId: 'transaction-a',
      kind, status: 'resolved', outcome: kind === 'apply' ? 'applied' : 'undone', transactionRevision: 'transaction-revision-2', ...more }; },
  };
}
const operation = (extra = {}) => ({ kind: 'apply', requestId: 'request-a', phase: 'before-prepare', state: 'pending', ...extra });

test('creation is explicitly restricted to authorized isolated harness', async () => {
  await assert.rejects(createFacilityRecoveryAdapter(), { code: 'facility_harness_not_authorized' });
});

test('two edits then Close Cancel preserve the exact draft, selection, camera and Undo/Redo without Save', async t => {
  const f = await fixture(t); f.local.edit('x', 10); f.local.edit('y', 15);
  f.local.change(s => { s.editorFrame.redo = [{ label: 'Preserved future redo' }]; });
  const before = f.local.state();
  const prepared = await f.adapter.prepare('close');
  assert.equal(prepared.status, 'needsDecision');
  assert.equal(f.local.frozen, prepared.intentId);
  assert.equal((await f.adapter.getSaveGate()).allowed, false);
  const retained = await f.adapter.listRecovery();
  assert.equal(retained.length, 1);
  assert.deepEqual((await f.store.read(retained[0].key)).record.payload.snapshot, before);
  assert.equal((await f.adapter.cancel(prepared.intentId)).status, 'cancelled');
  assert.equal(f.local.frozen, null);
  assert.deepEqual(f.local.state(), before);
  assert.equal((await f.adapter.getSaveGate()).allowed, true);
  assert.equal((await f.adapter.listRecovery()).length, 0);
  assert.equal(f.local.calls.save + f.local.calls.apply + f.local.calls.undo + f.local.calls.restore, 0);
  assert.equal(await fs.readFile(f.savedPath, 'utf8'), 'saved layout remains unchanged');
});

test('Close without Save requires the exact prepared dirty-document decision and only invokes lifecycle commit', async t => {
  const f = await fixture(t); f.local.edit('x', 8);
  const before = f.local.state(); const prepared = await f.adapter.prepare('close');
  const noChoice = await f.adapter.commit({ ...prepared, discardDocumentIds: [] });
  assert.equal(noChoice.status, 'needsDecision'); assert.equal(f.commits.length, 0);
  const committed = await f.adapter.commit({ ...prepared, discardDocumentIds: [document.documentId] });
  assert.equal(committed.status, 'committed'); assert.equal(f.commits.length, 1);
  assert.deepEqual(f.local.state(), before);
  assert.equal(await fs.readFile(f.savedPath, 'utf8'), 'saved layout remains unchanged');
});

for (const kind of ['apply', 'undo']) test(`pending ${kind} prevents Close; Cancel retains its stable durable handle without duplicate execution`, async t => {
  const f = await fixture(t);
  const input = operation({ kind, transactionId: 'transaction-a', phase: 'before-ack' });
  const first = await f.adapter.persistOperation(input);
  const duplicate = await f.adapter.persistOperation(input);
  assert.equal(duplicate.duplicate, true); assert.equal(first.checkpointId, duplicate.checkpointId);
  f.local.change(s => { s.busy = true; s.pendingOperations = [input]; });
  const before = f.local.state(); const prepared = await f.adapter.prepare('close');
  assert.equal(prepared.status, 'blocked');
  await f.adapter.cancel(prepared.intentId);
  assert.deepEqual(f.local.state(), before);
  assert.equal((await f.store.read(first.key)).record.handle.transactionId, 'transaction-a');
  assert.equal((await f.adapter.getSaveGate()).allowed, false);
  assert.equal(f.lookups.length + f.local.calls.apply + f.local.calls.undo + f.local.calls.save, 0);
});

test('checkpoint snapshot advances with installed candidate while operation-start document binding stays immutable', async t => {
  const f = await fixture(t);
  const first = await f.adapter.persistOperation(operation());
  f.local.edit('x', 99);
  const latest = f.local.state();
  await f.adapter.persistOperation(operation({ transactionId: 'transaction-a', phase: 'ack-lost', state: 'unknown', response: { status: 'installed' } }));
  const record = (await f.store.read(first.key)).record;
  assert.equal(record.document.draftRevision, 'draft-0');
  assert.equal(record.payload.snapshot.document.draftRevision, 'draft-1');
  assert.deepEqual(record.payload.snapshot.editorFrame, latest.editorFrame);
  assert.equal(record.payload.phaseLog.length, 2);
  await assert.rejects(f.adapter.persistOperation(operation({ transactionId: 'transaction-a', phase: 'retry-ack' })), { code: 'facility_operation_unresolved' });
  await assert.rejects(f.adapter.persistOperation(operation({ requestId: 'request-b' })), { code: 'facility_operation_blocked' });
});

test('restart after lost acknowledgment requires explicit restoration plus verified owner and transaction resolution before Save', async t => {
  const f = await fixture(t);
  const first = await f.adapter.persistOperation(operation());
  f.local.edit('x', 77);
  f.local.change(s => { s.pendingOperations = [operation({ transactionId: 'transaction-a', state: 'unknown', phase: 'ack-lost' })]; });
  await f.adapter.persistOperation(operation({ transactionId: 'transaction-a', phase: 'ack-lost', state: 'unknown' }));
  const retained = (await f.store.read(first.key)).record.payload.snapshot;
  const fresh = editorDouble('renderer-2');
  const reopenedStore = await createRecoveryStore({ directory: f.recoveryDirectory, identity });
  const resumed = await createFacilityRecoveryAdapter({ ...f.options, editor: fresh.editor, recoveryStore: reopenedStore });
  await assert.rejects(resumed.assertSaveAllowed(), { code: 'facility_save_blocked' });
  const checkpoint = (await resumed.listRecovery())[0];
  assert.equal(checkpoint.needsRestore, true);
  await resumed.recover({ key: checkpoint.key, expectedCheckpointId: checkpoint.checkpointId,
    expectedRendererGeneration: 'renderer-2', expectedStateSequence: 0 });
  assert.deepEqual(fresh.state().editorFrame, retained.editorFrame);
  assert.equal((await resumed.getSaveGate()).allowed, false);
  f.resolved('apply', { owner: { ...owner, ownerId: 'someone-else' } });
  await assert.rejects(resumed.clearOperation({ requestId: 'request-a' }), { code: 'facility_reconciliation_owner_mismatch' });
  assert.equal((await reopenedStore.read(checkpoint.key)).record.handle.state, 'unknown');
  f.resolved('apply', { transactionId: 'wrong-transaction' });
  await assert.rejects(resumed.clearOperation({ requestId: 'request-a' }), { code: 'facility_reconciliation_transaction_mismatch' });
  f.resolved();
  assert.equal((await resumed.clearOperation({ requestId: 'request-a' })).status, 'reconciled');
  assert.equal((await resumed.getSaveGate()).allowed, true);
  assert.equal((await reopenedStore.read(checkpoint.key)).record.handle.state, 'reconciled');
  assert.equal(fresh.calls.adopt, 1); assert.equal(fresh.calls.save + fresh.calls.apply + fresh.calls.undo, 0);
});

test('unknown read-only lookup cannot clear its durable handle or authorize Save', async t => {
  const f = await fixture(t);
  const ack = await f.adapter.persistOperation(operation({ transactionId: 'transaction-a' }));
  await assert.rejects(f.adapter.clearOperation({ requestId: 'request-a' }), { code: 'facility_transaction_unresolved' });
  assert.equal((await f.store.read(ack.key)).record.handle.state, 'pending');
  assert.equal(f.local.calls.adopt, 0); assert.equal((await f.adapter.getSaveGate()).allowed, false);
});

test('changed frontend sequence during lookup prevents stale adoption and leaves journal unresolved', async t => {
  const pending = deferred(); const entered = deferred();
  const f = await fixture(t, { lookupOperation: () => { entered.resolve(); return pending.promise; } });
  const ack = await f.adapter.persistOperation(operation({ transactionId: 'transaction-a' }));
  const clearing = f.adapter.clearOperation({ requestId: 'request-a' });
  await entered.promise;
  f.local.change(s => { s.camera.x++; });
  pending.resolve({ identity, document, owner, requestId: 'request-a', transactionId: 'transaction-a', kind: 'apply', status: 'resolved', outcome: 'applied' });
  await assert.rejects(clearing, { code: 'facility_state_changed' });
  assert.equal((await f.store.read(ack.key)).record.handle.state, 'pending');
  assert.equal(f.local.calls.adopt, 0);
});

test('lookup timeout observes late completion without adopting or clearing unknown work', async t => {
  const pending = deferred(); let signal;
  const f = await fixture(t, { lookupTimeoutMs: 10, lookupOperation: (_request, control) => { signal = control.signal; return pending.promise; } });
  const ack = await f.adapter.persistOperation(operation({ state: 'unknown' }));
  await assert.rejects(f.adapter.clearOperation({ requestId: 'request-a' }), { code: 'facility_lookup_timeout' });
  assert.equal(signal.aborted, true);
  pending.reject(new Error('Late backend rejection'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal((await f.store.read(ack.key)).record.handle.state, 'unknown'); assert.equal(f.local.calls.adopt, 0);
});

test('lost durable journal acknowledgment survives restart; no second key replaces the handle', async t => {
  const f = await fixture(t); const local = editorDouble('renderer-lost');
  const store = { ...f.store, write: async request => { await f.store.write(request); throw new Error('Injected lost durability acknowledgment'); } };
  const a = await createFacilityRecoveryAdapter({ ...f.options, editor: local.editor, recoveryStore: store });
  await assert.rejects(a.persistOperation(operation({ transactionId: 'transaction-a', state: 'unknown' })), /lost durability acknowledgment/);
  const retained = await f.store.list(); assert.equal(retained.length, 1);
  const restarted = await createFacilityRecoveryAdapter({ ...f.options, editor: editorDouble('renderer-new').editor });
  assert.equal((await restarted.listRecovery())[0].key, retained[0].key);
  assert.equal((await restarted.getSaveGate()).allowed, false);
  assert.equal(local.calls.apply + local.calls.undo + local.calls.save, 0);
});

test('checkpoint CAS conflict preserves a newer durable record and never adopts the stale result', async t => {
  const f = await fixture(t);
  const ack = await f.adapter.persistOperation(operation({ transactionId: 'transaction-a' }));
  await assert.rejects(f.adapter.clearOperation({ requestId: 'request-a', expectedCheckpointId: 'stale-checkpoint' }), { code: 'facility_checkpoint_conflict' });
  assert.equal((await f.store.read(ack.key)).checkpointId, ack.checkpointId); assert.equal(f.lookups.length, 0);
});

test('different owner cannot adopt same-document recovery records after restart', async t => {
  const f = await fixture(t); await f.adapter.persistOperation(operation());
  await assert.rejects(createFacilityRecoveryAdapter({ ...f.options, owner: { ...owner, sessionId: 'foreign-session' } }), { code: 'facility_recovery_owner_mismatch' });
  assert.equal((await f.store.list()).length, 1);
});

test('dirty recovery replacement and stale generation/sequence are rejected before renderer side effects', async t => {
  const f = await fixture(t); const ack = await f.adapter.persistOperation(operation());
  const fresh = editorDouble('renderer-next'); fresh.edit('x', 3);
  const a = await createFacilityRecoveryAdapter({ ...f.options, editor: fresh.editor });
  const request = { key: ack.key, expectedCheckpointId: ack.checkpointId, expectedRendererGeneration: 'renderer-next', expectedStateSequence: 1 };
  await assert.rejects(a.recover({ ...request, expectedRendererGeneration: 'renderer-old' }), { code: 'facility_state_changed' });
  await assert.rejects(a.recover(request), { code: 'facility_restore_would_replace_draft' });
  assert.equal(fresh.calls.restore, 0);
});

test('failed local adoption after durable backend reconciliation still blocks Save until explicit adoption succeeds', async t => {
  const f = await fixture(t); f.resolved();
  const original = f.local.editor.acceptReconciliation;
  f.local.editor.acceptReconciliation = () => { throw new Error('Renderer adoption failed'); };
  const ack = await f.adapter.persistOperation(operation({ transactionId: 'transaction-a' }));
  await assert.rejects(f.adapter.clearOperation({ requestId: 'request-a' }), /Renderer adoption failed/);
  assert.equal((await f.store.read(ack.key)).record.handle.state, 'reconciled');
  assert.equal((await f.adapter.getSaveGate()).allowed, false);
  f.local.editor.acceptReconciliation = original;
  await f.adapter.clearOperation({ requestId: 'request-a' });
  assert.equal((await f.adapter.getSaveGate()).allowed, true);
});

test('cooperative late prepare cannot freeze after Close Cancel completes', async t => {
  const pending = deferred(); const f = await fixture(t);
  const freeze = f.local.editor.freeze;
  f.local.editor.freeze = async (request, control) => { await pending.promise; control.assertCurrent(); freeze(request, control); };
  const preparing = f.adapter.prepare('close');
  await new Promise(resolve => setImmediate(resolve));
  const active = f.adapter.getLifecycleState();
  assert.equal((await f.adapter.cancel(active.intentId)).status, 'cancelled');
  pending.resolve(); await preparing;
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.local.frozen, null); assert.equal(f.local.calls.freeze, 0);
  assert.equal((await f.adapter.getSaveGate()).allowed, true);
});

test('Cancel during initial snapshot does not unfreeze an intent never dispatched to the renderer', async t => {
  const f = await fixture(t); const initial = deferred(); const entered = deferred();
  const realSnapshot = f.local.editor.snapshot;
  let first = true;
  f.local.editor.snapshot = () => { if (first) { first = false; entered.resolve(); return initial.promise; } return realSnapshot(); };
  f.local.editor.unfreeze = () => { throw new Error('No renderer intent owns a freeze'); };
  const preparing = f.adapter.prepare('close'); await entered.promise;
  const cancelled = await f.adapter.cancel(f.adapter.getLifecycleState().intentId);
  assert.equal(cancelled.status, 'cancelled');
  initial.resolve(realSnapshot()); await preparing;
  assert.equal(f.local.calls.freeze, 0);
  assert.equal((await f.adapter.getSaveGate()).allowed, true);
});

test('prepare timeout never authorizes close and Cancel releases only its owned freeze', async t => {
  const f = await fixture(t, { timeoutMs: 10 }); const never = deferred();
  f.local.editor.freeze = (_request, _control) => never.promise;
  const prepared = await f.adapter.prepare('close');
  assert.equal(prepared.status, 'blocked'); assert.ok(prepared.blockers.includes('lifecycle_timeout'));
  assert.equal((await f.adapter.commit(prepared)).status, 'blocked');
  assert.equal(f.commits.length, 0);
  await f.adapter.cancel(prepared.intentId); never.resolve();
  assert.equal((await f.adapter.getSaveGate()).allowed, true);
});

test('prior Close Cancel and adopted Apply/Undo checkpoints cannot permanently block later lost-ack recovery', async t => {
  const f = await fixture(t); f.local.edit('x', 10); f.local.edit('y', 15);
  const manual = f.local.state(); const close = await f.adapter.prepare('close');
  await f.adapter.cancel(close.intentId); assert.equal((await f.store.list()).length, 0);
  await f.adapter.persistOperation(operation());
  f.local.edit('x', 70);
  await f.adapter.persistOperation(operation({ transactionId: 'transaction-a', phase: 'apply-acknowledged' }));
  f.resolved(); await f.adapter.clearOperation({ requestId: 'request-a' });
  const applyRecord = (await f.adapter.listRecovery())[0];
  assert.equal(applyRecord.adopted, true);
  await f.adapter.persistOperation(operation({ requestId: 'request-b', transactionId: 'transaction-a', kind: 'undo' }));
  f.local.change(state => { state.editorFrame = clone(manual.editorFrame); state.document = clone(manual.document); });
  await f.adapter.persistOperation(operation({ requestId: 'request-b', transactionId: 'transaction-a', kind: 'undo', phase: 'undo-acknowledged' }));
  f.resolved('undo', { requestId: 'request-b' }); await f.adapter.clearOperation({ requestId: 'request-b' });
  await f.adapter.persistOperation(operation({ requestId: 'request-c' }));
  f.local.edit('y', 88);
  const pending = operation({ requestId: 'request-c', transactionId: 'transaction-c', phase: 'installation-ack-lost', state: 'unknown' });
  f.local.change(state => { state.pendingOperations = [pending]; });
  await f.adapter.persistOperation(pending);
  const fresh = editorDouble('renderer-restarted');
  const resumed = await createFacilityRecoveryAdapter({ ...f.options, editor: fresh.editor });
  const all = await resumed.listRecovery();
  assert.equal(all.length, 3);
  assert.equal(all.filter(item => item.supersededBy).length, 2);
  assert.equal(all.filter(item => item.needsRestore).length, 1);
  const active = all.find(item => !item.supersededBy);
  assert.equal(active.handle.requestId, 'request-c');
  await resumed.recover({ key: active.key, expectedCheckpointId: active.checkpointId,
    expectedRendererGeneration: 'renderer-restarted', expectedStateSequence: 0 });
  f.resolved('apply', { requestId: 'request-c', transactionId: 'transaction-c' });
  await resumed.clearOperation({ requestId: 'request-c' });
  assert.equal((await resumed.getSaveGate()).allowed, true);
  assert.equal((await f.store.list()).length, 3, 'historical reconciled handles remain retained');
  assert.equal(fresh.calls.save + fresh.calls.apply + fresh.calls.undo, 0);
});

test('phase journal retains hashes instead of repeating large response payloads', async t => {
  const f = await fixture(t); const response = { fullFrame: 'x'.repeat(600000) };
  let receipt;
  for (let index = 0; index < 6; index++) receipt = await f.adapter.persistOperation(operation({ phase: 'phase-' + index, response }));
  const record = (await f.store.read(receipt.key)).record;
  assert.equal(record.payload.phaseLog.length, 6);
  assert.ok(record.payload.phaseLog.every(item => !('response' in item) && /^[a-f0-9]{64}$/.test(item.diagnosticSha256)));
  assert.equal(record.payload.operation.response.fullFrame.length, 600000);
  assert.ok(JSON.stringify(record).length < 610000);
});
