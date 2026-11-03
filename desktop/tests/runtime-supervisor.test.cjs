'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { PassThrough, Writable } = require('node:stream');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createManagedRuntime } = require('../src/runtime-supervisor.cjs');

const turn = () => new Promise(resolve => setImmediate(resolve));

test('expired restart cannot launch another backend after owned cleanup settles', async t => {
  const f = fixture(t);
  await f.supervisor.start();
  const controller = new AbortController();
  const restarting = f.supervisor.restart({ signal: controller.signal });
  const stopping = f.supervisor.stop();
  controller.abort(new Error('restart deadline expired'));
  await assert.rejects(restarting, /restart deadline expired/);
  const cleanup = await stopping;
  assert.equal(f.launches.length, 1);
  assert.equal(cleanup.terminationConfirmed, true);
  assert.equal(cleanup.resourcesClosed, true);
  assert.deepEqual(f.children[0].kills, []);
  assert.deepEqual(f.supervisor.getEvidence()[0].cleanup, cleanup);
});

for (const stage of ['read', 'cleanup']) for (const cancelBy of ['restart deadline', 'stop']) {
  test(cancelBy + ' cancels replacement startup stalled in reader ' + stage, { timeout: 3000 }, async t => {
    let cancelStarted, releaseCancel;
    const cancelling = new Promise(resolve => { cancelStarted = resolve; });
    const cancelled = new Promise(resolve => { releaseCancel = resolve; });
    const f = fixture(t, [{}, { ignoreShutdown: true }], { fetch: async (_url, _options, child, runtime) => {
      if (child.pid === f.children[0].pid) return new Response(JSON.stringify(runtime));
      let read = false;
      return { ok: true, body: { getReader: () => ({
        read: async () => {
          if (stage === 'read') { cancelStarted(); await cancelled; }
          return read ? { done: true } : (read = true, { value: Buffer.from(JSON.stringify(runtime)), done: false });
        },
        cancel: () => { cancelStarted(); return cancelled; },
      }) } };
    } });
    await f.supervisor.start();
    const controller = new AbortController();
    const restarting = f.supervisor.restart({ signal: controller.signal });
    const rejected = assert.rejects(restarting, cancelBy === 'stop'
      ? { code: 'desktop_startup_cancelled' } : /restart deadline expired/);
    await cancelling;
    assert.equal(f.children.length, 2, 'cancel only after the replacement child has started');
    if (cancelBy === 'restart deadline') controller.abort(new Error('restart deadline expired'));
    const cleanup = await f.supervisor.stop();
    await rejected;
    assert.equal(f.requests[1].options.signal.aborted, true);
    assert.equal(cleanup.processId, f.children[1].pid);
    assert.equal(cleanup.terminationConfirmed, true);
    assert.equal(cleanup.forced, true);
    assert.equal(cleanup.resourcesClosed, false);
    assert.equal(f.children[1].controls.filter(value => value.command === 'shutdown').length, 1);
    assert.deepEqual(f.children[0].kills, []);
    assert.deepEqual(f.children[1].kills, ['SIGKILL']);
    assert.deepEqual(f.supervisor.getEvidence()[1].cleanup, cleanup);
    const saved = JSON.parse(fs.readFileSync(path.join(f.root, 'desktop-logs', cleanup.instanceId + '-process.json')));
    assert.deepEqual(saved, cleanup);
    releaseCancel(); await turn();
    assert.equal(f.supervisor.getState().status, 'cleanup-failed');
    assert.equal(f.supervisor.getCredential(), null);
    assert.equal(f.states.filter(state => state === 'ready').length, 1, 'late cleanup cannot authorize the replacement');
  });
}

test('startup request deadline bounds response cleanup without an explicit stop', { timeout: 3000 }, async t => {
  const f = fixture(t, [{}], { options: { startupTimeoutMs: 80 }, fetch: async () => ({
    ok: true, body: { getReader: () => ({
      read: async () => ({ done: true }), cancel: () => new Promise(() => {}),
    }) },
  }) });
  // AbortSignal.timeout is unref'ed; the fake transport has no live socket.
  const keepAlive = setTimeout(() => {}, 3000);
  try { await assert.rejects(f.supervisor.start(), { name: 'TimeoutError' }); }
  finally { clearTimeout(keepAlive); }
  assert.equal(f.children[0].ended, true);
  assert.equal(f.supervisor.getEvidence()[0].cleanup.resourcesClosed, true);
  assert.equal(f.supervisor.getState().status, 'failed');
});

