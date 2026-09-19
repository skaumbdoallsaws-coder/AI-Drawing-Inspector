'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/preload.cjs'), 'utf8');
const HTML_NS = 'http://www.w3.org/1999/xhtml';
const SVG_NS = 'http://www.w3.org/2000/svg';

function harness({ nativeInert = true, mainFrame = true, failWrap = false } = {}) {
  const observers = [], exposed = {}, ipc = [], required = [];
  let nativeWrites = 0, observerCallbacks = 0;
  const within = (node, ancestor) => {
    for (let current = node; current; current = current.parentNode) if (current === ancestor) return true;
    return false;
  };
  function mutation(record) {
    for (const observer of observers) for (const registration of observer.registrations) {
      const { target, options } = registration;
      if (record.target !== target && !(options.subtree && within(record.target, target))) continue;
      if (record.type === 'childList' && !options.childList) continue;
      if (record.type === 'attributes' && (!options.attributes
          || (options.attributeFilter && !options.attributeFilter.includes(record.attributeName)))) continue;
      observer.records.push(record); break;
    }
  }
  class Events {
    listeners = new Map();
    addEventListener(type, callback, options) {
      const listeners = this.listeners.get(type) || [];
      listeners.push({ callback, options }); this.listeners.set(type, listeners);
    }
    dispatch(type, event = {}) {
      for (const entry of [...(this.listeners.get(type) || [])]) {
        entry.callback(event);
        if (entry.options?.once) this.listeners.set(type, this.listeners.get(type).filter(item => item !== entry));
        if (event.stopped) break;
      }
    }
  }
  class Node extends Events {
    parentNode = null;
    children = [];
    append(...nodes) {
      for (const node of nodes) {
        if (node.parentNode) node.parentNode.removeChild(node);
        this.children.push(node); node.parentNode = this;
        mutation({ type: 'childList', target: this, addedNodes: [node], removedNodes: [] });
      }
    }
    insertBefore(node, reference) {
      if (failWrap && this.tagName === 'BODY' && node.tagName === 'DIV' && node.style.display === 'contents') {
        throw new Error('Injected wrapper insertion failure');
      }
      if (node.parentNode) node.parentNode.removeChild(node);
      const index = this.children.indexOf(reference);
      if (index < 0) throw new Error('Reference child missing');
      this.children.splice(index, 0, node); node.parentNode = this;
      mutation({ type: 'childList', target: this, addedNodes: [node], removedNodes: [] });
    }
    removeChild(node) {
      const index = this.children.indexOf(node);
      if (index < 0) throw new Error('Child missing');
      this.children.splice(index, 1); node.parentNode = null;
      mutation({ type: 'childList', target: this, addedNodes: [], removedNodes: [node] });
      return node;
    }
    replaceChild(replacement, original) { this.insertBefore(replacement, original); this.removeChild(original); }
  }
  class Element extends Node {
    attributes = new Map();
    style = {};
    dataset = {};
    constructor(tag, namespace) { super(); this.tagName = namespace === HTML_NS ? tag.toUpperCase() : tag; this.namespaceURI = namespace; }
    get id() { return this.getAttribute('id') || ''; }
    set id(value) { this.setAttribute('id', value); }
    get className() { return this.getAttribute('class') || ''; }
    set className(value) { this.setAttribute('class', value); }
    setAttribute(name, value) {
      this.attributes.set(name, String(value));
      mutation({ type: 'attributes', target: this, attributeName: name });
    }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    hasAttribute(name) { return this.attributes.has(name); }
    removeAttribute(name) {
      if (this.attributes.delete(name)) mutation({ type: 'attributes', target: this, attributeName: name });
    }
    focus() {
      for (let current = this; current; current = current.parentNode) {
        if (current instanceof Html && nativeDescriptor.get.call(current)) return;
      }
      document.activeElement = this;
    }
  }
  class Html extends Element {
    constructor(tag) { super(tag, HTML_NS); }
    get inert() { return this.hasAttribute('inert'); }
    set inert(value) { nativeWrites++; if (value) this.setAttribute('inert', ''); else this.removeAttribute('inert'); }
  }
  const nativeDescriptor = Object.getOwnPropertyDescriptor(Html.prototype, 'inert');
  if (!nativeInert) delete Html.prototype.inert;
  class Svg extends Element { constructor(tag = 'svg') { super(tag, SVG_NS); } }
  class Document extends Node {
    readyState = 'loading';
    activeElement = null;
    get documentElement() { return this.children.find(child => child.tagName === 'HTML') || null; }
    get body() { return this.documentElement?.children.find(child => child.tagName === 'BODY') || null; }
    createElement(tag) { return new Html(tag); }
    createElementNS(namespace, tag) { return namespace === HTML_NS ? new Html(tag) : new Svg(tag); }
  }
  const document = new Document(), window = new Events();
  document.append(new Html('html')); document.documentElement.append(new Html('body'));
  class Observer {
    records = [];
    registrations = [];
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe(target, options) { this.registrations.push({ target, options }); }
  }
  function load() {
    vm.runInNewContext(source, { document, window, HTMLElement: Html, MutationObserver: Observer,
      process: { isMainFrame: mainFrame }, require(name) {
        required.push(name);
        if (name !== 'electron') throw new Error('Sandbox preload cannot load local modules');
        return { contextBridge: { exposeInMainWorld: (name, value) => { exposed[name] = value; } },
          ipcRenderer: { send: (...args) => ipc.push(args) } };
      } });
  }
  function ready() { document.readyState = 'interactive'; document.dispatch('DOMContentLoaded'); }
  function flush() {
    for (let round = 0; round < 20; round++) {
      if (observers.every(observer => observer.records.length === 0)) return;
      for (const observer of observers) {
        if (!observer.records.length) continue;
        const records = observer.records.splice(0); observerCallbacks++;
        observer.callback(records);
      }
    }
    assert.fail('Input lock created a MutationObserver loop');
  }
  const diagnostics = () => JSON.parse(JSON.stringify(exposed.InspectorProDesktop.getInputLockDiagnostics()));
  const banner = () => document.body?.children.find(node => node.tagName === 'ASIDE' && node.id === 'inspectorpro-desktop-spike-banner');
  return { document, window, Html, Svg, nativeDescriptor, load, ready, flush, diagnostics, banner,
    exposed, ipc, required, get nativeWrites() { return nativeWrites; }, get observerCallbacks() { return observerCallbacks; } };
}

