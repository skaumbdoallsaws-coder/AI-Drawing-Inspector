'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { createRecoveryStore } = require('../src/recovery-store.cjs');

const identity = { backendId: 'backend-a', storeId: 'store-a', principalId: 'principal-a' };
const windowsOnly = { skip: process.platform !== 'win32' && 'Windows replacement retry policy' };
const key = 'pending_undo';
const secret = 'DO-NOT-LOG-PRIVATE-DRAFT-OR-ACCESS-TOKEN';
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
function record(phase = 'undo-prepare-pending') {
  return {
    schemaVersion: 1, identity: { ...identity },
    document: { tenantId: 'tenant-a', siteId: 'site-a', documentId: 'layout-a', baseRevision: 'base-a', draftRevision: 'draft-a' },
    handle: { requestId: 'request-a', transactionId: 'transaction-a', phase, state: 'pending' },
    payload: { draft: secret, selection: ['machine-a'], history: ['edit-1', 'edit-2', 'apply'] },
  };
}
function injected(code) {
  return Object.assign(new Error('Injected replacement failure: ' + secret), { code, errno: -4048, syscall: 'rename' });
}
async function fixture(t, onDiagnostic) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'inspectorpro-replacement-test-'));
  t.after(async () => {
    t.mock.restoreAll();
    const resolved = path.resolve(directory);
    assert.equal(path.dirname(resolved), path.resolve(os.tmpdir()));
    assert.ok(path.basename(resolved).startsWith('inspectorpro-replacement-test-'));
    await fs.rm(resolved, { recursive: true, force: true });
  });
  const events = [];
  const store = await createRecoveryStore({ directory, identity, onDiagnostic(event) {
    events.push(event);
    return onDiagnostic?.(event);
  } });
  const previous = await store.write({ key, record: record() });
  const target = path.join(directory, sha256(key) + '.json');
  const previousBytes = await fs.readFile(target);
  return { directory, store, target, previous, previousBytes, events,
    replace: () => store.write({ key, record: record('undo-prepare-received'), expectedCheckpointId: previous.checkpointId }) };
}
async function previousRetained(f) {
  assert.deepEqual(await fs.readFile(f.target), f.previousBytes);
  assert.equal((await f.store.read(key)).checkpointId, f.previous.checkpointId);
  assert.equal((await fs.readdir(f.directory)).some(name => name.endsWith('.tmp')), false);
}
function failureEvent(f) {
  const event = f.events.findLast(item => item.event === 'checkpoint-write-failed');
  assert.ok(event);
  assert.equal(event.acknowledged, false);
  assert.equal(JSON.stringify(f.events).includes(secret), false, 'Diagnostics must not include payload or error-message secrets');
  return event;
}

for (const code of ['EPERM', 'EACCES', 'EBUSY']) {
  test('Windows ' + code + ' retries one flushed, closed candidate without an early acknowledgment', windowsOnly, async t => {
    const f = await fixture(t);
    const realOpen = fs.open;
    const realRename = fs.rename;
    const handles = new Map();
    const attempts = [];
    let acknowledged = false;
    t.mock.method(fs, 'open', async (...args) => {
      const handle = await realOpen(...args);
      if (!String(args[0]).endsWith('.tmp')) return handle;
      const state = { syncs: 0, closes: 0 };
      handles.set(String(args[0]), state);
      return {
        writeFile: (...values) => handle.writeFile(...values),
        sync: async () => { await handle.sync(); state.syncs += 1; },
        close: async () => { await handle.close(); state.closes += 1; },
      };
    });
    t.mock.method(fs, 'rename', async (temporary, target) => {
      assert.equal(target, f.target);
      assert.equal(acknowledged, false);
      assert.deepEqual(handles.get(temporary), { syncs: 1, closes: 1 });
      assert.deepEqual(await fs.readFile(target), f.previousBytes);
      attempts.push({ temporary, bytes: await fs.readFile(temporary) });
      if (attempts.length < 3) throw injected(code);
      return realRename(temporary, target);
    });
    const ack = await f.replace().then(value => { acknowledged = true; return value; });
    assert.equal(ack.acknowledged, true);
    assert.equal(attempts.length, 3);
    assert.equal(handles.size, 1);
    assert.equal(new Set(attempts.map(item => item.temporary)).size, 1);
    for (const attempt of attempts) assert.deepEqual(attempt.bytes, attempts[0].bytes);
    const candidate = JSON.parse(attempts[0].bytes);
    assert.equal(ack.checkpointId, candidate.checkpointId);
    assert.notEqual(ack.checkpointId, f.previous.checkpointId);
    assert.deepEqual(await fs.readFile(f.target), attempts[0].bytes);
    assert.equal((await f.store.read(key)).record.handle.phase, 'undo-prepare-received');
    assert.equal(f.events.filter(event => event.event === 'replacement-attempt-failed').length, 2);
    assert.equal(f.events.some(event => event.event === 'checkpoint-write-failed'), false);
    const succeeded = f.events.find(event => event.event === 'replacement-retry-succeeded');
    assert.equal(succeeded.targetState, 'candidate-checkpoint');
    assert.equal(succeeded.observedTargetSha256, sha256(attempts[0].bytes));
    assert.equal(JSON.stringify(f.events).includes(secret), false);
  });
}

