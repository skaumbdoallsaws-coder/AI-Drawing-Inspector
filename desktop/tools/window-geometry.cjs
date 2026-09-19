'use strict';

// Read-only diagnostic data. Electron native bounds and display work areas use
// DIP; dipToScreenRect supplies separately labeled Windows physical pixels.
// Renderer CSS viewport/DPR are recorded by rendering-capture, not inferred here.
function readWindowGeometry({ window, screen, requestedOuterSize }) {
  const errors = {};
  const read = (name, getter) => {
    try { return getter(); }
    catch (error) { errors[name] = String(error?.message || error); return null; }
  };
  const invoke = (target, method, ...args) => {
    if (typeof target?.[method] !== 'function') throw new Error(method + ' is unavailable');
    return target[method](...args);
  };
  const rect = value => value ? ({ x: value.x ?? null, y: value.y ?? null,
    width: value.width ?? null, height: value.height ?? null }) : null;
  const pair = value => Array.isArray(value) ? value.slice(0, 2) : null;
  const display = value => value ? ({ id: value.id ?? null, boundsDip: rect(value.bounds), workAreaDip: rect(value.workArea),
    scaleFactor: value.scaleFactor ?? null, rotation: value.rotation ?? null, internal: value.internal ?? null,
    nativeOriginPixels: value.nativeOrigin ? { x: value.nativeOrigin.x ?? null, y: value.nativeOrigin.y ?? null } : null }) : null;
  const bounds = read('boundsDip', () => rect(invoke(window, 'getBounds')));
  const matching = read('matchingDisplay', () => {
    if (!bounds) throw new Error('Window bounds are unavailable');
    return display(invoke(screen, 'getDisplayMatching', bounds));
  });
  const result = {
    observedAt: new Date().toISOString(),
    units: { nativeWindow: 'DIP', displayBounds: 'DIP', physicalWindowBounds: 'screen pixels' },
    physicalWindowBoundsSource: 'screen.dipToScreenRect conversion; not an independent HWND measurement',
    requestedOuterSizeDip: pair(requestedOuterSize),
    actualOuterSizeDip: read('actualOuterSizeDip', () => pair(invoke(window, 'getSize'))),
    actualContentSizeDip: read('actualContentSizeDip', () => pair(invoke(window, 'getContentSize'))),
    boundsDip: bounds,
    contentBoundsDip: read('contentBoundsDip', () => rect(invoke(window, 'getContentBounds'))),
    normalBoundsDip: read('normalBoundsDip', () => rect(invoke(window, 'getNormalBounds'))),
    minimumSizeDip: read('minimumSizeDip', () => pair(invoke(window, 'getMinimumSize'))),
    maximumSizeDip: read('maximumSizeDip', () => pair(invoke(window, 'getMaximumSize'))),
    matchingDisplay: matching,
    primaryDisplay: read('primaryDisplay', () => display(invoke(screen, 'getPrimaryDisplay'))),
    displays: read('displays', () => invoke(screen, 'getAllDisplays').map(display)),
    physicalWindowBounds: read('physicalWindowBounds', () => {
      if (!bounds) throw new Error('Window bounds are unavailable');
      return rect(invoke(screen, 'dipToScreenRect', window, bounds));
    }),
    zoomFactor: read('zoomFactor', () => invoke(window?.webContents, 'getZoomFactor')),
    state: Object.fromEntries(['isDestroyed', 'isVisible', 'isMinimized', 'isMaximized', 'isFullScreen',
      'isMenuBarVisible', 'isMenuBarAutoHide'].map(method => [method, read(method, () => invoke(window, method))])),
    errors,
  };
  if (result.requestedOuterSizeDip && result.actualOuterSizeDip) {
    result.outerSizeDeltaDip = result.actualOuterSizeDip.map((value, index) => value - result.requestedOuterSizeDip[index]);
  }
  const work = matching?.workAreaDip;
  if (work && result.requestedOuterSizeDip) {
    // Dimension-only comparison; window placement is recorded separately.
    result.requestedSizeFitsWorkArea = result.requestedOuterSizeDip[0] <= work.width
      && result.requestedOuterSizeDip[1] <= work.height;
  }
  return result;
}

module.exports = { readWindowGeometry };