test('real preload wraps original SVG in native inert HTML while leaving HTML roots in place', () => {
  const h = harness(), svg = new h.Svg(), definitions = new h.Svg('defs'), script = new h.Html('script'), content = new h.Html('div');
  svg.id = 'symbols'; svg.append(definitions); svg.inert = true;
  h.document.body.append(svg, script, content);
  svg.focus(); assert.equal(h.document.activeElement, svg, 'SVG expando does not implement native inert');
  svg.setAttribute('inert', ''); h.document.activeElement = null; svg.focus();
  assert.equal(h.document.activeElement, svg, 'An SVG inert attribute also does not replace a HTML inert ancestor');
  h.load(); h.ready(); h.flush();
  const wrapper = svg.parentNode;
  assert.equal(wrapper instanceof h.Html, true);
  assert.equal(wrapper.parentNode, h.document.body);
  assert.equal(wrapper.style.display, 'contents');
  assert.equal(wrapper.hasAttribute('data-inspectorpro-inert-wrapper'), true);
  assert.equal(wrapper.inert, true);
  assert.equal(wrapper.hasAttribute('inert'), true);
  assert.equal(wrapper.children[0], svg);
  assert.equal(svg.children[0], definitions);
  assert.equal(script.parentNode, h.document.body);
  assert.equal(content.parentNode, h.document.body);
  assert.deepEqual(h.document.body.children.slice(1, 3), [script, content]);
  h.document.activeElement = null; svg.focus(); assert.equal(h.document.activeElement, null);
  const close = h.banner().children.find(node => node.tagName === 'BUTTON');
  close.focus(); assert.equal(h.document.activeElement, close);
  assert.equal(h.ipc.filter(([channel]) => channel === 'desktop-spike:frozen').length, 1);
  assert.equal(h.diagnostics().current.allProtectedRootsLocked, true);
  assert.deepEqual(h.required, ['electron']);
});

test('the observed 1 SVG + 23 scripts + 9 divs fixture acknowledges only after all 33 roots are native HTML inert', () => {
  const h = harness(), svg = new h.Svg(); svg.inert = true;
  h.document.body.append(svg);
  for (let index = 0; index < 23; index++) h.document.body.append(new h.Html('script'));
  for (let index = 0; index < 9; index++) h.document.body.append(new h.Html('div'));
  h.load(); h.ready(); h.flush();
  const diagnostics = h.diagnostics();
  assert.equal(diagnostics.initial.before.totalRoots, 33);
  assert.equal(diagnostics.initial.before.roots[0].tag, 'svg');
  assert.equal(diagnostics.initial.before.roots[0].inertOwnProperty, true);
  assert.equal(diagnostics.initial.before.roots[0].inertValue, true);
  assert.equal(diagnostics.initial.before.roots[0].inertAttribute, false);
  assert.equal(diagnostics.initial.after.totalRoots, 34);
  assert.equal(diagnostics.current.protectedRootCount, 33);
  assert.equal(diagnostics.current.allProtectedRootsLocked, true);
  assert.equal(diagnostics.current.roots.filter(root => !root.banner)
    .every(root => root.isHTMLElement && root.inertAttribute && root.inertValue === true), true);
  assert.equal(h.ipc.filter(([channel]) => channel === 'desktop-spike:frozen').length, 1);
});

