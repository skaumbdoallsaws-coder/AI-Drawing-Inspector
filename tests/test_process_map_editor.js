'use strict';

const assert = require('assert');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const runtime = require(path.join(ROOT, 'static', 'process_map_editor.js'));

let checks = 0;
function check(name, fn) {
    fn();
    checks += 1;
    process.stdout.write(`PASS ${name}\n`);
}

function node(id, level, parentNodeId, type, order, position) {
    const value = {
        nodeId: id,
        level,
        parentNodeId,
        type,
        name: id,
        suggestedBuildOrder: order,
        partIds: [],
    };
    if (position) value.position = position;
    return value;
}

function edge(id, from, to, kind = 'precedence') {
    return {
        edgeId: id,
        from: { nodeId: from, port: 'out' },
        to: { nodeId: to, port: 'in' },
        kind,
    };
}

function fixture() {
    return {
        nodes: [
            node('root', 0, null, 'assembly', 99),
            node('module-b', 1, 'root', 'subassembly', 2),
            node('module-a', 1, 'root', 'subassembly', 1),
            node('group-a', 2, 'module-a', 'subassembly', 1),
            node('group-b', 2, 'module-b', 'subassembly', 2),
            node('part-a', 3, 'group-a', 'input', 1),
            node('part-b', 3, 'group-a', 'input', 2),
        ],
        edges: [
            edge('e1', 'module-a', 'group-a'),
            edge('e2', 'part-a', 'part-b'),
            edge('e3', 'group-b', 'module-b', 'rework'),
        ],
    };
}

function placementFixture() {
    return {
        schemaVersion: 3,
        mapId: 'default',
        productId: 'fixture',
        sourceStructureRevision: 'structure-rev',
        canvasNodes: [],
        canvasEdges: [],
    };
}

check('default scope shows levels one and two only', () => {
    assert.deepStrictEqual(
        runtime.scopedNodes(fixture(), null).map(item => item.nodeId),
        ['module-a', 'module-b', 'group-a', 'group-b']
    );
});

check('focused scope shows direct children in build order', () => {
    assert.deepStrictEqual(
        runtime.scopedNodes(fixture(), 'group-a').map(item => item.nodeId),
        ['part-a', 'part-b']
    );
});

check('visible edges require both endpoints in scope', () => {
    const map = fixture();
    const scoped = runtime.scopedNodes(map, null);
    assert.deepStrictEqual(
        runtime.visibleEdges(map, scoped).map(item => item.edgeId),
        ['e1', 'e3']
    );
});

check('precedence edges determine left-to-right ranks', () => {
    const map = fixture();
    const scoped = runtime.scopedNodes(map, null);
    const positions = runtime.layeredLayout(scoped, runtime.visibleEdges(map, scoped));
    assert.ok(positions['group-a'].x > positions['module-a'].x);
});

check('level fallback separates disconnected hierarchy levels', () => {
    const nodes = [
        node('a', 1, 'root', 'subassembly', 1),
        node('b', 2, 'a', 'subassembly', 1),
    ];
    const positions = runtime.layeredLayout(nodes, []);
    assert.ok(positions.b.x > positions.a.x);
});

check('saved node coordinates override automatic layout', () => {
    const nodes = [node('saved', 1, 'root', 'operation', 1, { x: 321, y: 654 })];
    const positions = runtime.layeredLayout(nodes, []);
    assert.strictEqual(positions.saved.x, 321);
    assert.strictEqual(positions.saved.y, 654);
});

check('layout is deterministic regardless of input order', () => {
    const map = fixture();
    const left = runtime.layeredLayout(map.nodes.slice().reverse(), map.edges.slice().reverse());
    const right = runtime.layeredLayout(map.nodes, map.edges);
    assert.deepStrictEqual(left, right);
});

check('bounds include every node rectangle', () => {
    const bounds = runtime.graphBounds({
        a: { x: 10, y: 20, width: 100, height: 50 },
        b: { x: 200, y: 100, width: 80, height: 60 },
    });
    assert.deepStrictEqual(bounds, { x: 10, y: 20, width: 270, height: 140 });
});

check('port anchors and bezier paths are stable', () => {
    const rect = { x: 20, y: 40, width: 100, height: 80 };
    assert.deepStrictEqual(runtime.portAnchor(rect, 'in'), { x: 20, y: 80 });
    assert.deepStrictEqual(runtime.portAnchor(rect, 'out'), { x: 120, y: 80 });
    const pathValue = runtime.bezierPath({ x: 120, y: 80 }, { x: 300, y: 200 });
    assert.ok(pathValue.startsWith('M 120 80 C '));
    assert.ok(pathValue.endsWith('300 200'));
});