function fixture(t, plans = [{}], overrides = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ip-supervisor-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const profile = { schemaVersion: 1, mode: 'managed', profileId: 'supervisor-unit', origin: 'http://127.0.0.1:8198',
    dataRoot: root, profileFile: path.join(root, 'profile.json'),
    backendId: 'e777e777-7777-4777-8777-777777777777', storeId: 'd888d888-8888-4888-8888-888888888888',
    acceptanceLayoutId: 'fl-isolated' };
  fs.writeFileSync(profile.profileFile, JSON.stringify(profile));
  const children = [], launches = [], requests = [], states = [];
  function runtime(child) {
    return { schemaVersion: 1, product: 'InspectorPro', mode: 'desktop-managed', profileId: profile.profileId,
      origin: profile.origin, instanceId: child.bootstrap.instanceId, processId: child.pid, storeBinding: 'b'.repeat(64),
      identity: { backendId: profile.backendId, storeId: profile.storeId, principalId: 'principal-local' },
      owner: { sessionId: 'session-stable', ownerId: 'owner-stable' },
      document: { tenantId: 'local', siteId: 'site-local', documentId: profile.acceptanceLayoutId },
      capabilities: { generalEditing: false, researchBrowsing: false, facilityAcceptance: true },
      ...child.plan.runtime };
  }
  function spawn(executable, args, options) {
    const plan = plans[children.length] || {};
    launches.push({ executable, args, options });
    if (plan.spawnError) throw Object.assign(new Error('fake executable unavailable'), { code: 'ENOENT' });
    const child = new EventEmitter();
    Object.assign(child, { pid: 43000 + children.length, stdout: new PassThrough(), stderr: new PassThrough(),
      plan, controls: [], kills: [], ended: false });
    const emit = (kind, value) => child.stdout.write('INSPECTORPRO_DESKTOP_RUNTIME_' + kind + ' ' + JSON.stringify(value) + '\n');
    child.checkpoint = value => emit('CHECKPOINT', { schemaVersion: 1, processId: child.pid,
      instanceId: child.bootstrap.instanceId, ...value });
    child.finish = (code = 0) => {
      if (child.ended) return;
      child.ended = true;
      child.emit('exit', code);
      child.stdout.end(); child.stderr.end();
      if (!plan.noCloseEvent) child.emit('close', code);
    };
    child.ready = () => emit('READY', { ...runtime(child), ...plan.ready });
    child.kill = signal => { child.kills.push(signal); child.finish(1); return true; };
    child.unref = () => { child.unreferenced = true; };
    child.stdin = new Writable({ write(bytes, _encoding, done) {
      let value;
      try { value = JSON.parse(bytes.toString()); } catch (error) { done(error); return; }
      child.controls.push(value);
      done();
      queueMicrotask(() => {
        if (!child.bootstrap) {
          child.bootstrap = value;
          for (const checkpoint of plan.checkpoints || []) child.checkpoint(checkpoint);
          if (plan.echoCredential === 'split-streams') {
            child.stderr.write('stderr credential: ' + value.credential.slice(0, 31));
            child.stdout.write('stdout credential: ' + value.credential.slice(0, 19));
            child.stderr.write(value.credential.slice(31) + '\n');
            child.stdout.write(value.credential.slice(19) + '\n');
          } else if (plan.echoCredential === 'bytewise') {
            child.stderr.write('bytewise credential: ');
            for (const character of value.credential) child.stderr.write(character);
            child.stderr.write('\n');
          } else if (plan.echoCredential) child.stderr.write('diagnostic accidental credential: ' + value.credential + '\n');
          if (!plan.noReady) child.ready();
        } else if (value.command === 'shutdown' && !plan.ignoreShutdown) {
          if (!plan.noReceipt) emit('SHUTDOWN', { schemaVersion: 1, instanceId: child.bootstrap.instanceId,
            processId: child.pid, requestId: value.requestId, resourcesClosed: true, ...plan.shutdown });
          child.finish(plan.exitCode || 0);
        }
      });
    } });
    children.push(child);
    return child;
  }
  async function fetchImpl(url, options) {
    requests.push({ url, options });
    const child = children.find(item => item.bootstrap?.credential === options.headers['X-InspectorPro-Desktop-Token']);
    assert.ok(child, 'HTTP authority must identify one privately bootstrapped owned child');
    if (overrides.fetch) return overrides.fetch(url, options, child, runtime(child));
    return new Response(JSON.stringify(runtime(child)), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }
  const supervisor = createManagedRuntime({ profile, python: path.join(root, 'python.exe'), appRoot: root,
    startupTimeoutMs: 500, stopTimeoutMs: 50, forceTimeoutMs: 50, spawnImpl: spawn, fetchImpl,
    onState: state => states.push(state.status), ...overrides.options });
  return { supervisor, profile, root, children, launches, requests, states, runtime };
}

test('concurrent start owns one child and confines launch authority to private stdin and exact runtime HTTP', async t => {
  const f = fixture(t, [{ echoCredential: true }]);
  const first = f.supervisor.start(), second = f.supervisor.start();
  assert.equal(first, second);
  const value = await first;
  assert.equal(f.launches.length, 1);
  const child = f.children[0], launch = f.launches[0];
  assert.deepEqual(Object.keys(child.bootstrap).sort(), ['credential', 'instanceId', 'schemaVersion']);
  assert.match(child.bootstrap.credential, /^[a-f0-9]{64}$/);
  assert.equal(value.processId, child.pid);
  assert.equal(value.instanceId, child.bootstrap.instanceId);
  assert.equal(launch.options.shell, false); assert.equal(launch.options.windowsHide, true);
  assert.deepEqual(launch.options.stdio, ['pipe', 'pipe', 'pipe']);
  assert.equal(launch.args.includes(child.bootstrap.credential), false);
  assert.equal(JSON.stringify(launch.options.env).includes(child.bootstrap.credential), false);
  assert.deepEqual(launch.args, ['-u', path.join(f.root, 'desktop', 'runtime', 'managed_backend.py'), '--profile-file', f.profile.profileFile]);
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].url, f.profile.origin + '/api/desktop-shell/runtime');
  assert.equal(f.requests[0].options.redirect, 'error');
  assert.equal(f.requests[0].options.headers['X-InspectorPro-Desktop-Token'], child.bootstrap.credential);
  const log = fs.readFileSync(f.supervisor.getState().logPath, 'utf8');
  assert.equal(log.includes(child.bootstrap.credential), false);
  assert.match(log, /\[redacted\]/);
  const timings = f.supervisor.getEvidence()[0].timings;
  for (const key of ['spawnReturnedElapsedMs', 'startControlSentElapsedMs',
    'firstStdoutElapsedMs', 'firstStderrElapsedMs', 'maximumLogWriteMs']) {
    assert.equal(Number.isSafeInteger(timings[key]), true, key); assert.ok(timings[key] >= 0, key);
  }
  assert.ok(timings.spawnReturnedElapsedMs <= timings.startControlSentElapsedMs);
  assert.ok(timings.startControlSentElapsedMs <= timings.firstStdoutElapsedMs);
  assert.ok(timings.firstStdoutElapsedMs <= timings.readyObservedElapsedMs);
  const receipt = await f.supervisor.stop();
  assert.equal(receipt.resourcesClosed, true); assert.equal(receipt.terminationConfirmed, true); assert.equal(receipt.stdioClosed, true);
  assert.equal(receipt.shutdown.requestId, child.controls[1].requestId);
  assert.deepEqual(child.kills, []);
  assert.equal(f.supervisor.getCredential(), null);
});

