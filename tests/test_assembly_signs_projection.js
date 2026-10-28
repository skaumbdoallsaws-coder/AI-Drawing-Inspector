'use strict';

// Signs on assembly parts (docs/assembly-signs-scenes-plan.md, AD2): the Assembly view's ray search for the side
// of a part and the projection onto its surface, run from index.html against three r128 and its DecalGeometry.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const THREE = require('../static/vendor/three/0.128.0/build/three.min.js');
global.THREE = THREE;
require('../static/vendor/three/0.128.0/examples/js/geometries/DecalGeometry.js');

function viewerFunctions() {
    const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
    const start = html.indexOf('        const ASSEMBLY_SIGN_SIDES = Object.freeze({');
    const end = html.indexOf('        async function _assemblySignPlace(signs, row, allMeshes) {');
    assert(start > 0 && end > start, 'the sign functions are in index.html');
    const state = {};
    const factory = new Function('THREE', 'state', html.slice(start, end)
        + '\nreturn { _assemblySignHit, _assemblySignGeometry, _assemblySignSearch, ASSEMBLY_SIGN_SIDES };');
    return factory(THREE, state);
}

const { _assemblySignHit, _assemblySignGeometry, _assemblySignSearch } = viewerFunctions();

function diagonalBar(width) {
    // An arm of a scissor lift: a bar of this width, 1.2 m long, facing the front at 45 degrees.
    const bar = new THREE.Mesh(new THREE.BoxGeometry(width, 1.2, 0.03), new THREE.MeshStandardMaterial());
    bar.rotation.z = Math.PI / 4;
    bar.updateMatrixWorld(true);
    return bar;
}

function onBar(point, across, up, halfWidth) {
    // Whether a point of the sign lies on the diagonal bar: within half its width of the centre line.
    const along = new THREE.Vector3(-Math.SQRT1_2, Math.SQRT1_2, 0);
    const corner = point.clone().add(across).add(up);
    const off = corner.clone().sub(along.multiplyScalar(corner.dot(along)));
    return Math.hypot(off.x, off.y) <= halfWidth + 1e-6;
}

function box(width, height, depth, position, rotationY) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), new THREE.MeshStandardMaterial());
    if (position) mesh.position.set(...position);
    if (rotationY) mesh.rotation.y = rotationY;
    mesh.updateMatrixWorld(true);
    return mesh;
}

function worldPositions(geometry, host) {
    const position = geometry.getAttribute('position');
    const points = [];
    for (let index = 0; index < position.count; index += 1) {
        points.push(new THREE.Vector3().fromBufferAttribute(position, index).applyMatrix4(host.matrixWorld));
    }
    return points;
}

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('a sign on the front lands on the face toward +Z, the size asked, upright', () => {
    const part = box(1, 0.5, 0.2);
    const found = _assemblySignHit([part], [], 'front', 0.5, 0.5);
    assert(found, 'the front face is found');
    assert(Math.abs(found.hit.point.z - 0.1) < 1e-6 && found.normal.z > 0.99);
    const geometry = _assemblySignGeometry(part, found.hit.point, found.normal,
        { widthMeters: 0.3, aspect: 1.15, rotationDegrees: 0 });
    const points = worldPositions(geometry, part);
    assert(points.length >= 6);
    points.forEach(point => assert(Math.abs(point.z - 0.1) < 1e-5, 'only the front face is covered'));
    const xs = points.map(point => point.x);
    const ys = points.map(point => point.y);
    assert(Math.abs(Math.max(...xs) - Math.min(...xs) - 0.3) < 1e-4);
    assert(Math.abs(Math.max(...ys) - Math.min(...ys) - 0.3 / 1.15) < 1e-4);
    // The picture's right is +X and its top +Y for a person in front.
    const uv = geometry.getAttribute('uv');
    const right = points.reduce((best, point, index) => (point.x > points[best].x ? index : best), 0);
    const top = points.reduce((best, point, index) => (point.y > points[best].y ? index : best), 0);
    assert(uv.getX(right) > 0.99 && uv.getY(top) > 0.99);
});

test('the far side of a thin plate never gets a mirrored copy', () => {
    const plate = box(0.6, 0.6, 0.004);
    const found = _assemblySignHit([plate], [], 'front', 0.5, 0.5);
    const geometry = _assemblySignGeometry(plate, found.hit.point, found.normal,
        { widthMeters: 0.3, aspect: 1, rotationDegrees: 0 });
    const normals = geometry.getAttribute('normal');
    for (let index = 0; index < normals.count; index += 1) assert(normals.getZ(index) > 0.99);
});

