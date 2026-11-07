const assert = require('node:assert/strict');
const { test, before, afterEach } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'static/packaging.js'), 'utf8');
const sceneSource = fs.readFileSync(path.join(root, 'static/packaging_scene.js'), 'utf8');
const originalFetch = global.fetch;
let ui, THREE, scene;

before(async () => {
  const testSource = source + '\nexport { state as testState, resetDocumentState as testResetDocumentState, readCarton as testReadCarton };';
  const uiUrl = 'data:text/javascript;base64,' + Buffer.from(testSource).toString('base64');
  const threeUrl = pathToFileURL(path.join(root, 'static/vendor/three/0.184.0/build/three.module.min.js')).href;
  ui = await import(uiUrl);
  THREE = await import(threeUrl);
  const boundsSource = sceneSource.replace("from 'three'", `from '${threeUrl}'`)
    .replace(/^import .* from 'three\/addons\/.*';$/gm, '')
    .replace("from './packaging.js'", `from '${uiUrl}'`);
  scene = await import('data:text/javascript;base64,' + Buffer.from(boundsSource).toString('base64'));
});
afterEach(() => { global.fetch = originalFetch; });

test('source bounds accept angled nested CAD geometry without inflating or scaling it', () => {
  const root = new THREE.Group(), assembly = new THREE.Group();
  root.position.set(1.7, 2.3, -1.2); root.add(assembly);
  assembly.rotation.set(.4, .3, Math.PI / 5); assembly.position.set(.2, -.1, .3);
  const geometry = new THREE.TetrahedronGeometry(.1), material = new THREE.MeshBasicMaterial();
  const mesh = new THREE.Mesh(geometry, material); assembly.add(mesh); root.updateMatrixWorld(true);
  const positions = geometry.getAttribute('position'), points = [];
  for (let i = 0; i < positions.count; i++) points.push(new THREE.Vector3().fromBufferAttribute(positions, i).applyMatrix4(mesh.matrixWorld));
  const expected = new THREE.Box3().setFromPoints(points), dimensions = expected.getSize(new THREE.Vector3()).toArray();
  const approximate = new THREE.Box3().setFromObject(root).getSize(new THREE.Vector3()).toArray();
  assert.ok(approximate.some((n, i) => n - dimensions[i] > .001), 'fixture exposes the conservative-box mismatch');
  const before = mesh.matrixWorld.toArray();
  const actual = scene.sourceBounds(root, dimensions);
  assert.ok(actual.min.distanceTo(expected.min) < 1e-10);
  assert.ok(actual.max.distanceTo(expected.max) < 1e-10);
  assert.deepEqual(mesh.matrixWorld.toArray(), before);
  assert.deepEqual(root.scale.toArray(), [1, 1, 1]);
  assert.match(sceneSource, /const box = sourceBounds\(loaded, product\.dimensions_m\)/);
  geometry.dispose(); material.dispose();
});

test('source bounds still reject wrong dimensions, empty sources and nonfinite vertices', () => {
  const geometry = new THREE.BoxGeometry(.1, .2, .3), material = new THREE.MeshBasicMaterial();
  const mesh = new THREE.Mesh(geometry, material);
  assert.throws(() => scene.sourceBounds(mesh, [.1, .2, .4]), /immutable source dimensions/);
  assert.throws(() => scene.sourceBounds(new THREE.Group(), [.1, .2, .3]), /immutable source dimensions/);
  geometry.getAttribute('position').setX(0, Infinity);
  assert.throws(() => scene.sourceBounds(mesh, [.1, .2, .3]), /immutable source dimensions/);
  geometry.dispose(); material.dispose();
});

test('display modes and transparency are finite presentation settings, not physical material inputs', () => {
  const shaded = scene.displayMaterialSettings('shaded', 0);
  assert.equal(shaded.wireframe, false); assert.equal(shaded.transparent, false); assert.equal(shaded.opacity, 1);
  assert.equal(shaded.color, 0xb9bfc5);
  const wire = scene.displayMaterialSettings('wireframe', 65);
  assert.equal(wire.wireframe, true); assert.equal(wire.opacity, .35); assert.equal(wire.depthWrite, false);
  assert.equal(scene.displayMaterialSettings('edges', 0).polygonOffset, true);
  for (const value of [-1, 86, NaN, Infinity, '50', true]) assert.throws(() => scene.displayMaterialSettings('shaded', value), /display settings/);
  assert.throws(() => scene.displayMaterialSettings('invented', 0), /display settings/);
  assert.equal('density_kg_m3' in wire, false); assert.equal('mass_kg' in wire, false);
});

