'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const spatial = require(path.join(ROOT, 'static', 'process_map_spatial.js'));
const editor = require(path.join(ROOT, 'static', 'process_map_editor.js'));
const contract = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'static', 'contracts', 'process-map-spatial-contract-v1.json'),
    'ascii'
));
const fixture = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'tests', 'fixtures', 'process_map_spatial', 'phase1_scene.json'),
    'ascii'
));
const diagnosticFixture = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'tests', 'fixtures', 'process_map_spatial', 'phase2_diagnostics.json'),
    'ascii'
));
const placementMap = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'tests', 'fixtures', 'process_map_spatial', 'phase3_placement_map.json'),
    'ascii'
));
const placementFixture = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'tests', 'fixtures', 'process_map_spatial', 'phase3_candidates.json'),
    'ascii'
));
const routeFixture = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'tests', 'fixtures', 'process_map_spatial', 'phase4_route.json'),
    'ascii'
));
const arrangementFixture = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'tests', 'fixtures', 'process_map_spatial', 'phase7_arrangement.json'),
    'ascii'
));

let checks = 0;
const pendingChecks = [];
function check(name, fn) {
    const result = fn();
    if (result && typeof result.then === 'function') {
        pendingChecks.push(Promise.resolve(result).then(() => {
            checks += 1;
            process.stdout.write(`PASS ${name}\n`);
        }));
        return;
    }
    checks += 1;
    process.stdout.write(`PASS ${name}\n`);
}

function approximate(actual, expected, tolerance = 1e-9) {
    Object.keys(expected).forEach((key) => {
        assert.ok(Math.abs(actual[key] - expected[key]) <= tolerance, `${key}: ${actual[key]}`);
    });
}

check('shared contract is versioned and valid', () => {
    const validated = spatial.validateContract(contract);
    assert.strictEqual(validated.contractId, spatial.CONTRACT_ID);
    assert.strictEqual(validated.spatialVersion, spatial.SPATIAL_VERSION);
    validated.geometry.nodeEnvelopes.default.width = 1;
    assert.strictEqual(contract.geometry.nodeEnvelopes.default.width, 270);
    assert.strictEqual(contract.geometry.legacyBezierSamplingSegments, 32);
    assert.strictEqual(contract.diagnostics.regionColumns, 4);
});

check('shared contract matches live editor envelopes', () => {
    assert.strictEqual(contract.geometry.nodeEnvelopes.default.width, editor.NODE_WIDTH);
    assert.strictEqual(contract.geometry.nodeEnvelopes.default.height, editor.NODE_HEIGHT);
    assert.strictEqual(contract.geometry.junction.hitDiameter, editor.JUNCTION_HIT_SIZE);
});

check('point coordinates round trip through pan and zoom', () => {
    const point = { x: 410.5, y: -23.25 };
    const transform = { x: 88, y: -40, scale: 0.28 };
    approximate(spatial.viewportToWorld(spatial.worldToViewport(point, transform), transform), point);
});

check('rectangle coordinates round trip through pan and zoom', () => {
    const rect = { x: 120, y: 80, width: 270, height: 146 };
    const transform = { x: -42, y: 91, scale: 1.35 };
    approximate(spatial.viewportRectToWorld(spatial.worldRectToViewport(rect, transform), transform), rect);
});

check('normalized coordinates use world bounds', () => {
    approximate(
        spatial.worldToNormalized(
            { x: 445, y: 246 },
            { x: 70, y: 32, width: 750, height: 428 }
        ),
        { x: 0.5, y: 0.5 }
    );
});

check('invalid transforms fail closed', () => {
    assert.throws(
        () => spatial.worldToViewport({ x: 1, y: 2 }, { x: 0, y: 0, scale: 0 }),
        /positive scale/
    );
});

check('scene compiler matches the shared golden fixture', () => {
    assert.deepStrictEqual(
        spatial.compileSpatialScene(fixture.processMap, {
            contract,
            revision: fixture.revision,
        }),
        fixture.expectedScene
    );
});