check('each card can persist horizontal or vertical connection ports', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'canvas-a',
        nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-a',
        position: { x: 20, y: 40 },
    });
    processMap = runtime.setNodePortOrientation(processMap, 'canvas-a', 'vertical');
    const placed = runtime.mapNodes(processMap)[0];
    const position = runtime.layeredLayout(runtime.mapNodes(processMap), [])['canvas-a'];
    assert.strictEqual(placed.portOrientation, 'vertical');
    assert.strictEqual(position.portOrientation, 'vertical');
    assert.deepStrictEqual(runtime.portAnchor(position, 'in'), { x: 175, y: 40 });
    assert.deepStrictEqual(runtime.portAnchor(position, 'out'), { x: 175, y: 210 });
    assert.deepStrictEqual(
        runtime.portDirection('vertical', 'input_first', 'in'),
        { x: 0, y: -1 }
    );
    assert.deepStrictEqual(
        runtime.portDirection('vertical', 'input_first', 'out'),
        { x: 0, y: 1 }
    );
    const pathValue = runtime.bezierPath(
        runtime.portAnchor(position, 'out'),
        { x: 500, y: 420 },
        position.portOrientation,
        'vertical'
    );
    assert.ok(pathValue.startsWith('M 175 210 C 175 '));

    const invalid = runtime.setNodePortOrientation(processMap, 'canvas-a', 'diagonal');
    assert.strictEqual(runtime.mapFingerprint(invalid), runtime.mapFingerprint(processMap));

    const swappedMap = runtime.setNodePortOrder(processMap, 'canvas-a', 'output_first');
    const swappedPosition = runtime.layeredLayout(runtime.mapNodes(swappedMap), [])['canvas-a'];
    assert.strictEqual(runtime.mapNodes(swappedMap)[0].portOrder, 'output_first');
    assert.deepStrictEqual(runtime.portAnchor(swappedPosition, 'in'), { x: 175, y: 210 });
    assert.deepStrictEqual(runtime.portAnchor(swappedPosition, 'out'), { x: 175, y: 40 });
    assert.deepStrictEqual(
        runtime.portDirection('vertical', 'output_first', 'in'),
        { x: 0, y: 1 }
    );
    assert.deepStrictEqual(
        runtime.portDirection('vertical', 'output_first', 'out'),
        { x: 0, y: -1 }
    );
    const invalidOrder = runtime.setNodePortOrder(swappedMap, 'canvas-a', 'inside_out');
    assert.strictEqual(runtime.mapFingerprint(invalidOrder), runtime.mapFingerprint(swappedMap));
});

check('junctions keep their point-port behavior', () => {
    const processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'junction-a',
        nodeKind: 'junction',
        junctionType: 'wire_branch',
        position: { x: 120, y: 140 },
    });
    const changed = runtime.setNodePortOrientation(processMap, 'junction-a', 'vertical');
    assert.strictEqual(runtime.mapFingerprint(changed), runtime.mapFingerprint(processMap));
    const reordered = runtime.setNodePortOrder(processMap, 'junction-a', 'output_first');
    assert.strictEqual(runtime.mapFingerprint(reordered), runtime.mapFingerprint(processMap));
});

check('graph operations return new maps without mutating their input', () => {
    const original = fixture();
    const before = JSON.stringify(original);
    const withEdge = runtime.addEdge(original, edge('e4', 'module-b', 'group-b'));
    assert.strictEqual(original.edges.length, 3);
    assert.strictEqual(withEdge.edges.length, 4);
    assert.strictEqual(JSON.stringify(original), before);
});

check('duplicate and self connections are ignored', () => {
    const original = fixture();
    const duplicate = runtime.addEdge(original, edge('other-id', 'module-a', 'group-a'));
    const self = runtime.addEdge(original, edge('self', 'module-a', 'module-a'));
    assert.strictEqual(duplicate.edges.length, original.edges.length);
    assert.strictEqual(self.edges.length, original.edges.length);
});

check('delete move and retype operations are deterministic', () => {
    const original = fixture();
    const withoutEdge = runtime.deleteEdge(original, 'e1');
    assert.deepStrictEqual(withoutEdge.edges.map(item => item.edgeId), ['e2', 'e3']);
    const moved = runtime.moveNode(withoutEdge, 'module-a', { x: 111, y: 222 });
    assert.deepStrictEqual(
        moved.nodes.find(item => item.nodeId === 'module-a').position,
        { x: 111, y: 222 }
    );
    const retyped = runtime.retypeNode(moved, 'module-a', 'operation');
    assert.strictEqual(
        retyped.nodes.find(item => item.nodeId === 'module-a').type,
        'operation'
    );
    assert.strictEqual(original.nodes.find(item => item.nodeId === 'module-a').type, 'subassembly');
});

