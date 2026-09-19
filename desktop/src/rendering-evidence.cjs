'use strict';

// Read-only evidence for the initial empty application. This does not exercise
// workflow editing, loaded CAD assets, agents, or production backend pairing.
const WORKFLOWS = ['drawing', '3dmodel', 'assembly', 'training', 'dfm', 'report', 'usage', 'sessions'];
// Geometry is measured in CSS pixels/DIPs, independently of device pixel ratio.
function collectChromeLayout() {
  const rect = node => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; };
  const visible = node => { const r = rect(node), s = getComputedStyle(node); return r.width > 0 && r.height > 0
    && s.display !== 'none' && !['hidden', 'collapse'].includes(s.visibility) && s.opacity !== '0'; };
  const viewport = { width: innerWidth, height: innerHeight };
  const clip = node => {
    let left = 0, top = 0, right = innerWidth, bottom = innerHeight;
    for (let parent = node.parentElement; parent; parent = parent.parentElement) {
      const r = parent.getBoundingClientRect(), s = getComputedStyle(parent);
      if (['hidden', 'clip', 'scroll', 'auto'].includes(s.overflowX)) {
        left = Math.max(left, r.left + parent.clientLeft); right = Math.min(right, r.left + parent.clientLeft + parent.clientWidth);
      }
      if (['hidden', 'clip', 'scroll', 'auto'].includes(s.overflowY)) {
        top = Math.max(top, r.top + parent.clientTop); bottom = Math.min(bottom, r.top + parent.clientTop + parent.clientHeight);
      }
    }
    return { x: left, y: top, width: Math.max(0, right - left), height: Math.max(0, bottom - top) };
  };
  const labels = node => {
    const result = [], walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    let child;
    while ((child = walker.nextNode())) {
      if (!child.textContent.trim() || !visible(child.parentElement)) continue;
      const range = document.createRange(); range.selectNodeContents(child);
      for (const r of range.getClientRects()) if (r.width > 0 && r.height > 0) {
        result.push({ x: r.x, y: r.y, width: r.width, height: r.height });
        if (result.length > 64) return result;
      }
    }
    return result;
  };
  const toolbar = document.querySelector('.app-container > .toolbar');
  const tabbar = document.querySelector('.center-viewport > .tab-bar[role="tablist"]');
  if (!toolbar || !tabbar) return { revision: 'chrome-layout-v1', viewport, toolbar: null, tabbar: null };
  const controls = [...toolbar.querySelectorAll('button, input, select, textarea, a[href], [role="button"], .app-menu-label, .toolbar-logo, .toolbar-brand, .toolbar-search-wrap, .status-indicator')]
    .filter(visible).slice(0, 129);
  const ids = controls.map((node, index) => node.id || 'toolbar-control-' + index);
  const measure = (node, id) => ({ id, visible: visible(node), bounds: rect(node), clipBounds: clip(node),
    labelBounds: labels(node), ancestorIds: [] });
  return { revision: 'chrome-layout-v1', viewport,
    toolbar: { bounds: rect(toolbar), controls: controls.map((node, index) => ({ ...measure(node, ids[index]),
      ancestorIds: controls.flatMap((parent, parentIndex) => parent !== node && parent.contains(node) ? [ids[parentIndex]] : []) })) },
    tabbar: { bounds: rect(tabbar), tabs: [...tabbar.querySelectorAll(':scope > [data-tab]')]
      .map(node => measure(node, node.dataset.tab)) } };
}

