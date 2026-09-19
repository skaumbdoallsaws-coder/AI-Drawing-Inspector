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

function focusFixture() {
    return {
        schemaVersion: 3,
        mapId: 'default',
        productId: 'fixture',
        canvasNodes: [
            {
                nodeId: 'node-a',
                nodeKind: 'product_occurrence',
                sourceOccurrenceId: 'occ-a',
                position: { x: 0, y: 0 },
            },
            {
                nodeId: 'stage-1',
                nodeKind: 'process_step',
                processType: 'operation',
                position: { x: 260, y: 0 },
            },
            {
                nodeId: 'node-target',
                nodeKind: 'product_occurrence',
                sourceOccurrenceId: 'occ-target',
                position: { x: 520, y: 0 },
            },
            {
                nodeId: 'node-downstream',
                nodeKind: 'product_occurrence',
                sourceOccurrenceId: 'occ-downstream',
                position: { x: 780, y: 0 },
            },
            {
                nodeId: 'unrelated',
                nodeKind: 'product_occurrence',
                sourceOccurrenceId: 'occ-unrelated',
                position: { x: 0, y: 260 },
            },
        ],
        canvasEdges: [
            { edgeId: 'edge-a-stage', from: { nodeId: 'node-a' }, to: { nodeId: 'stage-1' } },
            { edgeId: 'edge-stage-target', from: { nodeId: 'stage-1' }, to: { nodeId: 'node-target' } },
            { edgeId: 'edge-target-downstream', from: { nodeId: 'node-target' }, to: { nodeId: 'node-downstream' } },
            { edgeId: 'edge-unrelated', from: { nodeId: 'unrelated' }, to: { nodeId: 'node-a' } },
        ],
    };
}