test('display styling clones materials, keeps source vertices and transforms, and shares edge geometry', () => {
  const original = new THREE.MeshStandardMaterial({ color: 0xff5500, opacity: .8 });
  const geometry = new THREE.BoxGeometry(.1, .2, .3), model = new THREE.Group();
  model.add(new THREE.Mesh(geometry, original)); model.position.set(.2, .1, -.3);
  const clone = model.clone(true); clone.add(new THREE.Mesh(geometry, original));
  const viewer = Object.create(scene.PackagingScene.prototype);
  Object.assign(viewer, { resources: new Set(), edgeCache: new Map(), displayMode: 'edges', transparency: 40 });
  const vertices = [...geometry.attributes.position.array], position = clone.position.toArray();
  viewer.styleComponent(clone);
  assert.equal(model.children[0].material, original); assert.equal(original.color.getHex(), 0xff5500);
  assert.equal(original.opacity, .8); assert.equal(clone.children[0].geometry, geometry);
  assert.notEqual(clone.children[0].material, original);
  assert.equal(clone.children[0].material.opacity, .6);
  assert.equal(clone.children[0].children[0].geometry, clone.children[1].children[0].geometry);
  assert.deepEqual([...geometry.attributes.position.array], vertices);
  assert.deepEqual(clone.position.toArray(), position); assert.deepEqual(clone.scale.toArray(), [1, 1, 1]);
  for (const resource of viewer.resources) resource.dispose(); geometry.dispose(); original.dispose();
});

test('changing display state never edits the design, document revision or undo history', () => {
  const draft = new ui.DraftDocument();
  draft.accept({ id: 'pkg_view', revision: 9, design: { ...ui.emptyDesign(), product: {
    name: 'Measured', dimensions_m: [.1, .2, .3], mass_kg: .4, mass_basis: 'user_measured', mass_evidence: 'Scale',
  } } });
  const before = JSON.stringify(draft), viewer = Object.create(scene.PackagingScene.prototype);
  let redraws = 0;
  Object.assign(viewer, { design: draft.design, displayMode: 'edges', transparency: 0, rebuild: () => redraws++ });
  viewer.setDisplay('shaded', 40); viewer.setDisplay('wireframe', 0); viewer.setDisplay('edges', 0);
  assert.equal(redraws, 3); assert.equal(JSON.stringify(draft), before);
});

test('ribbon commands use local icons and carton edits preserve additive physical and appearance records', () => {
  assert.deepEqual(ui.PANEL_COMMANDS.map(command => command.id), ['product', 'carton', 'contents', 'arrange', 'appearance', 'graphics', 'validation', 'rates']);
  for (const command of ui.PANEL_COMMANDS) assert.ok(fs.existsSync(path.join(root, 'static/assets/facility-layout-ribbon-icons/svg', command.icon + '.svg')));
  const original = { ...ui.defaultCarton(), appearance: { color: '#909090', opacity: .8 },
    board_blank: { dimensions_m: [1, 2], quantity: 1, mass_per_area_kg_m2: .2, evidence: 'Supplier' } };
  const fields = { carton_name: 'Edited carton', inner_0: '400', inner_1: '300', inner_2: '250', outer_0: '410', outer_1: '310', outer_2: '260',
    tare: '.4', tare_evidence: 'Supplier', payload: '', carton_cost: '' };
  const updated = ui.testReadCarton({ elements: { namedItem: name => ({ value: fields[name] }) } }, original);
  assert.deepEqual(updated.appearance, original.appearance); assert.deepEqual(updated.board_blank, original.board_blank);
  assert.notEqual(updated.appearance, original.appearance); assert.equal(updated.name, 'Edited carton');
  assert.equal(original.name, 'Carton');
});

