'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
const { authorizeTransition, transitionStep } = require('../src/application-lifecycle.cjs');
const main = fs.readFileSync(path.join(__dirname, '../src/application-main.cjs'), 'utf8');
const clean = { schemaVersion: 1, dirty: false, busy: false, pending: false, fingerprint: 'saved', affected: [] };
const dirty = { ...clean, dirty: true, fingerprint: 'draft', affected: ['facility'] };
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
const turn = () => new Promise(resolve => setImmediate(resolve));
async function until(predicate) {
  const deadline = Date.now() + 2000;
  while (!predicate()) {
    assert(Date.now() < deadline, 'application transition did not settle');
    await turn();
  }
}

// Exercise the actual main-process functions and event/menu bindings, as in
// application-startup-failure.test.cjs. No Electron process or backend is used.
function fixture(options = {}) {
  const events = [], notices = [], dialogs = [], files = new Map();
  const receipt = { terminationConfirmed: true, stdioClosed: true, resourcesClosed: true, forced: false };
  const window = new EventEmitter(), app = new EventEmitter();
  let destroyed = false;
  Object.assign(window, {
    show() {}, focus() {}, isDestroyed: () => destroyed,
    destroy() { events.push('destroy'); destroyed = true; },
    loadURL: options.loadURL || (async () => {}),
    webContents: {
      send(channel, detail) {
        if (channel === 'ip-application-transition-status') notices.push(detail);
        else events.push([channel, detail]);
      },
      reload: options.reload || (async () => {}), stop: () => events.push('stop-navigation'),
    },
  });
  app.quit = () => events.push('quit');
  const runtime = {
    stop: options.stop || (async () => { events.push('stop-backend'); return receipt; }),
    restart: options.restart || (async () => {}), getEvidence: () => [{ cleanup: receipt }],
  };
  const step = (label, action, _timeoutMs, onTimeout) => transitionStep(label, action, 20, onTimeout);
  const context = vm.createContext({
    window, app, runtime, path, profile: { dataRoot: '/test-data' },
    closing: false, transition: false, booted: true, closeRequested: false, transitionStatus: null,
    evidenceWrites: Promise.resolve(),
    browser: null, browserPromise: null, documents: null, chatgptAccount: null, acceptanceOutput: null,
    transitionStep: step, authorizeTransition: args => authorizeTransition({ ...args, step }),
    observe: options.observe || (async () => clean),
    network: { setEnabled: value => events.push(['network', value]), getEvidence: () => ({}) },
    dialog: { showMessageBox: async (_window, args) => {
      dialogs.push(args);
      return options.dialog ? options.dialog(args) : { response: 0 };
    } },
    fs: { writeFile: async (file, content) => { events.push('write-evidence'); files.set(file, JSON.parse(content)); } },
    Menu: { buildFromTemplate: value => value, setApplicationMenu: value => { context.menu = value; } },
  });
  // Also run against the pre-fix main source to demonstrate the write race.
  const evidenceHelpers = main.includes('function writeEvidence(') ? ['writeEvidence'] : [];
  for (const name of ['transitionNotice', 'message', ...evidenceHelpers, 'shutdown', 'change']) {
    const source = main.match(new RegExp('^(?:async )?function ' + name + '\\([^]*?^\\}', 'm'));
    assert(source, 'actual lifecycle function: ' + name);
    vm.runInContext(source[0], context);
  }
  for (const prefix of ["window.on('close'", "app.on('before-quit'"]) {
    vm.runInContext(main.split('\n').find(line => line.trim().startsWith(prefix)), context);
  }
  vm.runInContext(main.match(/Menu\.setApplicationMenu\(Menu\.buildFromTemplate\(\[[^]*?\]\)\);/)[0], context);
  function request(source = 'window') {
    if (source === 'menu') return context.menu[0].submenu[0].click();
    const event = { prevented: false, preventDefault() { this.prevented = true; } };
    (source === 'window' ? window : app).emit(source === 'window' ? 'close' : 'before-quit', event);
    assert.equal(event.prevented, true, 'native close cannot bypass authorization or cleanup');
  }
  return { context, runtime, events, notices, dialogs, files, receipt, request,
    closed: () => destroyed, evidence: () => [...files.values()].at(-1) };
}

