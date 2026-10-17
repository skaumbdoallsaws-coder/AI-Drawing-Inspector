'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const main = fs.readFileSync(path.join(__dirname, '../src/application-main.cjs'), 'utf8');
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

async function bounded(promise) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('Automated failure waited for a dialog')), 500);
    })]);
  } finally { clearTimeout(timer); }
}

function fixture(options = {}) {
  const events = [], files = new Map(), dialogResult = deferred();
  const profile = { dataRoot: path.resolve('test-data'), stateRoot: path.resolve('test-state') };
  const output = path.resolve('test-output');
  const failure = Object.assign(new Error('Backend startup exceeded its deadline'), { code: 'desktop_backend_startup_timeout' });
  const receipt = { terminationConfirmed: true, stdioClosed: true, resourcesClosed: false,
    forced: true, exitCode: null, processId: 123, logPath: 'retained-backend.log', ...options.receipt };
  const runtime = {
    start: async () => { events.push('start'); throw failure; },
    stop: async () => {
      events.push('stop');
      if (options.stopError) throw Object.assign(new Error('Cleanup failed'), { code: 'desktop_cleanup_unverified' });
      return receipt;
    },
    getEvidence: () => [{ failure: { code: failure.code, message: failure.message }, cleanup: receipt }],
  };
  const context = vm.createContext({
    path, root: path.resolve('.'), process: { argv: ['electron', 'entry'] },
    acceptanceOutput: null, profile: null, runtime: null, window: null, network: null,
    browserPromise: null, documents: null, browser: null, closing: false, pythonPath: null,
    parseRuntimeOptions: () => ({ python: 'python', profileFile: 'profile',
      ...(options.interactive ? {} : { [options.outputKey || 'codexAcceptanceOutput']: output }) }),
    loadApplicationProfile: async () => {
      if (options.profileError) throw Object.assign(new Error('Invalid profile'), { code: 'desktop_profile_invalid' });
      return profile;
    },
    localPath: async value => value,
    createManagedRuntime: args => { assert.equal(args.startupTimeoutMs, 120000); return runtime; },
    fs: {
      mkdir: async () => {},
      writeFile: async (file, content) => {
        events.push('write:' + path.basename(file));
        if (options.writeError) throw Object.assign(new Error('Cannot write'), { code: 'EACCES' });
        files.set(file, JSON.parse(content));
      },
    },
    app: { isPackaged: false, setPath() {}, requestSingleInstanceLock: () => true, on() {},
      whenReady: async () => {}, isReady: () => true,
      exit: code => events.push('exit:' + code) },
    dialog: { showMessageBox: () => { events.push('dialog'); return dialogResult.promise; } },
    console: { error: (...args) => events.push('log:' + args.join(' ')) },
  });
  for (const name of ['message', 'shutdown', 'start', 'failStartup']) {
    const source = main.match(new RegExp('^async function ' + name + '\\([^]*?^\\}', 'm'));
    assert(source, 'Actual application lifecycle function exists: ' + name);
    vm.runInContext(source[0], context);
  }
  assert(main.includes('start().catch(failStartup);'));
  return { context, files, events, output, profile, runtime, dialogResult, receipt,
    run: () => context.start().catch(context.failStartup) };
}

for (const outputKey of ['codexAcceptanceOutput', 'generationAcceptanceOutput', 'browserAcceptanceOutput',
  'workflowAcceptanceOutput', 'acceptanceOutput']) {
  test(outputKey + ': startup timeout exits without a dialog and retains forced cleanup evidence', async () => {
    const f = fixture({ outputKey });
    await bounded(f.run());
    assert.equal(f.events.includes('dialog'), false);
    assert.equal(f.events.at(-1), 'exit:1');
    assert.equal(f.events.filter(event => event === 'stop').length, 1);
    const report = f.files.get(path.join(f.output, 'driver-failure.json'));
    assert.equal(report.status, 'failed');
    assert.equal(report.phase, 'startup');
    assert.equal(report.code, 'desktop_backend_startup_timeout');
    assert.equal(report.desktop.cleanup.forced, true);
    assert.equal(report.desktop.cleanup.resourcesClosed, false);
    assert.equal(report.desktop.backends[0].failure.code, 'desktop_backend_startup_timeout');
    const desktop = f.files.get(path.join(f.profile.dataRoot, 'last-application-run.json'));
    assert.deepEqual(desktop, report.desktop);
    assert.equal(f.context.closing, true);
  });
}

test('automated profile failure is reported before a backend or window exists', async () => {
  const f = fixture({ profileError: true });
  await bounded(f.run());
  assert.equal(f.events.includes('start'), false);
  assert.equal(f.events.includes('stop'), false);
  assert.equal(f.events.includes('dialog'), false);
  const report = f.files.get(path.join(f.output, 'driver-failure.json'));
  assert.equal(report.code, 'desktop_profile_invalid');
  assert.deepEqual(report.desktop.backends, []);
  assert.equal(report.desktop.cleanup, null);
  assert.equal(f.events.at(-1), 'exit:1');
});

test('cleanup failure does not hide the original startup error or prevent exit', async () => {
  const f = fixture({ stopError: true });
  await bounded(f.run());
  const report = f.files.get(path.join(f.output, 'driver-failure.json'));
  assert.equal(report.code, 'desktop_backend_startup_timeout');
  assert.equal(report.desktop.cleanupError.code, 'desktop_cleanup_unverified');
  assert.equal(report.desktop.cleanup.forced, true);
  assert.equal(f.events.includes('dialog'), false);
  assert.equal(f.events.at(-1), 'exit:1');
});

test('evidence write failure still exits the automated process without a modal', async () => {
  const f = fixture({ writeError: true });
  await bounded(f.run());
  assert(f.events.some(event => event.startsWith('log:')));
  assert.equal(f.events.includes('dialog'), false);
  assert.equal(f.events.at(-1), 'exit:1');
});

test('normal interactive startup failure retains its operator dialog', async () => {
  const f = fixture({ interactive: true });
  const running = f.run();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(f.events, ['start', 'dialog']);
  f.dialogResult.resolve({ response: 0 });
  await bounded(running);
  assert.deepEqual(f.events, ['start', 'dialog', 'stop', 'exit:1']);
});

test('automated post-start cleanup failure cannot block report creation on a dialog', async () => {
  const f = fixture();
  f.context.acceptanceOutput = f.output;
  f.context.runtime = f.runtime;
  f.context.profile = f.profile;
  await bounded(f.context.shutdown());
  assert.equal(f.events.includes('dialog'), false);
  assert.equal(f.files.get(path.join(f.profile.dataRoot, 'last-application-run.json')).cleanup.forced, true);
});
