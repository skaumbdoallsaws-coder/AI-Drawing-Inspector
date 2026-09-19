'use strict';

const { randomUUID } = require('node:crypto');

function stable(value) {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort()
    .map(key => JSON.stringify(key) + ':' + stable(value[key])).join(',') + '}';
  return JSON.stringify(value);
}

function identityValid(identity) {
  return identity && ['backendId', 'storeId', 'principalId'].every(key =>
    typeof identity[key] === 'string' && identity[key].length > 0 && identity[key].length <= 256);
}

/**
 * Lifecycle protocol only. Workflow adapters own mutation quiescing and truthful
 * snapshots. No callback here saves, discards, undoes, or restores a document.
 *
 * Every callback receives (request, control). request is serializable; control
 * contains an AbortSignal and isCurrent/assertCurrent/runIfCurrent guards for
 * THIS invocation. Pass the signal to cancellable work and guard immediately
 * before every side effect, including after each await and inside deferred
 * continuations. runIfCurrent accepts only a synchronous effect: do not put an
 * await or schedule unguarded later work inside it. A guard before an await is
 * insufficient. Freeze/unfreeze ownership must also be bound to request.intentId.
 * These controls are local, not IPC data. A renderer/backend receiving a queued
 * command needs its own intent check where the actual side effect occurs;
 * checking only before dispatch does not revoke an already-dispatched command.
 *
 * Cancel revokes work authority before invoking cleanup. Cleanup receives its
 * own authority; a timed-out cleanup cannot affect a newer intent or retry.
 * Authority expires when a callback settles, times out, or is cancelled, so
 * abort listeners must not perform unguarded cleanup. The cancel callback owns
 * cleanup. Arbitrary callbacks cannot be forcibly stopped: this is a cooperative
 * contract, not a sandbox or proof that backend work has been cancelled.
 */
