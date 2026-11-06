'use strict';
// Offline lifecycle contracts, not native-window or packaging release acceptance.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const observation = require('../../static/desktop_workflow_observation.js');
const Session = require('../../static/facility_layout_session.js');
const { createRuntimeLifecycle } = require('../src/runtime-lifecycle.cjs');
const { authorizeTransition, transitionStep, validateObservation } = require('../src/application-lifecycle.cjs');
const base = require('../../tests/fixtures/facility_layout/empty_cell.json');
const bridgeSource = fs.readFileSync(path.join(__dirname, '../../static/desktop_runtime_bridge.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../../static/index.html'), 'utf8');
const packagingSource = fs.readFileSync(path.join(__dirname, '../../static/packaging.js'), 'utf8');
const mainSource = fs.readFileSync(path.join(__dirname, '../src/application-main.cjs'), 'utf8');
const preloadSource = fs.readFileSync(path.join(__dirname, '../src/application-preload.cjs'), 'utf8');
const clone = value => JSON.parse(JSON.stringify(value));
const empty = () => ({ loaded: false, dirty: false, busy: false, pending: false });
const emptySources = () => Object.fromEntries(Object.keys(observation.WORKFLOWS).map(id => [id, empty()]));
const unavailable = { code: 'desktop_workflow_coverage_unavailable' };
const uncovered = { code: 'desktop_workflow_recovery_not_enabled' };

function packagingFixture({ mounted = true } = {}) {
  const flags = empty(), hostFlags = empty(), frames = [];
  const childDocument = { readyState: 'complete' };
  const child = { document: childDocument, location: { href: 'http://127.0.0.1:8180/packaging' },
    InspectorProPackaging: {
      getDesktopLifecycleObservation: () => ({ ...flags }),
      confirmNavigation: () => assert.fail('Observation cannot ask to discard'),
    } };
  const frame = { tagName: 'IFRAME', isConnected: true, src: child.location.href,
    contentWindow: child, contentDocument: childDocument, hidden: false };
  if (mounted) frames.push(frame);
  const host = { document: { querySelectorAll: selector => {
    assert.equal(selector, '#packagingWorkspaceFrame'); return [...frames];
  } }, location: { origin: 'http://127.0.0.1:8180', href: 'http://127.0.0.1:8180/' },
  InspectorProPackagingHost: { getDesktopLifecycleObservation: () => ({ ...hostFlags }) } };
  return { host, frame, child, childDocument, flags, hostFlags, frames,
    read: () => observation.observePackaging(host) };
}

function between(source, start, end) {
  const begin = source.indexOf(start), finish = source.indexOf(end, begin);
  assert.ok(begin >= 0 && finish > begin, 'actual source boundary: ' + start);
  return source.slice(begin, finish);
}

function actualPackagingFixture() {
  const f = packagingFixture({ mounted: false });
  const files = [], addresses = { origin: {}, destinations: [{}] };
  const childState = { draft: { dirty: false }, formDirty: false, busy: false,
    conflict: false, sage: { locked: false, admission: null, closing: null } };
  f.childDocument.querySelectorAll = selector => {
    assert.equal(selector, 'input[type="file"]'); return files;
  };
  f.childDocument.querySelector = selector => {
    assert.equal(selector, 'dialog[open]'); return f.dialog || null;
  };
  f.host.document.getElementById = id => {
    assert.equal(id, 'packagingWorkspaceFrame'); return f.frames[0] || null;
  };
  const childContext = vm.createContext({ window: f.child, document: f.childDocument, state: childState,
    captureAddresses: () => addresses, confirm: () => assert.fail('No discard or navigation confirmation') });
  vm.runInContext(packagingSource.match(/^function blankAddress\(\)[^\r\n]+/m)[0], childContext);
  addresses.origin = clone(childContext.blankAddress());
  addresses.destinations[0] = clone(childContext.blankAddress());
  vm.runInContext(between(packagingSource, 'const hasDraft =', 'function notify('), childContext);
  vm.runInContext(between(packagingSource, 'window.InspectorProPackaging = Object.freeze({', '\n  });')
    + '\n});', childContext);
  f.host.InspectorProDesktopWorkflowObservation = observation;
  f.host.__agentChatStreamV1 = { getDesktopLifecycleObservation: empty };
  const hostContext = vm.createContext({ window: f.host, document: f.host.document,
    state: { activeTab: 'model', faiMeasurements: {}, faiVerdicts: {}, faiTolOverrides: {},
      assemblyPartDisplayOverrides: {}, pendingExecutionReceipts: [], partsManualDraftOccurrenceIds: new Set() },
    trainingState: { type: 'facility_layout', goal: 'Answer facility layout questions.' },
    annoState: { shapes: [] }, regionsCuratorState: {}, sessionsTabState: { actionBusy: {}, syncPreviews: {}, refreshResults: {} },
    _trainCurrentProcessFlowEditor: () => null, _trainFacilityLayoutAuthoringApp: null, _trainFacilitySheets: null,
    _packagingActiveTurn: null, _packagingReleasePromise: null });
  vm.runInContext(between(html, 'window.InspectorProPackagingHost = {', '\n        };') + '\n};', hostContext);
  vm.runInContext(between(html, '        function _desktopObserveApplication() {',
    '        function setupEventListeners() {'), hostContext);
  return Object.assign(f, { childState, files, addresses, hostContext, childContext });
}

