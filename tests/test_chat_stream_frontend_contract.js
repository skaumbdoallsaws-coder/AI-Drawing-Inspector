'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
const workspace = fs.readFileSync(
    path.join(__dirname, '..', 'static', 'facility_layout_workspace.js'),
    'utf8'
);
let passed = 0;
function test(name, fn) {
    try {
        fn();
        passed += 1;
        console.log('PASS ' + name);
    } catch (error) {
        console.error('FAIL ' + name + ': ' + error.message);
        process.exitCode = 1;
    }
}

test('pending assistant messages are excluded from API history', () => {
    assert(html.includes("&& !(m.meta && m.meta.pending)"));
});

test('pending assistant messages are excluded from persistence', () => {
    assert(html.includes(".filter(msg => !(msg.meta && msg.meta.pending))"));
});

test('tool execution remains after terminal stream consumption', () => {
    const handlerStart = html.indexOf('async function handleAgentSend(');
    const handlerEnd = html.indexOf('// === Scout Browser Search', handlerStart);
    const handler = html.slice(handlerStart, handlerEnd);
    const streamCall = handler.indexOf('_requestAgentChatStream(');
    const execution = handler.indexOf('await executeToolCalls(');
    assert(streamCall >= 0 && execution > streamCall);
});

test('the final receipt-grounded response commits the provisional bubble', () => {
    const normalBranch = html.indexOf('if (streamingAssistant) streamingAssistant.commit(response, assistantPresentation)');
    const receiptStatus = html.indexOf('_receiptGroundedStatusLine(');
    assert(receiptStatus >= 0 && normalBranch > receiptStatus);
});

test('provisional bubbles use the visual queue and plain text DOM updates', () => {
    const start = html.indexOf('function createStreamingAssistantMessage(');
    const end = html.indexOf('function createPlantWalkStreamingMessage(', start);
    const streaming = html.slice(start, end);
    assert(start >= 0 && end > start);
    assert(streaming.includes('createVisualTextQueue'));
    assert(streaming.includes('cachedTextNode.appendData'));
    assert(streaming.includes('const schedulePump'));
    assert(streaming.includes('const renderFinal'));
});

test('rich rendering is applied only by the terminal streaming renderer', () => {
    const start = html.indexOf('function createStreamingAssistantMessage(');
    const end = html.indexOf('function createPlantWalkStreamingMessage(', start);
    const streaming = html.slice(start, end);
    const provisional = streaming.slice(
        streaming.indexOf('const renderProvisional'),
        streaming.indexOf('const renderFinal')
    );
    const finalRenderer = streaming.slice(
        streaming.indexOf('const renderFinal'),
        streaming.indexOf('const schedulePump')
    );
    assert(!provisional.includes('renderMessageToDOM('));
    assert(finalRenderer.includes('renderMessageToDOM(msg, agentKey)'));
    assert(finalRenderer.includes('row.replaceWith(replacement)'));
});

test('working state is separate from an answer message', () => {
    assert(html.includes('const RESPONSE_UI_STATES = Object.freeze'));
    assert(html.includes('function createAgentWorkingState('));
    assert(html.includes("compass.src = '/static/logo.svg'"));
    assert(html.includes("workingState.beginStreaming()"));
});

test('answer bubble promotion requires a visible text delta', () => {
    const start = html.indexOf('async function _requestAgentChatStream(');
    const end = html.indexOf('window.__agentChatStreamV1 =', start);
    const stream = html.slice(start, end);
    assert(start >= 0 && end > start);
    assert(stream.includes("if (!/\\S/.test(delta)) break;"));
    assert(stream.includes('beginStreaming().appendInitialText(preambleText)'));
    assert(stream.includes('showStatus: false'));
});

test('stream failures retain rendered partial text and attach retry to it', () => {
    assert(html.includes("err.streamingMessage.fail('Response interrupted. Retry the request to continue.')"));
    assert(html.includes('function _showAgentStreamRetry('));
    assert(html.includes('frozenRequest'));
});

test('provider failures never fall through to the generic part-loaded response', () => {
    const streamStart = html.indexOf('async function _requestAgentChatStream(');
    const streamEnd = html.indexOf('window.__agentChatStreamV1 =', streamStart);
    const stream = html.slice(streamStart, streamEnd);
    const handlerStart = html.indexOf('async function handleAgentSend(');
    const handlerEnd = html.indexOf('// === Scout Browser Search', handlerStart);
    const handler = html.slice(handlerStart, handlerEnd);
    assert(stream.includes('failed.agentServiceFailure = parsed.code !=='));
    assert(stream.includes('if (error.agentServiceFailure)'));
    assert(handler.includes('} else if (err && err.agentServiceFailure) {'));
    assert(handler.includes('_agentServiceFailureText(originAgent, err)'));
    assert(handler.includes('streamTurnFailed = true;'));
});

test('send button aborts instead of starting a second turn', () => {
    assert(html.includes('session.activeStream.controller.abort()'));
});

test('Scout owns its streaming controller and provisional message', () => {
    const start = html.indexOf('async function handleScoutSearchSend(');
    const end = html.indexOf('// Add a system-style notification message', start);
    const scout = html.slice(start, end);
    assert(start >= 0 && end > start);
    assert(scout.includes('const scoutController = new AbortController()'));
    assert(scout.includes('signal: scoutController.signal'));
    assert(scout.includes("source: 'scout_provider_stream'"));
    assert(scout.includes("case 'text_delta'"));
    assert(scout.includes('scoutStreamingMessage.commit(fullResponse, scoutPresentation)'));
});