function focusStructure() {
    return {
        schemaVersion: 1,
        occurrences: [
            { occurrenceId: 'occ-root', parentOccurrenceId: null, kind: 'assembly', name: 'Root Assembly' },
            { occurrenceId: 'occ-target', parentOccurrenceId: 'occ-root', kind: 'subassembly', name: 'Target Subassembly' },
            { occurrenceId: 'occ-a', parentOccurrenceId: 'occ-target', kind: 'part', name: 'Input Part A' },
            { occurrenceId: 'occ-b', parentOccurrenceId: 'occ-target', kind: 'part', name: 'Input Part B' },
            { occurrenceId: 'occ-downstream', parentOccurrenceId: 'occ-root', kind: 'part', name: 'Downstream Part' },
            { occurrenceId: 'occ-unrelated', parentOccurrenceId: 'occ-root', kind: 'part', name: 'Unrelated Part' },
        ],
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

check('agent focus traces upstream cards and routes from a target occurrence', () => {
    const map = focusFixture();
    const before = JSON.stringify(map);
    const focus = runtime.resolveProcessMapFocus(map, {
        targetOccurrenceId: 'occ-target',
        direction: 'upstream',
        includeRoutes: true,
        label: 'Target Subassembly',
    }, focusStructure());
    assert.deepStrictEqual(focus.targetNodeIds, ['node-target']);
    assert.deepStrictEqual(focus.nodeIds, ['node-a', 'node-target', 'stage-1', 'unrelated']);
    assert.deepStrictEqual(focus.edgeIds, ['edge-a-stage', 'edge-stage-target', 'edge-unrelated']);
    assert.strictEqual(focus.resolution, 'exact');
    assert.strictEqual(JSON.stringify(map), before);
});

check('agent focus unions multiple named scopes and their upstream routes', () => {
    const map = focusFixture();
    map.canvasNodes.push(
        {
            nodeId: 'node-b',
            nodeKind: 'product_occurrence',
            sourceOccurrenceId: 'occ-b',
            position: { x: 0, y: 520 },
        },
        {
            nodeId: 'stage-2',
            nodeKind: 'process_step',
            processType: 'operation',
            position: { x: 260, y: 520 },
        },
        {
            nodeId: 'node-target-b',
            nodeKind: 'product_occurrence',
            sourceOccurrenceId: 'occ-target-b',
            position: { x: 520, y: 520 },
        }
    );
    map.canvasEdges.push(
        { edgeId: 'edge-b-stage', from: { nodeId: 'node-b' }, to: { nodeId: 'stage-2' } },
        { edgeId: 'edge-stage-target-b', from: { nodeId: 'stage-2' }, to: { nodeId: 'node-target-b' } }
    );
    const focus = runtime.resolveProcessMapFocus(map, {
        targetNodeIds: ['node-target', 'node-target-b'],
        labels: ['Target A', 'Target B'],
        direction: 'upstream',
        includeRoutes: true,
    }, focusStructure());
    assert.deepStrictEqual(focus.targetNodeIds, ['node-target', 'node-target-b']);
    assert.deepStrictEqual(
        focus.nodeIds,
        [
            'node-a', 'node-b', 'node-target', 'node-target-b',
            'stage-1', 'stage-2', 'unrelated',
        ]
    );
    assert.deepStrictEqual(
        focus.edgeIds,
        [
            'edge-a-stage', 'edge-b-stage', 'edge-stage-target',
            'edge-stage-target-b', 'edge-unrelated',
        ]
    );
    assert.strictEqual(focus.targets.length, 2);
    assert.deepStrictEqual(focus.labels, ['Target A', 'Target B']);
});

check('agent focus can isolate one placed part without routes', () => {
    const focus = runtime.resolveProcessMapFocus(focusFixture(), {
        targetOccurrenceId: 'occ-a',
        direction: 'target',
        includeRoutes: true,
    }, focusStructure());
    assert.deepStrictEqual(focus.targetNodeIds, ['node-a']);
    assert.deepStrictEqual(focus.nodeIds, ['node-a']);
    assert.deepStrictEqual(focus.edgeIds, []);
});

check('agent focus handles cyclic process routes deterministically', () => {
    const map = focusFixture();
    map.canvasEdges.push({
        edgeId: 'edge-cycle',
        from: { nodeId: 'node-target' },
        to: { nodeId: 'node-a' },
    });
    const focus = runtime.resolveProcessMapFocus(map, {
        targetOccurrenceId: 'occ-target',
        direction: 'upstream',
        includeRoutes: true,
    }, focusStructure());
    assert.deepStrictEqual(focus.nodeIds, ['node-a', 'node-target', 'stage-1', 'unrelated']);
    assert.deepStrictEqual(
        focus.edgeIds,
        ['edge-a-stage', 'edge-cycle', 'edge-stage-target', 'edge-unrelated']
    );
});

check('agent focus falls back to placed members for an unplaced subassembly', () => {
    const map = focusFixture();
    map.canvasNodes = map.canvasNodes.filter(item => item.nodeId !== 'node-target');
    map.canvasEdges = map.canvasEdges.filter(item => item.edgeId !== 'edge-stage-target');
    const focus = runtime.resolveProcessMapFocus(map, {
        targetOccurrenceId: 'occ-target',
        direction: 'upstream',
        includeRoutes: true,
    }, focusStructure());
    assert.deepStrictEqual(focus.targetNodeIds, []);
    assert.deepStrictEqual(focus.nodeIds, ['node-a']);
    assert.deepStrictEqual(focus.edgeIds, []);
    assert.strictEqual(focus.resolution, 'placed_scope_members');
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

check('operation stages assign deterministic distinct input slots', () => {
    const nodes = [
        { nodeId: 'upper', nodeKind: 'product_occurrence' },
        { nodeId: 'lower', nodeKind: 'product_occurrence' },
        { nodeId: 'stage', nodeKind: 'process_step', processType: 'operation' },
    ];
    const positions = {
        upper: { x: 20, y: 20, width: 270, height: 146 },
        lower: { x: 20, y: 260, width: 270, height: 146 },
        stage: {
            x: 520, y: 120, width: 270, height: 146,
            nodeKind: 'process_step', portOrientation: 'horizontal', portOrder: 'input_first',
        },
    };
    const edges = [
        { edgeId: 'lower-stage', from: { nodeId: 'lower' }, to: { nodeId: 'stage' } },
        { edgeId: 'upper-stage', from: { nodeId: 'upper' }, to: { nodeId: 'stage' } },
    ];
    const layout = runtime.processStepInputPortLayout(nodes, edges, positions);
    assert.deepStrictEqual(layout.byNode.stage, [
        { edgeId: 'upper-stage', index: 0, count: 2 },
        { edgeId: 'lower-stage', index: 1, count: 2 },
    ]);
    assert.deepStrictEqual(
        runtime.portAnchor(positions.stage, 'in', 0, 2),
        { x: 520, y: 120 + 146 / 3 }
    );
    assert.deepStrictEqual(
        runtime.portAnchor(positions.stage, 'in', 1, 2),
        { x: 520, y: 120 + 292 / 3 }
    );
    const upperGeometry = runtime.edgeGeometry(edges[1], positions, {
        routingEnabled: false,
        inputPortSlots: layout.byEdge,
    });
    const lowerGeometry = runtime.edgeGeometry(edges[0], positions, {
        routingEnabled: false,
        inputPortSlots: layout.byEdge,
    });
    assert.notStrictEqual(upperGeometry.points[1].y, lowerGeometry.points[1].y);
    assert.strictEqual(upperGeometry.points[1].y, 120 + 146 / 3);
    assert.strictEqual(lowerGeometry.points[1].y, 120 + 292 / 3);
});

check('vertical operation-stage input slots spread across the input edge', () => {
    const nodes = [
        { nodeId: 'left', nodeKind: 'product_occurrence' },
        { nodeId: 'right', nodeKind: 'product_occurrence' },
        { nodeId: 'stage', nodeKind: 'process_step', processType: 'operation' },
    ];
    const positions = {
        left: { x: 10, y: 10, width: 270, height: 146 },
        right: { x: 410, y: 10, width: 270, height: 146 },
        stage: {
            x: 220, y: 320, width: 270, height: 146,
            nodeKind: 'process_step', portOrientation: 'vertical', portOrder: 'input_first',
        },
    };
    const edges = [
        { edgeId: 'right-stage', from: { nodeId: 'right' }, to: { nodeId: 'stage' } },
        { edgeId: 'left-stage', from: { nodeId: 'left' }, to: { nodeId: 'stage' } },
    ];
    const layout = runtime.processStepInputPortLayout(nodes, edges, positions);
    assert.deepStrictEqual(
        runtime.portAnchor(positions.stage, 'in', 0, 2),
        { x: 310, y: 320 }
    );
    assert.deepStrictEqual(
        runtime.portAnchor(positions.stage, 'in', 1, 2),
        { x: 400, y: 320 }
    );
    assert.strictEqual(layout.byEdge['left-stage'].index, 0);
    assert.strictEqual(layout.byEdge['right-stage'].index, 1);
});

check('shared edge geometry renders routed polylines and preserves legacy fallback', () => {
    const positions = {
        a: {
            x: 0, y: 100, width: 270, height: 146,
            portOrientation: 'horizontal', portOrder: 'input_first',
        },
        b: {
            x: 700, y: 100, width: 270, height: 146,
            portOrientation: 'horizontal', portOrder: 'input_first',
        },
    };
    const edge = {
        edgeId: 'routed',
        from: { nodeId: 'a', port: 'out' },
        to: { nodeId: 'b', port: 'in' },
        routing: {
            mode: 'orthogonal_auto', routerVersion: 1,
            waypoints: [{ x: 300, y: 173 }, { x: 300, y: 360 }, { x: 680, y: 360 }, { x: 680, y: 173 }],
            obstacleFingerprint: 'fixture',
        },
    };
    const routed = runtime.edgeGeometry(edge, positions, { routingEnabled: true });
    assert.strictEqual(routed.mode, 'orthogonal_auto');
    assert.ok(routed.path.startsWith('M 270 173 L 300 173'));
    assert.deepStrictEqual(routed.bounds, { x: 270, y: 173, width: 430, height: 187 });
    const bounds = runtime.graphBounds(positions, [], [routed]);
    assert.strictEqual(bounds.y + bounds.height, 360);

    const fallback = runtime.edgeGeometry(edge, positions, { routingEnabled: false });
    assert.strictEqual(fallback.mode, 'bezier_legacy');
    assert.ok(fallback.path.indexOf(' C ') >= 0);
});

check('clearing a routed edge restores the curved mode immutably', () => {
    const source = placementFixture();
    source.canvasEdges = [{
        edgeId: 'route-a',
        from: { nodeId: 'a', port: 'out' },
        to: { nodeId: 'b', port: 'in' },
        kind: 'precedence',
        routing: {
            mode: 'orthogonal_auto',
            routerVersion: 1,
            waypoints: [{ x: 320, y: 120 }],
            obstacleFingerprint: 'fixture',
        },
    }];
    const next = runtime.clearEdgeRouting(source, 'route-a');
    assert.strictEqual(next.canvasEdges[0].routing, undefined);
    assert.strictEqual(source.canvasEdges[0].routing.mode, 'orthogonal_auto');
    assert.deepStrictEqual(
        runtime.clearEdgeRouting(source, 'missing-edge'),
        source
    );
});

check('manual polyline waypoints are immutable, editable, and support diagonal geometry', () => {
    const source = placementFixture();
    source.layoutVersion = 2;
    source.canvasNodes = [
        {
            nodeId: 'a', nodeKind: 'process_step', processType: 'operation',
            position: { x: 0, y: 100 },
        },
        {
            nodeId: 'b', nodeKind: 'process_step', processType: 'output',
            position: { x: 700, y: 260 },
        },
    ];
    source.canvasEdges = [edge('manual-edge', 'a', 'b')];
    const authored = runtime.setManualEdgeWaypoints(source, 'manual-edge', [
        { x: 340, y: 230 },
        { x: 510, y: 155 },
    ]);
    assert.strictEqual(source.canvasEdges[0].routing, undefined);
    assert.strictEqual(authored.layoutVersion, 3);
    assert.deepStrictEqual(authored.canvasEdges[0].routing, {
        mode: 'polyline_manual',
        routerVersion: 1,
        waypoints: [{ x: 340, y: 230 }, { x: 510, y: 155 }],
    });

    const inserted = runtime.addManualEdgeWaypoint(
        authored,
        'manual-edge',
        1,
        { x: 420, y: 300 }
    );
    assert.deepStrictEqual(inserted.canvasEdges[0].routing.waypoints, [
        { x: 340, y: 230 },
        { x: 420, y: 300 },
        { x: 510, y: 155 },
    ]);
    const removed = runtime.removeManualEdgeWaypoint(inserted, 'manual-edge', 0);
    assert.deepStrictEqual(removed.canvasEdges[0].routing.waypoints, [
        { x: 420, y: 300 },
        { x: 510, y: 155 },
    ]);

    const positions = runtime.layeredLayout(
        authored.canvasNodes,
        authored.canvasEdges
    );
    const geometry = runtime.edgeGeometry(
        authored.canvasEdges[0],
        positions,
        { routingEnabled: true }
    );
    assert.strictEqual(geometry.mode, 'polyline_manual');
    assert.ok(geometry.path.indexOf(' L ') >= 0);
    assert.strictEqual(
        runtime.routeGeometryFindings(
            authored.canvasEdges[0],
            geometry,
            positions,
            []
        ).some(finding => finding.code === 'route_diagonal_segment'),
        false
    );
});

check('nearest manual route segment returns a stable projected insertion point', () => {
    const nearest = runtime.nearestPointOnPolyline(
        [{ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 100, y: 100 }],
        { x: 80, y: 35 }
    );
    assert.deepStrictEqual(nearest, {
        point: { x: 100, y: 35 },
        segmentIndex: 1,
        distance: 20,
    });
});

check('manual and stale routed geometry is surfaced for deterministic repair', () => {
    const positions = {
        source: { x: 0, y: 100, width: 270, height: 146 },
        obstacle: { x: 330, y: 50, width: 270, height: 146 },
        target: { x: 700, y: 100, width: 270, height: 146 },
    };
    const edge = {
        edgeId: 'manual-route',
        from: { nodeId: 'source', port: 'out' },
        to: { nodeId: 'target', port: 'in' },
        routing: {
            mode: 'orthogonal_manual', routerVersion: 1,
            waypoints: [], obstacleFingerprint: 'manual-owner',
        },
    };
    const blocked = runtime.edgeGeometry(edge, positions, { routingEnabled: true });
    assert.deepStrictEqual(
        runtime.routeGeometryFindings(edge, blocked, positions, []).map((finding) => finding.code),
        ['route_card_intersection']
    );

    positions.obstacle.y = 360;
    assert.deepStrictEqual(runtime.routeGeometryFindings(edge, blocked, positions, []), []);

    edge.routing.waypoints = [{ x: 400, y: 280 }];
    const diagonal = runtime.edgeGeometry(edge, positions, { routingEnabled: true });
    assert.strictEqual(
        runtime.routeGeometryFindings(edge, diagonal, positions, [])[0].code,
        'route_diagonal_segment'
    );
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
    const centerX = 20 + runtime.NODE_WIDTH / 2;
    const bottomY = 40 + runtime.NODE_HEIGHT;
    assert.strictEqual(placed.portOrientation, 'vertical');
    assert.strictEqual(position.portOrientation, 'vertical');
    assert.deepStrictEqual(runtime.portAnchor(position, 'in'), { x: centerX, y: 40 });
    assert.deepStrictEqual(runtime.portAnchor(position, 'out'), { x: centerX, y: bottomY });
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
    assert.ok(pathValue.startsWith(`M ${centerX} ${bottomY} C ${centerX} `));

    const invalid = runtime.setNodePortOrientation(processMap, 'canvas-a', 'diagonal');
    assert.strictEqual(runtime.mapFingerprint(invalid), runtime.mapFingerprint(processMap));

    const swappedMap = runtime.setNodePortOrder(processMap, 'canvas-a', 'output_first');
    const swappedPosition = runtime.layeredLayout(runtime.mapNodes(swappedMap), [])['canvas-a'];
    assert.strictEqual(runtime.mapNodes(swappedMap)[0].portOrder, 'output_first');
    assert.deepStrictEqual(runtime.portAnchor(swappedPosition, 'in'), { x: centerX, y: bottomY });
    assert.deepStrictEqual(runtime.portAnchor(swappedPosition, 'out'), { x: centerX, y: 40 });
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
    assert.strictEqual(
        moved.nodes.find(item => item.nodeId === 'module-a').positionMode,
        'manual'
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
        positionMode: 'manual',
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

check('semantic junctions are never collapsed into ordinary wires', () => {
    let processMap = junctionGraph();
    processMap = runtime.addJunctionNode(processMap, {
        nodeId: 'semantic-merge',
        junctionType: 'merge',
        position: { x: 300, y: 160 },
    });
    processMap.canvasEdges = [
        { ...edge('left', 'a', 'semantic-merge'), logicalConnectionId: 'trunk' },
        { ...edge('right', 'semantic-merge', 'b'), logicalConnectionId: 'trunk' },
    ];
    const result = runtime.collapseRedundantJunctions(processMap);
    assert.strictEqual(
        runtime.mapNodes(result).some(item => item.nodeId === 'semantic-merge'),
        true
    );
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
    assert.strictEqual(processStep.canPreview, true);
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

check('card preview descriptors separate direct and inherited stage occurrences', () => {
    const productStructure = {
        schemaVersion: 1,
        productId: 'fixture',
        productName: 'Fixture Assembly',
        occurrences: [
            {
                occurrenceId: 'root',
                parentOccurrenceId: null,
                name: 'Root',
                kind: 'assembly',
            },
            {
                occurrenceId: 'part-a',
                parentOccurrenceId: 'root',
                name: 'Part A',
                kind: 'part',
            },
            {
                occurrenceId: 'part-b',
                parentOccurrenceId: 'root',
                name: 'Part B',
                kind: 'part',
            },
            {
                occurrenceId: 'part-c',
                parentOccurrenceId: 'root',
                name: 'Part C',
                kind: 'part',
            },
        ],
    };
    const processMap = {
        ...placementFixture(),
        canvasNodes: [
            {
                nodeId: 'card-a',
                nodeKind: 'product_occurrence',
                sourceOccurrenceId: 'part-a',
                position: { x: 0, y: 0 },
            },
            {
                nodeId: 'card-b',
                nodeKind: 'product_occurrence',
                sourceOccurrenceId: 'part-b',
                position: { x: 0, y: 180 },
            },
            {
                nodeId: 'stage-one',
                nodeKind: 'process_step',
                processType: 'operation',
                name: 'Join A and B',
                position: { x: 340, y: 90 },
            },
            {
                nodeId: 'card-c',
                nodeKind: 'product_occurrence',
                sourceOccurrenceId: 'part-c',
                position: { x: 340, y: 280 },
            },
            {
                nodeId: 'stage-two',
                nodeKind: 'process_step',
                processType: 'operation',
                name: 'Install C',
                position: { x: 680, y: 180 },
            },
        ],
        canvasEdges: [
            edge('edge-a-one', 'card-a', 'stage-one'),
            edge('edge-b-one', 'card-b', 'stage-one'),
            edge('edge-one-two', 'stage-one', 'stage-two'),
            edge('edge-c-two', 'card-c', 'stage-two'),
        ],
    };
    const descriptors = runtime.processMapCardPreviewDescriptors(
        processMap,
        productStructure
    );
    const byId = new Map(descriptors.map(item => [item.previewId, item]));
    assert.deepStrictEqual(byId.get('card-a'), {
        previewId: 'card-a',
        kind: 'occurrence',
        occurrenceIds: ['part-a'],
        directOccurrenceIds: [],
    });
    assert.deepStrictEqual(byId.get('stage-one'), {
        previewId: 'stage-one',
        kind: 'stage',
        occurrenceIds: ['part-a', 'part-b'],
        directOccurrenceIds: ['part-a', 'part-b'],
    });
    assert.deepStrictEqual(byId.get('stage-two'), {
        previewId: 'stage-two',
        kind: 'stage',
        occurrenceIds: ['part-a', 'part-b', 'part-c'],
        directOccurrenceIds: ['part-c'],
    });
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

check('illustrative reference provenance survives native editor normalization', () => {
    const reference = runtime.normalizeProcessReference({
        referenceId: 'demo-requirement-1',
        kind: 'requirement',
        name: 'Install rotor requirement',
        identifier: 'WI-FW-002',
        revision: 'A',
        clause: '4.1',
        details: 'Illustrative instructions.',
        knowledgeStatus: 'illustrative',
        demoData: true,
        sourcePlanId: 'front-wheel-brake-demo',
        sourceRevision: 'A',
        sourcePlanHash: 'a'.repeat(64),
        sourceRequirementId: 'route-rotor-a-stage2:requirement:1',
        sourceResourceId: 'res-torque-wrench',
        populatedBy: 'Sage',
        populatedAt: '2026-07-22T12:00:00Z',
    });
    assert.strictEqual(reference.knowledgeStatus, 'illustrative');
    assert.strictEqual(reference.demoData, true);
    assert.strictEqual(reference.sourcePlanId, 'front-wheel-brake-demo');
    assert.strictEqual(reference.sourceRequirementId, 'route-rotor-a-stage2:requirement:1');
    assert.strictEqual(reference.populatedBy, 'Sage');
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
    assert.strictEqual(grouped.layoutVersion, runtime.PROCESS_MAP_LAYOUT_VERSION);
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

check('clearing the map is atomic and preserves map identity', () => {
    let processMap = runtime.addCanvasNode(placementFixture(), {
        nodeId: 'node-a', nodeKind: 'process_step', processType: 'operation',
        name: 'Machine', position: { x: 100, y: 120 },
    });
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'node-b', nodeKind: 'process_step', processType: 'inspection',
        name: 'Inspect', position: { x: 420, y: 120 },
    });
    processMap = runtime.addEdge(processMap, edge('edge-a', 'node-a', 'node-b'));
    processMap = runtime.addGroup(processMap, {
        groupId: 'group-a', label: 'Cell', position: { x: 40, y: 60 },
        size: { width: 700, height: 320 }, colorKey: 'orange',
        memberNodeIds: ['node-a', 'node-b'], collapsed: false,
    });
    processMap = runtime.attachProcessReference(processMap, {
        targetType: 'node', targetId: 'node-a',
        reference: { referenceId: 'tool-1', kind: 'tool', name: 'Torque wrench' },
    });
    processMap = runtime.dismissSuggestion(processMap, 'suggestion-a');
    const original = runtime.cloneMap(processMap);
    const cleared = runtime.clearProcessMapCanvas(processMap);
    assert.strictEqual(runtime.hasProcessMapCanvasContent(cleared), false);
    assert.deepStrictEqual(runtime.mapNodes(cleared), []);
    assert.deepStrictEqual(runtime.mapEdges(cleared), []);
    assert.deepStrictEqual(runtime.mapGroups(cleared), []);
    assert.deepStrictEqual(runtime.mapReferenceCatalog(cleared), []);
    assert.deepStrictEqual(runtime.mapDismissedSuggestions(cleared), []);
    assert.strictEqual(cleared.mapId, 'default');
    assert.strictEqual(cleared.productId, 'fixture');
    assert.strictEqual(cleared.sourceStructureRevision, 'structure-rev');
    assert.strictEqual(runtime.mapNodes(processMap).length, 2);

    const history = new runtime.SnapshotHistory(5);
    history.record(original);
    assert.deepStrictEqual(history.undo(cleared), original);
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

check('map catalog keeps the active map visible and sorts templates', () => {
    const current = placementFixture();
    current.mapId = 'pm-current001';
    current.displayName = 'Current map';
    const catalog = runtime.normalizeMapCatalog({
        defaultMapId: 'default',
        maps: [
            { mapId: 'default', displayName: 'Main flow', status: 'active', isDefault: true },
        ],
        templates: [
            { templateId: 'pmt-zeta', displayName: 'Zeta' },
            { templateId: 'pmt-alpha', displayName: 'Alpha' },
        ],
    }, current);
    assert.deepStrictEqual(catalog.maps.map(item => item.mapId), ['pm-current001', 'default']);
    assert.deepStrictEqual(
        catalog.templates.map(item => item.templateId),
        ['pmt-alpha', 'pmt-zeta']
    );
});

check('required-part scope resolves descendant occurrences without using part numbers', () => {
    const structure = {
        schemaVersion: 1,
        productId: 'fixture',
        productName: 'Fixture Assembly',
        occurrences: [
            { occurrenceId: 'root', parentOccurrenceId: null, name: 'Root', kind: 'assembly' },
            { occurrenceId: 'body', parentOccurrenceId: 'root', name: 'Body', kind: 'subassembly' },
            { occurrenceId: 'panel-group', parentOccurrenceId: 'body', name: 'Panels', kind: 'subassembly' },
            { occurrenceId: 'panel-left', parentOccurrenceId: 'panel-group', itemId: 'PANEL', name: 'Panel', kind: 'part' },
            { occurrenceId: 'panel-right', parentOccurrenceId: 'panel-group', itemId: 'PANEL', name: 'Panel', kind: 'part' },
            { occurrenceId: 'frame', parentOccurrenceId: 'root', itemId: 'FRAME', name: 'Frame', kind: 'part' },
        ],
    };
    const before = JSON.stringify(structure);
    const resolved = runtime.resolveRequiredOccurrenceScope(structure, 'body');
    assert.deepStrictEqual(resolved.requiredOccurrenceIds, ['panel-left', 'panel-right']);
    assert.deepStrictEqual(new Set(resolved.expandedOccurrenceIds), new Set(['root', 'body', 'panel-group']));
    assert.deepStrictEqual(resolved.parentMatchCounts, {
        root: 2,
        body: 2,
        'panel-group': 2,
    });
    assert.strictEqual(JSON.stringify(structure), before);
});

check('required-part scope rejects unknown and empty non-part scopes', () => {
    const structure = {
        occurrences: [
            { occurrenceId: 'root', parentOccurrenceId: null, name: 'Root', kind: 'assembly' },
            { occurrenceId: 'empty', parentOccurrenceId: 'root', name: 'Empty', kind: 'subassembly' },
        ],
    };
    assert.strictEqual(runtime.resolveRequiredOccurrenceScope(structure, 'missing'), null);
    assert.deepStrictEqual(
        runtime.resolveRequiredOccurrenceScope(structure, 'empty').requiredOccurrenceIds,
        []
    );
});

check('pane width normalization preserves the last valid splitter width', () => {
    assert.strictEqual(runtime.normalizePaneWidth(undefined, 220, 480, 300), 300);
    assert.strictEqual(runtime.normalizePaneWidth(340, 220, 480, 300), 340);
    assert.strictEqual(runtime.normalizePaneWidth(120, 220, 480, 300), 220);
    assert.strictEqual(runtime.normalizePaneWidth(900, 220, 480, 300), 480);
    assert.strictEqual(runtime.normalizePaneWidth(333.6, 220, 480, 300), 334);
});

check('marquee geometry selects touching rectangles and wire segments', () => {
    const marquee = runtime.normalizedRect(140, 90, 20, 210);
    assert.deepStrictEqual(marquee, {
        left: 20,
        top: 90,
        right: 140,
        bottom: 210,
    });
    assert.strictEqual(runtime.rectsIntersect(
        marquee,
        { left: 140, top: 120, right: 220, bottom: 180 }
    ), true);
    assert.strictEqual(runtime.rectsIntersect(
        marquee,
        { left: 141, top: 120, right: 220, bottom: 180 }
    ), false);
    assert.strictEqual(runtime.segmentIntersectsRect(
        { x: 0, y: 150 },
        { x: 240, y: 150 },
        marquee
    ), true);
    assert.strictEqual(runtime.segmentIntersectsRect(
        { x: 0, y: 20 },
        { x: 240, y: 20 },
        marquee
    ), false);
});

check('multi-selection deletion is immutable and removes one graph selection atomically', () => {
    let processMap = placementFixture();
    ['a', 'b', 'c'].forEach((nodeId, index) => {
        processMap = runtime.addCanvasNode(processMap, {
            nodeId,
            nodeKind: 'process_step',
            processType: 'operation',
            name: nodeId.toUpperCase(),
            position: { x: index * 320, y: 80 },
        });
    });
    processMap = runtime.addEdge(processMap, edge('edge-a-b', 'a', 'b'));
    processMap = runtime.addEdge(processMap, edge('edge-b-c', 'b', 'c'));
    processMap = runtime.addGroup(processMap, {
        groupId: 'group-a', label: 'Cell', position: { x: 20, y: 20 },
        size: { width: 980, height: 300 }, colorKey: 'blue',
        memberNodeIds: ['a', 'b', 'c'], collapsed: false,
    });
    processMap = runtime.attachProcessReference(processMap, {
        targetType: 'node', targetId: 'a',
        reference: { referenceId: 'tool-a', kind: 'tool', name: 'Fixture A' },
    });
    processMap = runtime.attachProcessReference(processMap, {
        targetType: 'node', targetId: 'c',
        reference: { referenceId: 'machine-c', kind: 'machine', name: 'Machine C' },
    });
    const before = runtime.cloneMap(processMap);
    const deleted = runtime.deleteCanvasSelection(
        processMap,
        ['a', 'b'],
        ['edge-b-c']
    );
    assert.deepStrictEqual(runtime.mapNodes(deleted).map(item => item.nodeId), ['c']);
    assert.deepStrictEqual(runtime.mapEdges(deleted), []);
    assert.deepStrictEqual(runtime.mapGroups(deleted)[0].memberNodeIds, ['c']);
    assert.deepStrictEqual(
        runtime.mapReferenceCatalog(deleted).map(item => item.referenceId),
        ['machine-c']
    );
    assert.deepStrictEqual(processMap, before);

    const history = new runtime.SnapshotHistory(5);
    history.record(processMap);
    assert.deepStrictEqual(history.undo(deleted), processMap);
});

// -- Phase 3: card locking and deterministic placement acceptance -------

check('position ownership persists for cards and junctions', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'step-a', nodeKind: 'process_step', processType: 'operation',
        name: 'Step A', description: '', position: { x: 0, y: 0 },
    });
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'junction-a', nodeKind: 'junction', junctionType: 'wire_branch',
        position: { x: 400, y: 0 },
    });
    const locked = runtime.setNodePositionLocked(processMap, 'step-a', true);
    const stepAfter = runtime.mapNodes(locked).find((item) => item.nodeId === 'step-a');
    assert.strictEqual(stepAfter.locked, true);
    assert.strictEqual(stepAfter.positionMode, 'locked');
    assert.strictEqual(runtime.nodePositionLocked(stepAfter), true);

    const unlocked = runtime.setNodePositionLocked(locked, 'step-a', false);
    const stepUnlocked = runtime.mapNodes(unlocked).find((item) => item.nodeId === 'step-a');
    assert.strictEqual(stepUnlocked.locked, undefined);
    assert.strictEqual(stepUnlocked.positionMode, 'manual');

    const junctionLockAttempt = runtime.setNodePositionLocked(processMap, 'junction-a', true);
    const junctionAfter = runtime.mapNodes(junctionLockAttempt).find((item) => item.nodeId === 'junction-a');
    assert.strictEqual(junctionAfter.locked, true);
    assert.strictEqual(junctionAfter.positionMode, 'locked');
});

check('accepting a new product_occurrence candidate adds exactly one node', () => {
    const processMap = placementFixture();
    const before = runtime.cloneMap(processMap);
    const result = runtime.acceptPlacementCandidate(processMap, {
        nodeId: 'pm-n-new-1',
        isNew: true,
        nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occurrence-1',
        nameSnapshot: 'Fixture Part',
        itemIdSnapshot: 'ITEM-1',
        position: { x: 40, y: 60 },
        portOrientation: 'vertical',
        portOrder: 'output_first',
    });
    assert.strictEqual(result.accepted, true);
    assert.strictEqual(result.nodeId, 'pm-n-new-1');
    assert.strictEqual(runtime.mapNodes(result.map).length, 1);
    const placed = runtime.mapNodes(result.map)[0];
    assert.strictEqual(placed.sourceOccurrenceId, 'occurrence-1');
    assert.deepStrictEqual(placed.position, { x: 40, y: 60 });
    assert.strictEqual(placed.portOrientation, 'vertical');
    assert.strictEqual(placed.portOrder, 'output_first');
    assert.deepStrictEqual(processMap, before);
});

check('accepting a new process_step with a connection adds one node and one edge as a single op', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'anchor-a', nodeKind: 'process_step', processType: 'operation',
        name: 'Anchor', description: '', position: { x: 0, y: 0 },
    });
    const before = runtime.cloneMap(processMap);
    const result = runtime.acceptPlacementCandidate(processMap, {
        nodeId: 'pm-n-new-2',
        isNew: true,
        nodeKind: 'process_step',
        processType: 'inspection',
        name: 'New Inspection',
        position: { x: 320, y: 0 },
        portOrientation: 'horizontal',
        portOrder: 'input_first',
        connection: { anchorNodeId: 'anchor-a', direction: 'outgoing', kind: 'precedence' },
    });
    assert.strictEqual(result.accepted, true);
    assert.strictEqual(runtime.mapNodes(result.map).length, 2);
    assert.strictEqual(runtime.mapEdges(result.map).length, 1);
    const addedEdge = runtime.mapEdges(result.map)[0];
    assert.strictEqual(addedEdge.from.nodeId, 'anchor-a');
    assert.strictEqual(addedEdge.to.nodeId, 'pm-n-new-2');
    assert.deepStrictEqual(processMap, before);
});

check('accepting an existing-node move repositions without duplicating', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'movable', nodeKind: 'process_step', processType: 'operation',
        name: 'Movable', description: '', position: { x: 0, y: 0 },
        portOrientation: 'horizontal', portOrder: 'input_first',
    });
    const result = runtime.acceptPlacementCandidate(processMap, {
        nodeId: 'movable',
        isNew: false,
        position: { x: 500, y: 240 },
        portOrientation: 'vertical',
        portOrder: 'output_first',
    });
    assert.strictEqual(result.accepted, true);
    assert.strictEqual(runtime.mapNodes(result.map).length, 1);
    const moved = runtime.mapNodes(result.map)[0];
    assert.strictEqual(moved.nodeId, 'movable');
    assert.deepStrictEqual(moved.position, { x: 500, y: 240 });
    assert.strictEqual(moved.portOrientation, 'vertical');
});

check('accepting a move for a locked target is rejected and leaves the map unchanged', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'locked-node', nodeKind: 'process_step', processType: 'operation',
        name: 'Locked', description: '', position: { x: 0, y: 0 }, locked: true,
    });
    const before = runtime.cloneMap(processMap);
    const result = runtime.acceptPlacementCandidate(processMap, {
        nodeId: 'locked-node',
        isNew: false,
        position: { x: 500, y: 0 },
    });
    assert.strictEqual(result.accepted, false);
    assert.strictEqual(result.reason, 'target_unavailable');
    assert.deepStrictEqual(result.map, before);
});