check('invalid node types do not alter the map', () => {
    const original = fixture();
    const result = runtime.retypeNode(original, 'module-a', 'component');
    assert.strictEqual(runtime.mapFingerprint(result), runtime.mapFingerprint(original));
});

check('snapshot history supports bounded undo and redo', () => {
    const history = new runtime.SnapshotHistory(2);
    const first = fixture();
    const second = runtime.moveNode(first, 'module-a', { x: 10, y: 20 });
    const third = runtime.moveNode(second, 'module-a', { x: 30, y: 40 });
    const fourth = runtime.moveNode(third, 'module-a', { x: 50, y: 60 });
    history.record(first);
    history.record(second);
    history.record(third);
    assert.strictEqual(history.undoStack.length, 2);
    assert.deepStrictEqual(
        history.undo(fourth).nodes.find(item => item.nodeId === 'module-a').position,
        { x: 30, y: 40 }
    );
    assert.deepStrictEqual(
        history.undo(third).nodes.find(item => item.nodeId === 'module-a').position,
        { x: 10, y: 20 }
    );
    assert.deepStrictEqual(
        history.redo(second).nodes.find(item => item.nodeId === 'module-a').position,
        { x: 30, y: 40 }
    );
});

check('schema v3 keeps source placements separate from the product catalog', () => {
    const original = placementFixture();
    const placed = runtime.addCanvasNode(original, {
        nodeId: 'canvas-a',
        nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-a',
        position: { x: 20, y: 30 },
    });
    assert.strictEqual(runtime.mapNodes(original).length, 0);
    assert.strictEqual(runtime.mapNodes(placed).length, 1);
    assert.strictEqual(placed.canvasNodes[0].sourceOccurrenceId, 'occ-a');
    assert.strictEqual(Object.prototype.hasOwnProperty.call(placed, 'nodes'), false);
});

check('the same product occurrence cannot be placed twice', () => {
    const first = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'canvas-a',
        nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-a',
        position: { x: 20, y: 30 },
    });
    const duplicate = runtime.addCanvasNode(first, {
        nodeId: 'canvas-b',
        nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-a',
        position: { x: 80, y: 90 },
    });
    assert.strictEqual(runtime.mapNodes(duplicate).length, 1);
});

check('deleting a canvas node removes incident edges atomically', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'canvas-a', nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-a', position: { x: 20, y: 30 },
    });
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'canvas-b', nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-b', position: { x: 200, y: 30 },
    });
    processMap = runtime.addEdge(processMap, edge('placed-edge', 'canvas-a', 'canvas-b'));
    const deleted = runtime.deleteNode(processMap, 'canvas-a');
    assert.deepStrictEqual(runtime.mapNodes(deleted).map(item => item.nodeId), ['canvas-b']);
    assert.strictEqual(runtime.mapEdges(deleted).length, 0);
});

check('schema v3 product occurrences cannot be retyped as process steps', () => {
    const placed = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'canvas-a', nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-a', position: { x: 20, y: 30 },
    });
    const result = runtime.retypeNode(placed, 'canvas-a', 'inspection');
    assert.strictEqual(result.canvasNodes[0].processType, undefined);
});

function junctionGraph() {
    let processMap = placementFixture();
    ['a', 'b', 'c', 'd'].forEach((id, index) => {
        processMap = runtime.addCanvasNode(processMap, {
            nodeId: id,
            nodeKind: 'product_occurrence',
            sourceOccurrenceId: `occ-${id}`,
            position: { x: 40 + index * 240, y: 80 + (index % 2) * 220 },
        });
    });
    return runtime.addEdge(processMap, {
        ...edge('trunk', 'a', 'b'),
        label: 'Primary flow',
        style: { stroke: 'blue' },
    });
}

function splitFixture() {
    return runtime.splitEdgeWithJunction(junctionGraph(), {
        sourceNodeId: 'c',
        targetEdgeId: 'trunk',
        position: { x: 240, y: 140 },
        junctionNodeId: 'junction-1',
        firstEdgeId: 'trunk-left',
        secondEdgeId: 'trunk-right',
        branchEdgeId: 'branch-c',
        kind: 'precedence',
    });
}

