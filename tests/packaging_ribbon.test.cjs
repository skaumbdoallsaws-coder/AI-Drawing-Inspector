const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const child = fs.readFileSync(path.join(root, 'static/packaging.js'), 'utf8');
const host = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
const block = (source, start, end) => {
  const first = source.indexOf(start), last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first);
  return source.slice(first, last);
};

function editor() {
  const nodes = new Map();
  for (const id of ['command-product', 'document-new', 'document-save', 'packaging-resume-editing']) {
    nodes.set(id, { disabled: false, clicks: 0, click() { this.clicks++; } });
  }
  const context = vm.createContext({ PANEL_COMMANDS: [{ id: 'product' }],
    state: { panel: null, busy: false, sage: { locked: false } },
    $: id => nodes.get(id), document: { querySelector: () => null } });
  vm.runInContext(block(child, 'const DOCUMENT_COMMANDS =', 'function updateHeader()'), context);
  return { context, nodes, run: id => context.executeRibbonCommand(id) };
}

test('host commands dispatch only known child controls, without a second edit path', () => {
  const f = editor();
  assert.equal(f.run('product'), true);
  assert.equal(f.nodes.get('command-product').clicks, 1);
  for (const id of ['delete-all', 'eval', '__proto__', 'constructor', null]) assert.equal(f.run(id), false);
  f.nodes.get('document-save').disabled = true;
  assert.equal(f.run('save'), false);
});

test('busy, modal and Sage locks fail closed even if a button has not rerendered', () => {
  const f = editor();
  f.context.state.busy = true;
  assert.equal(f.run('new'), false);
  f.context.state.busy = false;
  f.context.state.sage.locked = true;
  assert.equal(f.run('product'), false);
  assert.equal(f.run('save'), false);
  assert.equal(f.run('resume'), true);
  f.context.state.sage.locked = false;
  f.context.document.querySelector = () => ({});
  assert.equal(f.run('new'), false);
  assert.equal(f.run('resume'), false);
  assert.equal(f.nodes.get('document-new').clicks, 0);
});

test('ribbon state contains command flags only, not document data or credentials', () => {
  const f = editor();
  f.context.state.panel = 'product';
  const status = JSON.parse(JSON.stringify(f.context.ribbonState()));
  assert.deepEqual(Object.keys(status).sort(), ['commands', 'locked']);
  assert.deepEqual(status.commands.product, { enabled: true, active: true });
  for (const value of Object.values(status.commands)) assert.deepEqual(Object.keys(value).sort(), ['active', 'enabled']);
});

test('host adapter ignores inactive, missing, wrong-route and cross-origin frames', () => {
  const api = {}, childWindow = { location: { href: 'http://127.0.0.1:8181/packaging' }, InspectorProPackaging: api };
  let frame = { contentWindow: childWindow };
  const context = vm.createContext({ state: { activeTab: 'training' }, trainingState: { type: 'packaging_shipping' },
    document: { getElementById: () => frame }, URL, location: { origin: 'http://127.0.0.1:8181' } });
  vm.runInContext(block(host, '        function _packagingEditorUI()', '        function _packagingRunCommand('), context);
  assert.equal(context._packagingEditorUI(), api);
  context.state.activeTab = 'assembly'; assert.equal(context._packagingEditorUI(), null);
  context.state.activeTab = 'training';
  context.trainingState.type = 'facility_layout'; assert.equal(context._packagingEditorUI(), null);
  context.trainingState.type = 'packaging_shipping';
  for (const url of ['about:blank', 'http://127.0.0.1:8181/other', 'https://example.com/packaging']) {
    childWindow.location.href = url; assert.equal(context._packagingEditorUI(), null);
  }
  frame = null; assert.equal(context._packagingEditorUI(), null);
  frame = { get contentWindow() { throw new Error('denied'); } }; assert.equal(context._packagingEditorUI(), null);
});
