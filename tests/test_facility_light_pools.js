'use strict';

// Floor light pools (docs/facility-lighting-plan.md, L3): finding lamps in a glowing geometry and building the
// pool quads, exercised against the vendored three.js r184.

const assert = require('assert');
const path = require('path');
const { pathToFileURL } = require('url');

const ROOT = path.resolve(__dirname, '..');
const pools = require('../static/facility_layout_light_pools.js');

const tests = [];
function test(name, callback) { tests.push({ name, callback }); }

let threeModule = null;
async function three() {
    if (!threeModule) {
        threeModule = await import(pathToFileURL(path.join(ROOT, 'static/vendor/three/0.184.0/build/three.module.min.js')).href);
    }
    return threeModule;
}

// Several geometries as one indexed geometry, like a light row's lens: one mesh holding every lamp.
function merge(THREE, geometries) {
    const positions = [];
    const indices = [];
    let offset = 0;
    geometries.forEach(geometry => {
        const position = geometry.attributes.position;
        for (let i = 0; i < position.count; i += 1) positions.push(position.getX(i), position.getY(i), position.getZ(i));
        for (let i = 0; i < geometry.index.count; i += 1) indices.push(geometry.index.getX(i) + offset);
        offset += position.count;
    });
    const merged = new THREE.BufferGeometry();
    merged.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    merged.setIndex(indices);
    return merged;
}

// Three round lenses 6 m apart along x, 15 mm thick, radius 0.1755 m (the Factory 02 high-bay lens).
function lensRow(THREE) {
    return merge(THREE, [0, 6, 12].map(x => new THREE.CylinderGeometry(0.1755, 0.1755, 0.015, 24).translate(x, 0, 0)));
}

test('lamps are the downward-facing patches of a glowing geometry, indexed or not', async () => {
    const THREE = await three();
    const row = lensRow(THREE);
    const lamps = pools.lampsOf(row);
    assert.deepStrictEqual(lamps.map(lamp => Math.round(lamp.x * 1000) / 1000), [0, 6, 12]);
    lamps.forEach(lamp => {
        assert.ok(Math.abs(lamp.y + 0.0075) < 1e-6, 'at the bottom face');
        assert.ok(Math.abs(lamp.z) < 1e-6);
        assert.ok(lamp.area > 0.09 && lamp.area < 0.0968, 'one lens bottom: ' + lamp.area);
    });
    assert.strictEqual(pools.lampsOf(row), lamps, 'cached per geometry');
    const loose = pools.lampsOf(row.toNonIndexed());
    assert.deepStrictEqual(loose.map(lamp => Math.round(lamp.x * 1000) / 1000), [0, 6, 12], 'corners joined by position');
    assert.deepStrictEqual(pools.lampsOf(new THREE.PlaneGeometry(1, 0.5)), [], 'a sign face looks sideways');
    const box = pools.lampsOf(new THREE.BoxGeometry(1, 0.2, 1));
    assert.strictEqual(box.length, 1, 'a box has one downward face');
    assert.ok(Math.abs(box[0].y + 0.1) < 1e-6 && Math.abs(box[0].area - 1) < 1e-6);
    assert.deepStrictEqual(pools.lampsOf(new THREE.BoxGeometry(0.02, 0.02, 0.02)), [], 'a sliver is not a lamp');
    assert.deepStrictEqual(pools.lampsOf(null), []);
});

test('a lamp is a part that faces down: a lens or a bowl, not the bottom edge of an exit sign (also for L7)', async () => {
    const THREE = await three();
    const share = geometry => pools.lampPartsOf(geometry).parts.map(part => part.lamp + ' ' + Math.round(100 * part.area
        / part.surface) + '%');
    // The Factory 02 exit-door sign is a thin glowing box: its bottom edge faces down but is 4% of it.
    assert.deepStrictEqual(share(new THREE.BoxGeometry(0.38, 0.21, 0.02)), ['false 4%']);
    assert.deepStrictEqual(share(new THREE.BoxGeometry(0.38, 0.21, 0.02).toNonIndexed()), ['false 4%'],
        'faces that only share corner positions are one part');
    assert.deepStrictEqual(share(new THREE.CylinderGeometry(0.1755, 0.1755, 0.015, 24)), ['true 46%']);
    assert.deepStrictEqual(share(new THREE.SphereGeometry(0.2, 24, 12, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2)),
        ['true 29%'], 'a bowl facing down');
    const row = lensRow(THREE);
    const parts = pools.lampPartsOf(row);
    assert.strictEqual(parts.lamps, 3);
    assert.deepStrictEqual(parts.parts.map(part => Math.round(part.x * 1000) / 1000), [0, 6, 12], 'numbered as they come');
    assert.strictEqual(parts.vertexPart.length, row.attributes.position.count);
    for (let vertex = 0; vertex < row.attributes.position.count; vertex += 1) {
        assert.strictEqual(parts.vertexPart[vertex], Math.round(row.attributes.position.getX(vertex) / 6) || 0, 'its own lens');
    }
    assert.strictEqual(pools.lampPartsOf(row), parts, 'cached per geometry');
    assert.deepStrictEqual(pools.lampPartsOf(null).parts, []);
});

