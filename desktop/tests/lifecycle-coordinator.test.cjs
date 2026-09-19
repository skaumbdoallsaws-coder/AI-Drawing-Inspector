'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createLifecycleCoordinator } = require('../src/lifecycle-coordinator.cjs');

function fixture(overrides = {}) {
  const identity = { backendId: 'backend-a', storeId: 'store-a', principalId: 'principal-a' };
  const state = { rendererGeneration: 'renderer-one', stateSequence: 1, identity,
    coverage: [{ workflowId: 'application', status: 'covered' }], documents: [],
    pendingOperations: [], activeJobs: [], recovery: { status: 'none' } };
  let frozen = false;
  const commits = [];
  const calls = [];
  const options = { identity, timeoutMs: 30,
    prepare: async ({ intentId }, control) => { control.runIfCurrent(() => { calls.push('prepare'); frozen = true; }); return { intentId, ...structuredClone(state) }; },
    revalidate: async ({ intentId }) => { calls.push('revalidate'); return { intentId, ...structuredClone(state) }; },
    cancel: async (_request, control) => { control.runIfCurrent(() => { calls.push('cancel'); frozen = false; }); },
    commit: async (request, control) => { control.runIfCurrent(() => { calls.push('commit'); commits.push(request); }); }, ...overrides };
  const coordinator = createLifecycleCoordinator(options);
  return { state, calls, commits, coordinator, get frozen() { return frozen; } };
}

test('clean close requires fresh matching decision and never calls persistence', async () => {
  const f = fixture();
  const prepared = await f.coordinator.prepare('close');
  assert.equal(prepared.status, 'ready');
  assert.equal((await f.coordinator.commit(prepared)).status, 'committed');
  assert.deepEqual(f.calls, ['prepare', 'revalidate', 'commit']);
  assert.equal(f.commits.length, 1);
  assert.deepEqual(f.coordinator.getState(), { phase: 'idle' });
});

test('cancel preserves dirty draft/history/selection and releases freeze', async () => {
  const f = fixture();
  f.state.documents = [{ documentId: 'layout-a', dirty: true, discardable: true,
    draftRevision: 'draft-a', history: ['move', 'rotate'], selection: ['machine-a'] }];
  const before = structuredClone(f.state);
  const prepared = await f.coordinator.prepare('close');
  assert.equal(prepared.status, 'needsDecision');
  assert.equal(f.frozen, true);
  assert.equal((await f.coordinator.cancel(prepared.intentId)).status, 'cancelled');
  assert.equal(f.frozen, false);
  assert.deepEqual(f.state, before);
  assert.deepEqual(f.calls, ['prepare', 'cancel']);
});

test('discard must explicitly name the exact supported dirty drafts', async () => {
  const f = fixture();
  f.state.documents = [{ documentId: 'layout-a', dirty: true, discardable: true }];
  const prepared = await f.coordinator.prepare('reload');
  assert.equal((await f.coordinator.commit(prepared)).status, 'needsDecision');
  assert.equal(f.commits.length, 0);
  assert.equal((await f.coordinator.commit({ ...prepared, discardDocumentIds: ['layout-a'] })).status, 'committed');
  assert.equal(f.state.documents[0].dirty, true, 'Coordinator does not clear the original draft');
});

test('unsupported dirty draft cannot gain discard authority', async () => {
  const f = fixture();
  f.state.documents = [{ documentId: 'layout-a', dirty: true }];
  const prepared = await f.coordinator.prepare('close');
  assert.equal((await f.coordinator.commit({ ...prepared, discardDocumentIds: ['layout-a'] })).status, 'needsDecision');
  assert.equal(f.commits.length, 0);
});

for (const [name, mutate] of [
  ['missing adapter', state => { state.coverage = []; }],
  ['unknown adapter', state => { state.coverage[0].status = 'unknown'; }],
  ['pending Apply', state => { state.pendingOperations = [{ requestId: 'apply-one' }]; }],
  ['pending Undo despite clean document', state => { state.recovery.status = 'unresolved'; }],
  ['inspection job', state => { state.activeJobs = [{ jobId: 'inspection-one' }]; }],
  ['wrong store identity', state => { state.identity.storeId = 'other-store'; }],
  ['unknown dirty state', state => { state.documents = [{ documentId: 'fai' }]; }],
  ['clean process map still applying', state => { state.documents = [{ documentId: 'map', dirty: false, busy: true }]; }],
]) {
  test(name + ' fails closed', async () => {
    const f = fixture(); mutate(f.state);
    const prepared = await f.coordinator.prepare('close');
    assert.equal(prepared.status, 'blocked');
    assert.equal((await f.coordinator.commit(prepared)).status, 'blocked');
    assert.equal(f.commits.length, 0);
  });
}

