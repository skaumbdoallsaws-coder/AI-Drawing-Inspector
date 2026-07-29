import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const SITE_ID = 'site-a';
const LAYOUT_ID = 'fl-p5-authoring';
const API_URL = `/api/facility-layouts/${SITE_ID}/${LAYOUT_ID}`;
const CATALOG_URL = (
  '/tests/fixtures/facility_layout/rendering/p4-asset-catalog.json'
);
const OVERVIEW_URL = (
  '/generated/industrial_assets/p0_spike/rack_prototypes/' +
  'Pallet%20Racking_colored_overview_proxy.glb'
);
const CLEAR_COLOR = Object.freeze({ r: 215, g: 224, b: 230 });

const LayoutRuntime = window.InspectorProFacilityLayout;
const ThreeRuntime = window.InspectorProFacilityThree;
const SessionRuntime = window.InspectorProFacilitySession;
const WorkspaceRuntime = window.InspectorProFacilityWorkspace;

const evidence = {
  state: 'loading',
  errors: [],
  pageErrors: []
};
window.facilityP5Evidence = evidence;

window.addEventListener('error', (event) => {
  evidence.pageErrors.push(String(event.message || event.error || event));
});
window.addEventListener('unhandledrejection', (event) => {
  evidence.pageErrors.push(String(event.reason || event));
});

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
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function nextFrame() {
  return new Promise((resolve) => window.requestAnimationFrame(resolve));
}

function clientPoint(value) {
  return {
    clientX: Number(value.clientX === undefined ? value.x : value.clientX),
    clientY: Number(value.clientY === undefined ? value.y : value.clientY)
  };
}

function dragEvent(type, transfer, point) {
  const client = clientPoint(point);
  return new DragEvent(type, {
    bubbles: true,
    cancelable: true,
    dataTransfer: transfer,
    clientX: client.clientX,
    clientY: client.clientY
  });
}

function pointerEvent(type, point, options) {
  const client = clientPoint(point);
  return new PointerEvent(type, Object.assign({
    bubbles: true,
    cancelable: true,
    pointerId: 17,
    pointerType: 'mouse',
    button: 0,
    buttons: type === 'pointerup' ? 0 : 1,
    clientX: client.clientX,
    clientY: client.clientY
  }, options || {}));
}

function mouseEvent(type, point, options) {
  const client = clientPoint(point);
  return new MouseEvent(type, Object.assign({
    bubbles: true,
    cancelable: true,
    button: 0,
    buttons: 0,
    clientX: client.clientX,
    clientY: client.clientY
  }, options || {}));
}

function placement(layout, placementId) {
  return layout.placements.find(
    (item) => item.placementId === placementId
  ) || null;
}

function zone(layout, zoneId) {
  return layout.zones.find((item) => item.zoneId === zoneId) || null;
}

function position(layout, placementId) {
  const item = placement(layout, placementId);
  return item ? clone(item.transform.position) : null;
}

function pointDistance(left, right) {
  if (!left || !right) return null;
  const a = clientPoint(left);
  const b = clientPoint(right);
  return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value && typeof value === 'object') {
    return Object.keys(value).sort().reduce((result, key) => {
      result[key] = canonicalValue(value[key]);
      return result;
    }, {});
  }
  return value;
}

function jsonEqual(left, right) {
  return JSON.stringify(canonicalValue(left))
    === JSON.stringify(canonicalValue(right));
}

async function responseJson(response) {
  const body = await response.json();
  if (!response.ok) {
    const detail = body && body.error || {};
    const error = new Error(detail.message || `HTTP ${response.status}`);
    error.code = detail.code || `http_${response.status}`;
    error.details = detail.details || {};
    error.status = response.status;
    throw error;
  }
  return body;
}

const transportTrace = {
  previewRequests: [],
  previewResponses: [],
  previewRejections: [],
  applyRequests: [],
  applyResponses: [],
  reloadCount: 0
};