test('private READY mismatch never sends a credential to the advertised port', async t => {
  for (const ready of [{ processId: 99999 }, { origin: 'http://127.0.0.1:8999' }, { instanceId: 'foreign-instance' }]) {
    await t.test(JSON.stringify(ready), async sub => {
      const f = fixture(sub, [{ ready }]);
      await assert.rejects(f.supervisor.start(), error => ['desktop_owned_ready_mismatch', 'desktop_private_channel_identity_mismatch'].includes(error.code));
      assert.equal(f.requests.length, 0);
      assert.equal(f.children[0].ended, true);
      assert.equal(f.supervisor.getState().status, 'failed');
      assert.equal(f.supervisor.getCredential(), null);
    });
  }
});

test('credential redaction survives interleaved arbitrary stdout and stderr chunks', async t => {
  for (const echoCredential of ['split-streams', 'bytewise']) {
    await t.test(echoCredential, async sub => {
      const f = fixture(sub, [{ echoCredential }]);
      await f.supervisor.start();
      const credential = f.children[0].bootstrap.credential;
      await f.supervisor.stop();
      const log = fs.readFileSync(f.supervisor.getState().logPath, 'utf8');
      assert.equal(log.includes(credential), false);
      assert.equal(log.includes(credential.slice(0, 19)), false);
      assert.equal(log.includes(credential.slice(31)), false);
      assert.match(log, /credential: \[redacted\]/);
      assert.match(log, /INSPECTORPRO_DESKTOP_RUNTIME_SHUTDOWN/);
    });
  }
});

