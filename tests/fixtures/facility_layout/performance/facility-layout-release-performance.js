import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const LAYOUT_URL = (
  '/tests/fixtures/facility_layout/rendering/p4-facility-layout.json'
);
const CATALOG_URL = (
  '/tests/fixtures/facility_layout/rendering/p4-asset-catalog.json'
);
const OVERVIEW_URL = (
  '/generated/industrial_assets/p0_spike/rack_prototypes/' +
  'Pallet%20Racking_colored_overview_proxy.glb'
);
const DETAIL_URL = (
  '/generated/industrial_assets/p0_spike/rack_prototypes/' +
  'Pallet%20Racking_colored.glb'
);
const FIXTURE_REVISION = (
  'f445fc1c92c5793d84936b01df393a8c82a138ffe8f5dbafef8073d25ed2b65b'
);

const LayoutRuntime = window.InspectorProFacilityLayout;
const ThreeRuntime = window.InspectorProFacilityThree;
const SessionRuntime = window.InspectorProFacilitySession;
const WorkspaceRuntime = window.InspectorProFacilityWorkspace;
const NativeResizeObserver = window.ResizeObserver;
const nativeRequestAnimationFrame = window.requestAnimationFrame.bind(window);
const nativeCancelAnimationFrame = window.cancelAnimationFrame.bind(window);

const root = document.getElementById('facility-benchmark-root');
const rendererPool = ThreeRuntime.createRendererPool({ maximumSize: 1 });
const state = {
  status: 'booting',
  errors: [],
  pageErrors: [],
  runtime: null,
  runtimeSequence: 0,
  layout: null,
  catalog: null,
  frameCapture: null
};

window.addEventListener('error', (event) => {
  state.pageErrors.push(String(event.message || event.error || event));
});
window.addEventListener('unhandledrejection', (event) => {
  state.pageErrors.push(String(event.reason || event));
});

const tracker = {
  activeObserverTargets: 0,
  observerInstances: 0,
  activeAdapterFrames: new Map(),
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
    if (this.targets.delete(target)) tracker.activeObserverTargets -= 1;
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
  const nativeId = nativeRequestAnimationFrame((timestamp) => {
    tracker.activeAdapterFrames.delete(token);
    callback(timestamp);
  });
  tracker.activeAdapterFrames.set(token, nativeId);
  return token;
}

function trackedCancelAnimationFrame(token) {
  const nativeId = tracker.activeAdapterFrames.get(token);
  if (nativeId === undefined) return;
  tracker.activeAdapterFrames.delete(token);
  nativeCancelAnimationFrame(nativeId);
}