check('accepting a connection that would create a cycle rejects the whole plan atomically', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'a', nodeKind: 'process_step', processType: 'operation',
        name: 'A', description: '', position: { x: 0, y: 0 },
    });
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'b', nodeKind: 'process_step', processType: 'operation',
        name: 'B', description: '', position: { x: 320, y: 0 },
    });
    processMap = runtime.addEdge(processMap, edge('edge-a-b', 'a', 'b'));
    const before = runtime.cloneMap(processMap);
    const result = runtime.acceptPlacementCandidate(processMap, {
        nodeId: 'a',
        isNew: false,
        position: { x: 0, y: 400 },
        connection: { anchorNodeId: 'b', direction: 'incoming', kind: 'precedence' },
    });
    assert.strictEqual(result.accepted, false);
    assert.strictEqual(result.reason, 'connection_rejected');
    assert.deepStrictEqual(result.map, before);
});

check('spatial suggestion acceptance persists its exact routed geometry', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'a', nodeKind: 'process_step', processType: 'operation',
        name: 'A', description: '', position: { x: 0, y: 0 },
    });
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'b', nodeKind: 'process_step', processType: 'inspection',
        name: 'B', description: '', position: { x: 500, y: 0 },
    });
    const suggestion = {
        suggestionId: 'pms-routed', evidenceFingerprint: 'evidence-routed',
        spatialProposal: {
            accepted: true,
            semanticSuggestionId: 'pms-routed',
            semanticEvidenceFingerprint: 'evidence-routed',
            routerVersion: 1,
            obstacleFingerprint: 'obstacles-v1',
            edge: edge('edge-routed', 'a', 'b'),
            route: {
                waypoints: [{ x: 320, y: 73 }, { x: 320, y: 120 }],
            },
        },
    };
    const result = runtime.acceptSpatialSuggestions(processMap, [suggestion]);
    assert.deepStrictEqual(result.accepted, ['pms-routed']);
    assert.deepStrictEqual(result.skipped, []);
    const routed = runtime.mapEdges(result.map)[0];
    assert.strictEqual(routed.routing.mode, 'orthogonal_auto');
    assert.deepStrictEqual(routed.routing.waypoints, suggestion.spatialProposal.route.waypoints);
    assert.strictEqual(routed.routing.obstacleFingerprint, 'obstacles-v1');
});

