'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { setImmediate: nextTurn } = require('node:timers/promises');
const { closeRenderingPreview } = require('../tools/close-rendering-preview.cjs');

class Preview extends EventEmitter {
  destroyed = false;
  isDestroyed() { return this.destroyed; }
  finishClose() { this.destroyed = true; this.emit('closed'); }
}

test('committed decision waits for a later closed event before succeeding', async () => {
  const window = new Preview();
  const decision = { status: 'committed', intentId: 'one-close' };
  let calls = 0, completed = false;
  const running = closeRenderingPreview({ window, requestClose: async () => { calls++; return decision; } });
  running.then(() => { completed = true; });
  await nextTurn();
  assert.equal(calls, 1);
  assert.equal(completed, false);
  assert.equal(window.listenerCount('closed'), 1);
  window.finishClose();
  assert.equal(await running, decision);
  assert.equal(window.listenerCount('closed'), 0);
});

test('closed event before commit resolves is retained but does not authorize a pass alone', async () => {
  const window = new Preview();
  let commit, completed = false;
  const running = closeRenderingPreview({ window, requestClose: () => {
    assert.equal(window.listenerCount('closed'), 1);
    window.finishClose();
    return new Promise(resolve => { commit = resolve; });
  } });
  running.then(() => { completed = true; });
  await nextTurn();
  assert.equal(completed, false);
  commit({ status: 'committed' });
  assert.equal((await running).status, 'committed');
  assert.equal(window.listenerCount('closed'), 0);
});

test('blocked decision fails without closing or quitting the window', async () => {
  const window = new Preview();
  let calls = 0;
  window.close = window.destroy = window.quit = () => assert.fail('Helper must not take lifecycle actions');
  await assert.rejects(closeRenderingPreview({ window, requestClose: async () => {
    calls++; return { status: 'blocked', blockers: ['unknown-state'] };
  } }), { code: 'lifecycle_close_not_committed' });
  assert.equal(calls, 1);
  assert.equal(window.isDestroyed(), false);
  assert.equal(window.listenerCount('closed'), 0);
});

test('request error propagates and releases its listener', async () => {
  const window = new Preview();
  const error = new Error('Lifecycle adapter failed');
  await assert.rejects(closeRenderingPreview({ window, requestClose: () => { throw error; } }), value => value === error);
  assert.equal(window.listenerCount('closed'), 0);
});

test('a rejection without an Error object remains a failure', async () => {
  const window = new Preview();
  await assert.rejects(closeRenderingPreview({ window, requestClose: () => Promise.reject(undefined) }), value => value === undefined);
  assert.equal(window.listenerCount('closed'), 0);
});

test('timeout while waiting for closed releases the listener and does not retry', async () => {
  const window = new Preview();
  let calls = 0;
  await assert.rejects(closeRenderingPreview({ window, timeoutMs: 20, requestClose: async () => {
    calls++; return { status: 'committed' };
  } }), { code: 'lifecycle_close_timeout' });
  assert.equal(calls, 1);
  assert.equal(window.listenerCount('closed'), 0);
  window.finishClose();
});

test('overall deadline also bounds a pending commit and observes its late rejection', async () => {
  const window = new Preview();
  let rejectCommit;
  await assert.rejects(closeRenderingPreview({ window, timeoutMs: 20, requestClose: () => {
    window.finishClose();
    return new Promise((_resolve, reject) => { rejectCommit = reject; });
  } }), { code: 'lifecycle_close_timeout' });
  assert.equal(window.listenerCount('closed'), 0);
  rejectCommit(new Error('Late lifecycle failure'));
  await nextTurn();
});

test('closed event without destroyed state cannot pass', async () => {
  const window = new Preview();
  await assert.rejects(closeRenderingPreview({ window, requestClose: () => {
    window.emit('closed');
    return { status: 'committed' };
  } }), { code: 'lifecycle_close_not_destroyed' });
  assert.equal(window.listenerCount('closed'), 0);
});

test('an already destroyed preview does not authorize another close', async () => {
  const window = new Preview(); window.finishClose();
  await assert.rejects(closeRenderingPreview({ window, requestClose: () => assert.fail('Must not dispatch') }),
    { code: 'lifecycle_close_already_destroyed' });
  assert.equal(window.listenerCount('closed'), 0);
});

test('destruction before the scheduled close callback cannot authorize another close', async () => {
  const window = new Preview();
  const running = closeRenderingPreview({ window, requestClose: () => assert.fail('Must not dispatch') });
  window.finishClose();
  await assert.rejects(running, { code: 'lifecycle_close_already_destroyed' });
  assert.equal(window.listenerCount('closed'), 0);
});

test('invalid bounded-close arguments fail before dispatch', async () => {
  for (const timeoutMs of [0, -1, 1.5, 60001, Infinity]) {
    await assert.rejects(closeRenderingPreview({ window: new Preview(), requestClose: () => assert.fail('Must not dispatch'), timeoutMs }), TypeError);
  }
  await assert.rejects(closeRenderingPreview({}), TypeError);
  await assert.rejects(closeRenderingPreview({ window: new Preview() }), TypeError);
});
