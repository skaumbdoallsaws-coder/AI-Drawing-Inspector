const assert = require('node:assert/strict');
const { test, before, afterEach } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'static/packaging.js'), 'utf8');
const sceneSource = fs.readFileSync(path.join(root, 'static/packaging_scene.js'), 'utf8');
const originalFetch = global.fetch;
let ui, THREE;

before(async () => {
  const testSource = source + '\nexport { state as testState, resetDocumentState as testResetDocumentState };';
  ui = await import('data:text/javascript;base64,' + Buffer.from(testSource).toString('base64'));
  THREE = await import(pathToFileURL(path.join(root, 'static/vendor/three/0.184.0/build/three.module.min.js')).href);
});
afterEach(() => { global.fetch = originalFetch; });

test('form millimeters convert to SI meters without changing source dimensions', () => {
  for (const [mm, m] of [[100, .1], [25.4, .0254], [1, .001], [5000, 5], [0, 0]]) {
    assert.equal(ui.mmToM(mm), m); assert.equal(ui.mToMm(m), mm);
  }
  assert.deepEqual(ui.emptyDesign().constraints.allowed_orientations, [0]);
  assert.equal(ui.emptyDesign().product, null);
  assert.equal(ui.defaultCarton().tare_kg, null);
});

test('orientation indexes exactly match backend ORDERS', () => {
  const backend = fs.readFileSync(path.join(root, 'ai_inspector/packaging_shipping/geometry.py'), 'utf8');
  const line = backend.match(/^ORDERS\s*=\s*(.+)$/m)[1];
  const orders = JSON.parse(line.replaceAll('(', '[').replaceAll(')', ']'));
  assert.deepEqual(ui.ORIENTATION_ORDERS, orders);
});

test('all six orientation transforms are proper rotations and preserve minimum-corner placements', () => {
  const dimensions = [.113, .207, .359], position = [.024, .031, .048];
  for (let orientation = 0; orientation < 6; orientation++) {
    const rows = ui.orientationRows(orientation), center = ui.placementCenter(dimensions, { orientation, position_m: position });
    const rotation = new THREE.Matrix4().set(...rows[0], 0, ...rows[1], 0, ...rows[2], 0, 0, 0, 0, 1);
    assert.equal(rotation.determinant(), 1, `orientation ${orientation} must not reflect`);
    const inverse = rotation.clone().transpose().multiply(rotation);
    assert.ok(inverse.equals(new THREE.Matrix4()), 'rotation is orthonormal');
    const geometry = new THREE.BoxGeometry(...dimensions);
    const mesh = new THREE.Mesh(geometry); mesh.setRotationFromMatrix(rotation); mesh.position.fromArray(center); mesh.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(mesh);
    const size = bounds.getSize(new THREE.Vector3()).toArray();
    for (let axis = 0; axis < 3; axis++) {
      assert.ok(Math.abs(bounds.min.getComponent(axis) - position[axis]) < 1e-7, `orientation ${orientation}, minimum ${axis}`);
      assert.ok(Math.abs(size[axis] - dimensions[ui.ORIENTATION_ORDERS[orientation][axis]]) < 1e-7, `orientation ${orientation}, size ${axis}`);
    }
    assert.deepEqual(mesh.scale.toArray(), [1, 1, 1]); geometry.dispose(); mesh.material.dispose();
  }
  assert.throws(() => ui.orientationRows(6), /Unsupported/);
});

test('draft edits are atomic, independently cloned, undoable, and redoable', () => {
  const draft = new ui.DraftDocument();
  draft.edit(d => { d.product = { dimensions_m: [.1, .2, .3], source_id: 'src_123', source_revision: 'abc' }; });
  const snapshot = ui.clone(draft.design);
  assert.equal(draft.dirty, true);
  assert.throws(() => draft.edit(d => { d.quantity = 22; throw new Error('invalid edit'); }), /invalid edit/);
  assert.deepEqual(draft.design, snapshot);
  assert.equal(draft.undo(), true); assert.equal(draft.design.product, null); assert.equal(draft.dirty, false);
  assert.equal(draft.redo(), true); assert.deepEqual(draft.design, snapshot);
  draft.undo(); draft.edit(d => { d.quantity = 3; }); assert.equal(draft.redo(), false);
});

