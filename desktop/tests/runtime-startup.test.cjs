'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const Session = require('../../static/facility_layout_session.js');
const root = path.resolve(__dirname, '../..');
const bridgeSource = fs.readFileSync(path.join(root, 'static/desktop_runtime_bridge.js'), 'utf8');
const indexSource = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
const base = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/facility_layout/empty_cell.json'), 'utf8'));
const clone = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
function runtime() {
  return { schemaVersion: 1, status: 'ready', mode: 'desktop-managed', origin: 'http://127.0.0.1:8099',
    identity: { backendId: 'backend', storeId: 'store', principalId: 'principal' },
    owner: { ownerId: 'owner', sessionId: 'session' }, instanceId: 'process-one',
    document: { tenantId: 'local', siteId: 'site-local', documentId: base.layoutId },
    capabilities: { facilityAcceptance: true, generalEditing: false, researchBrowsing: false, save: false } };
}
function indexFunction(name) {
  const expression = new RegExp('^        (?:async )?function ' + name + '\\([^]*?^        \\}', 'm');
  const found = indexSource.match(expression);
  assert.ok(found, 'Actual index function is present: ' + name);
  return found[0];
}
function fixture(options = {}) {
  const value = options.runtime || runtime(), events = [];
  let handler, attaches = 0, activations = 0, saves = 0;
  const session = Session.createSession({ previewOperations: async () => { throw new Error('Unexpected edit'); },
    applyOperations: async () => { saves++; throw new Error('Unexpected Save'); } });
  session.load({ layout: clone(base), revision: crypto.createHash('sha256').update(JSON.stringify(base)).digest('hex') });
  const element = { id: 'trainFacilityLayoutAuthoring', isConnected: true }, app = { session, ready: Promise.resolve(), getState: () => ({ destroyed: false }) };
  function rpc(method, args) {
    const envelope = handler({ method, args }, { assertCurrent() {} });
    if (!envelope.ok) throw Object.assign(new Error(envelope.error.code), envelope.error);
    return clone(envelope.result);
  }
  const native = {
    getRuntime: async () => { events.push('runtime'); return clone(value); },
    onLifecycleRequest(callback) { handler = callback; return () => { handler = null; }; },
    async attachFacility(binding) {
      attaches++; events.push('attach');
      assert.equal(binding.document.documentId, base.layoutId);
      assert.equal(binding.owner.sessionId, value.owner.sessionId);
      if (options.attachError) throw options.attachError;
      const current = rpc('snapshot');
      if (!options.recoveryRequired) rpc('setStartupRecoveryGate', { blocked: false,
        expectedRendererGeneration: current.rendererGeneration, expectedStateSequence: current.stateSequence });
      return { ready: true, recoveryRequired: !!options.recoveryRequired, capabilities: value.capabilities };
    }, persistOperation: async () => { throw new Error('Startup may not persist operations'); },
    clearOperation: async () => { throw new Error('Startup may not clear operations'); },
  };
  const context = vm.createContext({ InspectorProDesktop: options.browser ? undefined : native, URLSearchParams,
    location: { origin: value.origin, search: options.search === undefined ? '?facilityLayoutId=' + base.layoutId : options.search },
    sessionStorage: { getItem: () => null }, console: { warn() {}, error() {} } });
  context.window = context;
  vm.runInContext(bridgeSource, context);
  const bridge = context.InspectorProDesktopRuntimeBridge;
  async function activateFacility(document) {
    activations++; events.push('activate');
    assert.deepEqual(clone(document), value.document);
    if (options.activationGate) await options.activationGate.promise;
    if (options.activationError) throw options.activationError;
    if (options.skipAttach) return true;
    const prepared = await bridge.prepareFacilityOptions({ siteId: 'site-local', layoutId: base.layoutId });
    const attached = await bridge.attachFacility(app, element, prepared);
    assert.equal(attached.attached, true);
    return options.mountResult === undefined ? true : options.mountResult;
  }
  return { bridge, context, value, events, session, app, element, activateFacility, rpc,
    start: () => bridge.startFacilityWorkspace({ activateFacility }),
    get attaches() { return attaches; }, get activations() { return activations; }, get saves() { return saves; } };
}