for (const [name, mutate] of [
  ['generation', state => { state.rendererGeneration = 'renderer-two'; }],
  ['sequence', state => { state.stateSequence++; }],
  ['unreported new edit', state => { state.documents.push({ documentId: 'layout-new', dirty: true }); }],
]) {
  test('changed ' + name + ' invalidates earlier decision', async () => {
    const f = fixture(); const prepared = await f.coordinator.prepare('close'); mutate(f.state);
    assert.equal((await f.coordinator.commit(prepared)).status, 'blocked');
    assert.equal(f.commits.length, 0);
  });
}

test('duplicate close shares one intent and stale replies cannot commit it', async () => {
  const f = fixture();
  const [a, b] = await Promise.all([f.coordinator.prepare('close'), f.coordinator.prepare('close')]);
  assert.equal(a.intentId, b.intentId);
  assert.equal(f.calls.filter(call => call === 'prepare').length, 1);
  assert.equal((await f.coordinator.commit({ ...a, intentId: 'old-intent' })).status, 'blocked');
  assert.equal((await f.coordinator.commit({ ...a, stateSequence: 0 })).status, 'blocked');
  assert.equal(f.commits.length, 0);
});

test('prepare and revalidation timeouts never grant close', async () => {
  for (const phase of ['prepare', 'revalidate']) {
    const f = fixture({ [phase]: () => new Promise(() => {}) });
    const prepared = await f.coordinator.prepare('close');
    const result = phase === 'prepare' ? prepared : await f.coordinator.commit(prepared);
    assert.equal(result.status, 'blocked');
    assert.deepEqual(result.blockers, ['lifecycle_timeout']);
    assert.equal(f.commits.length, 0);
  }
});

test('cancel while a prepare reply is in flight invalidates the late reply', async () => {
  let resolveReply;
  const f = fixture({ prepare: request => new Promise(resolve => { resolveReply = () => resolve({ ...f.state, ...request }); }) });
  const preparing = f.coordinator.prepare('close');
  await Promise.resolve();
  await f.coordinator.cancel(f.coordinator.getState().intentId);
  resolveReply();
  assert.equal((await preparing).status, 'cancelled');
  assert.equal(f.commits.length, 0);
});

test('wrong response intent and cancelled coordinator reject old approval', async () => {
  const f = fixture({ prepare: async () => ({ ...f.state, intentId: 'some-other-intent' }) });
  const prepared = await f.coordinator.prepare('close');
  assert.equal(prepared.status, 'blocked');
  await f.coordinator.cancel(prepared.intentId);
  assert.equal((await f.coordinator.commit(prepared)).status, 'blocked');
});

test('cancel during revalidation invalidates its later clean reply', async () => {
  let resolveReply;
  const f = fixture({ revalidate: request => new Promise(resolve => { resolveReply = () => resolve({ ...f.state, ...request }); }) });
  const prepared = await f.coordinator.prepare('close');
  const committing = f.coordinator.commit(prepared);
  await Promise.resolve();
  await f.coordinator.cancel(prepared.intentId);
  resolveReply();
  assert.equal((await committing).status, 'cancelled');
  assert.equal(f.commits.length, 0);
});

test('failed cancellation remains blocked and a repeated close cannot reuse readiness', async () => {
  const f = fixture({ cancel: async () => { throw new Error('Cannot unfreeze adapter'); } });
  const prepared = await f.coordinator.prepare('close');
  assert.equal((await f.coordinator.cancel(prepared.intentId)).status, 'blocked');
  assert.equal((await f.coordinator.prepare('close')).status, 'blocked');
  assert.equal((await f.coordinator.commit(prepared)).status, 'blocked');
});

function deferred() {
  let resolve;
  const promise = new Promise(accept => { resolve = accept; });
  return { promise, resolve };
}

