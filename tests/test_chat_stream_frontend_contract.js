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

console.log(passed + ' passed, ' + (process.exitCode ? 1 : 0) + ' failed');
