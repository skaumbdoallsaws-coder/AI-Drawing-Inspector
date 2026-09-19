'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const vm = require('node:vm');
const { parseRuntimeOptions, hasCompleteStartupDiagnostics } = require('../src/runtime-settings.cjs');
const main = fs.readFileSync(path.join(__dirname, '../src/runtime-main.cjs'), 'utf8');
const absolute = name => path.resolve(__dirname, name);
function sourceFunction(name) {
  const found = main.match(new RegExp('^async function ' + name + '\\([^]*?^}', 'm'));
  assert.ok(found, name); return found[0];
}
const clone = value => JSON.parse(JSON.stringify(value));
const cleanupReceipt = () => ({ instanceId: 'owned-instance', processId: 4242, terminationConfirmed: true, stdioClosed: true,
  resourcesClosed: true, forced: false, exitCode: 0 });

function fixture(options = {}) {
  const events = [], outputs = [], urls = [], errors = [], exits = [];
  const runtime = { instanceId: 'owned-instance', processId: 4242 };
  const cleanup = options.cleanup || cleanupReceipt();
  const counts = () => ({ invalidCount: 0, foreignCount: 0, truncatedCount: 0 });
  const record = { instanceId: runtime.instanceId, processId: runtime.processId, runtime, cleanup, startupDiagnosticsEnabled: true,
    failure: null, diagnosticErrors: [], diagnosticErrorCounts: counts(), startupElapsedMs: 22, importTimingLines: 12,
    timings: { spawnStartedUnixMs: Date.now(), readyObservedElapsedMs: 20, runtimeVerifiedElapsedMs: 22,
      shutdownRequestedElapsedMs: 25, processExitElapsedMs: 30, stdioClosedElapsedMs: 31 },
    startupCheckpoints: { ...counts(), lastPhase: 'application-ready', records: [
      { phase: 'application-ready', instanceId: runtime.instanceId, processId: runtime.processId, sequence: 1, elapsedMs: 19, observedElapsedMs: 20 }] },
    diagnosticsFiles: { stacks: { path: absolute('stacks.log'), exists: true, sizeBytes: 256, baselinePresent: true },
      imports: { path: absolute('imports.json'), exists: true, metadataValid: true } } };
  options.mutateRecord?.(record);
  let preferences, stopped = false;
  const context = vm.createContext({ path, Date, __dirname: path.resolve(__dirname, '../src'), window: undefined,
    console: { error: value => errors.push(value) },
    options: { startupDiagnosticsOutput: absolute('diagnostic-output'), acceptanceOutput: null },
    profile: { partition: 'isolated', dataRoot: absolute('data'), stateRoot: absolute('state') },
    startupTime: Date.now(), currentRuntime: options.noRuntime ? null : runtime, exiting: false,
    rendererFailed: false, network: undefined, peer: undefined, hasCompleteStartupDiagnostics,
    fail: (code, message = code) => Object.assign(new Error(message), { code }),
    localPath: async value => { events.push('validate-path'); return value; },
    fs: { mkdir: async () => { assert.equal(stopped, true); events.push('mkdir'); },
      writeFile: async (file, text) => { assert.equal(stopped, true); events.push('write');
        if (options.writeError) throw options.writeError; outputs.push({ file, report: JSON.parse(text) }); } },
    supervisor: { start: async () => { events.push('backend-start'); return runtime; },
      stop: async () => { events.push('backend-stop'); stopped = true; if (options.stopError) throw options.stopError; return cleanup; },
      getEvidence: () => { if (options.evidenceError) throw options.evidenceError; return [record]; } },
    BrowserWindow: class {
      constructor(value) { events.push('window'); assert.equal(value.show, false); preferences = value.webPreferences;
        this.webContents = { session: {}, getLastWebPreferences: () => Object.hasOwn(options, 'preferences') ? options.preferences : preferences,
          setWindowOpenHandler() {}, on() {} }; this.destroyed = false; }
      on() {} isDestroyed() { return this.destroyed; }
      destroy() { this.destroyed = true; events.push('window-destroy'); }
      async loadURL(url) { urls.push(url); events.push('load-starting-page'); }
    },
    session: { fromPartition: () => ({}) },
    Menu: { buildFromTemplate: value => value, setApplicationMenu() {} },
    app: { on() {}, exit: code => { events.push('exit'); exits.push(code); } },
    createFirstPaintGate: () => ({}),
    installLifecycle: () => { context.peer = { dispose: () => events.push('peer-dispose') }; context.lifecycle = {}; },
    installIPC: () => {}, lockInput: () => {}, evidence: () => {},
    createRuntimeNetwork: () => { throw new Error('Diagnostic mode must not install application network access'); },
    applicationURL: () => { throw new Error('Diagnostic mode must not load the application'); },
  });
  vm.runInContext(sourceFunction('finishStartupDiagnostics') + '\n' + sourceFunction('start'), context);
  return { context, events, outputs, urls, errors, exits, cleanup, get preferences() { return preferences; } };
}

