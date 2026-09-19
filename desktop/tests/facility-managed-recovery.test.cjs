'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { createFacilityRecoveryAdapter } = require('../src/facility-recovery-adapter.cjs');
const { createFacilityManagedRecovery } = require('../src/facility-managed-recovery.cjs');
const clone = value => JSON.parse(JSON.stringify(value));
const runtime = { identity: { backendId: 'backend-stable', storeId: 'isolated-store', principalId: 'principal-stable' },
  document: { tenantId: 'tenant-test', siteId: 'site-test', documentId: 'manual-copy' },
  owner: { sessionId: 'session-stable', ownerId: 'writer-stable' }, origin: 'http://127.0.0.1:48761', instanceId: 'process-old' };
function deferred() { let resolve; const promise = new Promise(a => { resolve = a; }); return { promise, resolve }; }
function reconciledFrame(before, kind) {
  const expected = clone(before.editorFrame);
  if (kind === 'apply') expected.activeProposal = { ...expected.activeProposal, status: 'active', transactionRevision: 'transaction-r2' };
  else if (kind === 'undo') expected.activeProposal = null;
  return expected;
}

async function fixture(t, kind = 'apply', extra = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'facility-managed-recovery-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const saved = path.join(directory, 'saved-layout.json');
  const savedBytes = Buffer.from('{"placements":[{"id":"machine-a","x":0}]}');
  await fs.writeFile(saved, savedBytes);
  const effects = [];
  let frozen = null;
  let state = { schemaVersion: 1, rendererGeneration: 'renderer-stable', stateSequence: 2,
    document: { documentId: runtime.document.documentId, baseRevision: 'saved-r1', draftRevision: 'draft-r3' },
    editorFrame: { schemaVersion: 1, baseLayout: { placements: [{ id: 'machine-a', x: 0, y: 0 }] }, baseRevision: 'saved-r1',
      draftLayout: { placements: [{ id: 'machine-a', x: 18, y: 42 }] }, draftRevision: 'draft-r3',
      selectedIds: ['machine-a'], batches: [{ label: 'Move X', operations: [{ x: 18 }] }, { label: 'Move Y', operations: [{ y: 42 }] }],
      cursor: 2, redo: [{ label: 'Future command' }], recentReceiptIds: ['receipt-1'], generatedDraft: null,
      editorGenerationId: 'editor-generation-stable', commandJournalHash: 'journal-stable',
      activeProposal: kind ? { proposalId: 'proposal-stable', proposalRevision: 'proposal-r1', transactionId: 'transaction-' + kind,
        transactionRevision: 'transaction-r1', transactionBindingRevision: 'binding-r1',
        status: kind === 'apply' ? 'installation_pending' : 'undo_acknowledgment_pending' } : null },
    pendingOperations: [], activeJobs: [], busy: false, dirty: true, conflict: null, startupRecoveryPending: false };
  const pending = { kind, requestId: 'request-' + kind, transactionId: 'transaction-' + kind,
    phase: kind + '-acknowledge-pending', state: 'pending' };
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
      assert.ok(frozen === null || frozen === request.intentId);
      frozen = request.intentId; effects.push('freeze');
      return clone(state);
    },
    unfreeze(request, control) {
      control.assertCurrent(); assert.equal(request.intentId, frozen);
      frozen = null; effects.push('unfreeze'); return clone(state);
    },
    setStartupRecoveryGate(request, control) {
      if (control) control.assertCurrent();
      check(request);
      if (!request.blocked && state.pendingOperations.length) throw Object.assign(new Error('Pending transaction'), { code: 'pending' });
      state.startupRecoveryPending = request.blocked; state.stateSequence++;
      effects.push('gate:' + request.blocked); return clone(state);
    },
    restoreRecovery() { throw new Error('Managed restart must not replace the editor frame'); },
    acceptReconciliation(request) {
      check(request); assert.equal(request.requestId, pending.requestId);
      assert.ok(frozen); assert.equal(state.busy, false);
      effects.push('adopt:' + request.resolution);
      if (request.resolution === 'applied') state.editorFrame.activeProposal = { ...state.editorFrame.activeProposal,
        status: 'active', transactionRevision: request.transactionRevision };
      else if (request.resolution === 'undone') state.editorFrame.activeProposal = null;
      state.pendingOperations = []; state.stateSequence++;
      return clone(state);
    },
  };
  let lookupError;
  let lookupDeferred;
  const lookupReached = deferred();
  const adapter = await createFacilityRecoveryAdapter({ authorizedIsolatedHarness: true,
    ...runtime, editor, recoveryDirectory: path.join(directory, 'journal'),
    commitLifecycle() { throw new Error('A managed restart must not commit window Close'); },
    async lookupOperation(request, control) {
      effects.push('lookup:' + request.kind);
      lookupReached.resolve();
      if (lookupDeferred) await lookupDeferred.promise;
      control.signal.throwIfAborted();
      if (lookupError) throw Object.assign(new Error(lookupError), { code: lookupError });
      return { identity: runtime.identity, document: runtime.document, owner: runtime.owner,
        requestId: request.requestId, transactionId: request.transactionId, kind: request.kind,
        status: 'resolved', outcome: request.kind === 'apply' ? 'applied' : 'undone', transactionRevision: 'transaction-r2' };
    },
  });
  if (kind) {
    state.pendingOperations = [clone(pending)]; state.busy = true; state.stateSequence++;
    await adapter.persistOperation({ ...pending, snapshot: clone(state) });
  }
  const before = clone(state);
  let currentRuntime = { ...clone(runtime), instanceId: 'process-new' };
  let restartResult = { status: 'ready', beforeRuntime: clone(runtime) };
  const callbacks = {};
  const coordinator = createFacilityManagedRecovery({ authorizedIsolatedHarness: true, adapter, editor, expectedRuntime: runtime,
    async quiescePending(control) {
      callbacks.quiesce = control;
      control.assertCurrent(); assert.ok(frozen); assert.equal(state.startupRecoveryPending, true);
      effects.push('quiesce');
      if (kind) {
        state.busy = false; state.pendingOperations[0].state = 'unknown';
        state.pendingOperations[0].phase = kind + '-acknowledge-unknown'; state.stateSequence++;
        await adapter.persistOperation({ ...state.pendingOperations[0], snapshot: clone(state) });
      }
    },
    async restartBackend(control) {
      callbacks.restart = control;
      control.assertCurrent(); assert.ok(frozen); assert.equal(state.startupRecoveryPending, true);
      effects.push('restart'); return clone(restartResult);
    },
    async readRuntime(control) { callbacks.read = control; control.assertCurrent(); effects.push('runtime'); return clone(currentRuntime); },
    ...extra,
  });
  return { coordinator, editor, adapter, directory, effects, callbacks, before, pending, lookupReached,
    get frozen() { return frozen; }, state: () => clone(state),
    change(fn) { fn(state); state.stateSequence++; },
    setRuntime(value) { currentRuntime = clone(value); }, setRestart(value) { restartResult = clone(value); },
    failLookup(code) { lookupError = code; }, holdLookup() { return lookupDeferred = deferred(); },
    async savedUnchanged() { assert.deepEqual(await fs.readFile(saved), savedBytes); },
  };
}

