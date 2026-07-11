'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.resolve(__dirname, '..', 'static', 'index.html'), 'utf8');
let checks = 0;

function check(name, fn) {
    fn();
    checks += 1;
    process.stdout.write(`PASS ${name}\n`);
}

function functionBody(name) {
    const start = source.indexOf(`function ${name}(`);
    assert(start >= 0, `missing ${name}`);
    const brace = source.indexOf('{', start);
    let depth = 0;
    for (let index = brace; index < source.length; index += 1) {
        if (source[index] === '{') depth += 1;
        else if (source[index] === '}') {
            depth -= 1;
            if (depth === 0) return source.slice(brace + 1, index);
        }
    }
    throw new Error(`unterminated ${name}`);
}

check('agent sessions own stable workflow continuity fields', () => {
    const body = functionBody('createAgentSession');
    assert(body.includes('chatSessionId: _newAgentChatSessionId(agentKey)'));
    assert(body.includes('workflowState: null'));
    assert(body.includes('workflowStateEvent: null'));
});

check('workflow fields persist with the existing chat snapshot', () => {
    const body = functionBody('serializeSessionForPersistence');
    assert(body.includes('chatSessionId: session.chatSessionId'));
    assert(body.includes('workflowState: session.workflowState'));
    assert(body.includes('workflowStateEvent: session.workflowStateEvent'));
});

check('new and cleared chats rotate the session identity', () => {
    const reset = functionBody('resetAllSessions');
    assert(reset.includes('s.chatSessionId = _newAgentChatSessionId(key)'));
    assert(reset.includes('s.workflowState = null'));
    const empty = functionBody('buildEmptyConversationState');
    assert(empty.includes("createAgentSession('deviation-analyst')"));
});

check('asset identity excludes active tab and live viewport state', () => {
    const body = functionBody('_workflowAssetIdentity');
    assert(!body.includes('activeTab'));
    assert(!body.includes('motionPlaying'));
    assert(!body.includes('partExplorerAgentParts'));
    assert(body.includes('part_number'));
    assert(body.includes('assembly_number'));
    assert(body.includes('fai_revision'));
    assert(body.includes('motion_asset_pin'));
});

check('requests carry the stable session ID', () => {
    assert(source.includes('session_id: originSession.chatSessionId'));
});

check('workflow mirror travels only in session context', () => {
    const body = functionBody('buildAgentAttachments');
    assert(body.includes('att.session.skill_workflow_state'));
    assert(body.includes('asset_identity: _workflowAssetIdentity()'));
});

check('server response updates semantic state without viewport replay', () => {
    const body = functionBody('_applyServerWorkflowState');
    assert(body.includes('session.workflowState ='));
    assert(body.includes('scheduleChatRegistrySave()'));
    assert(!body.includes('_dispatchUiAction'));
    assert(!body.includes('playMotion'));
    assert(!body.includes('applyPartHighlight3D'));
});

check('workflow debug surface exposes state but no mutation command', () => {
    assert(source.includes('window.__workflowDbg ='));
    const blockStart = source.indexOf('window.__workflowDbg =');
    const block = source.slice(blockStart, blockStart + 1800);
    assert(block.includes('current: () =>'));
    assert(block.includes('forAgent: agentKey =>'));
    assert(!block.includes('setState'));
});

process.stdout.write(`${checks} passed, 0 failed\n`);