test('authenticated runtime binding mismatch is rejected and its owned child is shut down', async t => {
  const f = fixture(t, [{ runtime: { document: { tenantId: 'local', siteId: 'site-local', documentId: 'fl-foreign' } } }]);
  await assert.rejects(f.supervisor.start(), { code: 'desktop_runtime_document_mismatch' });
  assert.equal(f.requests.length, 1);
  assert.equal(f.children[0].controls[1].command, 'shutdown');
  assert.equal(f.children[0].ended, true);
  assert.equal(f.supervisor.getCredential(), null);
});

test('shutdown waits for an owned matching receipt and reuses cleanup on repeated stop', async t => {
  const f = fixture(t);
  await f.supervisor.start();
  const first = f.supervisor.stop(), concurrent = f.supervisor.stop();
  assert.equal(first, concurrent);
  const stopped = await first;
  assert.equal(stopped.resourcesClosed, true);
  assert.equal(stopped.forced, false);
  assert.equal(stopped.shutdown.instanceId, f.children[0].bootstrap.instanceId);
  assert.equal(stopped.processId, f.children[0].pid);
  assert.equal(f.supervisor.getState().status, 'stopped');
  assert.deepEqual(await f.supervisor.stop(), stopped);
  assert.equal(f.children[0].controls.length, 2);
});

test('closed process without valid resource receipt is failed cleanup and cannot restart', async t => {
  for (const plan of [{ noReceipt: true }, { shutdown: { resourcesClosed: false } }, { shutdown: { requestId: 'foreign-request' } }]) {
    await t.test(JSON.stringify(plan), async sub => {
      const f = fixture(sub, [plan]);
      await f.supervisor.start();
      const stopped = await f.supervisor.stop();
      assert.equal(stopped.terminationConfirmed, true); assert.equal(stopped.stdioClosed, true);
      assert.equal(stopped.resourcesClosed, false);
      assert.equal(f.supervisor.getState().status, 'cleanup-failed');
      await assert.rejects(f.supervisor.restart(), { code: 'desktop_cleanup_unverified' });
      assert.equal(f.children.length, 1);
      assert.equal(f.supervisor.getCredential(), null);
    });
  }
});

test('failed graceful stop only kills its directly owned child and retains failure diagnostics', async t => {
  const f = fixture(t, [{ ignoreShutdown: true }]);
  await f.supervisor.start();
  const stopped = await f.supervisor.stop();
  assert.deepEqual(f.children[0].kills, ['SIGKILL']);
  assert.equal(stopped.forced, true); assert.equal(stopped.resourcesClosed, false);
  assert.equal(stopped.terminationConfirmed, true); assert.equal(stopped.stdioClosed, true);
  assert.equal(f.launches.length, 1);
  const saved = JSON.parse(fs.readFileSync(path.join(f.root, 'desktop-logs', stopped.instanceId + '-process.json')));
  assert.equal(saved.forced, true); assert.equal(saved.resourcesClosed, false);
  assert.equal(fs.existsSync(stopped.logPath), true);
});

test('process exit without child close does not claim diagnostic stream closure', async t => {
  const f = fixture(t, [{ noCloseEvent: true }]);
  await f.supervisor.start();
  const stopped = await f.supervisor.stop();
  assert.equal(stopped.terminationConfirmed, true);
  assert.equal(stopped.stdioClosed, false);
  assert.equal(stopped.resourcesClosed, true);
  assert.equal(stopped.forced, false);
  assert.equal(f.supervisor.getState().status, 'cleanup-failed');
  assert.equal(f.children[0].unreferenced, true);
  assert.deepEqual(f.children[0].kills, []);
  await assert.rejects(f.supervisor.restart(), { code: 'desktop_cleanup_unverified' });
  assert.equal(f.children.length, 1);
});