test('managed recovery requires explicit isolated-harness authority', () => {
  assert.throws(() => createFacilityManagedRecovery(), { code: 'facility_harness_not_authorized' });
});

for (const kind of ['apply', 'undo']) test(`restart pending ${kind} performs durable lookup once and preserves exact frame before releasing Save`, async t => {
  const f = await fixture(t, kind);
  const barrier = f.holdLookup();
  const run = f.coordinator.restart();
  await Promise.race([f.lookupReached.promise, run.then(result => { throw new Error(JSON.stringify(result)); })]);
  assert.equal(f.coordinator.getState().status, 'reconciling');
  assert.equal((await f.coordinator.getSaveGate()).allowed, false);
  assert.ok(f.frozen); assert.equal(f.state().startupRecoveryPending, true);
  const duplicate = f.coordinator.restart(); assert.equal(duplicate, run);
  barrier.resolve();
  const result = await run;
  assert.equal(result.status, 'reconciled'); assert.equal(result.exactDraftSelectionHistoryRetained, true);
  assert.equal(result.verifiedProposalMetadataAdopted, true);
  assert.deepEqual(f.state().editorFrame, reconciledFrame(f.before, kind));
  assert.equal(f.state().rendererGeneration, f.before.rendererGeneration);
  assert.deepEqual(result.beforeRuntime, runtime);
  assert.deepEqual(result.afterRuntime, { ...runtime, instanceId: 'process-new' });
  assert.ok(f.effects.indexOf('restart') < f.effects.indexOf('runtime'));
  assert.ok(f.effects.indexOf('runtime') < f.effects.indexOf('lookup:' + kind));
  assert.ok(f.effects.indexOf('lookup:' + kind) < f.effects.indexOf('adopt:' + (kind === 'apply' ? 'applied' : 'undone')));
  assert.equal(f.effects.filter(item => item === 'restart').length, 1);
  assert.equal(f.effects.filter(item => item === 'lookup:' + kind).length, 1);
  assert.equal(f.frozen, null); assert.equal((await f.coordinator.getSaveGate()).allowed, true);
  assert.equal(f.state().pendingOperations.length, 0);
  await f.savedUnchanged();
  assert.throws(() => f.callbacks.restart.runIfCurrent(() => { throw new Error('Should never run'); }), { code: 'facility_managed_callback_settled' });
});

