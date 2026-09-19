'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { planRenderingWindows, assertRenderingDisplay, validateRenderingWindowReport } = require('../tools/rendering-window-policy.cjs');

function display(width = 1536, height = 816) {
  return { id: 17, bounds: { x: 0, y: 0, width, height: height + 48 },
    workArea: { x: 0, y: 0, width, height }, scaleFactor: 1.25 };
}
function reportFor(value = display()) {
  const policy = JSON.parse(JSON.stringify(planRenderingWindows(value)));
  return { windowSizePolicy: policy,
    captures: {
      wide: { outerSize: { width: policy.wide[0], height: policy.wide[1] } },
      narrow: { outerSize: { width: policy.narrow[0], height: policy.narrow[1] } },
    }, referenceWideCapture: { requestedOuterSize: [1440, 960],
      ...(policy.exactWide ? { status: 'passed' } : { status: 'not-exercised',
        reason: 'The selected display work area cannot fit the nominal 1440x960 DIP window.' }) } };
}

test('1536x816 DIP work area produces 1440x816 wide and unchanged 900x700 narrow', () => {
  const plan = planRenderingWindows(display());
  assert.equal(plan.revision, 'work-area-v1');
  assert.deepEqual(plan.wide, [1440, 816]);
  assert.deepEqual(plan.narrow, [900, 700]);
  assert.deepEqual(plan.wideBounds, { x: 48, y: 0, width: 1440, height: 816 });
  assert.equal(plan.exactWide, false);
  assert.equal(plan.display.scaleFactor, 1.25);
});

test('large work area retains exact nominal windows without applying display scale', () => {
  const source = display(1920, 1040); source.scaleFactor = 2;
  const plan = planRenderingWindows(source);
  assert.deepEqual(plan.wide, [1440, 960]);
  assert.deepEqual(plan.narrow, [900, 700]);
  assert.deepEqual(plan.wideBounds, { x: 240, y: 40, width: 1440, height: 960 });
  assert.equal(plan.exactWide, true);
});

test('window bounds are centered on the selected negative-origin display', () => {
  const source = { id: 23, bounds: { x: -1920, y: -1080, width: 1920, height: 1080 },
    workArea: { x: -1920, y: -1050, width: 1920, height: 1050 }, scaleFactor: 1 };
  const plan = planRenderingWindows(source);
  assert.deepEqual(plan.wideBounds, { x: -1680, y: -1005, width: 1440, height: 960 });
});

test('fractional DIP dimensions are floored rather than converted to pixels', () => {
  const plan = planRenderingWindows(display(1536.9, 816.9));
  assert.deepEqual(plan.availableWorkArea, { x: 0, y: 0, width: 1536, height: 816 });
  assert.deepEqual(plan.wide, [1440, 816]);
  assert.deepEqual(plan.narrow, [900, 700]);
});

test('fractional negative origin uses an integer rectangle entirely inside the work area', () => {
  const source = { id: 3, bounds: { x: -1536.75, y: -20.5, width: 1536.75, height: 900.75 },
    workArea: { x: -1536.75, y: -10.25, width: 1536.25, height: 826.9 }, scaleFactor: 1.25 };
  const plan = planRenderingWindows(source);
  assert.deepEqual(plan.availableWorkArea, { x: -1536, y: -10, width: 1535, height: 826 });
  assert.deepEqual(plan.wideBounds, { x: -1489, y: -10, width: 1440, height: 826 });
  assert.equal(plan.wideBounds.x >= source.workArea.x, true);
  assert.equal(plan.wideBounds.y >= source.workArea.y, true);
  assert.equal(plan.wideBounds.x + plan.wideBounds.width <= source.workArea.x + source.workArea.width, true);
  assert.equal(plan.wideBounds.y + plan.wideBounds.height <= source.workArea.y + source.workArea.height, true);
});

for (const [name, mutate] of [
  ['missing identity', value => { delete value.id; }],
  ['invalid scale', value => { value.scaleFactor = 0; }],
  ['nonfinite dimension', value => { value.workArea.width = Infinity; }],
  ['negative dimension', value => { value.workArea.height = -1; }],
  ['work area outside display bounds', value => { value.workArea.x = -1; }],
  ['unsafe coordinates', value => { value.bounds.x = Number.MAX_VALUE; }],
]) {
  test(name + ' rejects instead of creating an adaptive plan', () => {
    const value = display(); mutate(value);
    assert.throws(() => planRenderingWindows(value), { code: 'rendering_display_invalid' });
  });
}