test('actual host hook covers active workspace, preparing turn and release without an iframe', () => {
  const f = actualPackagingFixture();
  assert.deepEqual(f.read(), empty());
  f.hostContext.state.activeTab = 'training';
  assert.deepEqual(f.read(), empty(), 'facility training does not imply packaging');
  f.hostContext.trainingState.type = 'packaging_shipping';
  assert.equal(f.read().loaded, true); assert.equal(f.read().pending, true);
  f.hostContext.state.activeTab = 'model';
  f.hostContext._packagingActiveTurn = { preparing: true, documentId: 'private' };
  assert.equal(f.read().busy, true); assert.equal(f.read().pending, true);
  f.hostContext._packagingActiveTurn = null;
  f.hostContext._packagingReleasePromise = Promise.resolve();
  assert.equal(f.read().pending, true);
  f.hostContext._packagingReleasePromise = null;
  f.frames.push(f.frame); assert.equal(f.read().loaded, true);
});

for (const [name, mutate, flag] of [
  ['draft', f => { f.childState.draft.dirty = true; }, 'dirty'],
  ['unapplied form', f => { f.childState.formDirty = true; }, 'dirty'],
  ['session address', f => { f.addresses.origin.street1 = 'private'; }, 'dirty'],
  ['selected file', f => { f.files.push({ files: [{ name: 'private' }] }); }, 'dirty'],
  ['busy request', f => { f.childState.busy = true; }, 'busy'],
  ['Sage lock', f => { f.childState.sage.locked = true; }, 'busy'],
  ['admission', f => { f.childState.sage.admission = { id: 'private' }; }, 'pending'],
  ['reconciliation', f => { f.childState.sage.closing = Promise.resolve(); }, 'pending'],
  ['conflict', f => { f.childState.conflict = true; }, 'pending'],
  ['open dialog', f => { f.dialog = {}; }, 'pending'],
]) test('actual child hook reports ' + name + ' as boolean-only lifecycle evidence', () => {
  const f = actualPackagingFixture(); mutate(f);
  const result = clone(f.child.InspectorProPackaging.getDesktopLifecycleObservation());
  assert.deepEqual(Object.keys(result).sort(), Object.keys(empty()).sort());
  assert.ok(Object.values(result).every(value => typeof value === 'boolean'));
  assert.equal(result.loaded, true); assert.equal(result[flag], true);
  assert.equal(JSON.stringify(result).includes('private'), false);
});

test('complete empty host without a mounted packaging frame is empty', () => {
  const f = packagingFixture({ mounted: false });
  assert.deepEqual(f.read(), empty());
  delete f.host.InspectorProPackagingHost;
  assert.deepEqual(f.read(), empty());
  assert.doesNotThrow(() => observation.assertEmpty(observation.capture(emptySources(), 'renderer'), 'renderer'));
});

for (const [name, flags] of [
  ['saved document', {}], ['unsaved document', { dirty: true }],
  ['unapplied form', { dirty: true, pending: true }], ['request in flight', { busy: true }],
  ['Sage lock', { busy: true, pending: true }],
]) test(name + ' is uncovered even while the iframe is hidden', () => {
  const f = packagingFixture(); Object.assign(f.flags, flags); f.frame.hidden = true;
  const result = f.read();
  assert.equal(result.loaded, true); assert.equal(result.pending, true);
  for (const key of Object.keys(flags)) assert.equal(result[key], flags[key]);
  const sources = { ...emptySources(), packaging: result };
  assert.throws(() => observation.assertEmpty(observation.capture(sources, 'r'), 'r'), error => {
    assert.equal(error.code, uncovered.code); assert.ok(error.workflows.includes('packaging'));
    assert.match(error.message, /Packaging & Shipping/); return true;
  });
});

for (const flag of ['loaded', 'dirty', 'busy', 'pending']) {
  test('host-only ' + flag + ' remains blocking without an iframe', async () => {
    const f = packagingFixture({ mounted: false }); f.hostFlags[flag] = true;
    const row = f.read(); assert.equal(row.pending, true);
    for (const kind of ['close', 'restart']) {
      const result = await authorizeTransition({ kind, observe: async () => ({ schemaVersion: 1,
        dirty: row.dirty, busy: row.busy, pending: row.pending, affected: ['packaging'], fingerprint: JSON.stringify(row) }),
      confirmDiscard: () => assert.fail('Uncovered packaging cannot be explicitly discarded by facility controls') });
      assert.equal(result.allowed, false);
    }
  });
}