test('SVG added after preload but before DOMContentLoaded and SVG added later are both wrapped', () => {
  const h = harness(); h.document.body.append(new h.Html('div')); h.load();
  const startup = new h.Svg(); h.document.body.append(startup); h.ready(); h.flush();
  const later = new h.Svg(); h.document.body.append(later); h.flush();
  for (const svg of [startup, later]) {
    assert.equal(svg.parentNode instanceof h.Html, true);
    assert.equal(svg.parentNode.style.display, 'contents');
    assert.equal(svg.parentNode.inert, true);
  }
  assert.equal(h.diagnostics().current.allProtectedRootsLocked, true);
});

test('banner exemption uses exact node identity, including duplicate IDs', () => {
  const h = harness(), duplicate = new h.Html('div'); duplicate.id = 'inspectorpro-desktop-spike-banner';
  h.document.body.append(duplicate); h.load(); h.ready(); h.flush();
  assert.equal(duplicate.inert, true);
  assert.equal(h.banner().inert, false);
  const items = h.diagnostics().current.roots.filter(item => item.id === duplicate.id);
  assert.equal(items.filter(item => item.banner).length, 1);
  assert.equal(items.find(item => !item.banner).inertValue, true);
});

test('native inert descriptor controls locking even when a HTML root has a false own expando', () => {
  const h = harness(), content = new h.Html('div');
  Object.defineProperty(content, 'inert', { value: false, writable: true, configurable: true });
  h.document.body.append(content); h.load(); h.ready(); h.flush();
  assert.equal(content.inert, false);
  assert.equal(h.nativeDescriptor.get.call(content), true);
  const item = h.diagnostics().current.roots.find(root => !root.banner);
  assert.equal(item.inertOwnProperty, true);
  assert.equal(item.inertValue, false);
  assert.equal(h.diagnostics().current.allProtectedRootsLocked, true);
  assert.equal(h.ipc.some(([channel]) => channel === 'desktop-spike:frozen'), true);
});

test('removing native inert from a protected root repairs once without an observer loop', () => {
  const h = harness(), svg = new h.Svg(); h.document.body.append(svg); h.load(); h.ready(); h.flush();
  const wrapper = svg.parentNode, writes = h.nativeWrites;
  wrapper.removeAttribute('inert'); assert.equal(wrapper.inert, false);
  h.flush();
  assert.equal(wrapper.inert, true);
  assert.equal(h.nativeWrites, writes + 1);
  const callbacks = h.observerCallbacks; h.flush();
  assert.equal(h.observerCallbacks, callbacks);
  assert.equal(h.nativeWrites, writes + 1);
});

test('body replacement restores the same banner and locks new HTML and SVG roots', () => {
  const h = harness(); h.document.body.append(new h.Html('div')); h.load(); h.ready(); h.flush();
  const originalBanner = h.banner(), previous = h.document.body;
  const replacement = new h.Html('body'), content = new h.Html('div'), svg = new h.Svg();
  replacement.append(content, svg);
  h.document.documentElement.replaceChild(replacement, previous); h.flush();
  assert.equal(h.banner(), originalBanner);
  assert.equal(content.inert, true);
  assert.equal(svg.parentNode instanceof h.Html, true);
  assert.equal(svg.parentNode.inert, true);
  assert.equal(h.diagnostics().current.allProtectedRootsLocked, true);
  assert.equal(h.diagnostics().repairHistory.some(item => item.reason === 'body-replaced'), true);
  assert.equal(h.ipc.filter(([channel]) => channel === 'desktop-spike:frozen').length, 1);
});

test('removed body and banner do not make a stale lock current', () => {
  const h = harness(); h.document.body.append(new h.Html('div')); h.load(); h.ready(); h.flush();
  const previous = h.document.body;
  h.document.documentElement.removeChild(previous); h.flush();
  assert.equal(h.diagnostics().current.bodyPresent, false);
  assert.equal(h.diagnostics().current.allProtectedRootsLocked, false);
  const replacement = new h.Html('body'); replacement.append(new h.Svg());
  h.document.documentElement.append(replacement); h.flush();
  assert.equal(h.diagnostics().current.allProtectedRootsLocked, true);
  const banner = h.banner(); replacement.removeChild(banner); h.flush();
  assert.equal(h.banner(), banner);
});

