'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { commitRuntimeWindow } = require('../src/runtime-window-commit.cjs');
function fixture() {
  const events = [], cleanup = { terminationConfirmed: true, stdioClosed: true, resourcesClosed: true };
  const options = { request: { reason: 'close' }, control: { assertCurrent() {} },
    stop: async () => { events.push('stop'); return cleanup; }, finalizeDiscard: async () => { events.push('finalize'); },
    close: async () => { events.push('destroy'); }, replace: async () => { events.push('reload'); } };
  return { events, cleanup, options };
}
test('close verifies backend cleanup before durable discard and renderer destruction', async () => {
  const f = fixture(); assert.equal((await commitRuntimeWindow(f.options)).status, 'closed'); assert.deepEqual(f.events, ['stop','finalize','destroy']);
});
for (const field of ['terminationConfirmed','stdioClosed','resourcesClosed']) test('failed '+field+' retains renderer and checkpoint', async () => {
  const f = fixture(); f.cleanup[field] = false; await assert.rejects(commitRuntimeWindow(f.options), { code: 'desktop_cleanup_unverified' }); assert.deepEqual(f.events, ['stop']);
});
test('failed durable discard retains renderer even after backend cleanup', async () => {
  const f = fixture(); f.options.finalizeDiscard = async () => { throw new Error('disk checkpoint conflict'); };
  await assert.rejects(commitRuntimeWindow(f.options), /checkpoint conflict/); assert.deepEqual(f.events, ['stop']);
});
test('reload retires explicitly discarded state before replacing renderer without stopping backend', async () => {
  const f = fixture(); f.options.request.reason = 'reload'; await commitRuntimeWindow(f.options); assert.deepEqual(f.events, ['finalize','reload']);
});
test('expired close intent cannot finalize or destroy after asynchronous cleanup', async () => {
  const f = fixture(); let current = true; f.options.control.assertCurrent = () => { if (!current) throw new Error('expired'); };
  f.options.stop = async () => { current = false; return f.cleanup; };
  await assert.rejects(commitRuntimeWindow(f.options), /expired/); assert.deepEqual(f.events, []);
});