test('permanent Windows replacement rejection is bounded and preserves exact previous bytes and ID', windowsOnly, async t => {
  const f = await fixture(t);
  const attempts = [];
  t.mock.method(fs, 'rename', async temporary => {
    attempts.push({ temporary, bytes: await fs.readFile(temporary) });
    throw injected('EPERM');
  });
  await assert.rejects(f.replace(), error => {
    assert.equal(error.code, 'EPERM');
    assert.equal(error.recoveryReplacement.targetState, 'previous-checkpoint');
    assert.equal(error.recoveryReplacement.replaced, false);
    assert.equal(error.recoveryReplacement.priorCheckpointId, f.previous.checkpointId);
    return true;
  });
  assert.ok(attempts.length >= 2 && attempts.length <= 6, 'The retry policy must have a finite attempt bound');
  assert.equal(new Set(attempts.map(item => item.temporary)).size, 1);
  for (const attempt of attempts) assert.deepEqual(attempt.bytes, attempts[0].bytes);
  const delays = f.events.filter(item => item.event === 'replacement-attempt-failed')
    .flatMap(item => item.failures.slice(-1)).filter(item => item.retryDelayMs !== null);
  assert.ok(delays.every(item => item.retryDelayMs > 0 && item.elapsedMs + item.retryDelayMs <= 1000));
  const event = failureEvent(f);
  assert.equal(event.attempts, attempts.length);
  assert.equal(event.targetState, 'previous-checkpoint');
  assert.equal(event.observedTargetSha256, sha256(f.previousBytes));
  assert.equal(event.temporaryCleanup, 'removed');
  await previousRetained(f);
});

test('a nonretryable rename error rejects immediately without consuming or changing the previous checkpoint', async t => {
  const f = await fixture(t);
  let attempts = 0;
  t.mock.method(fs, 'rename', async () => { attempts += 1; throw injected('EIO'); });
  await assert.rejects(f.replace(), { code: 'EIO' });
  assert.equal(attempts, 1);
  assert.equal(f.events.find(event => event.event === 'replacement-attempt-failed').willRetry, false);
  assert.equal(failureEvent(f).targetState, 'previous-checkpoint');
  await previousRetained(f);
});

for (const mutation of ['changed', 'deleted']) {
  test('a target ' + mutation + ' between Windows retry attempts is not overwritten', windowsOnly, async t => {
    const f = await fixture(t);
    const outside = JSON.parse(f.previousBytes);
    // Keep the same checkpoint ID: exact bytes, not ID alone, must protect the target.
    outside.record.payload.selection = ['another-writer-selection'];
    const outsideBytes = Buffer.from(JSON.stringify(outside));
    let attempts = 0;
    t.mock.method(fs, 'rename', async () => {
      attempts += 1;
      if (mutation === 'changed') await fs.writeFile(f.target, outsideBytes);
      else await fs.unlink(f.target);
      throw injected('EBUSY');
    });
    await assert.rejects(f.replace(), { code: 'recovery_checkpoint_conflict' });
    assert.equal(attempts, 1, 'A detected target change must stop before another replacement attempt');
    const event = failureEvent(f);
    assert.equal(event.targetState, mutation === 'changed' ? 'different-checkpoint' : 'missing');
    assert.equal(event.replaced, false);
    if (mutation === 'changed') assert.deepEqual(await fs.readFile(f.target), outsideBytes);
    else assert.equal(await f.store.read(key), null);
    assert.equal((await fs.readdir(f.directory)).some(name => name.endsWith('.tmp')), false);
  });
}

test('a queued checkpoint cannot overtake a Windows replacement that is retrying', { ...windowsOnly, timeout: 10000 }, async t => {
  const f = await fixture(t);
  const realRename = fs.rename;
  let notifyRetry;
  const retryReached = new Promise(resolve => { notifyRetry = resolve; });
  let releaseRetry;
  const allowRetry = new Promise(resolve => { releaseRetry = resolve; });
  t.after(() => releaseRetry());
  const order = [];
  let firstAttempts = 0;
  let firstCompleted = false;
  let secondCompleted = false;
  t.mock.method(fs, 'rename', async (temporary, target) => {
    if (target === f.target) {
      firstAttempts += 1;
      if (firstAttempts === 1) throw injected('EPERM');
      notifyRetry();
      await allowRetry;
      order.push('first-replaced');
    } else {
      assert.equal(firstCompleted, true, 'The second write must remain behind the first acknowledgment');
      order.push('second-replaced');
    }
    return realRename(temporary, target);
  });
  const first = f.replace().then(value => { firstCompleted = true; return value; });
  const second = f.store.write({ key: 'other_operation', record: record() })
    .then(value => { secondCompleted = true; return value; });
  try {
    await retryReached;
    assert.equal(firstCompleted, false);
    assert.equal(secondCompleted, false);
    assert.deepEqual(order, []);
    assert.equal((await fs.readdir(f.directory)).filter(name => name.endsWith('.tmp')).length, 1);
  } finally { releaseRetry(); }
  const [firstAck, secondAck] = await Promise.all([first, second]);
  assert.equal(firstAck.acknowledged, true);
  assert.equal(secondAck.acknowledged, true);
  assert.deepEqual(order, ['first-replaced', 'second-replaced']);
});