test('runtime options accept one explicit absolute diagnostic destination and keep normal acceptance distinct', () => {
  const base = ['--profile-file', absolute('profile.json'), '--python', absolute('python.exe')];
  const normal = parseRuntimeOptions([...base, '--acceptance-output', absolute('acceptance')]);
  assert.equal(normal.startupDiagnosticsOutput, null); assert.equal(normal.acceptanceOutput, absolute('acceptance'));
  const diagnostic = parseRuntimeOptions([...base, '--startup-diagnostics-output', absolute('diagnostics')]);
  assert.equal(diagnostic.acceptanceOutput, null); assert.equal(diagnostic.startupDiagnosticsOutput, absolute('diagnostics'));
  assert.throws(() => parseRuntimeOptions([...base, '--startup-diagnostics-output', 'relative']), { code: 'desktop_local_path_required' });
  assert.throws(() => parseRuntimeOptions([...base, '--startup-diagnostics-output', absolute('a'), '--acceptance-output', absolute('b')]), { code: 'desktop_options_invalid' });
  assert.throws(() => parseRuntimeOptions([...base, '--startup-diagnostics-output', absolute('a'), '--startup-diagnostics-output', absolute('b')]), { code: 'desktop_options_invalid' });
});

test('actual main startup uses the locked starting page and normal backend then exits after graceful cleanup without loading index', async () => {
  const f = fixture(); await f.context.start();
  assert.equal(f.urls.length, 1); assert.match(f.urls[0], /^data:text\/html/);
  assert.deepEqual(f.exits, [0]); assert.equal(f.outputs.length, 1);
  const report = f.outputs[0].report;
  assert.equal(report.mode, 'managed-backend-startup-diagnostics'); assert.equal(report.status, 'passed');
  assert.equal(report.runtimeVerified, true); assert.equal(report.startupDeadlineMs, 45000);
  assert.equal(report.startupDiagnosticsOnly, true); assert.equal(report.saveCalls, 0);
  for (const key of ['nativeAcceptance', 'applicationLoaded', 'facilityAttached', 'editorExercised', 'screenshotCaptured', 'generalEditing', 'researchBrowsing']) assert.equal(report[key], false, key);
  assert.deepEqual(report.isolation, { sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true });
  assert.equal(f.preferences.additionalArguments.includes('--inspectorpro-desktop-managed'), true);
  assert.deepEqual(report.cleanup, f.cleanup);
  assert.ok(f.events.indexOf('backend-start') < f.events.indexOf('backend-stop'));
  assert.ok(f.events.indexOf('backend-stop') < f.events.indexOf('write'));
  assert.ok(f.events.indexOf('write') < f.events.indexOf('window-destroy'));
});

test('backend startup failure retains failed cleanup evidence and cannot become a successful diagnostic receipt', async () => {
  const cleanup = { ...cleanupReceipt(), resourcesClosed: false, forced: true, exitCode: null };
  const f = fixture({ cleanup, noRuntime: true });
  const failure = Object.assign(new Error('Private exception message is not part of fixed receipt metadata'), { code: 'desktop_backend_startup_timeout' });
  const result = await f.context.finishStartupDiagnostics(failure);
  assert.equal(result.status, 'failed'); assert.equal(result.runtimeVerified, false);
  assert.deepEqual(clone(result.cleanup), cleanup); assert.deepEqual(f.exits, [1]);
  assert.equal(f.outputs[0].report.error.code, failure.code);
  assert.doesNotMatch(JSON.stringify(f.outputs[0].report), /Private exception/);
});

