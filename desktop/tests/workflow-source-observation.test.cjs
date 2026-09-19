'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const observation = require('../../static/desktop_workflow_observation.js');
const html = fs.readFileSync(path.join(__dirname, '../../static/index.html'), 'utf8');
const begin = html.indexOf('        function _desktopInspectOtherWorkflows() {');
const end = html.indexOf('        function setupEventListeners() {', begin);
assert.ok(begin >= 0 && end > begin);
const source = html.slice(begin, end);
function fixture() {
  const empty = () => ({ loaded: false, dirty: false, busy: false, pending: false });
  const context = vm.createContext({
    state: { faiMeasurements: {}, faiVerdicts: {}, faiTolOverrides: {}, assemblyPartDisplayOverrides: {},
      pendingExecutionReceipts: [], partsManualDraftOccurrenceIds: new Set() },
    trainingState: { type: 'facility_layout', goal: 'Answer facility layout questions.' },
    annoState: { shapes: [] }, regionsCuratorState: {},
    sessionsTabState: { actionBusy: {}, syncPreviews: {}, refreshResults: {} },
    window: { __agentChatStreamV1: { getDesktopLifecycleObservation: empty } },
    _trainCurrentProcessFlowEditor: () => null,
  });
  vm.runInContext(source, context);
  return { context, read: () => observation.capture(context._desktopInspectOtherWorkflows(), 'r') };
}
test('actual application observer excludes the facility goal from unrelated training work', () => {
  const f = fixture(); assert.doesNotThrow(() => observation.assertEmpty(f.read(), 'r'));
});

for (const [name, inject, workflowId] of [
  ['manual drawing annotations', c => { c.annoState.shapes.push({ type: 'line' }); }, 'drawing'],
  ['FAI measurement', c => { c.state.faiMeasurements.diameter = '12'; }, 'drawing'],
  ['inspection in progress', c => { c.state.inspecting = true; }, 'drawing'],
  ['loaded 3D part', c => { c.state.threeLoadedPart = 'part'; }, 'model'],
  ['assembly receipt', c => { c.state.pendingExecutionReceipts.push({ id: 'receipt' }); }, 'assembly'],
  ['hidden process map with history', c => { c._trainCurrentProcessFlowEditor = () => ({ dirty: false, history: { undoStack: [{}] } }); }, 'processMap'],
  ['unmounted process draft', c => { c.trainingState.processMapFlowDirty = true; }, 'processMap'],
  ['process map approval in flight', c => { c._trainCurrentProcessFlowEditor = () => ({ managedProposalBusy: true }); }, 'processMap'],
  ['documentation generation', c => { c.state.partsManualDocumentationGeneration = { id: 'generation' }; }, 'documentation'],
  ['non-facility training goal', c => { c.trainingState.type = 'operator'; }, 'training'],
  ['report', c => { c.state.results = { findings: [] }; }, 'report'],
  ['edit session action', c => { c.sessionsTabState.actionBusy.s1 = true; }, 'sessions'],
  ['microphone', c => { c.window.__agentChatStreamV1.getDesktopLifecycleObservation = () => ({ loaded: false, dirty: false, busy: true, pending: false }); }, 'agent'],
  ['curation Save', c => { c.regionsCuratorState.saving = true; }, 'curation'],
]) {
  test('actual application observer catches ' + name, () => {
    const f = fixture(); inject(f.context);
    assert.throws(() => observation.assertEmpty(f.read(), 'r'), error => {
      assert.equal(error.code, 'desktop_workflow_recovery_not_enabled');
      assert.ok(error.workflows.includes(workflowId)); return true;
    });
  });
}

test('missing agent observer does not claim chat or voice is clean', () => {
  const f = fixture(); delete f.context.window.__agentChatStreamV1;
  assert.throws(f.read, /desktop_agent_observation_unavailable/);
});