for (const [name, mutate] of [
  ['missing DOM', f => { delete f.host.document; }],
  ['missing host adapter', f => { delete f.host.InspectorProPackagingHost; }],
  ['legacy host API', f => { f.host.InspectorProPackagingHost = { prepare() {} }; }],
  ['legacy iframe API', f => { f.child.InspectorProPackaging = { hasUnsavedChanges: () => false, isLocked: () => false }; }],
  ['loading iframe', f => { f.childDocument.readyState = 'loading'; }],
  ['detached iframe', f => { f.frame.isConnected = false; }],
  ['wrong element type', f => { f.frame.tagName = 'DIV'; }],
  ['duplicate frames', f => { f.frames.push({ ...f.frame }); }],
  ['cross origin', f => { f.frame.src = 'https://example.invalid/packaging'; }],
  ['wrong route', f => { f.frame.src = 'http://127.0.0.1:8180/not-packaging'; }],
  ['initial about blank', f => { f.child.location.href = 'about:blank'; }],
  ['missing content document', f => { f.frame.contentDocument = null; }],
  ['old child document', f => { f.child.document = { readyState: 'complete' }; }],
  ['cross-world access denied', f => { Object.defineProperty(f.frame, 'contentWindow', { get() { throw Error('private payload'); } }); }],
  ['observer throws', f => { f.child.InspectorProPackaging.getDesktopLifecycleObservation = () => { throw Error('private payload'); }; }],
  ['async observer', f => { f.child.InspectorProPackaging.getDesktopLifecycleObservation = async () => empty(); }],
  ['missing flag', f => { delete f.flags.dirty; }],
  ['truthy nonboolean', f => { f.flags.busy = 'false'; }],
  ['extra payload', f => { f.flags.document = { secret: 'private payload' }; }],
  ['malformed host flag', f => { f.hostFlags.pending = null; }],
  ['accessor flags', f => { f.child.InspectorProPackaging.getDesktopLifecycleObservation = () =>
    Object.defineProperty(empty(), 'dirty', { get() { throw Error('private payload'); }, enumerable: true }); }],
]) test(name + ' fails closed without publishing raw state', () => {
  const f = packagingFixture(); mutate(f);
  assert.throws(f.read, error => {
    assert.equal(error.code, unavailable.code); assert.equal(error.message, unavailable.code);
    assert.equal(JSON.stringify(error).includes('private payload'), false); return true;
  });
});

for (const [name, mutate] of [
  ['remount', f => { f.frames[0] = { ...f.frame }; }],
  ['removal', f => { f.frames.length = 0; }],
  ['navigation', f => { f.frame.src += '?other-document=1'; }],
  ['reload', f => { f.frame.contentDocument = { readyState: 'complete' }; }],
  ['adapter replacement', f => { f.child.InspectorProPackaging = {}; }],
  ['host adapter replacement', f => { f.host.InspectorProPackagingHost = {}; }],
]) test(name + ' during synchronous inspection cannot return a clean snapshot', () => {
  const f = packagingFixture();
  f.child.InspectorProPackaging.getDesktopLifecycleObservation = () => { mutate(f); return empty(); };
  assert.throws(f.read, unavailable);
});

test('fresh observations do not cache empty state or overwrite stronger host evidence', () => {
  const f = packagingFixture({ mounted: false });
  const sources = emptySources(), before = clone(sources);
  assert.deepEqual(observation.withPackaging(sources, f.host).packaging, empty());
  assert.deepEqual(sources, before);
  sources.packaging.pending = true;
  assert.equal(observation.withPackaging(sources, f.host).packaging.pending, true);
  f.frames.push(f.frame); assert.equal(f.read().loaded, true);
  f.frames.length = 0; f.hostFlags.pending = true;
  assert.equal(f.read().pending, true);
  f.hostFlags.pending = false; assert.deepEqual(f.read(), empty());
});

test('legacy snapshots missing packaging and stale renderer generations cannot authorize close', () => {
  const sources = emptySources(); delete sources.packaging;
  assert.throws(() => observation.capture(sources, 'r'), unavailable);
  const snapshot = observation.capture(emptySources(), 'r');
  assert.throws(() => observation.assertEmpty(snapshot, 'other'), unavailable);
  snapshot.workflows = snapshot.workflows.filter(row => row.workflowId !== 'packaging');
  assert.throws(() => observation.assertEmpty(snapshot, 'r'), unavailable);
});

