'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { verifyRestart } = require('../tools/application-generation-check.cjs');
const before = [{ instanceId: 'original', runtime: {} }];
const ready = { instanceId: 'replacement', runtime: {}, failure: null };
function runtime(latest = ready, state = { status: 'ready', instanceId: 'replacement' }) {
  return { getEvidence: () => [...before, latest], getState: () => state };
}
test('acceptance requires a verified new ready backend after restart', () => {
  assert.deepEqual(verifyRestart(runtime(), before), [...before, ready]);
});
test('restart crash is reported before Undo, even when UI transition resolves', () => {
  const failed = { ...ready, runtime: null, failure: { code: 'desktop_backend_early_exit' } };
  assert.throws(() => verifyRestart(runtime(failed, { status: 'failed' }), before),
    { code: 'desktop_backend_early_exit', message: 'Backend restart failed: desktop_backend_early_exit' });
});
test('starting, interrupted, wrong identity and unverified backends cannot pass restart', () => {
  for (const state of [{ status: 'starting' }, { status: 'interrupted' }, { status: 'ready', instanceId: 'other' }]) {
    assert.throws(() => verifyRestart(runtime(ready, state), before));
  }
  assert.throws(() => verifyRestart(runtime({ ...ready, runtime: null }), before));
});
test('cancelled restart and reused instance cannot pass acceptance', () => {
  assert.throws(() => verifyRestart({ getEvidence: () => before }, before));
  assert.throws(() => verifyRestart(runtime({ ...ready, instanceId: 'original' }), before));
});