function clone(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function nextFrame() {
  return new Promise((resolve) => nativeRequestAnimationFrame(resolve));
}

async function settle(turns = 4) {
  if (state.runtime && state.runtime.workspace) {
    await state.runtime.workspace.whenIdle();
    if (state.runtime.workspace.controller
        && typeof state.runtime.workspace.controller.ready === 'function') {
      await state.runtime.workspace.controller.ready();
    }
  }
  for (let index = 0; index < turns; index += 1) {
    await Promise.resolve();
    await nextFrame();
  }
}

function assertRuntimeModules() {
  const missing = [];
  if (!LayoutRuntime
      || typeof LayoutRuntime.createTopPlanAdapter !== 'function'
      || typeof LayoutRuntime.createEditor !== 'function') {
    missing.push('facility_layout_editor');
  }
  if (!ThreeRuntime
      || typeof ThreeRuntime.createThreeAdapter !== 'function') {
    missing.push('facility_layout_three_adapter');
  }
  if (!SessionRuntime || typeof SessionRuntime.createSession !== 'function') {
    missing.push('facility_layout_session');
  }
  if (!WorkspaceRuntime
      || typeof WorkspaceRuntime.createWorkspace !== 'function') {
    missing.push('facility_layout_workspace');
  }
  if (typeof NativeResizeObserver !== 'function') {
    missing.push('ResizeObserver');
  }
  if (missing.length) {
    throw new Error(`Required runtime modules unavailable: ${missing.join(', ')}`);
  }
}

function responseJson(response, label) {
  if (!response.ok) {
    throw new Error(`${label} request failed with HTTP ${response.status}`);
  }
  return response.json();
}

function memorySnapshot() {
  const memory = performance.memory;
  if (!memory
      || !Number.isFinite(memory.usedJSHeapSize)
      || !Number.isFinite(memory.totalJSHeapSize)
      || !Number.isFinite(memory.jsHeapSizeLimit)
      || memory.usedJSHeapSize <= 0
      || memory.jsHeapSizeLimit <= 0) {
    throw new Error(
      'Precise performance.memory is unavailable; launch with ' +
      '--enable-precise-memory-info.'
    );
  }
  return {
    source: 'performance.memory',
    usedJSHeapSize: Number(memory.usedJSHeapSize),
    totalJSHeapSize: Number(memory.totalJSHeapSize),
    jsHeapSizeLimit: Number(memory.jsHeapSizeLimit),
    capturedAtMs: performance.now()
  };
}

function webglInformation() {
  const canvas = state.runtime
    && state.runtime.workspace.threeView.querySelector('canvas');
  if (!canvas) throw new Error('The real Three adapter has no WebGL canvas.');
  const context = canvas.getContext('webgl2') || canvas.getContext('webgl');
  if (!context) throw new Error('The real Three adapter has no WebGL context.');
  const debug = context.getExtension('WEBGL_debug_renderer_info');
  return {
    contextType: context instanceof WebGL2RenderingContext ? 'webgl2' : 'webgl',
    vendor: String(context.getParameter(context.VENDOR) || ''),
    renderer: String(context.getParameter(context.RENDERER) || ''),
    unmaskedVendor: debug
      ? String(context.getParameter(debug.UNMASKED_VENDOR_WEBGL) || '')
      : null,
    unmaskedRenderer: debug
      ? String(context.getParameter(debug.UNMASKED_RENDERER_WEBGL) || '')
      : null,
    version: String(context.getParameter(context.VERSION) || ''),
    shadingLanguageVersion: String(
      context.getParameter(context.SHADING_LANGUAGE_VERSION) || ''
    ),
    maxTextureSize: Number(context.getParameter(context.MAX_TEXTURE_SIZE)),
    maxRenderbufferSize: Number(
      context.getParameter(context.MAX_RENDERBUFFER_SIZE)
    )
  };
}

function browserEnvironment() {
  return {
    userAgent: navigator.userAgent,
    platform: navigator.platform,
    language: navigator.language,
    hardwareConcurrency: navigator.hardwareConcurrency || null,
    deviceMemoryGiB: navigator.deviceMemory || null,
    crossOriginIsolated: window.crossOriginIsolated === true,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio
    },
    display: {
      width: screen.width,
      height: screen.height,
      availableWidth: screen.availWidth,
      availableHeight: screen.availHeight,
      colorDepth: screen.colorDepth,
      pixelDepth: screen.pixelDepth
    },
    preciseMemoryInfo: memorySnapshot()
  };
}

function createFootprintPrototype(catalogEntry) {
  const bounds = catalogEntry.definition.geometry.aabb;
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
  object.name = 'ReleaseBenchmarkRackFootprint';
  return {
    object,
    bounds: clone(bounds),
    instancingEligible: true
  };
}

function bufferByteLength(attribute) {
  if (!attribute) return 0;
  const array = attribute.array
    || (attribute.data && attribute.data.array)
    || null;
  return array && Number.isFinite(array.byteLength)
    ? Number(array.byteLength)
    : 0;
}

function textureBytes(texture) {
  if (!texture) return null;
  const image = texture.image || (
    texture.source && texture.source.data
  );
  const width = Number(image && (image.width || image.videoWidth));
  const height = Number(image && (image.height || image.videoHeight));
  if (!Number.isFinite(width) || !Number.isFinite(height)
      || width <= 0 || height <= 0) {
    return null;
  }
  const mipFactor = texture.generateMipmaps === false ? 1 : 4 / 3;
  return Math.ceil(width * height * 4 * mipFactor);
}

function visualAllocationEstimate(result, placementCount) {
  const scene = result && (result.scene || result.object || result.object3D);
  if (!scene || typeof scene.traverse !== 'function') {
    return {
      available: false,
      reason: 'loaded_visual_has_no_traversable_scene'
    };
  }
  const geometries = new Set();
  const textures = new Set();
  let meshCount = 0;
  scene.traverse((object) => {
    if (!object || !object.isMesh) return;
    meshCount += 1;
    if (object.geometry) geometries.add(object.geometry);
    const materials = Array.isArray(object.material)
      ? object.material
      : [object.material];
    materials.filter(Boolean).forEach((material) => {
      Object.keys(material).forEach((key) => {
        const candidate = material[key];
        if (candidate && candidate.isTexture) textures.add(candidate);
      });
    });
  });

  let geometryBufferBytes = 0;
  geometries.forEach((geometry) => {
    if (geometry.index) geometryBufferBytes += bufferByteLength(geometry.index);
    Object.values(geometry.attributes || {}).forEach((attribute) => {
      geometryBufferBytes += bufferByteLength(attribute);
    });
    Object.values(geometry.morphAttributes || {}).forEach((attributes) => {
      (attributes || []).forEach((attribute) => {
        geometryBufferBytes += bufferByteLength(attribute);
      });
    });
  });

  let textureAllocationBytes = 0;
  let unknownTextureCount = 0;
  textures.forEach((texture) => {
    const estimate = textureBytes(texture);
    if (estimate === null) unknownTextureCount += 1;
    else textureAllocationBytes += estimate;
  });
  const instanceMatrixBytes = meshCount * placementCount * 16 * 4;
  return {
    available: unknownTextureCount === 0,
    method: (
      'Unique BufferGeometry attribute/index byte lengths plus RGBA8 texture ' +
      'dimensions with mip factor and one 4x4 float instance matrix per ' +
      'mesh and placement.'
    ),
    geometryCount: geometries.size,
    textureCount: textures.size,
    unknownTextureCount,
    meshCount,
    geometryBufferBytes,
    textureAllocationBytes,
    instanceMatrixBytes,
    estimatedGpuAllocationBytes: (
      geometryBufferBytes + textureAllocationBytes + instanceMatrixBytes
    )
  };
}

