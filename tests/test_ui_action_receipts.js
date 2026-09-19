'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const runtime = require(path.join(ROOT, 'static', 'ui_action_runtime.js'));
const contract = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'static', 'contracts', 'ui-action-contract-v1.json'), 'ascii'
));

let checks = 0;
function check(name, fn) {
    fn();
    checks += 1;
    process.stdout.write(`PASS ${name}\n`);
}

function baseState() {
    return {
        active_tab: 'assembly',
        highlight: { agent: [], manual: [] },
        display: { overrides: {} },
        motion: { playing: false, package_mode: true, motion_id: null, rpm: null, angle_deg: 0 },
        rotation: { assembly: false, part: false },
        process_map_selection: null,
        process_map_focus: null,
    };
}

check('valid bundle gets deterministic action IDs', () => {
    const result = runtime.validateBundle(contract, {
        workspace: 'assembly',
        actions: [
            { type: 'set_part_highlight', part_numbers: ['SYNTH-P1'], mode: 'replace' },
            { type: 'play_motion', motion_id: 'synthetic-cycle', rpm: 30, loop: true },
        ],
    });
    assert.strictEqual(result.ok, true);
    assert.deepStrictEqual(result.bundle.actions.map(action => action.action_id), ['a1', 'a2']);
});

check('unknown fields are rejected', () => {
    const result = runtime.validateBundle(contract, {
        workspace: 'assembly',
        actions: [{ type: 'play_motion', surprise: true }],
    });
    assert.strictEqual(result.ok, false);
    assert.deepStrictEqual(result.errors, ['action[0]:unknown_fields']);
});

check('conflicting actions are rejected', () => {
    const result = runtime.validateBundle(contract, {
        workspace: 'assembly',
        actions: [{ type: 'play_motion' }, { type: 'pause_motion' }],
    });
    assert.strictEqual(result.ok, false);
    assert.deepStrictEqual(result.errors, ['conflict:play_and_pause_conflict']);
});

check('highlight postcondition succeeds while preserving other domains', () => {
    const before = baseState();
    const after = baseState();
    after.highlight.agent = ['SYNTH-P1'];
    const verification = runtime.verifyPostcondition(
        contract,
        { type: 'set_part_highlight', action_id: 'a1', part_numbers: ['SYNTH-P1'], mode: 'replace' },
        before,
        after,
        true
    );
    assert.deepStrictEqual(verification, { ok: true });
});

check('unrelated state mutation fails the receipt canary', () => {
    const before = baseState();
    const after = baseState();
    after.highlight.agent = ['SYNTH-P1'];
    after.display.overrides['SYNTH-H1'] = { hidden: true };
    const verification = runtime.verifyPostcondition(
        contract,
        { type: 'set_part_highlight', action_id: 'a1', part_numbers: ['SYNTH-P1'], mode: 'replace' },
        before,
        after,
        true
    );
    assert.deepStrictEqual(verification, { ok: false, error: 'unrelated_state_changed:display' });
});

check('natural motion angle advance is not an unrelated mutation', () => {
    const before = baseState();
    before.motion.playing = true;
    before.motion.motion_id = 'synthetic-cycle';
    before.motion.rpm = 30;
    before.motion.angle_deg = 10;
    const after = JSON.parse(JSON.stringify(before));
    after.motion.angle_deg = 18;
    after.highlight.agent = ['SYNTH-P1'];
    const verification = runtime.verifyPostcondition(
        contract,
        { type: 'set_part_highlight', action_id: 'a1', part_numbers: ['SYNTH-P1'], mode: 'replace' },
        before,
        after,
        true
    );
    assert.deepStrictEqual(verification, { ok: true });
});

check('failed dispatch produces a failed receipt', () => {
    const before = baseState();
    const verification = runtime.verifyPostcondition(
        contract,
        { type: 'play_motion', action_id: 'a1' },
        before,
        before,
        false
    );
    const receipt = runtime.makeReceipt({
        receiptId: 'receipt:test-1',
        toolCallId: 'tool:test-1',
        action: { type: 'play_motion', action_id: 'a1' },
        before,
        after: before,
        verification,
        error: verification.error,
        durationMs: 5,
        timestamp: '2026-07-10T12:00:00Z',
    });
    assert.strictEqual(receipt.status, 'failed');
    assert.strictEqual(receipt.error, 'dispatch_refused');
    assert.strictEqual(receipt.tool_id, 'play_motion');
});

check('successful receipt has the closed phase4 shape', () => {
    const before = baseState();
    const after = baseState();
    after.motion.playing = true;
    after.motion.motion_id = 'synthetic-cycle';
    after.motion.rpm = 30;
    const action = { type: 'play_motion', action_id: 'a1', motion_id: 'synthetic-cycle', rpm: 30 };
    const receipt = runtime.makeReceipt({
        receiptId: 'receipt:test-2',
        toolCallId: 'tool:test-2',
        action,
        before,
        after,
        appliedArgs: { type: 'play_motion', rpm: 30 },
        evidence: ['motion-package:synthetic-cycle'],
        verification: runtime.verifyPostcondition(contract, action, before, after, true),
        durationMs: 10,
        timestamp: '2026-07-10T12:00:00Z',
    });
    assert.strictEqual(receipt.status, 'succeeded');
    assert.strictEqual(receipt.error, null);
    assert.deepStrictEqual(Object.keys(receipt).sort(), [
        'action_id', 'after', 'applied_args', 'before', 'contract_version', 'duration_ms',
        'error', 'evidence', 'receipt_id', 'requested_args', 'status', 'timestamp',
        'tool_call_id', 'tool_id',
    ]);
});

