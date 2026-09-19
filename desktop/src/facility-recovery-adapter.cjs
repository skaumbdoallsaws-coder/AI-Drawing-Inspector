'use strict';

const { randomUUID, createHash } = require('node:crypto');
const { isDeepStrictEqual } = require('node:util');
const { createLifecycleCoordinator } = require('./lifecycle-coordinator.cjs');
const { createRecoveryStore } = require('./recovery-store.cjs');

const VERSION = 'facility-recovery-v1';
const error = (code, message = code) => Object.assign(new Error(message), { code });
const text = value => typeof value === 'string' && value.length > 0 && value.length <= 512;
function data(value) {
  const seen = new Set();
  function inspect(item, depth) {
    if (depth > 32) throw error('facility_recovery_schema_invalid');
    if (item === null || typeof item === 'boolean' || typeof item === 'string'
        || (typeof item === 'number' && Number.isFinite(item))) return;
    if (!item || typeof item !== 'object' || seen.has(item)
        || (!Array.isArray(item) && ![Object.prototype, null].includes(Object.getPrototypeOf(item)))) {
      throw error('facility_recovery_schema_invalid');
    }
    seen.add(item);
    for (const child of Object.values(item)) inspect(child, depth + 1);
    seen.delete(item);
  }
  inspect(value, 0);
  return JSON.parse(JSON.stringify(value));
}
function fields(value, keys, code) {
  if (!value || keys.some(key => !text(value[key]))) throw error(code);
  return Object.fromEntries(keys.map(key => [key, value[key]]));
}
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  return JSON.stringify(value);
}

function assertFacilityRuntimeAuthorization(options, binding) {
  if (options.authorizedIsolatedHarness === true) return;
  const authorization = options.authorizedDesktopRuntime;
  if (!authorization || authorization.schemaVersion !== 1 || authorization.mode !== 'desktop-managed'
      || authorization.verified !== true || authorization.facilityAcceptance !== true
      || !text(authorization.instanceId)) throw error('facility_runtime_not_authorized');
  for (const name of ['identity', 'document', 'owner']) {
    if (!isDeepStrictEqual(authorization[name], binding[name])) throw error('facility_runtime_binding_mismatch');
  }
  if (binding.instanceId && authorization.instanceId !== binding.instanceId) throw error('facility_runtime_binding_mismatch');
}

/**
 * Explicitly authorized facility recovery bridge, not general workflow coverage.
 *
 * editor.snapshot/freeze/unfreeze/restoreRecovery/acceptReconciliation belong
 * to the installed real facility session facade. They must guard generation,
 * sequence and intent AT the renderer side effect; local coordinator guards do
 * not revoke an IPC message already queued in another process. Freeze ownership
 * must survive late replies, and Cancel must never restore/discard/undo a frame.
 *
 * persistOperation is awaited before transport dispatch. This adapter never
 * dispatches, repeats, cancels, saves, or undoes an operation. lookupOperation
 * must be a READ-ONLY, authenticated backend lookup. The main-owned mapper must
 * verify the backend lease and editor-generation binding against the retained
 * request/response before returning resolved. Identity/owner/handle equality is
 * independently checked here. A renderer assertion is not a verified lookup.
 *
 * Recovery restore and transaction adoption are explicit, CAS-checked calls.
 * Unknown handles are retained. Even a durably reconciled handle blocks Save
 * until its corresponding renderer state has been explicitly adopted. Records
 * remain retained. A newer durable full-state checkpoint can supersede exact
 * reconciled/adopted predecessors; no pending or unknown handle is superseded.
 * Cancel may clear only its own reconciled draft checkpoint after exact state
 * comparison. This is not a general journal compactor or record-deletion API.
 */