test('each copy hung high and facing down throws one pool per lamp, wider the higher it hangs', async () => {
    const THREE = await three();
    const color = new THREE.Color(1, 0.97, 0.9);
    const identity = new THREE.Matrix4();
    const mesh = new THREE.InstancedMesh(lensRow(THREE), new THREE.MeshBasicMaterial(), 4);
    const at = (x, y, z, rotationX, scale) => new THREE.Matrix4().compose(new THREE.Vector3(x, y, z),
        new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), rotationX || 0),
        new THREE.Vector3(scale === undefined ? 1 : scale, scale === undefined ? 1 : scale, scale === undefined ? 1 : scale));
    mesh.setMatrixAt(0, at(100, 9.9, 20));        // a high-bay row: three pools
    mesh.setMatrixAt(1, at(100, 2, 40));          // too low
    mesh.setMatrixAt(2, at(100, 9.9, 60, Math.PI)); // upside down: the lenses face the roof
    mesh.setMatrixAt(3, at(100, 9.9, 80, 0, 0));  // hidden, zero scale
    mesh.updateMatrixWorld(true);
    const found = pools.poolsOf(THREE, mesh, identity, color, 0);
    assert.deepStrictEqual(found.map(pool => [Math.round(pool.x * 100) / 100, Math.round(pool.z * 100) / 100]),
        [[100, 20], [106, 20], [112, 20]]);
    found.forEach(pool => {
        assert.ok(Math.abs(pool.radius - 0.5 * (9.9 - 0.0075)) < 1e-6, 'radius from the hanging height');
        assert.strictEqual(pool.color, color);
    });
    const single = new THREE.Mesh(lensRow(THREE), new THREE.MeshBasicMaterial());
    single.position.set(0, 6, 0);
    single.updateMatrixWorld(true);
    assert.deepStrictEqual(pools.poolsOf(THREE, single, identity, color, 0).map(pool => Math.round(pool.radius * 1000) / 1000),
        [2.996, 2.996, 2.996]);
    assert.strictEqual(pools.poolsOf(THREE, single, identity, color, 3.5).length, 0, 'measured from the floor given');
    assert.strictEqual(pools.poolRadius(40), 6, 'capped');
    assert.strictEqual(pools.poolRadius(3), 1.5, 'and floored');
    const sign = new THREE.Mesh(new THREE.PlaneGeometry(1, 0.5), new THREE.MeshBasicMaterial());
    sign.position.set(0, 9, 0);
    sign.updateMatrixWorld(true);
    assert.deepStrictEqual(pools.poolsOf(THREE, sign, identity, color, 0), [], 'no lamps, no pools');
});

test('a thin recessed downlight hung flush with a 3.2 m ceiling is a lamp: 28 of them throw 28 pools', async () => {
    // The gym lounge's downlights (ceiling mounting, 2026-11-02): 0.15 x 0.15 x 0.015 m, the base 3.185 m up so the
    // top meets the ceiling, the lens (its underside) facing down, about 3 m apart.
    const THREE = await three();
    const color = new THREE.Color(1, 0.85, 0.6);
    const downlight = new THREE.BoxGeometry(0.15, 0.015, 0.15).translate(0, 0.0075, 0);
    assert.deepStrictEqual(pools.lampsOf(downlight).length, 1, 'one lamp: its underside');
    const mesh = new THREE.InstancedMesh(downlight, new THREE.MeshBasicMaterial(), 28);
    for (let index = 0; index < 28; index += 1) {
        mesh.setMatrixAt(index, new THREE.Matrix4().makeTranslation(1.5 + 3 * (index % 7), 3.2 - 0.015, 1.5 + 3 * Math.floor(index / 7)));
    }
    mesh.updateMatrixWorld(true);
    const found = pools.poolsOf(THREE, mesh, new THREE.Matrix4(), color, 0);
    assert.strictEqual(found.length, 28);
    assert.deepStrictEqual([found[0].x, found[0].z, found[27].x, found[27].z].map(v => Math.round(v * 1000) / 1000),
        [1.5, 1.5, 19.5, 10.5], 'each under its downlight');
    found.forEach(pool => assert.ok(Math.abs(pool.radius - pools.poolRadius(3.185)) < 1e-6, 'from 3.185 m up'));
});

test('pool quads lie face up on the floor, colored per pool, with a soft round spot', async () => {
    const THREE = await three();
    const warm = new THREE.Color(1, 0.8, 0.6);
    const cool = new THREE.Color(0.9, 0.95, 1);
    const geometry = pools.poolGeometry(THREE, [{ x: 0, z: 0, radius: 2, color: warm }, { x: 10, z: 5, radius: 1, color: cool }], 0.02);
    const position = geometry.attributes.position;
    assert.strictEqual(position.count, 8);
    assert.strictEqual(geometry.index.count, 12);
    for (let i = 0; i < position.count; i += 1) assert.strictEqual(position.getY(i), Math.fround(0.02));
    for (let t = 0; t < 4; t += 1) {
        const [a, b, c] = [0, 1, 2].map(k => new THREE.Vector3().fromBufferAttribute(position, geometry.index.getX(3 * t + k)));
        const normal = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(c, a));
        assert.ok(normal.y > 0, 'triangle ' + t + ' faces up');
    }
    const box = geometry.boundingBox;
    assert.deepStrictEqual([box.min.x, box.max.x, box.min.z, box.max.z], [-2, 11, -2, 6]);
    assert.ok(Math.abs(geometry.attributes.color.getX(4) - 0.9) < 1e-6, 'the second pool takes its own color');
    const texture = pools.poolTexture(THREE);
    const data = texture.image.data;
    const alpha = (x, y) => data[(y * texture.image.width + x) * 4 + 3];
    assert.ok(alpha(32, 32) > 250, 'bright in the middle');
    assert.strictEqual(alpha(0, 0), 0, 'nothing in the corners');
    assert.ok(alpha(48, 32) > 0 && alpha(48, 32) < alpha(40, 32), 'fading out');
    assert.strictEqual(data[0], 255, 'white; the falloff is in alpha');
});