check('process-map scope selection is validated and receipt-verifiable', () => {
    const validation = runtime.validateBundle(contract, {
        workspace: 'process_map',
        actions: [{
            type: 'set_process_map_part_scope',
            scope_occurrence_id: 'bodywork-1',
            label: 'Bodywork Assembly',
        }],
    });
    assert.strictEqual(validation.ok, true);
    const before = baseState();
    const after = baseState();
    after.active_tab = 'training';
    after.process_map_selection = {
        scope_occurrence_id: 'bodywork-1',
        label: 'Bodywork Assembly',
        total: 24,
        placed: 0,
        remaining: 24,
    };
    assert.deepStrictEqual(runtime.verifyPostcondition(
        contract,
        validation.bundle.actions[0],
        before,
        after,
        true
    ), { ok: true });
});

check('process-map scope clear requires an empty transient selection', () => {
    const before = baseState();
    before.process_map_selection = { scope_occurrence_id: 'bodywork-1', total: 24 };
    const after = baseState();
    assert.deepStrictEqual(runtime.verifyPostcondition(
        contract,
        { type: 'clear_process_map_part_scope', action_id: 'a1' },
        before,
        after,
        true
    ), { ok: true });
});

check('process-map canvas focus is validated and receipt-verifiable', () => {
    const validation = runtime.validateBundle(contract, {
        workspace: 'process_map',
        actions: [{
            type: 'set_process_map_focus',
            target_occurrence_id: 'front-wheel',
            label: 'Front Wheel Assembly',
            direction: 'upstream',
            include_routes: true,
            fit_view: true,
            dim_others: true,
        }],
    });
    assert.strictEqual(validation.ok, true);
    const before = baseState();
    const after = baseState();
    after.active_tab = 'training';
    after.process_map_focus = {
        label: 'Front Wheel Assembly',
        target_occurrence_id: 'front-wheel',
        direction: 'upstream',
        target_node_ids: ['node-front-wheel'],
        node_ids: ['node-rim', 'stage-mount-tire', 'node-front-wheel'],
        edge_ids: ['edge-rim-stage', 'edge-stage-wheel'],
    };
    assert.deepStrictEqual(runtime.verifyPostcondition(
        contract,
        validation.bundle.actions[0],
        before,
        after,
        true
    ), { ok: true });
});

check('multi-scope process-map focus requires every requested target', () => {
    const validation = runtime.validateBundle(contract, {
        workspace: 'process_map',
        actions: [{
            type: 'set_process_map_focus',
            target_node_ids: ['stage-front', 'stage-rear'],
            labels: ['Front Wheel', 'Rear Wheel'],
            direction: 'upstream',
            include_routes: true,
        }],
    });
    assert.strictEqual(validation.ok, true);
    const before = baseState();
    const incomplete = baseState();
    incomplete.process_map_focus = {
        target_node_ids: ['stage-front'],
        target_occurrence_ids: [],
        node_ids: ['stage-front'],
        edge_ids: [],
    };
    assert.deepStrictEqual(runtime.verifyPostcondition(
        contract,
        validation.bundle.actions[0],
        before,
        incomplete,
        true
    ), { ok: false, error: 'process_map_focus_not_applied' });
    const complete = baseState();
    complete.process_map_focus = {
        target_node_ids: ['stage-front', 'stage-rear'],
        target_occurrence_ids: [],
        node_ids: ['part-front', 'stage-front', 'part-rear', 'stage-rear'],
        edge_ids: ['front-edge', 'rear-edge'],
    };
    assert.deepStrictEqual(runtime.verifyPostcondition(
        contract,
        validation.bundle.actions[0],
        before,
        complete,
        true
    ), { ok: true });
});

check('multi-scope process-map focus is capped at eight targets', () => {
    const validation = runtime.validateBundle(contract, {
        workspace: 'process_map',
        actions: [{
            type: 'set_process_map_focus',
            target_node_ids: Array.from({ length: 9 }, (_, index) => `stage-${index}`),
        }],
    });
    assert.strictEqual(validation.ok, false);
    assert.ok(validation.errors.includes(
        'action[0]:target_node_ids:too_many_items'
    ));
});

check('process-map canvas focus clear requires empty focus state', () => {
    const before = baseState();
    before.process_map_focus = {
        target_occurrence_id: 'front-wheel',
        node_ids: ['node-rim', 'node-front-wheel'],
    };
    const after = baseState();
    assert.deepStrictEqual(runtime.verifyPostcondition(
        contract,
        { type: 'clear_process_map_focus', action_id: 'a1' },
        before,
        after,
        true
    ), { ok: true });
});

process.stdout.write(`${checks} passed, 0 failed\n`);