async function lifecycleFixture(options = {}) {
  const f = options.actualHooks ? actualPackagingFixture() : packagingFixture({ mounted: false });
  const effects = { prepare: 0, commit: 0, restart: 0, locks: 0, access: 0, cancel: 0 };
  const session = Session.createSession({ previewOperations: async () => assert.fail('No editing'),
    applyOperations: async () => assert.fail('No Save transport') });
  session.load({ layout: clone(base), revision: 'saved-revision' });
  const runtime = { schemaVersion: 1, status: 'ready', mode: 'desktop-managed',
    identity: { backendId: 'backend', storeId: 'store', principalId: 'principal' },
    owner: { sessionId: 'session', ownerId: 'owner' }, instanceId: 'process-one',
    document: { tenantId: 'local', siteId: 'site-local', documentId: base.layoutId },
    capabilities: { generalEditing: false, researchBrowsing: false, facilityAcceptance: true, save: false } };
  let handler, lifecycle, observations = 0;
  const native = { getRuntime: async () => clone(runtime),
    onLifecycleRequest: callback => { handler = callback; return () => { handler = null; }; },
    attachFacility: binding => lifecycle.attach(clone(binding)),
    persistOperation: () => assert.fail('No recovery serialization'), clearOperation: () => assert.fail('No recovery deletion') };
  const context = vm.createContext({ ...f.host, InspectorProDesktop: native,
    InspectorProDesktopWorkflowObservation: observation, URL, URLSearchParams,
    sessionStorage: { getItem: () => null } });
  vm.runInContext(bridgeSource, context);
  function rpc(method, args, control = { assertCurrent() {} }) {
    const result = handler({ method, args }, control);
    if (!result.ok) throw Object.assign(Error(result.error.code), result.error);
    return clone(result.result);
  }
  const editor = Object.fromEntries(['snapshot', 'freeze', 'unfreeze', 'setStartupRecoveryGate']
    .map(method => [method, async (args, control) => rpc(method, args, control)]));
  lifecycle = createRuntimeLifecycle({ profile: { dataRoot: 'unused-no-persistence' }, editor,
    supervisor: { getState: () => ({ status: 'ready', runtime }), restart: async () => { effects.restart++; } },
    inspectOtherWorkflows: async control => {
      observations++; options.onObservation?.(f, observations); return rpc('inspectOtherWorkflows', undefined, control);
    }, lockInput: () => { effects.locks++; }, setBackendAccess: () => { effects.access++; },
    closeConnections: async () => {}, commitWindow: async () => { effects.commit++; },
    decideClose: () => assert.fail('No discard decision for packaging'),
    adapterFactory: async setup => {
      const initial = await editor.snapshot();
      await editor.setStartupRecoveryGate({ blocked: false, expectedRendererGeneration: initial.rendererGeneration,
        expectedStateSequence: initial.stateSequence });
      return { getSaveGate: async () => ({ allowed: true, blockers: [] }),
        prepare: async () => {
          effects.prepare++; const snapshot = await editor.snapshot();
          const prepared = { status: 'ready', intentId: 'intent-' + effects.prepare,
            rendererGeneration: snapshot.rendererGeneration, stateSequence: snapshot.stateSequence };
          await editor.freeze(prepared); options.afterPrepare?.(f); return prepared;
        },
        cancel: async intentId => { effects.cancel++; await editor.unfreeze({ intentId }); },
        commit: async () => {
          try { await setup.commitLifecycle({ reason: 'close' }, { assertCurrent() {} }); return { status: 'committed' }; }
          catch (error) { return { status: 'blocked', blockers: [error.code] }; }
        } };
    },
    managedFactory: setup => ({ restart: async () => {
      options.beforeRestart?.(f); await setup.restartBackend({ assertCurrent() {} }); return { status: 'reconciled' };
    } }),
  });
  const bridge = context.InspectorProDesktopRuntimeBridge;
  await bridge.startFacilityWorkspace({
    // Exercise the unchanged legacy host observer: bridge must add packaging.
    inspectOtherWorkflows: () => { const rows = emptySources(); delete rows.packaging; return rows; },
    activateFacility: async () => {
      const opts = await bridge.prepareFacilityOptions({ siteId: 'site-local', layoutId: base.layoutId });
      const result = await bridge.attachFacility({ ready: Promise.resolve(), session, getState: () => ({ destroyed: false }) },
        { id: 'trainFacilityLayoutAuthoring', isConnected: true }, opts);
      return result.attached;
    },
  });
  return { ...f, lifecycle, effects, rpc, context, get observations() { return observations; } };
}

test('real runtime bridge and lifecycle block packaging before freeze, shutdown or restart', async () => {
  const f = await lifecycleFixture(); f.frames.push(f.frame); f.flags.dirty = true;
  const before = f.rpc('snapshot');
  await assert.rejects(f.lifecycle.close(), uncovered);
  await assert.rejects(f.lifecycle.restart(), uncovered);
  assert.deepEqual(f.effects, { prepare: 0, commit: 0, restart: 0, locks: 0, access: 0, cancel: 0 });
  assert.deepEqual(f.rpc('snapshot'), before);
});

test('real bridge carries sanitized missing-adapter errors instead of clean coverage', async () => {
  const f = await lifecycleFixture(); f.frames.push(f.frame); delete f.child.InspectorProPackaging;
  await assert.rejects(f.lifecycle.close(), unavailable);
  await assert.rejects(f.lifecycle.restart(), unavailable);
  assert.equal(f.effects.prepare + f.effects.commit + f.effects.restart, 0);
});

test('late packaging work after preparation releases the facility freeze without discarding', async () => {
  const f = await lifecycleFixture({ afterPrepare: state => { state.frames.push(state.frame); } });
  const before = f.rpc('snapshot');
  await assert.rejects(f.lifecycle.close(), uncovered);
  assert.equal(f.effects.prepare, 1); assert.equal(f.effects.cancel, 1); assert.equal(f.effects.commit, 0);
  assert.deepEqual(f.rpc('snapshot'), before);
});

test('final close guard re-reads the iframe instead of reusing earlier clean coverage', async () => {
  const f = await lifecycleFixture({ onObservation: (state, count) => { if (count === 3) state.frames.push(state.frame); } });
  const before = f.rpc('snapshot'); const result = await f.lifecycle.close();
  assert.equal(result.status, 'blocked'); assert.ok(result.blockers.includes(uncovered.code));
  assert.equal(f.effects.commit, 0); assert.equal(f.effects.cancel, 1);
  assert.deepEqual(f.rpc('snapshot'), before);
});

