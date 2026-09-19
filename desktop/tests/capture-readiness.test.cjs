'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { createFirstPaintGate, withDeadline } = require('../tools/minimal-electron/capture-readiness.cjs');

class WindowDouble extends EventEmitter {
  destroyed = false;
  isDestroyed() { return this.destroyed; }
  close() { this.destroyed = true; this.emit('closed'); }
}
function nextTurn() { return new Promise(resolve => setImmediate(resolve)); }
function deferred() {
  let resolve, reject;
  const promise = new Promise((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}
function listenersRemoved(window) {
  assert.equal(window.listenerCount('ready-to-show'), 0);
  assert.equal(window.listenerCount('closed'), 0);
}

test('load and DOM-ready events do not substitute for first-paint evidence', async () => {
  const window = new WindowDouble();
  const gate = createFirstPaintGate(window);
  let completed = false;
  const pending = gate.wait({ timeoutMs: 1000 }).then(value => { completed = true; return value; });
  window.emit('did-finish-load'); window.emit('dom-ready');
  await nextTurn();
  assert.equal(completed, false);
  window.emit('ready-to-show');
  assert.deepEqual(await pending, { event: 'ready-to-show', observed: true });
  listenersRemoved(window);
});

test('ready-to-show before wait is latched and not missed', async () => {
  const window = new WindowDouble();
  const gate = createFirstPaintGate(window);
  window.emit('ready-to-show');
  await nextTurn();
  assert.deepEqual(await gate.wait({ timeoutMs: 10 }), { event: 'ready-to-show', observed: true });
  listenersRemoved(window);
});

test('timeout rejects with its code and removes listeners before a late paint', async () => {
  const window = new WindowDouble();
  const gate = createFirstPaintGate(window);
  const pending = gate.wait({ timeoutMs: 10 });
  await assert.rejects(pending, { code: 'first_paint_timeout' });
  listenersRemoved(window);
  window.emit('ready-to-show');
  assert.equal(gate.wait(), pending);
  await assert.rejects(pending, { code: 'first_paint_timeout' });
});

test('window closing before wait creates no eager rejection', async () => {
  const window = new WindowDouble();
  const gate = createFirstPaintGate(window);
  window.close();
  gate.dispose(); // Cleanup must retain the original startup failure reason.
  // node:test would fail this test if a rejected Promise existed before wait.
  await nextTurn();
  listenersRemoved(window);
  await assert.rejects(gate.wait(), { code: 'first_paint_window_closed' });
});

test('a closed window rejects even if paint was observed before wait', async () => {
  const window = new WindowDouble();
  const gate = createFirstPaintGate(window);
  window.emit('ready-to-show'); window.close();
  await assert.rejects(gate.wait(), { code: 'first_paint_window_closed' });
  listenersRemoved(window);
});

test('an already destroyed window rejects lazily', async () => {
  const window = new WindowDouble(); window.destroyed = true;
  const gate = createFirstPaintGate(window);
  await nextTurn();
  await assert.rejects(gate.wait(), { code: 'first_paint_window_closed' });
  listenersRemoved(window);
});

for (const event of ['close', 'dispose']) {
  test(event + ' while waiting rejects promptly and cleans up', async () => {
    const window = new WindowDouble();
    const gate = createFirstPaintGate(window);
    const pending = gate.wait({ timeoutMs: 1000 });
    if (event === 'close') window.close(); else gate.dispose();
    await assert.rejects(pending, { code: event === 'close' ? 'first_paint_window_closed' : 'first_paint_disposed' });
    listenersRemoved(window);
    gate.dispose();
  });
}

test('dispose before wait is lazy and idempotent', async () => {
  const window = new WindowDouble();
  const gate = createFirstPaintGate(window);
  gate.dispose(); gate.dispose();
  await nextTurn();
  await assert.rejects(gate.wait(), { code: 'first_paint_disposed' });
  listenersRemoved(window);
});

test('duplicate wait joins the initial bounded wait', async () => {
  const window = new WindowDouble();
  const gate = createFirstPaintGate(window);
  const first = gate.wait({ timeoutMs: 1000 });
  assert.equal(gate.wait({ timeoutMs: 1 }), first);
  window.emit('ready-to-show');
  await first; gate.dispose();
  listenersRemoved(window);
});

test('invalid deadline does not consume the latched first-paint event', async () => {
  const window = new WindowDouble();
  const gate = createFirstPaintGate(window);
  window.emit('ready-to-show');
  assert.throws(() => gate.wait({ timeoutMs: 0 }), TypeError);
  assert.equal((await gate.wait()).observed, true);
});

test('withDeadline invokes once and propagates success and callback failure', async () => {
  let calls = 0;
  assert.equal(await withDeadline(() => { calls++; return 'captured'; }, { timeoutMs: 100 }), 'captured');
  assert.equal(calls, 1);
  const failure = new Error('Capture failed');
  await assert.rejects(withDeadline(() => { throw failure; }, { timeoutMs: 100 }), error => error === failure);
  await withDeadline(() => Promise.reject(undefined), { timeoutMs: 100 }).then(
    () => assert.fail('A falsy rejection was incorrectly treated as success'),
    reason => assert.equal(reason, undefined));
});

test('withDeadline handles a late rejection without retry or an unhandled rejection', async () => {
  const callback = deferred();
  let calls = 0, controlSeen;
  const pending = withDeadline(control => { calls++; controlSeen = control; return callback.promise; },
    { timeoutMs: 10, code: 'renderer_capture_timeout' });
  await assert.rejects(pending, { code: 'renderer_capture_timeout' });
  assert.equal(controlSeen.signal.aborted, true);
  callback.reject(new Error('Late renderer rejection'));
  await nextTurn();
  assert.equal(calls, 1);
});

test('a timed-out cooperating continuation cannot advance to its next side effect', async () => {
  const release = deferred(), finished = deferred();
  let effects = 0, rejectionCode;
  const pending = withDeadline(async control => {
    await release.promise;
    try { control.assertCurrent(); effects++; }
    catch (error) { rejectionCode = error.code; }
    finally { finished.resolve(); }
    return 'late success';
  }, { timeoutMs: 10, code: 'animation_frame_timeout' });
  await assert.rejects(pending, { code: 'animation_frame_timeout' });
  release.resolve(); await finished.promise;
  assert.equal(effects, 0);
  assert.equal(rejectionCode, 'animation_frame_timeout');
  await assert.rejects(pending, { code: 'animation_frame_timeout' });
});

test('successful deadline clears its timer and expires retained callback authority', async () => {
  let retained;
  const result = await withDeadline(control => { retained = control; return 'done'; }, { timeoutMs: 10 });
  assert.equal(result, 'done');
  assert.equal(retained.isCurrent(), false);
  assert.throws(() => retained.assertCurrent(), { code: 'capture_stage_settled' });
  await nextTurn();
});