test('stalled reload queues a second close, stops navigation, and rechecks unsaved work', async () => {
  const navigation = deferred();
  const f = fixture({ loadURL: () => navigation.promise });
  const reloading = f.context.change('reload', 'http://application/');
  await turn();
  f.request();
  assert(f.notices.some(value => value.includes('Close requested')));
  await reloading;
  await until(f.closed);
  assert(f.events.includes('stop-navigation'));
  assert.equal(f.events.filter(value => value === 'stop-backend').length, 1);
  navigation.resolve(); await turn();
  assert.equal(f.events.filter(value => value === 'destroy').length, 1);
});

test('stalled observation releases close and ignores a late clean reply', async () => {
  const observation = deferred();
  const f = fixture({ observe: () => observation.promise });
  const closing = f.context.change('close');
  f.request();
  await closing;
  assert.equal(f.context.transition, false);
  assert.equal(f.context.closing, false);
  assert(f.notices.some(value => value.includes('Workflow observation timed out')));
  observation.resolve(clean); await turn();
  assert(!f.closed());
  assert(!f.events.includes('stop-backend'));
  f.context.observe = async () => clean;
  await f.context.change('close');
  assert(f.closed());
});

test('expired Unsaved work dialog never discards, even after a late affirmative response', async () => {
  const answer = deferred();
  const f = fixture({ observe: async () => dirty, dialog: args => args.title === 'Unsaved work' ? answer.promise : { response: 0 } });
  const closing = f.context.change('close');
  await until(() => f.dialogs.length > 0);
  f.request();
  await closing;
  assert.equal(f.dialogs.filter(value => value.title === 'Unsaved work').length, 1);
  assert(f.dialogs[0].signal.aborted);
  assert.equal(f.dialogs[0].defaultId, 0);
  assert(!f.closed());
  answer.resolve({ response: 1 }); await turn();
  assert(!f.closed());
  assert(!f.events.includes('stop-backend'));
  f.context.dialog.showMessageBox = async () => ({ response: 0 });
  await f.context.change('close');
  assert(!f.closed());
  f.context.dialog.showMessageBox = async () => ({ response: 1 });
  await f.context.change('close');
  assert(f.closed());
});

for (const flag of ['busy', 'pending']) {
  test(flag + ' blocker stays visible when the informational dialog never resolves', async () => {
    const f = fixture({ observe: async () => ({ ...clean, [flag]: true }), dialog: () => deferred().promise });
    await f.context.change('close');
    assert.equal(f.context.transition, false);
    assert(f.notices.some(value => value.includes('Finish or cancel the active operation')));
    assert(f.dialogs[0].signal.aborted);
    assert(!f.closed());
    f.context.observe = async () => clean;
    await f.context.change('close');
    assert(f.closed());
  });
}

test('changed workflow after explicit discard blocks close', async () => {
  let observations = 0;
  const f = fixture({ observe: async () => ({ ...dirty, fingerprint: String(observations++) }), dialog: async () => ({ response: 1 }) });
  await f.context.change('close');
  assert(!f.closed());
  assert(!f.events.includes('stop-backend'));
  assert(f.notices.some(value => value.includes('workflow changed')));
});