function chromeLayoutViolations(layout, expectedTabs) {
  const violations = [], tolerance = 1;
  const add = (kind, ids = []) => { if (violations.length < 32) violations.push({ kind, ids }); };
  const number = value => typeof value === 'number' && Number.isFinite(value);
  const rectangle = value => value && ['x', 'y', 'width', 'height'].every(key => number(value[key]))
    && value.width > 0 && value.height > 0;
  const contains = (outer, inner) => inner.x >= outer.x - tolerance && inner.y >= outer.y - tolerance
    && inner.x + inner.width <= outer.x + outer.width + tolerance
    && inner.y + inner.height <= outer.y + outer.height + tolerance;
  if (!layout || layout.revision !== 'chrome-layout-v1' || !number(layout.viewport?.width)
      || !number(layout.viewport?.height) || layout.viewport.width <= 0 || layout.viewport.height <= 0) {
    add('invalid-layout'); return violations;
  }
  const viewport = { x: 0, y: 0, width: layout.viewport.width, height: layout.viewport.height };
  for (const [name, key] of [['toolbar', 'controls'], ['tabbar', 'tabs']]) {
    const section = layout[name], nodes = section?.[key];
    if (!rectangle(section?.bounds) || !Array.isArray(nodes) || !nodes.length || nodes.length > 128) {
      add('invalid-' + name); continue;
    }
    if (!contains(viewport, section.bounds)) add(name + '-outside-viewport');
    if (name === 'tabbar' && (nodes.length !== expectedTabs.length
        || expectedTabs.some(id => nodes.filter(node => node?.id === id).length !== 1))) add('missing-or-duplicate-tabs');
    const ids = nodes.map(node => node?.id), valid = [];
    for (const node of nodes) {
      if (!node || typeof node.id !== 'string' || !node.id || ids.filter(id => id === node.id).length !== 1
          || node.visible !== true || !rectangle(node.bounds) || !rectangle(node.clipBounds)
          || !Array.isArray(node.labelBounds) || node.labelBounds.length > 64 || !node.labelBounds.every(rectangle)
          || !Array.isArray(node.ancestorIds) || node.ancestorIds.some(id => !ids.includes(id) || id === node.id)
          || (name === 'tabbar' && (!node.labelBounds.length || node.ancestorIds.length))) {
        add('invalid-' + name + '-item', [node?.id || 'unknown']); continue;
      }
      valid.push(node);
      if (!contains(viewport, node.bounds) || !contains(section.bounds, node.bounds) || !contains(node.clipBounds, node.bounds)) {
        add('clipped-' + name + '-item', [node.id]);
      }
      for (const label of node.labelBounds) if (!contains(node.bounds, label) || !contains(node.clipBounds, label)) {
        add('clipped-' + name + '-label', [node.id]); break;
      }
    }
    for (let a = 0; a < valid.length; a++) for (let b = a + 1; b < valid.length; b++) {
      const first = valid[a], second = valid[b];
      const firstContains = second.ancestorIds.includes(first.id), secondContains = first.ancestorIds.includes(second.id);
      if (firstContains || secondContains) {
        if ((firstContains && secondContains) || !contains(firstContains ? first.bounds : second.bounds,
            firstContains ? second.bounds : first.bounds)) add('invalid-control-ancestry', [first.id, second.id]);
        continue;
      }
      const overlapWidth = Math.min(first.bounds.x + first.bounds.width, second.bounds.x + second.bounds.width) - Math.max(first.bounds.x, second.bounds.x);
      const overlapHeight = Math.min(first.bounds.y + first.bounds.height, second.bounds.y + second.bounds.height) - Math.max(first.bounds.y, second.bounds.y);
      if (overlapWidth > tolerance && overlapHeight > tolerance) add('overlapping-' + name + '-items', [first.id, second.id]);
    }
  }
  return violations;
}

function assertChromeLayout(layout) {
  const violations = chromeLayoutViolations(layout, WORKFLOWS);
  if (violations.length || !Array.isArray(layout?.violations) || layout.violations.length) {
    throw Object.assign(new Error('Application toolbar or workflow tabs are clipped or overlapping'),
      { code: 'rendering_chrome_layout_invalid', violations });
  }
  return true;
}

function assertChromeLayoutCapture(layout, capture) {
  const viewport = capture?.frameCheckpoint?.viewport;
  if (!viewport || ![viewport.width, viewport.height].every(value => Number.isFinite(value) && value > 0)
      || !layout?.viewport || ![layout.viewport.width, layout.viewport.height].every(value => Number.isFinite(value) && value > 0)
      || Math.abs(layout.viewport.width - viewport.width) > 1
      || Math.abs(layout.viewport.height - viewport.height) > 1) {
    throw Object.assign(new Error('Application chrome geometry is stale relative to its captured renderer viewport'),
      { code: 'rendering_chrome_layout_stale' });
  }
  return true;
}

