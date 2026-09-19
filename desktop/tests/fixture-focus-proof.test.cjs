'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { FIXTURE_FOCUS_SCRIPT, assertFixtureFocusProof } = require('../tools/fixture-focus-proof.cjs');

// These mocks check script/validator branches, not browser focus semantics. The
// ordinary-user Electron fixture is responsible for native behavior evidence.
function fixture() {
  const document = { activeElement: null };
  class Element {
    constructor(tagName, namespaceURI) {
      this.tagName = tagName; this.localName = tagName.toLowerCase();
      this.namespaceURI = namespaceURI; this.id = ''; this.isConnected = true;
      this.attributes = new Set(); this.parentElement = null; this.focusAllowed = true;
      this.focusCalls = 0; this.blurCalls = 0; this.textContent = '';
    }
    hasAttribute(name) { return this.attributes.has(name); }
    focus() { this.focusCalls++; if (this.focusError) throw new Error(this.focusError); if (this.focusAllowed) document.activeElement = this; }
    blur() { this.blurCalls++; if (document.activeElement === this) document.activeElement = null; }
  }
  class HTMLElement extends Element {
    constructor(tagName) { super(tagName.toUpperCase(), 'http://www.w3.org/1999/xhtml'); }
    get inert() { return this.hasAttribute('inert'); }
  }
  class SVGElement extends Element {
    constructor() { super('svg', 'http://www.w3.org/2000/svg'); }
  }
  const body = document.body = new HTMLElement('body');
  const parent = new HTMLElement('div'); parent.attributes.add('inert'); parent.parentElement = body;
  const svg = new SVGElement(); svg.id = 'desktop-fixture-svg'; svg.parentElement = parent; svg.focusAllowed = false;
  const banner = new HTMLElement('aside'); banner.id = 'inspectorpro-desktop-spike-banner'; banner.parentElement = body;
  const close = new HTMLElement('button'); close.textContent = 'Close preview'; close.parentElement = banner;
  const lists = { svg: [svg], banner: [banner], close: [close] };
  banner.querySelectorAll = () => lists.close;
  document.querySelectorAll = selector => selector === '#desktop-fixture-svg' ? lists.svg : lists.banner;
  const baseline = { svgFocusable: true, svgAttributeStillFocusable: true };
  const window = { __desktopFixtureFocusBaseline: baseline };
  const run = () => vm.runInNewContext(FIXTURE_FOCUS_SCRIPT, { document, window, HTMLElement, SVGElement });
  return { document, HTMLElement, SVGElement, svg, parent, banner, close, lists, baseline, window, run };
}

test('fixture focus script compiles and returns serializable proof with successful mock branches', () => {
  assert.doesNotThrow(() => new vm.Script(FIXTURE_FOCUS_SCRIPT));
  const f = fixture(); const result = f.run();
  assert.equal(assertFixtureFocusProof(result), true);
  assert.equal(f.svg.focusCalls, 1); assert.equal(f.close.focusCalls, 1);
  assert.equal(f.document.activeElement, null);
  assert.equal(f.svg.blurCalls, 2); assert.equal(f.close.blurCalls, 2);
  assert.equal(assertFixtureFocusProof(JSON.parse(JSON.stringify(result))), true);
});

for (const [name, change] of [
  ['missing parser baseline', f => { delete f.window.__desktopFixtureFocusBaseline; }],
  ['SVG never focusable in baseline', f => { f.baseline.svgFocusable = false; }],
  ['SVG-only inert unexpectedly prevented baseline focus', f => { f.baseline.svgAttributeStillFocusable = false; }],
  ['missing SVG', f => { f.lists.svg = []; }],
  ['duplicate SVG IDs', f => { f.lists.svg.push(f.svg); }],
  ['duplicate banner IDs', f => { f.lists.banner.push(f.banner); }],
  ['missing close button', f => { f.lists.close = []; }],
  ['duplicate close buttons', f => { f.lists.close.push(f.close); }],
  ['SVG parent has only a JavaScript inert expando', f => { f.parent.attributes.delete('inert'); Object.defineProperty(f.parent, 'inert', { value: true }); }],
  ['SVG parent is itself SVG with inert attribute', f => { const parent = new f.SVGElement(); parent.attributes.add('inert'); parent.inert = true; parent.parentElement = f.document.body; f.svg.parentElement = parent; }],
  ['wrapper is detached from body root', f => { f.parent.parentElement = null; }],
  ['SVG still receives focus after lock', f => { f.svg.focusAllowed = true; }],
  ['close control cannot receive focus', f => { f.close.focusAllowed = false; }],
  ['SVG focus API throws', f => { f.svg.focusError = 'focus failed'; }],
  ['close focus API throws', f => { f.close.focusError = 'focus failed'; }],
]) test(name + ' cannot pass focus proof', () => {
  const f = fixture(); change(f);
  const proof = f.run();
  assert.throws(() => assertFixtureFocusProof(proof), /native focus proof/);
  assert.equal(f.document.activeElement, null);
});

test('validator rejects missing, false, or inconsistent serialized evidence', () => {
  const complete = JSON.parse(JSON.stringify(fixture().run()));
  for (const key of Object.keys(complete)) {
    const proof = structuredClone(complete); delete proof[key];
    assert.throws(() => assertFixtureFocusProof(proof), /native focus proof/, key);
  }
  for (const key of Object.keys(complete).filter(key => typeof complete[key] === 'boolean')) {
    const proof = structuredClone(complete); proof[key] = false;
    assert.throws(() => assertFixtureFocusProof(proof), /native focus proof/, key);
  }
  for (const [key, value] of [['svgCount', 2], ['bannerCount', 0], ['closeButtonCount', 2], ['errors', ['unconfirmed focus']]]) {
    const proof = structuredClone(complete); proof[key] = value;
    assert.throws(() => assertFixtureFocusProof(proof), /native focus proof/, key);
  }
  assert.throws(() => assertFixtureFocusProof(null), /native focus proof/);
  assert.throws(() => assertFixtureFocusProof({}), /native focus proof/);
});
