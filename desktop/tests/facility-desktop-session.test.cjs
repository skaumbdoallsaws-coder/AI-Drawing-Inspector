'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const Session = require('../../static/facility_layout_session.js');
const Desktop = require('../../static/facility_layout_desktop_adapter.js');
const App = require('../../static/facility_layout_app.js');
const root = path.resolve(__dirname, '../..');
const clone = value => JSON.parse(JSON.stringify(value));
const canonical = value => Array.isArray(value) ? value.map(canonical)
  : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;
const hash = value => crypto.createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex');
const base = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/facility_layout/empty_cell.json'), 'utf8'));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const expected = adapter => { const s = adapter.snapshot(); return { expectedRendererGeneration: s.rendererGeneration, expectedStateSequence: s.stateSequence }; };
const freeze = (adapter, intentId = 'close-a') => { const s = adapter.snapshot(); return adapter.freeze({ intentId, rendererGeneration: s.rendererGeneration, stateSequence: s.stateSequence }); };

// Mocked transaction envelopes test client protocol behavior. The first test
// separately exercises real editor mutations through the real Python kernel.
function fixture(options = {}) {
  const calls = { prepare: 0, commit: 0, applyAck: 0, undoPrepare: 0, undoAck: 0, recover: 0, save: 0 };
  const records = [], cleared = [];
  let rootFrame;
  const config = {
    previewOperations: async () => ({ layout: clone(base), revision: hash(base), changed: false }),
    applyOperations: async () => { calls.save++; throw new Error('Save forbidden in fixture'); },
    prepareDesignProposalApply: async request => {
      calls.prepare++; rootFrame = clone(request.rootUndoFrame);
      const candidateLayout = clone(rootFrame.draftLayout);
      const zone = { zoneId: 'zn-candidate', label: 'Prepared candidate', zoneType: 'workcell',
        boundary: [{ x: 0, z: 0 }, { x: 4, z: 0 }, { x: 4, z: 4 }, { x: 0, z: 4 }], floorElevation: 0, anchors: [], evidence: [] };
      candidateLayout.zones.push(zone);
      const resultLayoutRevision = hash(candidateLayout), transactionBindingRevision = 'binding-1';
      return { transaction: { transaction: { transactionId: 'tx-1', proposalBinding: { resultLayoutRevision } }, transactionRevision: 'prepared-1' },
        transactionBindingRevision, candidateLayout, candidateOperations: [{ op: 'add_zone', zone: clone(zone) }],
        expectedInstallationFingerprint: hash({ commandJournalHash: request.expectedResultCommandJournalHash, draftRevision: resultLayoutRevision,
          editorGenerationId: request.expectedResultEditorGenerationId, proposalId: request.proposalId, proposalRevision: request.proposalRevision, transactionBindingRevision }),
        adoption: { adoptionToken: 'test-token' } };
    },
    commitDesignProposalApply: async () => { calls.commit++; return { transaction: { transaction: { transactionId: 'tx-1' }, transactionRevision: 'committed-1' } }; },
    acknowledgeDesignProposalApply: async () => {
      calls.applyAck++;
      if (options.loseApplyAck) throw new Error('Lost Apply acknowledgment');
      return { transaction: { transactionRevision: 'active-1' } };
    },
    recoverDesignProposalApply: async () => { calls.recover++; return {}; },
    prepareDesignUndo: async () => {
      calls.undoPrepare++;
      return { mode: 'coordinated', readiness: 'undo_acknowledgment_pending', rootUndoFrame: clone(rootFrame),
        transaction: { transaction: { transactionId: 'tx-1', proposalBinding: { proposalId: 'proposal-1', proposalRevision: 'revision-1' } }, transactionRevision: 'undo-pending-1' } };
    },
    acknowledgeDesignUndo: async () => {
      calls.undoAck++;
      if (options.loseUndoAck) throw new Error('Lost Undo acknowledgment');
      return { outcome: 'undone' };
    },
  };
  const session = Session.createSession(config);
  session.load({ layout: clone(base), revision: hash(base) });
  const adapter = Desktop.createAdapter({ session,
    startupRecoveryPending: options.startupRecoveryPending === true,
    persistOperation: async record => { records.push(clone(record)); if (options.persist) await options.persist(record); },
    clearOperation: async record => { cleared.push(clone(record)); if (options.clear) await options.clear(record, adapter); },
  });
  return { session, adapter, calls, records, cleared, config };
}
const apply = value => value.session.applyDesignProposal({ proposalId: 'proposal-1', proposalRevision: 'revision-1' });

