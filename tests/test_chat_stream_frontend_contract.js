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