test('terminal presentation links feedback and structured blocks to the exact run', () => {
    assert(html.includes('function _assistantTerminalPresentation('));
    assert(html.includes('memoryEnvelopeSha256'));
    assert(html.includes('contextManifestId'));
    assert(html.includes('serverMessageId'));
    assert(html.includes('toolSource: String('));
    assert(html.includes('payload.tool_source || payload.toolSource'));
    assert(html.includes('latestAssistantToolSource()'));
    assert(html.includes('contentBlocks: _assistantResponseBlocks(payload)'));
});

test('chat runtime exposes bounded operational working states', () => {
    assert(html.includes('createWorkingState: ensureAgentWorkingState'));
    const start = html.indexOf('function _agentWorkingOperationLabel(');
    const end = html.indexOf('function createAgentWorkingState(', start);
    const label = html.slice(start, end);
    assert(start >= 0 && end > start);
    assert(label.includes("searching: 'Searching sources'"));
    assert(!label.toLowerCase().includes('chain-of-thought'));
});

test('thinking indicator uses a scoped blue halo and stops before leaving', () => {
    assert(html.includes('.agent-working-compass-shell::before'));
    assert(html.includes('animation: agentWorkingHalo 1.8s ease-in-out infinite'));
    assert(html.includes('animation: agentWorkingCompassRotate 3.5s linear infinite'));
    assert(html.includes('0 0 22px rgba(0, 145, 255, 0.18)'));
    assert(html.includes('.agent-working-row.is-stopped .agent-working-compass'));
    assert(html.includes("currentRow.classList.add('is-stopped')"));
    assert(html.includes("nextRow.setAttribute('role', 'status')"));
    assert(html.includes("nextRow.setAttribute('aria-live', 'polite')"));

    const start = html.indexOf('function createAgentWorkingState(');
    const end = html.indexOf('function ensureAgentWorkingState(', start);
    const working = html.slice(start, end);
    assert(start >= 0 && end > start);
    for (const transition of ['beginStreaming', 'complete', 'cancel', 'error']) {
        const signature = transition === 'error'
            ? 'error: (operation) =>'
            : `${transition}: () =>`;
        const transitionStart = working.indexOf(signature);
        assert(transitionStart >= 0, `missing ${transition} transition`);
        assert(
            working.slice(transitionStart, transitionStart + 520).includes('stopAnimation()'),
            `${transition} does not stop the indicator animation`
        );
    }
});

test('Scout state does not leak into the Sage or Iris send path', () => {
    const mainStart = html.indexOf('async function handleAgentSend(');
    const scoutStart = html.indexOf('async function handleScoutSearchSend(');
    const main = html.slice(mainStart, scoutStart);
    assert(mainStart >= 0 && scoutStart > mainStart);
    assert(!main.includes('scoutController'));
    assert(!main.includes('scoutActiveStream'));
});

test('agent switching synchronizes the composer placeholder', () => {
    assert(html.includes('id="agentInput" placeholder="Message Iris..."'));
    assert(html.includes("let currentAgent = 'inspector';"));
    assert(html.includes('function _syncAgentInputPlaceholder()'));
    assert(html.includes("`Message ${AGENTS[currentAgent]?.name || 'agent'}...`"));
    const start = html.indexOf('function selectAgent(');
    const end = html.indexOf('// ---- Agent Context Bar', start);
    const selection = html.slice(start, end);
    assert(start >= 0 && end > start);
    assert(selection.includes('_syncAgentInputPlaceholder();'));
});

test('composer exposes UI-only reasoning levels instead of model names', () => {
    const start = html.indexOf('<div id="agentModelMenu"');
    const end = html.indexOf('<button id="agentSendBtn"', start);
    const menu = html.slice(start, end);
    assert(start >= 0 && end > start);
    assert(menu.includes('Reasoning level'));
    for (const level of ['High', 'Medium', 'Low']) {
        assert(menu.includes(`data-reasoning-level="${level}"`));
    }
    for (const model of ['Opus 4.7 Adaptive', 'Sonnet 4', 'GPT-5', 'GPT-5.4 Mini']) {
        assert(!menu.includes(model));
    }
    assert(html.includes("let agentReasoningUiSelection = 'High'; // UI-only placeholder"));
});

test('Facility design context and closed tools share the live workspace', () => {
    const attachmentStart = html.indexOf('function buildAgentAttachments(');
    const attachmentEnd = html.indexOf('function _facilityLayoutSemanticToolStatusLine(', attachmentStart);
    const attachment = html.slice(attachmentStart, attachmentEnd);
    assert(attachmentStart >= 0 && attachmentEnd > attachmentStart);
    assert(attachment.includes('getDesignReference'));
    for (const name of [
        'inspect_facility_design_brief',
        'update_facility_design_brief',
        'run_facility_design_preview',
        'apply_facility_design_proposal_draft',
    ]) {
        assert(html.includes(`${name}: {`), `missing ${name} browser tool`);
    }
    assert(workspace.includes("'Current baseline'"));
    assert(workspace.includes('facility_design_no_improved_alternative'));
});

test('Facility design apply and Undo are executed through exact editor transactions', () => {
    assert(html.includes('context.workspace.applySelectedDesignProposal()'));
    assert(html.includes('context.workspace.undoDesignProposal()'));
    assert(html.includes('if (data.facility_design_action)'));
    assert(html.includes("name: 'undo_facility_design_proposal'"));
});

console.log(passed + ' passed, ' + (process.exitCode ? 1 : 0) + ' failed');
