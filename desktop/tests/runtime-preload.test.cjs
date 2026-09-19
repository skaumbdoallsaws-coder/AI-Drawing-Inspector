'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/runtime-preload.cjs'), 'utf8');
const copy = value => JSON.parse(JSON.stringify(value));
const turn = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function fixture(options = {}) {
  class Element {
    constructor(id = '') { this.id = id; this.children = []; this.isConnected = true; this._inert = false; this.style = {}; }
    append(child) { if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1); this.children.push(child); child.parent = this; return child; }
    insertBefore(child, existing) { this.children.splice(this.children.indexOf(existing), 0, child); child.parent = this; }
    setAttribute() {}
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    get inert() { return this._inert; }
    set inert(value) { this._inert = value; }
  }
  const body = new Element('body'), outer = body.append(new Element('workspace'));
  const ribbon = outer.append(new Element('ribbon'));
  const commandbar = ribbon.append(new Element('facility-commandbar'));
  const commandButton = commandbar.append(new Element('pan'));
  const workflowSelector = ribbon.append(new Element('workflow-selector'));
  const assets = outer.append(new Element('trainFacilityLayoutAssets'));
  const theme = body.append(new Element('themeToggleBtn'));
  const facility = outer.append(new Element('trainFacilityLayoutAuthoring'));
  const edit = facility.append(new Element('edit')), chat = body.append(new Element('chat'));
  const listeners = new Map(), captures = new Map(), replies = [], invokes = [];
  let api;
  const observers = [];
  const ipcRenderer = {
    on(name, callback) { listeners.set(name, callback); },
    async invoke(name, ...args) {
      invokes.push({ name, args });
      if (options.invoke) return options.invoke(name, ...args);
      return { ready: true, recoveryRequired: false, capabilities: { facilityAcceptance: true } };
    },
    send(name, payload) { replies.push({ name, ...copy(payload) }); },
  };
  const context = vm.createContext({
    require(name) { assert.equal(name, 'electron'); return { ipcRenderer, contextBridge: { exposeInMainWorld(name, value) { assert.equal(name, 'InspectorProDesktop'); api = value; } } }; },
    process: { isMainFrame: options.mainFrame !== false, argv: options.noFlag ? [] : ['--inspectorpro-desktop-managed'] },
    HTMLElement: Element, AbortController, setTimeout, clearTimeout, Date,
    MutationObserver: class { constructor(fn) { observers.push(fn); } observe() {} },
    document: { body, querySelectorAll: selector => {
      if (!options.integrated) return [];
      if (selector === '.facility-layout-ribbon .facility-ribbon-commandbar') return options.duplicateSurface ? [commandbar, ribbon] : [commandbar];
      if (selector === '#trainFacilityLayoutAssets') return [assets];
      if (selector === '#themeToggleBtn') return [theme];
      return [];
    }, createElement: () => new Element(), addEventListener() {}, getElementById(id) {
      function find(node) { if (node.id === id && node.isConnected) return node; for (const child of node.children) { const result = find(child); if (result) return result; } }
      return find(body);
    } },
    window: { addEventListener(name, fn) { captures.set(name, fn); } },
  });
  vm.runInContext(source, context);
  let count = 0;
  async function command(method, args = {}, extra = {}) {
    const requestId = extra.requestId || 'request-' + (++count);
    listeners.get('desktop-runtime:facility-command')({}, { requestId, method, args, deadlineUnixMs: Date.now() + 1000, ...extra });
    await turn(); return { requestId, reply: replies.find(item => item.requestId === requestId) };
  }
  function blocked(node) {
    const ancestors = []; for (let parent = node; parent; parent = parent.parent) ancestors.push(parent);
    const result = { prevented: false, stopped: false, composedPath: () => ancestors,
      preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; } };
    captures.get('click')(result); assert.equal(result.prevented, result.stopped); return result.prevented;
  }
  return { api, body, outer, ribbon, commandbar, commandButton, workflowSelector, assets, theme,
    facility, edit, chat, replies, invokes, listeners, command, blocked, observe: () => observers.forEach(fn => fn()) };
}
function handler(request, control) { control.assertCurrent(); return { ok: true, result: { startupRecoveryPending: request.args?.blocked === true } }; }

test('managed main frame only exposes fixed API and begins entirely input locked', () => {
  assert.equal(fixture({ noFlag: true }).api, undefined);
  assert.equal(fixture({ mainFrame: false }).api, undefined);
  const f = fixture();
  assert.equal(f.outer.inert, true); assert.equal(f.chat.inert, true);
  assert.equal(f.blocked(f.edit), true);
  assert.equal(f.api.getCapabilities().save, false);
  assert.deepEqual(Object.keys(f.api).sort(), ['attachFacility', 'clearOperation', 'getCapabilities', 'getInputLockDiagnostics',
    'getRuntime', 'onLifecycleRequest', 'openResearch', 'persistOperation', 'requestClose', 'restartBackend'].sort());
});

