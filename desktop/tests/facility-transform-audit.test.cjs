'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createRealThreeHarness, getPinnedThree } = require('./helpers/facility-three-harness.cjs');

const REVISION = 'a'.repeat(64);
const asset = { assetId: 'matrix-prototype', publishedAssetDefinitionRevision: REVISION,
  definition: { geometry: { aabb: { minimum: { x: -1, y: 0, z: -1 }, maximum: { x: 1, y: 2, z: 1 } } } } };

async function fixture(t, { compound = false, meshes = 1 } = {}) {
  const THREE = await getPinnedThree();
  const prototype = new THREE.Group();
  prototype.position.set(...(compound ? [0.1234567, 0.85, -0.52] : [0, 0, 0]));
  if (compound) {
    prototype.rotation.set(0.17, -0.34, 0.21);
    prototype.scale.set(1.13, 0.87, 1.04);
  }
  for (let index = 0; index < meshes; index++) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 2, 1), new THREE.MeshStandardMaterial());
    if (compound || index) {
      mesh.position.set(index + 0.321098, 0.015, -0.2187);
      mesh.rotation.set(0.04, 0.11, -0.02);
    }
    prototype.add(mesh);
  }
  const canonical = new THREE.Matrix4().compose(new THREE.Vector3(0, 0.42, -0.83),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(-0.08, 0.13, 0.02)),
    new THREE.Vector3(0.96, 0.96, 0.96));
  const quaternion = compound
    ? new THREE.Quaternion().setFromEuler(new THREE.Euler(0.23, 0.71, -0.12))
    : new THREE.Quaternion();
  const placements = (compound ? [263.506, 281.371] : [264, 280]).map((x, index) => ({
    placementId: 'placement-' + index, assetId: asset.assetId, assetDefinitionRevision: REVISION,
    transform: { position: { x, y: compound ? 0.031 : 0, z: compound ? -116.726 : 0 },
      quaternion: { x: quaternion.x, y: quaternion.y, z: quaternion.z, w: quaternion.w },
      scale: compound ? 1.17 : 1 },
  }));
  const harness = await createRealThreeHarness({ assetResolver(request) {
    if (request.stage === 'manifest') return asset;
    if (request.stage === 'detail') return { object: prototype,
      ...(compound ? { sourceToCanonical: canonical.elements.slice() } : {}) };
    return null;
  } });
  t.after(() => harness.dispose());
  await harness.adapter.setScene({ layout: { placements }, assetCatalog: [asset] });
  harness.flush();
  assert.deepEqual(harness.errors, [], 'adapter must construct the real scene successfully');
  const instances = [];
  harness.renderer.lastRender.scene.traverse(object => { if (object.isInstancedMesh) instances.push(object); });
  assert.equal(instances.length, meshes);
  assert(instances.every(mesh => mesh.instanceMatrix.array instanceof Float32Array));
  prototype.updateMatrixWorld(true);
  const prototypeMatrices = [];
  prototype.traverse(object => { if (object.isMesh) prototypeMatrices.push(object.matrixWorld.clone()); });
  function expectedMatrix(meshIndex, placementIndex) {
    const transform = placements[placementIndex].transform;
    return new THREE.Matrix4().compose(
      new THREE.Vector3(transform.position.x, transform.position.y, transform.position.z),
      new THREE.Quaternion(transform.quaternion.x, transform.quaternion.y, transform.quaternion.z, transform.quaternion.w),
      new THREE.Vector3(transform.scale, transform.scale, transform.scale)
    ).multiply(prototypeMatrices[meshIndex]);
  }
  return { ...harness, placements, instances, expectedMatrix };
}

function assertMismatch(fixture, id = 'placement-0') {
  const audit = fixture.adapter.getPlacementTransformAudit();
  assert.equal(audit.status, 'mismatch');
  assert(audit.transformMismatchIdsAll.includes(id), JSON.stringify(audit));
}

function assertBaseline(fixture) {
  const audit = fixture.adapter.getPlacementTransformAudit();
  assert.equal(audit.status, 'match', 'negative case must start from a matching audit: ' + JSON.stringify(audit));
}