check('dropping a connection on an edge inserts one real junction atomically', () => {
    const original = junctionGraph();
    const split = splitFixture();
    assert.strictEqual(runtime.mapNodes(original).length, 4);
    assert.strictEqual(runtime.mapEdges(original).length, 1);
    assert.strictEqual(runtime.mapNodes(split).length, 5);
    assert.strictEqual(runtime.mapEdges(split).length, 3);
    const junction = runtime.mapNodes(split).find(item => item.nodeId === 'junction-1');
    assert.deepStrictEqual(junction, {
        nodeId: 'junction-1',
        nodeKind: 'junction',
        junctionType: 'wire_branch',
        position: { x: 240, y: 140 },
    });
    const shapes = runtime.mapEdges(split).map(item => `${item.from.nodeId}>${item.to.nodeId}`).sort();
    assert.deepStrictEqual(shapes, ['a>junction-1', 'c>junction-1', 'junction-1>b']);
});

check('split segments preserve direction styling and one copy of the label', () => {
    const split = splitFixture();
    const trunk = runtime.mapEdges(split).filter(item => item.logicalConnectionId === 'trunk');
    assert.strictEqual(trunk.length, 2);
    assert.strictEqual(trunk.filter(item => item.label === 'Primary flow').length, 1);
    assert.ok(trunk.every(item => item.style.stroke === 'blue'));
    assert.strictEqual(
        runtime.mapEdges(split).find(item => item.edgeId === 'branch-c').logicalConnectionId,
        'branch-c'
    );
});

check('branch insertion rejects a newly introduced precedence cycle', () => {
    const original = runtime.addEdge(junctionGraph(), edge('tail', 'b', 'c'));
    const rejected = runtime.splitEdgeWithJunction(original, {
        sourceNodeId: 'c',
        targetEdgeId: 'trunk',
        position: { x: 240, y: 140 },
        junctionNodeId: 'junction-cycle',
        firstEdgeId: 'cycle-left',
        secondEdgeId: 'cycle-right',
        branchEdgeId: 'cycle-branch',
    });
    assert.strictEqual(runtime.hasPrecedenceCycle(original), false);
    assert.strictEqual(runtime.mapFingerprint(rejected), runtime.mapFingerprint(original));
});

check('deleting a branch collapses only its original logical trunk', () => {
    const collapsed = runtime.deleteEdge(splitFixture(), 'branch-c');
    assert.strictEqual(runtime.mapNodes(collapsed).some(item => item.nodeKind === 'junction'), false);
    assert.strictEqual(runtime.mapEdges(collapsed).length, 1);
    assert.strictEqual(runtime.mapEdges(collapsed)[0].from.nodeId, 'a');
    assert.strictEqual(runtime.mapEdges(collapsed)[0].to.nodeId, 'b');
    assert.strictEqual(runtime.mapEdges(collapsed)[0].label, 'Primary flow');
});

check('junctions with unrelated logical wires are never auto-merged', () => {
    let processMap = junctionGraph();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'junction-2',
        nodeKind: 'junction',
        junctionType: 'wire_branch',
        position: { x: 300, y: 160 },
    });
    processMap.canvasEdges = [
        { ...edge('left', 'a', 'junction-2'), logicalConnectionId: 'left-logical' },
        { ...edge('right', 'junction-2', 'b'), logicalConnectionId: 'right-logical' },
    ];
    const result = runtime.collapseRedundantJunctions(processMap);
    assert.strictEqual(runtime.mapNodes(result).some(item => item.nodeId === 'junction-2'), true);
    assert.strictEqual(runtime.mapEdges(result).length, 2);
});

check('junction positions are point coordinates and both ports share the center', () => {
    const positions = runtime.layeredLayout([{
        nodeId: 'junction-layout',
        nodeKind: 'junction',
        junctionType: 'wire_branch',
        position: { x: 321, y: 654 },
    }], []);
    assert.strictEqual(positions['junction-layout'].isJunction, true);
    assert.strictEqual(positions['junction-layout'].width, 0);
    assert.deepStrictEqual(runtime.portAnchor(positions['junction-layout'], 'in'), { x: 321, y: 654 });
    assert.deepStrictEqual(runtime.portAnchor(positions['junction-layout'], 'out'), { x: 321, y: 654 });
});