check('scene output is deterministic across input order', () => {
    const reordered = JSON.parse(JSON.stringify(fixture.processMap));
    reordered.canvasNodes.reverse();
    reordered.canvasEdges.reverse();
    reordered.canvasGroups[0].memberNodeIds.reverse();
    assert.deepStrictEqual(
        spatial.compileSpatialScene(reordered, { contract }),
        spatial.compileSpatialScene(fixture.processMap, { contract })
    );
});

check('duplicate group membership fails closed', () => {
    const processMap = JSON.parse(JSON.stringify(fixture.processMap));
    processMap.canvasGroups.push({
        groupId: 'group-second',
        position: { x: 0, y: 0 },
        size: { width: 300, height: 200 },
        memberNodeIds: ['node-a'],
    });
    assert.throws(() => spatial.compileSpatialScene(processMap, { contract }), /multiple groups/);
});

check('contract loader supports an injected fetch implementation', async () => {
    const loaded = await spatial.loadSpatialContract('/fixture-contract.json', async (url) => {
        assert.strictEqual(url, '/fixture-contract.json');
        return { ok: true, json: async () => contract };
    });
    assert.strictEqual(loaded.contractId, spatial.CONTRACT_ID);
});

check('clean diagnostics ignore explicit junction connectivity', () => {
    const diagnostics = spatial.diagnoseSpatialScene(
        spatial.compileSpatialScene(fixture.processMap, { contract }),
        { contract }
    );
    assert.strictEqual(diagnostics.metrics.nodeOverlaps, 0);
    assert.strictEqual(diagnostics.metrics.edgeNodeIntersections, 0);
    assert.strictEqual(diagnostics.metrics.edgeCrossings, 0);
    assert.deepStrictEqual(diagnostics.problems, []);
});

check('diagnostic metrics and problem order match shared golden fixture', () => {
    const diagnostics = spatial.diagnoseSpatialScene(
        spatial.compileSpatialScene(diagnosticFixture.processMap, { contract }),
        { contract }
    );
    assert.deepStrictEqual(diagnostics.metrics, diagnosticFixture.expectedMetrics);
    assert.deepStrictEqual(
        diagnostics.problems.map((item) => item.problemId),
        diagnosticFixture.expectedProblemIds
    );
    assert.deepStrictEqual(
        diagnostics.regions.map((item) => [
            item.regionId,
            item.relativeLocation,
            item.classification,
        ]),
        diagnosticFixture.expectedRegions
    );
});

check('diagnostics are deterministic across scene input order', () => {
    const scene = spatial.compileSpatialScene(diagnosticFixture.processMap, { contract });
    const reordered = JSON.parse(JSON.stringify(scene));
    reordered.nodes.reverse();
    reordered.edges.reverse();
    reordered.groups.reverse();
    assert.deepStrictEqual(
        spatial.diagnoseSpatialScene(reordered, { contract }),
        spatial.diagnoseSpatialScene(scene, { contract })
    );
});

check('diagnostic output never contains viewport coordinates', () => {
    const diagnostics = spatial.diagnoseSpatialScene(
        spatial.compileSpatialScene(diagnosticFixture.processMap, { contract }),
        { contract }
    );
    const encoded = JSON.stringify(diagnostics);
    assert.ok(!encoded.includes('clientX'));
    assert.ok(!encoded.includes('clientY'));
    assert.ok(!encoded.includes('viewportRect'));
});

check('minimum clearance is global beyond index-neighbor cells', () => {
    const processMap = {
        schemaVersion: 3,
        layoutVersion: 2,
        mapId: 'clearance-map',
        productId: 'fixture-product',
        canvasNodes: [
            { nodeId: 'left', nodeKind: 'process_step', position: { x: 0, y: 0 } },
            { nodeId: 'right', nodeKind: 'process_step', position: { x: 5000, y: 0 } },
        ],
        canvasEdges: [],
        canvasGroups: [],
    };
    const diagnostics = spatial.diagnoseSpatialScene(
        spatial.compileSpatialScene(processMap, { contract }),
        { contract }
    );
    assert.strictEqual(diagnostics.metrics.minimumNodeClearance, 4730);
});

// -- Phase 3: deterministic incremental placement -----------------------