test('a cooperating prepare cannot freeze after await when Cancel already completed', async () => {
  const entered = deferred(), release = deferred(), finished = deferred();
  let freezeOwner = null, controlSeen, blockedCode;
  const f = fixture({
    prepare: async ({ intentId }, control) => {
      controlSeen = control; entered.resolve();
      await release.promise;
      try { control.runIfCurrent(() => { freezeOwner = intentId; }); }
      catch (error) { blockedCode = error.code; }
      finally { finished.resolve(); }
      return { intentId, ...structuredClone(f.state) };
    },
    cancel: async ({ intentId }, control) => {
      control.runIfCurrent(() => { if (freezeOwner === intentId) freezeOwner = null; });
    },
  });
  const before = structuredClone(f.state);
  const preparing = f.coordinator.prepare('close');
  await entered.promise;
  const intentId = f.coordinator.getState().intentId;
  assert.equal((await f.coordinator.cancel(intentId)).status, 'cancelled');
  assert.equal(controlSeen.signal.aborted, true);
  assert.equal(controlSeen.isCurrent(), false);
  assert.equal((await preparing).status, 'cancelled');
  release.resolve(); await finished.promise;
  assert.equal(blockedCode, 'lifecycle_cancelled');
  assert.equal(freezeOwner, null);
  assert.deepEqual(f.state, before);
});

test('a late prepare cannot replace a newer intent freeze', async () => {
  const entered = deferred(), release = deferred(), finished = deferred();
  let freezeOwner = null, attempts = 0, staleEffects = 0, blockedCode;
  const f = fixture({
    prepare: async ({ intentId }, control) => {
      if (++attempts === 1) {
        entered.resolve(); await release.promise;
        try { control.runIfCurrent(() => { freezeOwner = intentId; staleEffects++; }); }
        catch (error) { blockedCode = error.code; }
        finally { finished.resolve(); }
      } else control.runIfCurrent(() => { freezeOwner = intentId; });
      return { intentId, ...structuredClone(f.state) };
    },
    cancel: async ({ intentId }, control) => {
      control.runIfCurrent(() => { if (freezeOwner === intentId) freezeOwner = null; });
    },
  });
  const oldPreparing = f.coordinator.prepare('close'); await entered.promise;
  await f.coordinator.cancel(f.coordinator.getState().intentId);
  const current = await f.coordinator.prepare('close');
  assert.equal(freezeOwner, current.intentId);
  release.resolve(); await finished.promise;
  assert.equal((await oldPreparing).status, 'cancelled');
  assert.equal(blockedCode, 'lifecycle_cancelled');
  assert.equal(staleEffects, 0);
  assert.equal(freezeOwner, current.intentId);
  await f.coordinator.cancel(current.intentId);
});

test('late revalidation side effects are revoked before cancellation cleanup', async () => {
  const entered = deferred(), release = deferred(), finished = deferred();
  let effects = 0, controlSeen, blockedCode;
  const f = fixture({ revalidate: async ({ intentId }, control) => {
    controlSeen = control; entered.resolve(); await release.promise;
    try { control.assertCurrent(); effects++; }
    catch (error) { blockedCode = error.code; }
    finally { finished.resolve(); }
    return { intentId, ...structuredClone(f.state) };
  } });
  const prepared = await f.coordinator.prepare('close');
  const committing = f.coordinator.commit(prepared); await entered.promise;
  await f.coordinator.cancel(prepared.intentId);
  assert.equal(controlSeen.signal.aborted, true);
  release.resolve(); await finished.promise;
  assert.equal((await committing).status, 'cancelled');
  assert.equal(blockedCode, 'lifecycle_cancelled');
  assert.equal(effects, 0);
  assert.equal(f.commits.length, 0);
  assert.equal(f.frozen, false);
});