check('contextual commands share one selection and lock policy', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'product-card',
        nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-product',
        position: { x: 20, y: 30 },
    });
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'process-card',
        nodeKind: 'process_step',
        processType: 'operation',
        name: 'Machine feature',
        position: { x: 220, y: 30 },
    });
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'junction-card',
        nodeKind: 'junction',
        junctionType: 'wire_branch',
        position: { x: 180, y: 200 },
    });

    const product = runtime.selectedNodeCommandStates(
        processMap,
        'product-card',
        null,
        { hasPreview: true }
    );
    assert.strictEqual(product.canPreview, true);
    assert.strictEqual(product.canRetype, false);
    assert.strictEqual(product.canChangePorts, true);
    assert.strictEqual(product.canAddConnectedStep, true);
    assert.strictEqual(product.canEditLabel, true);
    assert.strictEqual(product.canEditNote, true);
    assert.strictEqual(product.canDelete, true);

    const processStep = runtime.selectedNodeCommandStates(
        processMap,
        'process-card',
        null,
        { hasPreview: true }
    );
    assert.strictEqual(processStep.canPreview, false);
    assert.strictEqual(processStep.canRetype, true);
    assert.strictEqual(processStep.canAddConnectedStep, true);
    assert.strictEqual(processStep.canEditLabel, true);
    assert.strictEqual(processStep.canEditNote, true);
    assert.deepStrictEqual(processStep.typeOptions, runtime.PROCESS_STEP_TYPES);

    const junction = runtime.selectedNodeCommandStates(
        processMap,
        'junction-card',
        null,
        { hasPreview: true }
    );
    assert.strictEqual(junction.isJunction, true);
    assert.strictEqual(junction.canPreview, false);
    assert.strictEqual(junction.canRetype, false);
    assert.strictEqual(junction.canChangePorts, false);
    assert.strictEqual(junction.canAddConnectedStep, false);
    assert.strictEqual(junction.canEditLabel, false);
    assert.strictEqual(junction.canEditNote, false);
    assert.strictEqual(junction.canDelete, true);

    const locked = runtime.selectedNodeCommandStates(
        processMap,
        'product-card',
        null,
        { hasPreview: true, conflict: true }
    );
    assert.strictEqual(locked.canPreview, false);
    assert.strictEqual(locked.canChangePorts, false);
    assert.strictEqual(locked.canAddConnectedStep, false);
    assert.strictEqual(locked.canEditLabel, false);
    assert.strictEqual(locked.canEditNote, false);
    assert.strictEqual(locked.canDelete, false);
});

check('card labels and notes persist without mutating source identity', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'product-card',
        nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-product',
        nameSnapshot: 'Original product name',
        position: { x: 20, y: 30 },
    });
    processMap = runtime.setNodeLabel(processMap, 'product-card', 'Fixture-side housing');
    processMap = runtime.setNodeNote(processMap, 'product-card', 'Inspect before final wash.');
    assert.strictEqual(processMap.canvasNodes[0].sourceOccurrenceId, 'occ-product');
    assert.strictEqual(processMap.canvasNodes[0].nameSnapshot, 'Original product name');
    assert.strictEqual(processMap.canvasNodes[0].labelOverride, 'Fixture-side housing');
    assert.strictEqual(processMap.canvasNodes[0].note, 'Inspect before final wash.');

    processMap = runtime.setNodeLabel(processMap, 'product-card', '');
    processMap = runtime.setNodeNote(processMap, 'product-card', '');
    assert.strictEqual(processMap.canvasNodes[0].labelOverride, undefined);
    assert.strictEqual(processMap.canvasNodes[0].note, undefined);
});

check('process-step label edits update the authored step name', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'step-a',
        nodeKind: 'process_step',
        processType: 'operation',
        name: 'New Operation',
        position: { x: 20, y: 30 },
    });
    processMap = runtime.setNodeLabel(processMap, 'step-a', 'Finish machine bore');
    assert.strictEqual(processMap.canvasNodes[0].name, 'Finish machine bore');
    assert.strictEqual(processMap.canvasNodes[0].labelOverride, undefined);
});

check('add connected step creates one placed card and one edge atomically', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'source-card',
        nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-source',
        position: { x: 100, y: 120 },
        portOrientation: 'horizontal',
        portOrder: 'input_first',
    });
    const original = runtime.cloneMap(processMap);
    processMap = runtime.addConnectedProcessStep(processMap, {
        sourceNodeId: 'source-card',
        nodeId: 'inspection-step',
        edgeId: 'source-to-inspection',
        processType: 'inspection',
    });
    assert.strictEqual(runtime.mapNodes(processMap).length, 2);
    assert.strictEqual(runtime.mapEdges(processMap).length, 1);
    const step = runtime.mapNodes(processMap).find(item => item.nodeId === 'inspection-step');
    assert.strictEqual(step.name, 'New Inspection');
    assert.ok(step.position.x > original.canvasNodes[0].position.x);
    assert.strictEqual(runtime.mapEdges(processMap)[0].from.nodeId, 'source-card');
    assert.strictEqual(runtime.mapEdges(processMap)[0].to.nodeId, 'inspection-step');
    assert.strictEqual(runtime.mapNodes(original).length, 1);
    assert.strictEqual(runtime.mapEdges(original).length, 0);
});