// Outdoor lights (L8): a lamp's aim, the pool where its beam meets the ground, and the beam's cone.
test('a lamp aims where its downward patches face: straight down for a lens, tilted for a wall light', async () => {
    const THREE = await three();
    pools.lampsOf(lensRow(THREE)).forEach(lamp => {
        assert.ok(Math.abs(lamp.nx) < 1e-9 && Math.abs(lamp.ny + 1) < 1e-9 && Math.abs(lamp.nz) < 1e-9, 'down');
    });
    // A wall light's lens tipped 30 degrees: its face looks down and out (the lens edges look sideways).
    const tilted = pools.lampsOf(new THREE.CylinderGeometry(0.1, 0.1, 0.015, 24).rotateX(Math.PI / 6));
    assert.strictEqual(tilted.length, 1);
    const aim = [tilted[0].nx, tilted[0].ny, tilted[0].nz];
    [0, -Math.cos(Math.PI / 6), -Math.sin(Math.PI / 6)].forEach((value, k) => {
        assert.ok(Math.abs(aim[k] - value) < 1e-6, 'aim ' + aim);
    });
    assert.ok(Math.abs(Math.hypot(...aim) - 1) < 1e-9, 'a unit vector');
});

test('an outdoor lamp lights the ground where its aim lands, as wide as its beam', async () => {
    const flat = () => 0;
    const close = (actual, expected, label) => assert.ok(Math.abs(actual - expected) < 1e-9, label + ': ' + actual + ' vs ' + expected);
    const tan = degrees => Math.tan(degrees * Math.PI / 180);
    const down = pools.aimedPool({ x: 0, y: 8, z: 0 }, { x: 0, y: -1, z: 0 }, 110, flat);
    [['x', 0], ['y', 0], ['z', 0], ['length', 8], ['radius', 8 * tan(55)]].forEach(([key, value]) => close(down[key], value, key));
    // A wall light 6 m up aimed 30 degrees out from straight down lands 6 tan 30 out from the wall.
    const out = pools.aimedPool({ x: 0, y: 6, z: 0 }, { x: 0, y: -Math.cos(Math.PI / 6), z: Math.sin(Math.PI / 6) }, 100, flat);
    close(out.length, 6 / Math.cos(Math.PI / 6), 'length');
    close(out.z, 6 * tan(30), 'out from the wall');
    close(out.radius, out.length * tan(50), 'radius');
    // A sunken truck yard east of x 2, 1.35 m down: straight down into it, and slanting over the dock edge into it.
    const yard = (x) => (x > 2 ? -1.35 : 0);
    const sunk = pools.aimedPool({ x: 5, y: 8, z: 0 }, { x: 0, y: -1, z: 0 }, 70, yard);
    close(sunk.y, -1.35, 'on the yard');
    close(sunk.length, 9.35, 'length');
    const over = pools.aimedPool({ x: 0, y: 8, z: 0 }, { x: Math.sin(Math.PI / 6), y: -Math.cos(Math.PI / 6), z: 0 }, 70, yard);
    close(over.y, -1.35, 'past the edge');
    close(over.length, 9.35 / Math.cos(Math.PI / 6), 'length');
    close(over.x, over.length * Math.sin(Math.PI / 6), 'along its aim');
    assert.strictEqual(pools.aimedPool({ x: 0, y: 8, z: 0 }, { x: 0, y: 1, z: 0 }, 110, flat), null, 'aimed up');
    assert.strictEqual(pools.aimedPool({ x: 0, y: -1, z: 0 }, { x: 0, y: -1, z: 0 }, 110, flat), null, 'under the ground');
    assert.strictEqual(pools.aimedPool({ x: 0, y: 8, z: 0 }, { x: 0, y: -1, z: 0 }, 110, () => -1000), null,
        'no ground within ' + pools.BEAM_REACH + ' m');
});

test('with a beam, each copy throws its pool on the ground under its aim and records the beam', async () => {
    const THREE = await three();
    const color = new THREE.Color(1, 0.95, 0.86);
    const identity = new THREE.Matrix4();
    const head = new THREE.CylinderGeometry(0.2, 0.2, 0.015, 24);
    const mesh = new THREE.InstancedMesh(head, new THREE.MeshBasicMaterial(), 4);
    const at = (x, y, z, rotationX) => new THREE.Matrix4().compose(new THREE.Vector3(x, y, z),
        new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), rotationX || 0), new THREE.Vector3(1, 1, 1));
    mesh.setMatrixAt(0, at(0, 8, 0));                 // a car park pole
    mesh.setMatrixAt(1, at(30, 8, 0));                // a pole in the sunken yard
    mesh.setMatrixAt(2, at(10, 2, 0));                // too low
    mesh.setMatrixAt(3, at(0, 8, 40, Math.PI / 6));   // tilted 30 degrees
    mesh.updateMatrixWorld(true);
    const ground = (x) => (x > 20 ? -1.35 : 0);
    const found = pools.poolsOf(THREE, mesh, identity, color, 0, { angleDegrees: 110, groundAt: ground });
    assert.strictEqual(found.length, 3);
    const tan55 = Math.tan(55 * Math.PI / 180);
    found.forEach(pool => {
        const end = ['x', 'y', 'z'].map(k => pool.lamp[k] + pool.aim[k] * pool.length);
        assert.ok(Math.abs(end[0] - pool.x) < 1e-6 && Math.abs(end[1] - pool.y) < 1e-6 && Math.abs(end[2] - pool.z) < 1e-6,
            'the pool is where the aim lands');
        assert.ok(Math.abs(pool.y - ground(pool.x)) < 1e-9, 'on the ground');
        assert.ok(Math.abs(pool.radius - pool.length * tan55) < 1e-9, 'as wide as the beam');
        assert.strictEqual(pool.beamAngleDegrees, 110);
        assert.strictEqual(pool.color, color);
    });
    assert.ok(Math.abs(found[0].length - (8 - 0.0075)) < 1e-6 && Math.abs(found[1].length - (9.35 - 0.0075)) < 1e-6);
    assert.ok(found[2].z < 40 - 4, 'the tilted one lands out along its aim: ' + found[2].z);
    // Without a beam the same copies throw the floor pools of L3, under each lamp (the tilted one too: it faces down).
    assert.deepStrictEqual(pools.poolsOf(THREE, mesh, identity, color, 0).map(pool => [Math.round(pool.x * 100) / 100 + 0,
        Math.round(pool.z * 100) / 100 + 0, pool.lamp]), [[0, 0, undefined], [30, 0, undefined], [0, 40, undefined]]);
});

