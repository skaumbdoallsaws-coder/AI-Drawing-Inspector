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