test('a facility query in an ordinary browser cannot activate managed startup', async () => {
  const f = fixture({ browser: true });
  await f.start();
  assert.equal(f.bridge.getStartupStatus().status, 'browser');
  assert.equal(f.activations, 0); assert.equal(f.attaches, 0); assert.deepEqual(f.events, []);
});

test('ready read-only native runtime without a document does not route or attach', async () => {
  const value = runtime(); value.document = null; value.capabilities.facilityAcceptance = false;
  const f = fixture({ runtime: value }); await f.start();
  assert.equal(f.bridge.getStartupStatus().status, 'read-only');
  assert.equal(f.activations, 0); assert.equal(f.attaches, 0);
});

test('startup rejects unready, malformed, unauthorized or mismatched bindings before activation', async t => {
  const cases = [
    ['starting', value => { value.status = 'starting'; }],
    ['wrong mode', value => { value.mode = 'browser'; }],
    ['no identity', value => { value.identity = null; }],
    ['missing owner', value => { value.owner.sessionId = ''; }],
    ['general editing', value => { value.capabilities.generalEditing = true; }],
    ['research browsing', value => { value.capabilities.researchBrowsing = true; }],
    ['Save capability', value => { value.capabilities.save = true; }],
    ['no facility capability', value => { value.capabilities.facilityAcceptance = false; }],
    ['no document', value => { value.document = null; }],
    ['query mismatch', () => {}, '?facilityLayoutId=unapproved-layout'],
    ['duplicate query', () => {}, '?facilityLayoutId=' + base.layoutId + '&facilityLayoutId=' + base.layoutId],
  ];
  for (const [name, change, search] of cases) await t.test(name, async () => {
    const value = runtime(); change(value); const f = fixture({ runtime: value, search });
    await assert.rejects(f.start());
    assert.equal(f.bridge.getStartupStatus().status, 'failed');
    assert.match(f.bridge.getStartupStatus().code, /^desktop_runtime_/);
    assert.equal(f.activations, 0); assert.equal(f.attaches, 0);
  });
});

test('exact or absent query routes the verified facility and attaches the actual session once', async t => {
  for (const search of ['', '?facilityLayoutId=' + base.layoutId]) await t.test(search || 'absent query', async () => {
    const f = fixture({ search }); await f.start();
    assert.equal(f.bridge.getStartupStatus().status, 'ready');
    assert.equal(f.bridge.getStartupStatus().documentId, base.layoutId);
    assert.equal(f.activations, 1); assert.equal(f.attaches, 1);
    assert.equal(f.rpc('snapshot').startupRecoveryPending, false);
    assert.equal(f.session.getState().canSave, false);
    await assert.rejects(f.session.save(), { code: 'facility_desktop_save_disabled' });
    assert.equal(f.saves, 0);
  });
});

test('concurrent and repeated startup calls share one activation and wait for actual attachment', async () => {
  const gate = deferred(), f = fixture({ activationGate: gate });
  let settled = false; const first = f.start().then(value => { settled = true; return value; });
  const second = f.start(); await flush();
  assert.equal(f.activations, 1); assert.equal(f.attaches, 0); assert.equal(settled, false);
  gate.resolve(); await Promise.all([first, second]); await f.start();
  assert.equal(f.activations, 1); assert.equal(f.attaches, 1);
});

test('mount return alone cannot claim readiness without a verified attachment', async () => {
  const f = fixture({ skipAttach: true });
  await assert.rejects(f.start());
  assert.equal(f.bridge.getStartupStatus().status, 'failed'); assert.equal(f.attaches, 0);
});