test('restart guard detects a host Sage lock appearing after preflight', async () => {
  const f = await lifecycleFixture({ beforeRestart: state => { state.hostFlags.pending = true; } });
  await assert.rejects(f.lifecycle.restart(), uncovered);
  assert.equal(f.effects.restart, 0); assert.equal(f.effects.commit, 0);
});

test('cancelled native controls cannot invoke the iframe observer', async () => {
  const f = await lifecycleFixture();
  f.context.document.querySelectorAll = () => assert.fail('Cancelled request must not inspect');
  assert.throws(() => f.rpc('inspectOtherWorkflows', undefined, { assertCurrent() {
    throw Object.assign(Error('cancelled'), { code: 'desktop_runtime_request_cancelled' });
  } }), { code: 'desktop_runtime_request_cancelled' });
});

test('fully empty attached lifecycle still permits a clean close', async () => {
  const f = await lifecycleFixture();
  assert.equal((await f.lifecycle.close()).status, 'committed');
  assert.equal(f.effects.commit, 1); assert.equal(f.effects.restart, 0);
});

test('actual host and child hooks also block the managed runtime bridge route', async () => {
  const f = await lifecycleFixture({ actualHooks: true });
  f.frames.push(f.frame); f.childState.formDirty = true;
  await assert.rejects(f.lifecycle.close(), uncovered);
  await assert.rejects(f.lifecycle.restart(), uncovered);
  assert.deepEqual(f.effects, { prepare: 0, commit: 0, restart: 0, locks: 0, access: 0, cancel: 0 });
});

function applicationFixture(options = {}) {
  const f = actualPackagingFixture(), events = [], replies = [], dialogs = [], departureReplies = [];
  const mainHandlers = new Map(), rendererHandlers = new Map();
  const receipt = { terminationConfirmed: true, stdioClosed: true, resourcesClosed: true };
  let destroyed = false, requests = 0;
  const window = { show() {}, focus() {}, isDestroyed: () => destroyed,
    destroy() { destroyed = true; events.push('destroy'); },
    loadURL: async () => events.push('navigate'),
    webContents: { mainFrame: {}, reload: async () => events.push('reload'), stop() {},
      send(channel, id) {
        if (channel === 'ip-application-observe') {
          options.beforeObservation?.(f, ++requests);
          rendererHandlers.get(channel)({}, id);
        } else if (channel === 'ip-application-close-packaging') {
          if (!options.dropDeparture) rendererHandlers.get(channel)({}, id);
        } else if (channel !== 'ip-application-transition-status') events.push(channel);
      } },
  };
  const main = vm.createContext({ window, app: { quit: () => events.push('quit') },
    ipcMain: { on: (channel, callback) => mainHandlers.set(channel, callback) },
    randomUUID: () => 'observation-' + requests, setTimeout, clearTimeout, path,
    closing: false, transition: false, booted: true, closeRequested: false, transitionStatus: null, backendUnavailable: false,
    trusted: event => event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame,
    browser: null, browserPromise: null, documents: null, chatgptAccount: null, acceptanceOutput: null,
    profile: { dataRoot: '/unused-no-persistence' }, evidenceWrites: Promise.resolve(),
    fs: { writeFile: async () => events.push('evidence') },
    runtime: { stop: async () => { events.push('stop'); return receipt; },
      restart: async () => events.push('restart'), getEvidence: () => [] },
    network: { setEnabled: () => events.push('network'), getEvidence: () => ({}) },
    dialog: { showMessageBox: async (_window, value) => { dialogs.push(value); return { response: 1 }; } },
    transitionStep, authorizeTransition, validateObservation,
  });
  vm.runInContext(between(mainSource, 'const observations = new Map();', 'function transitionNotice('), main);
  for (const name of ['transitionNotice', 'message', 'writeEvidence', 'shutdown', 'change']) {
    const source = mainSource.match(new RegExp('^(?:async )?function ' + name + '\\([^]*?^\\}', 'm'));
    assert.ok(source, 'actual application-main function: ' + name);
    vm.runInContext(source[0], main);
  }
  const preload = vm.createContext({
    document: f.host.document,
    contextBridge: { exposeInMainWorld: (name, value) => { f.host[name] = value; } },
    ipcRenderer: { on: (channel, callback) => rendererHandlers.set(channel, callback),
      send(channel, id, value) {
        if (channel === 'ip-application-observed') replies.push(clone(value));
        else { assert.equal(channel, 'ip-application-packaging-closed'); departureReplies.push(clone(value)); }
        mainHandlers.get(channel)({ sender: window.webContents, senderFrame: window.webContents.mainFrame }, id, clone(value));
      } },
  });
  vm.runInContext(between(preloadSource, 'let observe = null;', 'let transitionNotice = null;'), preload);
  const registration = html.match(/window\.InspectorProNativeApplication\.registerLifecycleObserver\(_desktopObserveApplication\);/);
  assert.ok(registration, 'actual index observer registration');
  vm.runInContext(registration[0], f.hostContext);
  return Object.assign(f, { main, events, replies, dialogs, departureReplies, mainHandlers, rendererHandlers, nativeWindow: window, closed: () => destroyed });
}