test('accepting a saved revision resets local history without mutating server data', () => {
  const draft = new ui.DraftDocument();
  const response = { id: 'pkg_1', revision: 7, can_undo: true, can_redo: false, design: ui.emptyDesign() };
  draft.accept(response); draft.edit(d => { d.name = 'Working copy'; });
  assert.equal(response.design.name, 'Untitled package'); assert.equal(draft.document.design.name, 'Untitled package');
  draft.accept({ ...response, revision: 8, design: draft.design });
  assert.equal(draft.dirty, false); assert.equal(draft.undo(), false); assert.equal(draft.future.length, 0);
  assert.equal(draft.document.revision, 8);
});

test('New/Open reset carton alternatives, evidence, candidate settings and the review view', () => {
  const state = ui.testState;
  for (const name of ['Previous document', 'Another document']) {
    const carton = { ...ui.defaultCarton(), name, tare_kg: 2, tare_evidence: 'Previous scale measurement' };
    state.alternatives = [carton, ui.defaultCarton()]; state.alternativeIndex = 1; state.maxPackages = 6;
    state.candidateConfig = 'previous-config'; state.candidates = { candidates: [{}] }; state.candidateRevision = 8;
    state.review = 'rates';
    ui.testResetDocumentState();
    assert.deepEqual(state.alternatives, [ui.defaultCarton()]);
    assert.notEqual(state.alternatives[0], carton);
    assert.equal(state.alternatives[0].tare_kg, null);
    assert.equal(state.alternatives[0].tare_evidence, '');
    assert.equal(state.alternativeIndex, 0); assert.equal(state.maxPackages, 3);
    assert.equal(state.candidateConfig, null); assert.equal(state.candidates, null); assert.equal(state.candidateRevision, null);
    assert.equal(state.review, 'validation');
    assert.equal(carton.tare_evidence, 'Previous scale measurement');
  }
  assert.match(source, /async function newDocument\(\)[\s\S]*?resetDocumentState\(\)/);
  assert.match(source, /async function loadDocument\(id\)[\s\S]*?resetDocumentState\(\)/);
});

test('applying a candidate can restore every prior pad and allowance with Undo', () => {
  const draft = new ui.DraftDocument(), design = ui.emptyDesign();
  design.packages = [{ id: 'box_original', placements: [], inserts: [{ id: 'pad', density_kg_m3: 30 }], allowance_kg: .08, allowance_evidence: 'Measured tape' }];
  draft.accept({ id: 'pkg', revision: 2, design });
  const candidatePackages = [{ id: 'box_1', placements: [{ id: 'item_1' }], inserts: [], allowance_kg: null, allowance_evidence: '' }];
  draft.edit(d => { d.packages = ui.clone(candidatePackages); });
  assert.equal(draft.design.packages[0].allowance_kg, null);
  draft.undo(); assert.deepEqual(draft.design.packages, design.packages);
  draft.redo(); assert.deepEqual(draft.design.packages, candidatePackages);
  assert.match(source, /Replace all package arrangements, pads and allowances/);
});

test('all API requests carry the packaging header; source upload is raw binary', async () => {
  const calls = [];
  global.fetch = async (url, options) => { calls.push({ url, options }); return new Response(JSON.stringify({ id: 'src_1' }), { headers: { 'Content-Type': 'application/json' } }); };
  const raw = new Uint8Array([103, 108, 84, 70]);
  await ui.request('/sources?name=part.glb&meters_per_unit=0.001', { method: 'POST', body: raw, raw: true });
  await ui.request('/documents');
  await ui.request('/documents/pkg', { method: 'PUT', body: { expected_revision: 2, request_id: 'edit_123', design: ui.emptyDesign() } });
  for (const call of calls) {
    assert.equal(call.options.headers['X-InspectorPro-Request'], 'packaging');
    assert.equal(call.options.credentials, 'same-origin'); assert.equal(call.options.cache, 'no-store');
  }
  assert.equal(calls[0].options.body, raw); assert.equal(calls[0].options.headers['Content-Type'], 'model/gltf-binary');
  assert.equal(calls[1].options.body, undefined);
  const edit = JSON.parse(calls[2].options.body); assert.equal(edit.expected_revision, 2); assert.equal(edit.request_id, 'edit_123');
  assert.deepEqual(edit.design, ui.emptyDesign());
  assert.match(sceneSource, /'X-InspectorPro-Request': 'packaging'/);
});