test('attached retained recovery can complete startup while the real session keeps editing and Save gated', async () => {
  const f = fixture({ recoveryRequired: true }); await f.start();
  assert.equal(f.bridge.getStartupStatus().status, 'ready');
  assert.equal(f.attaches, 1); assert.equal(f.rpc('snapshot').startupRecoveryPending, true);
  assert.throws(() => f.session.clearSelection(), { code: 'facility_desktop_recovery_unresolved' });
  assert.equal(f.session.getState().canSave, false);
  await assert.rejects(f.session.save(), { code: 'facility_desktop_save_disabled' });
  assert.equal(f.saves, 0);
});

test('typed activation or attachment failure remains terminal and never silently retries the mount', async t => {
  for (const field of ['activationError', 'attachError']) await t.test(field, async () => {
    const error = Object.assign(new Error('Sensitive error details must not become startup status'), { code: 'desktop_runtime_controlled_failure' });
    const f = fixture({ [field]: error });
    await assert.rejects(f.start(), { code: error.code });
    const status = clone(f.bridge.getStartupStatus());
    assert.equal(status.status, 'failed'); assert.equal(status.code, error.code);
    assert.doesNotMatch(JSON.stringify(status), /Sensitive/);
    await assert.rejects(f.start(), { code: error.code }); assert.equal(f.activations, 1);
  });
});

test('actual index activation applies facility subtype before one workflow render and returns its tracked mount', async () => {
  const gate = deferred(), events = [], context = vm.createContext({
    trainingState: { type: 'service', viewportMode: 'assembly3d' },
    state: { activeTab: 'drawing' },
    _trainFacilityLayoutAuthoringApp: null, _trainDesktopFacilityDocument: null,
    document: { getElementById: () => null, querySelector: () => null },
    _trainFacilityLayoutMountPromise: null,
    _trainApplyTrainingTypeDefaults(previous) { events.push('defaults:' + previous + ':' + context.trainingState.type); context.trainingState.viewportMode = 'facility_layout'; return true; },
    switchTab(tab) { events.push('tab:' + tab + ':' + context.trainingState.type); context.state.activeTab = tab; context._trainMountFacilityLayoutViewer(); },
    _trainMountFacilityLayoutViewerImpl() { events.push('mount'); return gate.promise; },
  });
  context.window = context;
  vm.runInContext(indexFunction('_trainMountFacilityLayoutViewer') + '\n' + indexFunction('_trainActivateDesktopFacilityWorkspace'), context);
  let settled = false;
  const work = context._trainActivateDesktopFacilityWorkspace(runtime().document).then(result => { settled = true; return result; });
  await flush();
  assert.deepEqual(events, ['defaults:service:facility_layout', 'tab:training:facility_layout', 'mount']);
  assert.equal(settled, false); gate.resolve(true); assert.equal(await work, true);
});

test('actual init waits for deferred profiles and assembly selection before managed facility routing', async () => {
  const profiles = deferred(), selection = deferred(), events = [];
  const context = vm.createContext({
    setupEventListeners: () => events.push('listeners'), renderFeatureScopeControls: () => {},
    fetch: async () => ({ json: () => profiles.promise }),
    state: {}, profileCountEl: {}, populateDropdown: () => {}, requestedAssemblyProfileId: 'assembly-request',
    partSearch: {}, assemblyContextAvailable: true,
    selectPartNumber: async () => { events.push('select-start'); await selection.promise; events.push('select-end'); },
    switchTab: tab => events.push('tab:' + tab), showError: () => {},
    _trainActivateDesktopFacilityWorkspace: () => { events.push('facility'); return Promise.resolve(true); },
    _desktopInspectOtherWorkflows: () => ({}),
    InspectorProDesktopRuntimeBridge: { startFacilityWorkspace: async ({ activateFacility, inspectOtherWorkflows }) => {
      assert.equal(inspectOtherWorkflows, context._desktopInspectOtherWorkflows);
      events.push('managed-start'); return activateFacility(); } },
    console: { error() {}, warn() {} },
  });
  context.window = context;
  vm.runInContext(indexFunction('init'), context);
  const work = context.init(); await flush(); assert.deepEqual(events, ['listeners']);
  profiles.resolve([{ part_number: 'assembly-request', part_name: 'Requested assembly', context_kind: 'assembly' }]);
  await flush(); assert.deepEqual(events, ['listeners', 'select-start']);
  selection.resolve(); await work;
  assert.deepEqual(events, ['listeners', 'select-start', 'select-end', 'tab:assembly', 'managed-start', 'facility']);
});