for (const kind of ['close', 'reload', 'restart']) {
  for (const [name, mutate] of [
    ['mounted saved editor', f => { f.frames.push(f.frame); }],
    ['unapplied fields', f => { f.frames.push(f.frame); f.childState.formDirty = true; }],
    ['selected file', f => { f.frames.push(f.frame); f.files.push({ files: [{}] }); }],
    ['busy request', f => { f.frames.push(f.frame); f.childState.busy = true; }],
    ['host admission', f => { f.hostContext._packagingActiveTurn = { preparing: true }; }],
    ['host release', f => { f.hostContext._packagingReleasePromise = Promise.resolve(); }],
  ]) test('actual application IPC ' + kind + ' blocks ' + name + ' before native effects', async () => {
    const f = applicationFixture(); mutate(f);
    await f.main.change(kind);
    assert.deepEqual(f.events, []); assert.equal(f.closed(), false);
    assert.equal(f.replies.length, 1); assert.equal(f.replies[0].pending, true);
    assert.ok(f.replies[0].affected.includes('packaging'));
    assert.equal(f.dialogs.some(value => value.title === 'Unsaved work'), false);
  });
}

for (const [name, mutate] of [
  ['host getter', f => { delete f.host.InspectorProPackagingHost.getDesktopLifecycleObservation; }],
  ['child getter', f => { f.child.InspectorProPackaging = {}; f.frames.push(f.frame); }],
  ['observation module', f => { delete f.host.InspectorProDesktopWorkflowObservation; }],
  ['complete iframe', f => { f.frames.push(f.frame); f.childDocument.readyState = 'loading'; }],
]) test('actual application preload sends unavailable rather than clean when missing ' + name, async () => {
  const f = applicationFixture(); mutate(f);
  await f.main.change('close'); await f.main.change('restart');
  assert.deepEqual(f.replies, [null, null]); assert.deepEqual(f.events, []);
  assert.equal(f.closed(), false);
});

test('actual application second observation rejects packaging work introduced after clean preflight', async () => {
  const f = applicationFixture({ beforeObservation: (state, count) => {
    if (count === 2) state.hostContext._packagingReleasePromise = Promise.resolve();
  } });
  await f.main.change('close');
  assert.equal(f.replies.length, 2);
  assert.equal(f.replies[0].pending, false); assert.equal(f.replies[1].pending, true);
  assert.deepEqual(f.events, []); assert.equal(f.closed(), false);
});

test('actual application empty observation still permits close and requires fresh IPC replies', async () => {
  const f = applicationFixture(); await f.main.change('close');
  assert.equal(f.closed(), true); assert.equal(f.replies.length, 2);
  assert.ok(f.events.includes('stop')); assert.ok(f.events.includes('destroy'));
});

test('application observation accepts all eleven workflows plus facility within the native limit', async () => {
  const f = applicationFixture();
  f.hostContext._desktopInspectOtherWorkflows = () => Object.fromEntries(
    Object.keys(observation.WORKFLOWS).map(id => [id, { ...empty(), pending: true }]));
  f.hostContext._trainFacilitySheets = { observation: () => ({ dirty: false, busy: false, pending: true }) };
  await f.main.change('close');
  assert.equal(f.replies[0].affected.length, 12);
  assert.match(f.dialogs[0].message, /Packaging & Shipping is open.*Document > Close Packaging/);
  assert.deepEqual(f.events, []);
});

function departureFixture(options = {}) {
  const f = applicationFixture(options), context = f.hostContext;
  f.frames.push(f.frame);
  context.state.activeTab = 'training'; context.trainingState.type = 'packaging_shipping';
  f.host.document.documentElement = { inert: !!options.frozen };
  context.location = f.host.location; context.URL = URL;
  f.host.document.getElementById = id => id === 'packagingWorkspaceFrame' ? f.frames[0] || null : null;
  f.host.document.querySelectorAll = selector => selector === '#packagingWorkspaceFrame' ? [...f.frames] : [];
  context._trainIsPlantProcessMode = () => false;
  context._desktopRestorePartPanel = () => {};
  context.renderViewport = () => { f.frames.splice(0); f.frame.isConnected = false; };
  f.prompts = [];
  f.childContext.confirm = message => { f.prompts.push(message); return options.discard === true; };
  for (const name of ['_packagingEditorUI', '_packagingCloseWorkspace', '_packagingConfirmLeave', 'switchTab']) {
    const source = html.match(new RegExp('^        function ' + name + '\\([^]*?^        \\}', 'm'));
    assert.ok(source, name); vm.runInContext(source[0], context);
  }
  f.host.InspectorProNativeApplication.registerPackagingClose(context._packagingCloseWorkspace);
  f.main.backendUnavailable = !!options.frozen;
  return f;
}

