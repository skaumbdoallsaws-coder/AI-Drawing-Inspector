'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const promises = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const vm = require('node:vm');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const Session = require('../../static/facility_layout_session.js');
const { createFacilityRecoveryAdapter, assertFacilityRuntimeAuthorization } = require('../src/facility-recovery-adapter.cjs');
const { createFacilityManagedRecovery } = require('../src/facility-managed-recovery.cjs');
const project = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(project, 'static/desktop_runtime_bridge.js'), 'utf8');
const base = JSON.parse(fs.readFileSync(path.join(project, 'tests/fixtures/facility_layout/empty_cell.json'), 'utf8'));
const clone = value => JSON.parse(JSON.stringify(value));
const hash = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
function runtime() { return { schemaVersion: 1, mode: 'desktop-managed', identity: { backendId: 'backend', storeId: 'store', principalId: 'principal' },
  owner: { sessionId: 'session', ownerId: 'owner' }, instanceId: 'process-one', origin: 'http://127.0.0.1:8099',
  document: { tenantId: 'local', siteId: 'site-local', documentId: base.layoutId },
  capabilities: { generalEditing: false, researchBrowsing: false, facilityAcceptance: true, save: false } }; }
const authorization = value => ({ schemaVersion: 1, mode: 'desktop-managed', verified: true, facilityAcceptance: true,
  identity: clone(value.identity), document: clone(value.document), owner: clone(value.owner), instanceId: value.instanceId });
function fixture(options = {}) {
  let handler, installed = false, attached = false, state = runtime(), reads = 0, writes = 0;
  const records = [], clears = [], calls = [], element = { id: 'trainFacilityLayoutAuthoring', isConnected: true }, legacy = new Map();
  let saves = 0;
  const session = Session.createSession({ previewOperations: options.preview || (async () => { throw new Error('Unexpected preview'); }),
    applyOperations: async () => { saves++; throw new Error('Save transport reached'); } });
  session.load(options.initial || { layout: clone(base), revision: hash(base) });
  const install = session.installDesktopRecovery;
  const observedSession = { ...session, installDesktopRecovery: hooks => { installed = true; return install(hooks); } };
  const app = { ready: options.ready || Promise.resolve(), session: observedSession, getState: () => ({ destroyed: options.destroyed === true }) };
  const native = {
    async getRuntime() { reads++; return clone(options.getRuntime ? options.getRuntime(reads, state) : state); },
    onLifecycleRequest(fn) { assert.equal(handler, undefined); handler = fn; calls.push('handler'); return () => { handler = undefined; calls.push('unsubscribe'); }; },
    async attachFacility(binding) {
      calls.push('attach'); assert.equal(installed, true); assert.equal(typeof handler, 'function'); attached = true;
      if (options.attach) return options.attach(binding, rpc);
      const snapshot = await rpc('snapshot');
      await rpc('setStartupRecoveryGate', { blocked: false, expectedRendererGeneration: snapshot.rendererGeneration, expectedStateSequence: snapshot.stateSequence });
      return { ready: true, recoveryRequired: false, capabilities: { facilityAcceptance: true } };
    },
    async persistOperation(record) { records.push(clone(record)); }, async clearOperation(record) { clears.push(clone(record)); },
  };
  const context = vm.createContext({ InspectorProDesktop: options.browser ? undefined : native,
    sessionStorage: { getItem: key => legacy.has(key) ? legacy.get(key) : null, setItem: () => { writes++; }, removeItem: () => { writes++; } } });
  vm.runInContext(source, context);
  function rpc(method, args, control = { assertCurrent() {} }) {
    const envelope = handler({ requestId: 'request', method, args }, control);
    if (envelope.ok !== true) throw Object.assign(new Error(envelope.error.code), envelope.error);
    return clone(envelope.result);
  }
  return { bridge: context.InspectorProDesktopRuntimeBridge, app, element, session, native, state,
    options: { siteId: 'site-local', layoutId: base.layoutId, externalCommandSurface: true }, records, clears, calls, legacy, rpc,
    get installed() { return installed; }, get attached() { return attached; }, get saves() { return saves; }, get writes() { return writes; } };
}

test('ordinary browser options and existing session behavior remain unchanged', async () => {
  const f = fixture({ browser: true });
  assert.equal(await f.bridge.prepareFacilityOptions(f.options), f.options);
  assert.equal((await f.bridge.attachFacility(f.app, f.element, f.options)).attached, false);
  assert.equal(f.installed, false); assert.equal(f.attached, false);
});