test('pocket display removes actual geometry with unchanged outer bounds and documented floors', () => {
  const pad = { dimensions_m: [.2, .05, .15], pockets: [
    { shape: 'rectangular', position_m: [.01, .01, .01], dimensions_m: [.05, .04, .05] },
    { shape: 'cylindrical', position_m: [.1, .02, .05], dimensions_m: [.04, .03, .04] },
  ] };
  const before = JSON.stringify(pad), geometries = scene.insertGeometries(pad), group = new THREE.Group();
  let volume = 0;
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  for (const geometry of geometries) {
    const positions = geometry.attributes.position;
    for (let i = 0; i < positions.count; i += 3) {
      a.fromBufferAttribute(positions, i); b.fromBufferAttribute(positions, i + 1); c.fromBufferAttribute(positions, i + 2);
      volume += a.dot(b.cross(c)) / 6;
    }
    group.add(new THREE.Mesh(geometry));
  }
  const expected = .2 * .05 * .15 - .05 * .04 * .05 - Math.PI * .02 ** 2 * .03;
  assert.ok(Math.abs(volume - expected) < 5e-8, `${volume} versus ${expected}`);
  const bounds = new THREE.Box3().setFromObject(group, true);
  assert.ok(bounds.min.length() < 1e-8);
  bounds.getSize(a); assert.ok(a.distanceTo(new THREE.Vector3(...pad.dimensions_m)) < 1e-7);
  assert.equal(JSON.stringify(pad), before);
  for (const geometry of geometries) geometry.dispose();
  group.children.forEach(mesh => mesh.material.dispose());
  assert.throws(() => scene.insertGeometries({ ...pad, pockets: [{ ...pad.pockets[0], position_m: [.01, 0, .01] }] }), /top-opening/);
  assert.throws(() => scene.insertGeometries({ ...pad, pockets: [pad.pockets[0], pad.pockets[0]] }), /Overlapping/);
});

test('gray display ignores saved colors while appearance mode uses only visual fields', () => {
  const appearance = { color: '#42A578', roughness: .3, metalness: .7, opacity: .5 };
  assert.equal(scene.displayMaterialSettings('shaded', 0, appearance).color, 0xb9bfc5);
  const styled = scene.displayMaterialSettings('appearance', 40, appearance);
  assert.equal(styled.color, appearance.color); assert.equal(styled.opacity, .3);
  assert.equal(styled.roughness, .3); assert.equal(styled.metalness, .7);
});

test('diagonally separated round pockets render real voids despite intersecting footprint AABBs', () => {
  const circle = { shape: 'cylindrical', position_m: [.02, .01, .02], dimensions_m: [.04, .04, .04] };
  for (const second of [
    { shape: 'cylindrical', position_m: [.055, .01, .055], dimensions_m: [.04, .04, .04] },
    { shape: 'rectangular', position_m: [.058, .01, .058], dimensions_m: [.025, .04, .025] },
  ]) {
    assert.ok([0, 2].every(axis => circle.position_m[axis] + circle.dimensions_m[axis] > second.position_m[axis]), 'fixture has overlapping AABBs');
    assert.ok(scene.pocketFootprintDistance(circle, second) > .005, 'actual voids retain the backend default minimum web');
    assert.ok(Math.abs(scene.pocketFootprintDistance(circle, second) - scene.pocketFootprintDistance(second, circle)) < 1e-14);
    const pad = { dimensions_m: [.12, .05, .12], pockets: [circle, second] }, before = JSON.stringify(pad);
    const geometries = scene.insertGeometries(pad), group = new THREE.Group();
    const material = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide });
    geometries.forEach(geometry => group.add(new THREE.Mesh(geometry, material))); group.updateMatrixWorld(true);
    for (const pocket of pad.pockets) {
      const center = new THREE.Vector3(pocket.position_m[0] + pocket.dimensions_m[0] / 2, .1, pocket.position_m[2] + pocket.dimensions_m[2] / 2);
      const hit = new THREE.Raycaster(center, new THREE.Vector3(0, -1, 0)).intersectObject(group, true)[0];
      assert.ok(hit && Math.abs(hit.point.y - .01) < 1e-7, 'ray enters the cut and hits its floor, not a solid envelope');
    }
    assert.equal(JSON.stringify(pad), before);
    geometries.forEach(geometry => geometry.dispose()); material.dispose();
    assert.throws(() => scene.insertGeometries({ ...pad, pockets: [circle, { ...second, position_m: [.035, .01, .035] }] }), /Overlapping/);
  }
});

test('pocket display matches the backend one-micron top-opening tolerance without changing source records', () => {
  const backend = fs.readFileSync(path.join(root, 'ai_inspector/packaging_shipping/components.py'), 'utf8');
  assert.equal(scene.PACKAGING_TOLERANCE_M, Number(backend.match(/^TOLERANCE_M = (.+)$/m)[1]));
  const pad = { dimensions_m: [.1, .05, .1], pockets: [{ shape: 'rectangular', position_m: [.02, .01, .02], dimensions_m: [.02, .04, .02] }] };
  for (const delta of [-.9e-6, .9e-6]) {
    const input = structuredClone(pad); input.pockets[0].dimensions_m[1] += delta;
    const before = JSON.stringify(input), geometries = scene.insertGeometries(input);
    const bounds = new THREE.Box3();
    for (const geometry of geometries) { geometry.computeBoundingBox(); bounds.union(geometry.boundingBox); geometry.dispose(); }
    assert.ok(Math.abs(bounds.max.y - .05) < 1e-8); assert.equal(JSON.stringify(input), before);
  }
  for (const delta of [-1.1e-6, 1.1e-6]) {
    const input = structuredClone(pad); input.pockets[0].dimensions_m[1] += delta;
    assert.throws(() => scene.insertGeometries(input), /top-opening/);
  }
});