for (const phase of ['prepare', 'revalidate']) {
  test(phase + ' timeout revokes a cooperating late continuation without authorizing close', async () => {
    const entered = deferred(), release = deferred(), finished = deferred();
    let effects = 0, controlSeen, blockedCode;
    const f = fixture({ [phase]: async ({ intentId }, control) => {
      controlSeen = control; entered.resolve(); await release.promise;
      try { control.runIfCurrent(() => { effects++; }); }
      catch (error) { blockedCode = error.code; }
      finally { finished.resolve(); }
      return { intentId, ...structuredClone(f.state) };
    } });
    const pending = phase === 'prepare' ? f.coordinator.prepare('close')
      : f.coordinator.commit(await f.coordinator.prepare('close'));
    await entered.promise;
    const timedOut = await pending;
    assert.equal(timedOut.status, 'blocked');
    assert.deepEqual(timedOut.blockers, ['lifecycle_timeout']);
    assert.equal(controlSeen.signal.aborted, true);
    release.resolve(); await finished.promise;
    assert.equal(blockedCode, 'lifecycle_timeout');
    assert.equal(effects, 0);
    assert.equal(f.commits.length, 0);
    assert.equal((await f.coordinator.prepare('close')).status, 'blocked');
    await f.coordinator.cancel(timedOut.intentId);
  });
}

test('timed-out cleanup cannot release a newer intent after a successful cleanup retry', async () => {
  const entered = deferred(), release = deferred(), finished = deferred();
  let freezeOwner = null, cancelAttempts = 0, lateEffects = 0, blockedCode;
  const f = fixture({
    prepare: async ({ intentId }, control) => {
      control.runIfCurrent(() => { freezeOwner = intentId; });
      return { intentId, ...structuredClone(f.state) };
    },
    cancel: async ({ intentId }, control) => {
      if (++cancelAttempts === 1) {
        entered.resolve(); await release.promise;
        try { control.runIfCurrent(() => { lateEffects++; if (freezeOwner === intentId) freezeOwner = null; }); }
        catch (error) { blockedCode = error.code; }
        finally { finished.resolve(); }
      } else control.runIfCurrent(() => { if (freezeOwner === intentId) freezeOwner = null; });
    },
  });
  const original = await f.coordinator.prepare('close');
  const cancelling = f.coordinator.cancel(original.intentId); await entered.promise;
  assert.equal((await cancelling).status, 'blocked');
  assert.equal(freezeOwner, original.intentId, 'Failed cleanup does not pretend the freeze was released');
  assert.equal((await f.coordinator.cancel(original.intentId)).status, 'cancelled');
  const current = await f.coordinator.prepare('close');
  release.resolve(); await finished.promise;
  assert.equal(blockedCode, 'lifecycle_timeout');
  assert.equal(lateEffects, 0);
  assert.equal(freezeOwner, current.intentId);
  await f.coordinator.cancel(current.intentId);
});

test('duplicate and abort-listener cancellation share one cleanup invocation', async () => {
  const entered = deferred(), cleanupEntered = deferred(), releaseCleanup = deferred();
  let reentrantCancel, cleanups = 0;
  const f = fixture({
    prepare: async ({ intentId }, control) => {
      control.signal.addEventListener('abort', () => { reentrantCancel = f.coordinator.cancel(intentId); }, { once: true });
      entered.resolve(); await new Promise(() => {});
    },
    cancel: async (_request, control) => {
      cleanups++; cleanupEntered.resolve(); await releaseCleanup.promise;
      control.assertCurrent();
    },
  });
  const preparing = f.coordinator.prepare('close'); await entered.promise;
  const intentId = f.coordinator.getState().intentId;
  const first = f.coordinator.cancel(intentId);
  const duplicate = f.coordinator.cancel(intentId);
  assert.equal(first, duplicate);
  assert.equal(first, reentrantCancel);
  assert.equal((await f.coordinator.prepare('close')).status, 'blocked');
  await cleanupEntered.promise; releaseCleanup.resolve();
  assert.equal((await first).status, 'cancelled');
  assert.equal((await preparing).status, 'cancelled');
  assert.equal(cleanups, 1);
});

test('settled callback guards expire and control stays separate from the serializable request', async () => {
  let retained, requestKeys;
  const f = fixture({ prepare: async (request, control) => {
    retained = control; requestKeys = Object.keys(request);
    control.assertCurrent();
    return { intentId: request.intentId, ...structuredClone(f.state) };
  } });
  const prepared = await f.coordinator.prepare('close');
  assert.deepEqual(requestKeys.sort(), ['intentId', 'reason']);
  assert.equal(retained.signal.aborted, true);
  assert.equal(retained.isCurrent(), false);
  assert.throws(() => retained.runIfCurrent(() => assert.fail('Expired callback executed a side effect')),
    { code: 'lifecycle_callback_settled' });
  assert.equal(prepared.status, 'ready');
  await f.coordinator.cancel(prepared.intentId);
});
