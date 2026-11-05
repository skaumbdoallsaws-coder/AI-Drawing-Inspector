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
  const context = vm.createContext({ _packagingActiveTurn: null, _packagingReleasePromise: null,
    document: { getElementById: () => ({ contentWindow: {
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

test('workspace navigation waits for cancellation and reconciliation acknowledgement', async () => {
  let release, resumed = 0;
  const drained = new Promise(resolve => { release = resolve; });
  const context = vm.createContext({ _packagingActiveTurn: {}, _packagingReleasePromise: null,
    document: { getElementById: () => ({ contentWindow: { InspectorProPackaging: { isLocked: () => true } } }) },
    window: { InspectorProPackagingHost: { release: () => drained } }, resume: () => resumed++ });
  vm.runInContext(source('_packagingConfirmLeave'), context);
  assert.equal(vm.runInContext('_packagingConfirmLeave(resume)', context), false);
  assert.equal(resumed, 0); release(); await drained; await Promise.resolve();
  assert.equal(resumed, 1);
});

test('failed reconciliation prevents workflow switch and reports the retained lock', async () => {
  let resumed = 0, reported = '';
  const context = vm.createContext({ _packagingActiveTurn: {}, _packagingReleasePromise: null,
    document: { getElementById: () => null },
    window: { InspectorProPackagingHost: { release: async () => { throw new Error('Revoke refused'); } },
      _toast: message => { reported = message; } }, resume: () => resumed++ });
  vm.runInContext(source('_packagingConfirmLeave'), context);
  assert.equal(vm.runInContext('_packagingConfirmLeave(resume)', context), false);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(resumed, 0); assert.match(reported, /remains locked.*Revoke refused/);
});

test('public release aborts and awaits the active turn before requesting editor unlock', async () => {
  const events = [];
  let drain;
  const turn = { cancelled: false, controller: { abort: () => events.push('abort') },
    done: new Promise(resolve => { drain = resolve; }) };
  const fakeBridge = { release: async () => { events.push('release'); return { state: 'idle' }; } };
  const start = html.indexOf('        let _packagingBridgePromise = null;');
  const end = html.indexOf('        function _packagingConfirmLeave(', start);
  const context = vm.createContext({ window: {}, fakeBridge, turn });
  vm.runInContext(html.slice(start, end), context);
  vm.runInContext('_packagingBridgePromise = Promise.resolve(fakeBridge); _packagingActiveTurn = turn;', context);
  const released = context.window.InspectorProPackagingHost.release();
  assert.equal(context.window.InspectorProPackagingHost.release(), released);
  assert.equal(turn.cancelled, true); assert.deepEqual(events, ['abort']);
  drain(); await released; assert.deepEqual(events, ['abort', 'release']);
});

test('packaging attachments are admission-only and cannot inherit viewport or document context', () => {
  const start = html.indexOf('            function buildAgentAttachments(');
  const end = html.indexOf('\n            window.__workflowDbg', start + 1);
  const context = vm.createContext({
    state: { activeTab: 'training' }, trainingState: { type: 'packaging_shipping' }, currentAgent: 'deviation-analyst',
    getAgentSession: () => ({}), _packagingActiveTurn: { admitted: { admission_id: 'adm_one' } },
  });
  vm.runInContext(html.slice(start, end), context);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(buildAgentAttachments())', context)), {
    schema_version: 1, session: { agent: 'deviation-analyst', active_tab: 'training', active_mode: 'packaging_shipping' },
    packaging: { admission_id: 'adm_one' },
  });
  context._packagingActiveTurn = null;
  assert.throws(() => vm.runInContext('buildAgentAttachments()', context), /admission is required/);
});

test('packaging terminal paths are streaming-only, reconcile in finally, and bypass legacy tools', () => {
  const start = html.indexOf('            async function handleAgentSend(');
  const handler = html.slice(start, html.indexOf('            async function handleScoutSearchSend(', start));
  assert.match(html, /packagingMode && !codexPackaging/);
  assert.match(html, /status\?\.packagingRuntime === 'codex'/);
  assert.match(html, /event\.phase === 'codex_packaging'/);
  assert.match(handler, /if \(packagingTurn\) throw new Error\('Packaging requires the streaming backend/);
  assert.match(handler, /if \(packagingTurn \|\| data\.tool_source === 'codex_packaging'\)/);
  assert.match(handler, /finally \{\s+if \(packagingTurn\) \{\s+try \{\s+await window\.InspectorProPackagingHost\.finish\(packagingTerminal\)/);
  assert.match(handler, /Saved edits may remain/);
  assert.match(handler, /packagingTurn\.resolve\(\)/);
});

test('agent and conversation changes drain an active admission but do not discard an idle draft', () => {
  let guarded = 0;
  const context = vm.createContext({ _packagingActiveTurn: null, _packagingReleasePromise: null,
    document: { getElementById: () => ({ contentWindow: { InspectorProPackaging: { isLocked: () => false } } }) },
    _packagingConfirmLeave: () => { guarded++; return false; } });
  vm.runInContext(source('_packagingConfirmChatChange'), context);
  assert.equal(vm.runInContext('_packagingConfirmChatChange()', context), true); assert.equal(guarded, 0);
  context._packagingActiveTurn = {};
  assert.equal(vm.runInContext('_packagingConfirmChatChange()', context), false); assert.equal(guarded, 1);
  for (const call of ['selectAgent(agentKey)', 'switchConversation(convId)', 'createNewConversation()', 'clearCurrentConversation()']) {
    assert.ok(html.includes('_packagingConfirmChatChange(() => ' + call + ')'), call);
  }
});

test('memory identity binds the admitted document and saved revision before freezing the request', () => {
  const context = vm.createContext({});
  vm.runInContext(source('_packagingRequestContext'), context);
  const actual = vm.runInContext("_packagingRequestContext({document_id:'pkg_one',revision:0}, {semantic_targets:{partOccurrenceIds:[]}})", context);
  assert.deepEqual(JSON.parse(JSON.stringify(actual)), {
    semantic_targets: { partOccurrenceIds: [] },
    asset_scope: { kind: 'packaging_shipping', ids: { documentId: 'pkg_one' }, expectedRevisionVector: { packagingRevision: '0' } },
  });
  assert.throws(() => vm.runInContext("_packagingRequestContext({document_id:'pkg_one',revision:'4'})", context), /saved packaging revision/);
  const handler = html.slice(html.indexOf('            async function handleAgentSend('));
  assert.ok(handler.indexOf('payload.request_context = _packagingRequestContext') < handler.indexOf('frozenTurnRequest = _chatMemoryRuntime.frozenRequest'));
});

test('packaging HTTP failures retain structured mutation receipts and never use legacy fallback', async () => {
  const start = html.indexOf('            async function _requestAgentChatStream(');
  const end = html.indexOf('\n            window.__agentChatStreamV1', start);
  const receipts = { documentId: 'pkg_one', revision: 5, mutationOutcome: 'committed', mutations: [{ after_revision: 5 }] };
  let calls = 0;
  const context = vm.createContext({
    AbortController, _getChatStreamingStatus: async () => ({ packagingRuntime: 'codex' }),
    _agentReasoningEffort: () => '', agentReasoningUiSelection: '', _packagingActiveTurn: null,
    _trainFacilityLayoutAuthoringApp: null, setWaiting() {},
    _chatMemoryRuntime: require('../static/chat_memory_runtime.js'),
    fetch: async () => { calls++; return new Response(JSON.stringify({ detail: { error: {
      code: 'revision_conflict', message: 'Changed', codex_packaging: receipts,
    } } }), { status: 409 }); },
  });
  vm.runInContext(html.slice(start, end), context);
  const payload = { inspection_context: { attachments: { session: { active_mode: 'packaging_shipping' } } } };
  const session = { chatSessionId: 'session_1' };
  await assert.rejects(context._requestAgentChatStream(payload, 'deviation-analyst', session, 1, { enableSteps() {} }), error => {
    assert.deepEqual(error.codex_packaging, receipts); assert.equal(error.status, 409); return true;
  });
  assert.equal(calls, 1); assert.equal(session.activeStream, null);
  context._getChatStreamingStatus = async () => ({ packagingRuntime: 'disabled', enabled: true, agents: ['sage'] });
  await assert.rejects(context._requestAgentChatStream(payload, 'deviation-analyst', session, 2, {}), /not enabled/);
  assert.equal(calls, 1);
});
