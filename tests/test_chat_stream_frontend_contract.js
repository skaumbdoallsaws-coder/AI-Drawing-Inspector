'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'index.html'), 'utf8');
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
    const handlerStart = html.indexOf('async function handleAgentSend()');
    const handlerEnd = html.indexOf('// === Scout Browser Search', handlerStart);
    const handler = html.slice(handlerStart, handlerEnd);
    const streamCall = handler.indexOf('_requestAgentChatStream(');
    const execution = handler.indexOf('await executeToolCalls(');
    assert(streamCall >= 0 && execution > streamCall);
});

test('the final receipt-grounded response commits the provisional bubble', () => {
    const normalBranch = html.indexOf('if (streamingAssistant) streamingAssistant.commit(response)');
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

test('markdown is applied only by the terminal streaming renderer', () => {
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
    assert(!provisional.includes('formatMessageText('));
    assert(finalRenderer.includes('formatMessageText('));
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
    assert(html.includes('function _showAgentStreamRetry(agentKey, originalText, failedStreamMessage)'));
});

test('provider failures never fall through to the generic part-loaded response', () => {
    const streamStart = html.indexOf('async function _requestAgentChatStream(');
    const streamEnd = html.indexOf('window.__agentChatStreamV1 =', streamStart);
    const stream = html.slice(streamStart, streamEnd);
    const handlerStart = html.indexOf('async function handleAgentSend()');
    const handlerEnd = html.indexOf('// === Scout Browser Search', handlerStart);
    const handler = html.slice(handlerStart, handlerEnd);
    assert(stream.includes('failed.agentServiceFailure = true'));
    assert(stream.includes('if (error.agentServiceFailure)'));
    assert(handler.includes('} else if (err && err.agentServiceFailure) {'));
    assert(handler.includes('_agentServiceFailureText(originAgent, err)'));
    assert(handler.includes('streamTurnFailed = true;'));
});

test('send button aborts instead of starting a second turn', () => {
    assert(html.includes('session.activeStream.controller.abort()'));
});

test('Scout owns its streaming controller and provisional message', () => {
    const start = html.indexOf('async function handleScoutSearchSend()');
    const end = html.indexOf('// Add a system-style notification message', start);
    const scout = html.slice(start, end);
    assert(start >= 0 && end > start);
    assert(scout.includes('const scoutController = new AbortController()'));
    assert(scout.includes('signal: scoutController.signal'));
    assert(scout.includes("source: 'scout_provider_stream'"));
    assert(scout.includes("case 'text_delta'"));
    assert(scout.includes("scoutStreamingMessage.commit(fullResponse || 'Search completed.')"));
});

test('Scout state does not leak into the Sage or Iris send path', () => {
    const mainStart = html.indexOf('async function handleAgentSend()');
    const scoutStart = html.indexOf('async function handleScoutSearchSend()');
    const main = html.slice(mainStart, scoutStart);
    assert(mainStart >= 0 && scoutStart > mainStart);
    assert(!main.includes('scoutController'));
    assert(!main.includes('scoutActiveStream'));
});

console.log(passed + ' passed, ' + (process.exitCode ? 1 : 0) + ' failed');