const placementScene = spatial.compileSpatialScene(placementMap, { contract });
const placementCases = {
    anchoredOutgoing: { targetKind: 'process_step', anchorNodeId: 'anchor-a', connectionDirection: 'outgoing' },
    requiredGroup: {
        targetKind: 'process_step',
        anchorNodeId: 'anchor-a',
        connectionDirection: 'outgoing',
        requiredGroupId: 'group-main',
    },
    anchorless: { targetKind: 'product_occurrence' },
    lockedTargetMove: { targetKind: 'process_step', targetNodeId: 'locked-b' },
    junctionAnchor: { targetKind: 'process_step', anchorNodeId: 'junction-d', connectionDirection: 'outgoing' },
    existingNodeMove: { targetKind: 'process_step', targetNodeId: 'clutter-c' },
    verticalFlow: {
        targetKind: 'process_step',
        anchorNodeId: 'anchor-a',
        connectionDirection: 'outgoing',
        preferredFlowDirection: 'top_to_bottom',
    },
};

check('placement candidates match shared golden fixture', () => {
    Object.keys(placementCases).forEach((name) => {
        const result = spatial.generatePlacementCandidates(
            placementScene,
            Object.assign({ contract }, placementCases[name])
        );
        assert.deepStrictEqual(result, placementFixture.cases[name], name);
    });
});

check('candidates are deterministic across repeated calls', () => {
    const first = spatial.generatePlacementCandidates(placementScene, Object.assign(
        { contract }, placementCases.anchoredOutgoing
    ));
    const second = spatial.generatePlacementCandidates(placementScene, Object.assign(
        { contract }, placementCases.anchoredOutgoing
    ));
    assert.deepStrictEqual(first, second);
});

check('candidate ranking is stable and unique', () => {
    const result = spatial.generatePlacementCandidates(placementScene, Object.assign(
        { contract }, placementCases.anchoredOutgoing
    ));
    const ids = result.candidates.map((candidate) => candidate.candidateId);
    assert.strictEqual(new Set(ids).size, ids.length);
    assert.ok(result.candidates.length <= 3);
});

check('locked target move rejects before generating candidates', () => {
    const result = spatial.generatePlacementCandidates(placementScene, Object.assign(
        { contract }, placementCases.lockedTargetMove
    ));
    assert.deepStrictEqual(result.candidates, []);
    assert.deepStrictEqual(result.rejectionCounts, { locked_node_movement: 1 });
    assert.strictEqual(result.evaluatedCount, 0);
});

check('fully blocked placement fails closed with deterministic rejections', () => {
    const processMap = {
        schemaVersion: 3,
        layoutVersion: 2,
        mapId: 'blocked-map',
        productId: 'fixture-product',
        canvasNodes: [{ nodeId: 'a', nodeKind: 'process_step', position: { x: 0, y: 0 } }],
        canvasEdges: [],
        canvasGroups: [],
    };
    const scene = spatial.compileSpatialScene(processMap, { contract });
    const result = spatial.generatePlacementCandidates(scene, {
        contract, targetKind: 'process_step', anchorNodeId: 'a', requiredGroupId: 'no-such-group',
    });
    assert.deepStrictEqual(result.candidates, []);
    assert.deepStrictEqual(result.rejectionCounts, { group_containment_violation: 1 });
});

check('anchorless placement uses the least-dense available region', () => {
    const result = spatial.generatePlacementCandidates(placementScene, {
        contract, targetKind: 'product_occurrence',
    });
    assert.ok(result.candidates.length);
    assert.strictEqual(result.anchorNodeId, null);
    result.candidates.forEach((candidate) => {
        assert.ok(candidate.candidateId.startsWith('cand-region-'));
    });
});

check('group containment rejections are counted and candidates stay inside', () => {
    const result = spatial.generatePlacementCandidates(placementScene, Object.assign(
        { contract }, placementCases.requiredGroup
    ));
    assert.ok((result.rejectionCounts.group_containment_violation || 0) > 0);
    result.candidates.forEach((candidate) => {
        assert.ok(candidate.position.x >= -40);
        assert.ok(candidate.position.y >= -40);
    });
});