test('native menu has an outside-document Close Packaging command and the profile presence enables the pilot', () => {
  let invoked = 0, menu;
  vm.runInNewContext(mainSource.match(/Menu\.setApplicationMenu\(Menu\.buildFromTemplate\(\[[^]*?\]\)\);/)[0], {
    Menu: { buildFromTemplate: value => value, setApplicationMenu: value => { menu = value; } },
    profile: {}, closePackaging: () => invoked++,
  });
  menu.find(row => row.label === 'Document').submenu.find(row => row.label === 'Close Packaging').click();
  assert.equal(invoked, 1);
  const start = between(mainSource, '  const url = new URL(profile.origin);', '  await window.loadURL(url.href);');
  for (const config of [undefined, { schemaVersion: 1, dependencyRoot: 'local-packages' }]) {
    const result = vm.runInNewContext(start + '\nurl.href', { URL, profile: {
      origin: 'http://127.0.0.1:8180', startupLayoutId: 'fl-local', packagingRuntime: config } });
    const url = new URL(result);
    assert.equal(url.searchParams.get('packagingPilot'), config ? '1' : null);
    assert.equal(url.searchParams.get('facilityLayoutId'), 'fl-local');
  }
  assert.match(html, /menu\('facilityExportPdf', 'Document', \['new', 'open', 'undo', 'redo', 'reload', 'pdf', 'close'\]\)/);
});

test('backend interruption notice explains how to reveal the native menu while the document is inert', () => {
  const events = [], notices = [];
  const context = vm.createContext({
    state: { status: 'interrupted' }, backendUnavailable: false,
    window: { isDestroyed: () => false, webContents: { send: (...args) => events.push(args) } },
    network: { setEnabled: value => events.push(['network', value]) },
    message: (title, detail) => notices.push({ title, detail }),
  });
  vm.runInContext(between(mainSource, "    if (state.status === 'interrupted'", '  }});'), context);
  assert.equal(context.backendUnavailable, true);
  assert.deepEqual(events, [['network', false], ['ip-application-freeze', true]]);
  assert.equal(notices.length, 1);
  assert.match(notices[0].detail, /Press Alt, then Document > Close Packaging/);
  assert.match(notices[0].detail, /Unsaved or unresolved packaging work stays blocked; draft recovery is not available/);
});

test('saved backend-loss native departure unmounts without unfreezing, then fresh close succeeds', async () => {
  const f = departureFixture({ frozen: true });
  await f.main.change('restart');
  assert.deepEqual(f.events, []); assert.equal(f.read().pending, true);
  assert.equal(await f.main.closePackaging(), true);
  assert.equal(f.frames.length, 0); assert.equal(f.hostContext.state.activeTab, 'drawing');
  assert.equal(f.host.document.documentElement.inert, true);
  assert.equal(f.main.backendUnavailable, true);
  assert.deepEqual(f.events, []); assert.deepEqual(f.prompts, []); assert.equal(f.closed(), false);
  const count = f.replies.length;
  await f.main.change('close');
  assert.equal(f.replies.length, count + 2); assert.equal(f.closed(), true);
});

test('saved backend-loss departure permits separately requested restart through normal guards', async () => {
  const f = departureFixture({ frozen: true });
  assert.equal(await f.main.closePackaging(), true);
  await f.main.change('restart');
  assert.ok(f.events.includes('restart')); assert.equal(f.main.backendUnavailable, false);
});

for (const [name, mutate] of [
  ['draft', f => { f.childState.draft.dirty = true; }],
  ['unapplied fields', f => { f.childState.formDirty = true; }],
  ['address', f => { f.addresses.origin.street1 = 'session-only'; }],
  ['selected file', f => { f.files.push({ files: [{ name: 'selected.glb' }] }); }],
  ['request', f => { f.childState.busy = true; }],
  ['Sage lock', f => { f.childState.sage.locked = true; }],
  ['admission without lock', f => { f.childState.sage.admission = {}; }],
  ['reconciliation', f => { f.childState.sage.closing = Promise.resolve(); }],
  ['conflict', f => { f.childState.conflict = true; }],
  ['dialog', f => { f.dialog = {}; }],
  ['host turn', f => { f.hostContext._packagingActiveTurn = {}; }],
  ['host release', f => { f.hostContext._packagingReleasePromise = Promise.resolve(); }],
  ['unavailable adapter', f => { delete f.child.InspectorProPackaging; }],
  ['loading frame', f => { f.childDocument.readyState = 'loading'; }],
]) test('backend-loss departure retains ' + name + ' without discard or Sage release', async () => {
  const f = departureFixture({ frozen: true, discard: true }); mutate(f);
  f.host.InspectorProPackagingHost.release = () => assert.fail('No offline admission release');
  assert.equal(await f.main.closePackaging(), false);
  assert.equal(f.frames.length, 1); assert.equal(f.hostContext.state.activeTab, 'training');
  assert.equal(f.host.document.documentElement.inert, true);
  assert.equal(f.main.backendUnavailable, true);
  assert.deepEqual(f.events, []); assert.deepEqual(f.prompts, []); assert.equal(f.closed(), false);
});

test('preload enforces clean-only on an inert document even without the main flag', async () => {
  const f = departureFixture({ frozen: true, discard: true });
  f.main.backendUnavailable = false; f.childState.draft.dirty = true;
  assert.equal(await f.main.closePackaging(), false);
  assert.equal(f.frames.length, 1); assert.deepEqual(f.prompts, []);
});