test('a response body finishing after its owned process exits is rejected as stale', async t => {
  let releaseBody, bodyStarted;
  const started = new Promise(resolve => { bodyStarted = resolve; });
  const f = fixture(t, [{}], { fetch: async (url, _options, child, runtime) => {
    if (url.endsWith('/api/desktop-shell/runtime')) return new Response(JSON.stringify(runtime));
    return new Response(new ReadableStream({ start(controller) {
      releaseBody = () => { controller.enqueue(Buffer.from('{"late":true}')); controller.close(); };
      bodyStarted();
    } }));
  } });
  await f.supervisor.start();
  const pending = f.supervisor.request('/api/desktop-shell/recovery/transaction', { requestId: 'stale-test' });
  const rejected = assert.rejects(pending, { code: 'desktop_backend_changed' });
  await started;
  await turn();
  f.children[0].finish(1);
  releaseBody();
  await rejected;
  assert.equal(f.supervisor.getState().status, 'interrupted');
  assert.equal(f.supervisor.getCredential(), null);
  await f.supervisor.stop();
});

test('restart changes process instance and credential while preserving identity, owner, store and document', async t => {
  const f = fixture(t, [{}, {}]);
  const before = await f.supervisor.start();
  const after = await f.supervisor.restart();
  assert.notEqual(after.instanceId, before.instanceId); assert.notEqual(after.processId, before.processId);
  assert.notEqual(f.children[0].bootstrap.credential, f.children[1].bootstrap.credential);
  for (const field of ['identity', 'owner', 'document', 'storeBinding']) assert.deepEqual(after[field], before[field]);
  assert.equal(f.children[0].ended, true); assert.equal(f.children[1].ended, false);
  assert.deepEqual(f.children[0].kills, []);
  assert.equal(f.requests.length, 2);
  assert.equal(f.supervisor.getEvidence()[0].cleanup.resourcesClosed, true);
  await f.supervisor.stop();
});

test('new instance with changed stable owner cannot regain backend authority', async t => {
  const f = fixture(t, [{}, { runtime: { owner: { sessionId: 'session-other', ownerId: 'owner-other' } } }]);
  await f.supervisor.start();
  await assert.rejects(f.supervisor.restart(), { code: 'desktop_restarted_store_mismatch' });
  assert.equal(f.children.length, 2); assert.equal(f.children.every(child => child.ended), true);
  assert.equal(f.supervisor.getCredential(), null);
  assert.equal(f.supervisor.getState().status, 'failed');
  assert.equal(f.supervisor.getEvidence()[1].failure.code, 'desktop_restarted_store_mismatch');
});

test('startup timeout never probes an unready port and retains owned process cleanup', async t => {
  const f = fixture(t, [{ noReady: true }], { options: { startupTimeoutMs: 60 } });
  await assert.rejects(f.supervisor.start(), { code: 'desktop_backend_startup_timeout' });
  assert.equal(f.requests.length, 0);
  assert.equal(f.children[0].ended, true);
  assert.equal(f.supervisor.getEvidence()[0].cleanup.terminationConfirmed, true);
  assert.equal(fs.existsSync(f.supervisor.getEvidence()[0].logPath), true);
});

test('stop during startup cancels the one launch without sending HTTP credentials', async t => {
  const f = fixture(t, [{ noReady: true }]);
  const starting = f.supervisor.start();
  const rejected = assert.rejects(starting, { code: 'desktop_startup_cancelled' });
  const cleanup = await f.supervisor.stop();
  await rejected;
  assert.equal(cleanup.terminationConfirmed, true);
  assert.equal(f.children.length, 1); assert.equal(f.requests.length, 0);
  assert.equal(f.supervisor.getCredential(), null);
});

test('synchronous spawn failure persists diagnostics without claiming resource shutdown', async t => {
  const f = fixture(t, [{ spawnError: true }]);
  await assert.rejects(f.supervisor.start(), { code: 'ENOENT' });
  const record = f.supervisor.getEvidence()[0];
  assert.equal(record.cleanup.terminationConfirmed, true); assert.equal(record.cleanup.stdioClosed, true);
  assert.equal(record.cleanup.resourcesClosed, false);
  assert.equal(record.processId, null);
  assert.equal(f.requests.length, 0); assert.equal(f.children.length, 0);
  assert.equal(fs.existsSync(record.logPath), true);
});