check('connected-step placement follows output port orientation and order', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'source-card',
        nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occ-source',
        position: { x: 100, y: 300 },
        portOrientation: 'vertical',
        portOrder: 'output_first',
    });
    processMap = runtime.addConnectedProcessStep(processMap, {
        sourceNodeId: 'source-card',
        nodeId: 'operation-step',
        edgeId: 'source-to-operation',
        processType: 'operation',
    });
    const step = runtime.mapNodes(processMap).find(item => item.nodeId === 'operation-step');
    assert.ok(step.position.y < 300);
    assert.strictEqual(step.portOrientation, 'vertical');
    assert.strictEqual(step.portOrder, 'output_first');
});

check('card references reuse catalog definitions and reject incomplete standards', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'operation-card',
        nodeKind: 'process_step',
        processType: 'operation',
        name: 'Machine housing',
        position: { x: 100, y: 120 },
    });
    processMap = runtime.attachProcessReference(processMap, {
        targetType: 'node',
        targetId: 'operation-card',
        reference: {
            referenceId: 'machine-1',
            kind: 'machine',
            name: 'Five-axis machining center',
            identifier: 'MC-01',
        },
    });
    processMap = runtime.attachProcessReference(processMap, {
        targetType: 'node',
        targetId: 'operation-card',
        reference: {
            referenceId: 'machine-duplicate',
            kind: 'machine',
            name: 'Five-axis machining center',
            identifier: 'MC-01',
        },
    });
    assert.strictEqual(runtime.mapReferenceCatalog(processMap).length, 1);
    assert.deepStrictEqual(processMap.canvasNodes[0].referenceIds, ['machine-1']);
    assert.deepStrictEqual(runtime.referenceSummary(
        runtime.referenceItemsForTarget(processMap, 'node', 'operation-card')
    ), [{ kind: 'machine', count: 1 }]);

    const beforeInvalid = runtime.mapFingerprint(processMap);
    processMap = runtime.attachProcessReference(processMap, {
        targetType: 'node',
        targetId: 'operation-card',
        reference: {
            referenceId: 'standard-incomplete',
            kind: 'standard',
            name: 'Geometric tolerancing',
        },
    });
    assert.strictEqual(runtime.mapFingerprint(processMap), beforeInvalid);
});

check('logical connection references and labels propagate across split wire segments', () => {
    let processMap = placementFixture();
    ['source', 'target', 'branch'].forEach((nodeId, index) => {
        processMap = runtime.addCanvasNode(processMap, {
            nodeId,
            nodeKind: 'process_step',
            processType: 'operation',
            name: nodeId,
            position: { x: index * 260, y: index === 2 ? 260 : 40 },
        });
    });
    processMap = runtime.addEdge(processMap, edge('trunk', 'source', 'target'));
    processMap = runtime.splitEdgeWithJunction(processMap, {
        sourceNodeId: 'branch',
        targetEdgeId: 'trunk',
        position: { x: 310, y: 120 },
        junctionNodeId: 'junction',
        firstEdgeId: 'trunk-left',
        secondEdgeId: 'trunk-right',
        branchEdgeId: 'branch-edge',
    });
    processMap = runtime.attachProcessReference(processMap, {
        targetType: 'edge',
        targetId: 'trunk-left',
        reference: {
            referenceId: 'standard-1',
            kind: 'standard',
            name: 'Dimensioning and tolerancing',
            identifier: 'ASME Y14.5',
            revision: '2018',
            clause: '7.5',
        },
    });
    const trunkSegments = runtime.mapEdges(processMap).filter(item => (
        item.logicalConnectionId === 'trunk'
    ));
    assert.strictEqual(trunkSegments.length, 2);
    trunkSegments.forEach(item => assert.deepStrictEqual(item.referenceIds, ['standard-1']));
    assert.strictEqual(
        runtime.referenceItemsForTarget(processMap, 'edge', 'trunk-right')[0].identifier,
        'ASME Y14.5'
    );

    processMap = runtime.setEdgeLabel(processMap, 'trunk-right', 'Inspection release');
    assert.strictEqual(runtime.logicalEdgeLabel(processMap, 'trunk-left'), 'Inspection release');
    assert.strictEqual(
        runtime.mapEdges(processMap).filter(item => item.label === 'Inspection release').length,
        1
    );
});