test('an outdoor pool lies on its own ground, and a beam is an open cone from the lamp to a unit ring', async () => {
    const THREE = await three();
    const warm = new THREE.Color(1, 0.8, 0.6);
    const quads = pools.poolGeometry(THREE, [{ x: 0, z: 0, radius: 2, color: warm, y: -1.35 }, { x: 10, z: 5, radius: 1, color: warm }], 0.02);
    assert.deepStrictEqual([0, 4].map(v => Math.round(quads.attributes.position.getY(v) * 1000) / 1000), [-1.33, 0.02]);
    const cone = pools.beamGeometry(THREE);
    const position = cone.attributes.position;
    const along = cone.attributes.beamAlong;
    const normal = cone.attributes.normal;
    assert.strictEqual(position.count, along.count);
    for (let v = 0; v < position.count; v += 1) {
        const p = new THREE.Vector3().fromBufferAttribute(position, v);
        if (along.getX(v) === 0) assert.ok(p.length() < 1e-9, 'the tip at the lamp');
        else {
            assert.strictEqual(along.getX(v), 1);
            assert.ok(Math.abs(p.y + 1) < 1e-6 && Math.abs(Math.hypot(p.x, p.z) - 1) < 1e-6, 'the base ring');
        }
        assert.ok(Math.abs(new THREE.Vector3().fromBufferAttribute(normal, v).length() - 1) < 1e-6);
    }
    assert.strictEqual(cone.index.count / 3, 24, 'one triangle per side, no cap');
    for (let t = 0; t < cone.index.count / 3; t += 1) {
        const [a, b, c] = [0, 1, 2].map(k => new THREE.Vector3().fromBufferAttribute(position, cone.index.getX(3 * t + k)));
        const face = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(c, a));
        const centre = new THREE.Vector3().add(a).add(b).add(c).divideScalar(3);
        assert.ok(face.x * centre.x + face.z * centre.z > 0 && face.y > 0, 'triangle ' + t + ' faces out');
    }
    assert.ok(/beamAlong/.test(pools.BEAM_VERTEX_SHADER) && /project_vertex/.test(pools.BEAM_VERTEX_SHADER));
    assert.ok(/instanceColor/.test(pools.BEAM_VERTEX_SHADER) && /facilityBeamStrength/.test(pools.BEAM_FRAGMENT_SHADER));
});

