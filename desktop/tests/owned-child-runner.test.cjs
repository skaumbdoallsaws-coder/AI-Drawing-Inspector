'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { runOwnedChild } = require('../tools/owned-child-runner.cjs');

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function fixture(t) {
  const parent = path.resolve(os.tmpdir());
  const root = await fs.mkdtemp(path.join(parent, 'ip-owned-child-'));
  t.after(async () => {
    // Only remove the exact temporary directory created for this test.
    assert.equal(path.dirname(path.resolve(root)), parent);
    assert.ok(path.basename(root).startsWith('ip-owned-child-'));
    await fs.rm(root, { recursive: true, force: true });
  });
  return { logPath: path.join(root, 'child.log'), root };
}
class FakeChild extends EventEmitter {
  constructor(pid = 12345) {
    super(); this.pid = pid; this.stdout = new PassThrough(); this.stderr = new PassThrough();
    this.signals = []; this.unrefCalled = false;
  }
  kill(signal) { this.signals.push(signal); return this.onKill ? this.onKill(signal) : true; }
  unref() { this.unrefCalled = true; }
}
function startFake(logPath, child, options = {}) {
  return runOwnedChild({ executable: 'owned-test-process', logPath, timeoutMs: 1000,
    terminationGraceMs: 20, forceKillGraceMs: 20, drainGraceMs: 60,
    spawnImpl: () => child, ...options });
}

test('synchronous spawn throw still leaves persistent failure diagnostics', async t => {
  const { logPath } = await fixture(t);
  const result = await startFake(logPath, null, { spawnImpl: () => { throw new Error('bad launch'); } });
  assert.equal(result.status, 'spawn-error'); assert.equal(result.ok, false);
  assert.equal(result.terminationConfirmed, true); assert.equal(result.stdioClosed, true);
  assert.match(await fs.readFile(logPath, 'utf8'), /Spawn threw: bad launch/);
});

test('asynchronous spawn failure waits for close and retains the final stderr', async t => {
  const { logPath } = await fixture(t); const child = new FakeChild(undefined); child.pid = undefined;
  let settled = false;
  const pending = startFake(logPath, child).then(result => { settled = true; return result; });
  child.emit('error', new Error('ENOENT fixture executable'));
  child.stderr.write('loader diagnostic after error\n');
  await pause(10); assert.equal(settled, false);
  child.emit('close', -2, null);
  const result = await pending;
  assert.equal(result.status, 'spawn-error'); assert.equal(result.terminationConfirmed, true);
  assert.match(await fs.readFile(logPath, 'utf8'), /loader diagnostic after error/);
});

test('exit is not completion: wait for close and drain trailing output', async t => {
  const { logPath } = await fixture(t); const child = new FakeChild(); let settled = false;
  const pending = startFake(logPath, child).then(result => { settled = true; return result; });
  child.stdout.write('before exit\n'); child.emit('exit', 7, null);
  await pause(10); assert.equal(settled, false);
  child.stderr.write('last buffered stderr\n'); child.emit('close', 7, null);
  const result = await pending;
  assert.equal(result.ok, false); assert.equal(result.code, 7); assert.equal(result.stdioClosed, true);
  assert.match(await fs.readFile(logPath, 'utf8'), /last buffered stderr/);
  assert.deepEqual(child.signals, []);
});

test('timeout retains diagnostics emitted after SIGTERM and before close', async t => {
  const { logPath } = await fixture(t); const child = new FakeChild(); let emittedFinal = false;
  child.onKill = signal => {
    assert.equal(signal, 'SIGTERM');
    child.stderr.write('graceful termination requested\n'); child.emit('exit', null, 'SIGTERM');
    setTimeout(() => { emittedFinal = true; child.stderr.write('shutdown cleanup complete\n'); child.emit('close', null, 'SIGTERM'); }, 10);
    return true;
  };
  const result = await startFake(logPath, child, { timeoutMs: 10 });
  assert.equal(result.status, 'timed-out'); assert.equal(result.ok, false);
  assert.equal(result.terminationConfirmed, true); assert.equal(result.stdioClosed, true);
  assert.equal(emittedFinal, true); assert.deepEqual(child.signals, ['SIGTERM']);
  assert.match(await fs.readFile(logPath, 'utf8'), /shutdown cleanup complete/);
});

test('timeout escalates only the owned child and confirms forced close', async t => {
  const { logPath } = await fixture(t); const child = new FakeChild();
  child.onKill = signal => {
    if (signal === 'SIGKILL') setTimeout(() => {
      child.stderr.write('forced shutdown diagnostic\n'); child.emit('exit', null, signal); child.emit('close', null, signal);
    }, 5);
    return true;
  };
  const result = await startFake(logPath, child, { timeoutMs: 10 });
  assert.equal(result.status, 'timed-out'); assert.equal(result.terminationConfirmed, true);
  assert.deepEqual(child.signals, ['SIGTERM', 'SIGKILL']);
  assert.match(await fs.readFile(logPath, 'utf8'), /forced shutdown diagnostic/);
});