test('read-only runtime without an acceptance document renders without installing or attaching recovery authority', async () => {
  const f = fixture({ getRuntime: (_reads, value) => ({ ...value, document: null, capabilities: { ...value.capabilities, facilityAcceptance: false } }) });
  const options = await f.bridge.prepareFacilityOptions(f.options);
  const result = await f.bridge.attachFacility(f.app, f.element, options);
  assert.equal(result.readOnly, true); assert.equal(result.attached, false);
  assert.equal(f.installed, false); assert.equal(f.attached, false);
  assert.deepEqual(f.calls, []);
});

test('desktop installs only after ready and registers guarded real facade before reentrant native attach', async () => {
  let release; const ready = new Promise(resolve => { release = resolve; });
  const f = fixture({ ready }); const options = await f.bridge.prepareFacilityOptions(f.options);
  assert.equal(options.externalCommandSurface, true); assert.equal(options.sessionId, f.state.owner.sessionId);
  assert.equal(f.options.externalCommandSurface, true);
  const work = f.bridge.attachFacility(f.app, f.element, options);
  await Promise.resolve(); assert.equal(f.installed, false); assert.equal(f.attached, false);
  release(); assert.equal((await work).attached, true);
  assert.equal(f.element.id, 'trainFacilityLayoutAuthoring');
  assert.deepEqual(f.calls, ['handler', 'attach']);
  assert.equal(f.rpc('snapshot').startupRecoveryPending, false);
  await assert.rejects(f.session.save(), { code: 'facility_desktop_save_disabled' });
  assert.equal(f.saves, 0);
});

test('legacy pending or malformed storage is retained and fails closed before hook installation', async () => {
  for (const value of ['', '{malformed', '{"transactionId":"pending"}']) {
    const f = fixture(); const key = 'InspectorPro:facility-design-undo:site-local:' + base.layoutId; f.legacy.set(key, value);
    await assert.rejects(f.bridge.prepareFacilityOptions(f.options), { code: 'desktop_runtime_legacy_recovery_required' });
    assert.equal(f.legacy.get(key), value); assert.equal(f.writes, 0); assert.equal(f.installed, false);
  }
});

test('runtime identity changes, legacy data appearing during mount and failed attach cannot enable work', async () => {
  const changed = fixture({ getRuntime: (reads, value) => reads === 1 ? value : { ...value, instanceId: 'different-process' } });
  const options = await changed.bridge.prepareFacilityOptions(changed.options);
  await assert.rejects(changed.bridge.attachFacility(changed.app, changed.element, options), { code: 'desktop_runtime_identity_changed' });
  assert.equal(changed.installed, false);
  const legacy = fixture(), next = await legacy.bridge.prepareFacilityOptions(legacy.options);
  legacy.legacy.set('InspectorPro:facility-design-undo:site-local:' + base.layoutId, 'late');
  await assert.rejects(legacy.bridge.attachFacility(legacy.app, legacy.element, next), { code: 'desktop_runtime_legacy_recovery_required' });
  const rejected = fixture({ attach: async () => ({ ready: false }) });
  await assert.rejects(rejected.bridge.attachFacility(rejected.app, rejected.element,
    await rejected.bridge.prepareFacilityOptions(rejected.options)), { code: 'desktop_runtime_attach_rejected' });
  assert.equal(rejected.calls.at(-1), 'unsubscribe');
  assert.throws(() => rejected.session.clearSelection(), { code: 'facility_desktop_recovery_unresolved' });
});

test('field-order equivalent identity is accepted while stale controls, requests and generations cannot mutate session', async () => {
  const f = fixture({ getRuntime: (_reads, value) => ({ ...value, identity: { principalId: value.identity.principalId, storeId: value.identity.storeId, backendId: value.identity.backendId } }) });
  await f.bridge.attachFacility(f.app, f.element, await f.bridge.prepareFacilityOptions(f.options));
  const before = f.rpc('snapshot');
  assert.throws(() => f.rpc('freeze', { intentId: 'cancelled', rendererGeneration: before.rendererGeneration, stateSequence: before.stateSequence },
    { assertCurrent() { throw Object.assign(new Error('cancelled'), { code: 'desktop_runtime_request_cancelled' }); } }), { code: 'desktop_runtime_request_cancelled' });
  assert.throws(() => f.rpc('save'), { code: 'desktop_runtime_request_rejected' });
  assert.throws(() => f.rpc('freeze', { intentId: 'wrong', rendererGeneration: 'wrong', stateSequence: before.stateSequence }), { code: 'facility_desktop_stale_state' });
  assert.deepEqual(f.rpc('snapshot'), before);
  f.element.isConnected = false;
  assert.throws(() => f.rpc('snapshot'), { code: 'desktop_runtime_facility_unavailable' });
});