test('startup import diagnostics are explicit, boolean, and alter only interpreter flags', async t => {
  assert.throws(() => fixture(t, [{}], { options: { startupDiagnostics: 'true' } }), { code: 'desktop_diagnostics_option_invalid' });
  const ordinary = fixture(t), enabled = fixture(t, [{}], { options: { startupDiagnostics: true } });
  await ordinary.supervisor.start(); await enabled.supervisor.start();
  assert.equal(ordinary.launches[0].args.includes('-X'), false);
  assert.deepEqual(enabled.launches[0].args, ['-u', '-X', 'importtime', path.join(enabled.root, 'desktop/runtime/managed_backend.py'),
    '--profile-file', enabled.profile.profileFile]);
  assert.deepEqual(Object.keys(enabled.launches[0].options.env).sort(), Object.keys(ordinary.launches[0].options.env).sort());
  assert.equal(Object.hasOwn(enabled.launches[0].options.env, 'PYTHONPROFILEIMPORTTIME'), false);
  assert.equal(enabled.launches[0].options.windowsHide, true); assert.equal(enabled.launches[0].options.shell, false);
  assert.equal(ordinary.supervisor.getEvidence()[0].startupDiagnosticsEnabled, false);
  assert.equal(ordinary.supervisor.getEvidence()[0].diagnosticsFiles, null);
  assert.equal(enabled.supervisor.getEvidence()[0].startupDiagnosticsEnabled, true);
  await ordinary.supervisor.stop(); await enabled.supervisor.stop();
});

test('owned fixed checkpoint timings are projected without unrelated record content', async t => {
  const f = fixture(t, [{ checkpoints: [{ phase: 'profile-validation' }, { phase: 'application-import', sequence: 2,
    elapsedMs: 123.5, previousPhase: 'uvicorn-import', previousPhaseDurationMs: 12.75 }] }]);
  await f.supervisor.start();
  const child = f.children[0];
  child.checkpoint({ phase: 'application-ready', sequence: 3, elapsedMs: 156.75, previousPhase: 'application-import',
    previousPhaseDurationMs: 33.25, credential: child.bootstrap.credential, arbitraryPayload: { draft: 'must-not-project' } });
  const records = f.supervisor.getEvidence()[0].startupCheckpoints.records;
  assert.equal(records.length, 3);
  assert.equal(records[0].elapsedMs, null); assert.equal(records[0].sequence, null);
  assert.equal(records[1].elapsedMs, 123.5); assert.equal(records[1].previousPhaseDurationMs, 12.75);
  assert.equal(records[2].phase, 'application-ready'); assert.equal(records[2].sequence, 3);
  assert.equal(records[2].processId, child.pid); assert.equal(records[2].instanceId, child.bootstrap.instanceId);
  assert.ok(records.every(item => Number.isSafeInteger(item.observedElapsedMs) && item.observedElapsedMs >= 0));
  assert.equal(JSON.stringify(records).includes('must-not-project'), false);
  assert.equal(JSON.stringify(records).includes(child.bootstrap.credential), false);
  records[0].phase = 'changed-by-reader';
  assert.equal(f.supervisor.getEvidence()[0].startupCheckpoints.records[0].phase, 'profile-validation');
  await f.supervisor.stop();
});

test('foreign malformed and bounded checkpoint streams cannot replace startup authority', async t => {
  const f = fixture(t);
  await f.supervisor.start();
  const child = f.children[0];
  child.stdout.write('INSPECTORPRO_DESKTOP_RUNTIME_CHECKPOINT {invalid-json\n');
  child.checkpoint({ phase: 'not a fixed phase' });
  child.checkpoint({ phase: 'application-import', elapsedMs: -1 });
  child.checkpoint({ phase: 'application-import', sequence: 0 });
  child.checkpoint({ phase: 'application-import', processId: child.pid + 1 });
  child.checkpoint({ phase: 'application-import', instanceId: 'foreign-instance' });
  for (let index = 0; index < 80; index++) child.checkpoint({ phase: 'phase-' + index, sequence: index + 1, elapsedMs: index });
  const summary = f.supervisor.getEvidence()[0].startupCheckpoints;
  assert.equal(summary.invalidCount, 4); assert.equal(summary.foreignCount, 2);
  assert.equal(summary.records.length, 64); assert.equal(summary.truncatedCount, 16);
  assert.equal(summary.lastPhase, 'phase-79'); assert.equal(summary.records[0].phase, 'phase-16');
  assert.equal(f.supervisor.getState().status, 'ready');
  assert.equal(f.requests.length, 1);
  await f.supervisor.stop();
});