check('spatial next-card acceptance is atomic when its connection is invalid', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'anchor', nodeKind: 'process_step', processType: 'operation',
        name: 'Anchor', description: '', position: { x: 0, y: 0 },
    });
    const before = runtime.cloneMap(processMap);
    const suggestion = {
        suggestionId: 'pms-placement', evidenceFingerprint: 'evidence-placement',
        spatialProposal: {
            accepted: true,
            semanticSuggestionId: 'pms-placement',
            semanticEvidenceFingerprint: 'evidence-placement',
            routerVersion: 1,
            obstacleFingerprint: 'obstacles-placement',
            placement: {
                node: {
                    nodeId: 'new-part', nodeKind: 'product_occurrence',
                    sourceOccurrenceId: 'occurrence-1', nameSnapshot: 'New Part',
                    position: { x: 320, y: 0 },
                },
            },
            edge: edge('bad-edge', 'anchor', 'missing-node'),
            route: { waypoints: [] },
        },
    };
    const result = runtime.acceptSpatialSuggestions(processMap, [suggestion]);
    assert.deepStrictEqual(result.accepted, []);
    assert.strictEqual(result.skipped[0].reason, 'dangling_endpoint');
    assert.deepStrictEqual(result.map, before);
});

check('accepting an invalid plan leaves the map byte-identical', () => {
    const processMap = placementFixture();
    const before = runtime.cloneMap(processMap);
    const missingNodeId = runtime.acceptPlacementCandidate(processMap, {
        isNew: true, nodeKind: 'process_step', position: { x: 0, y: 0 },
    });
    assert.strictEqual(missingNodeId.accepted, false);
    assert.strictEqual(runtime.mapFingerprint(missingNodeId.map), runtime.mapFingerprint(before));

    const nonFinitePosition = runtime.acceptPlacementCandidate(processMap, {
        nodeId: 'x', isNew: true, nodeKind: 'process_step', position: { x: NaN, y: 0 },
    });
    assert.strictEqual(nonFinitePosition.accepted, false);
    assert.strictEqual(runtime.mapFingerprint(nonFinitePosition.map), runtime.mapFingerprint(before));
});

