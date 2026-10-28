'use strict';

// Faces of parts in the Assembly view (docs/assembly-face-selection-plan.md, F1-F3): which face a triangle is on
// (the exporter's CAD faces, or smooth patches), robust to a BVH reordering the index; finding a face again by its
// fingerprint; finished faces drawn as groups; and a sign kept inside one face. Run from index.html against three
// r128, its DecalGeometry and the vendored three-mesh-bvh.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const THREE = require('../static/vendor/three/0.128.0/build/three.min.js');
global.THREE = THREE;
require('../static/vendor/three/0.128.0/examples/js/geometries/DecalGeometry.js');

function bvhLibrary() {
    const source = fs.readFileSync(path.join(ROOT, 'static/vendor/three-mesh-bvh/0.5.23/three-mesh-bvh.umd.js'), 'utf8');
    const exports = {};
    new Function('exports', 'module', 'require', source)(exports, { exports }, () => THREE);
    return exports;
}

function viewerFunctions() {
    const html = fs.readFileSync(path.join(ROOT, 'static/index.html'), 'utf8');
    const cut = (from, to) => {
        const start = html.indexOf(from);
        const end = html.indexOf(to, start);
        assert(start > 0 && end > start, `index.html has ${from.trim()}`);
        return html.slice(start, end);
    };
    const faces = cut('        // ===== Faces of parts (docs/assembly-face-selection-plan.md) =====',
        '        // ===== Assembly scenes and signs (docs/assembly-signs-scenes-plan.md) =====');
    const signs = cut('        const ASSEMBLY_SIGN_SIDES = Object.freeze({',
        '        async function _assemblySignPlace(signs, row, allMeshes) {');
    const state = {};
    return new Function('THREE', 'state', faces + signs + '\nreturn { _assemblyFaceTable, _assemblyFaceFingerprint, '
        + '_assemblyFaceResolve, _assemblyFaceOnCopy, _assemblyFaceSide, _assemblyFaceSubsetGeometry, '
        + '_assemblyFaceDisposeShared, _assemblyFaceRegroup, _assemblySignOnFace, _assemblySignGeometry };')(THREE, state);
}

const face = viewerFunctions();
const BVH = bvhLibrary();

