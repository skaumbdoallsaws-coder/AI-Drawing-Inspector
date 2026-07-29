import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

function buildMinimalGlb() {
  const document = JSON.stringify({
    asset: { version: '2.0', generator: 'InspectorPro P0 offline smoke' },
    scene: 0,
    scenes: [{}]
  });
  const encoder = new TextEncoder();
  const source = encoder.encode(document);
  const paddedLength = Math.ceil(source.length / 4) * 4;
  const totalLength = 12 + 8 + paddedLength;
  const buffer = new ArrayBuffer(totalLength);
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);

  view.setUint32(0, 0x46546c67, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, totalLength, true);
  view.setUint32(12, paddedLength, true);
  view.setUint32(16, 0x4e4f534a, true);
  bytes.fill(0x20, 20, totalLength);
  bytes.set(source, 20);
  return buffer;
}

async function runSmoke() {
  const result = {
    state: 'running',
    threeRevision: THREE.REVISION,
    officialLoaderImported: typeof GLTFLoader === 'function',
    validGlbParsed: false,
    corruptGlbRejected: false,
    webgl2Rendered: false,
    nonblankPixel: false,
    renderCalls: 0,
    triangles: 0
  };
  window.facilityThreeOfflineSmoke = result;

  const loader = new GLTFLoader();
  const valid = buildMinimalGlb();
  const parsed = await loader.parseAsync(valid, '');
  result.validGlbParsed = Boolean(parsed && parsed.scene && parsed.scenes.length === 1);

  const corrupt = valid.slice(0);
  new DataView(corrupt).setUint32(0, 0, true);
  try {
    await loader.parseAsync(corrupt, '');
  } catch (_error) {
    result.corruptGlbRejected = true;
  }

  const canvas = document.getElementById('smoke-canvas');
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: false,
    alpha: false,
    preserveDrawingBuffer: true
  });
  renderer.setSize(64, 64, false);
  renderer.setClearColor(0x102030, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10);
  camera.position.set(0, 0, 3);
  const geometry = new THREE.BoxGeometry(1, 1, 1);
  const material = new THREE.MeshBasicMaterial({ color: 0x35b8c8 });
  const mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh);
  renderer.render(scene, camera);

  const context = renderer.getContext();
  const pixel = new Uint8Array(4);
  context.readPixels(32, 32, 1, 1, context.RGBA, context.UNSIGNED_BYTE, pixel);
  result.webgl2Rendered =
    typeof WebGL2RenderingContext !== 'undefined' &&
    context instanceof WebGL2RenderingContext;
  result.nonblankPixel = pixel[0] + pixel[1] + pixel[2] > 0;
  result.renderCalls = renderer.info.render.calls;
  result.triangles = renderer.info.render.triangles;

  scene.remove(mesh);
  geometry.dispose();
  material.dispose();
  renderer.dispose();
  result.state = 'complete';
  window.facilityThreeOfflineSmoke = result;
  document.documentElement.dataset.result = 'complete';
}

runSmoke().catch((error) => {
  window.facilityThreeOfflineSmoke = {
    state: 'error',
    error: String(error && error.stack ? error.stack : error)
  };
  document.documentElement.dataset.result = 'error';
});