test('ready-named checkpoint cannot satisfy readiness and failure timing excludes forced cleanup', async t => {
  const f = fixture(t, [{ noReady: true, ignoreShutdown: true, checkpoints: [{ phase: 'application-ready', sequence: 1, elapsedMs: 1 }] }],
    { options: { startupTimeoutMs: 60, startupDiagnostics: true } });
  await assert.rejects(f.supervisor.start(), { code: 'desktop_backend_startup_timeout' });
  const record = f.supervisor.getEvidence()[0];
  assert.equal(f.requests.length, 0); assert.equal(record.startupCheckpoints.lastPhase, 'application-ready');
  assert.equal(record.cleanup.forced, true); assert.equal(record.cleanup.resourcesClosed, false);
  assert.equal(record.startupElapsedMs, record.timings.failureElapsedMs);
  assert.ok(record.timings.failureElapsedMs <= record.timings.shutdownRequestedElapsedMs);
  assert.ok(record.timings.shutdownRequestedElapsedMs < record.timings.processExitElapsedMs);
  assert.ok(record.timings.processExitElapsedMs <= record.timings.stdioClosedElapsedMs);
  assert.equal(record.timings.readyObservedElapsedMs, undefined);
  assert.equal(record.timings.runtimeVerifiedElapsedMs, undefined);
  await turn(); assert.equal(f.supervisor.getEvidence()[0].startupElapsedMs, record.startupElapsedMs);
});

test('diagnostic references require actual regular files and matching metadata without changing authority', async t => {
  const f = fixture(t, [{}], { options: { startupDiagnostics: true } });
  await f.supervisor.start();
  let record = f.supervisor.getEvidence()[0];
  assert.equal(record.diagnosticsFiles.stacks.exists, false);
  assert.equal(record.diagnosticsFiles.stacks.baselinePresent, false);
  assert.equal(record.diagnosticsFiles.imports.exists, false); assert.equal(record.diagnosticsFiles.imports.metadataValid, false);
  const { stacks, imports } = record.diagnosticsFiles;
  assert.equal(stacks.path, path.join(f.root, 'desktop-logs', record.instanceId + '-import-stacks.log'));
  assert.equal(imports.path, path.join(f.root, 'desktop-logs', record.instanceId + '-import-diagnostics.json'));
  fs.mkdirSync(stacks.path);
  fs.writeFileSync(imports.path, '{partial');
  assert.equal(f.supervisor.getEvidence()[0].diagnosticsFiles.stacks.exists, false);
  assert.equal(f.supervisor.getEvidence()[0].diagnosticsFiles.imports.metadataValid, false);
  fs.rmdirSync(stacks.path); fs.writeFileSync(stacks.path, 'fixed thread stacks; no locals');
  assert.equal(f.supervisor.getEvidence()[0].diagnosticsFiles.stacks.baselinePresent, false);
  const baseline = 'InspectorPro import stack baseline (no locals or source)\n';
  fs.writeFileSync(stacks.path, baseline);
  assert.equal(f.supervisor.getEvidence()[0].diagnosticsFiles.stacks.baselinePresent, false);
  fs.appendFileSync(stacks.path, 'Current thread 0x0000:\n  File "managed_backend.py", line 12 in bind\n');
  assert.equal(f.supervisor.getEvidence()[0].diagnosticsFiles.stacks.baselinePresent, true);
  fs.writeFileSync(imports.path, JSON.stringify({ schemaVersion: 1, instanceId: record.instanceId, processId: record.processId + 1 }));
  assert.equal(f.supervisor.getEvidence()[0].diagnosticsFiles.imports.metadataValid, false);
  fs.writeFileSync(imports.path, JSON.stringify({ schemaVersion: 1, instanceId: record.instanceId, processId: record.processId }));
  assert.equal(f.supervisor.getEvidence()[0].diagnosticsFiles.imports.metadataValid, false);
  fs.writeFileSync(imports.path, JSON.stringify({ schemaVersion: 1, instanceId: record.instanceId, processId: record.processId,
    mode: 'cpython-importtime-with-bounded-stacks', importTimeEnabled: false }));
  assert.equal(f.supervisor.getEvidence()[0].diagnosticsFiles.imports.metadataValid, false);
  fs.writeFileSync(imports.path, JSON.stringify({ schemaVersion: 1, instanceId: record.instanceId, processId: record.processId,
    mode: 'cpython-importtime-with-bounded-stacks', importTimeEnabled: true, unknown: f.children[0].bootstrap.credential }));
  record = f.supervisor.getEvidence()[0];
  assert.equal(record.diagnosticsFiles.stacks.exists, true); assert.equal(record.diagnosticsFiles.imports.exists, true);
  assert.ok(record.diagnosticsFiles.stacks.sizeBytes > baseline.length);
  assert.equal(record.diagnosticsFiles.imports.metadataValid, true);
  assert.equal(JSON.stringify(record).includes(f.children[0].bootstrap.credential), false);
  assert.equal(f.supervisor.getState().status, 'ready');
  assert.equal(record.startupElapsedMs, record.timings.runtimeVerifiedElapsedMs);
  assert.ok(record.timings.readyObservedElapsedMs <= record.timings.runtimeVerifiedElapsedMs);
  await f.supervisor.stop();
});