function createStageRecorder(profile, catalogEntry) {
  const records = [];
  const loader = new GLTFLoader();

  async function record(stage, producer, metadata = {}) {
    const startedAtMs = performance.now();
    const entry = {
      stage,
      status: 'started',
      startedAtMs,
      endedAtMs: null,
      durationMs: null,
      url: metadata.url || null,
      visualAllocation: null,
      error: null
    };
    records.push(entry);
    try {
      const value = await producer();
      entry.endedAtMs = performance.now();
      entry.durationMs = entry.endedAtMs - entry.startedAtMs;
      entry.status = value === null || value === undefined
        ? 'skipped'
        : 'resolved';
      if (metadata.visual === true && value) {
        entry.visualAllocation = visualAllocationEstimate(
          value,
          state.layout.placements.length
        );
      }
      return value;
    } catch (error) {
      entry.endedAtMs = performance.now();
      entry.durationMs = entry.endedAtMs - entry.startedAtMs;
      entry.status = 'failed';
      entry.error = String(error && error.message || error);
      throw error;
    }
  }

  return {
    records,
    resolver: {
      loadManifest() {
        return record('manifest', async () => ({
          assetId: catalogEntry.assetId,
          assetDefinitionRevision: catalogEntry.assetDefinitionRevision,
          definition: clone(catalogEntry.definition)
        }));
      },
      loadFootprint() {
        return record('footprint', async () => (
          createFootprintPrototype(catalogEntry)
        ));
      },
      loadProxy() {
        return record(
          'proxy',
          async () => loader.loadAsync(OVERVIEW_URL),
          { url: OVERVIEW_URL, visual: true }
        );
      },
      loadOverview() {
        if (profile !== 'full-detail') {
          return record('overview', async () => null);
        }
        return record(
          'overview',
          async () => loader.loadAsync(OVERVIEW_URL),
          { url: OVERVIEW_URL, visual: true }
        );
      },
      loadDetail() {
        if (profile !== 'full-detail') {
          return record('detail', async () => null);
        }
        return record(
          'detail',
          async () => loader.loadAsync(DETAIL_URL),
          { url: DETAIL_URL, visual: true }
        );
      }
    }
  };
}

function createRenderer(record) {
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
    powerPreference: 'high-performance'
  });
  renderer.setClearColor(0xd7e0e6, 1);
  record.renderer = renderer;
  return renderer;
}

function rendererMetrics(runtime = state.runtime) {
  const renderer = runtime && runtime.rendererRecord.renderer;
  if (!renderer || !renderer.info) {
    throw new Error('renderer.info is unavailable from the real Three adapter.');
  }
  return {
    autoReset: renderer.info.autoReset !== false,
    render: clone(renderer.info.render),
    memory: clone(renderer.info.memory),
    programs: Array.isArray(renderer.info.programs)
      ? renderer.info.programs.length
      : null
  };
}

function createSession() {
  const session = SessionRuntime.createSession({
    async previewOperations() {
      throw new Error('Benchmark does not mutate the authoritative layout.');
    },
    async applyOperations() {
      throw new Error('Benchmark does not apply layout operations.');
    },
    async reloadLayout() {
      return {
        layout: clone(state.layout),
        revision: FIXTURE_REVISION
      };
    }
  });
  session.load({
    layout: clone(state.layout),
    revision: FIXTURE_REVISION
  });
  return session;
}

function resourceEntries() {
  return performance.getEntriesByType('resource').map((entry) => ({
    name: entry.name,
    initiatorType: entry.initiatorType,
    startTimeMs: entry.startTime,
    durationMs: entry.duration,
    responseEndMs: entry.responseEnd,
    transferSize: entry.transferSize,
    encodedBodySize: entry.encodedBodySize,
    decodedBodySize: entry.decodedBodySize,
    nextHopProtocol: entry.nextHopProtocol
  }));
}

