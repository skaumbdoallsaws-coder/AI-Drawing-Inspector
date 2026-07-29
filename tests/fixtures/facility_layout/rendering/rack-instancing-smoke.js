import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const FIXTURE_URL = './repeated-rack-instance-spike.json';

function placementMatrix(placement) {
  const position = new THREE.Vector3(
    placement.position.x,
    placement.position.y,
    placement.position.z
  );
  const quaternion = new THREE.Quaternion(
    placement.quaternion.x,
    placement.quaternion.y,
    placement.quaternion.z,
    placement.quaternion.w
  );
  const scale = new THREE.Vector3(
    placement.scale,
    placement.scale,
    placement.scale
  );
  return new THREE.Matrix4().compose(position, quaternion, scale);
}

function collectPrototypeMeshes(root) {
  root.updateMatrixWorld(true);
  const meshes = [];
  root.traverse((object) => {
    if (!object.isMesh || !object.geometry || !object.material) {
      return;
    }
    meshes.push({
      geometry: object.geometry,
      material: object.material,
      matrix: object.matrixWorld.clone()
    });
  });
  return meshes;
}

function expandBounds(target, geometry, matrix) {
  if (!geometry.boundingBox) {
    geometry.computeBoundingBox();
  }
  const bounds = geometry.boundingBox.clone();
  bounds.applyMatrix4(matrix);
  target.union(bounds);
}

function buildInstanceScene(scene, meshes, placements) {
  const instanceMeshes = [];
  const reverseLookup = new Map();
  const bounds = new THREE.Box3();
  const matrix = new THREE.Matrix4();

  for (const prototype of meshes) {
    const instances = new THREE.InstancedMesh(
      prototype.geometry,
      prototype.material,
      placements.length
    );
    const placementIds = [];
    for (let index = 0; index < placements.length; index += 1) {
      const placement = placements[index];
      matrix.multiplyMatrices(placementMatrix(placement), prototype.matrix);
      instances.setMatrixAt(index, matrix);
      placementIds.push(placement.placementId);
      expandBounds(bounds, prototype.geometry, matrix);
    }
    instances.instanceMatrix.needsUpdate = true;
    instances.computeBoundingBox();
    instances.computeBoundingSphere();
    reverseLookup.set(instances.uuid, placementIds);
    instanceMeshes.push(instances);
    scene.add(instances);
  }

  return { bounds, instanceMeshes, reverseLookup };
}

function frameCamera(camera, bounds, aspect) {
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const span = Math.max(size.x, size.z, 1);
  camera.aspect = aspect;
  camera.position.set(
    center.x + span * 1.2,
    center.y + Math.max(size.y * 1.4, span),
    center.z + span * 1.2
  );
  camera.near = Math.max(0.01, span / 1000);
  camera.far = span * 20;
  camera.lookAt(center);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
}

function resolveRaycastPlacement(camera, bounds, meshes, lookup) {
  const target = bounds.getCenter(new THREE.Vector3()).project(camera);
  const raycaster = new THREE.Raycaster();
  raycaster.setFromCamera(new THREE.Vector2(target.x, target.y), camera);
  const hits = raycaster.intersectObjects(meshes, false);
  const hit = hits.find((candidate) => Number.isInteger(candidate.instanceId));
  if (!hit) {
    return null;
  }
  const placementIds = lookup.get(hit.object.uuid) || [];
  return {
    instanceId: hit.instanceId,
    placementId: placementIds[hit.instanceId] || null
  };
}

function countChangedPixels(renderer, width, height, clearColor) {
  const context = renderer.getContext();
  const pixels = new Uint8Array(width * height * 4);
  context.readPixels(
    0,
    0,
    width,
    height,
    context.RGBA,
    context.UNSIGNED_BYTE,
    pixels
  );
  let changed = 0;
  for (let offset = 0; offset < pixels.length; offset += 4) {
    if (
      Math.abs(pixels[offset] - clearColor.r) > 2 ||
      Math.abs(pixels[offset + 1] - clearColor.g) > 2 ||
      Math.abs(pixels[offset + 2] - clearColor.b) > 2
    ) {
      changed += 1;
    }
  }
  return changed;
}

async function runSmoke() {
  const result = {
    state: 'running',
    threeRevision: THREE.REVISION,
    officialLoaderImported: typeof GLTFLoader === 'function'
  };
  window.facilityRackInstancingSmoke = result;

  const fixture = await fetch(FIXTURE_URL).then((response) => {
    if (!response.ok) {
      throw new Error(`Fixture request failed: ${response.status}`);
    }
    return response.json();
  });
  const geometryUrl = `/${fixture.prototype.geometryPath
    .split('/')
    .map(encodeURIComponent)
    .join('/')}`;
  const gltf = await new GLTFLoader().loadAsync(geometryUrl);
  const prototypeMeshes = collectPrototypeMeshes(gltf.scene);

  const canvas = document.getElementById('rack-canvas');
  const width = 1280;
  const height = 800;
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true
  });
  renderer.setPixelRatio(1);
  renderer.setSize(width, height, false);
  renderer.setClearColor(0x17212b, 1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, width / height, 0.01, 1000);
  scene.add(new THREE.HemisphereLight(0xd9efff, 0x24313a, 2.4));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(8, 16, 12);
  scene.add(key);

  const built = buildInstanceScene(
    scene,
    prototypeMeshes,
    fixture.placements
  );
  frameCamera(camera, built.bounds, width / height);
  renderer.render(scene, camera);

  const clearColor = { r: 0x17, g: 0x21, b: 0x2b };
  const raycast = resolveRaycastPlacement(
    camera,
    built.bounds,
    built.instanceMeshes,
    built.reverseLookup
  );
  const placementIds = fixture.placements.map((item) => item.placementId);

  Object.assign(result, {
    state: 'complete',
    prototypeId: fixture.prototype.prototypeId,
    prototypeMeshCount: prototypeMeshes.length,
    placementCount: fixture.placements.length,
    instancedMeshCount: built.instanceMeshes.length,
    totalGeometryInstances:
      built.instanceMeshes.length * fixture.placements.length,
    naiveDrawCalls:
      prototypeMeshes.length * fixture.placements.length,
    instancedDrawCalls: renderer.info.render.calls,
    drawCallReductionRatio:
      (prototypeMeshes.length * fixture.placements.length) /
      Math.max(renderer.info.render.calls, 1),
    renderedTriangles: renderer.info.render.triangles,
    changedPixelCount: countChangedPixels(
      renderer,
      width,
      height,
      clearColor
    ),
    raycast,
    raycastResolvedStablePlacement:
      Boolean(raycast) && placementIds.includes(raycast.placementId),
    uniquePlacementIds: new Set(placementIds).size,
    webgl2Rendered:
      typeof WebGL2RenderingContext !== 'undefined' &&
      renderer.getContext() instanceof WebGL2RenderingContext
  });
  window.facilityRackInstancingSmoke = result;
  document.documentElement.dataset.result = 'complete';
}

runSmoke().catch((error) => {
  window.facilityRackInstancingSmoke = {
    state: 'error',
    error: String(error && error.stack ? error.stack : error)
  };
  document.documentElement.dataset.result = 'error';
});