async function fetchLayout() {
  transportTrace.reloadCount += 1;
  return responseJson(await fetch(API_URL, { cache: 'no-store' }));
}

async function previewOperations(request) {
  transportTrace.previewRequests.push(clone(request));
  try {
    const response = await responseJson(await fetch(`${API_URL}/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    }));
    transportTrace.previewResponses.push(clone(response));
    return response;
  } catch (error) {
    transportTrace.previewRejections.push({
      code: error.code || null,
      message: error.message,
      status: error.status || null
    });
    throw error;
  }
}

async function applyOperations(request) {
  transportTrace.applyRequests.push(clone(request));
  const response = await responseJson(await fetch(API_URL, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  }));
  transportTrace.applyResponses.push(clone(response));
  return response;
}

function createAssetResolver() {
  return {
    loadManifest(request) {
      return clone(request.asset || {});
    },
    loadFootprint() {
      return null;
    },
    loadProxy() {
      return OVERVIEW_URL;
    },
    loadOverview() {
      return null;
    },
    loadDetail() {
      return null;
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
  renderer.setClearColor(0xd7e0e6, 1);
  return renderer;
}

let runtime = null;
let dragSequence = 0;

async function settle(turns) {
  const count = Number.isInteger(turns) ? turns : 6;
  if (runtime && runtime.workspace) {
    await runtime.workspace.whenIdle();
    if (runtime.workspace.controller
        && typeof runtime.workspace.controller.ready === 'function') {
      await runtime.workspace.controller.ready();
    }
  }
  for (let index = 0; index < count; index += 1) {
    await Promise.resolve();
    await nextFrame();
  }
}

function threeCanvas() {
  return runtime && runtime.workspace
    ? runtime.workspace.threeView.querySelector('canvas')
    : null;
}

function canvasPixelProbe() {
  const canvas = threeCanvas();
  if (!canvas) return { available: false, changedPixelCount: 0 };
  runtime.three.invalidate();
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
  let maximumDelta = 0;
  for (let offset = 0; offset < pixels.length; offset += 4) {
    const delta = (
      Math.abs(pixels[offset] - CLEAR_COLOR.r)
      + Math.abs(pixels[offset + 1] - CLEAR_COLOR.g)
      + Math.abs(pixels[offset + 2] - CLEAR_COLOR.b)
    );
    if (delta > 18) changed += 1;
    maximumDelta = Math.max(maximumDelta, delta);
  }
  return {
    available: true,
    width,
    height,
    changedPixelCount: changed,
    changedPixelFraction: changed / Math.max(1, width * height),
    maximumDelta
  };
}

function summarizeTransport() {
  const lastPreview = transportTrace.previewResponses[
    transportTrace.previewResponses.length - 1
  ] || null;
  const lastApply = transportTrace.applyResponses[
    transportTrace.applyResponses.length - 1
  ] || null;
  return {
    previewCount: transportTrace.previewRequests.length,
    previewRejections: clone(transportTrace.previewRejections),
    applyCount: transportTrace.applyRequests.length,
    reloadCount: transportTrace.reloadCount,
    lastPreviewCreatedIds: clone(
      lastPreview && lastPreview.createdIds || []
    ),
    lastPreviewFindingCount: (
      lastPreview && Array.isArray(lastPreview.findings)
        ? lastPreview.findings.length
        : 0
    ),
    lastApplyRevision: lastApply && lastApply.revision || null,
    lastApplyCreatedIds: clone(
      lastApply && lastApply.operationResult
        && lastApply.operationResult.createdIds || []
    )
  };
}

function summary() {
  if (!runtime) return null;
  const sessionState = runtime.session.getState();
  const workspaceState = runtime.workspace.getState();
  if (workspaceState.lastError) {
    workspaceState.lastError = {
      message: workspaceState.lastError.message || String(workspaceState.lastError),
      code: workspaceState.lastError.code || null
    };
  }
  if (workspaceState.session && workspaceState.session.lastError) {
    workspaceState.session.lastError = {
      message: workspaceState.session.lastError.message
        || String(workspaceState.session.lastError),
      code: workspaceState.session.lastError.code || null
    };
  }
  const warning = runtime.root.querySelector('.ip-flw-validation-notice');
  return {
    session: clone(sessionState),
    workspace: clone(workspaceState),
    top: runtime.top.getDiagnostics(),
    three: runtime.three.getDiagnostics(),
    transport: summarizeTransport(),
    rootRect: runtime.root.getBoundingClientRect().toJSON(),
    dom: {
      canvasCount: runtime.root.querySelectorAll('canvas').length,
      planSvgCount: runtime.root.querySelectorAll('.ip-flw-plan-view svg').length,
      planGhostCount: runtime.root.querySelectorAll(
        '[data-facility-ghost]'
      ).length,
      assetRows: runtime.root.querySelectorAll('.ip-flw-asset-row').length,
      toolbarCount: runtime.root.querySelectorAll('[role="toolbar"]').length,
      selectedTabCount: runtime.root.querySelectorAll(
        '[role="tab"][aria-selected="true"]'
      ).length,
      p6Warning: warning ? warning.textContent : null,
      p6WarningVisible: Boolean(
        warning && warning.getBoundingClientRect().height > 0
      ),
      sageElements: runtime.root.querySelectorAll(
        '[data-sage], [data-agent], .sage'
      ).length
    },
    tracker: {
      activeObserverTargets: tracker.activeObserverTargets,
      observerInstances: tracker.observerInstances,
      activeFrames: tracker.activeFrames.size
    },
    theme: {
      name: document.documentElement.dataset.theme,
      background: getComputedStyle(runtime.root).backgroundColor,
      color: getComputedStyle(runtime.root).color
    }
  };
}

function assetRow() {
  return runtime.root.querySelector(
    `[data-asset-id="${runtime.asset.assetId}"]`
  );
}

function startAssetDrag(point) {
  const row = assetRow();
  if (!row) throw new Error('P5 asset row is unavailable.');
  const transfer = new DataTransfer();
  row.dispatchEvent(dragEvent('dragstart', transfer, point));
  const text = transfer.getData(WorkspaceRuntime.ASSET_MIME);
  const payload = WorkspaceRuntime.parseAssetDragPayload(text);
  if (!payload) throw new Error('P5 asset drag payload was not created.');
  return { row, transfer, payload };
}

function ghostSnapshot(layoutBefore, payload) {
  const state = runtime.session.getState();
  return {
    payload: clone(payload),
    layoutUnchanged: jsonEqual(layoutBefore, state.layout),
    transientOnly: state.dirty === runtime.session.getState().dirty,
    sessionGhost: clone(state.ghostPlacement),
    topGhostActive: runtime.top.getDiagnostics().ghostActive,
    threeGhostActive: runtime.three.getDiagnostics().ghostActive,
    planGhostCount: runtime.root.querySelectorAll(
      '[data-facility-ghost]'
    ).length,
    overlayVisible: runtime.workspace.ghostOverlay.hidden === false
  };
}

async function dropAtClient(mode, point, expectedWorld) {
  runtime.workspace._setViewMode(mode);
  await settle(3);
  const before = runtime.session.getState();
  const beforeIds = new Set(
    before.layout.placements.map((item) => item.placementId)
  );
  const historyBefore = before.history.length;
  const started = startAssetDrag(point);
  const host = mode === 'plan'
    ? runtime.workspace.planView
    : runtime.workspace.threeView;
  host.dispatchEvent(dragEvent('dragover', started.transfer, point));
  await nextFrame();
  const ghost = ghostSnapshot(before.layout, started.payload);
  host.dispatchEvent(dragEvent('drop', started.transfer, point));
  await settle(8);
  const after = runtime.session.getState();
  const created = after.layout.placements.filter(
    (item) => !beforeIds.has(item.placementId)
  );
  if (created.length !== 1) {
    throw new Error(`Expected one placed asset, received ${created.length}.`);
  }
  const item = created[0];
  return {
    mode,
    payload: started.payload,
    expectedWorld: clone(expectedWorld),
    placementId: item.placementId,
    actualWorld: clone(item.transform.position),
    positionMode: item.positionMode,
    ghost,
    historyBefore,
    historyAfter: after.history.length,
    operationCount: after.history[after.history.length - 1].operationCount,
    placementIdWasClientSupplied: Boolean(
      after.operations[after.operations.length - 1]
        && after.operations[after.operations.length - 1]
          .placement.placementId
    ),
    previewCreatedIds: clone(
      transportTrace.previewResponses[
        transportTrace.previewResponses.length - 1
      ].createdIds || []
    )
  };
}

async function runAuthoringScenario() {
  runtime.workspace._setViewMode('plan');
  runtime.workspace._setToolMode('select');
  runtime.workspace.controller.fit();
  await settle(6);

  const marqueeStart = runtime.top.worldToClient({ x: 1, y: 0, z: 1 });
  const marqueeEnd = runtime.top.worldToClient({ x: 9, y: 0, z: 11 });
  runtime.workspace.planView.dispatchEvent(
    pointerEvent('pointerdown', marqueeStart)
  );
  runtime.workspace.planView.dispatchEvent(
    pointerEvent('pointerup', marqueeEnd)
  );
  const marqueeSelection = runtime.session.getState().selection.slice().sort();

  const beforeMove = runtime.session.getState();
  const autoBefore = position(beforeMove.layout, 'pl-p5-auto');
  const manualBefore = position(beforeMove.layout, 'pl-p5-manual');
  const target = runtime.workspace.planView.querySelector(
    '[data-placement-id="pl-p5-auto"]'
  );
  if (!target) throw new Error('Auto placement is not rendered in Plan view.');
  const moveStart = runtime.top.worldToClient(autoBefore);
  const moveEnd = runtime.top.worldToClient({
    x: autoBefore.x + 1.24,
    y: autoBefore.y,
    z: autoBefore.z + 0.76
  });
  target.dispatchEvent(pointerEvent('pointerdown', moveStart));
  target.dispatchEvent(pointerEvent('pointermove', moveEnd));
  target.dispatchEvent(pointerEvent('pointerup', moveEnd));
  await settle(6);
  const afterMove = runtime.session.getState();
  const moveBatch = afterMove.history[afterMove.history.length - 1];

  await runtime.workspace.executeCommand('undo');
  await settle(4);
  const afterUndo = runtime.session.getState();
  await runtime.workspace.executeCommand('redo');
  await settle(4);
  const afterRedo = runtime.session.getState();

  const beforeDuplicateIds = new Set(
    afterRedo.layout.placements.map((item) => item.placementId)
  );
  const duplicateHistoryBefore = afterRedo.history.length;
  await runtime.workspace.executeCommand('duplicate');
  await settle(6);
  const afterDuplicate = runtime.session.getState();
  const duplicateIds = afterDuplicate.layout.placements.filter(
    (item) => !beforeDuplicateIds.has(item.placementId)
  ).map((item) => item.placementId).sort();
  const duplicateBatch = afterDuplicate.history[
    afterDuplicate.history.length - 1
  ];
  await runtime.workspace.executeCommand('delete');
  await settle(6);
  const afterDelete = runtime.session.getState();
  const deleteBatch = afterDelete.history[afterDelete.history.length - 1];

  runtime.session.select('pl-p5-auto');
  const rotateHistoryBefore = runtime.session.getState().history.length;
  await runtime.workspace.executeCommand('rotate');
  await settle(5);
  const rotated = placement(
    runtime.session.getState().layout,
    'pl-p5-auto'
  );

  runtime.session.select('pl-p5-locked');
  const lockedBefore = clone(placement(
    runtime.session.getState().layout,
    'pl-p5-locked'
  ));
  const lockedHistoryBefore = runtime.session.getState().history.length;
  let lockedError = null;
  try {
    await runtime.session.moveSelected({ x: 1, y: 0, z: 0 });
  } catch (error) {
    lockedError = {
      code: error.code || null,
      message: error.message
    };
  }
  const lockedAfterState = runtime.session.getState();

  runtime.session.select('pl-p5-auto');
  await runtime.workspace.executeCommand('lock');
  await settle(4);
  const modeAfterLock = placement(
    runtime.session.getState().layout,
    'pl-p5-auto'
  ).positionMode;
  await runtime.workspace.executeCommand('lock');
  await settle(4);
  const modeAfterUnlock = placement(
    runtime.session.getState().layout,
    'pl-p5-auto'
  ).positionMode;

  runtime.workspace.controller.fit();
  await settle(4);
  await runtime.workspace.executeCommand('rectangle-zone');
  const rectangleStart = runtime.top.worldToClient({ x: 0, y: 0, z: 13 });
  const rectangleEnd = runtime.top.worldToClient({ x: 6, y: 0, z: 17 });
  runtime.workspace.planView.dispatchEvent(
    pointerEvent('pointerdown', rectangleStart)
  );
  runtime.workspace.planView.dispatchEvent(
    pointerEvent('pointermove', rectangleEnd)
  );
  runtime.workspace.planView.dispatchEvent(
    pointerEvent('pointerup', rectangleEnd)
  );
  await settle(5);
  const rectangleId = runtime.session.getState().selection[0];
  const rectangleBatch = runtime.session.getState().history[
    runtime.session.getState().history.length - 1
  ];

  const widthInput = runtime.workspace.propertiesBody.querySelector(
    '[data-property="width"]'
  );
  const depthInput = runtime.workspace.propertiesBody.querySelector(
    '[data-property="depth"]'
  );
  widthInput.value = '8';
  depthInput.value = '5';
  widthInput.dispatchEvent(new Event('change', {
    bubbles: true,
    cancelable: true
  }));
  await settle(5);
  const resizedRectangle = clone(zone(
    runtime.session.getState().layout,
    rectangleId
  ));

  await runtime.workspace.executeCommand('polygon-zone');
  const polygonPoints = [
    { x: 9, y: 0, z: 13 },
    { x: 14, y: 0, z: 13 },
    { x: 15, y: 0, z: 16 },
    { x: 11, y: 0, z: 18 }
  ];
  polygonPoints.forEach((world) => {
    runtime.workspace.planView.dispatchEvent(
      mouseEvent('click', runtime.top.worldToClient(world))
    );
  });
  runtime.root.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter',
    bubbles: true,
    cancelable: true
  }));
  await settle(5);
  const polygonId = runtime.session.getState().selection[0];
  const polygon = clone(zone(runtime.session.getState().layout, polygonId));

  return {
    marqueeSelection,
    move: {
      historyBefore: beforeMove.history.length,
      historyAfter: afterMove.history.length,
      operationCount: moveBatch.operationCount,
      autoBefore,
      autoAfter: position(afterMove.layout, 'pl-p5-auto'),
      autoPositionMode: placement(
        afterMove.layout,
        'pl-p5-auto'
      ).positionMode,
      manualBefore,
      manualAfter: position(afterMove.layout, 'pl-p5-manual')
    },
    undoRedo: {
      undoAuto: position(afterUndo.layout, 'pl-p5-auto'),
      undoManual: position(afterUndo.layout, 'pl-p5-manual'),
      redoAuto: position(afterRedo.layout, 'pl-p5-auto'),
      redoManual: position(afterRedo.layout, 'pl-p5-manual')
    },
    duplicateDelete: {
      historyBefore: duplicateHistoryBefore,
      historyAfterDuplicate: afterDuplicate.history.length,
      duplicateIds,
      duplicateOperationCount: duplicateBatch.operationCount,
      selectionAfterDuplicate: afterDuplicate.selection.slice().sort(),
      deleteOperationCount: deleteBatch.operationCount,
      duplicatesRemain: duplicateIds.some(
        (id) => Boolean(placement(afterDelete.layout, id))
      )
    },
    rotation: {
      historyBefore: rotateHistoryBefore,
      historyAfter: runtime.session.getState().history.length,
      quaternion: clone(rotated.transform.quaternion)
    },
    locking: {
      error: lockedError,
      historyUnchanged: (
        lockedHistoryBefore === lockedAfterState.history.length
      ),
      placementUnchanged: jsonEqual(
        lockedBefore,
        placement(lockedAfterState.layout, 'pl-p5-locked')
      ),
      modeAfterLock,
      modeAfterUnlock
    },
    zones: {
      rectangleId,
      rectangleOperationCount: rectangleBatch.operationCount,
      rectangleDimensions: WorkspaceRuntime.zoneDimensions(resizedRectangle),
      polygonId,
      polygonBoundary: polygon.boundary,
      polygonDimensions: WorkspaceRuntime.zoneDimensions(polygon)
    }
  };
}

async function preparePlanProjection() {
  runtime.workspace._setViewMode('plan');
  runtime.workspace.controller.fit();
  await settle(5);
  const target = { x: 11.24, y: 0, z: 8.26 };
  return {
    viewport: runtime.workspace.planView.getBoundingClientRect().toJSON(),
    target,
    targetClient: runtime.top.worldToClient(target),
    layout: clone(runtime.session.getState().layout)
  };
}

async function finishPlanProjection(prepared) {
  await settle(5);
  const layoutBeforeFit = clone(runtime.session.getState().layout);
  runtime.workspace.controller.fit();
  await settle(3);
  runtime.top.panByPixels(83, -47);
  let targetClient = runtime.top.worldToClient(prepared.target);
  runtime.top.zoomAt(targetClient, 1.65);
  targetClient = runtime.top.worldToClient(prepared.target);
  const expected = WorkspaceRuntime.snapWorldPoint(prepared.target, 0.5);
  const drop = await dropAtClient('plan', targetClient, expected);
  return {
    viewport: runtime.workspace.planView.getBoundingClientRect().toJSON(),
    projectionDelta: pointDistance(prepared.targetClient, targetClient),
    fitChangedLayout: !jsonEqual(
      layoutBeforeFit,
      prepared.layout
    ),
    drop
  };
}

async function prepareThreeProjection() {
  runtime.workspace._setViewMode('3d');
  runtime.workspace.controller.fit();
  await settle(8);
  const canvas = threeCanvas();
  const stableWorld = { x: 3, y: 0, z: 3 };
  return {
    canvasRect: canvas.getBoundingClientRect().toJSON(),
    stableWorld,
    stableClient: runtime.three.worldToClient(stableWorld),
    renderedFrames: runtime.three.getDiagnostics()
      .demandRendering.renderedFrames
  };
}

async function finishThreeProjection(prepared) {
  await settle(7);
  const canvas = threeCanvas();
  const rect = canvas.getBoundingClientRect();
  const afterProjection = runtime.three.worldToClient(prepared.stableWorld);
  const centerClient = {
    clientX: rect.left + rect.width * 0.54,
    clientY: rect.top + rect.height * 0.58
  };
  const floorPoint = runtime.three.worldPointOnFloor(centerClient, 0);
  if (!floorPoint) throw new Error('3D floor ray did not intersect.');
  const expected = WorkspaceRuntime.snapWorldPoint(floorPoint, 0.5);
  const drop = await dropAtClient('3d', centerClient, expected);
  const roundTrip = runtime.three.worldPointOnFloor(centerClient, 0);
  return {
    canvasRect: rect.toJSON(),
    projectionDelta: pointDistance(
      prepared.stableClient,
      afterProjection
    ),
    stableClientAfterOrbit: afterProjection,
    floorPoint,
    floorRoundTripError: Math.hypot(
      floorPoint.x - roundTrip.x,
      floorPoint.y - roundTrip.y,
      floorPoint.z - roundTrip.z
    ),
    renderedFrameDelta: (
      runtime.three.getDiagnostics().demandRendering.renderedFrames
      - prepared.renderedFrames
    ),
    drop
  };
}

async function runInvalidDrop() {
  runtime.workspace._setViewMode('3d');
  await settle(3);
  const canvas = threeCanvas();
  const rect = canvas.getBoundingClientRect();
  const candidates = [
    {
      clientX: rect.left + rect.width / 2,
      clientY: rect.top - rect.height * 4
    },
    {
      clientX: rect.left - rect.width * 4,
      clientY: rect.top - rect.height * 2
    },
    {
      clientX: rect.right + rect.width * 4,
      clientY: rect.top - rect.height * 2
    }
  ];
  let invalid = candidates.find(
    (point) => runtime.three.worldPointOnFloor(point, 0) === null
  ) || null;
  let method = 'dom-floor-miss';
  const before = runtime.session.getState();
  const started = startAssetDrag(invalid || candidates[0]);
  if (invalid) {
    runtime.workspace.threeView.dispatchEvent(
      dragEvent('dragover', started.transfer, invalid)
    );
    runtime.workspace.threeView.dispatchEvent(
      dragEvent('drop', started.transfer, invalid)
    );
  } else {
    method = 'normalized-floor-miss';
    invalid = { clientX: 0, clientY: 0 };
    runtime.workspace._handleDrop({
      normalized: true,
      x: 0,
      y: 4,
      dataTransfer: started.transfer,
      preventDefault() {}
    });
  }
  await settle(4);
  const after = runtime.session.getState();
  return {
    method,
    invalidProjection: (
      method === 'normalized-floor-miss'
      || runtime.three.worldPointOnFloor(invalid, 0) === null
    ),
    layoutUnchanged: jsonEqual(before.layout, after.layout),
    historyUnchanged: jsonEqual(before.history, after.history),
    ghostCleared: after.ghostPlacement === null
  };
}

async function saveAndReopen() {
  const before = clone(runtime.session.getState().layout);
  const operationCount = runtime.session.getState().operations.length;
  const applyBefore = transportTrace.applyRequests.length;
  const result = await runtime.workspace.executeCommand('save');
  await settle(7);
  const afterSave = runtime.session.getState();
  const reopenedReceipt = await fetchLayout();
  await runtime.session.reload(reopenedReceipt);
  await settle(7);
  const reopened = runtime.session.getState();
  const receipt = result && result.receipt || null;
  return {
    before,
    reopened: clone(reopened.layout),
    exact: jsonEqual(before, reopened.layout),
    operationCount,
    applyCalls: transportTrace.applyRequests.length - applyBefore,
    appliedOperationCount: transportTrace.applyRequests[
      transportTrace.applyRequests.length - 1
    ].operations.length,
    receiptRevision: receipt && receipt.revision || null,
    baseRevision: reopened.baseRevision,
    savedState: {
      dirty: afterSave.dirty,
      historyLength: afterSave.history.length
    },
    reopenedState: {
      dirty: reopened.dirty,
      historyLength: reopened.history.length,
      placementCount: reopened.layout.placements.length,
      zoneCount: reopened.layout.zones.length
    }
  };
}

async function runMobileProbe() {
  runtime.workspace._setViewMode('plan');
  runtime.workspace.controller.fit();
  await settle(5);
  const first = runtime.session.getState().layout.placements[0];
  const world = {
    x: first.transform.position.x + 2,
    y: 0,
    z: first.transform.position.z + 2
  };
  const client = runtime.top.worldToClient(world);
  const before = runtime.session.getState().layout;
  const started = startAssetDrag(client);
  runtime.workspace.planView.dispatchEvent(
    dragEvent('dragover', started.transfer, client)
  );
  await nextFrame();
  const ghost = ghostSnapshot(before, started.payload);
  runtime.workspace._cancelGhost();
  runtime.workspace._setViewMode('3d');
  runtime.workspace.controller.fit();
  await settle(7);
  const pixels = canvasPixelProbe();
  runtime.workspace._setViewMode('plan');
  await settle(3);
  const rootRect = runtime.root.getBoundingClientRect();
  return {
    ghost,
    pixels,
    theme: summary().theme,
    rootWidth: rootRect.width,
    rootScrollWidth: runtime.root.scrollWidth,
    planWidth: runtime.workspace.planView.getBoundingClientRect().width,
    assetPaneWidth: runtime.workspace.assetPane.getBoundingClientRect().width,
    warningVisible: summary().dom.p6WarningVisible
  };
}

async function disposeProbe() {
  if (!runtime) return null;
  const workspace = runtime.workspace;
  const three = runtime.three;
  const root = runtime.root;
  const before = summary();
  const first = workspace.destroy();
  const second = workspace.destroy();
  await nextFrame();
  await nextFrame();
  const after = {
    firstDestroy: first,
    secondDestroy: second,
    rootChildren: root.children.length,
    canvasCount: root.querySelectorAll('canvas').length,
    activeObserverTargets: tracker.activeObserverTargets,
    activeFrames: tracker.activeFrames.size,
    three: three.getDiagnostics()
  };
  return { before, after };
}

async function boot() {
  if (!LayoutRuntime || !ThreeRuntime || !SessionRuntime || !WorkspaceRuntime) {
    throw new Error('Facility Layout runtime modules are unavailable.');
  }
  if (typeof NativeResizeObserver !== 'function') {
    throw new Error('ResizeObserver is unavailable.');
  }
  const [initialReceipt, catalog] = await Promise.all([
    fetchLayout(),
    responseJson(await fetch(CATALOG_URL, { cache: 'no-store' }))
  ]);
  const asset = catalog[0];
  const session = SessionRuntime.createSession({
    previewOperations,
    applyOperations,
    reloadLayout: fetchLayout
  });
  session.load(initialReceipt);

  const three = ThreeRuntime.createThreeAdapter({
    THREE,
    OrbitControls,
    GLTFLoader,
    ResizeObserver: TrackedResizeObserver,
    requestAnimationFrame: trackedRequestAnimationFrame,
    cancelAnimationFrame: trackedCancelAnimationFrame,
    rendererFactory: createRenderer,
    assetResolver: createAssetResolver(),
    pixelRatio: 1,
    clearColor: 0xd7e0e6,
    logger: { warn() {} }
  });
  const root = document.getElementById('facility-workspace');
  const workspace = WorkspaceRuntime.createWorkspace({
    root,
    session,
    assetCatalog: catalog,
    layoutRuntime: LayoutRuntime,
    threeAdapter: three,
    topPlanOptions: {
      ResizeObserver: TrackedResizeObserver,
      padding: 24
    },
    gridSize: 0.5,
    createDragSessionId() {
      dragSequence += 1;
      return `p5-browser-drag-${String(dragSequence).padStart(3, '0')}`;
    },
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
      save: 'S'
    }
  });
  runtime = {
    asset,
    catalog,
    initialReceipt,
    root,
    session,
    workspace,
    top: workspace.topAdapter,
    three
  };
  await workspace.controller.ready();
  workspace.controller.fit();
  await settle(10);

  Object.assign(runtime, {
    settle,
    summary,
    runAuthoringScenario,
    preparePlanProjection,
    finishPlanProjection,
    prepareThreeProjection,
    finishThreeProjection,
    runInvalidDrop,
    saveAndReopen,
    runMobileProbe,
    canvasPixelProbe,
    disposeProbe
  });
  window.facilityP5 = runtime;
  evidence.state = 'ready';
}

boot().catch((error) => {
  const message = error && error.stack ? error.stack : String(error);
  evidence.state = 'error';
  evidence.errors.push(message);
  const root = document.getElementById('facility-workspace');
  root.innerHTML = '';
  const failure = document.createElement('pre');
  failure.className = 'boot-error';
  failure.textContent = message;
  root.appendChild(failure);
});