test('healthy Close Packaging confirms file-only drafts and preserves Cancel', () => {
  for (const discard of [false, true]) {
    const f = departureFixture({ discard }); f.files.push({ files: [{ name: 'artwork.png' }] });
    assert.equal(f.host.InspectorProPackagingHost.closeWorkspace(), discard);
    assert.equal(f.frames.length, discard ? 0 : 1);
    assert.equal(f.prompts.length, 1); assert.match(f.prompts[0], /selected files/);
  }
});

test('healthy Close Packaging waits for Sage release, rechecks unsaved work, and retains failure', async () => {
  for (const success of [false, true]) {
    const f = departureFixture({ discard: false });
    f.childState.sage.locked = true;
    let resolve, reject;
    const release = new Promise((yes, no) => { resolve = yes; reject = no; });
    f.host.InspectorProPackagingHost.release = () => release;
    assert.equal(f.host.InspectorProPackagingHost.closeWorkspace(), false);
    assert.equal(f.frames.length, 1);
    if (success) {
      f.childState.sage.locked = false; f.childState.formDirty = true; resolve();
    } else reject(new Error('Reconciliation failed'));
    await new Promise(done => setImmediate(done));
    assert.equal(f.frames.length, 1);
    assert.equal(f.prompts.length, success ? 1 : 0);
  }
});

test('healthy Close Packaging completes only after successful Sage cancellation and reconciliation', async () => {
  const f = departureFixture(); f.childState.sage.locked = true;
  let resolve;
  const release = new Promise(done => { resolve = done; });
  f.host.InspectorProPackagingHost.release = () => release;
  assert.equal(f.host.InspectorProPackagingHost.closeWorkspace(), false);
  assert.equal(f.frames.length, 1);
  f.childState.sage.locked = false; resolve();
  await new Promise(done => setImmediate(done));
  assert.equal(f.frames.length, 0); assert.equal(f.hostContext.state.activeTab, 'drawing');
  assert.deepEqual(f.prompts, []); assert.deepEqual(f.events, []);
});

test('failed native IPC send clears its timer and permits a new departure attempt', async () => {
  const f = departureFixture({ frozen: true });
  const send = f.nativeWindow.webContents.send;
  let cleared = 0;
  f.main.setTimeout = () => 1; f.main.clearTimeout = () => cleared++;
  f.nativeWindow.webContents.send = (channel, value) => {
    if (channel === 'ip-application-close-packaging') throw new Error('Renderer unavailable');
    return send(channel, value);
  };
  assert.equal(await f.main.closePackaging(), false); assert.equal(cleared, 1);
  assert.equal(f.main.transition, false); assert.equal(f.frames.length, 1);
  f.nativeWindow.webContents.send = send;
  assert.equal(await f.main.closePackaging(), true);
});

test('native departure refuses a forged acknowledgement, times out and ignores late replies', async () => {
  const f = departureFixture({ frozen: true, dropDeparture: true });
  let timeout;
  f.main.setTimeout = callback => { timeout = callback; return 1; }; f.main.clearTimeout = () => {};
  const pending = f.main.closePackaging();
  const handler = f.mainHandlers.get('ip-application-packaging-closed');
  handler({ sender: {}, senderFrame: {} }, 'observation-0', { closed: true });
  assert.equal(f.main.transition, 'packaging-close');
  timeout(); assert.equal(await pending, false);
  handler({ sender: f.nativeWindow.webContents, senderFrame: f.nativeWindow.webContents.mainFrame },
    'observation-0', { closed: true });
  assert.equal(f.frames.length, 1); assert.deepEqual(f.events, []);
  f.rendererHandlers.get('ip-application-close-packaging')({}, { id: 'expired', expiresAt: Date.now() - 1, cleanOnly: true });
  assert.equal(f.frames.length, 1); assert.equal(f.departureReplies.length, 0);
});

test('native departure reobserves and cannot claim success while host work remains', async () => {
  const f = departureFixture({ frozen: true, beforeObservation: state => {
    state.hostContext._packagingReleasePromise = Promise.resolve();
  } });
  assert.equal(await f.main.closePackaging(), false);
  assert.equal(f.read().pending, true); assert.deepEqual(f.events, []);
});

test('PDF action reports request dispatch, not unconfirmed native download success', async () => {
  const messages = [], actions = [];
  const context = vm.createContext({ state: { draft: { document: { revision: 3 } } }, hasDraft: () => false,
    docPath: () => '/documents/pkg_saved', working: async (_message, action) => action(),
    request: async url => { assert.equal(url, '/documents/pkg_saved/report.pdf?revision=3'); return {}; },
    URL: { createObjectURL: () => 'blob:owned', revokeObjectURL() {} },
    element: () => ({ click: () => actions.push('download-request'), remove() {} }),
    document: { body: { append() {} } }, setTimeout() {}, notify: message => messages.push(message) });
  vm.runInContext(between(packagingSource, 'async function downloadPDF()', '\nfunction '), context);
  await context.downloadPDF();
  assert.deepEqual(actions, ['download-request']); assert.deepEqual(messages, ['PDF export requested.']);
});