check('detaching and deleting the last use prunes reference catalog entries', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'node-a',
        nodeKind: 'process_step',
        processType: 'inspection',
        name: 'Inspect feature',
        position: { x: 20, y: 30 },
    });
    const reference = {
        referenceId: 'tool-1',
        kind: 'tool',
        name: 'Digital bore gauge',
        identifier: 'BG-12',
    };
    processMap = runtime.attachProcessReference(processMap, {
        targetType: 'node', targetId: 'node-a', reference,
    });
    processMap = runtime.detachProcessReference(processMap, {
        targetType: 'node', targetId: 'node-a', referenceId: 'tool-1',
    });
    assert.strictEqual(runtime.mapReferenceCatalog(processMap).length, 0);

    processMap = runtime.attachProcessReference(processMap, {
        targetType: 'node', targetId: 'node-a', reference,
    });
    processMap = runtime.deleteNode(processMap, 'node-a');
    assert.strictEqual(runtime.mapReferenceCatalog(processMap).length, 0);
    assert.strictEqual(Object.prototype.hasOwnProperty.call(processMap, 'referenceCatalog'), false);
});

check('group creation is immutable and advances the layout contract', () => {
    const original = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'node-a',
        nodeKind: 'process_step',
        processType: 'operation',
        name: 'Machine feature',
        position: { x: 100, y: 120 },
    });
    const grouped = runtime.addGroup(original, {
        groupId: 'group-a',
        label: 'Machining cell',
        position: { x: 40, y: 50 },
        size: { width: 520, height: 320 },
        colorKey: 'orange',
        memberNodeIds: ['node-a'],
        collapsed: false,
        futureField: { preserved: true },
    });
    assert.strictEqual(runtime.mapGroups(original).length, 0);
    assert.strictEqual(grouped.layoutVersion, 2);
    assert.deepStrictEqual(runtime.mapGroups(grouped)[0].memberNodeIds, ['node-a']);
    assert.deepStrictEqual(runtime.mapGroups(grouped)[0].futureField, { preserved: true });
});

check('group membership is single-owner and smallest-frame deterministic', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'node-a', nodeKind: 'process_step', processType: 'operation',
        name: 'Node A', position: { x: 150, y: 150 },
    });
    processMap = runtime.addGroup(processMap, {
        groupId: 'large', label: 'Large', position: { x: 0, y: 0 },
        size: { width: 900, height: 700 }, colorKey: 'blue', memberNodeIds: [], collapsed: false,
    });
    processMap = runtime.addGroup(processMap, {
        groupId: 'small', label: 'Small', position: { x: 100, y: 100 },
        size: { width: 400, height: 280 }, colorKey: 'green', memberNodeIds: [], collapsed: false,
    });
    assert.strictEqual(runtime.smallestContainingGroup(processMap, { x: 220, y: 220 }).groupId, 'small');
    processMap = runtime.resolveNodeGroupMembership(processMap, 'node-a', { x: 220, y: 220 });
    assert.deepStrictEqual(runtime.mapGroups(processMap).find(item => item.groupId === 'large').memberNodeIds, []);
    assert.deepStrictEqual(runtime.mapGroups(processMap).find(item => item.groupId === 'small').memberNodeIds, ['node-a']);
});

check('moving a group can move members or frame only', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'node-a', nodeKind: 'process_step', processType: 'operation',
        name: 'Node A', position: { x: 100, y: 120 },
    });
    processMap = runtime.addGroup(processMap, {
        groupId: 'group-a', label: 'Cell', position: { x: 40, y: 60 },
        size: { width: 500, height: 300 }, colorKey: 'teal', memberNodeIds: ['node-a'], collapsed: false,
    });
    const movedTogether = runtime.moveGroup(processMap, 'group-a', { x: 90, y: 100 }, true);
    assert.deepStrictEqual(runtime.mapNodes(movedTogether)[0].position, { x: 150, y: 160 });
    const movedFrameOnly = runtime.moveGroup(processMap, 'group-a', { x: 90, y: 100 }, false);
    assert.deepStrictEqual(runtime.mapNodes(movedFrameOnly)[0].position, { x: 100, y: 120 });
    assert.deepStrictEqual(runtime.mapGroups(movedFrameOnly)[0].position, { x: 90, y: 100 });
});