// Lamps that light things (2026-11-02): pendants over tables and accent spots become spot light candidates; the
// general lighting's pools sum into a fill map that lit materials add below the lamps.
test('a pendant hung over a table and an accent spot aimed along its lens are spot candidates; high lamps are not', async () => {
    const THREE = await three();
    const identity = new THREE.Matrix4();
    // A billiard pendant's three shades, 1.2 m apart, their lenses facing down.
    const shades = merge(THREE, [-1.2, 0, 1.2].map(x => new THREE.CylinderGeometry(0.15, 0.15, 0.01, 16).translate(x, 0, 0)));
    const mesh = new THREE.InstancedMesh(shades, new THREE.MeshBasicMaterial(), 4);
    mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(2.65, 1.7184, -11.5)); // over the pool table
    mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(9, 3.185, -10));       // high: it throws pools instead
    mesh.setMatrixAt(2, new THREE.Matrix4().makeTranslation(9, 0.3, -10));         // on the floor
    mesh.setMatrixAt(3, new THREE.Matrix4().makeScale(0, 0, 0));                   // hidden
    mesh.updateMatrixWorld(true);
    const glow = { color: '#ffd29a', intensity: 1, lumens: 4000, estimateBeamAngleDegrees: 110 };
    const found = pools.spotsOf(THREE, mesh, identity, glow, 0);
    assert.strictEqual(found.length, 1, 'only the pendant over the table');
    const spot = found[0];
    assert.deepStrictEqual([spot.x, spot.y, spot.z].map(v => Math.round(v * 100) / 100), [2.65, 1.71, -11.5],
        'one spot for the fixture, at the centre of its shades');
    assert.strictEqual(spot.kind, 'pendant');
    assert.strictEqual(spot.lamps, 3);
    assert.ok(Math.abs(spot.aim.y + 1) < 1e-6, 'straight down');
    assert.deepStrictEqual(pools.spotsOf(THREE, mesh, identity, null, 0), [], 'no glow, no light');
    assert.deepStrictEqual(pools.spotsOf(THREE, mesh, identity, { color: '#2fd36b', intensity: 1 }, 0), [],
        'a finish without lighting data (an exit sign, a signal lamp) lights nothing');
    // A vintage pendant's bare bulbs face down only at their tips, a tenth of their surface: still its lamps.
    const bulbs = merge(THREE, [-0.4, 0, 0.4].map(x => new THREE.SphereGeometry(0.03, 16, 12).scale(1, 2, 1).translate(x, 0, 0)));
    assert.strictEqual(pools.lampsOf(bulbs).length, 0, 'no lamp by the share rule');
    assert.strictEqual(pools.bulbsOf(bulbs).length, 3);
    const vintage = new THREE.Mesh(bulbs, new THREE.MeshBasicMaterial());
    vintage.position.set(2.65, 1.75, -11.5);
    vintage.updateMatrixWorld(true);
    const lit = pools.spotsOf(THREE, vintage, identity, glow, 0);
    assert.strictEqual(lit.length, 1);
    assert.deepStrictEqual([lit[0].x, lit[0].z].map(v => Math.round(v * 100) / 100), [2.65, -11.5]);
    assert.ok(lit[0].y < 1.75 && lit[0].aim.y < -0.99, 'at the bulb tips, aimed down');
    assert.strictEqual(lit[0].lamps, 3);
    // An exit sign's bottom edge faces down too, but its finish has no lighting data.
    const sign = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.2, 0.05), new THREE.MeshBasicMaterial());
    sign.position.set(0, 2.2, 0);
    sign.updateMatrixWorld(true);
    assert.deepStrictEqual(pools.spotsOf(THREE, sign, identity, { color: '#2fd36b', intensity: 1 }, 0), []);
    // An accent spot (asset-gym-accent-spot-30): its lens faces 30 degrees off down toward +z; yaw 180 turns it
    // toward -z. It is a candidate at any height, aimed along its lens as placed.
    const lens = new THREE.CylinderGeometry(0.03, 0.03, 0.004, 16).rotateX(-Math.PI / 6);
    const accent = { color: '#ffc08a', intensity: 1, beamAngleDegrees: 30, accent: true, lumens: 700 };
    const spotMesh = new THREE.InstancedMesh(lens, new THREE.MeshBasicMaterial(), 2);
    spotMesh.setMatrixAt(0, new THREE.Matrix4().compose(new THREE.Vector3(1.6, 3.1324, -3.9),
        new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI), new THREE.Vector3(1, 1, 1)));
    spotMesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(3.7, 3.1324, -3.9));
    spotMesh.updateMatrixWorld(true);
    const aimed = pools.spotsOf(THREE, spotMesh, identity, accent, 0);
    assert.strictEqual(aimed.length, 2);
    assert.ok(aimed.every(item => item.kind === 'accent'));
    const round = v => Math.round(v * 1000) / 1000 + 0;
    assert.deepStrictEqual([aimed[0].aim.x, aimed[0].aim.y, aimed[0].aim.z].map(round), [0, -0.866, -0.5], 'yaw 180: toward -z');
    assert.deepStrictEqual([aimed[1].aim.x, aimed[1].aim.y, aimed[1].aim.z].map(round), [0, -0.866, 0.5], 'as modelled');
    // The same lens glowing as a plain light is no pendant: 3.13 m up, it throws a pool.
    assert.deepStrictEqual(pools.spotsOf(THREE, spotMesh, identity, { color: '#ffffff' }, 0), []);
});

test('a spot light has settings from the lamp lumens and beam: candela, cone, soft edge and reach', () => {
    const accent = pools.spotSettings({ kind: 'accent' }, { lumens: 700, beamAngleDegrees: 30, estimateBeamAngleDegrees: 30 });
    const half = 15 * Math.PI / 180;
    const m = Math.log(0.5) / Math.log(Math.cos(half));
    assert.ok(Math.abs(accent.intensity - 700 * (m + 1) / (2 * Math.PI) * pools.LUX_TO_SCENE) < 1e-9);
    assert.ok(Math.abs(accent.angle - 1.5 * half) < 1e-9, '1.5 times half the beam');
    assert.strictEqual(accent.distance, 8);
    assert.strictEqual(accent.decay, 2);
    assert.ok(accent.penumbra > 0.5);
    // A pendant from its finish estimate: 4000 lm at 110 degrees; a wider beam's cone stops at 85 degrees.
    const pendant = pools.spotSettings({ kind: 'pendant' }, { lumens: 4000, estimateBeamAngleDegrees: 110 });
    assert.ok(Math.abs(pendant.angle - 82.5 * Math.PI / 180) < 1e-9);
    const wide = pools.spotSettings({ kind: 'pendant' }, { lumens: 4000, estimateBeamAngleDegrees: 140 });
    assert.ok(Math.abs(wide.angle - 85 * Math.PI / 180) < 1e-9);
    assert.strictEqual(pendant.distance, 6);
    // On the felt 1.7 m below: about 500 lux.
    const lux = pendant.intensity / pools.LUX_TO_SCENE / (1.7 * 1.7);
    assert.ok(lux > 450 && lux < 550, 'lux ' + lux);
    // Without data: typical values, not nothing.
    const plain = pools.spotSettings({ kind: 'accent' }, {});
    assert.ok(Math.abs(plain.intensity - accent.intensity) < 1e-9, '700 lm at 30 degrees');
    assert.ok(pools.spotSettings({ kind: 'pendant' }, null).intensity > 0);
});