test('surface graphics preserve aspect after rotation and use outward face coordinates', () => {
  for (const face of ['x-', 'x+', 'y-', 'y+', 'z-', 'z+']) for (const rotation of [0, 90, 180, 270]) {
    const graphic = { face, rotation_degrees: rotation, u: .5, v: .5, width_fraction: .6, height_fraction: .3 };
    const placed = scene.graphicPlacement([.4, .3, .2], graphic, 3);
    assert.ok(Math.abs(placed.width / placed.height - 3) < 1e-10);
    const u = new THREE.Vector3(...placed.u), v = new THREE.Vector3(...placed.v), n = new THREE.Vector3(...placed.normal);
    assert.ok(u.cross(v).distanceTo(n) < 1e-10);
    const axis = 'xyz'.indexOf(face[0]), offset = placed.center[axis] - [.4, .3, .2][axis] / 2;
    assert.equal(Math.sign(offset), face.endsWith('+') ? 1 : -1);
    const larger = scene.graphicPlacement([.8, .6, .4], graphic, 3);
    assert.ok(Math.abs(larger.width - placed.width * 2) < 1e-10);
  }
  assert.throws(() => scene.graphicPlacement([1, 1, 1], { face: 'y+', rotation_degrees: 45 }, 1), /Invalid graphic/);
});

test('blank-area tare is computed from sourced area weight, never from the carton envelope', () => {
  const fields = { carton_name: 'Blank estimate', inner_0: '400', inner_1: '300', inner_2: '250', outer_0: '410', outer_1: '310', outer_2: '260',
    tare: '0.01', tare_evidence: 'stale', payload: '', carton_cost: '', tare_method: 'blank',
    blank_width: '800', blank_length: '1200', blank_quantity: '2', blank_basis_weight: '.4', blank_evidence: 'Supplier board and complete blank' };
  const result = ui.testReadCarton({ elements: { namedItem: name => ({ value: fields[name] }) } }, ui.defaultCarton());
  assert.equal(result.tare_kg, .768); assert.equal(result.tare_evidence, fields.blank_evidence);
  assert.deepEqual(result.board_blank.dimensions_m, [.8, 1.2]);
});

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

test('applying a candidate can restore every prior pad, graphic and allowance with Undo', () => {
  const draft = new ui.DraftDocument(), design = ui.emptyDesign();
  design.packages = [{ id: 'box_original', placements: [], inserts: [{ id: 'pad', density_kg_m3: 30 }], graphics: [{ id: 'graphic', kind: 'text', text: 'TEST' }], allowance_kg: .08, allowance_evidence: 'Measured tape' }];
  draft.accept({ id: 'pkg', revision: 2, design });
  const candidatePackages = [{ id: 'box_1', placements: [{ id: 'item_1' }], inserts: [], allowance_kg: null, allowance_evidence: '' }];
  draft.edit(d => { d.packages = ui.clone(candidatePackages); });
  assert.equal(draft.design.packages[0].allowance_kg, null);
  draft.undo(); assert.deepEqual(draft.design.packages, design.packages);
  draft.redo(); assert.deepEqual(draft.design.packages, candidatePackages);
  assert.ok(source.includes('Replace all package arrangements, pads, graphics and allowances'));
});