check('port orientation and order are each evaluated', () => {
    const result = spatial.generatePlacementCandidates(placementScene, Object.assign(
        { contract }, placementCases.anchoredOutgoing
    ));
    const allowed = new Set([
        'horizontal:input_first', 'horizontal:output_first',
        'vertical:input_first', 'vertical:output_first',
    ]);
    result.candidates.forEach((candidate) => {
        assert.ok(allowed.has(candidate.portOrientation + ':' + candidate.portOrder));
    });
});

check('legacy wire/card intersection is a hard rejection', () => {
    const processMap = {
        schemaVersion: 3,
        layoutVersion: 2,
        mapId: 'wire-block-map',
        productId: 'fixture-product',
        canvasNodes: [
            {
                nodeId: 'anchor',
                nodeKind: 'process_step',
                position: { x: 0, y: 0 },
                portOrientation: 'vertical',
                portOrder: 'output_first',
            },
            { nodeId: 'obstacle', nodeKind: 'process_step', position: { x: 220, y: -60 } },
        ],
        canvasEdges: [],
        canvasGroups: [],
    };
    const scene = spatial.compileSpatialScene(processMap, { contract });
    const result = spatial.generatePlacementCandidates(scene, {
        contract, targetKind: 'process_step', anchorNodeId: 'anchor', connectionDirection: 'outgoing', limit: 3,
    });
    assert.ok((result.rejectionCounts.edge_node_intersection || 0) > 0);
});

check('candidate evaluation never exceeds the contract limit', () => {
    const result = spatial.generatePlacementCandidates(placementScene, Object.assign(
        { contract }, placementCases.anchoredOutgoing
    ));
    assert.ok(result.evaluatedCount <= contract.limits.maximumCandidates);
    assert.ok(result.evaluatedCount <= 96);
});

check('non-finite target kind is rejected without throwing', () => {
    const result = spatial.generatePlacementCandidates(placementScene, {
        contract, targetKind: 'not_a_real_kind',
    });
    assert.deepStrictEqual(result.candidates, []);
    assert.deepStrictEqual(result.rejectionCounts, { invalid_geometry: 1 });
});

check('pan and zoom transforms never alter candidate positions', () => {
    const baseline = spatial.generatePlacementCandidates(placementScene, Object.assign(
        { contract }, placementCases.anchoredOutgoing
    ));
    spatial.worldToViewport(placementScene.nodes[0].rect, { x: 400, y: -50, scale: 0.5 });
    const unaffected = spatial.generatePlacementCandidates(placementScene, Object.assign(
        { contract }, placementCases.anchoredOutgoing
    ));
    assert.deepStrictEqual(baseline, unaffected);
});

check('stale obstacle fingerprint is detectable after a map edit', () => {
    const before = spatial.generatePlacementCandidates(placementScene, { contract, targetKind: 'product_occurrence' });
    const edited = JSON.parse(JSON.stringify(placementMap));
    edited.canvasNodes.push({ nodeId: 'new-obstacle', nodeKind: 'process_step', position: { x: -400, y: 60 } });
    const sceneAfter = spatial.compileSpatialScene(edited, { contract });
    const after = spatial.generatePlacementCandidates(sceneAfter, { contract, targetKind: 'product_occurrence' });
    assert.notStrictEqual(before.obstacleFingerprint, after.obstacleFingerprint);
});

check('candidate identity fields are present for staleness binding', () => {
    const result = spatial.generatePlacementCandidates(placementScene, Object.assign(
        { contract }, placementCases.anchoredOutgoing
    ));
    assert.strictEqual(result.spatialEngineVersion, spatial.SPATIAL_VERSION);
    assert.strictEqual(result.candidatePolicyVersion, spatial.CANDIDATE_POLICY_VERSION);
    assert.strictEqual(result.identity.mapId, 'default');
    assert.strictEqual(result.obstacleFingerprint.length, 16);
    result.candidates.forEach((candidate) => {
        assert.ok('candidateId' in candidate);
        assert.ok('position' in candidate);
        assert.ok('score' in candidate);
    });
});