const EVIDENCE_SCRIPT = `(() => {
  const inspect = selector => {
    const node = document.querySelector(selector);
    if (!node) return { exists: false, visible: false };
    const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
    return { exists: true, visible: rect.width > 0 && rect.height > 0 && style.display !== 'none'
      && style.visibility !== 'hidden', bounds: { x: rect.x, y: rect.y, width: rect.width, height: rect.height } };
  };
  const elements = Object.fromEntries(Object.entries({ toolbar: '.app-container > .toolbar',
    main: '.app-container > .main-content', viewport: '.center-viewport',
    tabs: '.center-viewport > .tab-bar[role="tablist"]', content: '#viewportContent',
    upload: '#uploadZone', empty: '#viewportContent > .viewport-empty' }).map(([key, selector]) => [key, inspect(selector)]));
  const tabs = [...document.querySelectorAll('.center-viewport > .tab-bar[role="tablist"] > [data-tab]')]
    .map(node => ({ id: node.dataset.tab, selected: node.getAttribute('aria-selected') === 'true' }));
  const profileLabel = document.querySelector('#profileCount')?.textContent.trim() || '';
  const errorText = document.querySelector('#errorToast')?.textContent.trim() || '';
  const fixture = inspect('main[data-inspectorpro-rendering-fixture="true"]');
  const fixtureReady = document.title === 'InspectorPro fixture' && fixture.visible
    && document.querySelector('main[data-inspectorpro-rendering-fixture="true"] > h1')?.textContent.trim()
      === 'InspectorPro desktop acceptance fixture';
  const expected = ${JSON.stringify(WORKFLOWS)};
  const chromeLayout = document.title === 'InspectorPro' ? (${collectChromeLayout.toString()})() : null;
  if (chromeLayout) chromeLayout.violations = (${chromeLayoutViolations.toString()})(chromeLayout, expected);
  const fullReady = document.title === 'InspectorPro' && Object.values(elements).every(x => x.visible)
    && document.querySelector('#contextRibbon') !== null && profileLabel === 'Profiles: 0'
    && tabs.length === expected.length && expected.every(id => tabs.some(tab => tab.id === id))
    && tabs.filter(tab => tab.selected).length === 1 && tabs.some(tab => tab.id === 'drawing' && tab.selected)
    && !errorText.includes('Failed to load inspection profiles');
  const banners = [...document.querySelectorAll('body > #inspectorpro-desktop-spike-banner')];
  const bannerNode = banners.length === 1 ? banners[0] : null;
  const children = [...document.body.children].filter(x => x !== bannerNode);
  const nativeInertGetter = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'inert')?.get;
  const nativeInert = node => {
    try { return node instanceof HTMLElement && nativeInertGetter ? nativeInertGetter.call(node) : null; }
    catch (_error) { return null; }
  };
  const describeRoot = (node, index) => ({ index, tag: node.localName, namespace: node.namespaceURI,
    id: (node.getAttribute('id') || '').slice(0, 96), className: (node.getAttribute('class') || '').slice(0, 96),
    isHTMLElement: node instanceof HTMLElement, inertType: typeof node.inert,
    inertOwnProperty: Object.prototype.hasOwnProperty.call(node, 'inert'),
    inertAttribute: node.hasAttribute('inert'), nativeInert: nativeInert(node),
    wrapper: node.hasAttribute('data-inspectorpro-inert-wrapper') });
  const rootEvidence = children.map(describeRoot);
  const unlocked = rootEvidence.filter(node => !node.isHTMLElement || node.nativeInert !== true);
  let preloadLockDiagnostics = null, preloadDiagnosticsError = null;
  try { preloadLockDiagnostics = window.InspectorProDesktop?.getInputLockDiagnostics?.() || null; }
  catch (error) { preloadDiagnosticsError = String(error.message || error).slice(0, 512); }
  const lockEvidence = { totalRoots: children.length, uniqueBanner: banners.length === 1,
    reportedRoots: Math.min(rootEvidence.length, 128), truncated: rootEvidence.length > 128,
    unlockedRootCount: unlocked.length, roots: rootEvidence.slice(0, 128), unlockedRoots: unlocked.slice(0, 128) };
  return { title: document.title, bodyChildren: children.length,
    frozen: children.length > 0 && banners.length === 1 && unlocked.length === 0,
    lockEvidence, preloadLockDiagnostics, preloadDiagnosticsError, chromeLayout,
    desktopMarker: document.documentElement.dataset.inspectorproDesktop,
    capabilities: window.InspectorProDesktop?.getCapabilities(),
    nodeExposed: typeof window.require !== 'undefined' || typeof window.process !== 'undefined',
    banner: bannerNode?.innerText || '',
    markup: { kind: fixtureReady ? 'inert-fixture' : fullReady ? 'full-application' : 'unready',
      elements, tabs, profileLabel, errorText, fixture, contextRibbonExists: !!document.querySelector('#contextRibbon') } };
})()`;