check('semantic junctions and stage details are immutable native editor operations', () => {
    const source = placementFixture();
    const junction = runtime.addJunctionNode(source, {
        nodeId: 'parallel-a',
        junctionType: 'parallel_and',
        position: { x: 400, y: 100 },
    });
    assert.strictEqual(runtime.mapNodes(junction)[0].junctionType, 'parallel_and');
    assert.deepStrictEqual(source, placementFixture());

    let stageMap = runtime.addCanvasNode(source, {
        nodeId: 'stage-a', nodeKind: 'process_step', processType: 'operation',
        name: 'Install panels', position: { x: 100, y: 80 },
    });
    const before = runtime.cloneMap(stageMap);
    stageMap = runtime.setProcessStepProperties(stageMap, 'stage-a', {
        description: 'Install both lower panels.',
        duration: '12 min',
        torqueRequirements: '10 N m',
    });
    assert.deepStrictEqual(runtime.mapNodes(stageMap)[0].properties, {
        description: 'Install both lower panels.',
        duration: '12 min',
        torqueRequirements: '10 N m',
    });
    assert.deepStrictEqual(before.canvasNodes[0].properties, undefined);
});

check('copy and paste duplicates authored logic without duplicating product occurrences', () => {
    let processMap = placementFixture();
    processMap.canvasGroups = [{
        groupId: 'group-a', label: 'Assembly stage', colorKey: 'blue', collapsed: false,
        position: { x: 0, y: 0 }, size: { width: 900, height: 400 },
        memberNodeIds: ['stage-a', 'merge-a'],
    }];
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'part-a', nodeKind: 'product_occurrence', sourceOccurrenceId: 'occurrence-1',
        position: { x: 10, y: 10 },
    });
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'stage-a', nodeKind: 'process_step', processType: 'operation',
        name: 'Install', position: { x: 120, y: 80 },
        properties: { duration: '8 min' },
    });
    processMap = runtime.addJunctionNode(processMap, {
        nodeId: 'merge-a', junctionType: 'merge', position: { x: 500, y: 153 },
    });
    processMap = runtime.addEdge(processMap, {
        edgeId: 'stage-merge', logicalConnectionId: 'stage-merge',
        from: { nodeId: 'stage-a', port: 'out' },
        to: { nodeId: 'merge-a', port: 'in' }, kind: 'precedence',
        routing: { mode: 'orthogonal_auto', waypoints: [{ x: 300, y: 153 }] },
    });
    const clipboard = runtime.copyProcessLogicSelection(
        processMap,
        ['part-a', 'stage-a', 'merge-a']
    );
    assert.deepStrictEqual(
        clipboard.nodes.map(node => node.nodeId).sort(),
        ['merge-a', 'stage-a']
    );
    const result = runtime.pasteProcessLogicSelection(processMap, clipboard, {
        nodeIdMap: { 'stage-a': 'stage-b', 'merge-a': 'merge-b' },
        edgeIdMap: { 'stage-merge': 'stage-merge-b' },
        logicalConnectionIdMap: { 'stage-merge': 'stage-merge-b' },
        offset: { x: 28, y: 28 },
    });
    assert.strictEqual(result.accepted, true);
    assert.strictEqual(runtime.mapNodes(result.map).length, 5);
    assert.strictEqual(
        runtime.mapNodes(result.map).filter(node => node.nodeKind === 'product_occurrence').length,
        1
    );
    const pastedStage = runtime.mapNodes(result.map).find(node => node.nodeId === 'stage-b');
    assert.deepStrictEqual(pastedStage.position, { x: 148, y: 108 });
    assert.deepStrictEqual(pastedStage.properties, { duration: '8 min' });
    const pastedEdge = runtime.mapEdges(result.map).find(edge => edge.edgeId === 'stage-merge-b');
    assert.strictEqual(pastedEdge.routing, undefined);
    assert(result.map.canvasGroups[0].memberNodeIds.includes('stage-b'));
    assert(result.map.canvasGroups[0].memberNodeIds.includes('merge-b'));
});

