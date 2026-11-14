const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const shared = require('../static/cad_viewport.js');
const legacy = require('../static/vendor/three/0.128.0/build/three.min.js');

function documentFixture(theme = 'dark', tokens = {}) {
  const gradients = [], labels = [];
  const context = {
    createLinearGradient(...points) { const result = { kind: 'linear', points, stops: [], addColorStop(...s) { this.stops.push(s); } }; gradients.push(result); return result; },
    createRadialGradient(...points) { const result = { kind: 'radial', points, stops: [], addColorStop(...s) { this.stops.push(s); } }; gradients.push(result); return result; },
    fillRect() {}, fillText(label) { labels.push(label); }
  };
  const document = {
    documentElement: { getAttribute: () => theme },
    defaultView: { getComputedStyle: () => ({ getPropertyValue: name => tokens[name] || '' }) },
    createElement: () => ({ style: {}, setAttribute() {}, getContext: () => context, remove() { this.removed = true; } })
  };
  return { document, gradients, labels };
}

test('Assembly and Packaging share the background, tokens and orientation implementation', () => {
  const main = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
  const packaging = fs.readFileSync(path.join(__dirname, '../static/packaging_scene.js'), 'utf8');
  const html = fs.readFileSync(path.join(__dirname, '../static/packaging.html'), 'utf8');
  const css = fs.readFileSync(path.join(__dirname, '../static/cad_viewport.css'), 'utf8');
  assert.match(main, /InspectorProCadViewport\.createBackgroundTexture\(threeRuntime, document\)/);
  assert.match(main, /InspectorProCadViewport\.createOrientationGizmo\(THREE, container\)/);
  assert.match(packaging, /createBackgroundTexture\(THREE, host.ownerDocument\)/);
  assert.match(packaging, /createOrientationGizmo\(THREE, host\)/);
  for (const source of [main, html]) assert.match(source, /href="\/static\/cad_viewport.css"/);
  assert.doesNotMatch(main, /--viewport-bg-(center|mid|edge|gradient):/);
  assert.doesNotMatch(packaging, /GridHelper|AxesHelper|createLinearGradient|createRadialGradient/);
  assert.match(css, /bottom: 12px/); assert.match(css, /left: 12px/); assert.match(css, /pointer-events: none/);
});

test('background preserves Assembly band stops and theme token overrides', () => {
  const f = documentFixture('dark', { '--viewport-bg-center': '#123456' });
  const texture = shared.createBackgroundTexture(legacy, f.document);
  assert.deepEqual([texture.image.width, texture.image.height], [1024, 768]);
  assert.equal(texture.encoding, legacy.sRGBEncoding);
  assert.deepEqual(f.gradients[0].stops, [[0, '#343c47'], [.27, '#2b333e'], [.5, '#123456'], [.73, '#2b333e'], [1, '#343c47']]);
  assert.equal(f.gradients.length, 2);
  texture.dispose();
});

test('light background retains Assembly radial falloff and modern sRGB', async () => {
  const THREE = await import(pathToFileURL(path.join(__dirname, '../static/vendor/three/0.184.0/build/three.module.min.js')));
  const f = documentFixture('light');
  const texture = shared.createBackgroundTexture(THREE, f.document);
  assert.equal(texture.colorSpace, THREE.SRGBColorSpace);
  assert.equal(f.gradients.length, 3);
  assert.deepEqual(f.gradients[2].stops, [[0, 'rgba(54,68,82,0.24)'], [.36, 'rgba(84,100,116,0.14)'], [.72, 'rgba(255,255,255,0.00)']]);
  texture.dispose();
});

for (const version of ['legacy', 'modern']) test(`${version} triad follows world rotation, not pan/zoom, and releases resources`, async () => {
  const runtime = version === 'legacy' ? legacy : await import(pathToFileURL(path.join(__dirname, '../static/vendor/three/0.184.0/build/three.module.min.js')));
  let renderer;
  class Renderer {
    constructor({ canvas }) { this.canvas = canvas; renderer = this; }
    setClearColor() {} setPixelRatio() {} setSize() {}
    render(scene, camera) { this.scene = scene; this.camera = camera; this.renders = (this.renders || 0) + 1; }
    dispose() { this.disposed = true; }
    forceContextLoss() { this.contextLosses = (this.contextLosses || 0) + 1; }
  }
  const THREE = { ...runtime, WebGLRenderer: Renderer };
  const f = documentFixture(), container = { ownerDocument: f.document, appendChild() {} };
  const gizmo = shared.createOrientationGizmo(THREE, container);
  const camera = new THREE.PerspectiveCamera(40, 1, .01, 1000), parent = new THREE.Group();
  parent.rotation.set(.3, .7, .2); parent.add(camera);
  camera.rotation.set(.1, .4, .6); camera.position.set(1, 2, 3);
  const expected = camera.getWorldQuaternion(new THREE.Quaternion());
  const original = camera.matrixWorld.toArray();
  gizmo.update(camera);
  assert.ok(renderer.camera.quaternion.angleTo(expected) < 1e-7);
  const orientation = renderer.camera.quaternion.toArray(), position = renderer.camera.position.toArray();
  assert.deepEqual(camera.matrixWorld.toArray(), original);
  camera.position.set(100, -40, 250); camera.zoom = 8; camera.updateProjectionMatrix();
  gizmo.update(camera);
  assert.deepEqual(renderer.camera.quaternion.toArray(), orientation);
  assert.deepEqual(renderer.camera.position.toArray(), position);
  camera.rotateZ(.5); gizmo.update(camera);
  assert.notDeepEqual(renderer.camera.quaternion.toArray(), orientation);
  assert.deepEqual(f.labels, ['X', 'Y', 'Z']);
  const axes = renderer.scene.children[0];
  assert.deepEqual(axes.children.filter(n => n.isLine).map(n => n.material.color.getHex()), [0xff4444, 0x44ff44, 0x4488ff]);
  let disposed = 0;
  axes.traverse(n => { for (const r of [n.geometry, n.material, n.material?.map]) r?.addEventListener('dispose', () => disposed++); });
  // Supervisor (P5a-3): a renderer leaves a 'dispose' listener on the geometry Three.js shares among all
  // sprites; a closed widget must take its own off, or the shared object keeps its WebGL context alive.
  const sprites = axes.children.filter(n => n.isSprite), spriteGeometries = new Set(sprites.map(n => n.geometry));
  let spriteReleases = 0;
  spriteGeometries.forEach(geometry => geometry.addEventListener('dispose', () => spriteReleases++));
  gizmo.dispose(); gizmo.dispose();
  assert.equal(sprites.length, 3); assert.equal(spriteReleases, spriteGeometries.size);
  assert.equal(disposed, 17); assert.equal(renderer.disposed, true); assert.equal(gizmo.canvas.removed, true);
  assert.equal(renderer.contextLosses, 1); assert.equal(axes.children.length, 0);
  const renders = renderer.renders; gizmo.update(camera); assert.equal(renderer.renders, renders);
});