function assertRenderingEvidence(evidence, expectedPage) {
  if (!['inert-fixture', 'full-application'].includes(expectedPage)) throw new Error('Unsupported rendering expectation');
  if (!evidence || !Number.isSafeInteger(evidence.bodyChildren) || evidence.bodyChildren < 1
      || evidence.frozen !== true || evidence.desktopMarker !== 'rendering-spike' || !evidence.banner
      || evidence.lockEvidence?.uniqueBanner !== true || evidence.lockEvidence?.unlockedRootCount !== 0
      || evidence.lockEvidence?.totalRoots !== evidence.bodyChildren
      || evidence.preloadLockDiagnostics?.schemaVersion !== 1 || evidence.preloadLockDiagnostics?.acknowledged !== true
      || evidence.preloadLockDiagnostics?.current?.allProtectedRootsLocked !== true
      || evidence.preloadLockDiagnostics?.current?.protectedRootCount !== evidence.bodyChildren) {
    throw Object.assign(new Error('Application input-lock evidence is incomplete'), { code: 'rendering_input_lock_incomplete' });
  }
  const caps = evidence.capabilities;
  if (evidence.nodeExposed !== false || !caps || caps.schemaVersion !== 1 || caps.mode !== 'rendering-spike'
      || ['interactive', 'researchBrowsing', 'managedBackend', 'durableWorkflowRecovery'].some(key => caps[key] !== false)) {
    throw new Error('Renderer capability isolation failed');
  }
  const markup = evidence.markup;
  if (markup?.kind !== expectedPage) throw new Error('Expected ' + expectedPage + ' markup has not initialized');
  if (expectedPage === 'inert-fixture') {
    if (evidence.title !== 'InspectorPro fixture' || markup.fixture?.visible !== true) throw new Error('Inert fixture markup is missing');
  } else {
    assertChromeLayout(evidence.chromeLayout);
    if (evidence.title !== 'InspectorPro' || markup.profileLabel !== 'Profiles: 0' || markup.contextRibbonExists !== true
        || typeof markup.errorText !== 'string' || markup.errorText.includes('Failed to load inspection profiles')
        || ['toolbar', 'main', 'viewport', 'tabs', 'content', 'upload', 'empty'].some(key => markup.elements?.[key]?.visible !== true)
        || !Array.isArray(markup.tabs) || markup.tabs.length !== WORKFLOWS.length
        || WORKFLOWS.some(id => !markup.tabs.some(tab => tab.id === id))
        || markup.tabs.filter(tab => tab.selected).length !== 1
        || !markup.tabs.some(tab => tab.id === 'drawing' && tab.selected === true)) {
      throw new Error('Full application initialization evidence is incomplete');
    }
  }
  return true;
}

function assertInputLockRechecks(report, expectedPage) {
  if (report?.inputLockRevision !== 'html-root-lock-v1' || !Array.isArray(report.events)) {
    throw new Error('Rendering report is missing the current input-lock contract');
  }
  assertRenderingEvidence(report, expectedPage);
  const phases = ['before-wide-capture', 'after-wide-capture', 'before-narrow-capture', 'after-narrow-capture'];
  const checks = report.events.filter(event => event.name === 'input-lock-rechecked');
  if (checks.length !== phases.length || checks.some((check, index) => check.phase !== phases[index])) {
    throw new Error('Rendering report must include all four ordered input-lock rechecks');
  }
  for (const check of checks) {
    // Every recheck is complete current evidence; never inherit initial markup/geometry.
    assertRenderingEvidence(check, expectedPage);
  }
  if (expectedPage === 'full-application') {
    for (const name of ['wide', 'narrow']) {
      const after = checks.find(check => check.phase === 'after-' + name + '-capture');
      assertChromeLayoutCapture(after.chromeLayout, report.captures?.[name]);
    }
  }
  return true;
}

module.exports = { EVIDENCE_SCRIPT, assertRenderingEvidence, assertInputLockRechecks,
  collectChromeLayout, chromeLayoutViolations, assertChromeLayout, assertChromeLayoutCapture };
