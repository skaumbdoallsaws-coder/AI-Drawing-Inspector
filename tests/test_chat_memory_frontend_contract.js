'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
    path.resolve(__dirname, '..', 'static', 'index.html'),
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

function body(name) {
    const start = source.indexOf(`function ${name}(`);
    assert(start >= 0, `missing ${name}`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for (let index = open; index < source.length; index += 1) {
        if (source[index] === '{') depth += 1;
        if (source[index] === '}') depth -= 1;
        if (depth === 0) return source.slice(open + 1, index);
    }
    throw new Error(`unterminated ${name}`);
}

test('the memory runtime loads before the application script', () => {
    const runtime = source.indexOf('/static/chat_memory_runtime.js');
    const application = source.indexOf('InspectorPro - Frontend Application Logic');
    assert(runtime >= 0 && runtime < application);
});

test('boot reconciles conversations from the server', () => {
    const init = body('_initializeServerMemory');
    assert(init.includes("'/api/agent/conversations?limit=50'"));
    assert(init.includes('_archiveLegacyLocalConversations()'));
    assert(init.includes('_loadServerConversation(targetId, true)'));
    assert(source.includes('_serverMemoryReady = _initializeServerMemory()'));
});

test('legacy local chats are read-only archives and are never uploaded', () => {
    const archive = body('_archiveLegacyLocalConversations');
    assert(archive.includes('markLegacyArchive(record)'));
    assert(!archive.includes('fetch('));
    assert(source.includes('Legacy conversation archive (read only)'));
});

test('server restore separates committed history by agent type', () => {
    const hydrate = body('_hydrateServerConversation');
    assert(hydrate.includes('serverTypeToUiAgent'));
    assert(hydrate.includes('_serverMessageToLocal(raw, summary.id)'));
    assert(hydrate.includes('target.workflowState = _serverMemoryAuthoritative()'));
});

test('enforce requests exclude browser transcript authority', () => {
    const sendStart = source.indexOf('async function handleAgentSend(');
    const sendEnd = source.indexOf('// === Scout Browser Search', sendStart);
    const send = source.slice(sendStart, sendEnd);
    assert(send.includes("history: _serverMemoryAuthoritative()"));
    assert(send.includes('? [] : historyForApi'));
    assert(send.includes('_chatMemoryRuntime.decoratePayload'));
});

test('shadow and compare collect memory without replacing legacy prompt state', () => {
    const authoritative = body('_serverMemoryAuthoritative');
    assert(authoritative.includes("_serverMemoryMode === 'enforce'"));
    assert(!authoritative.includes('shadow'));
    assert(!authoritative.includes('compare'));
    const attachments = body('buildAgentAttachments');
    assert(attachments.includes('!_serverMemoryAuthoritative()'));
    assert(attachments.includes('skill_workflow_state'));
    const persisted = body('serializeSessionForPersistence');
    assert(persisted.includes('_serverMemoryAuthoritative() ? null'));
});

test('retry replays the immutable request identity', () => {
    const retry = body('_showAgentStreamRetry');
    assert(retry.includes('handleAgentSend({'));
    assert(retry.includes('frozenRequest'));
    const sendStart = source.indexOf('async function handleAgentSend(');
    const sendEnd = source.indexOf('// === Scout Browser Search', sendStart);
    const send = source.slice(sendStart, sendEnd);
    assert(send.includes('payload = _chatMemoryRuntime.clone('));
    assert(send.includes('retry.frozenRequest'));
    assert(send.includes('_chatMemoryRuntime.frozenRequest('));
});

test('Scout search uses durable identity and acknowledges terminal commit', () => {
    const send = body('handleScoutSearchSend');
    assert(send.includes('_chatMemoryRuntime.decoratePayload'));
    assert(send.includes('_chatMemoryRuntime.frozenRequest('));
    assert(send.includes("case 'response':"));
    assert(send.includes('memoryResult = ev.memory'));
    assert(send.includes("'committed'"));
    assert(send.includes('_showAgentStreamRetry('));
    const routeStart = source.indexOf("if (currentAgent === 'parts-finder')");
    assert(routeStart >= 0);
    const route = source.slice(routeStart, routeStart + 180);
    assert(route.includes('handleScoutSearchSend(retry)'));
    assert(!route.includes('!_serverMemoryEnabled()'));
});

test('server deletion replaces the deleted conversation', () => {
    const clear = body('clearCurrentConversation');
    assert(clear.includes("{ method: 'DELETE' }"));
    assert(clear.includes('delete _chatRegistry.conversations[_currentConversationId]'));
    assert(clear.includes('_createServerBackedConversation()'));
});

test('memory failures are visible and block local action fallback', () => {
    assert(source.includes('Memory unavailable; no action was executed.'));
    assert(source.includes("_setServerMemoryState('unavailable'"));
    const sendStart = source.indexOf('async function handleAgentSend(');
    const sendEnd = source.indexOf('// === Scout Browser Search', sendStart);
    const send = source.slice(sendStart, sendEnd);
    const memoryBranch = send.indexOf('} else if (_serverMemoryEnabled()) {');
    const legacyFallback = send.indexOf('// Fallback: provide contextual response locally');
    assert(memoryBranch >= 0 && legacyFallback > memoryBranch);
});

test('conversation transitions block send and cannot be marked ready by UI sync', () => {
    for (const name of ['handleAgentSend', 'createNewConversation', 'switchConversation', 'clearCurrentConversation']) {
        assert(body(name).includes("if (_serverMemoryState === 'initializing') return;"), name);
    }
    assert(body('updateSendButtonState').includes("['initializing', 'unavailable'].includes(_serverMemoryState)"));
    assert(body('_setServerMemoryState').includes('updateSendButtonState()'));
    assert(body('_syncChatUI').includes("&& _serverMemoryState !== 'initializing'"));
    assert(body('_syncChatUI').includes("if (archived && _serverMemoryState !== 'initializing')"));
    const load = body('_loadServerConversation');
    assert(load.indexOf("_setServerMemoryState('initializing'") < load.indexOf('await _serverMemoryJson('));
});

test('sending consumes the persisted draft before message persistence for Sage and Scout', () => {
    for (const name of ['handleAgentSend', 'handleScoutSearchSend']) {
        const send = body(name);
        const clear = send.indexOf("originSession.pendingInput = '';");
        assert(clear >= 0 && clear < send.indexOf("addMessage(displayText, 'user', originAgent)"), name);
    }
});

if (!process.exitCode) console.log(`${passed}/${passed} passed`);