test('a spot covered by another part moves to one a person can see', () => {
    const part = box(1, 1, 0.2);
    const guard = box(0.3, 0.3, 0.05, [0, 0, 0.3]);
    const found = _assemblySignHit([part], [guard], 'front', 0.5, 0.5);
    assert(found);
    const point = found.hit.point;
    assert(Math.abs(point.x) > 0.15 || Math.abs(point.y) > 0.15, 'it left the guarded centre');
    // With every spot covered, the covered centre is still used.
    const wall = box(3, 3, 0.05, [0, 0, 0.5]);
    const fallback = _assemblySignHit([part], [wall], 'front', 0.5, 0.5);
    assert(fallback && Math.abs(fallback.hit.point.x) < 1e-6 && Math.abs(fallback.hit.point.y) < 1e-6);
});

test('a sign moves off a step or recess to where the surface is flat under all of it', () => {
    const body = box(1, 0.4, 0.3);
    const boss = box(0.2, 0.2, 0.1, [0, 0, 0.2]);
    const centre = _assemblySignHit([body, boss], [], 'front', 0.5, 0.5);
    assert(Math.abs(centre.hit.point.z - 0.25) < 1e-6, 'without a size the spot asked for wins');
    const found = _assemblySignHit([body, boss], [], 'front', 0.5, 0.5, { width: 0.3, height: 0.3 });
    assert(found.flat && found.seen);
    assert(Math.abs(found.hit.point.z - 0.15) < 1e-6 && Math.abs(found.hit.point.x) >= 0.2, 'beside the boss');
    // A sign larger than every flat area still goes on the nearest uncovered spot.
    const large = _assemblySignHit([body, boss], [], 'front', 0.5, 0.5, { width: 2, height: 2 });
    assert(large && !large.flat && Math.abs(large.hit.point.x) < 1e-6);
});

test('a sign on a smooth curved cover fits at its size and wraps uncut', () => {
    const cover = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 0.6, 64), new THREE.MeshStandardMaterial());
    cover.updateMatrixWorld(true);
    const found = _assemblySignHit([cover], [], 'front', 0.5, 0.5, { width: 0.2, height: 0.2 / 1.15 });
    assert(found && found.flat && found.seen, 'a 0.2 m sign fits on a 0.15 m radius cover');
    assert(Math.abs(found.hit.point.x) < 0.02 && found.flat.spread > 0.02, 'centred, and the cover falls away');
    const geometry = _assemblySignGeometry(cover, found.hit.point, found.normal,
        { widthMeters: 0.2, aspect: 1.15, rotationDegrees: 0 }, found.flat);
    const xs = worldPositions(geometry, cover).map(point => point.x);
    assert(Math.max(...xs) - Math.min(...xs) > 0.19, 'the slab reaches the sides of the curve, nothing is cut off');
    // A step as tall as the curve's fall-away still fails: its faces are not tilted.
    const body = box(1, 0.4, 0.3);
    const step = box(0.5, 0.4, 0.03, [0.25, 0, 0.165]);
    const onStep = _assemblySignHit([body, step], [], 'front', 0.5, 0.5, { width: 0.2, height: 0.2 });
    assert(onStep.flat && Math.abs(onStep.hit.point.x) > 0.1, 'it moves fully onto one level');
});

test('a sign never climbs onto a rim in front of its spot, and every corner of it is seen', () => {
    const plate = box(1, 1, 0.3);
    const rim = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 1, 48), new THREE.MeshStandardMaterial());
    rim.position.set(0.12, 0, 0.15);
    rim.updateMatrixWorld(true);
    const found = _assemblySignHit([plate, rim], [], 'front', 0.5, 0.5, { width: 0.3, height: 0.3 });
    assert(found.flat && found.hit.point.x < -0.02, 'it moves off the bulge of the rim');
    // Another part covering the lower half of the sign: the centre is seen, the corners are not.
    const part = box(1, 1, 0.2);
    const gearbox = box(1, 0.4, 0.05, [0, -0.3, 0.3]);
    const clear = _assemblySignHit([part], [gearbox], 'front', 0.5, 0.5, { width: 0.3, height: 0.3 });
    assert(clear.seen && clear.hit.point.y > 0.03, 'it moves up until the whole sign is in view');
    // The part's own lip in front of a plate turned away from the person hides a corner the same way.
    // The plate faces left of the person; rays along its normal pass beside the lip, the person's do not.
    const turned = box(1, 1, 0.1, null, -Math.PI / 6);
    const lip = box(0.1, 1, 0.23, [0.15, 0, 0.285]);
    const own = _assemblySignHit([turned, lip], [], 'front', 0.5, 0.5, { width: 0.3, height: 0.3 });
    const reach = 0.135 * Math.cos(Math.PI / 6);
    assert(own.seen && (own.hit.point.x + reach < 0.1 || own.hit.point.x - reach > 0.2), 'it keeps clear of its own lip');
});

