'use strict';

const { randomUUID } = require('node:crypto');
const { isDeepStrictEqual } = require('node:util');
const { assertFacilityRuntimeAuthorization } = require('./facility-recovery-adapter.cjs');
const clone = value => JSON.parse(JSON.stringify(value));
const failure = (code, message = code) => Object.assign(new Error(message), { code });
const nonempty = value => typeof value === 'string' && value.length > 0 && value.length <= 2048;

function runtime(value) {
  const selected = {};
  for (const [name, keys] of Object.entries({ identity: ['backendId', 'storeId', 'principalId'],
    document: ['tenantId', 'siteId', 'documentId'], owner: ['sessionId', 'ownerId'] })) {
    if (!value?.[name] || keys.some(key => !nonempty(value[name][key]))) throw failure('facility_managed_runtime_invalid');
    selected[name] = Object.fromEntries(keys.map(key => [key, value[name][key]]));
  }
  if (!nonempty(value.instanceId) || !nonempty(value.origin)) throw failure('facility_managed_runtime_invalid');
  const url = new URL(value.origin);
  if (url.protocol !== 'http:' || !['127.0.0.1', '[::1]', 'localhost'].includes(url.hostname)
      || value.origin !== url.origin) throw failure('facility_managed_runtime_invalid');
  return { ...selected, instanceId: value.instanceId, origin: value.origin };
}

function operations(snapshot) {
  if (!Array.isArray(snapshot?.pendingOperations)) throw failure('facility_managed_snapshot_invalid');
  const result = snapshot.pendingOperations.map(operation => {
    if (!['apply', 'undo'].includes(operation.kind) || !nonempty(operation.requestId)
        || !nonempty(operation.transactionId)) throw failure('facility_managed_pending_identity_invalid');
    return { kind: operation.kind, requestId: operation.requestId, transactionId: operation.transactionId };
  }).sort((a, b) => a.requestId.localeCompare(b.requestId));
  if (new Set(result.map(item => item.requestId)).size !== result.length) throw failure('facility_managed_pending_identity_invalid');
  return result;
}

/**
 * Explicitly authorized facility restart gate. The supplied supervisor alone owns
 * process startup/shutdown, runtime authentication, and origin reservation.
 * This coordinator never dispatches a transaction, renews a lease, saves,
 * restores/discards an editor frame, or commits the window-close lifecycle.
 *
 * Pending transports must be quiesced to an unknown durable outcome before the
 * supervisor restarts. Only the adapter's authenticated, read-only durable
 * lookup can reconcile that outcome. Failed/foreign/expired ownership remains
 * frozen for explicit recovery, with the original editor frame retained.
 *
 * Callbacks receive per-invocation cooperative controls. Check the control at
 * each actual side effect after every await, including across IPC boundaries.
 * Their authority expires on cancellation or callback completion. Cancellation
 * is supported before restart dispatch; after dispatch the owned supervisor
 * must finish or fail closed. A second restart() joins the original operation.
 */