for (const [width, height] of [[799, 816], [1536, 599.9]]) {
  test('work area ' + width + 'x' + height + ' cannot satisfy the minimum', () => {
    assert.throws(() => planRenderingWindows(display(width, height)), { code: 'rendering_work_area_too_small' });
  });
}

test('insufficient distinct sizes fail without inventing a different narrow recipe', () => {
  assert.throws(() => planRenderingWindows(display(850, 650)), { code: 'rendering_insufficient_distinct_sizes' });
});

test('plan is deeply frozen, serializable, and independent from later input changes', () => {
  const input = display(), before = structuredClone(input), plan = planRenderingWindows(input);
  assert.deepEqual(input, before);
  assert.equal(Object.isFrozen(plan), true);
  assert.equal(Object.isFrozen(plan.display.workArea), true);
  assert.equal(Object.isFrozen(plan.wide), true);
  assert.equal(Object.isFrozen(plan.wideBounds), true);
  assert.throws(() => { plan.wide[1] = 960; }, TypeError);
  assert.throws(() => { plan.display.workArea.height = 960; }, TypeError);
  input.workArea.height = 960;
  assert.equal(plan.display.workArea.height, 816);
  assert.deepEqual(JSON.parse(JSON.stringify(plan)).wide, [1440, 816]);
});

for (const [name, mutate] of [
  ['identity', value => { value.id = 18; }],
  ['work area', value => { value.workArea.height = 800; }],
  ['scale factor', value => { value.scaleFactor = 1.5; }],
  ['display bounds', value => { value.bounds.width = 1600; }],
]) {
  test(name + ' change invalidates the pinned plan without adapting expected sizes', () => {
    const original = display(), plan = planRenderingWindows(original), current = structuredClone(original);
    mutate(current);
    assert.throws(() => assertRenderingDisplay(plan, current), { code: 'rendering_display_changed' });
    assert.deepEqual(plan.wide, [1440, 816]);
  });
}

test('unchanged display validates, including a serialized plan', () => {
  const source = display(), plan = planRenderingWindows(source);
  assert.equal(assertRenderingDisplay(plan, structuredClone(source)), true);
  assert.equal(assertRenderingDisplay(JSON.parse(JSON.stringify(plan)), source), true);
  assert.throws(() => assertRenderingDisplay({ revision: 'other' }, source), { code: 'rendering_plan_invalid' });
});

test('reports distinguish effective-size success from unexercised exact reference coverage', () => {
  assert.equal(validateRenderingWindowReport(reportFor()), true);
  assert.equal(validateRenderingWindowReport(reportFor(display(1920, 1040))), true);
});

for (const [name, mutate] of [
  ['missing policy', report => { delete report.windowSizePolicy; }],
  ['altered nominal size', report => { report.windowSizePolicy.nominalWide[1] = 816; }],
  ['altered centering', report => { report.windowSizePolicy.wideBounds.x = 0; }],
  ['altered effective size', report => { report.windowSizePolicy.wide[1] = 800; }],
  ['missing narrow capture', report => { delete report.captures.narrow; }],
  ['wrong captured wide size', report => { report.captures.wide.outerSize.height = 960; }],
  ['wrong captured narrow size', report => { report.captures.narrow.outerSize.width = 901; }],
  ['missing reference coverage', report => { delete report.referenceWideCapture; }],
  ['wrong reference request', report => { report.referenceWideCapture.requestedOuterSize = [1440, 816]; }],
  ['false exact reference success', report => { report.referenceWideCapture.status = 'passed'; }],
  ['missing work-area explanation', report => { delete report.referenceWideCapture.reason; }],
  ['unrelated explanation', report => { report.referenceWideCapture.reason = 'The diagnostic was skipped.'; }],
]) {
  test('report rejects ' + name, () => {
    const report = reportFor(); mutate(report);
    assert.throws(() => validateRenderingWindowReport(report), { code: 'rendering_window_report_invalid' });
  });
}

test('exact wide reference cannot be mislabeled as unexercised when captured size fits', () => {
  const report = reportFor(display(1920, 1040));
  report.referenceWideCapture.status = 'not-exercised';
  report.referenceWideCapture.reason = 'The work area was constrained.';
  assert.throws(() => validateRenderingWindowReport(report), { code: 'rendering_window_report_invalid' });
});