test('the general lighting fill is a map of its pools, gentle, capped, and only below the lamps', () => {
    assert.strictEqual(pools.fillField([]), null);
    assert.strictEqual(pools.fillField([{ x: 0, z: 0, radius: 1.5, color: { r: 1, g: 1, b: 1 } }]), null, 'no lamp height');
    const white = { r: 1, g: 1, b: 1 };
    const one = pools.fillField([{ x: 0, z: 0, radius: 1.5, color: white, lampY: 3.185 }]);
    assert.strictEqual(one.pools, 1);
    assert.strictEqual(one.cell, 0.25);
    assert.deepStrictEqual([one.minX, one.minZ, one.cols, one.rows], [-3, -3, 24, 24], 'out to twice the pool radius');
    const at = (field, x, z) => {
        const i = Math.floor((x - field.minX) / field.cell);
        const j = Math.floor((z - field.minZ) / field.cell);
        return Array.from(field.data.slice((j * field.cols + i) * 4, (j * field.cols + i) * 4 + 4));
    };
    const middle = at(one, 0.1, 0.1);
    assert.ok(middle[0] > 0.4 && middle[0] <= pools.FILL_PEAK, 'about FILL_PEAK under the lamp: ' + middle[0]);
    assert.ok(Math.abs(middle[3] - (3.185 - pools.FILL_BELOW)) < 1e-6, 'lit only below the lamp');
    const edge = at(one, 2.4, 0.1);
    assert.ok(edge[0] > 0 && edge[0] < middle[0] / 4, 'fading toward the edge: ' + edge[0]);
    assert.deepStrictEqual(at(one, 2.9, 2.9), [0, 0, 0, 0], 'nothing past the reach');
    // Many lamps over one spot add up, to a cap; a warm lamp gives a warm fill.
    const crowd = pools.fillField(Array.from({ length: 9 }, () => ({ x: 0, z: 0, radius: 1.5, color: white, lampY: 3 })));
    assert.ok(Math.abs(at(crowd, 0.1, 0.1)[0] - pools.FILL_LIMIT) < 1e-6);
    const warm = pools.fillField([{ x: 0, z: 0, radius: 1.5, color: { r: 1, g: 0.8, b: 0.5 }, lampY: 3 }]);
    const tint = at(warm, 0.1, 0.1);
    assert.ok(tint[0] > tint[1] && tint[1] > tint[2]);
    // A whole factory floor stays within 512 texels a side.
    const hall = pools.fillField([{ x: 0, z: 0, radius: 5, color: white, lampY: 10 },
        { x: 400, z: 150, radius: 5, color: white, lampY: 10 }]);
    assert.ok(hall.cols <= 512 && hall.rows <= 512 && hall.cell > 0.25);
    assert.ok(pools.insideOutline([{ x: -1, z: -3 }, { x: 3, z: -3 }, { x: 3, z: 3 }, { x: -1, z: 3 }], 0, 0));
    assert.ok(!pools.insideOutline([{ x: -1, z: -3 }, { x: 3, z: -3 }, { x: 3, z: 3 }, { x: -1, z: 3 }], -2, 0));
    assert.ok(!pools.insideOutline(null, 0, 0));
});