check('card duplication clones a stage and assigns it to the drop group', () => {
    let processMap = placementFixture();
    processMap.canvasGroups = [
        {
            groupId: 'source-group', label: 'Source', colorKey: 'blue', collapsed: false,
            position: { x: 0, y: 0 }, size: { width: 400, height: 400 },
            memberNodeIds: ['stage-a'],
        },
        {
            groupId: 'target-group', label: 'Target', colorKey: 'green', collapsed: false,
            position: { x: 500, y: 0 }, size: { width: 500, height: 400 },
            memberNodeIds: [],
        },
    ];
    processMap.referenceCatalog = [{
        referenceId: 'tool-a', kind: 'tool', name: 'Torque wrench',
    }];
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'stage-a', nodeKind: 'process_step', processType: 'operation',
        name: 'Install panel', note: 'Keep aligned', locked: true,
        properties: { duration: '8 min' }, referenceIds: ['tool-a'],
        position: { x: 80, y: 80 },
    });
    const before = runtime.cloneMap(processMap);
    const result = runtime.duplicateCanvasCard(processMap, 'stage-a', {
        nodeId: 'stage-copy',
        position: { x: 620, y: 100 },
        center: { x: 760, y: 180 },
    });
    assert.strictEqual(result.accepted, true);
    const duplicate = runtime.mapNodes(result.map).find(node => node.nodeId === 'stage-copy');
    assert.strictEqual(duplicate.name, 'Install panel');
    assert.strictEqual(duplicate.note, 'Keep aligned');
    assert.deepStrictEqual(duplicate.properties, { duration: '8 min' });
    assert.deepStrictEqual(duplicate.referenceIds, ['tool-a']);
    assert.strictEqual(duplicate.locked, undefined);
    assert.deepStrictEqual(duplicate.position, { x: 620, y: 100 });
    assert.deepStrictEqual(result.map.canvasGroups[0].memberNodeIds, ['stage-a']);
    assert.deepStrictEqual(result.map.canvasGroups[1].memberNodeIds, ['stage-copy']);
    assert.deepStrictEqual(processMap, before);
});

