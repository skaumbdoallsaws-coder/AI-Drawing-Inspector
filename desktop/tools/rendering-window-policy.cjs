'use strict';

const { isDeepStrictEqual } = require('node:util');

const REVISION = 'work-area-v1';
const NOMINAL_WIDE = [1440, 960];
const NOMINAL_NARROW = [900, 700];
const MINIMUM = [800, 600];

function fail(code, message, details = {}) {
  return Object.assign(new Error(message), { code, ...details });
}
function deepFreeze(value) {
  if (value && typeof value === 'object') {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}
function rectangle(value, label) {
  if (!value || !['x', 'y', 'width', 'height'].every(key => Number.isFinite(value[key]))
      || value.width <= 0 || value.height <= 0
      || !Number.isSafeInteger(Math.floor(value.x)) || !Number.isSafeInteger(Math.floor(value.y))
      || !Number.isSafeInteger(Math.ceil(value.x + value.width))
      || !Number.isSafeInteger(Math.ceil(value.y + value.height))) {
    throw fail('rendering_display_invalid', label + ' must be a finite positive DIP rectangle');
  }
  return { x: value.x, y: value.y, width: value.width, height: value.height };
}
function displayMetadata(display) {
  if (!display || !((typeof display.id === 'string' && display.id.length > 0 && display.id.length <= 128)
      || Number.isSafeInteger(display.id)) || !Number.isFinite(display.scaleFactor) || display.scaleFactor <= 0) {
    throw fail('rendering_display_invalid', 'Display identity and positive scale factor are required');
  }
  const bounds = rectangle(display.bounds, 'Display bounds');
  const workArea = rectangle(display.workArea, 'Display work area');
  if (workArea.x < bounds.x || workArea.y < bounds.y
      || workArea.x + workArea.width > bounds.x + bounds.width
      || workArea.y + workArea.height > bounds.y + bounds.height) {
    throw fail('rendering_display_invalid', 'Display work area must be inside display bounds');
  }
  return { id: display.id, bounds, workArea, scaleFactor: display.scaleFactor };
}

/**
 * Pure diagnostic policy. Electron display/window geometry is already DIP.
 * scaleFactor is recorded, never applied to geometry. Choose once before the
 * BrowserWindow constructor; do not recompute/adapt after a failed capture.
 */
function planRenderingWindows(display) {
  const metadata = displayMetadata(display);
  const area = metadata.workArea;
  // Use the largest integer-DIP rectangle wholly inside fractional work areas.
  // With integer origins this is simply floor(width) and floor(height).
  const availableWorkArea = { x: Math.ceil(area.x), y: Math.ceil(area.y),
    width: Math.floor(area.x + area.width) - Math.ceil(area.x),
    height: Math.floor(area.y + area.height) - Math.ceil(area.y) };
  if (availableWorkArea.width < MINIMUM[0] || availableWorkArea.height < MINIMUM[1]) {
    throw fail('rendering_work_area_too_small', 'Selected display cannot fit the minimum 800x600 DIP diagnostic window');
  }
  const wide = [Math.min(NOMINAL_WIDE[0], availableWorkArea.width), Math.min(NOMINAL_WIDE[1], availableWorkArea.height)];
  const narrow = [Math.min(NOMINAL_NARROW[0], availableWorkArea.width), Math.min(NOMINAL_NARROW[1], availableWorkArea.height)];
  if (isDeepStrictEqual(wide, narrow)) {
    throw fail('rendering_insufficient_distinct_sizes', 'Work area cannot provide distinct wide and narrow diagnostic windows');
  }
  const wideBounds = {
    x: availableWorkArea.x + Math.floor((availableWorkArea.width - wide[0]) / 2),
    y: availableWorkArea.y + Math.floor((availableWorkArea.height - wide[1]) / 2),
    width: wide[0], height: wide[1],
  };
  return deepFreeze({ revision: REVISION, display: metadata,
    nominalWide: [...NOMINAL_WIDE], nominalNarrow: [...NOMINAL_NARROW], minimum: [...MINIMUM],
    availableWorkArea, wide, narrow, wideBounds, exactWide: isDeepStrictEqual(wide, NOMINAL_WIDE) });
}

/** Reject a changed display; never modify/re-plan the existing expectations. */
function assertRenderingDisplay(plan, currentDisplay) {
  if (!plan || plan.revision !== REVISION || !plan.display) {
    throw fail('rendering_plan_invalid', 'A work-area-v1 rendering plan is required');
  }
  const original = displayMetadata(plan.display), current = displayMetadata(currentDisplay);
  const changed = [];
  for (const key of ['id', 'scaleFactor', 'bounds', 'workArea']) {
    if (!isDeepStrictEqual(original[key], current[key])) changed.push(key);
  }
  if (changed.length) throw fail('rendering_display_changed', 'Selected display changed after diagnostic planning', { changed });
  return true;
}

/** Validate report consistency; native execution evidence is verified separately. */
function validateRenderingWindowReport(report) {
  function invalid(message) { throw fail('rendering_window_report_invalid', message); }
  if (!report || !report.windowSizePolicy) invalid('Rendering report is missing its window size policy');
  let canonical;
  try { canonical = planRenderingWindows(report.windowSizePolicy.display); }
  catch (_error) { invalid('Rendering report contains an invalid display/window policy'); }
  if (!isDeepStrictEqual(report.windowSizePolicy, canonical)) invalid('Reported window policy does not match its canonical display plan');
  for (const kind of ['wide', 'narrow']) {
    const actual = report.captures?.[kind]?.outerSize;
    if (!actual || actual.width !== canonical[kind][0] || actual.height !== canonical[kind][1]) {
      invalid('Reported ' + kind + ' capture dimensions do not match the fixed window policy');
    }
  }
  const reference = report.referenceWideCapture;
  if (!reference || !isDeepStrictEqual(reference.requestedOuterSize, NOMINAL_WIDE)) {
    invalid('Report must identify nominal 1440x960 DIP reference coverage');
  }
  if (canonical.exactWide) {
    if (reference.status !== 'passed') invalid('Exact wide capture coverage must be reported as passed');
  } else if (reference.status !== 'not-exercised' || typeof reference.reason !== 'string'
      || !reference.reason.trim() || reference.reason.length > 1024 || !/work[\s-]*area/i.test(reference.reason)) {
    invalid('Constrained wide capture requires not-exercised reference coverage and a work-area explanation');
  }
  return true;
}

module.exports = { planRenderingWindows, assertRenderingDisplay, validateRenderingWindowReport };