for (const stage of ['Browser initialization', 'Browser cleanup', 'Document cleanup', 'Backend cleanup', 'Cleanup evidence']) {
  test(stage + ' stall keeps cleanup evidence and permits another close', async () => {
    const f = fixture(), stuck = deferred();
    if (stage === 'Browser initialization') f.context.browserPromise = stuck.promise;
    if (stage === 'Browser cleanup') f.context.browserPromise = Promise.resolve({ dispose: () => stuck.promise });
    if (stage === 'Document cleanup') f.context.documents = { dispose: () => stuck.promise };
    if (stage === 'Backend cleanup') f.runtime.stop = () => { f.events.push('stop-backend'); return stuck.promise; };
    if (stage === 'Cleanup evidence') f.context.fs.writeFile = () => stuck.promise;
    const closing = f.context.change('close');
    await until(() => f.events.some(value => Array.isArray(value) && value[0] === 'network'));
    f.request('before-quit');
    await closing;
    assert.equal(f.context.transition, false);
    assert.equal(f.context.closing, false);
    assert(!f.closed());
    assert(f.notices.some(value => value.includes(stage + ' timed out')));
    assert(f.events.includes('stop-backend'), 'browser cleanup cannot prevent owned backend cleanup');
    if (stage !== 'Cleanup evidence') {
      const evidence = f.evidence();
      assert(evidence.cleanupErrors.some(value => value.step === stage));
      assert.equal(evidence.cleanup?.terminationConfirmed ?? null, stage === 'Backend cleanup' ? null : true);
    }
    f.context.browserPromise = null; f.context.documents = null;
    f.runtime.stop = async () => f.receipt;
    f.context.fs.writeFile = async () => {};
    if (stage === 'Cleanup evidence') stuck.resolve();
    await f.context.change('close');
    assert(f.closed());
    stuck.resolve(f.receipt); await turn();
    assert.equal(f.events.filter(value => value === 'destroy').length, 1);
  });
}

test('expired evidence writes serialize retries and skip an expired queued record', async () => {
  const firstWrite = deferred(), laterWrite = deferred();
  const f = fixture(), started = [], completed = [];
  let attempt = 0;
  f.runtime.stop = async () => ({ ...f.receipt, attempt: ++attempt });
  f.context.fs.writeFile = async (file, content) => {
    const record = JSON.parse(content), number = record.cleanup.attempt;
    started.push(number);
    await (number === 1 ? firstWrite.promise : laterWrite.promise);
    completed.push(number);
    f.files.set(file, record);
  };
  await f.context.change('close');
  assert(!f.closed());
  assert(f.notices.some(value => value.includes('Cleanup evidence timed out')));
  await f.context.change('close');
  assert(!f.closed());
  assert.deepEqual(started, [1], 'the timed-out write must retain its place until it settles');
  const closing = f.context.change('close');
  await until(() => attempt === 3);
  // Reproduce the reviewer's out-of-order completion opportunity: the newer
  // write is ready before the original one, but cannot enter writeFile yet.
  laterWrite.resolve(); await turn();
  assert.deepEqual(started, [1]);
  firstWrite.resolve();
  await closing;
  assert(f.closed());
  assert.deepEqual(started, [1, 3], 'the expired second attempt must not write later');
  assert.deepEqual(completed, [1, 3]);
  assert.equal(f.evidence().cleanup.attempt, 3);
  await turn();
  assert.equal(f.evidence().cleanup.attempt, 3);
});

test('rejected evidence write leaves the queue usable for a fresh close', async () => {
  const f = fixture(), writeFile = f.context.fs.writeFile;
  f.context.fs.writeFile = async () => { throw new Error('evidence write failed'); };
  await f.context.change('close');
  assert(!f.closed());
  assert(f.notices.some(value => value.includes('evidence write failed')));
  f.context.fs.writeFile = writeFile;
  await f.context.change('close');
  assert(f.closed());
  assert.deepEqual(f.evidence().cleanup, f.receipt);
});

test('rejected cleanup and synchronous suspension failure do not latch closing or transition', async () => {
  const f = fixture({ stop: async () => { throw new Error('stop failed'); } });
  await f.context.change('close');
  assert.equal(f.context.closing, false);
  assert.equal(f.context.transition, false);
  assert(f.evidence().cleanupErrors.some(value => value.step === 'Backend cleanup'));
  f.context.browser = { suspend: () => { throw new Error('suspend failed'); } };
  // Failure when unsuspending must also leave the guard released.
  await f.context.change('close');
  assert.equal(f.context.transition, false);
  assert(f.notices.some(value => value.includes('suspend failed')));
  f.context.browser = null; f.runtime.stop = async () => f.receipt;
  await f.context.change('close');
  assert(f.closed());
});

