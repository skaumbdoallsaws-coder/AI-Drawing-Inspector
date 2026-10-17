'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');

function implementation(name) {
    let start = html.indexOf('function ' + name + '(');
    assert.ok(start >= 0, name);
    if (html.slice(start - 6, start) === 'async ') start -= 6;
    const open = html.indexOf('{', start);
    let depth = 0;
    for (let i = open; i < html.length; i++) {
        if (html[i] === '{') depth++;
        if (html[i] === '}' && --depth === 0) return html.slice(start, i + 1);
    }
    throw new Error('Unterminated function: ' + name);
}

test('a delayed new conversation cannot accept a send or another conversation operation', async () => {
    let finishCreate;
    let creates = 0;
    let loads = 0;
    const context = vm.createContext({
        _serverMemoryState: 'ready',
        isAnySessionWaiting: () => false,
        saveChatRegistryNow() {},
        _serverMemoryEnabled: () => true,
        _setServerMemoryState(state) { context._serverMemoryState = state; },
        _createServerBackedConversation() {
            creates++;
            return new Promise(resolve => { finishCreate = resolve; });
        },
        async _loadServerConversation(id) {
            assert.equal(id, 'new-chat');
            loads++;
            context._serverMemoryState = 'ready';
        },
        console,
    });
    for (const name of ['createNewConversation', 'handleAgentSend', 'switchConversation', 'clearCurrentConversation']) {
        vm.runInContext(implementation(name), context);
    }
    const pending = context.createNewConversation();
    assert.equal(context._serverMemoryState, 'initializing');
    await context.handleAgentSend();
    await context.createNewConversation();
    await context.switchConversation('other');
    await context.clearCurrentConversation();
    assert.equal(creates, 1);
    assert.equal(loads, 0);
    finishCreate({ id: 'new-chat' });
    await pending;
    assert.equal(context._serverMemoryState, 'ready');
    assert.equal(loads, 1);
});

test('memory transition disables composer and Send, restores them, and keeps Stop usable', () => {
    const session = { waiting: false, activeStream: null };
    const button = { setAttribute(name, value) { this[name] = value; } };
    const indicator = { dataset: {}, setAttribute() {} };
    const context = vm.createContext({
        _serverMemoryState: 'ready',
        agentInput: { value: 'Inspect this layout', disabled: false },
        agentCapturedImage: null,
        agentSendBtn: button,
        voiceMicBtn: {},
        micState: 'idle',
        _agentSendDefaultMarkup: 'Send',
        getCurrentAgentSession: () => session,
        _currentConversationIsLegacyArchive: () => false,
        syncAgentInputHeight() {},
        document: { getElementById: () => indicator },
    });
    vm.runInContext(implementation('updateSendButtonState'), context);
    vm.runInContext(implementation('_setServerMemoryState'), context);
    context._setServerMemoryState('initializing');
    assert.equal(context.agentInput.disabled, true);
    assert.equal(button.disabled, true);
    assert.equal(indicator.dataset.state, 'initializing');
    context._setServerMemoryState('ready');
    assert.equal(context.agentInput.disabled, false);
    assert.equal(button.disabled, false);
    session.activeStream = {};
    context._setServerMemoryState('unavailable');
    assert.equal(button.disabled, false);
    assert.equal(button['aria-label'], 'Stop generating');
});
