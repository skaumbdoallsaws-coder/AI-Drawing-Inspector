import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const LAYOUT_URL = './p4-facility-layout.json';
const CATALOG_URL = './p4-asset-catalog.json';
const OVERVIEW_URL = (
  '/generated/industrial_assets/p0_spike/rack_prototypes/' +
  'Pallet%20Racking_colored_overview_proxy.glb'
);
const DETAIL_URL = (
  '/generated/industrial_assets/p0_spike/rack_prototypes/' +
  'Pallet%20Racking_colored.glb'
);
const CLEAR_COLOR = Object.freeze({ r: 203, g: 212, b: 220 });

const LayoutRuntime = window.InspectorProFacilityLayout;
const ThreeRuntime = window.InspectorProFacilityThree;

const evidence = {
  state: 'loading',
  threeRevision: THREE.REVISION,
  officialLoaderImported: typeof GLTFLoader === 'function',
  officialControlsImported: typeof OrbitControls === 'function',
  errors: []
};
window.facilityP4Evidence = evidence;

const planHost = document.getElementById('plan-view');
const threeHost = document.getElementById('three-view');
const threePane = document.getElementById('three-pane');
const propertiesHost = document.getElementById('properties-content');
const selectionState = document.getElementById('selection-state');
const statusElement = document.getElementById('status');
const fitButton = document.getElementById('fit-button');

const NativeResizeObserver = window.ResizeObserver;
const tracker = {
  activeObserverTargets: 0,
  observerInstances: 0,
  activeFrames: new Map(),
  nextFrameToken: 1
};

class TrackedResizeObserver {
  constructor(callback) {
    this.targets = new Set();
    this.inner = new NativeResizeObserver(callback);
    tracker.observerInstances += 1;
  }

  observe(target) {
    if (!this.targets.has(target)) {
      this.targets.add(target);
      tracker.activeObserverTargets += 1;
    }
    this.inner.observe(target);
  }

  unobserve(target) {
    if (this.targets.delete(target)) {
      tracker.activeObserverTargets -= 1;
    }
    this.inner.unobserve(target);
  }

  disconnect() {
    tracker.activeObserverTargets -= this.targets.size;
    this.targets.clear();
    this.inner.disconnect();
  }
}

function trackedRequestAnimationFrame(callback) {
  const token = tracker.nextFrameToken;
  tracker.nextFrameToken += 1;
  const nativeId = window.requestAnimationFrame((timestamp) => {
    tracker.activeFrames.delete(token);
    callback(timestamp);
  });
  tracker.activeFrames.set(token, nativeId);
  return token;
}

