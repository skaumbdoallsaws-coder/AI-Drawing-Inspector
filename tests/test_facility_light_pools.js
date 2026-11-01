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