check('product-card duplication consumes a distinct matching occurrence', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'part-card-a', nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'occurrence-a', itemIdSnapshot: 'PART-100',
        nameSnapshot: 'Bracket', position: { x: 20, y: 30 },
    });
    const replacement = {
        occurrenceId: 'occurrence-b', itemId: 'PART-100', name: 'Bracket', kind: 'part',
    };
    const result = runtime.duplicateCanvasCard(processMap, 'part-card-a', {
        nodeId: 'part-card-b', position: { x: 420, y: 30 },
        replacementOccurrence: replacement, sourceItemId: 'PART-100',
    });
    assert.strictEqual(result.accepted, true);
    const duplicate = runtime.mapNodes(result.map).find(node => node.nodeId === 'part-card-b');
    assert.strictEqual(duplicate.sourceOccurrenceId, 'occurrence-b');
    assert.strictEqual(duplicate.itemIdSnapshot, 'PART-100');
    assert.strictEqual(duplicate.nameSnapshot, 'Bracket');

    const repeated = runtime.duplicateCanvasCard(result.map, 'part-card-a', {
        nodeId: 'part-card-c', position: { x: 720, y: 30 },
        replacementOccurrence: replacement, sourceItemId: 'PART-100',
    });
    assert.strictEqual(repeated.accepted, false);
    assert.strictEqual(repeated.reason, 'no_matching_product_occurrence');
    assert.strictEqual(runtime.mapNodes(repeated.map).length, 2);
});