function mountFixture(options = {}) {
  const f = fixture({ search: options.search === undefined ? '' : options.search, recoveryRequired: options.recoveryRequired });
  let legacy = 0, created = 0, fit = 0, supplied;
  const requests = [], createdNodes = [];
  function element() {
    const value = { style: {}, isConnected: true, children: [], appendChild(child) { this.children.push(child); return child; } };
    createdNodes.push(value); return value;
  }
  const host = element();
  const bootstrap = { siteId: options.siteId || 'site-local', layoutId: 'fl-bootstrap-default',
    layout: { layout: { ...clone(base), layoutId: 'fl-bootstrap-default' }, revision: 'bootstrap-revision' },
    capabilities: { viewerV2: options.viewerV2 !== false }, assetCatalog: [], grid: {} };
  Object.assign(f.context, {
    document: { getElementById: id => id === 'trainViewportHost' ? host : null, createElement: () => element() },
    _trainFacilityAuthoringRuntimesReady: () => options.runtimesReady !== false,
    _trainDesktopFacilityDocument: options.browser ? null : clone(f.value.document),
    _trainFacilityLayoutAuthoringApp: null, _trainFacilityLayoutMountGeneration: 0,
    _trainFacilityRendererPool: null, _trainFacilityLayoutMountPromise: null,
    _trainIsFacilityLayoutMode: () => true,
    _trainDisposeFacilityLayoutAuthoring() { f.context._trainFacilityLayoutMountGeneration++; f.context._trainFacilityLayoutAuthoringApp = null; },
    _trainDisposeLiveAssemblyViewer: () => {},
    _trainMountLegacyFacilityLayoutViewer: () => { legacy++; return true; },
    _trainLoadFacilityThreeRuntime: async () => ({}),
    InspectorProFacilityLayout: { placementFootprint() {} }, InspectorProFacilityThree: {},
    InspectorProFacilityApp: { createFacilityLayoutApp(input) {
      created++; supplied = input;
      f.app.workspace = { root: input.root, executeCommand: async command => { assert.equal(command, 'fit'); fit++; } };
      f.app.destroy = () => {};
      return f.app;
    } },
    fetch: async url => {
      requests.push(url);
      if (options.fetchError) throw options.fetchError;
      return { ok: true, json: async () => url === '/api/facility-layout-bootstrap' ? bootstrap
        : { layout: clone(base), revision: 'requested-revision' } };
    },
  });
  vm.runInContext(indexFunction('_trainMountFacilityLayoutViewer') + '\n' + indexFunction('_trainMountFacilityLayoutViewerImpl'), f.context);
  return { ...f, requests, createdNodes,
    mount: () => f.context._trainMountFacilityLayoutViewer(),
    get legacy() { return legacy; }, get created() { return created; }, get fit() { return fit; }, get supplied() { return supplied; } };
}

test('actual mount uses the authorized document without a query and attaches before fitting', async () => {
  const f = mountFixture(); assert.equal(await f.mount(), true);
  assert.deepEqual(f.requests, ['/api/facility-layout-bootstrap', '/api/facility-layouts/site-local/' + base.layoutId]);
  assert.equal(f.supplied.layoutId, base.layoutId);
  assert.equal(f.supplied.initialReceipt.layout.layoutId, base.layoutId);
  assert.equal(f.supplied.sessionId, f.value.owner.sessionId);
  assert.equal(f.created, 1); assert.equal(f.fit, 1); assert.equal(f.legacy, 0);
  assert.equal(f.rpc('snapshot').startupRecoveryPending, false);
});

