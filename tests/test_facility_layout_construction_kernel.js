'use strict';

// Integration fixture: real browser session and builders, real Python operation
// kernel, in-memory documents only. No server or Save transaction is used.
const assert = require('assert');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const sessionModule = require('../static/facility_layout_session.js');
const patterns = require('../static/facility_layout_patterns.js');
const adapterModule = require('../static/facility_layout_command_adapter.js');
const contract = require('../static/contracts/facility-construction-commands-v1.json');
const root = path.resolve(__dirname, '..');
const python = process.env.CONSTRUCTION_TEST_PYTHON || 'python';
const kernelProgram = [
    'import json, sys',
    'from ai_inspector.facility_layout.canonical import layout_revision',
    'from ai_inspector.facility_layout.operations import apply_facility_layout_operations',
    'request = json.load(sys.stdin)',
    'base = request["layout"]',
    'base_revision = layout_revision(base)',
    'result = apply_facility_layout_operations(base, request["operations"], base_revision=base_revision)',
    'revision = layout_revision(result["document"])',
    'print(json.dumps({"layout": result["document"], "revision": revision, "changed": result["changed"], "operationResult": result}))',
].join('\n');

async function main() {
    let base = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/facility_layout/empty_cell.json'), 'utf8'));
    const callKernel = operations => JSON.parse(execFileSync(python, ['-c', kernelProgram], {
        cwd: root, input: JSON.stringify({ layout: base, operations }), encoding: 'utf8', timeout: 20000,
    }));
    const initial = callKernel([]);
    base = initial.layout;
    let saves = 0;
    let previews = 0;
    const session = sessionModule.createSession({
        previewOperations: async request => {
            assert.strictEqual(request.baseRevision, initial.revision);
            previews++;
            return callKernel(request.operations);
        },
        applyOperations: async () => { saves++; throw new Error('Save is forbidden in this fixture'); },
    });
    session.load(initial);
    const startingState = session.getState();
    const draftRevisions = [startingState.draftRevision];
    function assertRevisionAdvanced(beforeRevision) {
        const after = session.getState();
        assert.notStrictEqual(after.draftRevision, beforeRevision);
        assert.strictEqual(after.baseRevision, startingState.baseRevision);
        draftRevisions.push(after.draftRevision);
    }
    const catalog = [
        { assetId: 'table', assetDefinitionRevision: 'e'.repeat(64), width: 3, depth: 2, height: 1,
            supportSurfaces: [{ surfaceId: 'worktop', allowedSides: ['above'],
                localFrame: { origin: { x: 0, y: 1, z: 0 }, xAxis: { x: 1, y: 0, z: 0 },
                    zAxis: { x: 0, y: 0, z: 1 }, normal: { x: 0, y: 1, z: 0 } },
                bounds: { minimumX: -1.5, maximumX: 1.5, minimumZ: -1, maximumZ: 1 } }] },
        { assetId: 'device', assetDefinitionRevision: 'f'.repeat(64), width: 0.3, depth: 0.3, height: 0.2 },
    ];
    await session.placeAssets([catalog[0], catalog[0], catalog[1]].map((asset, index) => ({
        assetId: asset.assetId, assetDefinitionRevision: asset.assetDefinitionRevision,
        worldPosition: { x: 10 + index * 5, y: 0, z: 10 }, metadata: { instanceLabel: 'seed-' + index },
    })));
    assertRevisionAdvanced(startingState.draftRevision);
    const getId = index => session.getState().layout.placements.find(p => p.metadata.instanceLabel === 'seed-' + index).placementId;
    const tableA = getId(0), tableB = getId(1), device = getId(2);
    const adapter = adapterModule.createAdapter(contract, patterns, session, () => catalog);
    let sequence = 0;
    const run = async (commandId, args) => {
        const beforeRevision = session.getState().draftRevision;
        const receipt = await adapter.execute({ commandId, arguments: args,
            requestId: 'kernel-' + (++sequence), expectedDraftRevision: beforeRevision });
        assertRevisionAdvanced(beforeRevision);
        assert.strictEqual(receipt.beforeDraftRevision, beforeRevision);
        assert.strictEqual(receipt.draftRevision, session.getState().draftRevision);
        return receipt;
    };
    await run('cell-layout', { selectionIds: [tableA, tableB], strategyId: 'line',
        targetBounds: { width: 15, depth: 8 }, sourceUnit: 'm', gap: 0.5, rows: 1,
        orientation: 'preserve', angleDegrees: 0, invertU: false });
    await run('surface-stack', { supportId: tableA, childIds: [device], surfaceId: 'worktop', itemGap: 0.05, inset: 0.05 });
    const group = await run('create-cell-group', { selectionIds: [tableA, tableB, device], label: 'Assembly', envelopePadding: 0.2 });
    assert.strictEqual(group.cells[0].memberIds.length, 3);
    const beforeRepeat = session.getState().layout;
    const request = { commandId: 'linear-pattern', arguments: { seedIds: [group.cells[0].cellId],
        count: 3, direction: 'north', spacing: 15, sourceUnit: 'm' },
        requestId: 'kernel-repeat', expectedDraftRevision: session.getState().draftRevision };
    const receipt = await adapter.execute(request);
    assertRevisionAdvanced(request.expectedDraftRevision);
    assert.strictEqual(receipt.beforeDraftRevision, request.expectedDraftRevision);
    assert.strictEqual(receipt.draftRevision, session.getState().draftRevision);
    const repeated = session.getState().layout;
    assert.strictEqual(repeated.placements.length, 9);
    assert.strictEqual(repeated.zones.length, 3);
    assert.strictEqual(receipt.cells.length, 2);
    receipt.cells.forEach(cell => {
        assert.strictEqual(cell.memberIds.length, 3);
        const child = repeated.placements.find(p => cell.memberIds.includes(p.placementId) && p.assetId === 'device');
        assert.ok(cell.memberIds.includes(child.snapRelationship.supportPlacementId));
        assert.notStrictEqual(child.snapRelationship.supportPlacementId, tableA);
        assert.strictEqual(child.snapRelationship.surfaceId, 'worktop');
        assert.strictEqual(child.assetDefinitionRevision, catalog[1].assetDefinitionRevision);
    });
    const previewCount = previews;
    assert.deepStrictEqual(await adapter.execute(request), receipt);
    const reordered = { expectedDraftRevision: request.expectedDraftRevision,
        requestId: request.requestId, arguments: { sourceUnit: 'm', spacing: 15,
            direction: 'north', count: 3, seedIds: request.arguments.seedIds }, commandId: request.commandId };
    assert.notStrictEqual(JSON.stringify(request), JSON.stringify(reordered));
    assert.deepStrictEqual(await adapter.execute(reordered), receipt);
    const afterRepeat = session.getState();
    await assert.rejects(adapter.execute({ ...request, requestId: 'kernel-stale-new-command' }),
        error => error.code === 'facility_command_stale');
    assert.deepStrictEqual(session.getState(), afterRepeat);
    assert.strictEqual(previews, previewCount);
    await session.undo();
    assert.deepStrictEqual(session.getState().layout, beforeRepeat);
    assert.strictEqual(session.getState().draftRevision, request.expectedDraftRevision);
    while (session.getState().canUndo) await session.undo();
    assert.deepStrictEqual(session.getState().layout, startingState.layout);
    assert.strictEqual(session.getState().draftRevision, startingState.draftRevision);
    assert.strictEqual(session.getState().baseRevision, startingState.baseRevision);
    assert.strictEqual(saves, 0);
    process.stdout.write(JSON.stringify({ placements: 9, cells: 3, remappedAttachments: 2,
        retriesAddedDuplicates: false, reorderedRetryMatched: true, staleRevisionRejected: true,
        draftRevisions, undoRestoredOriginal: true, undoRestoredOriginalRevision: true,
        saves, kernelPreviews: previews }) + '\n');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