test('a sign is not bent over a chamfer: a fold is not a curve', () => {
    const front = new THREE.Mesh(new THREE.PlaneGeometry(0.55, 1), new THREE.MeshStandardMaterial());
    front.position.set(-0.225, 0, 0.15);
    const chamfer = new THREE.Mesh(new THREE.PlaneGeometry(0.15 * Math.SQRT2, 1), new THREE.MeshStandardMaterial());
    chamfer.position.set(0.125, 0, 0.075);
    chamfer.rotation.y = Math.PI / 4;
    [front, chamfer].forEach(mesh => mesh.updateMatrixWorld(true));
    // Asked for right at the fold (x = 0); the sign moves onto the front face, clear of the fold at x = 0.05.
    const found = _assemblySignHit([front, chamfer], [], 'front', 0.5 / 0.7, 0.5, { width: 0.3, height: 0.3 });
    assert(found.flat && found.hit.point.x + 0.135 < 0.05, 'the whole sign is on the front face');
});

test('a rib narrower than the coarse rays still keeps a sign off it', () => {
    // A 1 cm rib, 4 cm proud (more than the 2.6 cm a 0.3 m sign may lie off its plane), between the coarse rays at
    // x = 0 and x = 0.0675.
    const plate = box(1, 1, 0.1);
    const rib = box(0.01, 1, 0.04, [0.035, 0, 0.07]);
    const found = _assemblySignHit([plate, rib], [], 'front', 0.5, 0.5, { width: 0.3, height: 0.3 });
    assert(found.flat, 'a spot clear of the rib is found');
    const reach = 0.135;
    assert(found.hit.point.x + reach < 0.03 || found.hit.point.x - reach > 0.04, 'the whole sign is off the rib');
});

test('a fitted sign stays on its own surface: no copy on a wall seen through a slot', () => {
    // One mesh: a front plate split by a 2 cm slot, and a wall 3 cm behind it.
    const pieces = [box(0.49, 1, 0.01, [-0.255, 0, 0]), box(0.49, 1, 0.01, [0.255, 0, 0]),
        box(1, 1, 0.01, [0, 0, -0.03])];
    const arrays = { position: [], normal: [], uv: [] };
    pieces.forEach(piece => {
        const flat = piece.geometry.toNonIndexed().applyMatrix4(piece.matrixWorld);
        ['position', 'normal', 'uv'].forEach(name => arrays[name].push(...flat.getAttribute(name).array));
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(arrays.position, 3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(arrays.normal, 3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(arrays.uv, 2));
    const host = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial());
    host.updateMatrixWorld(true);
    // A slab deep enough for a curve reaches the wall behind; only the front face may take the sign.
    const sign = _assemblySignGeometry(host, new THREE.Vector3(0.1, 0, 0.005), new THREE.Vector3(0, 0, 1),
        { widthMeters: 0.3, aspect: 1 }, { spread: 0.03 });
    const points = worldPositions(sign, host);
    assert(points.length >= 6);
    points.forEach(point => assert(Math.abs(point.z - 0.005) < 1e-5, 'on the front plate only'));
});

test('on a narrow diagonal bar a sign is drawn small enough to lie whole on it, upright', () => {
    // The MMLE-50D's scissor arms (6.5 cm bars at 45 degrees): a 0.3 m sign was drawn half off one.
    const found = _assemblySignSearch([diagonalBar(0.065)], [], { side: 'front', aspect: 1.143 }, 0.3);
    assert(found && found.fits, 'a size that fits is found');
    assert(found.width >= 0.03 && found.width < 0.075, `drawn ${found.width} m wide`);  // 7.5 cm hangs over
    const height = found.width / 1.143;
    for (const [da, du] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
        assert(onBar(found.hit.point, new THREE.Vector3(da * found.width * 0.45, 0, 0),
            new THREE.Vector3(0, du * height * 0.45, 0), 0.0325), 'every corner is on the bar');
    }
});

test('a turned sign is fitted turned: along a diagonal bar it may be larger', () => {
    const upright = _assemblySignSearch([diagonalBar(0.065)], [], { side: 'front', aspect: 1 }, 0.3);
    const along = _assemblySignSearch([diagonalBar(0.065)], [], { side: 'front', aspect: 1, rotationDegrees: 45 },
        0.3);
    assert(upright.fits && along.fits && along.width > upright.width, `${upright.width} upright, ${along.width} turned`);
    const r = Math.SQRT1_2 * along.width * 0.45;
    for (const [da, du] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
        assert(onBar(along.hit.point, new THREE.Vector3(da * r, da * r, 0), new THREE.Vector3(-du * r, du * r, 0),
            0.0325), 'every corner of the turned sign is on the bar');
    }
});

test('a spot on a bar little wider than the sign moves to its middle, where the sign lies whole', () => {
    // A frame of two 5 cm uprights: the search's spots land a few cm off their centre lines, where a 4 cm sign
    // hangs over an edge; the centred spot fits.
    const upright = x => {
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.05, 1, 0.03), new THREE.MeshStandardMaterial());
        mesh.position.x = x;
        mesh.updateMatrixWorld(true);
        return mesh;
    };
    const found = _assemblySignSearch([upright(-0.45), upright(0.2)], [], { side: 'front', aspect: 1 }, 0.04);
    assert(found.fits && found.width === 0.04, 'it fits at the size asked');
    assert(Math.abs(found.hit.point.x - 0.2) < 0.001 || Math.abs(found.hit.point.x + 0.45) < 0.001, 'centred');
});