async function createFacilityRecoveryAdapter(options = {}) {
  if (options.authorizedIsolatedHarness !== true && !options.authorizedDesktopRuntime) throw error('facility_harness_not_authorized');
  const identity = fields(options.identity, ['backendId', 'storeId', 'principalId'], 'facility_identity_invalid');
  const document = fields(options.document, ['tenantId', 'siteId', 'documentId'], 'facility_document_invalid');
  const owner = fields(options.owner, ['sessionId', 'ownerId'], 'facility_owner_invalid');
  assertFacilityRuntimeAuthorization(options, { identity, document, owner });
  const requireDiscardFinalization = !!options.authorizedDesktopRuntime || options.requireDiscardFinalization === true;
  const editor = options.editor;
  for (const name of ['snapshot', 'freeze', 'unfreeze', 'restoreRecovery', 'acceptReconciliation']) {
    if (typeof editor?.[name] !== 'function') throw new TypeError('editor.' + name + ' is required');
  }
  for (const name of ['lookupOperation', 'commitLifecycle']) {
    if (typeof options[name] !== 'function') throw new TypeError(name + ' is required');
  }
  const lookupTimeoutMs = options.lookupTimeoutMs ?? 5000;
  if (!Number.isSafeInteger(lookupTimeoutMs) || lookupTimeoutMs < 1 || lookupTimeoutMs > 60000) throw new TypeError('Invalid lookup timeout');
  const store = options.recoveryStore || await createRecoveryStore({ directory: options.recoveryDirectory, identity,
    onDiagnostic: options.onRecoveryDiagnostic });
  for (const name of ['read', 'write', 'list', 'clear']) if (typeof store?.[name] !== 'function') throw new TypeError('Recovery store is required');
  let generation;
  let frozenIntent = null;
  const entries = new Map();
  let queue = Promise.resolve();
  function serial(fn) {
    const result = queue.then(fn);
    queue = result.catch(() => {});
    return result;
  }
  function validateSnapshot(value) {
    const state = data(value);
    if (state.schemaVersion !== 1 || !text(state.rendererGeneration)
        || !Number.isSafeInteger(state.stateSequence) || state.stateSequence < 0
        || typeof state.dirty !== 'boolean' || typeof state.busy !== 'boolean'
        || !Array.isArray(state.pendingOperations) || !Array.isArray(state.activeJobs)
        || !state.editorFrame || typeof state.editorFrame !== 'object'
        || state.document?.documentId !== document.documentId
        || !text(state.document?.baseRevision) || !text(state.document?.draftRevision)) {
      throw error('facility_snapshot_invalid');
    }
    if (generation && state.rendererGeneration !== generation) throw error('facility_renderer_changed');
    return state;
  }
  async function snapshot() { return validateSnapshot(await editor.snapshot()); }
  function samePosition(before, after) {
    if (before.rendererGeneration !== after.rendererGeneration || before.stateSequence !== after.stateSequence) {
      throw error('facility_state_changed');
    }
  }
  function bindRecord(record) {
    if (record.payload?.adapter !== VERSION || !isDeepStrictEqual(record.identity, identity)
        || !isDeepStrictEqual(Object.fromEntries(Object.keys(document).map(k => [k, record.document[k]])), document)
        || !isDeepStrictEqual(record.payload.owner, owner)
        || !['draft', 'operation', 'discard'].includes(record.payload.type)) throw error('facility_recovery_owner_mismatch');
    // Historical generations are expected after restart; snapshot() validates
    // the active renderer separately from the retained editor frame.
    if (!record.payload.snapshot || record.payload.snapshot.document?.documentId !== document.documentId) {
      throw error('facility_recovery_schema_invalid');
    }
  }
  async function refresh() {
    const seen = new Set();
    for (const summary of await store.list()) {
      if (summary.document.documentId !== document.documentId) continue;
      const envelope = await store.read(summary.key);
      if (!envelope) throw error('facility_checkpoint_missing');
      bindRecord(envelope.record);
      seen.add(envelope.key);
      const prior = entries.get(envelope.key);
      if (!prior || prior.envelope.checkpointId !== envelope.checkpointId) {
        entries.set(envelope.key, { envelope, restored: false, adopted: false, loaded: true });
      }
    }
    for (const key of entries.keys()) if (!seen.has(key)) entries.delete(key);
    for (const entry of entries.values()) { entry.supersededBy = null; entry.retiredBy = null; }
    for (const entry of entries.values()) {
      const refs = entry.envelope.record.payload.supersedes || [];
      if (!Array.isArray(refs) || refs.length > 1000) throw error('facility_supersession_invalid');
      for (const ref of refs) {
        const prior = entries.get(ref.key);
        if (!prior || prior === entry || prior.envelope.record.payload.type === 'discard' || prior.envelope.checkpointId !== ref.checkpointId
            || prior.envelope.record.handle.state !== 'reconciled'
            || !text(ref.adoption?.rendererGeneration) || !Number.isSafeInteger(ref.adoption?.stateSequence)
            || ref.adoption.stateSequence < 0) {
          throw error('facility_supersession_invalid');
        }
        prior.supersededBy = entry.envelope.key;
      }
    }
    for (const start of entries.values()) {
      const walked = new Set(); let item = start;
      while (item?.supersededBy) {
        if (walked.has(item.envelope.key)) throw error('facility_supersession_invalid');
        walked.add(item.envelope.key); item = entries.get(item.supersededBy);
      }
    }
    // A close decision is one atomic, validated receipt. Keep the referenced
    // files: partial multi-file deletion could expose an older superseded draft.
    for (const receipt of entries.values()) {
      const record = receipt.envelope.record;
      if (record.payload.type !== 'discard') continue;
      const refs = record.payload.retiredCheckpoints;
      const state = record.payload.snapshot;
      if (record.handle.state !== 'reconciled' || record.handle.phase !== 'explicit-close-discard'
          || !text(record.payload.intentId) || record.handle.requestId !== 'close_' + record.payload.intentId
          || !['close', 'reload'].includes(record.payload.reason) || typeof state.dirty !== 'boolean'
          || !text(state.rendererGeneration) || !Number.isSafeInteger(state.stateSequence) || state.stateSequence < 0
          || state.document.baseRevision !== record.document.baseRevision || state.document.draftRevision !== record.document.draftRevision
          || record.payload.supersedes !== undefined
          || !isDeepStrictEqual(record.payload.discardDocumentIds, state.dirty ? [document.documentId] : [])
          || !Array.isArray(refs) || !refs.length || refs.length > 1000
          || new Set(refs.map(ref => ref.key)).size !== refs.length) throw error('facility_discard_receipt_invalid');
      for (const ref of refs) {
        const prior = entries.get(ref.key);
        if (!prior || prior.envelope.checkpointId !== ref.checkpointId
            || !['draft', 'operation'].includes(prior.envelope.record.payload.type)
            || prior.envelope.record.handle.state !== 'reconciled'
            || !text(ref.adoption?.rendererGeneration) || !Number.isSafeInteger(ref.adoption?.stateSequence)
            || ref.adoption.stateSequence < 0 || (prior.retiredBy && prior.retiredBy !== receipt.envelope.key)) {
          throw error('facility_discard_checkpoint_conflict');
        }
        prior.retiredBy = receipt.envelope.key;
        for (const ancestor of prior.envelope.record.payload.supersedes || []) {
          if (!refs.some(item => item.key === ancestor.key && item.checkpointId === ancestor.checkpointId)) {
            throw error('facility_discard_checkpoint_conflict');
          }
        }
      }
    }
  }
  async function write(key, record, prior, flags = {}) {
    const ack = await store.write({ key, record, ...(prior ? { expectedCheckpointId: prior.envelope.checkpointId } : {}) });
    if (ack.acknowledged !== true || !text(ack.checkpointId)) throw error('facility_checkpoint_unacknowledged');
    const envelope = await store.read(key);
    if (!envelope || envelope.checkpointId !== ack.checkpointId) throw error('facility_checkpoint_conflict');
      entries.set(key, { envelope, loaded: false, restored: true, adopted: false,
      ...(prior ? { loaded: prior.loaded, restored: prior.restored, adopted: prior.adopted, adoption: prior.adoption } : {}), ...flags });
    return { key, checkpointId: ack.checkpointId, acknowledged: true, durability: ack.durability };
  }
  function unresolved() {
    return [...entries.values()].filter(entry => !entry.retiredBy && !entry.supersededBy && entry.envelope.record.payload.type === 'operation'
      && (entry.envelope.record.handle.state !== 'reconciled' || !entry.adopted));
  }
  function recoveryBlockers() {
    const blockers = unresolved().map(entry => 'transaction_unresolved:' + entry.envelope.record.handle.requestId);
    for (const entry of entries.values()) if (!entry.retiredBy && !entry.supersededBy
      && entry.envelope.record.payload.type !== 'discard' && entry.loaded && !entry.restored) blockers.push('recovery_restore_required:' + entry.envelope.key);
    return blockers;
  }
  generation = (await snapshot()).rendererGeneration;
  await refresh();
  async function synchronizeStartupGate() {
    const before = await snapshot();
    if (typeof editor.setStartupRecoveryGate !== 'function') {
      if (before.startupRecoveryPending === true) throw error('facility_startup_gate_bridge_missing');
      return before;
    }
    const blocked = recoveryBlockers().length > 0;
    if (before.startupRecoveryPending === blocked) return before;
    const after = validateSnapshot(await editor.setStartupRecoveryGate({ blocked,
      expectedRendererGeneration: before.rendererGeneration, expectedStateSequence: before.stateSequence }));
    if (after.startupRecoveryPending !== blocked) throw error('facility_startup_gate_unacknowledged');
    return after;
  }
  // The harness renderer opted into a blocked state before async inspection.
  // Identity, journal, and bridge failures cannot silently release that gate.
  await synchronizeStartupGate();

  function persistOperation(operation) {
    const input = data(operation);
    if (!['apply', 'undo'].includes(input.kind) || !text(input.requestId) || !text(input.phase)
        || !['pending', 'unknown'].includes(input.state)
        || (input.transactionId !== undefined && !text(input.transactionId))) {
      return Promise.reject(error('facility_operation_invalid'));
    }
    return serial(async () => {
      await refresh();
      const live = await snapshot();
      const frame = input.snapshot ? validateSnapshot(input.snapshot) : live;
      samePosition(frame, live);
      const prior = [...entries.values()].find(item => item.envelope.record.handle.requestId === input.requestId);
      if (!prior && (frozenIntent || recoveryBlockers().length)) throw error('facility_operation_blocked');
      if (prior) {
        if (prior.supersededBy || prior.retiredBy) throw error('facility_operation_superseded');
        const old = prior.envelope.record;
        if (old.payload.operation.kind !== input.kind || (old.handle.transactionId
            && input.transactionId && old.handle.transactionId !== input.transactionId)) throw error('facility_operation_binding_conflict');
        if (old.handle.state === 'reconciled') throw error('facility_operation_already_resolved');
        if (old.handle.state === 'unknown' && input.state !== 'unknown') throw error('facility_operation_unresolved');
      }
      const details = { ...input }; delete details.snapshot;
      const record = prior ? data(prior.envelope.record) : {
        schemaVersion: 1, identity, document: { ...document, baseRevision: frame.document.baseRevision, draftRevision: frame.document.draftRevision },
        handle: { requestId: input.requestId, phase: input.phase, state: input.state },
        payload: { adapter: VERSION, type: 'operation', owner, snapshot: frame, operation: details, phaseLog: [],
          supersedes: [...entries.values()].filter(item => !item.retiredBy && !item.supersededBy && item.adopted
            && ['draft', 'operation'].includes(item.envelope.record.payload.type)
            && item.envelope.record.handle.state === 'reconciled')
            .map(item => ({ key: item.envelope.key, checkpointId: item.envelope.checkpointId,
              adoption: item.adoption || { rendererGeneration: item.envelope.record.payload.snapshot.rendererGeneration,
                stateSequence: item.envelope.record.payload.snapshot.stateSequence } })) },
      };
      const transactionId = input.transactionId || record.handle.transactionId;
      record.handle = { requestId: input.requestId, ...(transactionId ? { transactionId } : {}), phase: input.phase, state: input.state };
      record.payload.operation = details;
      // The immutable record document binds the operation START. Payload state
      // follows each durable phase, including a locally installed candidate.
      record.payload.snapshot = frame;
      // Keep a bounded diagnostic trail; it is data, never an instruction to replay.
      const phaseSummary = { phase: input.phase, state: input.state, requestId: input.requestId,
        ...(transactionId ? { transactionId } : {}), diagnosticSha256: createHash('sha256').update(canonical(details)).digest('hex') };
      const priorPhase = record.payload.phaseLog.at(-1);
      if (!isDeepStrictEqual(priorPhase, phaseSummary)) {
        if (record.payload.phaseLog.length >= 64) throw error('facility_operation_phase_limit');
        record.payload.phaseLog.push(phaseSummary);
      }
      if (prior && isDeepStrictEqual(record, prior.envelope.record)) return {
        key: prior.envelope.key, checkpointId: prior.envelope.checkpointId, acknowledged: true, duplicate: true,
      };
      return write(prior?.envelope.key || 'facility_' + randomUUID(), record, prior, { adopted: false });
    });
  }

  function clearOperation(operation) {
    const input = data(operation);
    if (!text(input.requestId)) return Promise.reject(error('facility_operation_invalid'));
    return serial(async () => {
      await refresh();
      const entry = [...entries.values()].find(item => item.envelope.record.handle.requestId === input.requestId);
      if (!entry || entry.envelope.record.payload.type !== 'operation') throw error('facility_operation_missing');
      if (entry.supersededBy || entry.retiredBy) throw error('facility_operation_superseded');
      if (input.expectedCheckpointId && input.expectedCheckpointId !== entry.envelope.checkpointId) throw error('facility_checkpoint_conflict');
      const record = data(entry.envelope.record);
      if (input.transactionId && record.handle.transactionId && input.transactionId !== record.handle.transactionId) throw error('facility_operation_binding_conflict');
      const before = await snapshot();
      const controller = new AbortController();
      let timer;
      let lookup;
      try {
        lookup = data(await Promise.race([
          Promise.resolve().then(() => options.lookupOperation({ identity: data(identity), document: data(document), owner: data(owner),
            requestId: record.handle.requestId, ...(record.handle.transactionId ? { transactionId: record.handle.transactionId } : {}),
            kind: record.payload.operation.kind, phase: record.handle.phase, record: data(record) }, { signal: controller.signal })),
          new Promise((_, reject) => { timer = setTimeout(() => {
            const failure = error('facility_lookup_timeout'); controller.abort(failure); reject(failure);
          }, lookupTimeoutMs); }),
        ]));
      } finally { clearTimeout(timer); controller.abort(error('facility_lookup_settled')); }
      if (!isDeepStrictEqual(lookup.identity, identity) || !isDeepStrictEqual(lookup.document, document)
          || !isDeepStrictEqual(lookup.owner, owner) || lookup.requestId !== record.handle.requestId
          || lookup.kind !== record.payload.operation.kind) throw error('facility_reconciliation_owner_mismatch');
      if ((record.handle.transactionId && lookup.transactionId !== record.handle.transactionId)
          || (input.transactionId && lookup.transactionId !== input.transactionId)) throw error('facility_reconciliation_transaction_mismatch');
      if (lookup.status !== 'resolved' || !['applied', 'undone', 'not-applied'].includes(lookup.outcome)
          || (lookup.outcome !== 'not-applied' && !text(lookup.transactionId))) throw error('facility_transaction_unresolved');
      if ((lookup.kind === 'apply' && lookup.outcome === 'undone') || (lookup.kind === 'undo' && lookup.outcome === 'applied')) {
        throw error('facility_reconciliation_outcome_mismatch');
      }
      samePosition(before, await snapshot());
      record.handle = { ...record.handle, ...(lookup.transactionId ? { transactionId: lookup.transactionId } : {}), state: 'reconciled', phase: 'owner-and-transaction-reconciled' };
      record.payload.resolution = lookup;
      const ack = await write(entry.envelope.key, record, entry, { adopted: false });
      samePosition(before, await snapshot());
      if (entry.loaded && !entry.restored) throw error('facility_recovery_restore_required');
      const adopted = validateSnapshot(await editor.acceptReconciliation({ record: data(record), resolution: lookup.outcome, verifiedResolution: lookup,
        ...(lookup.transactionRevision ? { transactionRevision: lookup.transactionRevision } : {}), requestId: record.handle.requestId,
        ...(record.handle.transactionId ? { transactionId: record.handle.transactionId } : {}), kind: record.payload.operation.kind,
        expectedRendererGeneration: before.rendererGeneration, expectedStateSequence: before.stateSequence }));
      // A failed/stale adoption retains its reconciled journal and Save gate.
      const current = entries.get(entry.envelope.key);
      current.adopted = true;
      current.adoption = { rendererGeneration: adopted.rendererGeneration, stateSequence: adopted.stateSequence };
      await synchronizeStartupGate();
      return { ...ack, status: 'reconciled', outcome: lookup.outcome,
        ...(lookup.transactionRevision ? { transactionRevision: lookup.transactionRevision } : {}) };
    });
  }

  function recover(request) {
    const input = data(request);
    return serial(async () => {
      await refresh();
      const entry = entries.get(input.key);
      if (!entry || entry.envelope.checkpointId !== input.expectedCheckpointId) throw error('facility_checkpoint_conflict');
      if (entry.supersededBy || entry.retiredBy || entry.envelope.record.payload.type === 'discard') throw error('facility_operation_superseded');
      const current = await snapshot();
      if (current.rendererGeneration !== input.expectedRendererGeneration || current.stateSequence !== input.expectedStateSequence) throw error('facility_state_changed');
      if (frozenIntent || current.busy || current.activeJobs.length) throw error('facility_restore_busy');
      if (current.dirty && input.discardCurrentDraft !== true) throw error('facility_restore_would_replace_draft');
      if (entry.envelope.record.payload.type === 'draft'
          && (entry.envelope.record.handle.state !== 'reconciled'
            || entry.envelope.record.payload.snapshot.pendingOperations?.length !== 0)) throw error('facility_recovery_schema_invalid');
      await editor.restoreRecovery({ snapshot: data(entry.envelope.record.payload.snapshot), record: data(entry.envelope.record),
        expectedRendererGeneration: current.rendererGeneration, expectedStateSequence: current.stateSequence });
      const restored = await snapshot();
      if (!isDeepStrictEqual(restored.editorFrame, entry.envelope.record.payload.snapshot.editorFrame)) throw error('facility_restore_incomplete');
      entry.restored = true;
      if (entry.envelope.record.payload.type === 'draft') {
        entry.adopted = true;
        entry.adoption = { rendererGeneration: restored.rendererGeneration, stateSequence: restored.stateSequence };
        await synchronizeStartupGate();
      }
      return { key: input.key, restored: true, transactionResolved: entry.envelope.record.handle.state === 'reconciled' && entry.adopted };
    });
  }

  function retirementCandidates() {
    function adoption(entry) {
      if (entry.adopted && (!entry.loaded || entry.restored)) return entry.adoption || {
        rendererGeneration: entry.envelope.record.payload.snapshot.rendererGeneration,
        stateSequence: entry.envelope.record.payload.snapshot.stateSequence };
      // Superseded ancestors carry durable evidence of adoption. Require their
      // entire successor chain to terminate at a currently adopted checkpoint.
      if (entry.supersededBy) {
        const successor = entries.get(entry.supersededBy);
        adoption(successor);
        return successor.envelope.record.payload.supersedes.find(ref => ref.key === entry.envelope.key).adoption;
      }
      throw error('facility_discard_unadopted');
    }
    return [...entries.values()].filter(entry => !entry.retiredBy && entry.envelope.record.payload.type !== 'discard')
      .map(entry => {
        if (entry.envelope.record.handle.state !== 'reconciled') throw error('facility_discard_unresolved');
        const proof = adoption(entry);
        if (!text(proof?.rendererGeneration) || !Number.isSafeInteger(proof?.stateSequence) || proof.stateSequence < 0) throw error('facility_discard_unadopted');
        return { key: entry.envelope.key, checkpointId: entry.envelope.checkpointId, adoption: data(proof) };
      }).sort((left, right) => left.key.localeCompare(right.key));
  }

  async function commitWithFinalization(request, control) {
    control.assertCurrent();
    if (!requireDiscardFinalization) return options.commitLifecycle(request, control);
    if (!['close', 'reload'].includes(request.reason)) throw error('facility_discard_reason_invalid');
    const before = await snapshot(); control.assertCurrent();
    await refresh(); control.assertCurrent();
    if (frozenIntent !== request.intentId || before.rendererGeneration !== request.rendererGeneration
        || before.stateSequence !== request.stateSequence || before.busy || before.pendingOperations.length
        || before.activeJobs.length || before.conflict || recoveryBlockers().length
        || !isDeepStrictEqual(request.discardDocumentIds, before.dirty ? [document.documentId] : [])) throw error('facility_discard_not_ready');
    const refs = retirementCandidates();
    const receiptKey = 'facility_discard_' + randomUUID();
    let finalized = null;
    const finalizeDiscard = () => serial(async () => {
      control.assertCurrent();
      if (finalized) return data(finalized);
      const current = await snapshot(); control.assertCurrent();
      await refresh(); control.assertCurrent();
      if (frozenIntent !== request.intentId || !isDeepStrictEqual(current, before)
          || recoveryBlockers().length || !isDeepStrictEqual(retirementCandidates(), refs)) throw error('facility_discard_checkpoint_conflict');
      if (!refs.length) { finalized = { status: 'finalized', retired: 0 }; return data(finalized); }
      const record = { schemaVersion: 1, identity,
        document: { ...document, baseRevision: before.document.baseRevision, draftRevision: before.document.draftRevision },
        handle: { requestId: 'close_' + request.intentId, state: 'reconciled', phase: 'explicit-close-discard' },
        payload: { adapter: VERSION, type: 'discard', owner, intentId: request.intentId, reason: request.reason,
          discardDocumentIds: data(request.discardDocumentIds), retiredCheckpoints: data(refs),
          snapshot: { document: data(before.document), dirty: before.dirty,
            rendererGeneration: before.rendererGeneration, stateSequence: before.stateSequence } } };
      control.assertCurrent();
      const ack = await write(receiptKey, record, null, { adopted: true });
      control.assertCurrent();
      await refresh(); control.assertCurrent();
      if (refs.some(ref => entries.get(ref.key)?.retiredBy !== receiptKey)) throw error('facility_discard_checkpoint_conflict');
      finalized = { ...ack, status: 'finalized', retired: refs.length };
      return data(finalized);
    });
    const result = await options.commitLifecycle(request, control, finalizeDiscard);
    control.assertCurrent();
    if (!finalized) throw error('facility_discard_finalization_required');
    return result;
  }

  async function lifecycleSnapshot(intentId, control, checkpoint) {
    const state = await snapshot(); control.assertCurrent();
    await refresh(); control.assertCurrent();
    if (checkpoint && state.dirty && !state.busy && !state.pendingOperations.length && !unresolved().length) {
      const record = { schemaVersion: 1, identity, document: { ...document, baseRevision: state.document.baseRevision, draftRevision: state.document.draftRevision },
        handle: { requestId: 'close_' + intentId, state: 'reconciled', phase: 'local-draft-checkpoint' },
        payload: { adapter: VERSION, type: 'draft', owner, snapshot: state } };
      control.assertCurrent();
      await write('facility_draft_' + randomUUID(), record, null, { adopted: true });
      control.assertCurrent();
      samePosition(state, await snapshot()); control.assertCurrent();
    }
    const blockers = recoveryBlockers();
    return { intentId, identity: data(identity), rendererGeneration: state.rendererGeneration, stateSequence: state.stateSequence,
      coverage: [{ workflowId: 'facility', status: 'covered' }],
      documents: [{ documentId: document.documentId, dirty: state.dirty, busy: state.busy,
        conflict: !!state.conflict, unknownOutcome: blockers.length > 0,
        discardable: !blockers.length && !state.busy && !state.pendingOperations.length }],
      pendingOperations: [...state.pendingOperations, ...unresolved().map(item => ({ key: item.envelope.key, ...item.envelope.record.handle }))],
      activeJobs: state.activeJobs,
      recovery: { status: entries.size ? 'durable' : 'none', checkpoints: [...entries.values()]
        .map(item => ({ key: item.envelope.key, checkpointId: item.envelope.checkpointId })).sort((a, b) => a.key.localeCompare(b.key)) },
    };
  }
  const lifecycle = createLifecycleCoordinator({ identity, requiredWorkflows: ['facility'], timeoutMs: options.timeoutMs ?? 5000,
    async prepare(request, control) {
      const before = await snapshot(); control.assertCurrent();
      control.runIfCurrent(() => { frozenIntent = request.intentId; });
      await editor.freeze({ intentId: request.intentId, rendererGeneration: before.rendererGeneration, stateSequence: before.stateSequence }, control);
      control.assertCurrent();
      samePosition(before, await snapshot()); control.assertCurrent();
      return lifecycleSnapshot(request.intentId, control, true);
    },
    revalidate: (request, control) => lifecycleSnapshot(request.intentId, control, false),
    async cancel(request, control) {
      control.assertCurrent();
      if (frozenIntent === request.intentId) {
        await editor.unfreeze({ intentId: request.intentId, rendererGeneration: generation }, control);
        control.runIfCurrent(() => { if (frozenIntent === request.intentId) frozenIntent = null; });
      }
      if (![...entries.values()].some(entry => entry.envelope.record.payload.type === 'draft'
          && entry.envelope.record.handle.requestId === 'close_' + request.intentId)) return;
      const current = await snapshot(); control.assertCurrent();
      for (const entry of entries.values()) {
        const record = entry.envelope.record;
        if (!entry.retiredBy && !entry.supersededBy && record.payload.type === 'draft' && record.handle.requestId === 'close_' + request.intentId
            && record.handle.state === 'reconciled' && isDeepStrictEqual(current, record.payload.snapshot)) {
          control.assertCurrent();
          await store.clear({ key: entry.envelope.key, expectedCheckpointId: entry.envelope.checkpointId });
          entries.delete(entry.envelope.key);
          control.assertCurrent();
        }
      }
    },
    commit: commitWithFinalization,
  });
  function getSaveGate() {
    return serial(async () => {
      await refresh();
      const state = await snapshot();
      const blockers = recoveryBlockers();
      if (frozenIntent) blockers.push('lifecycle_frozen');
      if (state.startupRecoveryPending === true) blockers.push('renderer_startup_recovery_pending');
      if (state.busy || state.pendingOperations.length || state.activeJobs.length || state.conflict) blockers.push('facility_unsettled');
      return { allowed: blockers.length === 0, blockers, rendererGeneration: state.rendererGeneration, stateSequence: state.stateSequence };
    });
  }
  return Object.freeze({ persistOperation, clearOperation, recover, getSaveGate,
    synchronizeRecoveryGate: () => serial(async () => { await refresh(); return synchronizeStartupGate(); }),
    async assertSaveAllowed() { const gate = await getSaveGate(); if (!gate.allowed) throw error('facility_save_blocked', gate.blockers.join(', ')); return gate; },
    async listRecovery() { await queue; await refresh(); return [...entries.values()].map(item => ({ key: item.envelope.key,
      checkpointId: item.envelope.checkpointId, document: data(item.envelope.record.document), handle: data(item.envelope.record.handle),
      type: item.envelope.record.payload.type, needsRestore: item.envelope.record.payload.type !== 'discard'
        && !item.retiredBy && !item.supersededBy && item.loaded && !item.restored,
      adopted: item.adopted, supersededBy: item.supersededBy || null, retiredBy: item.retiredBy || null })); },
    prepare: lifecycle.prepare, commit: lifecycle.commit, cancel: lifecycle.cancel, getLifecycleState: lifecycle.getState,
  });
}

module.exports = { createFacilityRecoveryAdapter, assertFacilityRuntimeAuthorization };