function planLayerFacts(runtime = state.runtime) {
  if (!runtime) throw new Error('Facility runtime is not mounted.');
  const svg = runtime.workspace.planView.querySelector('svg');
  if (!svg) throw new Error('The actual top-plan adapter has no SVG.');
  const placementElements = Array.from(
    svg.querySelectorAll('[data-layer="placements"] [data-placement-id]')
  );
  const zoneElements = Array.from(
    svg.querySelectorAll('[data-layer="zones"] [data-zone-id]')
  );
  const routeElements = Array.from(
    svg.querySelectorAll('[data-layer="routes"] [data-route-id]')
  );
  const routeCorridors = routeElements.map((element) => ({
    routeId: element.getAttribute('data-route-id'),
    strokeWidth: Number(element.getAttribute('stroke-width')),
    pointCount: String(element.getAttribute('points') || '')
      .trim().split(/\s+/).filter(Boolean).length
  }));
  const accessibleLabels = placementElements.concat(zoneElements)
    .map((element) => element.getAttribute('aria-label'))
    .filter(Boolean);
  const visibleTextLabels = svg.querySelectorAll('text').length;
  const placementClearanceElements = svg.querySelectorAll(
    '[data-clearance-id], [data-clearance-volume-id]'
  ).length;
  return {
    layoutCounts: {
      placements: state.layout.placements.length,
      zones: state.layout.zones.length,
      routes: state.layout.routes.length
    },
    renderedCounts: {
      placements: placementElements.length,
      zones: zoneElements.length,
      routes: routeElements.length
    },
    labels: {
      accessibilityLabelsSupported: true,
      accessibilityLabelCount: accessibleLabels.length,
      visibleTextLabelsSupported: visibleTextLabels > 0,
      visibleTextLabelCount: visibleTextLabels,
      unavailableReason: visibleTextLabels > 0
        ? null
        : 'TopPlanAdapter currently exposes labels through aria-label only.'
    },
    clearances: {
      routeCorridorsSupported: routeCorridors.length > 0,
      routeCorridorCount: routeCorridors.length,
      routeCorridors,
      placementClearanceVolumesSupported: placementClearanceElements > 0,
      placementClearanceVolumeCount: placementClearanceElements,
      unavailableReason: placementClearanceElements > 0
        ? null
        : (
          'TopPlanAdapter does not currently render per-placement clearance ' +
          'volume elements; no timing is fabricated.'
        )
    },
    layerOrder: Array.from(svg.querySelectorAll(':scope > g')).map(
      (element) => element.getAttribute('data-layer')
    ).filter(Boolean)
  };
}

function snapshot(runtime = state.runtime) {
  if (!runtime) return null;
  const sessionState = runtime.session.getState();
  const three = runtime.three.getDiagnostics();
  const top = runtime.workspace.topAdapter.getDiagnostics();
  return {
    runtimeId: runtime.runtimeId,
    profile: runtime.profile,
    moduleProof: {
      workspaceApiVersion: runtime.workspace.getState().apiVersion,
      workspaceConstructor: runtime.workspace.constructor.name,
      topAdapterType: top.type,
      threeAdapterStatus: three.status,
      sessionApiVersion: sessionState.apiVersion,
      actualWorkspace: (
        runtime.workspace instanceof WorkspaceRuntime.Workspace
      ),
      actualTopPlanAdapter: (
        runtime.workspace.topAdapter instanceof LayoutRuntime.TopPlanAdapter
      ),
      actualThreeAdapter: (
        typeof runtime.three.setScene === 'function'
        && typeof runtime.three.pick === 'function'
        && typeof runtime.three.getDiagnostics === 'function'
      )
    },
    selection: sessionState.selection.slice(),
    plan: planLayerFacts(runtime),
    topDiagnostics: top,
    threeDiagnostics: three,
    renderer: rendererMetrics(runtime),
    rendererPool: rendererPool.getDiagnostics(),
    dom: {
      workspaceRoots: root.querySelectorAll('[data-facility-workspace]').length,
      canvases: root.querySelectorAll('canvas').length,
      planSvgs: root.querySelectorAll('.ip-flw-plan-view svg').length
    },
    lifecycleTracker: {
      activeObserverTargets: tracker.activeObserverTargets,
      observerInstances: tracker.observerInstances,
      activeAdapterFrames: tracker.activeAdapterFrames.size
    }
  };
}

