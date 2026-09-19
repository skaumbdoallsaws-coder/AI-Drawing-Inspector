'use strict';

const path = require('node:path');
const { pathToFileURL } = require('node:url');
const runtime = require('../../../static/facility_layout_three_adapter.js');

let pinnedThree;
function getPinnedThree() {
  pinnedThree ||= import(pathToFileURL(path.resolve(__dirname,
    '../../../static/vendor/three/0.184.0/build/three.module.min.js')).href);
  return pinnedThree;
}

class DomTarget {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(callback);
  }
  removeEventListener(type, callback) { this.listeners.get(type)?.delete(callback); }
}

class DomElement extends DomTarget {
  constructor() {
    super();
    this.style = {};
    this.attributes = {};
    this.children = [];
    this.parentNode = null;
    this.clientWidth = 900;
    this.clientHeight = 700;
  }
  appendChild(child) {
    child.parentNode?.removeChild(child);
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getBoundingClientRect() {
    return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight,
      right: this.clientWidth, bottom: this.clientHeight };
  }
}

/** Real scene graph and CPU matrix/instance storage; no WebGL context or browser. */
async function createRealThreeHarness(options = {}) {
  const THREE = options.THREE || await getPinnedThree();
  const host = new DomElement();
  const document = new DomTarget();
  document.hidden = false;
  const window = new DomTarget();
  const frames = new Map();
  let frameId = 0;
  let clock = 0;
  const errors = [];
  const renderer = {
    domElement: new DomElement(),
    info: { render: { calls: 0, triangles: 0 }, memory: { geometries: 0, textures: 0 }, reset() {} },
    renderLists: { dispose() {} },
    lastRender: null,
    setPixelRatio(value) { this.pixelRatio = value; },
    setSize(width, height) {
      this.domElement.clientWidth = width;
      this.domElement.clientHeight = height;
    },
    render(scene, camera) {
      scene.updateMatrixWorld(true);
      camera.updateMatrixWorld(true);
      this.lastRender = { scene, camera };
      this.info.render.calls++;
    },
    setAnimationLoop() {}, setRenderTarget() {}, dispose() {}, forceContextLoss() {},
  };
  class Controls extends DomTarget {
    constructor(camera, canvas) {
      super(); this.camera = camera; this.domElement = canvas;
      this.target = new THREE.Vector3();
    }
    update() {} dispose() {}
  }
  class ResizeObserver {
    observe() {} disconnect() {}
  }
  const adapter = runtime.createThreeAdapter({
    ...options,
    THREE,
    rendererFactory: () => renderer,
    OrbitControls: Controls,
    ResizeObserver,
    document,
    window,
    requestAnimationFrame(callback) { const id = ++frameId; frames.set(id, callback); return id; },
    cancelAnimationFrame(id) { frames.delete(id); },
    logger: { warn(...values) { errors.push(values); } },
  });
  adapter.mount(host);
  function flush(maximumFrames = 30) {
    let count = 0;
    while (frames.size) {
      if (++count > maximumFrames) throw new Error('Unexpected continuous animation in matrix harness');
      const pending = [...frames.values()];
      frames.clear();
      clock += 16;
      pending.forEach(callback => callback(clock));
    }
    return renderer.lastRender;
  }
  return { THREE, adapter, renderer, host, errors, flush,
    dispose() { adapter.dispose(); frames.clear(); } };
}

module.exports = { getPinnedThree, createRealThreeHarness };