test('where no size down to 3 cm lies whole on the part the sign is not drawn', () => {
    // A 1 cm rod: too thin for any size; the view reports no_fit instead of drawing a sign cut by its edges.
    assert.deepStrictEqual(_assemblySignSearch([diagonalBar(0.01)], [], { side: 'front', aspect: 1.143 }, 0.3),
        { fits: false });
});

test('sides and spots follow the view axes, and a top sign reads from the front', () => {
    const part = box(1, 0.5, 0.4);
    const right = _assemblySignHit([part], [], 'right', 0.5, 0.5);
    assert(Math.abs(right.hit.point.x - 0.5) < 1e-6 && right.normal.x > 0.99);
    // Across runs left to right as a person facing the right side sees it: toward -Z.
    const near = _assemblySignHit([part], [], 'right', 0.9, 0.5);
    assert(near.hit.point.z < -0.1);
    const top = _assemblySignHit([part], [], 'top', 0.5, 0.5);
    assert(Math.abs(top.hit.point.y - 0.25) < 1e-6);
    const geometry = _assemblySignGeometry(part, top.hit.point, top.normal, { widthMeters: 0.2, aspect: 1 });
    const points = worldPositions(geometry, part);
    const uv = geometry.getAttribute('uv');
    const back = points.reduce((best, point, index) => (point.z < points[best].z ? index : best), 0);
    assert(uv.getY(back) > 0.99, 'the top of the sign points away from a person at the front');
    assert(_assemblySignHit([part], [], 'bottom', 0.5, 0.5).hit.point.y < -0.24);
});

test('a sign is kept in its part\'s own coordinates and a turned sign turns', () => {
    const part = box(0.8, 0.4, 0.3, [2, 1, -1], Math.PI / 6);
    const found = _assemblySignHit([part], [], 'front', 0.5, 0.5);
    assert(found && found.normal.z > 0.35);
    const geometry = _assemblySignGeometry(part, found.hit.point, found.normal, { widthMeters: 0.2, aspect: 2 });
    const local = geometry.getAttribute('position');
    for (let index = 0; index < local.count; index += 1) {
        assert(Math.abs(local.getZ(index) - 0.15) < 1e-5, 'on the part\'s own front face');
    }
    const turned = _assemblySignGeometry(box(1, 1, 0.2), new THREE.Vector3(0, 0, 0.1), new THREE.Vector3(0, 0, 1),
        { widthMeters: 0.4, aspect: 2, rotationDegrees: 90 });
    const ys = worldPositions(turned, box(1, 1, 0.2)).map(point => point.y);
    assert(Math.abs(Math.max(...ys) - Math.min(...ys) - 0.4) < 1e-4, 'turned a quarter, its width runs up');
});

test('a part with no surface toward the side, or a model without normals, is handled', () => {
    const flat = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshStandardMaterial());
    flat.rotation.x = -Math.PI / 2;
    flat.updateMatrixWorld(true);
    assert.strictEqual(_assemblySignHit([flat], [], 'front', 0.5, 0.5), null, 'a floor plate has no front');
    const bare = box(1, 1, 0.2);
    bare.geometry = bare.geometry.toNonIndexed();
    bare.geometry.deleteAttribute('normal');
    bare.updateMatrixWorld(true);
    const found = _assemblySignHit([bare], [], 'front', 0.5, 0.5);
    const geometry = _assemblySignGeometry(bare, found.hit.point, found.normal, { widthMeters: 0.2, aspect: 1 });
    assert(geometry && geometry.getAttribute('position').count >= 6);
    assert(!bare.geometry.getAttribute('normal'), 'the model itself is left as it was');
});

let failed = 0;
tests.forEach(([name, fn]) => {
    try {
        fn();
        console.log('ok - ' + name);
    } catch (error) {
        failed += 1;
        console.log('not ok - ' + name);
        console.log(error && error.stack || error);
    }
});
console.log(`${tests.length - failed}/${tests.length} passed`);
if (failed) process.exitCode = 1;