async function mount(options = {}) {
  if (state.runtime) await destroyRuntime();
  const profile = options.profile === 'proxy' ? 'proxy' : 'full-detail';
  state.runtimeSequence += 1;
  const runtimeId = `facility-release-runtime-${state.runtimeSequence}`;
  performance.clearResourceTimings();
  const loadStartedAtMs = performance.now();
  const session = createSession();
  const stage = createStageRecorder(profile, state.catalog[0]);
  const rendererRecord = { renderer: null };
  const three = ThreeRuntime.createThreeAdapter({
    THREE,
    OrbitControls,
    GLTFLoader,
    ResizeObserver: TrackedResizeObserver,
    requestAnimationFrame: trackedRequestAnimationFrame,
    cancelAnimationFrame: trackedCancelAnimationFrame,
    rendererFactory() {
      return createRenderer(rendererRecord);
    },
    rendererPool,
    onRendererReady(renderer) {
      rendererRecord.renderer = renderer;
    },
    assetResolver: stage.resolver,
    pixelRatio: 1,
    clearColor: 0xd7e0e6,
    logger: { warn() {} }
  });
  const workspace = WorkspaceRuntime.createWorkspace({
    root,
    session,
    assetCatalog: clone(state.catalog),
    layoutRuntime: LayoutRuntime,
    threeAdapter: three,
    topPlanOptions: {
      ResizeObserver: TrackedResizeObserver,
      padding: 24
    },
    gridSize: 0.5,
    commandIcons: {
      select: 'V',
      pan: 'H',
      'rectangle-zone': 'RZ',
      'polygon-zone': 'PZ',
      rotate: '90',
      duplicate: 'D',
      delete: 'X',
      lock: 'L',
      undo: 'U',
      redo: 'Y',
      fit: 'F',
      'auto-arrange': 'A',
      save: 'S'
    }
  });
  state.runtime = {
    runtimeId,
    profile,
    session,
    workspace,
    three,
    rendererRecord,
    stageRecords: stage.records,
    loadStartedAtMs,
    loadEndedAtMs: null
  };
  await workspace.controller.ready();
  workspace.controller.fit();
  await settle(4);
  state.runtime.loadEndedAtMs = performance.now();
  const facts = planLayerFacts();
  const diagnostics = three.getDiagnostics();
  const expectedStages = ['manifest', 'footprint', 'proxy', 'overview', 'detail'];
  if (stage.records.map((entry) => entry.stage).join('|')
      !== expectedStages.join('|')) {
    throw new Error('Progressive asset stages did not execute in contract order.');
  }
  if (profile === 'full-detail'
      && expectedStages.some((name) => {
        const record = stage.records.find((entry) => entry.stage === name);
        return !record || record.status !== 'resolved';
      })) {
    throw new Error('A required progressive full-detail stage did not resolve.');
  }
  if (facts.renderedCounts.placements !== state.layout.placements.length
      || facts.renderedCounts.zones !== state.layout.zones.length
      || facts.renderedCounts.routes !== state.layout.routes.length) {
    throw new Error('The actual top-plan adapter did not render every P4 layer.');
  }
  if (diagnostics.degraded || diagnostics.status !== 'ready') {
    throw new Error('The actual Three adapter did not reach ready status.');
  }
  return {
    load: {
      startedAtMs: loadStartedAtMs,
      endedAtMs: state.runtime.loadEndedAtMs,
      totalDurationMs: state.runtime.loadEndedAtMs - loadStartedAtMs,
      stages: clone(stage.records),
      resources: resourceEntries()
    },
    snapshot: snapshot(),
    browser: browserEnvironment(),
    webgl: webglInformation()
  };
}

async function destroyRuntime() {
  if (!state.runtime) {
    return {
      destroyed: false,
      workspaceRoots: root.querySelectorAll('[data-facility-workspace]').length,
      canvases: root.querySelectorAll('canvas').length,
      planSvgs: root.querySelectorAll('svg').length,
      activeObserverTargets: tracker.activeObserverTargets,
      activeAdapterFrames: tracker.activeAdapterFrames.size
    };
  }
  if (state.frameCapture) stopFrameCapture();
  const runtime = state.runtime;
  const before = snapshot(runtime);
  const destroyed = runtime.workspace.destroy();
  state.runtime = null;
  await nextFrame();
  await nextFrame();
  return {
    destroyed,
    before,
    workspaceRoots: root.querySelectorAll('[data-facility-workspace]').length,
    canvases: root.querySelectorAll('canvas').length,
    planSvgs: root.querySelectorAll('svg').length,
    rootChildren: root.children.length,
    activeObserverTargets: tracker.activeObserverTargets,
    activeAdapterFrames: tracker.activeAdapterFrames.size,
    rendererPool: rendererPool.getDiagnostics(),
    threeAfter: runtime.three.getDiagnostics()
  };
}