for (const kind of ['apply', 'undo']) for (const code of ['lease_expired', 'ownership_conflict']) {
  test(`${kind} with ${code} retains frame and durable handle for explicit recovery without retry`, async t => {
    const f = await fixture(t, kind); f.failLookup(code);
    const result = await f.coordinator.restart();
    assert.equal(result.status, 'requires-recovery'); assert.equal(result.code, code);
    assert.equal(result.explicitRecoveryRequired, true);
    assert.deepEqual(f.state().editorFrame, f.before.editorFrame);
    assert.equal(f.state().pendingOperations[0].requestId, f.pending.requestId);
    assert.equal(f.state().pendingOperations[0].transactionId, f.pending.transactionId);
    assert.equal(f.state().pendingOperations[0].state, 'unknown');
    assert.ok(f.frozen); assert.equal(f.state().startupRecoveryPending, true);
    await assert.rejects(f.coordinator.assertSaveAllowed(), { code: 'facility_save_blocked' });
    assert.deepEqual(await f.coordinator.restart(), result);
    assert.equal(f.effects.filter(item => item === 'lookup:' + kind).length, 1);
    assert.equal(f.effects.some(item => item.startsWith('adopt:')), false);
    const entries = await f.adapter.listRecovery();
    assert.equal(entries.length, 1); assert.equal(entries[0].handle.state, 'unknown');
    await f.savedUnchanged();
  });
}

for (const kind of ['apply', 'undo']) for (const status of ['failed', 'identity-mismatch']) {
  test(`${kind} ${status} restart never authenticates or reconciles against the unverified runtime`, async t => {
    const f = await fixture(t, kind); f.setRestart({ status, beforeRuntime: runtime });
    const result = await f.coordinator.restart();
    assert.equal(result.status, 'requires-recovery');
    assert.equal(result.code, status === 'failed' ? 'facility_managed_restart_failed' : 'facility_managed_identity_mismatch');
    assert.equal(f.effects.includes('runtime'), false);
    assert.equal(f.effects.some(item => item.startsWith('lookup:') || item.startsWith('adopt:')), false);
    assert.deepEqual(f.state().editorFrame, f.before.editorFrame);
    assert.ok(f.frozen); assert.equal(f.state().startupRecoveryPending, true);
    assert.equal((await f.coordinator.getSaveGate()).allowed, false);
    await f.savedUnchanged();
  });
}