check('existing-node candidates keep every incident wire clear of cards', () => {
    const processMap = {
        schemaVersion: 3,
        layoutVersion: 2,
        mapId: 'incident-route-probe',
        productId: 'fixture-product',
        canvasNodes: [
            { nodeId: 'a', nodeKind: 'process_step', processType: 'operation', position: { x: 0, y: 0 } },
            { nodeId: 'b', nodeKind: 'process_step', processType: 'operation', position: { x: -480, y: -240 } },
            { nodeId: 'obstacle', nodeKind: 'process_step', processType: 'operation', position: { x: -240, y: -480 } },
        ],
        canvasEdges: [{
            edgeId: 'edge-a-b',
            logicalConnectionId: 'edge-a-b',
            from: { nodeId: 'a', port: 'out' },
            to: { nodeId: 'b', port: 'in' },
            kind: 'precedence',
        }],
        canvasGroups: [],
    };
    const result = spatial.generatePlacementCandidates(
        spatial.compileSpatialScene(processMap, { contract }),
        { contract, targetKind: 'process_step', targetNodeId: 'b' }
    );
    assert.ok(result.candidates.length);
    assert.ok((result.rejectionCounts.edge_node_intersection || 0) > 0);
    result.candidates.forEach((candidate) => {
        const moved = JSON.parse(JSON.stringify(processMap));
        const target = moved.canvasNodes.find((node) => node.nodeId === 'b');
        target.position = candidate.position;
        target.portOrientation = candidate.portOrientation;
        target.portOrder = candidate.portOrder;
        const diagnostics = spatial.diagnoseSpatialScene(
            spatial.compileSpatialScene(moved, { contract }),
            { contract }
        );
        assert.strictEqual(diagnostics.metrics.edgeNodeIntersections, 0);
    });
});

check('anchorless candidates prefer a fully visible world position', () => {
    const visible = { x: 900, y: 500, width: 900, height: 600 };
    const result = spatial.generatePlacementCandidates(placementScene, {
        contract, targetKind: 'product_occurrence', visibleWorldRect: visible,
    });
    assert.ok(result.candidates.length);
    const first = result.candidates[0];
    assert.strictEqual(first.score.regionPreference, 0);
    assert.ok(first.position.x >= visible.x);
    assert.ok(first.position.y >= visible.y);
    assert.ok(first.position.x + 270 <= visible.x + visible.width);
    assert.ok(first.position.y + 146 <= visible.y + visible.height);
});

function phase4RouteMap() {
    return JSON.parse(JSON.stringify(routeFixture.processMap));
}

check('phase 4 route matches the shared Python and JavaScript golden fixture', () => {
    const actual = spatial.routeOrthogonalEdge(
        spatial.compileSpatialScene(routeFixture.processMap, { contract }),
        'route-me',
        { contract }
    );
    assert.deepStrictEqual(actual, routeFixture.expectedRoute);
});

check('phase 4 router is deterministic and avoids non-endpoint cards', () => {
    const processMap = phase4RouteMap();
    const scene = spatial.compileSpatialScene(processMap, { contract });
    const first = spatial.routeOrthogonalEdge(scene, 'route-me', { contract });
    const second = spatial.routeOrthogonalEdge(scene, 'route-me', { contract });
    assert.deepStrictEqual(first, second);
    assert.strictEqual(first.accepted, true);
    assert.strictEqual(first.mode, 'orthogonal_auto');
    assert.ok(first.metrics.bends >= 2);
    assert.strictEqual(first.obstacleFingerprint.length, 16);
    const applied = spatial.applyOrthogonalRoute(processMap, 'route-me', { contract });
    assert.strictEqual(applied.accepted, true);
    assert.deepStrictEqual(
        applied.map.canvasEdges.find((edge) => edge.edgeId === 'route-me').routing.waypoints,
        first.waypoints
    );
    assert.strictEqual('routing' in applied.map.canvasEdges.find((edge) => edge.edgeId === 'legacy-control'), false);
    const diagnostics = spatial.diagnoseSpatialScene(
        spatial.compileSpatialScene(applied.map, { contract }), { contract }
    );
    const routedIntersections = diagnostics.problems.filter((problem) => (
        problem.code === 'edge_node_intersection'
        && (problem.edgeIds || []).indexOf('route-me') >= 0
    ));
    assert.deepStrictEqual(routedIntersections, []);
});