function trackedCancelAnimationFrame(token) {
  const nativeId = tracker.activeFrames.get(token);
  if (nativeId === undefined) return;
  tracker.activeFrames.delete(token);
  window.cancelAnimationFrame(nativeId);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function nextFrame() {
  return new Promise((resolve) => window.requestAnimationFrame(resolve));
}

function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function findPlacement(layout, placementId) {
  return layout.placements.find(
    (placement) => placement.placementId === placementId
  ) || null;
}

function displayPosition(placement) {
  const position = placement.transform.position;
  return [
    position.x.toFixed(2),
    position.y.toFixed(2),
    position.z.toFixed(2)
  ].join(', ') + ' m';
}

function createPropertiesAdapter() {
  let layout = null;
  let selection = null;
  let disposed = false;
  let renderCount = 0;

  function render() {
    renderCount += 1;
    if (disposed) return;
    const placement = layout && selection
      ? findPlacement(layout, selection)
      : null;
    selectionState.textContent = placement ? 'Selected' : 'No selection';
    if (!placement) {
      propertiesHost.innerHTML = (
        '<div class="empty-properties">' +
        'Select a rack in the top plan or 3D view.' +
        '</div>'
      );
      return;
    }
    const label = placement.metadata.instanceLabel || placement.placementId;
    propertiesHost.innerHTML = [
      '<h2 class="selection-name"></h2>',
      '<div class="selection-id"></div>',
      '<dl class="property-grid">',
      '<dt>Asset</dt><dd class="asset-value"></dd>',
      '<dt>Position</dt><dd class="position-value"></dd>',
      '<dt>Mode</dt><dd><span class="mode-badge"></span></dd>',
      '<dt>Revision</dt><dd class="revision-value"></dd>',
      '</dl>'
    ].join('');
    propertiesHost.querySelector('.selection-name').textContent = label;
    propertiesHost.querySelector('.selection-id').textContent =
      placement.placementId;
    propertiesHost.querySelector('.asset-value').textContent =
      placement.assetId;
    propertiesHost.querySelector('.position-value').textContent =
      displayPosition(placement);
    propertiesHost.querySelector('.mode-badge').textContent =
      placement.positionMode;
    propertiesHost.querySelector('.revision-value').textContent =
      placement.assetDefinitionRevision.slice(0, 12);
  }

  return {
    id: 'facility-properties',
    type: 'properties',
    setLayout(value) {
      layout = clone(value);
      render();
    },
    setSelection(value) {
      selection = value || null;
      render();
    },
    getDiagnostics() {
      return {
        id: 'facility-properties',
        type: 'properties',
        mounted: !disposed,
        observerCount: 0,
        renderCount,
        selection
      };
    },
    dispose() {
      disposed = true;
      layout = null;
      selection = null;
    }
  };
}

function rackBounds(catalogEntry) {
  return clone(catalogEntry.definition.geometry.aabb);
}

function createFootprintPrototype(catalogEntry) {
  const bounds = rackBounds(catalogEntry);
  const width = bounds.maximum.x - bounds.minimum.x;
  const height = bounds.maximum.y - bounds.minimum.y;
  const depth = bounds.maximum.z - bounds.minimum.z;
  const geometry = new THREE.BoxGeometry(width, height, depth);
  const material = new THREE.MeshStandardMaterial({
    color: 0x6c8799,
    transparent: true,
    opacity: 0.72,
    roughness: 0.82,
    metalness: 0.05
  });
  const object = new THREE.Mesh(geometry, material);
  object.position.set(
    (bounds.minimum.x + bounds.maximum.x) / 2,
    (bounds.minimum.y + bounds.maximum.y) / 2,
    (bounds.minimum.z + bounds.maximum.z) / 2
  );
  object.name = 'P4RackFootprint';
  return {
    object,
    bounds,
    instancingEligible: true
  };
}

function createAssetResolver(catalogEntry, fullDetail) {
  return {
    loadManifest() {
      return {
        assetId: catalogEntry.assetId,
        assetDefinitionRevision: catalogEntry.assetDefinitionRevision,
        definition: clone(catalogEntry.definition)
      };
    },
    loadFootprint() {
      return createFootprintPrototype(catalogEntry);
    },
    loadProxy() {
      return fullDetail ? OVERVIEW_URL : null;
    },
    loadOverview() {
      return fullDetail ? OVERVIEW_URL : null;
    },
    loadDetail() {
      return fullDetail ? DETAIL_URL : null;
    }
  };
}

function createRenderer() {
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
    powerPreference: 'high-performance'
  });
  renderer.setClearColor(0xcbd4dc, 1);
  return renderer;
}

let sourceLayout = null;
let assetCatalog = null;
let current = null;

function disposeCurrent() {
  if (current && current.controller) {
    current.controller.dispose();
  }
  current = null;
  planHost.replaceChildren();
  threeHost.replaceChildren();
  propertiesHost.innerHTML = (
    '<div class="empty-properties">' +
    'Select a rack in the top plan or 3D view.' +
    '</div>'
  );
  selectionState.textContent = 'No selection';
  threePane.dataset.degraded = 'false';
}

async function settleRuntime() {
  await nextFrame();
  await nextFrame();
  await delay(80);
  await nextFrame();
}

async function mountRuntime(fullDetail) {
  disposeCurrent();
  const catalogEntry = assetCatalog[0];
  const plan = LayoutRuntime.createTopPlanAdapter(planHost, {
    id: 'facility-top-plan',
    ResizeObserver: TrackedResizeObserver,
    padding: 20,
    assetBounds: {
      [catalogEntry.assetId]: catalogEntry.definition.geometry
    }
  });
  const three = ThreeRuntime.createThreeAdapter({
    THREE,
    OrbitControls,
    GLTFLoader,
    ResizeObserver: TrackedResizeObserver,
    requestAnimationFrame: trackedRequestAnimationFrame,
    cancelAnimationFrame: trackedCancelAnimationFrame,
    rendererFactory: createRenderer,
    assetResolver: createAssetResolver(catalogEntry, fullDetail),
    onDegraded() {
      threePane.dataset.degraded = 'true';
      statusElement.textContent = '2D only';
    },
    onStatusChange(value) {
      if (value.status === 'ready') statusElement.textContent = 'Ready';
      if (value.status === 'degraded') statusElement.textContent = '2D only';
    },
    logger: {
      warn() {}
    }
  });
  three.id = 'facility-three';
  three.type = 'three';
  three.mount(threeHost);
  const canvas = threeHost.querySelector('canvas');
  if (canvas) canvas.tabIndex = 0;
  const properties = createPropertiesAdapter();
  const controller = LayoutRuntime.createEditor({
    layout: sourceLayout,
    assetCatalog,
    adapters: [plan, three, properties]
  });
  current = { controller, plan, three, properties, fullDetail };
  await controller.ready();
  controller.fit();
  await settleRuntime();
  statusElement.textContent = 'Ready';
  return getSummary();
}