// A box as our exporter writes a part: each triangle its own three vertices in order, and the CAD faces as runs.
// three's box order: +X, -X, +Y, -Y, +Z, -Z, two triangles each.
function exportedBox(width, height, depth, order = [0, 1, 2, 3, 4, 5]) {
    const box = new THREE.BoxGeometry(width, height, depth).toNonIndexed();
    const position = box.getAttribute('position');
    const normal = box.getAttribute('normal');
    const positions = [];
    const normals = [];
    order.forEach(side => {
        for (let vertex = side * 6; vertex < side * 6 + 6; vertex += 1) {
            positions.push(position.getX(vertex), position.getY(vertex), position.getZ(vertex));
            normals.push(normal.getX(vertex), normal.getY(vertex), normal.getZ(vertex));
        }
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
    geometry.setIndex(new THREE.BufferAttribute(Uint32Array.from({ length: 36 }, (_, at) => at), 1));
    geometry.userData.cadFaces = { faceVersion: 1, faceKinds: ['plane'], faceFeatures: ['Boss-Extrude1'],
        faces: order.map((_, at) => [at * 2, 2, 0, 0, 0]) };
    return geometry;
}

function rayAt(mesh, origin, direction) {
    const raycaster = new THREE.Raycaster(new THREE.Vector3(...origin), new THREE.Vector3(...direction).normalize());
    return raycaster.intersectObject(mesh, false)[0];
}

const close = (a, b, tolerance = 1e-6) => Math.abs(a - b) <= tolerance;

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('a GLB\'s CAD faces: each triangle knows its face, also after a BVH reorders the index', () => {
    const geometry = exportedBox(1, 0.5, 0.2);
    const table = face._assemblyFaceTable(geometry);
    assert(table.exact && table.count === 6 && table.faces[4].feature === 'Boss-Extrude1');
    const front = table.info(4);
    assert(close(front.area, 0.5) && close(front.center.z, 0.1) && close(front.normal.z, 1));
    assert.strictEqual(face._assemblyFaceSide(front.normal), 'front');
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
    mesh.updateMatrixWorld(true);
    assert.strictEqual(table.faceOfHit(rayAt(mesh, [0.2, 0.1, 1], [0, 0, -1])), 4);
    assert.strictEqual(table.faceOfHit(rayAt(mesh, [0.1, 1, 0], [0, -1, 0])), 2, 'the top');
    BVH.computeBoundsTree.call(geometry, { maxLeafTris: 1 });
    const order = Array.from(geometry.index.array);
    assert(order.some((value, at) => value !== at), 'the BVH reordered the index');
    mesh.raycast = BVH.acceleratedRaycast;
    assert.strictEqual(table.faceOfHit(rayAt(mesh, [0.2, 0.1, 1], [0, 0, -1])), 4);
    assert.strictEqual(table.faceOfHit(rayAt(mesh, [-1, 0.1, 0.05], [1, 0, 0])), 1, 'the left');
    delete geometry.userData._assemblyFaceTable;
    const again = face._assemblyFaceTable(geometry);
    assert(again.exact && again.count === 6 && close(again.info(4).area, 0.5), 'worked out again on the new order');
});

test('a face is found again by its fingerprint when a new export numbers it differently, never swapped', () => {
    const first = exportedBox(1, 0.5, 0.2);
    const print = face._assemblyFaceFingerprint(face._assemblyFaceTable(first).info(4));
    const renumbered = exportedBox(1, 0.5, 0.2, [5, 4, 3, 2, 1, 0]);
    const table = face._assemblyFaceTable(renumbered);
    assert.strictEqual(face._assemblyFaceResolve(renumbered, table, { face: 4, fingerprint: print }), 1);
    assert.strictEqual(face._assemblyFaceResolve(first, face._assemblyFaceTable(first), { face: 4, fingerprint: print }), 4);
    const changed = exportedBox(1, 0.5, 0.35);
    assert.strictEqual(face._assemblyFaceResolve(changed, face._assemblyFaceTable(changed), { face: 4, fingerprint: print }),
        -1, 'a moved face is missing, not replaced by the nearest');
    const copy = exportedBox(1, 0.5, 0.2);
    assert.strictEqual(face._assemblyFaceOnCopy(face._assemblyFaceTable(copy), 4, face._assemblyFaceTable(first).info(4)), 4);
    assert.strictEqual(face._assemblyFaceOnCopy(face._assemblyFaceTable(copy), 0, face._assemblyFaceTable(first).info(4)), -1,
        'a face of another size is not the same face on a copy');
});

test('models without CAD faces get smooth patches: a box has six, a cylinder three, sharper turns split', () => {
    const shared = face._assemblyFaceTable(new THREE.BoxGeometry(1, 0.5, 0.2));
    assert(!shared.exact && shared.count === 6 && shared.faces.every(row => row.approximate));
    const loose = exportedBox(1, 0.5, 0.2);
    delete loose.userData.cadFaces;
    assert.strictEqual(face._assemblyFaceTable(loose).count, 6, 'own vertices per triangle are welded first');
    const cylinder = face._assemblyFaceTable(new THREE.CylinderGeometry(0.1, 0.1, 0.5, 32));
    assert.strictEqual(cylinder.count, 3, 'the side turns 11 degrees a step and stays one face');
    const octagon = face._assemblyFaceTable(new THREE.CylinderGeometry(0.1, 0.1, 0.5, 8));
    assert.strictEqual(octagon.count, 10, '45 degree steps make eight sides and two ends');
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.5, 32), new THREE.MeshBasicMaterial());
    mesh.updateMatrixWorld(true);
    const table = face._assemblyFaceTable(mesh.geometry);
    const side = table.faceOfHit(rayAt(mesh, [0, 0, 1], [0, 0, -1]));
    const top = table.faceOfHit(rayAt(mesh, [0.02, 1, 0], [0, -1, 0]));
    assert(side >= 0 && top >= 0 && side !== top);
    assert(table.info(side).normal.length() < 0.2, 'a face curving all round has no one direction');
    assert.strictEqual(face._assemblyFaceSide(table.info(side).normal), null);
});