check('group edits and deletion never mutate member cards', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'node-a', nodeKind: 'process_step', processType: 'inspection',
        name: 'Inspect', position: { x: 100, y: 120 },
    });
    processMap = runtime.addGroup(processMap, {
        groupId: 'group-a', label: 'Quality', position: { x: 40, y: 60 },
        size: { width: 500, height: 300 }, colorKey: 'yellow', memberNodeIds: ['node-a'], collapsed: false,
    });
    processMap = runtime.resizeGroup(processMap, 'group-a', {
        position: { x: 20, y: 30 }, size: { width: 620, height: 360 },
    });
    processMap = runtime.renameGroup(processMap, 'group-a', 'Final inspection');
    processMap = runtime.recolorGroup(processMap, 'group-a', 'purple');
    const withoutGroup = runtime.deleteGroup(processMap, 'group-a');
    assert.strictEqual(runtime.mapGroups(withoutGroup).length, 0);
    assert.deepStrictEqual(runtime.mapNodes(withoutGroup)[0].position, { x: 100, y: 120 });
    assert.strictEqual(runtime.mapNodes(withoutGroup)[0].name, 'Inspect');
});

check('node deletion removes stale group membership', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'node-a', nodeKind: 'process_step', processType: 'operation',
        name: 'Node A', position: { x: 100, y: 120 },
    });
    processMap = runtime.addGroup(processMap, {
        groupId: 'group-a', label: 'Cell', position: { x: 40, y: 60 },
        size: { width: 500, height: 300 }, colorKey: 'gray', memberNodeIds: ['node-a'], collapsed: false,
    });
    const deleted = runtime.deleteNode(processMap, 'node-a');
    assert.deepStrictEqual(runtime.mapGroups(deleted)[0].memberNodeIds, []);
});

check('graph bounds include grouping frames', () => {
    const bounds = runtime.graphBounds(
        { node: { x: 100, y: 100, width: 100, height: 80 } },
        [{ position: { x: -50, y: -40 }, size: { width: 600, height: 400 } }]
    );
    assert.deepStrictEqual(bounds, { x: -50, y: -68, width: 600, height: 428 });
});

check('suggestion dismissal is immutable, unique, and persisted on the map', () => {
    const original = placementFixture();
    const dismissed = runtime.dismissSuggestion(original, 'pms-evidence-1');
    const duplicate = runtime.dismissSuggestion(dismissed, 'pms-evidence-1');
    assert.deepStrictEqual(runtime.mapDismissedSuggestions(original), []);
    assert.deepStrictEqual(
        runtime.mapDismissedSuggestions(dismissed),
        ['pms-evidence-1']
    );
    assert.deepStrictEqual(duplicate, dismissed);
});

check('batch suggestion acceptance is one map result with cumulative cycle checks', () => {
    let processMap = placementFixture();
    ['a', 'b', 'c'].forEach((nodeId, index) => {
        processMap = runtime.addCanvasNode(processMap, {
            nodeId,
            nodeKind: 'process_step',
            processType: 'operation',
            name: nodeId.toUpperCase(),
            position: { x: index * 300, y: 0 },
        });
    });
    const suggestion = (id, from, to) => ({
        suggestionId: id,
        edge: edge('edge-' + id, from, to),
        validation: { wouldCreateCycle: false },
    });
    const result = runtime.acceptSuggestions(processMap, [
        suggestion('a-b', 'a', 'b'),
        suggestion('b-c', 'b', 'c'),
        suggestion('c-a', 'c', 'a'),
    ]);
    assert.deepStrictEqual(result.accepted, ['a-b', 'b-c']);
    assert.deepStrictEqual(result.skipped, [
        { suggestionId: 'c-a', reason: 'would_create_cycle' },
    ]);
    assert.strictEqual(runtime.mapEdges(processMap).length, 0);
    assert.strictEqual(runtime.mapEdges(result.map).length, 2);
    assert.strictEqual(runtime.hasPrecedenceCycle(result.map), false);
});

check('annotations and server-blocked suggestions are never accepted as edges', () => {
    const processMap = placementFixture();
    const result = runtime.acceptSuggestions(processMap, [
        { suggestionId: 'annotation', annotation: { kind: 'resource_contention' } },
        {
            suggestionId: 'blocked',
            edge: edge('blocked-edge', 'a', 'b'),
            validation: { wouldCreateCycle: true },
        },
    ]);
    assert.deepStrictEqual(result.accepted, []);
    assert.deepStrictEqual(result.skipped.map(item => item.reason), [
        'not_an_edge',
        'would_create_cycle',
    ]);
    assert.deepStrictEqual(result.map, processMap);
});

process.stdout.write(`Process-map editor checks: ${checks}/${checks} passed\n`);