test('revision conflicts, validation failures and provider errors are not hidden', async () => {
  global.fetch = async () => new Response(JSON.stringify({ error: { code: 'revision_conflict', message: 'Document changed' } }), { status: 409 });
  await assert.rejects(ui.request('/documents/pkg'), error => error.status === 409 && error.code === 'revision_conflict' && error.message === 'Document changed');
  assert.equal(ui.errorMessage({ detail: [{ loc: ['body', 'product'], msg: 'Missing evidence' }] }, 422), 'body.product: Missing evidence');
  global.fetch = async () => new Response('unavailable', { status: 503 });
  await assert.rejects(ui.request('/status'), /HTTP 503/);
});

test('PDF endpoint is consumed as a Blob', async () => {
  global.fetch = async (url, options) => {
    assert.equal(url, '/api/packaging/documents/pkg/report.pdf?revision=4');
    assert.equal(options.headers['X-InspectorPro-Request'], 'packaging');
    return new Response('%PDF-1.7', { headers: { 'Content-Type': 'application/pdf' } });
  };
  const blob = await ui.request('/documents/pkg/report.pdf?revision=4', { responseType: 'blob' });
  assert.equal(blob.type, 'application/pdf'); assert.equal(await blob.text(), '%PDF-1.7');
});

test('quotes are stale for edited forms, changed revisions, or unknown address scenarios', () => {
  const quote = { revision: 2, stale: false };
  assert.equal(ui.quoteFreshness(null, 2, false, true), 'No quotes');
  assert.equal(ui.quoteFreshness(quote, 2, false, true), 'Current saved revision');
  assert.match(ui.quoteFreshness(quote, 2, true, true), /Stale/);
  assert.match(ui.quoteFreshness(quote, 3, false, true), /Stale/);
  assert.match(ui.quoteFreshness({ ...quote, stale: true }, 2, false, true), /Stale/);
  assert.match(ui.quoteFreshness(quote, 2, false, false), /scenario/);
});

test('same carrier and service remain distinguishable by carrier account', () => {
  const base = { carrier: 'Carrier', service: 'Ground', amount: '12.50', currency: 'USD', mode: 'test' };
  assert.equal(ui.rateAccountLabel({ ...base, account_id: 'ca_first' }), 'Account: ca_first');
  assert.equal(ui.rateAccountLabel({ ...base, account_id: 'ca_second' }), 'Account: ca_second');
  assert.equal(ui.rateAccountLabel(base), 'Account: not provided');
  assert.equal(ui.rateAccountLabel({ account_id: ' ' }), 'Account: not provided');
  assert.match(source, /element\('div', rateAccountLabel\(rate\), 'rate-account muted'\)/);
  assert.match(source, /All-package rate totals/);
  assert.match(source, /Individual parcel rates/);
});