function createFacilityManagedRecovery(options = {}) {
  if (options.authorizedIsolatedHarness !== true && !options.authorizedDesktopRuntime) throw failure('facility_harness_not_authorized');
  const adapter = options.adapter;
  const editor = options.editor;
  for (const name of ['prepare', 'cancel', 'getLifecycleState', 'clearOperation', 'listRecovery', 'getSaveGate']) {
    if (typeof adapter?.[name] !== 'function') throw new TypeError('adapter.' + name + ' is required');
  }
  for (const name of ['snapshot', 'setStartupRecoveryGate']) {
    if (typeof editor?.[name] !== 'function') throw new TypeError('editor.' + name + ' is required');
  }
  for (const name of ['restartBackend', 'readRuntime']) if (typeof options[name] !== 'function') throw new TypeError(name + ' is required');
  const expectedRuntime = runtime(options.expectedRuntime);
  assertFacilityRuntimeAuthorization(options, expectedRuntime);
  const requestId = 'managed_restart_' + randomUUID();
  const work = new AbortController();
  let state = { status: 'idle', requestId, beforeRuntime: expectedRuntime, explicitRecoveryRequired: false };
  let retained = null;
  let retainedOperations = [];
  let intentId = null;
  let preparedPromise;
  let restartedPromise;
  let cancelledPromise;
  let restartDispatched = false;
  let cancelRequested = false;
  let lifecycleStarted = false;
  const getState = () => clone(state);

  function assertCurrent() {
    if (cancelRequested || work.signal.aborted) throw work.signal.reason || failure('facility_managed_cancelled');
  }
  async function invoke(callback, extra = {}, cleanup = false) {
    const controller = new AbortController();
    let finished = false;
    const forwardAbort = () => controller.abort(work.signal.reason);
    if (!cleanup) {
      work.signal.addEventListener('abort', forwardAbort, { once: true });
      if (work.signal.aborted) forwardAbort();
    }
    const isCurrent = () => !finished && !controller.signal.aborted && (cleanup || !cancelRequested);
    const check = () => { if (!isCurrent()) throw controller.signal.reason || failure('facility_managed_stale_callback'); };
    const control = Object.freeze({ requestId, intentId, beforeRuntime: clone(expectedRuntime),
      ...(retained ? { retainedSnapshot: clone(retained), pendingOperations: clone(retainedOperations) } : {}),
      ...extra, signal: controller.signal, isCurrent, assertCurrent: check,
      runIfCurrent(effect) { check(); return effect(); } });
    let rejectAbort;
    const aborted = new Promise((_, reject) => {
      rejectAbort = () => reject(controller.signal.reason || failure('facility_managed_cancelled'));
      controller.signal.addEventListener('abort', rejectAbort, { once: true });
      if (controller.signal.aborted) rejectAbort();
    });
    try {
      return await Promise.race([Promise.resolve().then(() => { check(); return callback(control); }), aborted]);
    } finally {
      finished = true;
      work.signal.removeEventListener('abort', forwardAbort);
      controller.signal.removeEventListener('abort', rejectAbort);
      controller.abort(failure('facility_managed_callback_settled'));
    }
  }
  async function snapshot() {
    const value = clone(await editor.snapshot());
    if (value.schemaVersion !== 1 || !nonempty(value.rendererGeneration)
        || !Number.isSafeInteger(value.stateSequence) || value.stateSequence < 0
        || !value.editorFrame || value.document?.documentId !== expectedRuntime.document.documentId) {
      throw failure('facility_managed_snapshot_invalid');
    }
    return value;
  }
  function verifyFrame(value, pending = true) {
    const expectedFrame = retained && clone(retained.editorFrame);
    if (!pending) for (const resolution of state.resolutions || []) {
      // The trusted durable lookup can advance only the active transaction's
      // status/revision metadata. Geometry, selection, complete Undo/Redo,
      // generations, receipts and the command journal remain byte-for-byte
      // structured values. Never normalize away arbitrary proposal changes.
      const active = expectedFrame.activeProposal;
      if (resolution.outcome === 'applied') {
        if (!active || active.transactionId !== resolution.transactionId
            || !['installation_pending', 'active'].includes(active.status)
            || !nonempty(resolution.transactionRevision)) throw failure('facility_managed_resolution_metadata_invalid');
        expectedFrame.activeProposal = { ...active, status: 'active', transactionRevision: resolution.transactionRevision };
      } else if (resolution.outcome === 'undone') {
        if (active && (active.transactionId !== resolution.transactionId
            || active.status !== 'undo_acknowledgment_pending')) throw failure('facility_managed_resolution_metadata_invalid');
        expectedFrame.activeProposal = null;
      } else if (resolution.outcome !== 'not-applied' || active) throw failure('facility_managed_resolution_metadata_invalid');
    }
    if (!retained || value.rendererGeneration !== retained.rendererGeneration
        || !isDeepStrictEqual(value.document, retained.document)
        || !isDeepStrictEqual(value.editorFrame, expectedFrame)) throw failure('facility_managed_editor_frame_changed');
    if (pending && !isDeepStrictEqual(operations(value), retainedOperations)) throw failure('facility_managed_pending_identity_changed');
  }
  async function setGate(blocked, cleanup = false) {
    const before = await snapshot();
    if (before.startupRecoveryPending === blocked) return before;
    const after = await invoke(control => editor.setStartupRecoveryGate({ blocked,
      expectedRendererGeneration: before.rendererGeneration, expectedStateSequence: before.stateSequence }, control), {}, cleanup);
    if (after?.startupRecoveryPending !== blocked) throw failure('facility_managed_gate_unacknowledged');
    return after;
  }
  async function handles() {
    const entries = await adapter.listRecovery();
    return retainedOperations.map(operation => {
      const matching = entries.filter(item => !item.supersededBy && item.type === 'operation'
        && item.handle?.requestId === operation.requestId && item.handle?.transactionId === operation.transactionId);
      if (matching.length !== 1 || matching[0].needsRestore || matching[0].adopted
          || !['pending', 'unknown'].includes(matching[0].handle.state)) throw failure('facility_managed_durable_handle_missing');
      return { ...operation, expectedCheckpointId: matching[0].checkpointId };
    });
  }
  async function blocked(error) {
    state = { ...state, status: 'requires-recovery', code: error.code || 'facility_managed_restart_failed',
      message: error.message || String(error), explicitRecoveryRequired: true };
    try { await setGate(true, true); state.saveGateRetained = true; }
    catch (gateError) { state.saveGateRetained = false; state.gateError = gateError.code || gateError.message; }
    return getState();
  }
  function prepare() {
    if (preparedPromise) return preparedPromise;
    if (cancelRequested) return Promise.resolve(getState());
    state.status = 'preparing';
    preparedPromise = (async () => {
      try {
        retained = await snapshot(); assertCurrent();
        retainedOperations = operations(retained);
        state.pendingOperations = clone(retainedOperations);
        if (adapter.getLifecycleState().phase !== 'idle') throw failure('facility_managed_lifecycle_owned');
        lifecycleStarted = true;
        const preparation = adapter.prepare('backendRestart');
        intentId = adapter.getLifecycleState().intentId;
        state.intentId = intentId;
        const prepared = await preparation;
        assertCurrent();
        if (!intentId || prepared.intentId !== intentId || prepared.reason !== 'backendRestart'
            || prepared.rendererGeneration !== retained.rendererGeneration || prepared.stateSequence !== retained.stateSequence
            || !['ready', 'needsDecision', 'blocked'].includes(prepared.status)) throw failure('facility_managed_freeze_failed');
        verifyFrame(await snapshot()); assertCurrent();
        await setGate(true); assertCurrent();
        verifyFrame(await snapshot()); assertCurrent();
        await handles(); assertCurrent();
        state.status = 'prepared';
        return getState();
      } catch (error) {
        if (cancelRequested) return getState();
        return blocked(error);
      }
    })();
    return preparedPromise;
  }
  function verifyRuntime(value, instance = 'new') {
    const actual = runtime(value);
    for (const field of ['identity', 'document', 'owner', 'origin']) {
      if (!isDeepStrictEqual(actual[field], expectedRuntime[field])) throw failure('facility_managed_identity_mismatch', 'Managed runtime changed ' + field);
    }
    if (instance === 'new' ? actual.instanceId === expectedRuntime.instanceId : actual.instanceId !== expectedRuntime.instanceId) {
      throw failure('facility_managed_process_instance_mismatch');
    }
    return actual;
  }
  function restart() {
    if (restartedPromise) return restartedPromise;
    restartedPromise = (async () => {
      await prepare();
      if (state.status !== 'prepared' || cancelRequested) return getState();
      try {
        state.status = 'quiescing';
        if (retainedOperations.length && typeof options.quiescePending !== 'function') throw failure('facility_managed_quiesce_required');
        if (options.quiescePending) await invoke(options.quiescePending);
        assertCurrent();
        const quiesced = await snapshot(); assertCurrent(); verifyFrame(quiesced);
        if (quiesced.busy || quiesced.activeJobs?.length) throw failure('facility_managed_operation_not_quiescent');
        const pending = await handles(); assertCurrent();
        state.status = 'restarting';
        restartDispatched = true;
        const result = await invoke(options.restartBackend);
        if (result?.status !== 'ready') throw failure(result?.status === 'identity-mismatch'
          ? 'facility_managed_identity_mismatch' : result?.error?.code || 'facility_managed_restart_failed');
        verifyRuntime(result.beforeRuntime, 'same');
        const afterRuntime = verifyRuntime(await invoke(options.readRuntime));
        if (result.afterRuntime && !isDeepStrictEqual(runtime(result.afterRuntime), afterRuntime)) throw failure('facility_managed_runtime_observation_mismatch');
        state.afterRuntime = afterRuntime;
        state.status = 'reconciling';
        verifyFrame(await snapshot());
        state.resolutions = [];
        for (const operation of pending) {
          const resolution = await adapter.clearOperation(operation);
          if (resolution?.status !== 'reconciled') throw failure('facility_managed_transaction_unresolved');
          state.resolutions.push({ requestId: operation.requestId, transactionId: operation.transactionId, ...clone(resolution) });
        }
        const reconciled = await snapshot(); verifyFrame(reconciled, false);
        if (reconciled.pendingOperations.length || reconciled.busy || reconciled.activeJobs?.length || reconciled.conflict) throw failure('facility_managed_transaction_unresolved');
        // The adapter's lifecycle freeze keeps Save blocked even if its verified
        // adoption has already released the startup gate.
        await setGate(false);
        const released = await adapter.cancel(intentId);
        if (released.status !== 'cancelled') throw failure('facility_managed_unfreeze_failed');
        verifyFrame(await snapshot(), false);
        const gate = await adapter.getSaveGate();
        if (!gate.allowed) throw failure('facility_managed_save_gate_unresolved');
        state = { ...state, status: 'reconciled', explicitRecoveryRequired: false,
          exactDraftSelectionHistoryRetained: true, verifiedProposalMetadataAdopted: true };
        return getState();
      } catch (error) {
        if (cancelRequested) return getState();
        return blocked(error);
      }
    })();
    return restartedPromise;
  }
  function cancel() {
    if (restartDispatched) return Promise.reject(failure('facility_managed_restart_in_progress'));
    if (cancelledPromise) return cancelledPromise;
    cancelRequested = true;
    state.status = 'cancelling';
    work.abort(failure('facility_managed_cancelled'));
    cancelledPromise = (async () => {
      try {
        const active = lifecycleStarted ? intentId || adapter.getLifecycleState().intentId : null;
        if (active) {
          const result = await adapter.cancel(active);
          if (result.status !== 'cancelled') throw failure('facility_managed_cancel_failed');
        }
        await preparedPromise;
        if (retained) {
          verifyFrame(await snapshot());
          // Pending ownership keeps Save blocked exactly as before preparation.
          if (!retainedOperations.length) await setGate(retained.startupRecoveryPending === true, true);
        }
        state = { ...state, status: 'cancelled', explicitRecoveryRequired: false, exactEditorFrameRetained: !!retained };
        return getState();
      } catch (error) { return blocked(error); }
    })();
    return cancelledPromise;
  }
  async function getSaveGate() {
    // Do not queue behind a pending durable lookup just to report that Save is
    // blocked: that lookup may be precisely the operation holding this gate.
    if (!['idle', 'cancelled', 'reconciled'].includes(state.status)) return { allowed: false,
      blockers: ['managed_backend_recovery_pending'], rendererGeneration: retained?.rendererGeneration,
      stateSequence: retained?.stateSequence };
    return adapter.getSaveGate();
  }
  return Object.freeze({ prepare, restart, cancel, getState, getSaveGate,
    async assertSaveAllowed() { const gate = await getSaveGate(); if (!gate.allowed) throw failure('facility_save_blocked'); return gate; } });
}

module.exports = { createFacilityManagedRecovery };