function longTaskCollector() {
  if (!window.PerformanceObserver
      || !PerformanceObserver.supportedEntryTypes
      || !PerformanceObserver.supportedEntryTypes.includes('longtask')) {
    throw new Error('PerformanceObserver long-task entries are unavailable.');
  }
  const entries = [];
  const observer = new PerformanceObserver((list) => {
    list.getEntries().forEach((entry) => {
      entries.push({
        startTimeMs: entry.startTime,
        durationMs: entry.duration,
        name: entry.name
      });
    });
  });
  observer.observe({ type: 'longtask', buffered: false });
  return {
    stop() {
      observer.takeRecords().forEach((entry) => {
        entries.push({
          startTimeMs: entry.startTime,
          durationMs: entry.duration,
          name: entry.name
        });
      });
      observer.disconnect();
      return entries;
    }
  };
}

async function runPlanLoop(durationMs, collect) {
  const runtime = state.runtime;
  runtime.workspace._setViewMode('plan');
  const top = runtime.workspace.topAdapter;
  const placementIds = state.layout.placements.map(
    (placement) => placement.placementId
  );
  const frameIntervalsMs = [];
  const callbackDurationsMs = [];
  let lastTimestamp = null;
  let frameIndex = 0;
  const startedAtMs = performance.now();
  return new Promise((resolve) => {
    function tick(timestamp) {
      if (lastTimestamp !== null && collect) {
        frameIntervalsMs.push(timestamp - lastTimestamp);
      }
      lastTimestamp = timestamp;
      const callbackStarted = performance.now();
      const direction = frameIndex % 120 < 60 ? 1 : -1;
      top.panByPixels(direction * 0.7, direction * 0.35);
      if (frameIndex % 12 === 0) {
        const rect = top.svg.getBoundingClientRect();
        top.zoomAt({
          clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2
        }, frameIndex % 24 === 0 ? 1.008 : 1 / 1.008);
      }
      if (frameIndex % 30 === 0) {
        top.setSelection(
          placementIds[(frameIndex / 30) % placementIds.length | 0]
        );
      }
      if (collect) {
        callbackDurationsMs.push(performance.now() - callbackStarted);
      }
      frameIndex += 1;
      if (performance.now() - startedAtMs < durationMs) {
        nativeRequestAnimationFrame(tick);
      } else {
        top.fit();
        resolve({
          wallDurationMs: performance.now() - startedAtMs,
          frameIntervalsMs,
          callbackDurationsMs,
          frameCount: frameIndex
        });
      }
    }
    nativeRequestAnimationFrame(tick);
  });
}

async function runPlanFrames(options) {
  if (!state.runtime) throw new Error('Facility runtime is not mounted.');
  const warmupMs = Number(options && options.warmupMs || 0);
  const durationMs = Number(options && options.durationMs || 0);
  if (!(durationMs > 0) || warmupMs < 0) {
    throw new Error('Plan frame durations are invalid.');
  }
  if (warmupMs) await runPlanLoop(warmupMs, false);
  const collector = longTaskCollector();
  const before = snapshot();
  const measured = await runPlanLoop(durationMs, true);
  const longTasks = collector.stop();
  const after = snapshot();
  return {
    before,
    after,
    ...measured,
    longTasks,
    layerFacts: planLayerFacts()
  };
}

function runPlanRenderLatency(options) {
  if (!state.runtime) throw new Error('Facility runtime is not mounted.');
  const warmups = Number(options && options.warmups || 0);
  const iterations = Number(options && options.iterations || 0);
  if (!Number.isInteger(warmups) || !Number.isInteger(iterations)
      || warmups < 0 || iterations < 1) {
    throw new Error('Plan render iteration counts are invalid.');
  }
  const top = state.runtime.workspace.topAdapter;
  const samples = [];
  for (let index = 0; index < warmups + iterations; index += 1) {
    const startedAtMs = performance.now();
    top.setLayout(clone(state.layout));
    const endedAtMs = performance.now();
    if (index >= warmups) {
      samples.push({
        iteration: index - warmups,
        startedAtMs,
        endedAtMs,
        durationMs: endedAtMs - startedAtMs
      });
    }
  }
  return {
    discardedWarmups: warmups,
    samples,
    layerFacts: planLayerFacts(),
    diagnostics: top.getDiagnostics()
  };
}

function clientPointForNdc(ndc) {
  const canvas = state.runtime.workspace.threeView.querySelector('canvas');
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  return {
    clientX: rect.left + ((ndc.x + 1) / 2) * rect.width,
    clientY: rect.top + ((1 - ndc.y) / 2) * rect.height
  };
}