// Under zone ceilings only (2026-11-02): the shader adds the fill only where the ceiling mask, read as the GPU reads
// it (linear between texel centres), is above zero: never outside the footprint, inside all but a centimetre along a
// straight edge and a little more in an inner corner.
test('the ceiling mask cuts the fill at the ceilings\' edge and never lights outside it, and builds fast', () => {
    const white = { r: 1, g: 1, b: 1 };
    const field = pools.fillField([{ x: 0, z: 0, radius: 1.5, color: white, lampY: 3.185 }]);
    const room = [{ x: -1.1, z: -3 }, { x: 3, z: -3 }, { x: 3, z: 3 }, { x: -1.1, z: 3 }];
    const mask = pools.fillMask(field, [room]);
    const fine = pools.FILL_MASK_SUBDIVIDE;
    assert.deepStrictEqual([mask.minX, mask.minZ, mask.cols, mask.rows, mask.cell],
        [field.minX, field.minZ, field.cols * fine, field.rows * fine, field.cell / fine], 'finer, over the same plan');
    const read = (x, z) => pools.sampleMask(mask, x, z);
    const inset = pools.FILL_MASK_INSET;
    const reach = pools.FILL_EDGE_TEXELS * mask.cell;
    // The lamp would reach 1.9 m past the wall at x -1.1.
    assert.ok(pools.sampleLinear(field, -1.3, 0.1, 4, 0) > 0, 'the fill map itself reaches past the wall');
    for (const outside of [0, 0.001, 0.01, 0.05, 0.2, 0.4, 1.5]) {
        assert.ok(read(-1.1 - outside, 0.1) < 0, outside + ' m outside: no fill (' + read(-1.1 - outside, 0.1) + ')');
    }
    assert.ok(read(-1.1 + inset * 0.9, 0.1) < 0, 'a face on the edge (a wall\'s outer face) is outside');
    for (const inside of [0.011, 0.05, 0.09, 0.12]) {
        assert.ok(Math.abs(read(-1.1 + inside, 0.1) - (inside - inset)) < 1e-6, inside + ' m inside: lit, the distance');
    }
    assert.strictEqual(read(1, 0.1), Math.fround(reach - inset), 'deep inside: clamped');
    assert.ok(read(-2.6, 0.1) < 0 && read(-2.99, 0.1) < 0, 'outside, to the map border');
    // Two rooms side by side: the edge they share is inside the footprint, without a dip.
    const left = [{ x: -2.5, z: -3 }, { x: -1.1, z: -3 }, { x: -1.1, z: 3 }, { x: -2.5, z: 3 }];
    const both = pools.fillMask(field, [left, room]);
    for (const x of [-1.4, -1.1, -1, -0.8]) {
        assert.strictEqual(pools.sampleMask(both, x, 0.1), Math.fround(reach - inset), 'shared edge at ' + x);
    }
    assert.ok(pools.sampleMask(both, -2.52, 0.1) < 0 && pools.sampleMask(both, -2.48, 0.1) > 0, 'the outer edge still cuts');
    // A room inside a bigger one with a ceiling: the bigger one's edge only.
    const nested = pools.fillMask(field, [[{ x: -3, z: -3 }, { x: 3, z: -3 }, { x: 3, z: 3 }, { x: -3, z: 3 }], room]);
    assert.strictEqual(pools.sampleMask(nested, -1.1, 0.1), Math.fround(reach - inset), 'a nested room adds no edge');
    // Never lit outside, also by an inner corner, a step between two rooms, a gap narrower than a texel or a slanted
    // overlap (where plain linear filtering of distances would leak a few centimetres), probed every 7 mm; inside,
    // dark only near an edge.
    const shapes = {
        ell: [[{ x: -2.07, z: -2.1 }, { x: 2.13, z: -2.1 }, { x: 2.13, z: 0.06 }, { x: 0.11, z: 0.06 }, { x: 0.11, z: 2.2 }, { x: -2.07, z: 2.2 }]],
        step: [[{ x: -3, z: -2 }, { x: 0.07, z: -2 }, { x: 0.07, z: 2 }, { x: -3, z: 2 }], [{ x: 0.07, z: -1 }, { x: 3, z: -1 }, { x: 3, z: 3 }, { x: 0.07, z: 3 }]],
        gap: [[{ x: -3, z: -2 }, { x: -0.03, z: -2 }, { x: -0.03, z: 2 }, { x: -3, z: 2 }], [{ x: 0.05, z: -2 }, { x: 3, z: -2 }, { x: 3, z: 2 }, { x: 0.05, z: 2 }]],
        slanted: [[{ x: -3, z: -2 }, { x: 0.5, z: -2 }, { x: 0.5, z: 1 }, { x: -3, z: 1 }], [{ x: -0.4, z: -0.7 }, { x: 3, z: -1.3 }, { x: 2.6, z: 2.9 }, { x: -0.9, z: 2.4 }]],
        hallway: [[{ x: -3, z: -2 }, { x: -0.03, z: -2 }, { x: -0.03, z: 2 }, { x: -3, z: 2 }], [{ x: 0.05, z: -2 }, { x: 3, z: -2 }, { x: 3, z: 2 }, { x: 0.05, z: 2 }],
            [{ x: -3, z: 2 }, { x: 3, z: 2 }, { x: 3, z: 2.9 }, { x: -3, z: 2.9 }]],
    };
    Object.entries(shapes).forEach(([name, outlines]) => {
        const shaped = pools.fillMask(field, outlines);
        let lit = 0;
        let darkFar = 0;
        for (let x = -2.98; x <= 2.98; x += 0.0071) {
            for (let z = -2.98; z <= 2.98; z += 0.0073) {
                const value = pools.sampleMask(shaped, x, z);
                if (!outlines.some(outline => pools.insideOutline(outline, x, z))) {
                    if (value > 0) lit += 1;
                } else if (value <= 0 && outlines.every(outline => outline.every((point, k) => {
                    const next = outline[(k + 1) % outline.length];
                    const length = Math.hypot(next.x - point.x, next.z - point.z);
                    const t = Math.max(0, Math.min(1, ((x - point.x) * (next.x - point.x) + (z - point.z) * (next.z - point.z)) / (length * length)));
                    return Math.hypot(x - point.x - (next.x - point.x) * t, z - point.z - (next.z - point.z) * t) > 0.2;
                }))) darkFar += 1;
            }
        }
        assert.strictEqual(lit, 0, name + ': no fill outside');
        assert.strictEqual(darkFar, 0, name + ': inside, dark only within 0.2 m of an edge');
    });
    // Codex review of b4437c2: two rooms 8 cm apart (a wall's width). Each footprint reads its own distances in its
    // own channel, so a wall face 5 cm inside the first room keeps its fill when the second gets a ceiling.
    const first = [{ x: -3, z: -2 }, { x: -0.03, z: -2 }, { x: -0.03, z: 2 }, { x: -3, z: 2 }];
    const second = [{ x: 0.05, z: -2 }, { x: 3, z: -2 }, { x: 3, z: 2 }, { x: 0.05, z: 2 }];
    const alone = pools.fillMask(field, [first]);
    const paired = pools.fillMask(field, [first, second]);
    assert.deepStrictEqual([alone.channels, paired.channels], [1, 2]);
    assert.ok(Math.abs(pools.sampleMask(alone, -0.08, 0.3) - (0.05 - inset)) < 1e-6, 'the wall, one room');
    assert.strictEqual(pools.sampleMask(paired, -0.08, 0.3), pools.sampleMask(alone, -0.08, 0.3), 'the wall, both rooms');
    assert.ok(pools.sampleMask(paired, 0.01, 0.3) < 0 && pools.sampleMask(paired, 0.1, 0.3) > 0, 'the gap dark, the second lit');
    // Codex re-check of a068a1d: a hallway across their ends joins the two rooms. Each room keeps its channel, with
    // the hallway: the wall still reads as with one room, the hallway is lit over both rooms and the gap stays dark.
    const hallway = [{ x: -3, z: 2 }, { x: 3, z: 2 }, { x: 3, z: 3 }, { x: -3, z: 3 }];
    const joined = pools.fillMask(field, [first, second, hallway]);
    assert.strictEqual(joined.channels, 2);
    assert.strictEqual(pools.sampleMask(joined, -0.08, 0.3), pools.sampleMask(alone, -0.08, 0.3), 'the wall, rooms joined');
    assert.ok(Math.abs(pools.sampleMask(joined, 0.1, 0.3) - (0.05 - inset)) < 1e-6, 'the second room\'s wall');
    const hallOnly = pools.fillMask(field, [hallway]);
    for (const x of [-1.5, -0.5, 0.5, 1.5]) {
        assert.ok(pools.sampleMask(joined, x, 2.05) > 0, 'the hallway over the rooms at x ' + x);
        assert.ok(pools.sampleMask(joined, x, 2.05) >= pools.sampleMask(hallOnly, x, 2.05), 'no darker than the hallway alone');
    }
    // Over the gap's closed end the footprint has two inner corners; past their cost (about 0.18 m) it is lit.
    assert.ok(pools.sampleMask(joined, 0.01, 2.25) > 0, 'the hallway over the gap');
    assert.ok(pools.sampleMask(joined, 0.01, 1.99) < 0 && pools.sampleMask(joined, 0.01, 0) < 0, 'the gap, up to its closed end');
    for (const [x, z] of [[-1.5, 2], [1.5, 2], [-0.5, 1.99], [0.5, 2.01]]) {
        assert.ok(pools.sampleMask(joined, x, z) > 0.05, 'no dark line on the shared edges at ' + x + ', ' + z);
    }
    // Far apart footprints share a channel; touching ones are one footprint.
    assert.strictEqual(pools.fillMask(field, [first, [{ x: 2, z: -2 }, { x: 2.9, z: -2 }, { x: 2.9, z: 2 }, { x: 2, z: 2 }]]).channels, 1);
    assert.strictEqual(pools.fillMask(field, [first, [{ x: -0.03, z: -2 }, { x: 3, z: -2 }, { x: 3, z: 2 }, { x: -0.03, z: 2 }]]).channels, 1);
    // Six strips 0.1 m wide, 0.05 m apart: more footprints near one another than channels. One shares a channel,
    // still never lit outside; the others keep their own.
    const strips = Array.from({ length: 6 }, (_, k) => [{ x: k * 0.15, z: -2 }, { x: k * 0.15 + 0.1, z: -2 },
        { x: k * 0.15 + 0.1, z: 2 }, { x: k * 0.15, z: 2 }]);
    const crowded = pools.fillMask(field, strips);
    assert.strictEqual(crowded.channels, 4);
    Object.entries({ paired: [paired, [first, second]], joined: [joined, [first, second, hallway]], crowded: [crowded, strips] })
        .forEach(([name, [shapedMask, outlines]]) => {
        let lit = 0;
        for (let x = -2.98; x <= 2.98; x += 0.0071) {
            for (let z = -2.98; z <= 2.98; z += 0.0073) {
                if (!outlines.some(outline => pools.insideOutline(outline, x, z)) && pools.sampleMask(shapedMask, x, z) > 0) lit += 1;
            }
        }
        assert.strictEqual(lit, 0, name + ': no fill outside');
    });
    // A large building: 2,000 lamps under 100 ceiling zones builds in well under a second.
    const zones = [];
    for (let a = 0; a < 10; a += 1) for (let b = 0; b < 10; b += 1) {
        zones.push([{ x: a * 8, z: b * 6 }, { x: a * 8 + 8, z: b * 6 }, { x: a * 8 + 8, z: b * 6 + 6 }, { x: a * 8, z: b * 6 + 6 }]);
    }
    const lamps = Array.from({ length: 2000 }, (_, k) => ({ x: (k * 7.3) % 80, z: (k * 3.1) % 60, radius: 1.5, color: white, lampY: 3.185 }));
    const started = Date.now();
    const hall = pools.fillField(lamps);
    const hallMask = pools.fillMask(hall, zones);
    const took = Date.now() - started;
    assert.ok(took < 1000, '2,000 lamps, 100 zones: ' + took + ' ms');
    assert.ok(pools.sampleMask(hallMask, 40.2, 30.3) > 0 && pools.sampleMask(hallMask, -0.05, 30.3) < 0);
});