test('actual mount defers post-mount view changes when retained recovery remains unresolved', async () => {
  const f = mountFixture({ recoveryRequired: true }); assert.equal(await f.mount(), true);
  assert.equal(f.created, 1); assert.equal(f.fit, 0); assert.equal(f.legacy, 0);
  assert.equal(f.rpc('snapshot').startupRecoveryPending, true);
});

test('managed missing runtime, unavailable viewer, wrong bootstrap site and failed bootstrap never fall back to legacy', async t => {
  const cases = [
    ['runtime', { runtimesReady: false }, 'desktop_runtime_authoring_unavailable'],
    ['viewer', { viewerV2: false }, 'desktop_runtime_viewer_unavailable'],
    ['site', { siteId: 'foreign-site' }, 'desktop_runtime_bootstrap_site_mismatch'],
    ['bootstrap error', { fetchError: Object.assign(new Error('Controlled bootstrap failure'), { code: 'desktop_runtime_controlled_bootstrap' }) }, 'desktop_runtime_controlled_bootstrap'],
  ];
  for (const [name, options, code] of cases) await t.test(name, async () => {
    const f = mountFixture(options); await assert.rejects(f.mount(), { code });
    assert.equal(f.legacy, 0); assert.equal(f.created, 0); assert.equal(f.fit, 0);
    if (name === 'site') assert.deepEqual(f.requests, ['/api/facility-layout-bootstrap']);
  });
});

test('ordinary browser unavailable-runtime legacy fallback retains its existing behavior', async () => {
  const f = mountFixture({ browser: true, runtimesReady: false });
  assert.equal(await f.mount(), true); assert.equal(f.legacy, 1); assert.equal(f.created, 0);
});

test('returning to Facility restores the retained root and docked playback without recreating the session', async t => {
  for (const suspended of [false, true]) await t.test('suspended=' + suspended, async () => {
    const f = mountFixture();
    const host = f.context.document.getElementById('trainViewportHost');
    const motionHost = { appendChild(node) { this.child = node; } };
    const getElement = f.context.document.getElementById;
    f.context.document.getElementById = id => id === 'trainFacilityMotionPlaybackHost' ? motionHost : getElement(id);
    const root = { parentNode: null }, session = { history: ['manual edit'] };
    const motionPanel = { hidden: false, getAttribute: () => 'true' };
    let resumed = 0, visibility = 0;
    f.context._trainFacilityLayoutAuthoringApp = {
      session, getState: () => ({ loaded: true, destroyed: false, suspended }),
      workspace: { root, motionPanel, options: { onMotionPanelVisibilityChange: () => visibility++ } },
      resume(node) { assert.equal(node, root); resumed++; },
    };
    assert.equal(await f.mount(), true);
    assert.equal(host.children.at(-1), root);
    assert.equal(motionHost.child, motionPanel);
    assert.equal(f.context._trainFacilityLayoutAuthoringApp.session, session);
    assert.equal(resumed, suspended ? 1 : 0); assert.equal(visibility, 1);
    assert.equal(f.created, 0); assert.deepEqual(f.requests, []);
  });
});

test('viewport replacement suspends the connected facility before removing its DOM', () => {
  const events = [];
  const context = vm.createContext({
    _save3DCameraState() {}, _saveAssemblyCameraState() {},
    ASSEMBLY_VIEWPORT_STATE_PERSISTENCE: false,
    state: { activeTab: 'dfm' },
    _trainFacilityLayoutAuthoringApp: { workspace: { root: { isConnected: true } }, suspend() { events.push('suspend'); } },
    viewportContent: { set innerHTML(value) { assert.equal(value, ''); events.push('clear'); }, appendChild() {} },
    updateAnnotationToolbarVisibility() {}, renderRibbon() { events.push('ribbon'); },
    document: { createElement: () => ({ style: {} }) },
  });
  vm.runInContext(indexFunction('renderViewport'), context);
  context.renderViewport();
  assert.deepEqual(events, ['suspend', 'clear', 'ribbon']);
});