test('timed-out restart cannot re-enable networking after a queued close', async () => {
  const restart = deferred(); let signal;
  const f = fixture({ restart: args => { signal = args.signal; return restart.promise; } });
  const restarting = f.context.change('restart');
  await until(() => signal);
  f.request('menu');
  await restarting;
  await until(f.closed);
  assert(signal.aborted);
  restart.resolve(); await turn();
  assert(!f.events.some(value => Array.isArray(value) && value[0] === 'network' && value[1] === true));
});

for (const source of ['window', 'menu', 'before-quit']) {
  test(source + ' close preserves Cancel and can close on a fresh explicit discard', async () => {
    const f = fixture({ observe: async () => dirty });
    f.request(source);
    await until(() => f.dialogs.length && f.context.transition === false);
    assert(!f.closed());
    assert.equal(f.dialogs[0].title, 'Unsaved work');
    f.context.dialog.showMessageBox = async () => ({ response: 1 });
    f.request(source);
    await until(f.closed);
  });
}

test('close during loading provides a visible reason and remains retryable', async () => {
  const f = fixture({ dialog: () => deferred().promise });
  f.context.booted = false;
  await f.context.change('close');
  assert(f.notices.some(value => value.includes('still loading')));
  assert(!f.closed());
  f.context.booted = true;
  await f.context.change('close');
  assert(f.closed());
});

test('unconfirmed backend receipt is retained before its stalled warning dialog', async () => {
  const receipt = { terminationConfirmed: false, stdioClosed: false, resourcesClosed: false, forced: true };
  const f = fixture({ stop: async () => receipt, dialog: () => deferred().promise });
  const closing = f.context.change('close');
  await until(() => f.dialogs.length);
  assert.deepEqual(f.evidence().cleanup, receipt);
  assert(f.notices.some(value => value.includes('cleanup was not fully confirmed')));
  await closing;
  assert(f.closed());
});

test('preload keeps a dismissible text notice above the shutdown overlay without granting IPC authority', () => {
  const listeners = new Map(), nodes = [], exposed = [];
  const element = () => ({ style: {}, attributes: {}, children: [], handlers: {},
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(name, callback) { this.handlers[name] = callback; },
    append(...children) { this.children.push(...children); }, remove() { this.removed = true; } });
  const document = { addEventListener() {}, createElement: element,
    documentElement: { inert: false, appendChild: node => nodes.push(node) } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../src/application-preload.cjs'), 'utf8'), {
    require: () => ({ ipcRenderer: { on: (name, callback) => listeners.set(name, callback) },
      contextBridge: { exposeInMainWorld: (name, api) => exposed.push([name, Object.keys(api)]) } }),
    document, MutationObserver: class { observe() {} },
  });
  const notify = listeners.get('ip-application-transition-status');
  notify(null, 'Closing...');
  listeners.get('ip-application-freeze')(null, true, 'Cleaning up');
  const notice = nodes[0], overlay = nodes[1];
  assert.equal(notice.attributes.role, 'status');
  assert.equal(overlay.textContent, 'Cleaning up');
  const z = node => Number(node.style.cssText.match(/z-index:(\d+)/)[1]);
  assert(z(notice) > z(overlay));
  notify(null, 'The window was kept open. <unsafe>');
  assert(notice.removed);
  assert.equal(nodes[2].children[0].textContent, 'The window was kept open. <unsafe>');
  nodes[2].children[1].handlers.click();
  assert(nodes[2].removed);
  assert.deepEqual(exposed, [['InspectorProNativeApplication', ['registerLifecycleObserver']]]);
});

test('an already-committed shutdown gives a visible reason for a menu close', async () => {
  const f = fixture();
  f.context.closing = true;
  await f.request('menu');
  assert(f.notices.some(value => value.includes('shutdown is already in progress')));
  assert(!f.events.includes('stop-backend'));
});