test('main diagnostic receipt independently rejects missing or incorrect isolation preferences after owned cleanup', async t => {
  const expected = { sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true };
  for (const key of [null, ...Object.keys(expected)]) await t.test(key || 'missing preferences', async () => {
    const preferences = key === null ? null : { ...expected, [key]: !expected[key] };
    const f = fixture({ preferences }); await f.context.start();
    assert.deepEqual(f.exits, [1]); assert.equal(f.outputs.length, 1);
    const report = f.outputs[0].report;
    assert.equal(report.status, 'failed'); assert.equal(report.error.code, 'desktop_startup_diagnostic_isolation_failed');
    assert.deepEqual(report.cleanup, f.cleanup); assert.deepEqual(report.isolation, preferences);
    assert.ok(f.events.indexOf('backend-stop') < f.events.indexOf('write'));
  });
});

test('missing receipt, failed stop and diagnostic persistence errors cannot skip owned cleanup or report acceptance', async t => {
  for (const [name, options] of [
    ['missing graceful receipt', { cleanup: { ...cleanupReceipt(), resourcesClosed: false } }],
    ['failed stop', { stopError: Object.assign(new Error('stop failed'), { code: 'controlled_stop_failure' }) }],
    ['failed evidence observation', { evidenceError: Object.assign(new Error('evidence read failed'), { code: 'controlled_evidence_failure' }) }],
    ['failed diagnostic write', { writeError: Object.assign(new Error('file locked'), { code: 'EPERM' }) }],
  ]) await t.test(name, async () => {
    const f = fixture(options); const result = await f.context.finishStartupDiagnostics();
    assert.equal(result.status, 'failed'); assert.deepEqual(f.exits, [1]);
    assert.equal(f.events.filter(value => value === 'backend-stop').length, 1);
    if (options.writeError) { assert.equal(f.outputs.length, 0); assert.match(f.errors[0], /^INSPECTORPRO_STARTUP_DIAGNOSTIC_RESULT /); }
    if (options.stopError) assert.equal(result.cleanup, null);
  });
});

test('actual bootstrap enables instrumentation only from the explicit diagnostic option with no deadline override', async () => {
  let captured, starts = 0;
  const context = vm.createContext({
    process: { argv: ['electron', 'entry', '--profile-file', absolute('profile.json'), '--python', absolute('python.exe'),
      '--startup-diagnostics-output', absolute('diagnostics')] },
    parseRuntimeOptions, loadRuntimeProfile: async () => ({ stateRoot: absolute('profile-state'), acceptanceLayoutId: 'fl-test' }),
    localPath: async value => value, fs: { mkdir: async () => {} },
    app: { setPath() {}, setName() {}, requestSingleInstanceLock: () => true, whenReady: async () => {} },
    createManagedRuntime: value => { captured = value; return {}; }, appRoot: absolute('app'),
    start: async () => { starts++; }, fail: code => Object.assign(new Error(code), { code }),
  });
  vm.runInContext(sourceFunction('bootstrap'), context); await context.bootstrap();
  assert.equal(captured.startupDiagnostics, true); assert.equal(captured.startupTimeoutMs, undefined); assert.equal(starts, 1);
  context.process.argv = context.process.argv.slice(0, -2); await context.bootstrap();
  assert.equal(captured.startupDiagnostics, false); assert.equal(captured.startupTimeoutMs, undefined);
});

test('main receipt cannot pass merely because the backend started when owned instrumentation is incomplete', async t => {
  const cases = [
    ['wrong pid', item => { item.processId++; }],
    ['no checkpoints', item => { item.startupCheckpoints.records = []; }],
    ['no timings', item => { item.timings = {}; }],
    ['no import timings', item => { item.importTimingLines = 0; }],
    ['invalid import count', item => { item.importTimingLines = true; }],
    ['diagnostic error', item => { item.diagnosticErrors.push({ operation: 'bind', errorType: 'OSError' }); }],
    ['foreign diagnostic record', item => { item.diagnosticErrorCounts.foreignCount++; }],
    ['no baseline', item => { item.diagnosticsFiles.stacks.baselinePresent = false; }],
    ['empty stacks', item => { item.diagnosticsFiles.stacks.sizeBytes = 0; }],
    ['missing stacks', item => { item.diagnosticsFiles.stacks.exists = false; }],
    ['invalid metadata', item => { item.diagnosticsFiles.imports.metadataValid = false; }],
  ];
  for (const [name, mutateRecord] of cases) await t.test(name, async () => {
    const f = fixture({ mutateRecord }); const result = await f.context.finishStartupDiagnostics();
    assert.equal(result.status, 'failed'); assert.deepEqual(f.exits, [1]);
    assert.equal(result.error.code, 'desktop_startup_diagnostic_evidence_incomplete');
    assert.equal(result.cleanup.resourcesClosed, true);
  });
});