function createLifecycleCoordinator(options) {
  if (!options || !identityValid(options.identity)) throw new TypeError('Verified identity is required');
  for (const name of ['prepare', 'revalidate', 'cancel', 'commit']) {
    if (typeof options[name] !== 'function') throw new TypeError(name + ' callback is required');
  }
  const identity = JSON.parse(JSON.stringify(options.identity));
  const required = options.requiredWorkflows || ['application'];
  if (!Array.isArray(required) || !required.length || new Set(required).size !== required.length
      || required.some(item => typeof item !== 'string' || !item)) {
    throw new TypeError('Explicit workflow coverage is required');
  }
  const timeoutMs = options.timeoutMs ?? 5000;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000) {
    throw new TypeError('timeoutMs must be between 1 and 60000');
  }
  let active = null;

  function invalidatedError(code = 'lifecycle_intent_invalidated', message = 'Lifecycle callback authority expired') {
    return Object.assign(new Error(message), { name: 'AbortError', code });
  }

  function invalidateWork(intent, error) {
    intent.workInvalidated = true;
    for (const step of intent.steps) {
      if (step.name !== 'cancel') step.controller.abort(error);
    }
  }

  async function invoke(intent, name, extra = {}, bounded = true) {
    const phase = { prepare: 'preparing', revalidate: 'revalidating', cancel: 'cancelling', commit: 'committing' }[name];
    const step = { name, controller: new AbortController(), finished: false };
    intent.steps.add(step);
    const signal = step.controller.signal;
    const isCurrent = () => active === intent && !step.finished && !signal.aborted
      && intent.phase === phase && (name === 'cancel' || (!intent.cancelRequested && !intent.workInvalidated));
    const assertCurrent = () => {
      if (!isCurrent()) throw signal.reason || invalidatedError();
    };
    const control = Object.freeze({ signal, isCurrent, assertCurrent,
      runIfCurrent(effect) {
        if (typeof effect !== 'function') throw new TypeError('A synchronous side-effect callback is required');
        assertCurrent();
        return effect();
      } });
    const request = Object.freeze({ intentId: intent.intentId, reason: intent.reason, ...extra });
    let timer;
    let rejectOnAbort;
    const aborted = new Promise((_, reject) => {
      rejectOnAbort = () => reject(signal.reason || invalidatedError());
      signal.addEventListener('abort', rejectOnAbort, { once: true });
    });
    try {
      if (bounded) timer = setTimeout(() => {
        const error = invalidatedError('lifecycle_timeout', 'Lifecycle reply timed out');
        if (name === 'cancel') step.controller.abort(error);
        else invalidateWork(intent, error);
      }, timeoutMs);
      return await Promise.race([
        Promise.resolve().then(() => {
          assertCurrent();
          return options[name](request, control);
        }),
        aborted,
      ]);
    } finally {
      clearTimeout(timer);
      step.finished = true;
      intent.steps.delete(step);
      signal.removeEventListener('abort', rejectOnAbort);
      step.controller.abort(invalidatedError('lifecycle_callback_settled'));
    }
  }

  function inspect(snapshot, intent) {
    const blockers = [];
    if (!snapshot || snapshot.intentId !== intent.intentId
        || typeof snapshot.rendererGeneration !== 'string' || !snapshot.rendererGeneration
        || !Number.isSafeInteger(snapshot.stateSequence) || snapshot.stateSequence < 0) {
      return { blockers: ['invalid_or_stale_snapshot'], dirty: [] };
    }
    if (!identityValid(snapshot.identity) || stable(snapshot.identity) !== stable(identity)) {
      blockers.push('identity_mismatch');
    }
    const coverage = snapshot.coverage;
    if (!Array.isArray(coverage) || coverage.some(item => !item
        || !['covered', 'notApplicable'].includes(item.status))
        || new Set((coverage || []).map(item => item && item.workflowId)).size !== (coverage || []).length
        || required.some(name => !coverage?.some(item => item.workflowId === name))) {
      blockers.push('workflow_coverage_incomplete');
    }
    const documents = snapshot.documents;
    const dirty = [];
    if (!Array.isArray(documents) || documents.some(doc => !doc
        || typeof doc.documentId !== 'string' || !doc.documentId || typeof doc.dirty !== 'boolean')
        || new Set((documents || []).map(doc => doc && doc.documentId)).size !== (documents || []).length) {
      blockers.push('document_state_unknown');
    } else {
      for (const doc of documents) {
        if (doc.dirty) dirty.push(doc.documentId);
        if (doc.busy || doc.conflict || doc.unknownOutcome) blockers.push('document_unsettled:' + doc.documentId);
      }
    }
    for (const field of ['pendingOperations', 'activeJobs']) {
      if (!Array.isArray(snapshot[field]) || snapshot[field].length) blockers.push(field + '_unsettled');
    }
    if (!snapshot.recovery || !['none', 'durable'].includes(snapshot.recovery.status)) {
      blockers.push('recovery_unsettled');
    }
    return { blockers, dirty: dirty.sort() };
  }

  function result(intent, status, extra = {}) {
    return { status, intentId: intent.intentId, reason: intent.reason,
      ...(intent.snapshot ? { rendererGeneration: intent.snapshot.rendererGeneration,
        stateSequence: intent.snapshot.stateSequence } : {}), ...extra };
  }

  function prepare(reason) {
    if (!['close', 'reload', 'backendRestart'].includes(reason)) return Promise.reject(new TypeError('Unsupported lifecycle reason'));
    if (active) {
      if (active.phase === 'preparing') return active.preparation;
      return Promise.resolve(['prepared', 'blocked'].includes(active.phase) && active.result
        ? active.result : result(active, 'blocked', { blockers: ['lifecycle_in_progress'] }));
    }
    const intent = { intentId: randomUUID(), reason, phase: 'preparing', snapshot: null,
      workInvalidated: false, steps: new Set() };
    active = intent;
    intent.preparation = (async () => {
      try {
        const reply = await invoke(intent, 'prepare');
        if (active !== intent || intent.cancelRequested) return result(intent, 'cancelled');
        // Make the decision independent from later mutation of callback objects.
        intent.snapshot = JSON.parse(JSON.stringify(reply));
        const assessment = inspect(intent.snapshot, intent);
        intent.phase = 'prepared';
        intent.result = result(intent, assessment.blockers.length ? 'blocked'
          : assessment.dirty.length ? 'needsDecision' : 'ready', assessment);
      } catch (error) {
        if (active !== intent || intent.cancelRequested) return result(intent, 'cancelled');
        intent.phase = 'blocked';
        intent.result = result(intent, 'blocked', { blockers: [error.code || 'prepare_failed'] });
      }
      return intent.result;
    })();
    return intent.preparation;
  }

  async function commit(decision) {
    const intent = active;
    if (!intent || !decision || decision.intentId !== intent.intentId) {
      return { status: 'blocked', blockers: ['stale_intent'] };
    }
    if (intent.phase !== 'prepared' || intent.cancelRequested || intent.workInvalidated || !intent.snapshot
        || decision.rendererGeneration !== intent.snapshot.rendererGeneration
        || decision.stateSequence !== intent.snapshot.stateSequence) {
      return result(intent, 'blocked', { blockers: ['stale_or_unprepared_decision'] });
    }
    intent.phase = 'revalidating';
    try {
      const fresh = await invoke(intent, 'revalidate');
      if (active !== intent || intent.cancelRequested) return result(intent, 'cancelled');
      const assessment = inspect(fresh, intent);
      if (assessment.blockers.length || stable(fresh) !== stable(intent.snapshot)) {
        intent.phase = 'blocked';
        return intent.result = result(intent, 'blocked', { blockers: assessment.blockers.length
          ? assessment.blockers : ['state_changed'] });
      }
      const discards = decision.discardDocumentIds || [];
      const uniqueDiscards = Array.isArray(discards) ? [...new Set(discards)].sort() : null;
      if (!uniqueDiscards || uniqueDiscards.length !== discards.length
          || stable(uniqueDiscards) !== stable(assessment.dirty)
          || intent.snapshot.documents.some(doc => doc.dirty && doc.discardable !== true)) {
        intent.phase = 'prepared';
        return result(intent, 'needsDecision', { blockers: ['explicit_supported_discard_required'], dirty: assessment.dirty });
      }
      intent.phase = 'committing';
      // A commit callback must perform the already-authorized lifecycle action,
      // never save or replay work. Cancellation is no longer accepted at this point.
      await invoke(intent, 'commit', {
        rendererGeneration: fresh.rendererGeneration, stateSequence: fresh.stateSequence,
        discardDocumentIds: Object.freeze(uniqueDiscards) }, false);
      active = null;
      return result(intent, 'committed');
    } catch (error) {
      if (active !== intent || intent.cancelRequested) return result(intent, 'cancelled');
      intent.phase = 'blocked';
      return intent.result = result(intent, 'blocked', { blockers: [error.code || 'commit_failed'] });
    }
  }

  function cancel(intentId) {
    const intent = active;
    if (!intent || intentId !== intent.intentId) return Promise.resolve({ status: 'blocked', blockers: ['stale_intent'] });
    if (intent.phase === 'committing') return Promise.resolve(result(intent, 'blocked', { blockers: ['commit_in_progress'] }));
    if (intent.phase === 'cancelling') return intent.cancellation;
    intent.cancelRequested = true;
    intent.phase = 'cancelling';
    intent.cancellation = Promise.resolve().then(async () => {
      try {
        await invoke(intent, 'cancel');
        if (active === intent) active = null;
        return result(intent, 'cancelled');
      } catch (error) {
        intent.phase = 'blocked';
        return intent.result = result(intent, 'blocked', { blockers: [error.code || 'cancel_failed'] });
      }
    });
    // Invalidate synchronously, before cleanup can release the adapter freeze.
    // Publish the cleanup promise first so an abort listener's duplicate Cancel
    // joins the same attempt instead of starting a competing cleanup.
    invalidateWork(intent, invalidatedError('lifecycle_cancelled', 'Lifecycle intent was cancelled'));
    return intent.cancellation;
  }

  return Object.freeze({ prepare, commit, cancel,
    getState: () => active ? { intentId: active.intentId, reason: active.reason, phase: active.phase } : { phase: 'idle' } });
}

module.exports = { createLifecycleCoordinator };