test('explicit startup gate blocks actual session Save before any pending operation or restoration', async () => {
  const value = fixture({ startupRecoveryPending: true });
  const initial = value.adapter.snapshot();
  assert.equal(initial.startupRecoveryPending, true);
  assert.equal(initial.pendingOperations.length, 0);
  assert.equal(initial.recoveryOwned, false);
  assert.equal(value.session.getState().canSave, false);
  await assert.rejects(value.session.save(), { code: 'facility_desktop_recovery_unresolved' });
  assert.equal(value.calls.save, 0);
  assert.throws(() => value.adapter.setStartupRecoveryGate({ blocked: false,
    expectedRendererGeneration: 'stale-renderer', expectedStateSequence: initial.stateSequence }), { code: 'facility_desktop_stale_state' });
  assert.throws(() => value.adapter.setStartupRecoveryGate({ blocked: false,
    expectedRendererGeneration: initial.rendererGeneration, expectedStateSequence: initial.stateSequence + 1 }), { code: 'facility_desktop_stale_state' });
  assert.deepEqual(value.adapter.snapshot(), initial);
  value.adapter.setStartupRecoveryGate({ blocked: false, ...expected(value.adapter) });
  await apply(value);
  assert.equal(value.session.getState().canSave, true);
  assert.equal(value.calls.save, 0);
});

test('startup gate cannot release an unresolved restored owner; verified adoption alone does not release the native gate', async () => {
  const original = fixture({ loseApplyAck: true }); await assert.rejects(apply(original), /Lost Apply/);
  const value = fixture({ startupRecoveryPending: true });
  const snapshot = original.adapter.snapshot();
  value.adapter.restoreRecovery({ snapshot, ...expected(value.adapter) });
  assert.throws(() => value.adapter.setStartupRecoveryGate({ blocked: false, ...expected(value.adapter) }), { code: 'facility_desktop_recovery_unresolved' });
  value.adapter.acceptReconciliation({ ...snapshot.pendingOperations[0], resolution: 'applied',
    transactionRevision: 'active-verified', ...expected(value.adapter) });
  assert.equal(value.adapter.snapshot().pendingOperations.length, 0);
  assert.equal(value.adapter.snapshot().startupRecoveryPending, true);
  assert.equal(value.session.getState().canSave, false);
  await assert.rejects(value.session.save(), { code: 'facility_desktop_recovery_unresolved' });
  value.adapter.setStartupRecoveryGate({ blocked: false, ...expected(value.adapter) });
  assert.equal(value.session.getState().canSave, true);
  assert.equal(value.calls.save + value.calls.prepare + value.calls.commit + value.calls.applyAck, 0);
});

