'use strict';

// The ribbon's own Position and Build tools on a fixture, for tests/test_sage_position_tools.py and
// tests/test_sage_stack_tools.py (Node never runs in the app): the workspace's builders
// (static/facility_layout_workspace.js) and the session calls its Position dialog makes (movePlacements,
// moveSelected, duplicatePlacements; buildSwap through applyPattern); Stack and On Surface (the workspace's seed,
// buildVerticalStack or buildSurfaceStack, then applyPattern); Create Cell (the dialog's request to
// createCellGroup) and Ungroup Cell (ungroupCell).
// Input on stdin: {layout, catalog, operationIdNamespace, cases: [{name, mode, namespace, ...}]}.
// Output: [{name, ok, operations, result} | {name, ok: false, error}].
const fs = require('fs');
const workspace = require('../static/facility_layout_workspace.js');
const SESSION = require.resolve('../static/facility_layout_session.js');
const patterns = require('../static/facility_layout_patterns.js');

const CAPTURED = Symbol('operation plan captured');

function updatesFor(input, item) {
    if (item.mode === 'align') {
        return workspace.buildAlignmentUpdates(input.layout, input.catalog, item.ids, item.alignMode, item.anchorId);
    }
    if (item.mode === 'distribute') {
        return workspace.buildDistributionUpdates(input.layout, input.catalog, item.ids, item.axis, item.method,
            item.gap);
    }
    if (item.mode === 'relative') {
        return workspace.buildRelativePositionUpdates(input.layout, input.catalog, item.ids, item.referenceId,
            item.relation, item.distance, item.alignment);
    }
    return workspace.buildDistanceUpdate(input.layout, input.catalog, item.referenceId, item.ids[0],
        item.distanceMode, item.distance);
}

async function run(input, item) {
    let operations;
    delete require.cache[SESSION];  // its id counters start afresh, as in a newly opened layout
    const session = require(SESSION).createSession({
        operationIdNamespace: item.namespace || input.operationIdNamespace,
        previewOperations: async request => {
            operations = request.operations;
            throw CAPTURED;
        },
        applyOperations: async () => { throw new Error('The runner cannot save'); },
    });
    session.load({ layout: input.layout, revision: '0'.repeat(64) });
    let result = null;
    let call;
    if (item.mode === 'offset') {
        const delta = { x: item.offset.x, y: 0, z: item.offset.z };
        if (item.copy) {
            call = () => session.duplicatePlacements(item.ids, delta);
        } else {
            session.selectMany(item.ids);
            call = () => session.moveSelected(delta);
        }
    } else if (item.mode === 'swap') {
        result = patterns.buildSwap(input.layout, input.catalog, item.ids);
        call = () => session.applyPattern(result, 'Swap positions');
    } else if (item.mode === 'stack' || item.mode === 'surface') {
        const seed = patterns.collectSelection(input.layout, input.catalog, item.ids,
            { expandZones: true, includeZones: false });
        result = item.mode === 'stack'
            ? patterns.buildVerticalStack(seed, item.options)
            : patterns.buildSurfaceStack(seed, item.options);
        call = () => session.applyPattern(result, item.mode === 'stack'
            ? 'Create vertical stack' : 'Place equipment on a support surface');
    } else if (item.mode === 'group') {
        // The Create Cell dialog's request (Workspace.prototype._applyCellGroup).
        const seed = patterns.collectSelection(input.layout, input.catalog, item.ids,
            { expandZones: true, includeZones: false }).filter(function (entry) {
            return entry.kind === 'placement' || entry.kind === 'floor-marking';
        });
        const bounds = patterns.selectionBounds(seed);
        const cell = item.cell;
        const padding = Math.max(0, cell.envelopePadding);
        const request = {
            baseName: cell.baseName,
            prefix: String(cell.prefix || '').trim(),
            start: Math.max(0, Math.round(cell.start)),
            numberPadding: Math.max(1, Math.min(6, Math.round(cell.numberPadding))),
            envelopePadding: padding,
            minX: bounds.minX - padding,
            minZ: bounds.minZ - padding,
            width: Math.max(0.01, bounds.width + 2 * padding),
            depth: Math.max(0.01, bounds.depth + 2 * padding),
            seriesId: cell.seriesId,
            functionalInterfaces: { gate: '', loading: '', service: '' },
            extensions: { style: { fillColor: cell.color } },
        };
        call = () => session.createCellGroup(request);
    } else if (item.mode === 'ungroup') {
        call = () => session.ungroupCell(item.zoneId);
    } else {
        result = updatesFor(input, item);
        call = () => session.movePlacements(result.updates, 'Position placements');
    }
    try {
        await call();
        return { name: item.name, ok: true, operations: [], result: result };
    } catch (error) {
        if (error !== CAPTURED) throw error;
    }
    return { name: item.name, ok: true, operations: operations, result: result };
}

async function main() {
    const input = JSON.parse(fs.readFileSync(0, 'utf8'));
    const results = [];
    for (const item of input.cases) {
        try {
            results.push(await run(input, item));
        } catch (error) {
            results.push({ name: item.name, ok: false, error: String(error && error.message || error) });
        }
    }
    process.stdout.write(JSON.stringify(results));
}

main().catch(error => {
    process.stdout.write(JSON.stringify([{ ok: false, error: String(error && error.message || error) }]));
    process.exitCode = 1;
});
