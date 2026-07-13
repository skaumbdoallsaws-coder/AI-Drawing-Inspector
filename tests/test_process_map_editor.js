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

process.stdout.write(`Process-map editor checks: ${checks}/${checks} passed\n`);