test('real session facade plus durable native adapter keeps restart Save blocked before restore and until verified reconciliation', async t => {
  const { createFacilityRecoveryAdapter } = require('../src/facility-recovery-adapter.cjs');
  const promises = require('node:fs/promises');
  const directory = await promises.mkdtemp(path.join(require('node:os').tmpdir(), 'facility-startup-gate-'));
  t.after(() => promises.rm(directory, { recursive: true, force: true }));
  const identity = { backendId: 'isolated-backend', storeId: 'isolated-store', principalId: 'test-principal' };
  const document = { tenantId: 'test-tenant', siteId: 'test-site', documentId: base.layoutId };
  const owner = { sessionId: 'test-session', ownerId: 'test-owner' };
  const options = { authorizedIsolatedHarness: true, identity, document, owner, recoveryDirectory: directory,
    lookupOperation: async request => ({ identity, document, owner, requestId: request.requestId,
      transactionId: request.transactionId, kind: request.kind, status: 'resolved', outcome: 'applied', transactionRevision: 'verified-active' }),
    commitLifecycle: async () => {} };
  let nativeFirst;
  const first = fixture({ loseApplyAck: true, startupRecoveryPending: true,
    persist: record => nativeFirst.persistOperation(record), clear: record => nativeFirst.clearOperation(record) });
  nativeFirst = await createFacilityRecoveryAdapter({ ...options, editor: first.adapter });
  assert.equal(first.adapter.snapshot().startupRecoveryPending, false, 'clean initial journal releases startup after inspection');
  await assert.rejects(apply(first), /Lost Apply/);
  let nativeNext;
  const next = fixture({ startupRecoveryPending: true,
    persist: record => nativeNext.persistOperation(record), clear: record => nativeNext.clearOperation(record) });
  nativeNext = await createFacilityRecoveryAdapter({ ...options, editor: next.adapter });
  const initial = next.adapter.snapshot();
  assert.equal(initial.pendingOperations.length, 0);
  assert.equal(initial.startupRecoveryPending, true);
  assert.equal(next.session.getState().canSave, false);
  await assert.rejects(next.session.save(), { code: 'facility_desktop_recovery_unresolved' });
  assert.equal(next.calls.save, 0);
  const record = (await nativeNext.listRecovery()).find(item => !item.supersededBy);
  await nativeNext.recover({ key: record.key, expectedCheckpointId: record.checkpointId, ...expected(next.adapter) });
  assert.equal((await nativeNext.getSaveGate()).allowed, false);
  await assert.rejects(next.session.save(), { code: 'facility_desktop_recovery_unresolved' });
  await nativeNext.clearOperation({ requestId: record.handle.requestId, transactionId: record.handle.transactionId });
  assert.equal(next.adapter.snapshot().startupRecoveryPending, false);
  assert.equal(next.session.getState().canSave, true);
  assert.equal((await nativeNext.getSaveGate()).allowed, true);
  assert.deepEqual(next.calls, { prepare: 0, commit: 0, applyAck: 0, undoPrepare: 0, undoAck: 0, recover: 0, save: 0 });
});