for (const field of ['backendId', 'storeId', 'principalId', 'sessionId', 'ownerId', 'documentId', 'origin', 'instanceId']) {
  test(`changed ${field} cannot grant write authority or trigger durable transaction lookup`, async t => {
    const f = await fixture(t);
    const changed = { ...clone(runtime), instanceId: 'process-new' };
    if (field in changed.identity) changed.identity[field] += '-foreign';
    else if (field in changed.owner) changed.owner[field] += '-foreign';
    else if (field in changed.document) changed.document[field] += '-foreign';
    else changed[field] = field === 'origin' ? 'http://127.0.0.1:48762' : runtime.instanceId;
    f.setRuntime(changed);
    const result = await f.coordinator.restart();
    assert.equal(result.status, 'requires-recovery');
    assert.equal(result.code, field === 'instanceId' ? 'facility_managed_process_instance_mismatch' : 'facility_managed_identity_mismatch');
    assert.deepEqual(f.state().editorFrame, f.before.editorFrame);
    assert.equal(f.effects.some(item => item.startsWith('lookup:')), false);
    assert.equal((await f.coordinator.getSaveGate()).allowed, false);
    await f.savedUnchanged();
  });
}

test('Cancel before restart preserves pending identity and Undo history without dispatch or lookup', async t => {
  const f = await fixture(t, 'undo');
  assert.equal((await f.coordinator.prepare()).status, 'prepared');
  assert.equal((await f.coordinator.cancel()).status, 'cancelled');
  assert.equal(f.frozen, null);
  assert.deepEqual(f.state().editorFrame, f.before.editorFrame);
  assert.deepEqual(f.state().pendingOperations, f.before.pendingOperations);
  assert.equal((await f.coordinator.getSaveGate()).allowed, false);
  assert.equal((await f.coordinator.restart()).status, 'cancelled');
  assert.equal(f.effects.some(item => item === 'restart' || item.startsWith('lookup:')), false);
  await f.savedUnchanged();
});

test('Cancel invalidates a delayed cooperating gate before its late side effect', async t => {
  const f = await fixture(t, null);
  const waiting = deferred(); const reached = deferred(); const original = f.editor.setStartupRecoveryGate;
  let lateEffect = false;
  f.editor.setStartupRecoveryGate = async (request, control) => {
    if (request.blocked) {
      reached.resolve(); await waiting.promise;
      control.runIfCurrent(() => { lateEffect = true; });
    }
    return original(request, control);
  };
  const preparing = f.coordinator.prepare(); await reached.promise;
  assert.equal((await f.coordinator.cancel()).status, 'cancelled');
  waiting.resolve(); await preparing; await new Promise(resolve => setImmediate(resolve));
  assert.equal(lateEffect, false); assert.equal(f.frozen, null);
  assert.equal(f.state().startupRecoveryPending, false);
  assert.deepEqual(f.state().editorFrame, f.before.editorFrame);
  assert.equal(f.effects.includes('restart'), false);
});

test('Cancel is rejected after restart dispatch while the owned supervisor completes', async t => {
  const started = deferred(); const finish = deferred();
  const f = await fixture(t, 'apply', { async restartBackend(control) {
    control.assertCurrent(); started.resolve(); await finish.promise; control.assertCurrent();
    return { status: 'failed', beforeRuntime: runtime };
  } });
  const restarting = f.coordinator.restart(); await started.promise;
  await assert.rejects(f.coordinator.cancel(), { code: 'facility_managed_restart_in_progress' });
  assert.equal((await f.coordinator.getSaveGate()).allowed, false);
  finish.resolve(); assert.equal((await restarting).status, 'requires-recovery');
  assert.deepEqual(f.state().editorFrame, f.before.editorFrame);
});

test('missing durable pending checkpoint blocks restart before a process is stopped', async t => {
  const f = await fixture(t);
  f.change(state => { state.pendingOperations[0].requestId = 'unpersisted-request'; });
  const result = await f.coordinator.restart();
  assert.equal(result.status, 'requires-recovery'); assert.equal(result.code, 'facility_managed_durable_handle_missing');
  assert.equal(f.effects.includes('restart'), false);
  assert.equal((await f.coordinator.getSaveGate()).allowed, false);
});