test('finished faces become groups after the rest; the vertices are shared and an old BVH is dropped', () => {
    const geometry = exportedBox(1, 0.5, 0.2);
    const table = face._assemblyFaceTable(geometry);
    const own = face._assemblyFaceSubsetGeometry(geometry, table, [0, 1, 2, 3, 4, 5]);
    assert(own.attributes.position === geometry.attributes.position && own.index.count === 36);
    BVH.computeBoundsTree.call(own, { maxLeafTris: 1 });
    const groups = face._assemblyFaceRegroup(own, table, [4, 1]);
    assert.deepStrictEqual(groups.map(group => [group.start, group.count, group.materialIndex]),
        [[0, 24, 0], [24, 6, 1], [30, 6, 2]]);
    const faceAt = start => table.faceOf[Math.floor(own.index.getX(start) / 3)];
    for (let at = 24; at < 30; at += 3) assert.strictEqual(faceAt(at), 4);
    for (let at = 30; at < 36; at += 3) assert.strictEqual(faceAt(at), 1);
    assert.strictEqual(own.boundsTree, undefined, 'the BVH built on the old order is dropped');
    assert.strictEqual(face._assemblyFaceTable(own), table, 'the faces are the same faces');
    const mesh = new THREE.Mesh(own, [new THREE.MeshBasicMaterial(), new THREE.MeshBasicMaterial(),
        new THREE.MeshBasicMaterial()]);
    mesh.updateMatrixWorld(true);
    const hit = rayAt(mesh, [0.2, 0.1, 1], [0, 0, -1]);
    assert(hit.face.materialIndex === 1 && table.faceOfHit(hit) === 4, 'the front draws with its own material');
    BVH.computeBoundsTree.call(own, { maxLeafTris: 1 });
    mesh.raycast = BVH.acceleratedRaycast;
    assert.strictEqual(table.faceOfHit(rayAt(mesh, [0.2, 0.1, 1], [0, 0, -1])), 4, 'a new BVH keeps the groups');
    const tint = face._assemblyFaceSubsetGeometry(geometry, table, [2]);
    assert.strictEqual(tint.index.count, 6);
    face._assemblyFaceDisposeShared(tint);
    assert(geometry.attributes.position && geometry.attributes.position.count === 36, 'the part keeps its vertices');
});

test('a sign on a chosen face stays inside it, even where the part\'s other face is larger', () => {
    // A bar of a scissor arm, at 45 degrees: a large front face (0.2 m) and a narrow side face (8 cm).
    const bar = new THREE.Mesh(new THREE.BoxGeometry(0.2, 1.2, 0.08), new THREE.MeshStandardMaterial());
    bar.rotation.z = Math.PI / 4;
    bar.updateMatrixWorld(true);
    const table = face._assemblyFaceTable(bar.geometry);
    const numbered = direction => Array.from({ length: table.count }, (_, k) => k)
        .find(k => table.info(k).normal.dot(new THREE.Vector3(...direction)) > 0.99);
    const side = numbered([1, 0, 0]);
    const front = numbered([0, 0, 1]);
    assert(side !== undefined && front !== undefined && table.info(front).area > table.info(side).area);
    const row = { aspect: 1, rotationDegrees: 0 };
    const found = face._assemblySignOnFace([bar], [], bar, table, side, row, 0.3);
    assert(found.fits && found.width < 0.08, `the sign shrinks to fit the narrow face (${found.width})`);
    const outward = new THREE.Vector3(1, 0, 0).transformDirection(bar.matrixWorld);
    assert(found.normal.dot(outward) > 0.99, 'it faces the way the chosen face does');
    const local = bar.worldToLocal(found.point.clone());
    assert(close(local.x, 0.1, 1e-5) && Math.abs(local.z) + found.width * 0.45 <= 0.04 + 1e-6, 'inside the face');
    const onFront = face._assemblySignOnFace([bar], [], bar, table, front, row, 0.3);
    assert(onFront.fits && onFront.normal.z > 0.99 && onFront.width > found.width, 'the front takes a bigger sign');
    const tiny = face._assemblySignOnFace([bar], [], bar, table, numbered([0, 1, 0]), row, 0.3);
    assert(tiny.fits === true && tiny.width <= 0.08, 'the end of the bar takes a small one');
    const geometry = face._assemblySignGeometry(bar, found.point, found.normal,
        { widthMeters: found.width, aspect: 1, rotationDegrees: 0 }, found.flat);
    assert(geometry && geometry.getAttribute('position').count >= 6, 'the sign is drawn there');
});

test('a sign finds no room on a face smaller than 3 cm all round, and does not move to a bigger one', () => {
    const plate = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.02), new THREE.MeshStandardMaterial());
    plate.updateMatrixWorld(true);
    const table = face._assemblyFaceTable(plate.geometry);
    const edge = Array.from({ length: table.count }, (_, k) => k)
        .find(k => table.info(k).normal.x > 0.99);
    assert.deepStrictEqual(face._assemblySignOnFace([plate], [], plate, table, edge, { aspect: 1 }, 0.3), { fits: false });
});

(async () => {
    let failed = 0;
    for (const [name, fn] of tests) {
        try {
            await fn();
            console.log('ok - ' + name);
        } catch (error) {
            failed += 1;
            console.log('not ok - ' + name);
            console.log(error && error.stack || error);
        }
    }
    console.log(`${tests.length - failed}/${tests.length} passed`);
    if (failed) process.exitCode = 1;
})();