test('real kernel: two edits, Close/Cancel, retained selection, Undo/Redo and third edit never Save', async () => {
  const program = [
    'import json,sys',
    'from ai_inspector.facility_layout.canonical import layout_revision',
    'from ai_inspector.facility_layout.operations import apply_facility_layout_operations',
    'r=json.load(sys.stdin)',
    'v=apply_facility_layout_operations(r["layout"],r["operations"],base_revision=layout_revision(r["layout"]))',
    'print(json.dumps({"layout":v["document"],"revision":layout_revision(v["document"]),"changed":v["changed"]}))',
  ].join('\n');
  const kernel = (layout, operations) => JSON.parse(execFileSync(process.env.CONSTRUCTION_TEST_PYTHON || 'python', ['-c', program], {
    cwd: root, input: JSON.stringify({ layout, operations }), encoding: 'utf8', timeout: 20000,
  }));
  const initial = kernel(base, [{ op: 'add_zone', zone: { zoneId: 'zn-desktop-zone', label: 'Original', zoneType: 'workcell',
    boundary: [{ x: 0, z: 0 }, { x: 4, z: 0 }, { x: 4, z: 4 }, { x: 0, z: 4 }], floorElevation: 0, anchors: [], evidence: [] } }]);
  let saves = 0;
  const cache = new Map();
  const session = Session.createSession({ previewOperations: async request => {
    assert.equal(request.baseRevision, initial.revision);
    const key = JSON.stringify(request.operations);
    if (!cache.has(key)) cache.set(key, kernel(initial.layout, request.operations));
    return clone(cache.get(key));
  }, applyOperations: async () => { saves++; throw new Error('Save forbidden'); } });
  session.load(initial);
  const adapter = Desktop.createAdapter({ session, persistOperation: async () => {}, clearOperation: async () => {} });
  session.select('zn-desktop-zone');
  await session.editZoneLabel('zn-desktop-zone', 'Edit one');
  await session.editZoneLabel('zn-desktop-zone', 'Edit two');
  const before = adapter.snapshot();
  assert.equal(before.editorFrame.batches.length, 2);
  freeze(adapter);
  assert.throws(() => session.clearSelection(), e => e.code === 'facility_desktop_frozen');
  await assert.rejects(session.editZoneLabel('zn-desktop-zone', 'Forbidden'), e => e.code === 'facility_desktop_frozen');
  await assert.rejects(session.save(), e => e.code === 'facility_desktop_frozen');
  assert.throws(() => adapter.unfreeze({ intentId: 'wrong-close' }), e => e.code === 'facility_desktop_freeze_owned');
  adapter.unfreeze({ intentId: 'close-a' });
  assert.deepEqual(adapter.snapshot(), before);
  assert.throws(() => freeze(adapter), e => e.code === 'facility_desktop_stale_intent');
  assert.deepEqual(adapter.unfreeze({ intentId: 'close-a' }), before);
  await session.undo();
  assert.equal(session.getState().layout.zones[0].label, 'Edit one');
  assert.deepEqual(session.getState().selection, ['zn-desktop-zone']);
  await session.redo();
  assert.equal(session.getState().layout.zones[0].label, 'Edit two');
  await session.editZoneLabel('zn-desktop-zone', 'Edit three');
  assert.equal(session.getState().historyCursor, 3);
  assert.equal(saves, 0);
});

test('phase dispatch waits for durable checkpoint and identities remain stable', async () => {
  const gate = deferred(), entered = deferred();
  const value = fixture({ persist: async record => { if (record.phase === 'apply-prepare-pending') { entered.resolve(); await gate.promise; } } });
  const operation = apply(value);
  await entered.promise;
  assert.equal(value.calls.prepare, 0);
  assert.equal(value.adapter.snapshot().pendingOperations.length, 1);
  gate.resolve(); await operation;
  assert.equal(new Set(value.records.map(r => r.requestId)).size, 1);
  assert.equal(value.records.find(r => r.phase === 'apply-prepare-received').transactionId, 'tx-1');
  const installed = value.records.find(r => r.phase === 'apply-acknowledge-pending').snapshot;
  assert.equal(installed.editorFrame.draftLayout.zones[0].label, 'Prepared candidate');
  assert.equal(installed.editorFrame.batches.length, 1);
  assert.equal(value.cleared[0].resolution, 'applied');
  assert.equal(value.adapter.snapshot().pendingOperations.length, 0);
});

test('Close during checkpoint prevents late dispatch and retains a recoverable handle', async () => {
  const gate = deferred(), entered = deferred();
  const value = fixture({ persist: async record => { if (record.phase === 'apply-prepare-pending') { entered.resolve(); await gate.promise; } } });
  const operation = apply(value); await entered.promise;
  freeze(value.adapter);
  gate.resolve(); await assert.rejects(operation, e => e.code === 'facility_desktop_frozen');
  assert.equal(value.calls.prepare, 0);
  value.adapter.unfreeze({ intentId: 'close-a' });
  await assert.rejects(value.session.save(), e => e.code === 'facility_desktop_recovery_unresolved');
  assert.equal(value.adapter.snapshot().pendingOperations.length, 1);
});