check('auto route refresh follows geometry while manual route stays authored', () => {
    const routed = spatial.applyOrthogonalRoute(phase4RouteMap(), 'route-me', { contract }).map;
    routed.canvasEdges.find((edge) => edge.edgeId === 'legacy-control').routing = {
        mode: 'orthogonal_manual', routerVersion: 1,
        waypoints: [{ x: 290, y: 173 }], obstacleFingerprint: 'manual-owner',
    };
    const before = JSON.parse(JSON.stringify(routed.canvasEdges.find((edge) => edge.edgeId === 'route-me').routing));
    const manualBefore = JSON.parse(JSON.stringify(routed.canvasEdges.find((edge) => edge.edgeId === 'legacy-control').routing));
    routed.canvasNodes.find((node) => node.nodeId === 'obstacle').position = { x: 330, y: 220 };
    const refreshed = spatial.refreshOrthogonalAutoRoutes(routed, { contract });
    assert.deepStrictEqual(refreshed.failures, []);
    assert.notStrictEqual(
        refreshed.map.canvasEdges.find((edge) => edge.edgeId === 'route-me').routing.obstacleFingerprint,
        before.obstacleFingerprint
    );
    assert.deepStrictEqual(
        refreshed.map.canvasEdges.find((edge) => edge.edgeId === 'legacy-control').routing,
        manualBefore
    );
});

check('router fails closed when a port lead is blocked', () => {
    const processMap = phase4RouteMap();
    processMap.canvasNodes.find((node) => node.nodeId === 'obstacle').position = { x: 275, y: 100 };
    const result = spatial.routeOrthogonalEdge(
        spatial.compileSpatialScene(processMap, { contract }), 'route-me', { contract }
    );
    assert.strictEqual(result.accepted, false);
    assert.strictEqual(result.failureReason, 'no_obstacle_free_orthogonal_route');
    assert.deepStrictEqual(result.points, []);
});

check('routed logical connections survive explicit junction insertion and serialization', () => {
    const applied = spatial.applyOrthogonalRoute(phase4RouteMap(), 'route-me', { contract });
    assert.strictEqual(applied.accepted, true);
    const splitPoint = applied.route.points[Math.floor(applied.route.points.length / 2)];
    const split = editor.splitEdgeWithJunction(applied.map, {
        targetEdgeId: 'route-me',
        sourceNodeId: 'obstacle',
        junctionNodeId: 'route-junction',
        firstEdgeId: 'route-first',
        secondEdgeId: 'route-second',
        branchEdgeId: 'route-branch',
        position: splitPoint,
        kind: 'precedence',
    });
    const refreshed = spatial.refreshOrthogonalAutoRoutes(split, { contract });
    assert.deepStrictEqual(refreshed.failures, []);
    const trunk = refreshed.map.canvasEdges.filter((edge) => (
        edge.logicalConnectionId === 'route-me'
    ));
    assert.strictEqual(trunk.length, 2);
    assert.ok(trunk.every((edge) => edge.routing.mode === 'orthogonal_auto'));
    assert.strictEqual(
        refreshed.map.canvasNodes.filter((node) => node.nodeKind === 'junction').length,
        1
    );
    const roundTrip = JSON.parse(JSON.stringify(refreshed.map));
    assert.deepStrictEqual(roundTrip, refreshed.map);
    const diagnostics = spatial.diagnoseSpatialScene(
        spatial.compileSpatialScene(roundTrip, { contract }), { contract }
    );
    assert.strictEqual(diagnostics.metrics.edgeNodeIntersections, 0);
});