test('verified runtime authorization binds exact identity, document, owner and process', () => {
  const value = runtime(), auth = authorization(value);
  assert.doesNotThrow(() => assertFacilityRuntimeAuthorization({ authorizedDesktopRuntime: auth }, value));
  for (const change of [{ verified: false }, { facilityAcceptance: false }, { mode: 'browser' }, { instanceId: '' }]) {
    assert.throws(() => assertFacilityRuntimeAuthorization({ authorizedDesktopRuntime: { ...auth, ...change } }, value), { code: 'facility_runtime_not_authorized' });
  }
  for (const change of [{ identity: { ...auth.identity, storeId: 'foreign' } }, { document: { ...auth.document, documentId: 'foreign' } },
    { owner: { ...auth.owner, ownerId: 'foreign' } }, { instanceId: 'foreign-process' }]) {
    assert.throws(() => assertFacilityRuntimeAuthorization({ authorizedDesktopRuntime: { ...auth, ...change } }, value), { code: 'facility_runtime_binding_mismatch' });
  }
});

test('real session and kernel via runtime bridge retain exact two-edit draft, selection and Undo on native Close Cancel; Save stays disabled', async t => {
  const program = ['import json,sys', 'from ai_inspector.facility_layout.canonical import layout_revision',
    'from ai_inspector.facility_layout.operations import apply_facility_layout_operations', 'r=json.load(sys.stdin)',
    'v=apply_facility_layout_operations(r["layout"],r["operations"],base_revision=layout_revision(r["layout"]))',
    'print(json.dumps({"layout":v["document"],"revision":layout_revision(v["document"]),"changed":v["changed"]}))'].join('\n');
  const kernel = (layout, operations) => JSON.parse(execFileSync(process.env.CONSTRUCTION_TEST_PYTHON || 'python', ['-c', program],
    { cwd: project, input: JSON.stringify({ layout, operations }), encoding: 'utf8', timeout: 20000 }));
  const initial = kernel(base, [{ op: 'add_zone', zone: { zoneId: 'zn-runtime', label: 'Original', zoneType: 'workcell',
    boundary: [{ x: 0, z: 0 }, { x: 4, z: 0 }, { x: 4, z: 4 }, { x: 0, z: 4 }], floorElevation: 0, anchors: [], evidence: [] } }]);
  const directory = await promises.mkdtemp(path.join(os.tmpdir(), 'runtime-facility-'));
  t.after(() => promises.rm(directory, { recursive: true, force: true }));
  let adapter;
  const f = fixture({ initial, preview: async request => kernel(initial.layout, request.operations),
    attach: async (_binding, rpc) => {
      const editor = Object.fromEntries(['snapshot', 'freeze', 'unfreeze', 'restoreRecovery', 'acceptReconciliation', 'setStartupRecoveryGate']
        .map(method => [method, (args, control) => rpc(method, args, control)]));
      const value = runtime();
      adapter = await createFacilityRecoveryAdapter({ authorizedDesktopRuntime: authorization(value), identity: value.identity,
        document: value.document, owner: value.owner, recoveryDirectory: directory, editor,
        lookupOperation: async () => { throw new Error('No transaction should be looked up'); },
        commitLifecycle: async () => { throw new Error('Cancel cannot commit'); } });
      // Managed coordinator uses the same explicit production authorizer.
      const coordinator = createFacilityManagedRecovery({ authorizedDesktopRuntime: authorization(value), expectedRuntime: value,
        adapter, editor, restartBackend: async () => {}, readRuntime: async () => value });
      assert.equal(coordinator.getState().status, 'idle');
      return { ready: true, recoveryRequired: false, capabilities: value.capabilities };
    } });
  await f.bridge.attachFacility(f.app, f.element, await f.bridge.prepareFacilityOptions(f.options));
  f.session.select('zn-runtime');
  await f.session.editZoneLabel('zn-runtime', 'Edit one'); await f.session.editZoneLabel('zn-runtime', 'Edit two');
  const before = f.rpc('snapshot'); assert.equal(before.editorFrame.batches.length, 2);
  assert.equal(f.session.getState().canSave, false);
  const intent = await adapter.prepare('close'); assert.equal(intent.status, 'needsDecision');
  assert.throws(() => f.session.clearSelection(), { code: 'facility_desktop_frozen' });
  assert.equal((await adapter.cancel(intent.intentId)).status, 'cancelled');
  assert.deepEqual(f.rpc('snapshot'), before);
  assert.equal((await adapter.listRecovery()).length, 0);
  await f.session.undo(); assert.equal(f.rpc('snapshot').editorFrame.draftLayout.zones[0].label, 'Edit one');
  await f.session.redo(); assert.equal(f.rpc('snapshot').editorFrame.draftLayout.zones[0].label, 'Edit two');
  await assert.rejects(f.session.save(), { code: 'facility_desktop_save_disabled' });
  assert.equal(f.saves, 0); assert.equal(f.writes, 0);
});