test('lost Apply acknowledgment retains actual candidate and blocks Save without automatic recovery', async () => {
  const value = fixture({ loseApplyAck: true });
  await assert.rejects(apply(value), /Lost Apply/);
  const current = value.adapter.snapshot();
  assert.equal(current.editorFrame.draftLayout.zones[0].label, 'Prepared candidate');
  assert.equal(current.pendingOperations[0].phase, 'apply-acknowledge-unknown');
  assert.equal(current.pendingOperations[0].state, 'unknown');
  assert.equal(current.pendingOperations[0].transactionId, 'tx-1');
  assert.equal(value.calls.recover, 0);
  assert.equal(value.session.getState().canSave, false);
  await assert.rejects(value.session.save(), e => e.code === 'facility_desktop_recovery_unresolved');
  assert.equal(value.calls.save, 0);
  const reloaded = fixture();
  reloaded.adapter.restoreRecovery({ snapshot: current, ...expected(reloaded.adapter) });
  assert.deepEqual(reloaded.adapter.snapshot().editorFrame, current.editorFrame);
  assert.equal(reloaded.adapter.snapshot().recoveryOwned, true);
  assert.throws(() => reloaded.adapter.acceptReconciliation({ ...current.pendingOperations[0], requestId: 'wrong', resolution: 'applied', transactionRevision: 'active-verified', ...expected(reloaded.adapter) }), /match/);
  reloaded.adapter.acceptReconciliation({ ...current.pendingOperations[0], resolution: 'applied', transactionRevision: 'active-verified', ...expected(reloaded.adapter) });
  assert.equal(reloaded.session.getState().designProposalDraft.transactionRevision, 'active-verified');
  assert.equal(reloaded.session.getState().canSave, true);
  assert.deepEqual(reloaded.calls, { prepare: 0, commit: 0, applyAck: 0, undoPrepare: 0, undoAck: 0, recover: 0, save: 0 });
});

test('lost Undo acknowledgment restores real root frame and reload/reconciliation never replay Undo', async () => {
  const value = fixture({ loseUndoAck: true });
  const original = value.session.captureDesignEditorFrame();
  await apply(value);
  await assert.rejects(value.session.undoDesignProposal(), /Lost Undo/);
  const snapshot = value.adapter.snapshot(), operation = snapshot.pendingOperations[0];
  assert.equal(operation.kind, 'undo');
  assert.equal(operation.phase, 'undo-acknowledge-unknown');
  assert.deepEqual(snapshot.editorFrame.draftLayout, original.draftLayout);
  assert.deepEqual(snapshot.editorFrame.batches, original.batches);
  const reloaded = fixture();
  reloaded.adapter.restoreRecovery({ snapshot, ...expected(reloaded.adapter) });
  reloaded.adapter.acceptReconciliation({ ...operation, resolution: 'undone', ...expected(reloaded.adapter) });
  assert.deepEqual(reloaded.session.captureDesignEditorFrame(), original);
  assert.equal(reloaded.session.getState().designAuthorityState, 'ready');
  assert.equal(reloaded.calls.undoPrepare, 0);
  assert.equal(reloaded.calls.undoAck, 0);
  assert.equal(reloaded.calls.save, 0);
});