check('phase 5 connection geometry preserves semantic identity', () => {
    const processMap = phase4RouteMap();
    const routeEdge = processMap.canvasEdges.find((edge) => edge.edgeId === 'route-me');
    processMap.canvasEdges = processMap.canvasEdges.filter((edge) => edge.edgeId !== 'route-me');
    const suggestion = {
        suggestionId: 'pms-phase5-connection',
        evidenceFingerprint: 'evidence-v1',
        edge: routeEdge,
        validation: { wouldCreateCycle: false, duplicateOfExisting: false },
    };
    const beforeMap = JSON.parse(JSON.stringify(processMap));
    const beforeSuggestion = JSON.parse(JSON.stringify(suggestion));
    const result = spatial.spatializeSemanticSuggestions(processMap, [suggestion], { contract });
    const spatialized = result.suggestions[0];
    const proposal = spatialized.spatialProposal;
    assert.deepStrictEqual(processMap, beforeMap);
    assert.deepStrictEqual(suggestion, beforeSuggestion);
    assert.strictEqual(spatialized.suggestionId, suggestion.suggestionId);
    assert.strictEqual(spatialized.evidenceFingerprint, suggestion.evidenceFingerprint);
    assert.strictEqual(proposal.semanticSuggestionId, suggestion.suggestionId);
    assert.strictEqual(proposal.semanticEvidenceFingerprint, suggestion.evidenceFingerprint);
    assert.strictEqual(proposal.proposalId, 'pm-sp-51f763ad0640268b');
    assert.strictEqual(proposal.accepted, true);
    assert.deepStrictEqual(proposal.route.points, routeFixture.expectedRoute.points);
    assert.deepStrictEqual(proposal.route.waypoints, routeFixture.expectedRoute.waypoints);
    assert.deepStrictEqual(result.summary, {
        spatialized: 1, placementProposals: 0, unavailable: 0,
    });
});

check('phase 5 unplaced target gets one ghost card and routed wire proposal', () => {
    const processMap = {
        schemaVersion: 3, layoutVersion: 3, mapId: 'phase5-placement',
        productId: 'fixture-product',
        canvasNodes: [{
            nodeId: 'anchor', nodeKind: 'product_occurrence',
            sourceOccurrenceId: 'part-a', position: { x: 0, y: 100 },
        }],
        canvasEdges: [], canvasGroups: [],
    };
    const suggestion = {
        suggestionId: 'pms-phase5-placement',
        evidenceFingerprint: 'reviewed-sequence-v1',
        placement: {
            sourceOccurrenceId: 'part-b', nameSnapshot: 'Part B',
            itemIdSnapshot: 'PART-B', anchorNodeId: 'anchor',
            connectionDirection: 'outgoing', edgeKind: 'precedence',
            edgeId: 'phase5-next-edge',
        },
        validation: { wouldCreateCycle: false, duplicateOfExisting: false },
    };
    const first = spatial.spatializeSemanticSuggestions(processMap, [suggestion], { contract });
    const second = spatial.spatializeSemanticSuggestions(
        JSON.parse(JSON.stringify(processMap)),
        [JSON.parse(JSON.stringify(suggestion))],
        { contract }
    );
    assert.deepStrictEqual(first, second);
    const proposal = first.suggestions[0].spatialProposal;
    assert.strictEqual(proposal.accepted, true);
    assert.strictEqual(proposal.placement.node.sourceOccurrenceId, 'part-b');
    assert.strictEqual(proposal.placement.metricsAfter.nodeOverlaps, 0);
    assert.strictEqual(proposal.edge.from.nodeId, 'anchor');
    assert.strictEqual(proposal.edge.to.nodeId, proposal.placement.node.nodeId);
    assert.ok(proposal.route.points.length >= 2);
    assert.strictEqual(first.summary.placementProposals, 1);
});

check('phase 5 relevant geometry edits stale only the spatial proposal', () => {
    const processMap = phase4RouteMap();
    const routeEdge = processMap.canvasEdges.shift();
    const suggestion = {
        suggestionId: 'pms-phase5-staleness', evidenceFingerprint: 'evidence-v1',
        edge: routeEdge, validation: { wouldCreateCycle: false },
    };
    const first = spatial.spatializeSemanticSuggestions(processMap, [suggestion], { contract })
        .suggestions[0];
    const changed = JSON.parse(JSON.stringify(processMap));
    changed.canvasNodes.find((node) => node.nodeId === 'obstacle').position.y += 180;
    const second = spatial.spatializeSemanticSuggestions(changed, [suggestion], { contract })
        .suggestions[0];
    assert.strictEqual(first.suggestionId, second.suggestionId);
    assert.strictEqual(first.evidenceFingerprint, second.evidenceFingerprint);
    assert.notStrictEqual(first.spatialProposal.proposalId, second.spatialProposal.proposalId);
});