function findPickPoint(preferredPlacementId = '') {
  if (!state.runtime) throw new Error('Facility runtime is not mounted.');
  const hits = [];
  const steps = 72;
  for (let row = 2; row < steps - 2; row += 1) {
    const y = 1 - (row / (steps - 1)) * 2;
    for (let column = 2; column < steps - 2; column += 1) {
      const x = (column / (steps - 1)) * 2 - 1;
      const hit = state.runtime.three.pick({ normalized: true, x, y });
      if (!hit) continue;
      const point = {
        placementId: hit.placementId,
        ndc: { x, y },
        ...clientPointForNdc({ x, y })
      };
      if (hit.placementId === preferredPlacementId) return point;
      hits.push(point);
    }
  }
  return hits[0] || null;
}

function runPicking(options) {
  if (!state.runtime) throw new Error('Facility runtime is not mounted.');
  const warmups = Number(options && options.warmups || 0);
  const iterations = Number(options && options.iterations || 0);
  const point = findPickPoint(options && options.preferredPlacementId);
  if (!point) throw new Error('No real 3D placement is raycastable.');
  const samples = [];
  for (let index = 0; index < warmups + iterations; index += 1) {
    const startedAtMs = performance.now();
    const hit = state.runtime.three.pick({
      normalized: true,
      x: point.ndc.x,
      y: point.ndc.y
    });
    const endedAtMs = performance.now();
    if (!hit || hit.placementId !== point.placementId) {
      throw new Error('The real Three adapter returned an unstable pick result.');
    }
    if (index >= warmups) {
      samples.push({
        iteration: index - warmups,
        startedAtMs,
        endedAtMs,
        durationMs: endedAtMs - startedAtMs,
        placementId: hit.placementId,
        instanceId: hit.instanceId
      });
    }
  }
  return {
    discardedWarmups: warmups,
    point,
    samples
  };
}

async function prepareThreeInteraction() {
  if (!state.runtime) throw new Error('Facility runtime is not mounted.');
  state.runtime.workspace._setViewMode('3d');
  state.runtime.workspace.controller.fit();
  await settle(5);
  const canvas = state.runtime.workspace.threeView.querySelector('canvas');
  if (!canvas) throw new Error('The actual Three adapter has no canvas.');
  const rect = canvas.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) {
    throw new Error('The actual Three canvas is not visible.');
  }
  const pickPoint = findPickPoint('pl-rack-06');
  if (!pickPoint) throw new Error('No pick point is available for selection.');
  return {
    canvasRect: rect.toJSON(),
    pickPoint,
    camera: clone(state.runtime.three.getDiagnostics().camera),
    renderer: rendererMetrics()
  };
}

function startFrameCapture() {
  if (state.frameCapture) {
    throw new Error('A frame capture is already active.');
  }
  const collector = longTaskCollector();
  const capture = {
    frameIntervalsMs: [],
    startedAtMs: performance.now(),
    lastTimestamp: null,
    frameId: null,
    before: snapshot(),
    collector
  };
  function tick(timestamp) {
    if (capture.lastTimestamp !== null) {
      capture.frameIntervalsMs.push(timestamp - capture.lastTimestamp);
    }
    capture.lastTimestamp = timestamp;
    capture.frameId = nativeRequestAnimationFrame(tick);
  }
  capture.frameId = nativeRequestAnimationFrame(tick);
  state.frameCapture = capture;
  return {
    startedAtMs: capture.startedAtMs,
    before: capture.before
  };
}

function stopFrameCapture() {
  const capture = state.frameCapture;
  if (!capture) throw new Error('No frame capture is active.');
  nativeCancelAnimationFrame(capture.frameId);
  state.frameCapture = null;
  return {
    startedAtMs: capture.startedAtMs,
    endedAtMs: performance.now(),
    wallDurationMs: performance.now() - capture.startedAtMs,
    frameIntervalsMs: capture.frameIntervalsMs.slice(),
    frameCount: capture.frameIntervalsMs.length + 1,
    longTasks: capture.collector.stop(),
    before: capture.before,
    after: snapshot()
  };
}

async function idleSample(quietWindowMs) {
  const three = state.runtime.three;
  const before = three.getDiagnostics().demandRendering;
  const startedAtMs = performance.now();
  three.invalidate();
  let stoppedAtMs = null;
  let last = null;
  const deadline = startedAtMs + 1500;
  while (performance.now() < deadline) {
    await nextFrame();
    last = three.getDiagnostics().demandRendering;
    if (last.pendingFrame === false
        && last.renderedFrames > before.renderedFrames
        && tracker.activeAdapterFrames.size === 0) {
      stoppedAtMs = performance.now();
      break;
    }
  }
  if (stoppedAtMs === null) {
    throw new Error('Demand rendering did not stop within 1500 ms.');
  }
  const stableBefore = three.getDiagnostics().demandRendering;
  await delay(quietWindowMs);
  const stableAfter = three.getDiagnostics().demandRendering;
  if (stableBefore.renderRequests !== stableAfter.renderRequests
      || stableBefore.renderedFrames !== stableAfter.renderedFrames
      || stableAfter.pendingFrame !== false
      || tracker.activeAdapterFrames.size !== 0) {
    throw new Error('The Three adapter continued rendering while idle.');
  }
  return {
    startedAtMs,
    stoppedAtMs,
    stopLatencyMs: stoppedAtMs - startedAtMs,
    quietWindowMs,
    before,
    atStop: last,
    stableBefore,
    stableAfter,
    activeAdapterFrames: tracker.activeAdapterFrames.size
  };
}