for (const kind of ['apply', 'undo']) test(`verified same-process ${kind} recovery clears its interruption without releasing the startup gate`, async () => {
  const value = fixture({ loseApplyAck: kind === 'apply', loseUndoAck: kind === 'undo' });
  if (kind === 'undo') await apply(value);
  await assert.rejects(kind === 'apply' ? apply(value) : value.session.undoDesignProposal(), /Lost .* acknowledgment/);
  const interruption = value.session.getState().lastError;
  assert.ok(interruption);
  const snapshot = value.adapter.snapshot(), operation = snapshot.pendingOperations[0];
  const callsBefore = clone(value.calls);
  value.adapter.setStartupRecoveryGate({ blocked: true, ...expected(value.adapter) });
  const request = { ...operation, resolution: kind === 'apply' ? 'applied' : 'undone', transactionRevision: 'verified-recovery' };
  assert.throws(() => value.adapter.acceptReconciliation({ ...request, ...expected(value.adapter),
    expectedRendererGeneration: 'stale-renderer' }), { code: 'facility_desktop_stale_state' });
  assert.throws(() => value.adapter.acceptReconciliation({ ...request, ...expected(value.adapter),
    transactionId: 'wrong-transaction' }), { code: 'facility_desktop_recovery_binding' });
  assert.equal(value.session.getState().lastError, interruption);
  assert.equal(value.session.getState().canSave, false);
  let observed;
  const unsubscribe = value.session.subscribe(state => { observed = state.lastError; });
  value.adapter.acceptReconciliation({ ...request, ...expected(value.adapter) });
  unsubscribe();
  assert.equal(value.session.getState().lastError, null);
  assert.equal(observed, null);
  assert.equal(value.session.getState().canSave, false);
  assert.equal(value.adapter.snapshot().startupRecoveryPending, true);
  const after = value.adapter.snapshot();
  for (const key of ['draftLayout', 'batches', 'cursor', 'selectedIds']) {
    assert.deepEqual(after.editorFrame[key], snapshot.editorFrame[key]);
  }
  assert.deepEqual(value.calls, callsBefore);
  assert.equal(value.calls.save, 0);
});

test('native clear hook may adopt a verified result once without recursive journaling', async () => {
  let clears = 0;
  const value = fixture({ clear: async (record, adapter) => {
    clears++;
    adapter.acceptReconciliation({ ...record, transactionRevision: 'verified-' + clears, ...expected(adapter) });
  } });
  await apply(value);
  await value.session.undoDesignProposal();
  assert.equal(clears, 2);
  assert.equal(value.adapter.snapshot().pendingOperations.length, 0);
});

test('lost native clear reply after verified adoption blocks Save and further mutations with no pending handle', async () => {
  const value = fixture({ clear: async (record, adapter) => {
    adapter.acceptReconciliation({ ...record, transactionRevision: 'verified', ...expected(adapter) });
    throw new Error('native clear reply lost after verified adoption');
  } });
  let saveTransports = 0;
  value.config.saveDesignProposalDraft = async () => { saveTransports++; throw new Error('Save transport must not run'); };
  await assert.rejects(apply(value), /native clear reply lost/);
  const before = value.adapter.snapshot(), callsBefore = clone(value.calls);
  assert.equal(before.pendingOperations.length, 0);
  assert.equal(before.designAuthorityState, 'desktop_recovery_required');
  assert.equal(value.session.getState().canSave, false);
  assert.equal(value.session.getState().canUndo, false);
  assert.equal(value.session.getState().canRedo, false);
  for (const mutate of [() => value.session.save(), () => value.session.undo(),
    () => value.session.redo(), () => apply(value)]) {
    await assert.rejects(mutate(), { code: 'facility_desktop_recovery_unresolved' });
  }
  assert.equal(saveTransports, 0);
  assert.deepEqual(value.calls, callsBefore);
  assert.deepEqual(value.adapter.snapshot(), before);
});

test('verified already-undone prepare adopts the exact restored root without another acknowledgment or Save', async () => {
  const value = fixture({ clear: async (record, adapter) => {
    adapter.acceptReconciliation({ ...record, transactionRevision: 'verified', ...expected(adapter) });
  } });
  const rootFrame = value.session.captureDesignEditorFrame();
  await apply(value);
  const prepare = value.config.prepareDesignUndo;
  value.config.prepareDesignUndo = async () => ({ ...await prepare(), mode: 'already_undone', readiness: 'ready' });
  await value.session.undoDesignProposal();
  assert.deepEqual(value.session.captureDesignEditorFrame(), rootFrame);
  assert.equal(value.adapter.snapshot().pendingOperations.length, 0);
  assert.equal(value.session.getState().designAuthorityState, 'ready');
  assert.equal(value.calls.undoPrepare, 1);
  assert.equal(value.calls.undoAck, 0);
  assert.equal(value.calls.save, 0);
});