check('phase 7 full-map arrangement matches Python fixture and improves the metric', () => {
    const original = JSON.parse(JSON.stringify(arrangementFixture.ungroupedMap));
    const plan = spatial.generateArrangementPlan(original, {
        contract, revision: 'revision-7',
    });
    assert.strictEqual(plan.accepted, true);
    assert.strictEqual(plan.planId, arrangementFixture.expected.ungroupedFullPlanId);
    assert.deepStrictEqual(original, arrangementFixture.ungroupedMap);
    assert.ok(plan.metricsAfter.hardViolationCount < plan.metricsBefore.hardViolationCount);
    assert.deepStrictEqual(plan.hardViolationsAdded, []);
    assert.deepStrictEqual(plan.pinnedNodeIds, ['c']);
    assert.deepStrictEqual(
        plan.proposedMap.canvasNodes.find((node) => node.nodeId === 'c'),
        original.canvasNodes.find((node) => node.nodeId === 'c')
    );
});

check('phase 7 group arrangement preserves its frame and locked member', () => {
    const processMap = JSON.parse(JSON.stringify(arrangementFixture.groupMap));
    const plan = spatial.generateArrangementPlan(processMap, {
        contract, scope: 'group', groupId: 'g',
    });
    assert.strictEqual(plan.accepted, true);
    assert.strictEqual(plan.planId, arrangementFixture.expected.groupPlanId);
    assert.deepStrictEqual(plan.scope, {
        kind: 'group', nodeIds: ['a', 'b', 'c'], groupId: 'g',
    });
    assert.deepStrictEqual(plan.proposedMap.canvasGroups, processMap.canvasGroups);
    assert.deepStrictEqual(
        plan.proposedMap.canvasNodes.find((node) => node.nodeId === 'c'),
        processMap.canvasNodes.find((node) => node.nodeId === 'c')
    );
});

check('phase 7 selection arrangement honors explicit and persisted pins', () => {
    const processMap = JSON.parse(JSON.stringify(arrangementFixture.ungroupedMap));
    const plan = spatial.generateArrangementPlan(processMap, {
        contract,
        scope: 'selection',
        nodeIds: ['a', 'b', 'c'],
        pinnedNodeIds: ['b'],
    });
    assert.ok((plan.moves || []).every((move) => move.nodeId === 'a'));
    assert.deepStrictEqual(plan.pinnedNodeIds, ['b', 'c']);
    if (plan.accepted) {
        assert.deepStrictEqual(
            plan.proposedMap.canvasNodes.find((node) => node.nodeId === 'b'),
            processMap.canvasNodes.find((node) => node.nodeId === 'b')
        );
    }
});

check('arrangement preserves manual and locked positions by default', () => {
    const processMap = JSON.parse(JSON.stringify(arrangementFixture.ungroupedMap));
    const byId = Object.fromEntries(
        processMap.canvasNodes.map((node) => [node.nodeId, node])
    );
    byId.a.positionMode = 'manual';
    byId.b.positionMode = 'auto';
    byId.c.positionMode = 'locked';
    byId.c.locked = true;
    const plan = spatial.generateArrangementPlan(processMap, { contract });
    assert.deepStrictEqual(plan.pinnedNodeIds, ['a', 'c']);
    if (plan.accepted) {
        const proposed = Object.fromEntries(
            plan.proposedMap.canvasNodes.map((node) => [node.nodeId, node])
        );
        assert.deepStrictEqual(proposed.a.position, byId.a.position);
        assert.deepStrictEqual(proposed.c.position, byId.c.position);
        assert.ok(plan.moves.every((move) => move.nodeId === 'b'));
    }
});

check('phase 7 refuses a full-map cleanup when every card is pinned', () => {
    const processMap = JSON.parse(JSON.stringify(arrangementFixture.ungroupedMap));
    processMap.canvasNodes.forEach((node) => { node.locked = true; });
    const plan = spatial.generateArrangementPlan(processMap, { contract });
    assert.strictEqual(plan.accepted, false);
    assert.strictEqual(plan.failureReason, 'no_movable_nodes');
    assert.deepStrictEqual(plan.moves, []);
});

Promise.all(pendingChecks).then(() => {
    process.stdout.write(`Process-map spatial checks: ${checks}/44 passed\n`);
}).catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
});