test('verified attach unlocks exact facility path while ribbon, chat and replacement nodes stay blocked', async () => {
  const f = fixture(); f.api.onLifecycleRequest(handler); await f.api.attachFacility({ document: { documentId: 'layout' } });
  assert.equal(f.outer.inert, false); assert.equal(f.facility.inert, false);
  assert.equal(f.ribbon.inert, true); assert.equal(f.chat.inert, true);
  assert.equal(f.blocked(f.edit), false); assert.equal(f.blocked(f.ribbon), true);
  f.facility.isConnected = false; f.observe();
  assert.equal(f.outer.inert, true); assert.equal(f.blocked(f.edit), true);
  assert.equal(f.api.getInputLockDiagnostics().facilityInputAllowed, false);
});

test('non-HTML siblings receive native inert HTML ancestors without cloning their identity', async () => {
  const f = fixture();
  const svg = { id: 'svg-root', children: [], isConnected: true, contains(node) { return node === this; } };
  f.outer.append(svg); f.observe();
  f.api.onLifecycleRequest(handler); await f.api.attachFacility({});
  assert.notEqual(svg.parent, f.outer);
  assert.equal(svg.parent.inert, true); assert.equal(svg.parent.style.display, 'contents');
  assert.equal(svg.parent.children[0], svg);
  assert.equal(f.blocked(svg), true); assert.equal(f.blocked(f.edit), false);
});

test('integrated ribbon, asset library and theme share the exact facility recovery gate', async () => {
  const f = fixture({ integrated: true });
  f.api.onLifecycleRequest(handler);
  for (const node of [f.commandButton, f.assets, f.theme]) assert.equal(f.blocked(node), true);
  await f.api.attachFacility({});
  assert.equal(f.ribbon.inert, false);
  assert.equal(f.commandbar.inert, false);
  assert.equal(f.workflowSelector.inert, true);
  for (const node of [f.commandButton, f.assets, f.theme, f.edit]) assert.equal(f.blocked(node), false);
  for (const node of [f.ribbon, f.workflowSelector, f.chat]) assert.equal(f.blocked(node), true);
  await f.command('freeze', { intentId: 'close' });
  for (const node of [f.commandButton, f.assets, f.theme, f.edit]) assert.equal(f.blocked(node), true);
  await f.command('unfreeze', { intentId: 'close' });
  for (const node of [f.commandButton, f.assets, f.theme, f.edit]) assert.equal(f.blocked(node), false);
  await f.command('setStartupRecoveryGate', { blocked: true });
  assert.equal(f.blocked(f.commandButton), true);
  await f.command('setStartupRecoveryGate', { blocked: false });
  assert.equal(f.blocked(f.commandButton), false);
  f.facility.isConnected = false; f.observe();
  for (const node of [f.commandButton, f.assets, f.theme]) assert.equal(f.blocked(node), true);
});

test('replacement external surfaces do not inherit grants and ambiguous surfaces refuse attachment', async () => {
  const f = fixture({ integrated: true }); f.api.onLifecycleRequest(handler); await f.api.attachFacility({});
  const old = f.commandbar; old.isConnected = false;
  const replacement = f.ribbon.append(new old.constructor(old.id));
  f.observe();
  assert.equal(f.blocked(replacement), true); assert.equal(f.ribbon.inert, true);
  assert.equal(f.blocked(f.edit), false);
  const duplicate = fixture({ integrated: true, duplicateSurface: true }); duplicate.api.onLifecycleRequest(handler);
  await assert.rejects(duplicate.api.attachFacility({}), { code: 'desktop_runtime_facility_surface_ambiguous' });
  assert.equal(duplicate.invokes.length, 0); assert.equal(duplicate.blocked(duplicate.edit), true);
});

test('external surface lost during IPC cannot unlock a partial attachment', async () => {
  const wait = deferred(); const f = fixture({ integrated: true, invoke: () => wait.promise });
  f.api.onLifecycleRequest(handler); const attached = f.api.attachFacility({});
  f.assets.isConnected = false;
  wait.resolve({ ready: true, recoveryRequired: false, capabilities: { facilityAcceptance: true } });
  await assert.rejects(attached, { code: 'desktop_runtime_attach_rejected' });
  assert.equal(f.blocked(f.edit), true); assert.equal(f.blocked(f.commandButton), true);
});

test('unverified attachment, recovery gate and changed attachment node never unlock input', async () => {
  const rejected = fixture({ invoke: async () => ({ ready: false }) });
  rejected.api.onLifecycleRequest(handler);
  await assert.rejects(rejected.api.attachFacility({}), { code: 'desktop_runtime_attach_rejected' });
  assert.equal(rejected.blocked(rejected.edit), true);
  const f = fixture({ invoke: async () => ({ ready: true, recoveryRequired: true, capabilities: { facilityAcceptance: true } }) });
  f.api.onLifecycleRequest(handler); await f.api.attachFacility({});
  assert.equal(f.blocked(f.edit), true);
  await f.command('setStartupRecoveryGate', { blocked: false });
  assert.equal(f.blocked(f.edit), false);
  f.listeners.get('desktop-runtime:input-lock')({}, { locked: true });
  f.listeners.get('desktop-runtime:input-lock')({}, { locked: false });
  assert.equal(f.blocked(f.edit), true);
});