test('local-only stale Undo cannot be adopted as an authoritative already-undone result', async () => {
  const value = fixture({ clear: async (record, adapter) => {
    adapter.acceptReconciliation({ ...record, transactionRevision: 'verified', ...expected(adapter) });
  } });
  await apply(value);
  const prepare = value.config.prepareDesignUndo;
  value.config.prepareDesignUndo = async () => ({ ...await prepare(), mode: 'local_only', readiness: 'stale_local_restore' });
  await assert.rejects(value.session.undoDesignProposal(), { code: 'facility_desktop_recovery_state' });
  assert.equal(value.adapter.snapshot().pendingOperations.length, 1);
  assert.equal(value.session.getState().designAuthorityState, 'stale_local_restore');
  await assert.rejects(value.session.save(), { code: 'facility_design_base_rebind_required' });
  assert.equal(value.calls.undoAck, 0);
  assert.equal(value.calls.save, 0);
});

test('recovery rejects another base and stale target without changing editor state', async () => {
  const value = fixture({ loseApplyAck: true }); await assert.rejects(apply(value));
  const fresh = fixture(), before = fresh.adapter.snapshot(), snapshot = value.adapter.snapshot();
  snapshot.document.baseRevision = 'other-base';
  assert.throws(() => fresh.adapter.restoreRecovery({ snapshot, ...expected(fresh.adapter) }), e => e.code === 'facility_desktop_recovery_binding');
  assert.throws(() => fresh.adapter.restoreRecovery({ snapshot: value.adapter.snapshot(), expectedRendererGeneration: 'stale', expectedStateSequence: 0 }), e => e.code === 'facility_desktop_stale_state');
  const damaged = value.adapter.snapshot(); damaged.editorFrame.cursor = 999;
  assert.throws(() => fresh.adapter.restoreRecovery({ snapshot: damaged, ...expected(fresh.adapter) }), e => e.code === 'facility_desktop_recovery_binding');
  assert.deepEqual(fresh.adapter.snapshot(), before);
});

test('a failed durable checkpoint never dispatches and leaves Save blocked', async () => {
  const value = fixture({ persist: async () => { throw new Error('Disk checkpoint failed'); } });
  await assert.rejects(apply(value), /Disk checkpoint failed/);
  assert.equal(value.calls.prepare, 0);
  assert.equal(value.adapter.snapshot().pendingOperations.length, 1);
  await assert.rejects(value.session.save(), e => e.code === 'facility_desktop_recovery_unresolved');
});

test('app exposes separate awaited recovery hooks without consulting synchronous Storage', async () => {
  const gate = deferred(); let options, completed = false;
  const recovery = { load: async () => null, persist: async () => { await gate.promise; }, clear: async () => {} };
  const app = App.createFacilityLayoutApp({ root: { ownerDocument: {} }, initialReceipt: { layout: base, revision: hash(base) },
    transport: {}, transportRuntime: {}, layoutRuntime: {}, sessionRuntime: { createSession(value) { options = value; return { load() {} }; } },
    workspaceRuntime: { createWorkspace() { return { getState() { return {}; } }; } },
    designUndoRecovery: recovery,
    designUndoRecoveryStorage: { getItem() { throw new Error('Storage must not be used'); }, setItem() { throw new Error('Storage must not be used'); }, removeItem() { throw new Error('Storage must not be used'); } },
    enableSpatialAdvisory: false,
  });
  await app.ready;
  const work = options.persistDesignUndoRecovery({ transactionId: 'tx' }).then(() => { completed = true; });
  await Promise.resolve(); assert.equal(completed, false);
  gate.resolve(); await work; assert.equal(completed, true);
});