test('a native inert change on the real banner is repaired without unlocking application roots', () => {
  const h = harness(), content = new h.Html('div'); h.document.body.append(content);
  h.load(); h.ready(); h.flush();
  const banner = h.banner(); banner.inert = true;
  const writes = h.nativeWrites; h.flush();
  assert.equal(h.nativeDescriptor.get.call(banner), false);
  assert.equal(h.nativeDescriptor.get.call(content), true);
  assert.equal(h.nativeWrites, writes + 1);
  h.flush(); assert.equal(h.nativeWrites, writes + 1);
});

test('acknowledgment requires a nonempty verified protected root set', () => {
  const h = harness(); h.load(); h.ready(); h.flush();
  assert.equal(h.ipc.some(([channel]) => channel === 'desktop-spike:frozen'), false);
  assert.equal(h.diagnostics().current.allProtectedRootsLocked, false);
  h.document.body.append(new h.Html('div')); h.flush();
  assert.equal(h.ipc.filter(([channel]) => channel === 'desktop-spike:frozen').length, 1);
});

for (const [name, options] of [['missing native inert descriptor', { nativeInert: false }], ['wrapper insertion failure', { failWrap: true }]]) {
  test(name + ' fails closed without acknowledgment', () => {
    const h = harness(options); h.document.body.append(new h.Svg()); h.load(); h.ready(); h.flush();
    assert.equal(h.ipc.some(([channel]) => channel === 'desktop-spike:frozen'), false);
    assert.equal(h.diagnostics().current.allProtectedRootsLocked, false);
  });
}

test('preload-time input capture blocks application events and permits only the actual banner path', () => {
  const h = harness(), duplicate = new h.Html('div'); duplicate.id = 'inspectorpro-desktop-spike-banner';
  h.document.body.append(duplicate); h.load();
  function event(path) { return { prevented: false, stopped: false, composedPath: () => path,
    preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; } }; }
  for (const type of ['pointerdown', 'click', 'dblclick', 'keydown', 'drop', 'paste', 'beforeinput', 'submit']) {
    const input = event([duplicate, h.document.body]); h.window.dispatch(type, input);
    assert.equal(input.prevented, true); assert.equal(input.stopped, true);
    assert.equal(h.window.listeners.get(type)[0].options, true);
  }
  h.ready(); h.flush();
  const blocked = event([duplicate, h.document.body]); h.window.dispatch('click', blocked);
  assert.equal(blocked.prevented, true);
  const banner = h.banner(), button = banner.children.find(child => child.tagName === 'BUTTON');
  const close = event([button, banner, h.document.body]); h.window.dispatch('click', close);
  assert.equal(close.prevented, false); button.dispatch('click', close);
  assert.equal(h.ipc.some(([channel]) => channel === 'desktop-spike:close'), true);
  const capabilities = h.exposed.InspectorProDesktop.getCapabilities();
  assert.equal(capabilities.interactive, false); assert.equal(capabilities.researchBrowsing, false);
  assert.equal(capabilities.managedBackend, false); assert.equal(capabilities.durableWorkflowRecovery, false);
  assert.deepEqual(Object.keys(h.exposed.InspectorProDesktop).sort(), ['getCapabilities', 'getInputLockDiagnostics']);
});

test('diagnostics are bounded read-only copies without node text or values', () => {
  const h = harness();
  for (let index = 0; index < 60; index++) {
    const node = new h.Html('div'); node.id = 'x'.repeat(150); node.className = 'c'.repeat(150);
    node.textContent = 'DO_NOT_EXPOSE_SECRET_TEXT'; node.value = 'DO_NOT_EXPOSE_FORM_VALUE'; h.document.body.append(node);
  }
  h.load(); h.ready(); h.flush();
  const beforeWrites = h.nativeWrites, diagnostics = h.diagnostics();
  assert.equal(diagnostics.initial.before.totalRoots, 60);
  assert.equal(diagnostics.initial.after.totalRoots, 61);
  assert.equal(diagnostics.current.reportedRoots, 48);
  assert.equal(diagnostics.current.truncated, true);
  assert.equal(diagnostics.repairHistory.length <= 12, true);
  assert.equal(diagnostics.current.roots.every(root => root.id.length <= 96 && root.className.length <= 96), true);
  assert.equal(JSON.stringify(diagnostics).includes('DO_NOT_EXPOSE'), false);
  diagnostics.initial.before.roots[0].id = 'changed';
  assert.notEqual(h.diagnostics().initial.before.roots[0].id, 'changed');
  assert.equal(h.nativeWrites, beforeWrites);
});

test('subframes expose no input-unlock control and never acknowledge a main-frame lock', () => {
  const h = harness({ mainFrame: false }); h.load(); h.ready(); h.flush();
  assert.equal(h.diagnostics().mainFrame, false);
  assert.equal(h.ipc.length, 0);
  assert.equal(h.window.listeners.size, 0);
});