test('a pre-existing Close intent is neither adopted nor cancelled by managed restart', async t => {
  const f = await fixture(t);
  const close = await f.adapter.prepare('close');
  const result = await f.coordinator.restart();
  assert.equal(result.code, 'facility_managed_lifecycle_owned');
  await f.coordinator.cancel();
  assert.equal(f.adapter.getLifecycleState().intentId, close.intentId);
  assert.equal(f.frozen, close.intentId);
  assert.equal(f.effects.includes('restart'), false);
});

test('a failed freeze acknowledgement cannot permit backend restart', async t => {
  const f = await fixture(t);
  f.editor.freeze = () => { throw new Error('Renderer freeze failed'); };
  const result = await f.coordinator.restart();
  assert.equal(result.status, 'requires-recovery'); assert.equal(result.code, 'facility_managed_freeze_failed');
  assert.equal(f.effects.includes('restart'), false);
  assert.equal(f.state().startupRecoveryPending, true);
  assert.deepEqual(f.state().editorFrame, f.before.editorFrame);
});

test('idle restart still preserves a dirty manual frame and performs no transaction lookup', async t => {
  const f = await fixture(t, null);
  const result = await f.coordinator.restart();
  assert.equal(result.status, 'reconciled');
  assert.deepEqual(f.state().editorFrame, f.before.editorFrame);
  assert.equal(f.effects.some(item => item.startsWith('lookup:')), false);
  assert.equal(f.frozen, null);
  await f.savedUnchanged();
});

test('unexpected frame mutation is retained visibly and cannot be hidden by automatic restoration', async t => {
  let f;
  f = await fixture(t, 'apply', { async quiescePending(control) {
    control.assertCurrent(); f.change(state => { state.editorFrame.selectedIds = []; });
  } });
  const result = await f.coordinator.restart();
  assert.equal(result.status, 'requires-recovery'); assert.equal(result.code, 'facility_managed_editor_frame_changed');
  assert.equal(f.effects.includes('restart'), false);
  assert.equal((await f.coordinator.getSaveGate()).allowed, false);
});

for (const field of ['draftLayout', 'baseLayout', 'selectedIds', 'batches', 'cursor', 'editorGenerationId',
  'recentReceiptIds', 'commandJournalHash', 'proposalId', 'transactionRevision', 'status']) {
  test(`verified Apply metadata adoption cannot conceal an unexpected ${field} change`, async t => {
    const f = await fixture(t, 'apply');
    const accept = f.editor.acceptReconciliation;
    f.editor.acceptReconciliation = request => {
      accept(request);
      f.change(state => {
        const frame = state.editorFrame;
        if (field === 'draftLayout' || field === 'baseLayout') frame[field].placements[0].x += 1;
        else if (['selectedIds', 'recentReceiptIds'].includes(field)) frame[field] = ['foreign-id'];
        else if (field === 'batches') frame.batches[0].operations[0].x += 1;
        else if (field === 'cursor') frame.cursor = 1;
        else if (field in frame.activeProposal) frame.activeProposal[field] = 'foreign-value';
        else frame[field] = 'foreign-value';
      });
      return f.state();
    };
    const result = await f.coordinator.restart();
    assert.equal(result.status, 'requires-recovery'); assert.equal(result.code, 'facility_managed_editor_frame_changed');
    assert.ok(f.frozen); assert.equal(f.state().startupRecoveryPending, true);
    assert.equal((await f.coordinator.getSaveGate()).allowed, false);
    assert.equal(f.effects.filter(item => item === 'lookup:apply').length, 1);
    await f.savedUnchanged();
  });
}

test('Undo adoption permits clearing active proposal metadata without allowing any draft or history change', async t => {
  const f = await fixture(t, 'undo');
  const accept = f.editor.acceptReconciliation;
  f.editor.acceptReconciliation = request => {
    accept(request);
    f.change(state => { state.editorFrame.batches.pop(); state.editorFrame.cursor--; });
    return f.state();
  };
  const result = await f.coordinator.restart();
  assert.equal(result.status, 'requires-recovery'); assert.equal(result.code, 'facility_managed_editor_frame_changed');
  assert.equal(f.state().editorFrame.activeProposal, null);
  assert.ok(f.frozen); assert.equal(f.state().startupRecoveryPending, true);
  await f.savedUnchanged();
});