test('the fill goes into the indirect light of a lit material (three r184 standard, lambert, phong, toon), not an unlit one', async () => {
    const THREE = await three();
    ['standard', 'physical', 'lambert', 'phong', 'toon'].forEach(name => {
        const shader = { fragmentShader: THREE.ShaderLib[name].fragmentShader, uniforms: {} };
        assert.ok(pools.patchFillShader(shader), name);
        const source = shader.fragmentShader;
        assert.ok(/uniform sampler2D facilityFillMap;/.test(source) && /uniform mat4 facilityFillMatrix;/.test(source)
            && /uniform float facilityFillStrength;/.test(source) && /uniform sampler2D facilityFillMask;/.test(source),
        name + ' declares the fill');
        assert.ok(/facilityAt\.y < facilityFill\.a && facilityCeiling > 0\.0/.test(source), name + ' only under the ceilings');
        const fill = source.indexOf('irradiance += facilityFill.rgb * facilityFillStrength');
        assert.ok(fill > 0 && fill < source.indexOf('#include <lights_fragment_end>'), name + ' before the indirect light is used');
        assert.ok(fill > source.indexOf('#include <lights_fragment_begin>'), name + ' after irradiance is declared');
    });
    assert.ok(/vec3 irradiance = /.test(THREE.ShaderChunk.lights_fragment_begin), 'three declares irradiance there');
    assert.strictEqual(pools.patchFillShader({ fragmentShader: THREE.ShaderLib.basic.fragmentShader }), false, 'unlit');
    assert.strictEqual(pools.patchFillShader(null), false);
});

(async () => {
    let passed = 0;
    for (const entry of tests) {
        try {
            await entry.callback();
            passed += 1;
            console.log('ok - ' + entry.name);
        } catch (error) {
            console.error('not ok - ' + entry.name);
            console.error(error && error.stack ? error.stack : error);
            process.exitCode = 1;
        }
    }
    console.log(passed + '/' + tests.length + ' passed');
})();
