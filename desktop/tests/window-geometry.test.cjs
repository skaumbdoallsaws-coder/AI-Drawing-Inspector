'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { readWindowGeometry } = require('../tools/window-geometry.cjs');

function fixture() {
  const bounds = { x: -1920, y: 0, width: 1440, height: 824 };
  const secondary = { id: 2, bounds: { x: -1920, y: 0, width: 1536, height: 864 },
    workArea: { x: -1920, y: 0, width: 1536, height: 824 }, scaleFactor: 1.25, rotation: 0, internal: false };
  const primary = { ...secondary, id: 1, bounds: { x: 0, y: 0, width: 1920, height: 1080 }, scaleFactor: 1 };
  const window = {
    getBounds: () => bounds, getSize: () => [1440, 824], getContentSize: () => [1426, 764],
    getContentBounds: () => ({ x: -1913, y: 53, width: 1426, height: 764 }),
    getNormalBounds: () => bounds, getMinimumSize: () => [800, 600], getMaximumSize: () => [0, 0],
    isDestroyed: () => false, isVisible: () => false, isMinimized: () => false, isMaximized: () => false,
    isFullScreen: () => false, isMenuBarVisible: () => true, isMenuBarAutoHide: () => false,
    webContents: { getZoomFactor: () => 1 },
  };
  const screen = {
    getDisplayMatching: rect => { assert.deepEqual(rect, bounds); return secondary; },
    getPrimaryDisplay: () => primary, getAllDisplays: () => [primary, secondary],
    dipToScreenRect: (win, rect) => {
      assert.equal(win, window); assert.deepEqual(rect, bounds);
      return { x: -2400, y: 0, width: 1800, height: 1030 };
    },
  };
  return { window, screen, requestedOuterSize: [1440, 960] };
}

test('records work-area mismatch and matching monitor/DPI without replacing requested dimensions', () => {
  const f = fixture(), result = readWindowGeometry(f);
  assert.deepEqual(result.requestedOuterSizeDip, [1440, 960]);
  assert.deepEqual(result.actualOuterSizeDip, [1440, 824]);
  assert.deepEqual(result.outerSizeDeltaDip, [0, -136]);
  assert.equal(result.requestedSizeFitsWorkArea, false);
  assert.equal(result.matchingDisplay.id, 2); assert.equal(result.primaryDisplay.id, 1);
  assert.equal(result.matchingDisplay.scaleFactor, 1.25);
  assert.equal(result.matchingDisplay.boundsDip.x, -1920);
  assert.deepEqual(result.physicalWindowBounds, { x: -2400, y: 0, width: 1800, height: 1030 });
  assert.equal(result.state.isMenuBarVisible, true); assert.deepEqual(result.errors, {});
  assert.deepEqual(JSON.parse(JSON.stringify(result)), result, 'Diagnostics contain JSON values even without nativeOrigin on Windows');
  // The diagnostic must not retain mutable native rectangles/request arrays.
  f.requestedOuterSize[0] = 1; f.window.getBounds().width = 1;
  assert.equal(result.requestedOuterSizeDip[0], 1440); assert.equal(result.boundsDip.width, 1440);
});

test('unavailable native fields retain other measurements and serialize the diagnostic error', () => {
  const f = fixture();
  f.screen.dipToScreenRect = () => { throw new Error('conversion unavailable'); };
  f.window.getNormalBounds = () => { throw new Error('window is closing'); };
  const result = readWindowGeometry(f);
  assert.deepEqual(result.actualOuterSizeDip, [1440, 824]);
  assert.equal(result.normalBoundsDip, null); assert.equal(result.physicalWindowBounds, null);
  assert.equal(result.errors.normalBoundsDip, 'window is closing');
  assert.equal(result.errors.physicalWindowBounds, 'conversion unavailable');
  assert.equal(JSON.parse(JSON.stringify(result)).matchingDisplay.scaleFactor, 1.25);
});

test('destroyed-window and unavailable display reads cannot throw over a capture failure', () => {
  const result = readWindowGeometry({ window: { isDestroyed: () => true }, screen: {}, requestedOuterSize: [1440, 960] });
  assert.equal(result.actualOuterSizeDip, null); assert.equal(result.matchingDisplay, null);
  assert.equal(result.state.isDestroyed, true); assert.match(result.errors.actualOuterSizeDip, /unavailable/);
  assert.doesNotThrow(() => JSON.stringify(result));
});
