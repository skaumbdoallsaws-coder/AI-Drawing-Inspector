'use strict';

// Model files are mirrored once across their canonical x = 0 plane on their way
// into a layout (ai_inspector/facility_layout/model_axes.py). Checked here with
// the real vendored three.js, since the adapter tests run on a stub.
const assert = require('assert');
const path = require('path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');

const ROOT = path.resolve(__dirname, '..');
const { mirrorModelFileGeometry } = require(path.join(ROOT, 'static', 'facility_layout_three_adapter.js'));

async function loadThree() {
    return import(pathToFileURL(path.join(
        ROOT, 'static', 'vendor', 'three', '0.184.0', 'build', 'three.module.min.js')).href);
}

function triangle(THREE) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute([0.2, 0, 0, 1, 0, 0.1, 0.4, 0.8, 0.3], 3));
    geometry.setIndex([0, 1, 2]);
    geometry.computeVertexNormals();
    return geometry;
}

// Corner positions in the wrapper's frame, in index order.
function corners(THREE, wrapper, mesh) {
    wrapper.updateMatrixWorld(true);
    const toWrapper = new THREE.Matrix4().copy(wrapper.matrixWorld).invert();
    const local = new THREE.Matrix4().multiplyMatrices(toWrapper, mesh.matrixWorld);
    const position = mesh.geometry.attributes.position;
    const order = mesh.geometry.index ? Array.from(mesh.geometry.index.array) : [0, 1, 2];
    return order.map(index => new THREE.Vector3().fromBufferAttribute(position, index).applyMatrix4(local));
}

function faceNormal(THREE, points) {
    return new THREE.Vector3().subVectors(points[1], points[0])
        .cross(new THREE.Vector3().subVectors(points[2], points[0])).normalize();
}

function close(left, right) {
    assert.ok(left.distanceTo(right) < 1e-5, `${left.toArray()} != ${right.toArray()}`);
}

test('a nested part is mirrored across the wrapper x = 0 plane and stays outward-facing', async () => {
    const THREE = await loadThree();
    const wrapper = new THREE.Group();
    const part = new THREE.Group();
    part.position.set(1.5, 0.2, -0.7);
    part.rotation.set(0.3, 0.9, -0.2);
    const mesh = new THREE.Mesh(triangle(THREE), new THREE.MeshBasicMaterial());
    part.add(mesh);
    wrapper.add(part);
    const before = corners(THREE, wrapper, mesh);
    const normalBefore = faceNormal(THREE, before);
    const original = mesh.geometry;
    mirrorModelFileGeometry(THREE, wrapper);
    assert.notStrictEqual(mesh.geometry, original, 'the geometry is cloned before it is mirrored');
    const after = corners(THREE, wrapper, mesh);
    // Winding is reversed, so corner 1 and 2 trade places.
    [0, 2, 1].forEach((source, index) => close(after[index], before[source].clone().setX(-before[source].x)));
    close(faceNormal(THREE, after), normalBefore.clone().setX(-normalBefore.x));
    // The stored vertex normal agrees with the visible face.
    const normalMatrix = new THREE.Matrix3().getNormalMatrix(
        new THREE.Matrix4().copy(wrapper.matrixWorld).invert().multiply(mesh.matrixWorld));
    const stored = new THREE.Vector3().fromBufferAttribute(mesh.geometry.attributes.normal, 0)
        .applyMatrix3(normalMatrix).normalize();
    assert.ok(stored.dot(faceNormal(THREE, after)) > 0.999);
    // The mesh transform stays proper, so instancing and raycasting keep working.
    assert.ok(mesh.matrixWorld.determinant() > 0);
});

test('a geometry shared by two parts is mirrored once per part and the original is untouched', async () => {
    const THREE = await loadThree();
    const wrapper = new THREE.Group();
    const shared = triangle(THREE);
    const originalPositions = Array.from(shared.attributes.position.array);
    const left = new THREE.Mesh(shared, new THREE.MeshBasicMaterial());
    const right = new THREE.Mesh(shared, new THREE.MeshBasicMaterial());
    left.position.set(-2, 0, 0);
    right.position.set(3, 0, 1);
    right.rotation.y = 1.1;
    wrapper.add(left, right);
    const beforeLeft = corners(THREE, wrapper, left);
    const beforeRight = corners(THREE, wrapper, right);
    mirrorModelFileGeometry(THREE, wrapper);
    assert.deepStrictEqual(Array.from(shared.attributes.position.array), originalPositions);
    assert.notStrictEqual(left.geometry, right.geometry);
    const afterLeft = corners(THREE, wrapper, left);
    const afterRight = corners(THREE, wrapper, right);
    [0, 2, 1].forEach((source, index) => {
        close(afterLeft[index], beforeLeft[source].clone().setX(-beforeLeft[source].x));
        close(afterRight[index], beforeRight[source].clone().setX(-beforeRight[source].x));
    });
});

test('non-indexed interleaved geometry is mirrored with its corners swapped', async () => {
    const THREE = await loadThree();
    const data = new THREE.InterleavedBuffer(new Float32Array([
        0.2, 0, 0, 0, 0,
        1, 0, 0.1, 1, 0,
        0.4, 0.8, 0.3, 0.5, 1,
    ]), 5);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.InterleavedBufferAttribute(data, 3, 0));
    geometry.setAttribute('uv', new THREE.InterleavedBufferAttribute(data, 2, 3));
    const wrapper = new THREE.Group();
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
    wrapper.add(mesh);
    mirrorModelFileGeometry(THREE, wrapper);
    const position = mesh.geometry.attributes.position;
    const uv = mesh.geometry.attributes.uv;
    const point = index => new THREE.Vector3().fromBufferAttribute(position, index);
    close(point(0), new THREE.Vector3(-0.2, 0, 0));
    close(point(1), new THREE.Vector3(-0.4, 0.8, 0.3));
    close(point(2), new THREE.Vector3(-1, 0, 0.1));
    assert.deepStrictEqual([uv.getX(1), uv.getY(1), uv.getX(2), uv.getY(2)], [0.5, 1, 1, 0]);
});
