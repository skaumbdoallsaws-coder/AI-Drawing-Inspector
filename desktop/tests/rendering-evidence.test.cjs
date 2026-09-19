'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { EVIDENCE_SCRIPT, assertRenderingEvidence, assertInputLockRechecks, collectChromeLayout, assertChromeLayout } = require('../src/rendering-evidence.cjs');

function layout(width = 886, height = 638) {
  const viewport = { x: 0, y: 0, width, height };
  const item = (id, x, y, w, h) => ({ id, visible: true, bounds: { x, y, width: w, height: h },
    clipBounds: { ...viewport }, labelBounds: [{ x: x + 4, y: y + 5, width: w - 8, height: 15 }], ancestorIds: [] });
  return { revision: 'chrome-layout-v1', viewport: { width, height }, violations: [],
    toolbar: { bounds: { x: 0, y: 0, width, height: 42 }, controls: [item('brand', 8, 4, 130, 32), item('search', 160, 4, 150, 32)] },
    tabbar: { bounds: { x: 286, y: 42, width: width - 332, height: 60 },
      tabs: ['drawing', '3dmodel', 'assembly', 'training', 'dfm', 'report', 'usage', 'sessions']
        .map((id, index) => item(id, 290 + index % 4 * 130, 44 + Math.floor(index / 4) * 28, 126, 26)) } };
}

function evidence() {
  return { title: 'InspectorPro', bodyChildren: 3, frozen: true, chromeLayout: layout(),
    lockEvidence: { uniqueBanner: true, unlockedRootCount: 0, totalRoots: 3 },
    preloadLockDiagnostics: { schemaVersion: 1, acknowledged: true, current: { allProtectedRootsLocked: true, protectedRootCount: 3 } }, desktopMarker: 'rendering-spike', banner: 'Preview', nodeExposed: false,
    capabilities: { schemaVersion: 1, mode: 'rendering-spike', interactive: false, researchBrowsing: false, managedBackend: false, durableWorkflowRecovery: false },
    markup: { kind: 'full-application', profileLabel: 'Profiles: 0', contextRibbonExists: true, errorText: '',
      elements: Object.fromEntries(['toolbar', 'main', 'viewport', 'tabs', 'content', 'upload', 'empty'].map(key => [key, { visible: true }])),
      tabs: ['drawing', '3dmodel', 'assembly', 'training', 'dfm', 'report', 'usage', 'sessions'].map(id => ({ id, selected: id === 'drawing' })) } };
}

test('rendering probe compiles; empty-library startup accepts no populated canvas or ribbon', () => {
  assert.doesNotThrow(() => new vm.Script(EVIDENCE_SCRIPT));
  assert.equal(assertRenderingEvidence(evidence(), 'full-application'), true);
});

for (const [label, mutate] of [
  ['banner-only page', item => { item.bodyChildren = 0; }],
  ['unlocked content', item => { item.frozen = false; }],
  ['unlocked native root behind a stale summary', item => { item.lockEvidence.unlockedRootCount = 1; }],
  ['duplicate banner ID', item => { item.lockEvidence.uniqueBanner = false; }],
  ['stale preload acknowledgment', item => { item.preloadLockDiagnostics.current.allProtectedRootsLocked = false; }],
  ['missing lock diagnostics', item => { delete item.preloadLockDiagnostics; }],
  ['different root counts across contexts', item => { item.preloadLockDiagnostics.current.protectedRootCount = 2; }],
  ['uninitialized profile API', item => { item.markup.profileLabel = 'Profiles: --'; }],
  ['persisted profile failure', item => { item.markup.errorText = 'Failed to load inspection profiles.'; }],
  ['missing workflow tab', item => { item.markup.tabs.pop(); }],
  ['hidden application root', item => { item.markup.elements.main.visible = false; }],
  ['enabled editing', item => { item.capabilities.interactive = true; }],
  ['enabled research', item => { item.capabilities.researchBrowsing = true; }],
  ['Node globals', item => { item.nodeExposed = true; }],
]) test(label + ' cannot pass rendering acceptance', () => {
  const item = evidence(); mutate(item);
  assert.throws(() => assertRenderingEvidence(item, 'full-application'));
});

test('inert fixture cannot substitute for full application evidence', () => {
  const item = evidence(); item.title = 'InspectorPro fixture';
  item.markup = { kind: 'inert-fixture', fixture: { visible: true } };
  assert.equal(assertRenderingEvidence(item, 'inert-fixture'), true);
  assert.throws(() => assertRenderingEvidence(item, 'full-application'));
});


test('parent report validation requires every fresh lock recheck and the current revision', () => {
  const report = { ...evidence(), inputLockRevision: 'html-root-lock-v1', events: [] };
  report.events = ['before-wide-capture', 'after-wide-capture', 'before-narrow-capture', 'after-narrow-capture']
    .map(phase => ({ name: 'input-lock-rechecked', phase, ...evidence() }));
  report.captures = Object.fromEntries(['wide', 'narrow'].map(name => [name, { frameCheckpoint: { viewport: { width: 886, height: 638 } } }]));
  assert.equal(assertInputLockRechecks(report, 'full-application'), true);
  for (const mutate of [r => { delete r.inputLockRevision; }, r => { r.events.pop(); },
    r => { r.events.push(r.events[0]); }, r => { r.events.reverse(); },
    r => { delete r.events[0].lockEvidence; }, r => { r.events[1].frozen = false; },
    r => { r.events[2].preloadLockDiagnostics.current.allProtectedRootsLocked = false; },
    r => { delete r.events[2].chromeLayout; }, r => { delete r.events[3].markup; },
    r => { r.events[3].chromeLayout = layout(1426, 754); }]) {
    const broken = structuredClone(report); mutate(broken);
    assert.throws(() => assertInputLockRechecks(broken, 'full-application'));
  }
});