check('managed proposal preview merges exact records without mutating the saved map', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'existing', nodeKind: 'process_step', processType: 'operation',
        name: 'Existing', description: '', position: { x: 0, y: 0 },
    });
    const before = runtime.cloneMap(processMap);
    const preview = {
        nodes: [
            {
                nodeId: 'existing', nodeKind: 'process_step', processType: 'operation',
                name: 'Existing', description: '', position: { x: 320, y: 80 },
            },
            {
                nodeId: 'proposed', nodeKind: 'process_step', processType: 'inspection',
                name: 'Proposed', description: '', position: { x: 640, y: 80 },
            },
        ],
        edges: [{
            edgeId: 'proposal-edge',
            from: { nodeId: 'existing', port: 'out' },
            to: { nodeId: 'proposed', port: 'in' },
            kind: 'precedence',
        }],
        groups: [],
    };
    const merged = runtime.mergeManagedProposalPreview(processMap, preview);
    assert.deepStrictEqual(
        runtime.mapNodes(merged).find(node => node.nodeId === 'existing').position,
        { x: 320, y: 80 }
    );
    assert(runtime.mapNodes(merged).some(node => node.nodeId === 'proposed'));
    assert(runtime.mapEdges(merged).some(edge => edge.edgeId === 'proposal-edge'));
    assert.deepStrictEqual(processMap, before);
    assert.strictEqual(runtime.mapEdges(processMap).length, 0);
});

check('managed proposal reveal follows stable process topology', () => {
    const preview = {
        nodes: [
            { nodeId: 'output', position: { x: 1000, y: 200 } },
            { nodeId: 'part-b', position: { x: 100, y: 300 } },
            { nodeId: 'stage', position: { x: 700, y: 200 } },
            { nodeId: 'part-a', position: { x: 100, y: 100 } },
            { nodeId: 'junction', position: { x: 420, y: 200 } },
        ],
        edges: [
            edge('edge-output', 'stage', 'output'),
            edge('edge-b', 'part-b', 'junction'),
            edge('edge-stage', 'junction', 'stage'),
            edge('edge-a', 'part-a', 'junction'),
        ],
    };
    assert.deepStrictEqual(runtime.managedProposalRevealSequence(preview), [
        { kind: 'node', ids: ['part-a'] },
        { kind: 'node', ids: ['part-b'] },
        { kind: 'node', ids: ['junction'] },
        { kind: 'edges', ids: ['edge-a', 'edge-b'] },
        { kind: 'node', ids: ['stage'] },
        { kind: 'edges', ids: ['edge-stage'] },
        { kind: 'node', ids: ['output'] },
        { kind: 'edges', ids: ['edge-output'] },
    ]);
});

check('managed proposal reveal handles cycles with deterministic complete output', () => {
    const first = {
        nodes: [
            { nodeId: 'cycle-b', position: { x: 300, y: 200 } },
            { nodeId: 'cycle-a', position: { x: 100, y: 100 } },
        ],
        edges: [
            edge('cycle-ba', 'cycle-b', 'cycle-a'),
            edge('cycle-ab', 'cycle-a', 'cycle-b'),
        ],
    };
    const second = {
        nodes: first.nodes.slice().reverse(),
        edges: first.edges.slice().reverse(),
    };
    const sequence = runtime.managedProposalRevealSequence(first);
    assert.deepStrictEqual(sequence, runtime.managedProposalRevealSequence(second));
    assert.deepStrictEqual(sequence, [
        { kind: 'node', ids: ['cycle-a'] },
        { kind: 'node', ids: ['cycle-b'] },
        { kind: 'edges', ids: ['cycle-ab', 'cycle-ba'] },
    ]);
});

check('multi-occurrence placement finds one deterministic non-overlapping grid', () => {
    let processMap = placementFixture();
    processMap = runtime.addCanvasNode(processMap, {
        nodeId: 'existing-card',
        nodeKind: 'product_occurrence',
        sourceOccurrenceId: 'existing-occurrence',
        position: { x: 0, y: 0 },
    });
    const center = { x: runtime.NODE_WIDTH / 2, y: runtime.NODE_HEIGHT / 2 };
    const first = runtime.planOccurrenceBatchPositions(processMap, 4, center);
    const second = runtime.planOccurrenceBatchPositions(processMap, 4, center);
    assert.deepStrictEqual(first, second);
    assert.strictEqual(first.length, 4);
    const rectangles = first.map(position => ({
        x: position.x,
        y: position.y,
        width: runtime.NODE_WIDTH,
        height: runtime.NODE_HEIGHT,
    }));
    const overlaps = (left, right, margin = 0) => (
        left.x < right.x + right.width + margin
        && left.x + left.width + margin > right.x
        && left.y < right.y + right.height + margin
        && left.y + left.height + margin > right.y
    );
    rectangles.forEach((rectangle, index) => {
        assert.strictEqual(overlaps(rectangle, {
            x: 0, y: 0, width: runtime.NODE_WIDTH, height: runtime.NODE_HEIGHT,
        }, 24), false);
        rectangles.slice(index + 1).forEach(other => {
            assert.strictEqual(overlaps(rectangle, other), false);
        });
    });

    const narrow = runtime.planOccurrenceBatchPositions(
        placementFixture(),
        3,
        { x: 250, y: 250 },
        { visibleWorldRect: { x: 0, y: 0, width: 500, height: 700 } }
    );
    assert.strictEqual(new Set(narrow.map(position => position.x)).size, 1);
    assert(narrow.every(position => (
        position.x >= 24
        && position.y >= 24
        && position.x + runtime.NODE_WIDTH <= 476
        && position.y + runtime.NODE_HEIGHT <= 676
    )));
});

check('multi-occurrence insertion is atomic, grouped, immutable, and duplicate-safe', () => {
    const processMap = placementFixture();
    processMap.canvasGroups = [{
        groupId: 'group-drop',
        label: 'Dropped components',
        colorKey: 'blue',
        collapsed: false,
        position: { x: 0, y: 0 },
        size: { width: 1200, height: 800 },
        memberNodeIds: [],
    }];
    const before = runtime.cloneMap(processMap);
    const entries = ['occ-a', 'occ-b', 'occ-c'].map((sourceOccurrenceId, index) => ({
        nodeId: `batch-${index + 1}`,
        sourceOccurrenceId,
        nameSnapshot: `Part ${index + 1}`,
        itemIdSnapshot: `P-${index + 1}`,
    }));
    const result = runtime.addOccurrenceBatch(processMap, {
        entries,
        dropPoint: { x: 600, y: 400 },
    });
    assert.deepStrictEqual(processMap, before);
    assert.deepStrictEqual(result.addedNodeIds, ['batch-1', 'batch-2', 'batch-3']);
    assert.strictEqual(result.targetGroupId, 'group-drop');
    assert.strictEqual(runtime.mapNodes(result.map).length, 3);
    assert.deepStrictEqual(
        result.map.canvasGroups[0].memberNodeIds.slice().sort(),
        ['batch-1', 'batch-2', 'batch-3']
    );
    assert.deepStrictEqual(
        runtime.mapNodes(result.map).map(node => node.sourceOccurrenceId),
        ['occ-a', 'occ-b', 'occ-c']
    );

    const duplicate = runtime.addOccurrenceBatch(result.map, {
        entries: entries.map((entry, index) => ({ ...entry, nodeId: `duplicate-${index}` })),
        dropPoint: { x: 600, y: 400 },
    });
    assert.deepStrictEqual(duplicate.addedNodeIds, []);
    assert.deepStrictEqual(duplicate.skippedOccurrenceIds, ['occ-a', 'occ-b', 'occ-c']);
    assert.strictEqual(runtime.mapFingerprint(duplicate.map), runtime.mapFingerprint(result.map));
});

process.stdout.write(`Process-map editor checks: ${checks}/${checks} passed\n`);