for (const observerFailure of ['throw', 'reject']) {
  const observer = () => {
    if (observerFailure === 'throw') throw new Error('diagnostic observer failed');
    return Promise.reject(new Error('diagnostic observer failed'));
  };
  test('a diagnostic observer that ' + observerFailure + 's cannot turn a successful retry into failure', windowsOnly, async t => {
    const f = await fixture(t, observer);
    const realRename = fs.rename;
    let attempts = 0;
    t.mock.method(fs, 'rename', async (...args) => {
      attempts += 1;
      if (attempts === 1) throw injected('EACCES');
      return realRename(...args);
    });
    const ack = await f.replace();
    assert.equal(ack.acknowledged, true);
    assert.equal((await f.store.read(key)).checkpointId, ack.checkpointId);
    assert.equal(attempts, 2);
    assert.equal(JSON.stringify(f.events).includes(secret), false);
    await new Promise(resolve => setImmediate(resolve));
  });
  test('a diagnostic observer that ' + observerFailure + 's preserves the original failed-write result', async t => {
    const f = await fixture(t, observer);
    t.mock.method(fs, 'rename', async () => { throw injected('EIO'); });
    await assert.rejects(f.replace(), { code: 'EIO' });
    assert.equal(failureEvent(f).targetState, 'previous-checkpoint');
    await previousRetained(f);
    await new Promise(resolve => setImmediate(resolve));
  });
}

test('unreadable target diagnostics do not claim that the previous checkpoint was observed', windowsOnly, async t => {
  const f = await fixture(t);
  const realReadFile = fs.readFile;
  let targetUnreadable = false;
  let attempts = 0;
  t.mock.method(fs, 'readFile', async (file, ...args) => {
    if (targetUnreadable && String(file) === f.target) throw Object.assign(new Error('Injected read denial'), { code: 'EACCES' });
    return realReadFile(file, ...args);
  });
  t.mock.method(fs, 'rename', async () => {
    attempts += 1;
    targetUnreadable = true;
    throw injected('EPERM');
  });
  await assert.rejects(f.replace(), { code: 'EACCES' });
  assert.equal(attempts, 1);
  const event = failureEvent(f);
  assert.equal(event.targetState, 'unreadable');
  assert.equal(event.observationError, 'EACCES');
  assert.equal(event.observedTargetSha256, undefined);
  assert.equal(event.replaced, false);
  // The test's unmocked read proves retention; the failing operation could not observe it.
  assert.deepEqual(await realReadFile(f.target), f.previousBytes);
});

test('post-rename directory-sync failure reports the candidate on disk without acknowledging durability', async t => {
  const f = await fixture(t);
  const realOpen = fs.open;
  const platformDescriptor = Object.getOwnPropertyDescriptor(process, 'platform');
  let directoryClosed = false;
  let failed;
  // Exercise the POSIX directory-sync branch even on the Windows development host.
  // The file write and atomic rename remain real; only directory fsync is injected.
  Object.defineProperty(process, 'platform', { ...platformDescriptor, value: 'linux' });
  try {
    t.mock.method(fs, 'open', async (...args) => {
      if (String(args[0]) === f.directory && args[1] === 'r') return {
        sync: async () => { throw Object.assign(new Error('Injected directory fsync failure'), { code: 'EIO' }); },
        close: async () => { directoryClosed = true; },
      };
      return realOpen(...args);
    });
    await assert.rejects(f.replace(), error => { failed = error; return error.code === 'EIO'; });
  } finally { Object.defineProperty(process, 'platform', platformDescriptor); }
  assert.equal(directoryClosed, true);
  const event = failureEvent(f);
  assert.equal(event.targetState, 'candidate-checkpoint');
  assert.equal(event.replaced, true);
  assert.equal(event.stage, 'directory-sync');
  assert.equal(event.temporaryCleanup, 'absent');
  const retained = await f.store.read(key);
  assert.equal(retained.checkpointId, event.candidateCheckpointId);
  assert.notEqual(retained.checkpointId, f.previous.checkpointId);
  assert.equal(event.observedTargetSha256, sha256(await fs.readFile(f.target)));
  assert.deepEqual(failed.recoveryReplacement, event);
});