test('RPC enforces allowlist, deadlines, correlated single dispatch and typed renderer failures', async () => {
  const f = fixture(); let calls = 0;
  f.api.onLifecycleRequest((request, control) => { calls++; control.assertCurrent(); return request.args.fail
    ? { ok: false, error: { code: 'facility_desktop_stale_state' } } : { ok: true, result: { value: 17 } }; });
  assert.equal((await f.command('save')).reply.error.code, 'desktop_runtime_request_rejected');
  assert.equal((await f.command('snapshot', {}, { deadlineUnixMs: Date.now() - 1 })).reply.error.code, 'desktop_runtime_request_rejected');
  assert.equal((await f.command('snapshot', {}, { deadlineUnixMs: Date.now() + 70000 })).reply.error.code, 'desktop_runtime_request_rejected');
  const first = await f.command('snapshot'); assert.deepEqual(first.reply.result, { value: 17 });
  await f.command('snapshot', {}, { requestId: first.requestId });
  assert.equal(f.replies.at(-1).error.code, 'desktop_runtime_request_rejected');
  assert.equal((await f.command('freeze', { fail: true })).reply.error.code, 'facility_desktop_stale_state');
  assert.equal(calls, 2);
});

test('cancelled queued and cooperating delayed commands cannot perform late effects', async () => {
  const f = fixture(), wait = deferred(); let effects = 0;
  f.api.onLifecycleRequest(async (_request, control) => { await wait.promise; control.assertCurrent(); effects++; return { ok: true, result: {} }; });
  const request = await f.command('freeze', { intentId: 'close-a' }); assert.equal(request.reply, undefined);
  f.listeners.get('desktop-runtime:facility-cancel')({}, { requestId: request.requestId });
  wait.resolve(); await turn();
  assert.equal(effects, 0); assert.equal(f.replies.at(-1).error.code, 'desktop_runtime_request_cancelled');
  assert.equal(f.api.getInputLockDiagnostics().frozen, false);
});

test('deadline expiration revokes delayed side effects and unsubscribe revokes retained controls', async () => {
  const f = fixture(), wait = deferred(); let effects = 0, savedControl;
  const off = f.api.onLifecycleRequest(async (_request, control) => { savedControl = control; await wait.promise; control.assertCurrent(); effects++; return { ok: true, result: {} }; });
  await f.command('freeze', {}, { deadlineUnixMs: Date.now() + 20 });
  await new Promise(resolve => setTimeout(resolve, 35)); wait.resolve(); await turn();
  assert.equal(effects, 0); assert.equal(f.replies.at(-1).error.code, 'desktop_runtime_request_expired');
  off(); assert.throws(() => savedControl.assertCurrent()); assert.equal(f.blocked(f.edit), true);
});

test('completed callbacks cannot retain usable cancellation authority', async () => {
  const f = fixture(); let retained;
  f.api.onLifecycleRequest((_request, control) => { retained = control; control.assertCurrent(); return { ok: true, result: {} }; });
  assert.equal((await f.command('snapshot')).reply.ok, true);
  assert.throws(() => retained.assertCurrent(), { code: 'desktop_runtime_request_finished' });
});

test('late freeze acknowledgement retains owner so matching Cancel unfreezes, other intent cannot', async () => {
  const f = fixture(), wait = deferred(); let frozen = null;
  f.api.onLifecycleRequest(async (request, control) => {
    control.assertCurrent();
    if (request.method === 'freeze') { frozen = request.args.intentId; await wait.promise; }
    if (request.method === 'unfreeze') {
      if (frozen !== request.args.intentId) return { ok: false, error: { code: 'facility_desktop_freeze_owned' } };
      frozen = null;
    }
    return { ok: true, result: {} };
  });
  await f.api.attachFacility({});
  const first = await f.command('freeze', { intentId: 'close-a' });
  f.listeners.get('desktop-runtime:facility-cancel')({}, { requestId: first.requestId });
  wait.resolve(); await turn(); assert.equal(f.blocked(f.edit), true);
  assert.equal((await f.command('unfreeze', { intentId: 'other' })).reply.ok, false);
  assert.equal(f.blocked(f.edit), true);
  assert.equal((await f.command('unfreeze', { intentId: 'close-a' })).reply.ok, true);
  assert.equal(frozen, null); assert.equal(f.blocked(f.edit), false);
});

test('fixed close and restart invocations ignore caller payload and oversized payload never reaches IPC', async () => {
  const f = fixture(); await f.api.requestClose({ arbitrary: true }); await f.api.restartBackend('command');
  assert.deepEqual(f.invokes.map(call => call.args), [[], []]);
  await assert.rejects(f.api.persistOperation({ value: 'x'.repeat(16 * 1024 * 1024) }), { code: 'desktop_runtime_payload_invalid' });
  assert.equal(f.invokes.length, 2);
});