function getSummary() {
  if (!current) return null;
  const controllerState = current.controller.getState();
  const three = current.three.getDiagnostics();
  const plan = current.plan.getDiagnostics();
  const properties = current.properties.getDiagnostics();
  return {
    selectedPlacementId: controllerState.selectedPlacementId,
    planSelection: plan.selection,
    threeSelection: three.selectedPlacementIds[0] || null,
    propertiesSelection: properties.selection,
    planPlacementIds: plan.placementIds.slice().sort(),
    threePlacementCount: three.placementCount,
    threeStatus: three.status,
    degraded: three.degraded,
    contextLost: three.contextLost,
    representationGroups: clone(three.representationGroups),
    loadTrace: clone(three.loadTrace),
    demandRendering: clone(three.demandRendering),
    lifecycle: clone(three.lifecycle),
    modelRootTransform: clone(three.modelRootTransform),
    lastFit: clone(three.lastFit),
    activeObserverTargets: tracker.activeObserverTargets,
    activeRenderRequests: tracker.activeFrames.size,
    canvasCount: document.querySelectorAll('#three-view canvas').length,
    planSvgCount: document.querySelectorAll('#plan-view svg').length
  };
}

async function runFitProbe() {
  const sourceBefore = JSON.stringify(sourceLayout);
  const stateBefore = JSON.stringify(current.controller.getState().layout);
  const rootBefore = JSON.stringify(
    current.three.getDiagnostics().modelRootTransform
  );
  const results = current.controller.fit();
  await settleRuntime();
  const diagnostics = current.three.getDiagnostics();
  return {
    sourceLayoutUnchanged: JSON.stringify(sourceLayout) === sourceBefore,
    controllerLayoutUnchanged: (
      JSON.stringify(current.controller.getState().layout) === stateBefore
    ),
    modelRootUnchanged: (
      JSON.stringify(diagnostics.modelRootTransform) === rootBefore
    ),
    adapterReportedRootUnchanged: (
      diagnostics.lastFit && diagnostics.lastFit.rootUnchanged === true
    ),
    delegatedViewCount: results.length
  };
}

function clientPointForNdc(ndc) {
  const canvas = threeHost.querySelector('canvas');
  const rect = canvas.getBoundingClientRect();
  return {
    clientX: rect.left + ((ndc.x + 1) / 2) * rect.width,
    clientY: rect.top + ((1 - ndc.y) / 2) * rect.height
  };
}

function find3DPickPoint(preferredPlacementId, excludedPlacementId) {
  if (!current) return null;
  const hits = [];
  const steps = 72;
  for (let row = 2; row < steps - 2; row += 1) {
    const y = 1 - (row / (steps - 1)) * 2;
    for (let column = 2; column < steps - 2; column += 1) {
      const x = (column / (steps - 1)) * 2 - 1;
      const hit = current.three.pick({
        normalized: true,
        x,
        y
      });
      if (!hit || hit.placementId === excludedPlacementId) continue;
      const point = Object.assign(
        {
          placementId: hit.placementId,
          ndc: { x, y }
        },
        clientPointForNdc({ x, y })
      );
      if (hit.placementId === preferredPlacementId) return point;
      hits.push(point);
    }
  }
  return hits[0] || null;
}

async function canvasPixelProbe() {
  const canvas = threeHost.querySelector('canvas');
  if (!canvas) return { available: false, changedPixelCount: 0 };
  current.three.invalidate();
  await nextFrame();
  const context = canvas.getContext('webgl2') || canvas.getContext('webgl');
  if (!context) return { available: false, changedPixelCount: 0 };
  const width = context.drawingBufferWidth;
  const height = context.drawingBufferHeight;
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
  let maximumChannelSpan = 0;
  for (let offset = 0; offset < pixels.length; offset += 4) {
    const red = pixels[offset];
    const green = pixels[offset + 1];
    const blue = pixels[offset + 2];
    const delta = (
      Math.abs(red - CLEAR_COLOR.r) +
      Math.abs(green - CLEAR_COLOR.g) +
      Math.abs(blue - CLEAR_COLOR.b)
    );
    if (delta > 18) changed += 1;
    maximumChannelSpan = Math.max(
      maximumChannelSpan,
      Math.max(red, green, blue) - Math.min(red, green, blue)
    );
  }
  return {
    available: true,
    width,
    height,
    changedPixelCount: changed,
    changedPixelFraction: changed / Math.max(1, width * height),
    maximumChannelSpan
  };
}

