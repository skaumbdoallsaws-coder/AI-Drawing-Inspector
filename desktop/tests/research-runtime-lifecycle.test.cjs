'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const main = fs.readFileSync(path.join(__dirname, '../src/runtime-main.cjs'), 'utf8');
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function fixture() {
  const suspensions = new Set(), pending = deferred(), events = [];
  const runtime = { instanceId: 'current' };
  const context = vm.createContext({
    research: { suspend(value, owner) { if (value) suspensions.add(owner); else suspensions.delete(owner); } },
    supervisor: { getState: () => ({ status: 'ready', runtime }) }, network: { enabled: true },
    lifecycle: { restart: () => pending.promise }, currentRuntime: null,
    dialog: { showMessageBox: () => pending.promise }, window: {},
    options: {}, acceptanceDecision: null, evidence: (name, result) => events.push({ name, result }),
  });
  for (const name of ['restartBackend', 'decideClose']) {
    const source = main.match(new RegExp('^async function ' + name + '\\([^]*?^\\}', 'm'));
    assert.ok(source, 'Actual runtime function exists: ' + name); vm.runInContext(source[0], context);
  }
  return { context, pending, suspensions, runtime, events };
}
for (const decision of ['cancel', 'discard']) test('native Close '+decision+' releases only its own research suspension', async () => {
  const f = fixture(); f.suspensions.add('application-overlay');
  const result = f.context.decideClose({ status: 'needsDecision' });
  assert.ok(f.suspensions.has('close-dialog'));
  f.pending.resolve({ response: decision === 'discard' ? 1 : 0 }); assert.equal(await result, decision);
  assert.deepEqual([...f.suspensions], ['application-overlay']);
});
test('failed close dialog and acceptance Cancel cannot strand the research pane', async () => {
  const f = fixture(), result = f.context.decideClose({ status: 'needsDecision' });
  f.pending.reject(new Error('dialog unavailable')); await assert.rejects(result, /dialog unavailable/);
  assert.equal(f.suspensions.size, 0);
  f.context.options.acceptanceOutput = 'isolated'; f.context.acceptanceDecision = 'cancel';
  assert.equal(await f.context.decideClose({ status: 'needsDecision' }), 'cancel'); assert.equal(f.suspensions.size, 0);
});
test('preflight restart refusal restores research without clearing another owner', async () => {
  const f = fixture(); f.suspensions.add('application-overlay');
  const result = f.context.restartBackend(); assert.ok(f.suspensions.has('backend-restart'));
  f.pending.reject(new Error('uncovered process map')); await assert.rejects(result, /uncovered process map/);
  assert.deepEqual([...f.suspensions], ['application-overlay']); assert.equal(f.context.currentRuntime, null);
});
test('successful backend reconciliation resumes research and records exact runtime', async () => {
  const f = fixture(), result = f.context.restartBackend();
  f.pending.resolve({ status: 'reconciled' }); await result;
  assert.equal(f.suspensions.size, 0); assert.equal(f.context.currentRuntime, f.runtime);
  assert.equal(f.events[0].name, 'restart-result');
});
for (const failure of ['backend-down', 'recovery-blocked']) test(failure+' retains the restart suspension', async () => {
  const f = fixture(), result = f.context.restartBackend();
  if (failure === 'backend-down') {
    f.context.supervisor.getState = () => ({ status: 'failed' }); f.pending.reject(new Error('startup failed'));
    await assert.rejects(result, /startup failed/);
  } else {
    f.context.network.enabled = false; f.pending.resolve({ status: 'recovery-required' }); await result;
  }
  assert.deepEqual([...f.suspensions], ['backend-restart']); assert.equal(f.context.currentRuntime, null);
});
