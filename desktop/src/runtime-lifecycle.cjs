'use strict';
const { isDeepStrictEqual } = require('node:util');
const path = require('node:path');
const { createFacilityRecoveryAdapter } = require('./facility-recovery-adapter.cjs');
const { createFacilityManagedRecovery } = require('./facility-managed-recovery.cjs');
const { assertEmpty } = require('../../static/desktop_workflow_observation.js');
const fail = (code, message = code) => Object.assign(new Error(message), { code });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const pickDocument = value => Object.fromEntries(['tenantId','siteId','documentId'].map(key => [key,value?.[key]]));
function createRuntimeLifecycle({ profile, supervisor, editor, setBackendAccess, lockInput, closeConnections, commitWindow,
  decideClose, inspectOtherWorkflows, notify = () => {}, adapterFactory = createFacilityRecoveryAdapter, managedFactory = createFacilityManagedRecovery }) {
  let adapter = null, binding = null, attached = false, closing = null, restarting = null, operationRequestId = null;
  function runtime() { const state = supervisor.getState(); if (state.status !== 'ready' || !state.runtime) throw fail('desktop_backend_not_ready'); return state.runtime; }
  function authorization(actual) { return { schemaVersion: 1, mode: 'desktop-managed', verified: true, facilityAcceptance: true,
    identity: actual.identity, document: actual.document, owner: actual.owner, instanceId: actual.instanceId }; }
  async function requireOtherWorkflowsEmpty(control) {
    control?.assertCurrent();
    if (!attached) return;
    if (typeof inspectOtherWorkflows !== 'function') throw fail('desktop_workflow_coverage_unavailable');
    const observed = await inspectOtherWorkflows(control);
    control?.assertCurrent();
    return assertEmpty(observed, binding.rendererGeneration);
  }
  async function attach(value) {
    const actual = JSON.parse(JSON.stringify(runtime()));
    if (!actual.capabilities.facilityAcceptance || !actual.document || value?.schemaVersion !== 1
      || !isDeepStrictEqual(value.identity, actual.identity) || !isDeepStrictEqual(value.owner, actual.owner)
      || !isDeepStrictEqual(pickDocument(value.document), actual.document) || value.runtimeInstanceId !== actual.instanceId
      || typeof value.rendererGeneration !== 'string' || !Number.isSafeInteger(value.stateSequence)) throw fail('desktop_facility_binding_mismatch');
    if (binding) {
      if (!isDeepStrictEqual(binding, value)) throw fail('desktop_facility_remount_requires_recovery');
      return status();
    }
    binding = JSON.parse(JSON.stringify(value));
    try {
      // Validate the renderer's claim before construction: the real adapter
      // inspects its durable journal and may release the initial startup gate.
      const before = await editor.snapshot();
      if (before.schemaVersion !== 1 || before.rendererGeneration !== value.rendererGeneration
          || before.stateSequence !== value.stateSequence || before.startupRecoveryPending !== true
          || before.document?.documentId !== actual.document.documentId
          || before.document.baseRevision !== value.document.baseRevision
          || before.document.draftRevision !== value.document.draftRevision) throw fail('desktop_facility_attach_changed');
      adapter = await adapterFactory({ authorizedDesktopRuntime: authorization(actual), identity: actual.identity,
        document: actual.document, owner: actual.owner, editor, recoveryDirectory: path.join(profile.dataRoot, 'desktop-recovery'),
        timeoutMs: 15000, lookupTimeoutMs: 15000,
        lookupOperation: input => supervisor.request('/api/desktop-shell/recovery/transaction', input),
        commitLifecycle: async (request, control, finalizeDiscard) => {
          await requireOtherWorkflowsEmpty(control); control.assertCurrent();
          await commitWindow(request, control, finalizeDiscard);
        } });
      const observed = await editor.snapshot();
      const expected = { ...before, startupRecoveryPending: observed.startupRecoveryPending,
        stateSequence: before.stateSequence + (observed.startupRecoveryPending === false ? 1 : 0) };
      // Only the guarded startup-gate transition may differ. A changed draft,
      // selection, history, pending transaction or document is never excused by
      // the expected sequence increment.
      if (typeof observed.startupRecoveryPending !== 'boolean' || !isDeepStrictEqual(observed, expected)
          || !isDeepStrictEqual(authorization(runtime()), authorization(actual))) throw fail('desktop_facility_attach_changed');
      attached = true;
      return status();
    } catch (error) { attached = false; lockInput(); notify({ status: 'recovery-required', code: error.code }); throw error; }
  }
  async function status() {
    const current = supervisor.getState();
    if (!adapter || !attached) return { ready: false, recoveryRequired: Boolean(binding), capabilities: current.runtime?.capabilities || { generalEditing: false, researchBrowsing: false, facilityAcceptance: false } };
    const gate = await adapter.getSaveGate();
    return { ready: true, recoveryRequired: !gate.allowed || current.status !== 'ready', capabilities: current.runtime?.capabilities
      || { generalEditing: false, researchBrowsing: false, facilityAcceptance: Boolean(profile.acceptanceLayoutId) }, blockers: gate.blockers };
  }
  async function persist(record) {
    if (!attached || !adapter) throw fail('desktop_facility_not_attached');
    runtime();
    const result = await adapter.persistOperation(record);
    operationRequestId = record.requestId;
    return result;
  }
  async function clear(record) { if (!attached || !adapter) throw fail('desktop_facility_not_attached'); runtime(); return adapter.clearOperation(record); }
  async function commitPrepared(decision) {
    const result = await adapter.commit(decision);
    if (result.status === 'blocked' && result.blockers?.some(code =>
        ['desktop_workflow_recovery_not_enabled', 'desktop_workflow_coverage_unavailable'].includes(code))) {
      await adapter.cancel(decision.intentId);
    }
    if (result.status !== 'committed') notify({ status: 'blocked', blockers: result.blockers });
    return result;
  }
  function close(reason = 'close') {
    if (closing) return closing;
    if (restarting) return Promise.reject(fail('desktop_restart_in_progress'));
    closing = (async () => {
      if (!adapter || !attached) {
        if (binding) throw fail('desktop_recovery_unresolved', 'Facility startup recovery has not been verified; keep the window open for recovery.');
        return commitWindow({ reason }, { assertCurrent() {} });
      }
      await requireOtherWorkflowsEmpty();
      const prepared = await adapter.prepare(reason);
      try { await requireOtherWorkflowsEmpty(); }
      catch (error) { await adapter.cancel(prepared.intentId); throw error; }
      if (prepared.status === 'ready') return commitPrepared({ intentId: prepared.intentId, rendererGeneration: prepared.rendererGeneration,
        stateSequence: prepared.stateSequence, discardDocumentIds: [] });
      const decision = await decideClose(prepared);
      if (decision !== 'discard' || prepared.status !== 'needsDecision') {
        await adapter.cancel(prepared.intentId); return { status: 'cancelled' };
      }
      const result = await commitPrepared({ intentId: prepared.intentId, rendererGeneration: prepared.rendererGeneration,
        stateSequence: prepared.stateSequence, discardDocumentIds: [runtime().document.documentId] });
      return result;
    })().finally(() => { closing = null; }); return closing;
  }
  function restart() {
    if (restarting) return restarting;
    if (closing) return Promise.reject(fail('desktop_close_in_progress'));
    let recoveryStarted = false;
    restarting = (async () => {
      const beforeRuntime = runtime();
      await requireOtherWorkflowsEmpty();
      if (!adapter || !attached) {
        if (binding) throw fail('desktop_recovery_unresolved');
        recoveryStarted = true; lockInput(); setBackendAccess(false); await closeConnections();
        await supervisor.restart(); setBackendAccess(true);
        return { status: 'reconciled', beforeRuntime, afterRuntime: runtime(), facilityLoaded: false };
      }
      const manager = managedFactory({ authorizedDesktopRuntime: authorization(beforeRuntime), adapter, editor,
        expectedRuntime: beforeRuntime,
        quiescePending: async control => {
          control.assertCurrent(); lockInput(); setBackendAccess(false); await closeConnections(); control.assertCurrent();
          const until = Date.now() + 15000;
          for (;;) {
            const snapshot = await editor.snapshot(); control.assertCurrent();
            if (!snapshot.busy && !snapshot.activeJobs.length) return;
            if (Date.now() >= until) throw fail('desktop_pending_transport_unsettled');
            await sleep(50);
          }
        },
        restartBackend: async control => { await requireOtherWorkflowsEmpty(control); control.assertCurrent();
          const afterRuntime = await supervisor.restart(); control.assertCurrent();
          return { status: 'ready', beforeRuntime, afterRuntime, writeAuthority: false }; },
        readRuntime: async control => { control.assertCurrent(); return runtime(); } });
      recoveryStarted = true;
      const result = await manager.restart();
      if (result.status === 'reconciled') setBackendAccess(true);
      else { lockInput(); setBackendAccess(false); }
      notify(result); return result;
    })().catch(error => {
      if (recoveryStarted) { lockInput(); setBackendAccess(false); }
      notify({ status: recoveryStarted ? 'recovery-required' : 'blocked', code: error.code }); throw error;
    })
      .finally(() => { restarting = null; }); return restarting;
  }
  async function retainedRecovery() { return adapter ? adapter.listRecovery() : []; }
  async function restoreRetained(key, expectedCheckpointId) {
    if (!adapter || !attached || closing || restarting) throw fail('desktop_recovery_unavailable');
    const entry = (await adapter.listRecovery()).find(item => item.key === key && item.checkpointId === expectedCheckpointId && !item.supersededBy);
    if (!entry || !entry.needsRestore) throw fail('desktop_recovery_selection_stale');
    const before = await editor.snapshot();
    const result = await adapter.recover({ key, expectedCheckpointId,
      expectedRendererGeneration: before.rendererGeneration, expectedStateSequence: before.stateSequence });
    // Restoring a frame does not confer authority. Pending operations still
    // require the adapter's authenticated durable lookup and explicit adoption.
    if (entry.type === 'operation') await adapter.clearOperation({ requestId: entry.handle.requestId,
      transactionId: entry.handle.transactionId, expectedCheckpointId: (await adapter.listRecovery()).find(item => item.key === key)?.checkpointId });
    await adapter.synchronizeRecoveryGate();
    return { ...result, ...(await status()) };
  }
  return { attach, status, persist, clear, close, restart, retainedRecovery, restoreRetained,
    getOperationRequestId: () => operationRequestId,
    hasFacility: () => attached, isBusy: () => Boolean(closing || restarting) };
}
module.exports = { createRuntimeLifecycle };