function simulateContextLoss() {
  const canvas = threeHost.querySelector('canvas');
  if (!canvas) return null;
  const event = new Event('webglcontextlost', {
    bubbles: false,
    cancelable: true
  });
  canvas.dispatchEvent(event);
  return {
    defaultPrevented: event.defaultPrevented,
    summary: getSummary()
  };
}

async function runRemountProbe(cycles) {
  const count = Number.isInteger(cycles) ? cycles : 20;
  let maximumCanvasCount = 0;
  let maximumObserverTargets = 0;
  disposeCurrent();
  for (let index = 0; index < count; index += 1) {
    await mountRuntime(false);
    maximumCanvasCount = Math.max(
      maximumCanvasCount,
      document.querySelectorAll('#three-view canvas').length
    );
    maximumObserverTargets = Math.max(
      maximumObserverTargets,
      tracker.activeObserverTargets
    );
    disposeCurrent();
    await nextFrame();
    if (document.querySelectorAll('#three-view canvas').length !== 0) {
      throw new Error('Canvas remained after remount disposal.');
    }
    if (tracker.activeObserverTargets !== 0) {
      throw new Error('ResizeObserver target leaked after disposal.');
    }
  }
  await mountRuntime(true);
  await settleRuntime();
  const before = current.three.getDiagnostics().demandRendering.renderRequests;
  await delay(180);
  const after = current.three.getDiagnostics().demandRendering.renderRequests;
  const summary = getSummary();
  return {
    cycles: count,
    maximumCanvasCount,
    maximumObserverTargets,
    finalCanvasCount: summary.canvasCount,
    finalPlanSvgCount: summary.planSvgCount,
    activeObserverTargets: tracker.activeObserverTargets,
    activeRenderRequests: tracker.activeFrames.size,
    pendingFrame: summary.demandRendering.pendingFrame,
    idleRenderRequestsUnchanged: before === after,
    finalRepresentation: (
      summary.representationGroups[0]
        ? summary.representationGroups[0].representation
        : null
    )
  };
}

function selectViewMode(mode) {
  document.querySelectorAll('[data-view-mode]').forEach((button) => {
    button.setAttribute(
      'aria-pressed',
      button.dataset.viewMode === mode ? 'true' : 'false'
    );
  });
  if (mode === 'plan') {
    const first = planHost.querySelector('[data-placement-id]');
    if (first) first.focus();
  } else {
    const canvas = threeHost.querySelector('canvas');
    if (canvas) canvas.focus();
  }
}

fitButton.addEventListener('click', () => {
  if (current) current.controller.fit();
});

document.querySelectorAll('[data-view-mode]').forEach((button) => {
  button.addEventListener('click', () => selectViewMode(button.dataset.viewMode));
});

async function boot() {
  if (!LayoutRuntime || !ThreeRuntime) {
    throw new Error('Facility renderer modules are unavailable.');
  }
  if (typeof NativeResizeObserver !== 'function') {
    throw new Error('ResizeObserver is unavailable.');
  }
  [sourceLayout, assetCatalog] = await Promise.all([
    fetch(LAYOUT_URL).then((response) => {
      if (!response.ok) throw new Error('Layout fixture request failed.');
      return response.json();
    }),
    fetch(CATALOG_URL).then((response) => {
      if (!response.ok) throw new Error('Catalog fixture request failed.');
      return response.json();
    })
  ]);
  await mountRuntime(true);
  Object.assign(evidence, {
    state: 'ready',
    layoutId: sourceLayout.layoutId,
    placementIds: sourceLayout.placements.map(
      (placement) => placement.placementId
    ).sort(),
    getSummary,
    runFitProbe,
    find3DPickPoint,
    canvasPixelProbe,
    simulateContextLoss,
    runRemountProbe,
    remount: () => mountRuntime(true)
  });
  document.documentElement.dataset.p4State = 'ready';
}

boot().catch((error) => {
  const message = String(error && error.stack ? error.stack : error);
  evidence.state = 'error';
  evidence.errors.push(message);
  statusElement.textContent = 'Error';
  document.documentElement.dataset.p4State = 'error';
});