test('proposal protection inputs become closed SI records and blank rules stay absent', () => {
  const form = values => ({ elements: { namedItem: name => (name in values ? { value: String(values[name]) } : null) } });
  const zero = { cushion_floor: 0, cushion_top: 0, cushion_sides: 0, allowance_rule: '' };
  assert.deepEqual(ui.readProtection(form(zero)), { cushion: null, package_allowance: null });
  assert.throws(() => ui.readProtection(form({ ...zero, cushion_floor: 20, cushion_material: 'TEST foam', cushion_density: 35,
    cushion_material_evidence: ' ', cushion_evidence: 'TEST drop height' })), /cushion material/);
  const full = ui.readProtection(form({ cushion_floor: 20, cushion_top: 15, cushion_sides: 10, cushion_material: ' TEST foam ',
    cushion_density: 35, cushion_material_evidence: 'TEST datasheet', cushion_evidence: 'TEST drop height',
    allowance_rule: '0.12', allowance_rule_evidence: 'TEST tape' }));
  // Key order matches the server's Constraints dump, so an unchanged Apply leaves the draft clean.
  assert.equal(JSON.stringify(full), JSON.stringify({
    cushion: { floor_m: .02, top_m: .015, sides_m: .01, material: { name: 'TEST foam', density_kg_m3: 35, evidence: 'TEST datasheet' }, evidence: 'TEST drop height' },
    package_allowance: { allowance_kg: .12, evidence: 'TEST tape' } }));
  assert.throws(() => ui.readProtection(form({ ...zero, allowance_rule: '0', allowance_rule_evidence: ' ' })), /allowance includes/);
  assert.deepEqual(Object.keys(ui.emptyDesign().constraints), ['clearance_m', 'gap_m', 'allowed_orientations', 'contents']);
  assert.match(source, /d\.constraints = compactConstraints\(\{ \.\.\.d\.constraints, /);
});

test('candidate rows state how protection and allowances were carried', () => {
  assert.equal(ui.preservationText({ cushion: 'rebuilt_from_requirement', allowance: 'rule', carton_graphics: 'none', insert_graphics_dropped: 0 }),
    'foam lining rebuilt from the cushion requirement | allowance from the design rule');
  assert.equal(ui.preservationText({ cushion: 'not_required', allowance: 'unknown', carton_graphics: 'not_carried', insert_graphics_dropped: 0 }),
    'no cushion requirement | allowance unknown | some graphics not carried');
  assert.equal(ui.preservationText({ cushion: 'not_required', allowance: 'carried_forward', carton_graphics: 'carried_forward', insert_graphics_dropped: 2 }),
    'no cushion requirement | allowance carried from the saved packages | some graphics not carried');
  assert.equal(ui.preservationText(undefined), 'packing allowance and pads require review');
});

test('reusing a source retains appearance but never inherits mass evidence or calculation from a different source', () => {
  const prior = { name: 'Old', appearance: { color: '#FF0000' }, mass_basis: 'estimate', mass_kg: 4, mass_evidence: 'Old evidence', mass_calculation: { volume_m3: 1 }, source_id: 'old' };
  const metadata = { id: 'src_new', name: 'New source', dimensions_m: [.1, .2, .3], source_revision: 'a'.repeat(64) };
  const next = ui.productFromSource(metadata, prior);
  assert.deepEqual(next.appearance, prior.appearance); assert.notEqual(next.appearance, prior.appearance);
  assert.deepEqual(next.dimensions_m, metadata.dimensions_m); assert.notEqual(next.dimensions_m, metadata.dimensions_m);
  assert.equal(next.source_id, metadata.id); assert.equal(next.source_revision, metadata.source_revision);
  assert.equal(next.mass_kg, null); assert.equal(next.mass_calculation, null); assert.equal(next.mass_basis, 'unknown'); assert.equal(next.mass_evidence, '');
  assert.equal(prior.mass_kg, 4);
});

test('image crop honors authoritative trimmed alpha UVs with bottom-up V and rejects malformed metadata', () => {
  assert.deepEqual(scene.imageCrop({ width: 1000, height: 800, uv: [.1, .2, .9, .75] }), { x: 100, y: 200, width: 800, height: 440 });
  for (const metadata of [{ width: '100', height: 100, uv: [0, 0, 1, 1] }, { width: 4097, height: 100, uv: [0, 0, 1, 1] },
    { width: 100, height: 100, uv: [0, 0, NaN, 1] }, { width: 100, height: 100, uv: [.5, 0, .5, 1] },
    { width: 100, height: 100, uv: [0, 0, 1, 2] }]) assert.throws(() => scene.imageCrop(metadata), /metadata/);
});

test('pocket graphics masks stay in local coordinates through all rotations and only cut through floors on the bottom', () => {
  const dimensions = [.2, .05, .2], pockets = [
    { shape: 'rectangular', position_m: [.08, .01, .08], dimensions_m: [.04, .04, .04] },
    { shape: 'cylindrical', position_m: [.01, 0, .01], dimensions_m: [.02, .05, .02] },
  ];
  for (const rotation_degrees of [0, 90, 180, 270]) {
    const graphic = { face: 'y+', u: .5, v: .5, width_fraction: 1, height_fraction: 1, rotation_degrees };
    const paths = scene.graphicPocketPaths(dimensions, graphic, 1, pockets);
    assert.equal(paths.length, 2); assert.equal(paths[0].length, 4); assert.equal(paths[1].length, 96);
    for (const point of paths[0]) for (const value of point) assert.ok(Math.abs(value - .4) < 1e-9 || Math.abs(value - .6) < 1e-9);
    const bottom = scene.graphicPocketPaths(dimensions, { ...graphic, face: 'y-' }, 1, pockets);
    assert.equal(bottom.length, 1); assert.equal(bottom[0].length, 96);
    assert.deepEqual(scene.graphicPocketPaths(dimensions, { ...graphic, face: 'x+' }, 1, pockets), []);
  }
});

test('binary upload helper supports explicit STEP and image content types without encoding the payload', async () => {
  const calls = [], payload = new Uint8Array([1, 2, 3]);
  global.fetch = async (url, options) => { calls.push({ url, options }); return new Response('{}'); };
  for (const [path, contentType] of [['/sources/step?name=test.step', 'application/step'], ['/images', 'image/png'], ['/images', 'image/jpeg']]) {
    await ui.request(path, { method: 'POST', body: payload, raw: true, contentType });
    assert.equal(calls.at(-1).options.headers['Content-Type'], contentType);
    assert.equal(calls.at(-1).options.body, payload);
  }
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

test('first-save retry sends an explicit idempotency key without altering the document', async () => {
  const calls = [], design = ui.emptyDesign();
  global.fetch = async (url, options) => { calls.push(options); return new Response('{}'); };
  await ui.request('/documents', { method: 'POST', body: design, idempotencyKey: 'create_123' });
  assert.equal(calls[0].headers['Idempotency-Key'], 'create_123');
  assert.deepEqual(JSON.parse(calls[0].body), design);
  await ui.request('/documents');
  assert.equal(calls[1].headers['Idempotency-Key'], undefined);
});

test('carrier status distinguishes absent, saved unverified, and unavailable accounts', () => {
  assert.equal(ui.providerNotice(null), 'Provider status unavailable.');
  assert.equal(ui.providerNotice({ configured: false, validation: 'not_configured' }), 'No carrier account configured.');
  assert.equal(ui.providerNotice({ configured: true, validation: 'not_validated' }), 'Account saved; provider access has not been verified.');
  assert.equal(ui.providerNotice({ configured: false, validation: 'unavailable' }), 'Carrier account access is unavailable.');
  assert.equal(ui.providerNotice({ configured: true, notice: 'Provider supplied notice' }), 'Provider supplied notice');
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

test('quote freshness names account changes and requests carry only chosen options', () => {
  const quote = { revision: 2, stale: true };
  assert.equal(ui.quoteFreshness({ ...quote, stale_reason: 'account_changed' }, 2, false, true), 'Stale: carrier account changed');
  assert.equal(ui.quoteFreshness({ ...quote, stale_reason: 'account_removed' }, 2, false, true), 'Stale: carrier account removed');
  assert.equal(ui.quoteFreshness({ ...quote, stale_reason: 'account_changed' }, 3, false, true), 'Stale: package changed');
  assert.equal(ui.quoteFreshness({ ...quote, stale_reason: 'design_changed' }, 2, false, true), 'Stale: package changed');
  const addresses = { origin: { zip: '55401' }, destinations: [{ zip: '60601' }] };
  assert.deepEqual(ui.quoteBody(4, addresses, [], { delivery_confirmation: null, saturday_delivery: false }, false),
    { expected_revision: 4, ...addresses, carrier_accounts: [], options: {}, refresh: false });
  assert.deepEqual(ui.quoteBody(4, addresses, ['ca_TEST_A'], { delivery_confirmation: 'SIGNATURE', saturday_delivery: true }, 'yes'),
    { expected_revision: 4, ...addresses, carrier_accounts: ['ca_TEST_A'], options: { delivery_confirmation: 'SIGNATURE', saturday_delivery: true }, refresh: false });
  assert.equal(ui.quoteBody(4, addresses, [], {}, true).refresh, true);
  assert.equal(ui.priceText('USD', '4.10'), 'USD 4.10');
  assert.equal(ui.priceText('USD', null), '-');
  assert.equal(ui.priceText(null, undefined), '-');
});

test('constraints match the server form so an unchanged Apply is not an edit', () => {
  const base = { clearance_m: .02, gap_m: .01, allowed_orientations: [0], contents: 'unconfirmed' };
  assert.deepEqual(ui.compactConstraints({ ...base, cushion: null, package_allowance: null, no_contact: [] }), base);
  const region = { id: 'nc_1', name: 'Lens', face: 'y_max', area: null, air_gap_m: .005, evidence: 'TEST' };
  assert.deepEqual(Object.keys(ui.compactConstraints({ ...base, cushion: null, no_contact: [region] })),
    ['clearance_m', 'gap_m', 'allowed_orientations', 'contents', 'no_contact']);
  const draft = new ui.DraftDocument();
  draft.accept({ id: 'pkg_compact', revision: 1, design: ui.emptyDesign() });
  assert.equal(draft.edit(d => { d.constraints = ui.compactConstraints({ ...d.constraints, cushion: null, package_allowance: null }); }), false);
  assert.equal(draft.dirty, false);
  assert.match(source, /d\.constraints = compactConstraints\(\{ \.\.\.d\.constraints, clearance_m/);
});

test('no-contact regions read from the dialog and describe their face area', () => {
  const values = { region_name: ' Lens ', region_face: 'z_max', region_gap: '4', region_u0: '', region_u1: '', region_v0: '', region_v1: '',
    region_evidence: ' TEST polished face ' };
  const form = data => ({ elements: { namedItem: name => (name in data ? { value: data[name] } : null) } });
  assert.deepEqual(ui.readRegion(form(values), []),
    { id: 'nc_1', name: 'Lens', face: 'z_max', area: null, air_gap_m: .004, evidence: 'TEST polished face' });
  const part = ui.readRegion(form({ ...values, region_u0: '10', region_u1: '30', region_v0: '0', region_v1: '20' }), [{ id: 'nc_2' }]);
  assert.deepEqual([part.id, part.area], ['nc_3', { u_m: [.01, .03], v_m: [0, .02] }]);
  assert.equal(ui.regionText(part), 'Lens: Z max face, X 10-30 mm, Y 0-20 mm, air gap 4 mm');
  assert.equal(ui.regionText({ ...part, face: 'x_min', area: null }), 'Lens: X min face, whole face, air gap 4 mm');
  assert.throws(() => ui.readRegion(form({ ...values, region_u0: '10' }), []), /all four area limits/);
  assert.throws(() => ui.readRegion(form({ ...values, region_u0: '30', region_u1: '10', region_v0: '0', region_v1: '5' }), []), /below its end/);
  assert.throws(() => ui.readRegion(form({ ...values, region_evidence: ' ' }), []), /must not be touched/);
  assert.equal(ui.preservationText({ cushion: 'not_required', allowance: 'rule', carton_graphics: 'none', insert_graphics_dropped: 0, no_contact: 'air_gap_reserved' }),
    'no cushion requirement | allowance from the design rule | no-contact air gaps kept clear');
});

test('product face mapping follows the viewer rotation for every dimension order', () => {
  // [carton axis, mirrored] per product axis; must equal FACE_MAPPING in tests/test_packaging_no_contact.py.
  const expected = [[[0, false], [1, false], [2, false]], [[1, false], [0, true], [2, false]], [[2, false], [0, false], [1, false]],
    [[2, false], [1, false], [0, true]], [[1, false], [2, false], [0, false]], [[0, true], [2, false], [1, false]]];
  for (let o = 0; o < 6; o += 1) {
    const rows = ui.orientationRows(o);
    const mapping = [0, 1, 2].map(a => { const i = rows.findIndex(row => row[a] !== 0); return [i, rows[i][a] < 0]; });
    assert.deepEqual(mapping, expected[o], `orientation ${o}`);
  }
});

test('saved designs are quoted only under a complete session scenario', () => {
  const address = { street1: '1 Test Street', city: 'Testville', state: 'MN', zip: '55401' };
  assert.equal(ui.scenarioComplete({ origin: address, destinations: [address] }), true);
  assert.equal(ui.scenarioComplete({ origin: address, destinations: [] }), false);
  assert.equal(ui.scenarioComplete({ origin: { ...address, street1: ' ' }, destinations: [address] }), false);
  assert.equal(ui.scenarioComplete({ origin: address, destinations: [address, { ...address, zip: '' }] }), false);
  assert.equal(ui.scenarioComplete(undefined), false);
  assert.match(source, /Quote this design/);
  assert.match(source, /Set as baseline/);
  assert.match(source, /Use current design as baseline/);
  assert.match(source, /Unless this exact scenario was already priced, this creates \$\{shipments\} provider shipment\(s\)/);
});

test('comparison rows keep unknowns visible and follow the ranking', () => {
  const scenario = { destinations: [{ city: 'Testville', state: 'MN', zip: '55401', residential: true }, { city: 'Testburg', state: 'IL', zip: '60601', residential: false }],
    modes: ['test'], quotes: 2, quoted_at: '2026-11-06T10:00:00+00:00', current_account: false };
  assert.equal(ui.scenarioLabel(scenario), 'Testville, MN 55401 (residential); Testburg, IL 60601 | test | 2 quote(s) | latest 2026-11-06T10:00:00+00:00 | other carrier account');
  assert.equal(ui.differenceText('-4.66', 'USD'), 'USD -4.66 (lower)');
  assert.equal(ui.differenceText('2.10', 'USD'), 'USD +2.10 (higher)');
  assert.equal(ui.differenceText('0.00', 'USD'), 'USD 0.00 (same)');
  assert.equal(ui.differenceText(null, 'USD'), '-');
  const comparison = { service: { currency: 'USD' }, baseline: { ready: true }, ranking: ['alt_b', 'current'],
    reasons: { not_quoted: 'No saved quote matches.' }, caveats: { materials_unknown: 'Material cost is unknown.' },
    rows: [
      { ref: 'current', order: 0, name: 'Current', baseline: true, eligible: true, package_count: 2, gross_kg: 1.3, shipping_total: '27.48',
        materials_usd: null, total: null, shipping_difference: null, reasons: [], caveats: ['materials_unknown'] },
      { ref: 'alt_a', order: 1, name: 'A', baseline: false, eligible: false, package_count: 1, gross_kg: null, shipping_total: null,
        materials_usd: null, total: null, shipping_difference: null, reasons: ['not_quoted'], caveats: [] },
      { ref: 'alt_b', order: 2, name: 'B', baseline: false, eligible: true, package_count: 1, gross_kg: 1.15, shipping_total: '18.14',
        materials_usd: '1.50', total: '19.64', shipping_difference: '-9.34', reasons: [], caveats: [] }] };
  assert.deepEqual(ui.comparisonOrder(comparison).map(row => row.ref), ['alt_b', 'current', 'alt_a']);
  assert.deepEqual(ui.comparisonCells(comparison.rows[0], comparison),
    ['Current', 'Baseline', '2', '1.300 kg', 'USD 27.48', '-', '-', '-', 'Materials unknown']);
  assert.deepEqual(ui.comparisonCells(comparison.rows[1], comparison),
    ['A', 'Not compared', '1', 'Unknown', '-', '-', '-', '-', 'No saved quote matches.']);
  assert.deepEqual(ui.comparisonCells(comparison.rows[2], comparison),
    ['B', 'Compared', '1', '1.150 kg', 'USD 18.14', 'USD 1.50', 'USD 19.64', 'USD -9.34 (lower)', '']);
  assert.equal(ui.comparisonCells(comparison.rows[0], { ...comparison, baseline: { ready: false } })[1], 'Baseline (not ready)');
  const mixed = { ...comparison.rows[1], reasons: ['not_quoted'], caveats: ['test_mode', 'parcel_sum'] };
  assert.equal(ui.comparisonCells(mixed, comparison)[8], 'No saved quote matches. Test mode, Parcel sum');
  assert.match(source, /resourceDialog\('Compare costs', body => \{/);
  assert.match(source, /\}, \{ wide: true \}\);/);
  assert.match(source, /Reads saved quotes only\. No provider request is made\./);
  assert.match(source, /No saving is claimed: savings are stated only for production-mode quotes against a ready baseline\./);
});

test('carrier messages show one help line per carrier and category, never carrier text', () => {
  const messages = [
    { carrier: 'TEST Carrier', category: 'address', help: 'Check the address.', message: 'TEST 1 Private Street' },
    { carrier: 'TEST Carrier', category: 'address', help: 'Check the address.' },
    { carrier: null, category: 'other', help: 'Unrecognised problem.' },
  ];
  assert.deepEqual(ui.messageSummary(messages), ['TEST Carrier: Check the address.', 'Carrier: Unrecognised problem.']);
  assert.deepEqual(ui.messageSummary(undefined), []);
  assert.doesNotMatch(ui.messageSummary(messages).join(' '), /Private Street/);
  assert.match(source, /Refresh rates/);
  assert.match(source, /new provider shipment\(s\) for rating, which can be billed/);
  assert.match(source, /No provider request was made; use Refresh rates for new rates/);
  assert.match(source, /Test mode: these are not live carrier quotes/);
  assert.match(source, /got no response; the provider may still have created shipments/);
  assert.match(source, /Origin: \$\{note\.message\}/);
  assert.match(source, /request\('\/account\/carrier-accounts', \{ method: 'POST'/);
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