test('assets, icons, and Three imports stay local; server strings never enter HTML sinks', () => {
  const html = fs.readFileSync(path.join(root, 'static/packaging.html'), 'utf8');
  const css = fs.readFileSync(path.join(root, 'static/packaging.css'), 'utf8');
  const map = JSON.parse(html.match(/<script type="importmap">\s*([\s\S]+?)\s*<\/script>/)[1]);
  assert.equal(map.imports.three, '/static/vendor/three/0.184.0/build/three.module.min.js');
  for (const value of Object.values(map.imports)) assert.ok(fs.existsSync(path.join(root, value)));
  for (const match of source.matchAll(/symbol:\s*'([^']+)'/g)) assert.ok(fs.existsSync(path.join(root, 'static/assets/facility-layout-ribbon-icons/svg', match[1] + '.svg')), match[1]);
  assert.doesNotMatch(source + sceneSource, /innerHTML|outerHTML|insertAdjacentHTML|document\.write/);
  assert.doesNotMatch(html + source + sceneSource + css, /https?:\/\//);
  assert.doesNotMatch(css, /gradient\(/);
  assert.match(source, /beforeunload/); assert.match(source, /confirmNavigation/);
  assert.match(source, /dimensions_m: p.source_id \? clone\(p.dimensions_m\)/);
  assert.match(sceneSource, /new GLTFLoader\(\)\.parseAsync/);
  assert.doesNotMatch(sceneSource, /(?:sourceModel|loaded|rotation)\.scale/);
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const chatIdentity = { session_id: 'sage-session:1', conversation_id: 'conversation.1' };
function admissionFixture(options = {}) {
  const current = { document_id: 'pkg_one', revision: 4, dirty: false, conflict: false, pending_operations: 0 };
  const calls = [], locks = [], invalidated = [], scheduled = new Map();
  const token = { admission_id: 'adm_one', selection_id: 'sel_one', expires_in: 30 };
  let nextTimer = 0;
  const fixture = { current, calls, locks, invalidated, scheduled, token, accepted: [] };
  fixture.api = async (url, init) => {
    calls.push({ url, init });
    if (options.api) return options.api(url, init, fixture);
    if (url.startsWith('/documents/')) return { id: current.document_id, revision: 6, design: ui.emptyDesign() };
    return token;
  };
  fixture.editor = new ui.PackagingEditorAdmission({
    snapshot: () => ({ ...current }), lock: value => locks.push(value), api: fixture.api,
    accept: async saved => {
      assert.equal(fixture.editor.locked, true, 'accept must precede unlock');
      fixture.accepted.push(saved); current.revision = saved.revision;
    },
    invalidate: error => invalidated.push(error),
    schedule: (callback, ms) => { const id = ++nextTimer; scheduled.set(id, { callback, ms }); return id; },
    unschedule: id => scheduled.delete(id),
  });
  fixture.tick = async () => {
    const [id, job] = [...scheduled.entries()][0]; scheduled.delete(id); await job.callback();
  };
  return fixture;
}

test('admission locks synchronously, publishes saved identity, and waits for acknowledgement', async () => {
  const publish = deferred();
  const f = admissionFixture({ api: () => publish.promise });
  const preparing = f.editor.prepare(chatIdentity);
  assert.equal(f.editor.locked, true); assert.deepEqual(f.locks, [true]);
  assert.equal(f.editor.admission, null);
  assert.deepEqual(f.calls[0], { url: '/editor', init: { method: 'POST', body: {
    ...f.current, ...chatIdentity, active_mode: 'packaging_shipping'
  } } });
  publish.resolve(f.token);
  assert.deepEqual(await preparing, { admission_id: 'adm_one', document_id: 'pkg_one', revision: 4, state: 'locked' });
  assert.equal([...f.scheduled.values()][0].ms, 10000);
});

test('unsaved, dirty, conflicted, pending and invalid-identity admission never publishes', async () => {
  for (const invalid of [{ document_id: null }, { revision: null }, { dirty: true }, { conflict: true }, { pending_operations: 1 }]) {
    const f = admissionFixture(); Object.assign(f.current, invalid);
    await assert.rejects(f.editor.prepare(chatIdentity), /Save or reload/);
    assert.equal(f.calls.length, 0); assert.equal(f.editor.locked, false);
  }
  const f = admissionFixture();
  await assert.rejects(f.editor.prepare({ ...chatIdentity, session_id: '../outside' }), /active chat session/);
  assert.equal(f.calls.length, 0);
});

test('publish failure releases only the unadmitted lock; duplicate prepare is rejected', async () => {
  const f = admissionFixture({ api: async () => { throw new Error('Not authorized'); } });
  await assert.rejects(f.editor.prepare(chatIdentity), /Not authorized/);
  assert.deepEqual(f.locks, [true, false]); assert.equal(f.editor.admission, null);
  const admitted = admissionFixture(); await admitted.editor.prepare(chatIdentity);
  await assert.rejects(admitted.editor.prepare(chatIdentity), /Save or reload/);
  assert.equal(admitted.calls.length, 1);
});

test('heartbeat repeats exact admission binding without document contents', async () => {
  const f = admissionFixture(); await f.editor.prepare(chatIdentity); await f.tick();
  assert.deepEqual(f.calls[1], { url: '/editor/adm_one/heartbeat', init: { method: 'POST', body: {
    ...f.current, ...chatIdentity, active_mode: 'packaging_shipping', selection_id: 'sel_one'
  } } });
  assert.equal(f.scheduled.size, 1); assert.equal(f.invalidated.length, 0);
});

test('finished turn heartbeat stops renewal without aborting final SSE or unlocking', async () => {
  const f = admissionFixture({ api: async (url, init, self) => {
    if (url.endsWith('/heartbeat')) throw Object.assign(new Error('Finished'), { code: 'editor_turn_finished' });
    return self.token;
  } });
  await f.editor.prepare(chatIdentity); await f.tick();
  assert.equal(f.scheduled.size, 0); assert.equal(f.invalidated.length, 0);
  assert.equal(f.editor.locked, true); assert.equal(f.calls.length, 2);
});

test('default admission timers preserve the browser global receiver during prepare, heartbeat, finish and unload', async () => {
  const originalSchedule = globalThis.setTimeout, originalUnschedule = globalThis.clearTimeout;
  const scheduled = new Map(), receivers = [];
  let timer = 0;
  globalThis.setTimeout = function (callback, delay) {
    if (this !== globalThis) throw new TypeError('Illegal invocation: setTimeout receiver');
    receivers.push('setTimeout'); const id = ++timer; scheduled.set(id, { callback, delay }); return id;
  };
  globalThis.clearTimeout = function (id) {
    if (this !== globalThis) throw new TypeError('Illegal invocation: clearTimeout receiver');
    receivers.push('clearTimeout'); scheduled.delete(id);
  };
  try {
    const f = admissionFixture(), locks = [];
    const editor = new ui.PackagingEditorAdmission({
      snapshot: () => ({ ...f.current }), lock: value => locks.push(value), api: f.api,
      accept: async saved => { f.current.revision = saved.revision; },
    });
    await editor.prepare(chatIdentity);
    assert.equal(editor.locked, true); assert.equal(scheduled.size, 1);
    const [id, heartbeat] = [...scheduled.entries()][0]; scheduled.delete(id);
    assert.equal(heartbeat.delay, 10000); await heartbeat.callback();
    assert.equal(f.calls.at(-1).url, '/editor/adm_one/heartbeat'); assert.equal(scheduled.size, 1);
    await editor.finish();
    assert.equal(editor.locked, false); assert.equal(scheduled.size, 0);
    assert.equal(f.current.revision, 6); assert.deepEqual(locks, [true, false]);
    await editor.prepare(chatIdentity); editor.unload();
    assert.equal(scheduled.size, 0); assert.equal(f.calls.at(-1).init.keepalive, true);
    assert.ok(receivers.includes('setTimeout')); assert.ok(receivers.includes('clearTimeout'));
  } finally {
    globalThis.setTimeout = originalSchedule; globalThis.clearTimeout = originalUnschedule;
  }
});

test('expired or changed editor heartbeat requests host cancellation but keeps the editor locked', async () => {
  for (const changed of [false, true]) {
    const f = admissionFixture({ api: async (url, init, self) => {
      if (url.endsWith('/heartbeat')) throw Object.assign(new Error('Expired'), { code: 'editor_expired' });
      return self.token;
    } });
    await f.editor.prepare(chatIdentity);
    if (changed) f.current.dirty = true;
    await f.tick();
    assert.equal(f.invalidated.length, 1); assert.equal(f.editor.locked, true);
    assert.equal(f.scheduled.size, 0);
  }
});

test('finish coalesces, awaits revoke then authoritative GET, accepts revision then unlocks', async () => {
  const revoked = deferred(), loaded = deferred();
  const f = admissionFixture({ api: (url, init, self) => url.endsWith('/revoke') ? revoked.promise
    : url.startsWith('/documents/') ? loaded.promise : self.token });
  await f.editor.prepare(chatIdentity);
  const finished = f.editor.finish({ documentId: 'pkg_one', revision: 6 });
  assert.equal(f.editor.finish(), finished); assert.equal(f.editor.locked, true);
  assert.equal(f.calls.length, 2); assert.equal(f.scheduled.size, 0);
  revoked.resolve({ expires_in: 0 }); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.calls[2].url, '/documents/pkg_one'); assert.equal(f.editor.locked, true);
  loaded.resolve({ id: 'pkg_one', revision: 6, design: ui.emptyDesign() });
  assert.deepEqual(await finished, { admission_id: null, document_id: 'pkg_one', revision: 6, state: 'idle' });
  assert.deepEqual(f.locks, [true, false]); assert.equal(f.accepted.length, 1);
});

test('cancel or disconnected stream reconciles GET even without terminal receipts', async () => {
  const f = admissionFixture(); await f.editor.prepare(chatIdentity); await f.editor.finish();
  assert.equal(f.accepted[0].revision, 6);
  assert.deepEqual(f.calls.map(call => call.url), ['/editor', '/editor/adm_one/revoke', '/documents/pkg_one']);
});

test('failed revoke preserves lock and admission for an explicit retry', async () => {
  let fail = true;
  const f = admissionFixture({ api: (url, init, self) => {
    if (url.endsWith('/revoke') && fail) throw new Error('Lease busy');
    return url.startsWith('/documents/') ? { id: 'pkg_one', revision: 5 } : self.token;
  } });
  await f.editor.prepare(chatIdentity);
  await assert.rejects(f.editor.finish(), /Lease busy/);
  assert.equal(f.editor.locked, true); assert.ok(f.editor.admission); assert.equal(f.accepted.length, 0);
  fail = false; await f.editor.finish(); assert.equal(f.editor.locked, false);
});

test('reconciliation refuses stale receipts, wrong document, changed selection or newly dirty draft', async () => {
  for (const mismatch of ['receipt', 'response', 'selection', 'dirty']) {
    const f = admissionFixture({ api: (url, init, self) => {
      if (!url.startsWith('/documents/')) return self.token;
      if (mismatch === 'selection') self.current.document_id = 'pkg_other';
      if (mismatch === 'dirty') self.current.dirty = true;
      return { id: mismatch === 'response' ? 'pkg_other' : 'pkg_one', revision: 5 };
    } });
    await f.editor.prepare(chatIdentity);
    await assert.rejects(f.editor.finish({ documentId: 'pkg_one', revision: mismatch === 'receipt' ? 6 : 5 }), /not be reconciled/);
    assert.equal(f.accepted.length, 0); assert.equal(f.editor.locked, true);
  }
});

test('pagehide revocation forwards keepalive through the authenticated request helper', async () => {
  const f = admissionFixture(); await f.editor.prepare(chatIdentity); f.editor.unload();
  const call = f.calls.at(-1); assert.equal(call.url, '/editor/adm_one/revoke'); assert.equal(call.init.keepalive, true);
  global.fetch = async (url, init) => {
    assert.equal(init.keepalive, true); assert.equal(init.credentials, 'same-origin');
    assert.equal(init.headers['X-InspectorPro-Request'], 'packaging');
    return new Response('{}');
  };
  await ui.request(call.url, call.init);
});

test('host bridge authenticates source, origin and request nonce; only opaque state can cross back', async () => {
  const sent = [], frame = { contentWindow: { postMessage: (data, origin) => sent.push({ data, origin }) } };
  const hostWindow = { location: { origin: 'https://app.example' }, addEventListener() {} };
  let invalidated = 0;
  const bridge = new ui.PackagingHostBridge({ hostWindow, frame: () => frame, invalidate: () => invalidated++ });
  const prepared = bridge.prepare(chatIdentity);
  assert.equal(sent[0].origin, hostWindow.location.origin);
  const event = { source: frame.contentWindow, origin: hostWindow.location.origin, data: {
    type: ui.PACKAGING_BRIDGE, action: 'result', request_id: sent[0].data.request_id, ok: true,
    value: { admission_id: 'adm_one', document_id: 'pkg_one', revision: 4, state: 'locked' }
  } };
  bridge.receive({ ...event, origin: 'https://outside.example' });
  bridge.receive({ ...event, source: {} });
  bridge.receive({ ...event, data: { ...event.data, request_id: 'unknown' } });
  assert.equal(bridge.pending.size, 1); assert.equal(bridge.admitted, null);
  bridge.receive(event); assert.equal((await prepared).admission_id, 'adm_one');
  bridge.receive({ ...event, source: {}, data: { type: ui.PACKAGING_BRIDGE, action: 'invalidate' } });
  assert.equal(invalidated, 0);
  bridge.receive({ ...event, data: { type: ui.PACKAGING_BRIDGE, action: 'release-request' } });
  assert.equal(invalidated, 1);
  const finished = bridge.finish({ documentId: 'pkg_one', revision: 6, mutations: [{}], tools: ['arbitrary'] });
  assert.deepEqual(sent[1].data.payload, { documentId: 'pkg_one', revision: 6 });
  bridge.receive({ ...event, data: { ...event.data, request_id: sent[1].data.request_id,
    value: { admission_id: null, document_id: 'pkg_one', revision: 6, state: 'idle', design: {} } } });
  await assert.rejects(finished, /Invalid packaging bridge/);
  assert.ok(bridge.admitted, 'malformed acknowledgement must not clear host admission');
});
