const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
function source(name) {
  const start = html.indexOf(`        function ${name}(`);
  assert.ok(start >= 0, `Missing ${name}`);
  const next = html.indexOf('\n        function ', start + 1);
  assert.ok(next > start);
  return html.slice(start, next);
}

test('all executable inline scripts parse after packaging integration', () => {
  let count = 0;
  for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    if (/\bsrc\s*=|type\s*=\s*["'](?:module|importmap|application\/json)/i.test(match[1]) || !match[2].trim()) continue;
    new vm.Script(match[2]); count++;
  }
  assert.ok(count > 0);
});

test('packaging navigation uses the actual child draft guard', () => {
  let calls = 0;
  const context = vm.createContext({ document: { getElementById: () => ({ contentWindow: {
    InspectorProPackaging: { confirmNavigation: () => { calls++; return false; } }
  } }) } });
  vm.runInContext(source('_packagingConfirmLeave'), context);
  assert.equal(vm.runInContext('_packagingConfirmLeave()', context), false);
  assert.equal(calls, 1);
  context.document.getElementById = () => null;
  assert.equal(vm.runInContext('_packagingConfirmLeave()', context), true);
});

test('routine viewport refresh retains the live iframe and draft', () => {
  let ribbon = 0, annotations = 0;
  const context = vm.createContext({
    state: { activeTab: 'training' }, trainingState: { type: 'packaging_shipping' },
    document: { getElementById: () => ({ isConnected: true }) },
    updateAnnotationToolbarVisibility: () => annotations++, renderRibbon: () => ribbon++,
    _save3DCameraState: () => { throw new Error('Unexpected remount path'); }
  });
  vm.runInContext(source('renderViewport'), context);
  vm.runInContext('renderViewport()', context);
  assert.equal(ribbon, 1); assert.equal(annotations, 1);
});

test('cancelled tab and workflow changes retain packaging selection', () => {
  const context = vm.createContext({ state: { activeTab: 'training' },
    trainingState: { type: 'facility_layout' }, _packagingConfirmLeave: () => false });
  vm.runInContext(source('switchTab'), context);
  assert.equal(vm.runInContext("switchTab('assembly')", context), false);
  assert.equal(context.state.activeTab, 'training');
  vm.runInContext(source('_trainApplyTrainingTypeDefaults'), context);
  assert.equal(vm.runInContext("_trainApplyTrainingTypeDefaults('packaging_shipping')", context), false);
  assert.equal(context.trainingState.type, 'packaging_shipping');
});

test('pilot is explicitly gated and does not silently use the facility Sage route', () => {
  assert.ok(html.includes("get('packagingPilot') === '1'"));
  assert.ok(html.includes("frame.id = 'packagingWorkspaceFrame'"));
  assert.ok(html.includes('Packaging chat execution is not enabled'));
  const server = fs.readFileSync(path.join(__dirname, '../server.py'), 'utf8');
  assert.ok(server.includes('INSPECTORPRO_PACKAGING_ENABLED'));
  assert.ok(server.includes('_PACKAGING_SERVICE'));
});