test('exhausted termination deadline reports uncertainty and preserves pid', async t => {
  const { logPath } = await fixture(t); const child = new FakeChild();
  child.onKill = () => false;
  const result = await startFake(logPath, child, { timeoutMs: 10 });
  assert.equal(result.status, 'termination-unconfirmed'); assert.equal(result.terminationConfirmed, false);
  assert.equal(result.stdioClosed, false); assert.equal(result.pid, child.pid); assert.equal(result.ok, false);
  assert.equal(child.unrefCalled, true); assert.deepEqual(child.signals, ['SIGTERM', 'SIGKILL']);
  assert.match(await fs.readFile(logPath, 'utf8'), /terminationConfirmed=false/);
});

test('known exit with inherited open pipes reports unconfirmed drain', async t => {
  const { logPath } = await fixture(t); const child = new FakeChild();
  const pending = startFake(logPath, child, { drainGraceMs: 10 });
  child.emit('exit', 0, null);
  const result = await pending;
  assert.equal(result.status, 'stdio-unconfirmed'); assert.equal(result.terminationConfirmed, true);
  assert.equal(result.stdioClosed, false); assert.equal(result.ok, false); assert.deepEqual(child.signals, []);
});

test('failed signal attempts remain failure evidence and cannot imply termination', async t => {
  const { logPath } = await fixture(t); const child = new FakeChild();
  child.onKill = () => { throw new Error('signal refused'); };
  const result = await startFake(logPath, child, { timeoutMs: 10 });
  assert.equal(result.status, 'termination-unconfirmed');
  assert.match(await fs.readFile(logPath, 'utf8'), /SIGTERM failed.*signal refused/);
  assert.match(await fs.readFile(logPath, 'utf8'), /SIGKILL failed.*signal refused/);
});

test('stdio read errors initiate owned cleanup and persist the error', async t => {
  const { logPath } = await fixture(t); const child = new FakeChild();
  child.onKill = signal => { setImmediate(() => { child.emit('exit', null, signal); child.emit('close', null, signal); }); return true; };
  const pending = startFake(logPath, child);
  child.stderr.emit('error', new Error('pipe broken'));
  const result = await pending;
  assert.equal(result.status, 'process-error'); assert.equal(result.terminationConfirmed, true);
  assert.match(await fs.readFile(logPath, 'utf8'), /stderr read failed: pipe broken/);
});

test('bounded output keeps failure tail and lifecycle markers', async t => {
  const { logPath } = await fixture(t); const child = new FakeChild();
  const pending = startFake(logPath, child, { maxLogBytes: 1024 });
  child.stdout.write('x'.repeat(4000) + '\nfinal relevant diagnostic\n'); child.emit('exit', 1, null); child.emit('close', 1, null);
  const result = await pending;
  assert.equal(result.outputTruncated, true); assert.match(result.diagnostics, /final relevant diagnostic/);
  const log = await fs.readFile(logPath, 'utf8');
  assert.match(log, /Output exceeds 1024 bytes/); assert.match(log, /final relevant diagnostic/);
});

test('real Node output and owned pid are observable on disk before child exit', async t => {
  const { logPath } = await fixture(t); let settled = false;
  const pending = runOwnedChild({ executable: process.execPath,
    args: ['-e', "process.stdout.write('RUNNING_NOW\\n');setTimeout(()=>{process.stderr.write('FINAL_STDERR\\n');process.exitCode=7;},1200)"],
    logPath, timeoutMs: 5000 }).then(result => { settled = true; return result; });
  const deadline = Date.now() + 4000; let log = '';
  while (!log.includes('RUNNING_NOW') && Date.now() < deadline) { log = await fs.readFile(logPath, 'utf8'); if (!log.includes('RUNNING_NOW')) await pause(10); }
  assert.match(log, /RUNNING_NOW/); assert.match(log, /Spawn returned owned pid=\d+/); assert.equal(settled, false);
  const result = await pending;
  assert.equal(result.ok, false); assert.equal(result.code, 7); assert.equal(result.terminationConfirmed, true);
  assert.equal(result.stdioClosed, true); assert.match(await fs.readFile(logPath, 'utf8'), /FINAL_STDERR/);
});

test('real Node timeout waits for owned process close before returning', async t => {
  const { logPath } = await fixture(t);
  const result = await runOwnedChild({ executable: process.execPath,
    args: ['-e', "process.stderr.write('STILL_RUNNING\\n');setInterval(()=>{},1000)"],
    logPath, timeoutMs: 500, terminationGraceMs: 1000, forceKillGraceMs: 1000 });
  assert.equal(result.status, 'timed-out'); assert.equal(result.terminationConfirmed, true);
  assert.equal(result.stdioClosed, true); assert.equal(result.ok, false);
  assert.match(await fs.readFile(logPath, 'utf8'), /STILL_RUNNING/);
});

test('real missing executable records asynchronous launch failure', async t => {
  const { logPath, root } = await fixture(t);
  const result = await runOwnedChild({ executable: path.join(root, 'missing-executable'), logPath });
  assert.equal(result.status, 'spawn-error'); assert.equal(result.ok, false);
  assert.equal(result.terminationConfirmed, true); assert.equal(result.stdioClosed, true);
  assert.match(await fs.readFile(logPath, 'utf8'), /ENOENT/);
});