test('wrapped workflow rows and one-DIP rounding remain valid', () => {
  const data = layout();
  data.tabbar.tabs[0].bounds.x -= 0.5;
  data.tabbar.tabs[0].labelBounds.push({ x: 294, y: 62, width: 50, height: 8 });
  assert.equal(assertChromeLayout(data), true);
});

for (const [label, mutate] of [
  ['old narrow toolbar overlap', data => { data.toolbar.controls[1].bounds.x = 100; }],
  ['old narrow Sessions clipping', data => { data.tabbar.tabs[7].bounds.x = 860; }],
  ['tab hidden despite DOM presence', data => { data.tabbar.tabs[7].visible = false; }],
  ['workflow label clipped inside its button', data => { data.tabbar.tabs[7].labelBounds[0].width = 180; }],
  ['toolbar label clipped inside its input', data => { data.toolbar.controls[1].labelBounds[0].width = 200; }],
  ['ancestor overflow clips a toolbar control', data => { data.toolbar.controls[1].clipBounds.width = 200; }],
  ['workflow labels missing', data => { data.tabbar.tabs[7].labelBounds = []; }],
  ['workflow rows overlapping', data => { data.tabbar.tabs[4].bounds.y = 55; }],
  ['missing geometry revision', data => { delete data.revision; }],
  ['nonfinite geometry', data => { data.toolbar.controls[0].bounds.x = NaN; }],
]) test(label + ' fails even if reported violations are empty', () => {
  const data = layout(); mutate(data);
  assert.throws(() => assertChromeLayout(data), error => error.code === 'rendering_chrome_layout_invalid');
});

test('nested measured controls are not mistaken for sibling overlap', () => {
  const data = layout(), parent = data.toolbar.controls[1];
  data.toolbar.controls.push({ id: 'nested-search-input', visible: true,
    bounds: { x: 168, y: 8, width: 130, height: 24 }, clipBounds: { x: 0, y: 0, width: 886, height: 638 },
    labelBounds: [], ancestorIds: [parent.id] });
  assert.equal(assertChromeLayout(data), true);
  data.toolbar.controls.at(-1).ancestorIds = [];
  assert.throws(() => assertChromeLayout(data));
});

test('before-narrow geometry may precede renderer resize; after geometry must match the capture', () => {
  const report = { ...evidence(), inputLockRevision: 'html-root-lock-v1', events: [], captures: {
    wide: { frameCheckpoint: { viewport: { width: 1426, height: 754 } } },
    narrow: { frameCheckpoint: { viewport: { width: 886, height: 638 } } } } };
  report.events = ['before-wide-capture', 'after-wide-capture', 'before-narrow-capture', 'after-narrow-capture']
    .map((phase, index) => ({ name: 'input-lock-rechecked', phase, ...evidence(),
      chromeLayout: index < 3 ? layout(1426, 754) : layout() }));
  assert.equal(assertInputLockRechecks(report, 'full-application'), true);
  report.events[3].chromeLayout = layout(1426, 754);
  assert.throws(() => assertInputLockRechecks(report, 'full-application'), error => error.code === 'rendering_chrome_layout_stale');
});

test('geometry collector omits intentionally hidden toolbar controls and retains label rectangles', () => {
  const make = (id, bounds, text = id) => ({ id, bounds, text, dataset: { tab: id }, parentElement: null,
    getBoundingClientRect() { return { ...bounds, left: bounds.x, top: bounds.y }; }, contains(other) { return other === this; } });
  const brand = make('brand', { x: 8, y: 4, width: 130, height: 32 });
  const hidden = make('exportBtn', { x: 0, y: 0, width: 0, height: 0 });
  const toolbar = make('toolbar', { x: 0, y: 0, width: 886, height: 42 });
  const tabbar = make('tabbar', { x: 286, y: 42, width: 554, height: 60 });
  toolbar.querySelectorAll = selector => {
    assert.ok(selector.includes('.toolbar-brand')); assert.ok(selector.includes('.toolbar-search-wrap'));
    return [brand, hidden];
  }; tabbar.querySelectorAll = () => [];
  const document = { querySelector: selector => selector.includes('toolbar') ? toolbar : tabbar,
    createTreeWalker: node => { let read = false; return { nextNode: () => read ? null : (read = true, { textContent: node.text, parentElement: node }) }; },
    createRange: () => { let node; return { selectNodeContents(value) { node = value.parentElement; },
      getClientRects: () => [{ x: node.bounds.x + 2, y: node.bounds.y + 3, width: 50, height: 14 }] }; } };
  const collected = vm.runInNewContext('(' + collectChromeLayout.toString() + ')()', { document,
    innerWidth: 886, innerHeight: 638, NodeFilter: { SHOW_TEXT: 4 },
    getComputedStyle: node => ({ display: node === hidden ? 'none' : 'block', visibility: 'visible', opacity: '1' }) });
  assert.deepEqual(Array.from(collected.toolbar.controls, item => item.id), ['brand']);
  assert.equal(collected.toolbar.controls[0].labelBounds.length, 1);
});