async function measureIdleStop(options) {
  if (!state.runtime) throw new Error('Facility runtime is not mounted.');
  const warmups = Number(options && options.warmups || 0);
  const iterations = Number(options && options.iterations || 0);
  const quietWindowMs = Number(options && options.quietWindowMs || 300);
  if (!Number.isInteger(warmups) || !Number.isInteger(iterations)
      || warmups < 0 || iterations < 1 || quietWindowMs < 1) {
    throw new Error('Idle-render measurement options are invalid.');
  }
  for (let index = 0; index < warmups; index += 1) {
    await idleSample(quietWindowMs);
  }
  const samples = [];
  for (let index = 0; index < iterations; index += 1) {
    samples.push({
      iteration: index,
      ...(await idleSample(quietWindowMs))
    });
  }
  return {
    discardedWarmups: warmups,
    samples
  };
}

async function remountOnce() {
  if (!state.runtime) {
    throw new Error('A remount requires an existing mounted runtime.');
  }
  const runtime = state.runtime;
  const before = snapshot(runtime);
  const didSuspend = runtime.workspace.suspend();
  await nextFrame();
  await nextFrame();
  const suspended = {
    suspended: didSuspend,
    before,
    workspaceRoots: root.querySelectorAll('[data-facility-workspace]').length,
    canvases: root.querySelectorAll('canvas').length,
    planSvgs: root.querySelectorAll('svg').length,
    rootChildren: root.children.length,
    activeObserverTargets: tracker.activeObserverTargets,
    activeAdapterFrames: tracker.activeAdapterFrames.size,
    rendererPool: rendererPool.getDiagnostics(),
    threeAfter: runtime.three.getDiagnostics()
  };
  const didResume = runtime.workspace.resume(root);
  if (!didSuspend || !didResume) {
    throw new Error('Facility workspace suspend/resume transition failed.');
  }
  state.runtime.workspace._setViewMode('3d');
  state.runtime.workspace.controller.fit();
  await settle(3);
  if (suspended.workspaceRoots !== 0
      || suspended.canvases !== 0
      || suspended.planSvgs !== 0
      || suspended.rootChildren !== 0
      || suspended.activeObserverTargets !== 0
      || suspended.activeAdapterFrames !== 0) {
    throw new Error('Facility workspace suspension leaked active browser state.');
  }
  return {
    runtimeId: state.runtime.runtimeId,
    lifecycleMode: 'bounded-suspend-resume',
    suspended,
    mounted: snapshot()
  };
}

async function boot() {
  assertRuntimeModules();
  [state.layout, state.catalog] = await Promise.all([
    fetch(LAYOUT_URL, { cache: 'no-store' }).then(
      (response) => responseJson(response, 'P4 layout')
    ),
    fetch(CATALOG_URL, { cache: 'no-store' }).then(
      (response) => responseJson(response, 'P4 asset catalog')
    )
  ]);
  if (!state.layout || state.layout.schemaVersion !== 1
      || !Array.isArray(state.layout.placements)
      || !Array.isArray(state.layout.zones)
      || !Array.isArray(state.layout.routes)) {
    throw new Error('P4 Facility layout fixture is invalid.');
  }
  if (!Array.isArray(state.catalog) || state.catalog.length !== 1) {
    throw new Error('P4 Facility asset catalog is invalid.');
  }
  state.status = 'ready';
}

const api = {
  get state() {
    return {
      status: state.status,
      errors: state.errors.slice(),
      pageErrors: state.pageErrors.slice()
    };
  },
  mount,
  destroyRuntime,
  snapshot,
  planLayerFacts,
  runPlanFrames,
  runPlanRenderLatency,
  prepareThreeInteraction,
  startFrameCapture,
  stopFrameCapture,
  runPicking,
  findPickPoint,
  measureIdleStop,
  remountOnce,
  preciseMemory: memorySnapshot,
  browserEnvironment,
  webglInformation,
  rendererMetrics
};
window.facilityReleasePerformance = api;

boot().catch((error) => {
  const message = String(error && error.stack || error);
  state.status = 'error';
  state.errors.push(message);
  root.replaceChildren();
  const failure = document.createElement('pre');
  failure.className = 'benchmark-error';
  failure.textContent = message;
  root.appendChild(failure);
});