test('owned bounded diagnostic errors are observations and do not override readiness or cleanup', async t => {
  const f = fixture(t, [{}], { options: { startupDiagnostics: true } });
  await f.supervisor.start();
  const child = f.children[0];
  const emit = value => child.stdout.write('INSPECTORPRO_DESKTOP_RUNTIME_DIAGNOSTIC_ERROR ' + JSON.stringify({
    schemaVersion: 1, processId: child.pid, instanceId: child.bootstrap.instanceId, operation: 'bind', errorType: 'OSError', ...value }) + '\n');
  emit({ instanceId: null, operation: 'start', extra: child.bootstrap.credential });
  assert.equal(f.supervisor.getEvidence()[0].diagnosticErrors[0].instanceId, null);
  emit({ instanceId: null });
  emit({ processId: child.pid + 1 });
  emit({ instanceId: 'foreign-instance' });
  emit({ errorType: 'arbitrary exception text is not a class' });
  for (let index = 0; index < 20; index++) emit({ operation: index % 2 ? 'capture-shutdown' : 'stop' });
  const record = f.supervisor.getEvidence()[0];
  assert.equal(record.diagnosticErrors.length, 16);
  assert.deepEqual(record.diagnosticErrorCounts, { invalidCount: 2, foreignCount: 2, truncatedCount: 5 });
  assert.equal(record.diagnosticErrors.every(value => value.processId === child.pid && value.instanceId === child.bootstrap.instanceId), true);
  assert.equal(JSON.stringify(record.diagnosticErrors).includes(child.bootstrap.credential), false);
  assert.equal(f.supervisor.getState().status, 'ready');
  assert.equal((await f.supervisor.stop()).resourcesClosed, true);
});

test('import timing counts only completed numeric stderr records across arbitrary chunks', async t => {
  const f = fixture(t, [{}], { options: { startupDiagnostics: true } });
  await f.supervisor.start();
  const child = f.children[0];
  child.stderr.write('import time: self [us] | cumulative | imported package\n');
  child.stderr.write('import time:     cached | cached | module\n');
  child.stdout.write('import time:         9 |          9 | not_stderr\n');
  assert.equal(f.supervisor.getEvidence()[0].importTimingLines, 0);
  for (const character of 'import time:       123 |        456 |   package.module') child.stderr.write(character);
  assert.equal(f.supervisor.getEvidence()[0].importTimingLines, 0);
  child.stderr.write('\r\n');
  assert.equal(f.supervisor.getEvidence()[0].importTimingLines, 1);
  child.stderr.write('import time:       123 |        456 | ' + 'x'.repeat(5000));
  child.stderr.write('\nimport time:         0 |          0 | valid_after_oversized_line\n');
  assert.equal(f.supervisor.getEvidence()[0].importTimingLines, 2);
  child.stderr.write('import time:         8 |          8 | final_incomplete_line');
  await f.supervisor.stop();
  assert.equal(f.supervisor.getEvidence()[0].importTimingLines, 2);
});