test('real Three instance matrices preserve compound prototype transforms at facility coordinates', async t => {
  const value = await fixture(t, { compound: true, meshes: 2 });
  let largestRounding = 0;
  value.instances.forEach((mesh, meshIndex) => {
    value.placements.forEach((placement, placementIndex) => {
      const actual = new value.THREE.Matrix4();
      mesh.getMatrixAt(placementIndex, actual);
      const expected = value.expectedMatrix(meshIndex, placementIndex).elements;
      assert.deepEqual(actual.elements, expected.map(Math.fround), 'all 16 elements must equal actual Float32 storage');
      expected.forEach((number, index) => { largestRounding = Math.max(largestRounding, Math.abs(number - actual.elements[index])); });
    });
  });
  assert(largestRounding > 1e-5, 'fixture must exercise the original absolute-tolerance failure');
  const audit = value.adapter.getPlacementTransformAudit();
  assert.equal(audit.status, 'match', JSON.stringify({ largestRounding, audit }));
  assert.equal(audit.auditedPlacementCount, 2);
  assert.equal(audit.matrixComparison.tolerance, 1e-5);
  assert.equal(audit.matrixComparison.auditedMatrixCount, 4);
  assert.equal(audit.matrixComparison.maxStoredAbsoluteDelta, 0);
  assert(audit.matrixComparison.maxRawAbsoluteDelta > 1e-5);
  assert(audit.matrixComparison.samples.length > 0);
  for (const sample of audit.matrixComparison.samples) {
    assert.equal(sample.storage, 'Float32Array');
    assert.deepEqual(sample.expectedStored, sample.expectedDouble.map(Math.fround));
    assert.deepEqual(sample.actual, sample.expectedStored);
    assert(sample.rawDelta.some(delta => Math.abs(delta) > 1e-5));
    assert(sample.storedDelta.every(delta => delta === 0));
  }
});

test('real Float32 translation offset of one millimeter is rejected', async t => {
  const value = await fixture(t);
  assertBaseline(value);
  value.instances[0].instanceMatrix.array[12] += 0.001;
  assertMismatch(value);
});

test('one representable Float32 translation step is rejected rather than hidden by relative tolerance', async t => {
  const value = await fixture(t);
  assertBaseline(value);
  const array = value.instances[0].instanceMatrix.array;
  const bits = new Uint32Array(array.buffer, array.byteOffset, array.length);
  const before = array[12];
  bits[12] += 1;
  assert(array[12] - before > 1e-5);
  assertMismatch(value);
});

test('wrong real instance rotation is rejected', async t => {
  const value = await fixture(t);
  assertBaseline(value);
  const matrix = value.expectedMatrix(0, 0).multiply(new value.THREE.Matrix4().makeRotationY(0.01));
  value.instances[0].setMatrixAt(0, matrix);
  assertMismatch(value);
});

test('wrong real instance scale is rejected', async t => {
  const value = await fixture(t);
  assertBaseline(value);
  const matrix = value.expectedMatrix(0, 0).multiply(new value.THREE.Matrix4().makeScale(1.01, 1, 1));
  value.instances[0].setMatrixAt(0, matrix);
  assertMismatch(value);
});

test('an offset in a nonfirst prototype mesh is included in the placement audit', async t => {
  const value = await fixture(t, { meshes: 2 });
  assertBaseline(value);
  value.instances[1].instanceMatrix.array[12] += 0.001;
  assertMismatch(value);
});

test('a nonfinite real instance element cannot masquerade as an expected zero', async t => {
  const value = await fixture(t);
  assertBaseline(value);
  assert.equal(value.expectedMatrix(0, 0).elements[1], 0);
  value.instances[0].instanceMatrix.array[1] = NaN;
  assertMismatch(value);
  const sample = value.adapter.getPlacementTransformAudit().matrixComparison.samples[0];
  assert.deepEqual(sample.nonFiniteElements, [1]);
  assert.equal(sample.actual[1], 'NaN', 'JSON evidence must retain the invalid value explicitly');
});

test('an unreadable secondary mesh cannot produce complete placement coverage', async t => {
  const value = await fixture(t, { meshes: 2 });
  assertBaseline(value);
  value.instances[1].getMatrixAt = undefined;
  const audit = value.adapter.getPlacementTransformAudit();
  assert.equal(audit.status, 'incomplete');
  assert.equal(audit.auditedPlacementCount, 0);
  assert.equal(audit.unavailablePlacementCount, 2);
});
