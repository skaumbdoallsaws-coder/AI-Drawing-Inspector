'use strict';

const assert = require('assert');
const runtime = require('../static/chat_memory_runtime.js');

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

test('semantic targets are sorted, deduplicated, and complete', () => {
    assert.deepStrictEqual(runtime.normalizeSemanticTargets({
        processMapNodeIds: ['node-b', 'node-a', 'node-a', ''],
    }), {
        partOccurrenceIds: [],
        processMapNodeIds: ['node-a', 'node-b'],
        processMapEdgeIds: [],
        facilityPlacementIds: [],
        faiCharacteristicIds: [],
    });
});

test('semantic targets are captured from live workflow selections', () => {
    const targets = runtime.semanticTargetsFromAttachments({
        process_map: { state: { selection: {
            nodeIds: ['node-2', 'node-1'], edgeIds: ['edge-1'],
        } } },
        facility_layout: { state: { selection: {
            placementIds: ['placement-2'],
        } } },
    });
    assert.deepStrictEqual(targets.processMapNodeIds, ['node-1', 'node-2']);
    assert.deepStrictEqual(targets.processMapEdgeIds, ['edge-1']);
    assert.deepStrictEqual(targets.facilityPlacementIds, ['placement-2']);
});

test('decorated requests carry the complete memory identity', () => {
    const payload = runtime.decoratePayload({
        message: 'Inspect this.', inspection_context: { attachments: {} },
    }, {
        conversationId: 'conv-1',
        agentSessionId: 'session-1',
        clientTurnId: 'turn-1',
        semanticTargets: { processMapNodeIds: ['node-1'] },
    });
    assert.strictEqual(payload.conversation_id, 'conv-1');
    assert.strictEqual(payload.agent_session_id, 'session-1');
    assert.strictEqual(payload.client_turn_id, 'turn-1');
    assert.strictEqual(payload.memory_schema_version, '1.0');
    assert.strictEqual(payload.request_hash_version, 1);
    assert.deepStrictEqual(payload.request_context.semantic_targets.processMapNodeIds, ['node-1']);
});

test('request snapshots are deeply frozen and detached', () => {
    const source = { message: 'A', request_context: { semantic_targets: { processMapNodeIds: ['n1'] } } };
    const frozen = runtime.frozenRequest(source);
    source.message = 'B';
    source.request_context.semantic_targets.processMapNodeIds.push('n2');
    assert.strictEqual(frozen.message, 'A');
    assert.deepStrictEqual(frozen.request_context.semantic_targets.processMapNodeIds, ['n1']);
    assert(Object.isFrozen(frozen.request_context.semantic_targets.processMapNodeIds));
});

test('client turn IDs use the supplied UUID exactly once', () => {
    let calls = 0;
    const id = runtime.createClientTurnId(() => { calls += 1; return 'uuid-1'; }, 1000);
    assert.strictEqual(id, 'client-turn:rs:uuid-1');
    assert.strictEqual(calls, 1);
});

test('structured memory errors preserve stable server codes', () => {
    assert.deepStrictEqual(runtime.memoryError(503, {
        detail: { error: { code: 'memory_unavailable', message: 'Unavailable.' } },
    }), { code: 'memory_unavailable', message: 'Unavailable.', status: 503 });
});

test('legacy records become immutable archives without changing content', () => {
    const archived = runtime.markLegacyArchive({ id: 'chat-1', title: 'Old', state: { value: 3 } });
    assert.strictEqual(archived.backing, 'legacy');
    assert.strictEqual(archived.readOnly, true);
    assert.deepStrictEqual(archived.state, { value: 3 });
});

test('server conversation summaries are canonical cache records', () => {
    const record = runtime.serverConversationSummary({
        conversationId: 'conv-1', title: 'Pilot', createdAt: '2026-08-07T00:00:00Z',
        updatedAt: '2026-08-07T01:00:00Z', lastTurnSequence: 4,
    });
    assert.strictEqual(record.id, 'conv-1');
    assert.strictEqual(record.backing, 'server');
    assert.strictEqual(record.lastTurnSequence, 4);
});

if (!process.exitCode) console.log(`${passed}/${passed} passed`);
