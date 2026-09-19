'use strict';

const fs = require('fs');
const path = require('path');
const { performance } = require('perf_hooks');
const spatial = require('../static/process_map_spatial.js');

const contract = JSON.parse(fs.readFileSync(
    path.join(__dirname, '..', 'static', 'contracts', 'process-map-spatial-contract-v1.json'),
    'utf8'
));

function benchmarkMap() {
    const nodes = [];
    for (let index = 0; index < 250; index += 1) {
        nodes.push({
            nodeId: 'n-' + index,
            nodeKind: 'process_step',
            processType: 'operation',
            name: 'Operation ' + index,
            position: {
                x: (index % 25) * 360,
                y: Math.floor(index / 25) * 220,
            },
            portOrientation: 'horizontal',
            portOrder: 'input_first',
        });
    }
    const edges = [];
    function addEdge(from, to) {
        edges.push({
            edgeId: 'e-' + edges.length,
            from: { nodeId: 'n-' + from, port: 'out' },
            to: { nodeId: 'n-' + to, port: 'in' },
            kind: 'precedence',
        });
    }
    for (let index = 0; index < 249; index += 1) addEdge(index, index + 1);
    for (let index = 0; index < 151; index += 1) addEdge(index, index + 50);
    return {
        schemaVersion: 3,
        layoutVersion: 3,
        mapId: 'default',
        productId: 'benchmark',
        sourceStructureRevision: 'benchmark-structure',
        canvasNodes: nodes,
        canvasEdges: edges,
        canvasGroups: [],
    };
}

function percentile(values, fraction) {
    const sorted = values.slice().sort((left, right) => left - right);
    return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * fraction))];
}

function measure(callback, iterations) {
    const values = [];
    callback();
    callback();
    for (let index = 0; index < iterations; index += 1) {
        const started = performance.now();
        callback();
        values.push(performance.now() - started);
    }
    return {
        medianMs: Number(percentile(values, 0.5).toFixed(1)),
        p95Ms: Number(percentile(values, 0.95).toFixed(1)),
        maximumMs: Number(Math.max.apply(null, values).toFixed(1)),
    };
}

const processMap = benchmarkMap();
let scene = spatial.compileSpatialScene(processMap, { contract: contract });
const compileDiagnose = measure(function () {
    scene = spatial.compileSpatialScene(processMap, { contract: contract });
    spatial.diagnoseSpatialScene(scene, { contract: contract });
}, 7);
const candidates = measure(function () {
    const current = spatial.compileSpatialScene(processMap, { contract: contract });
    const result = spatial.generatePlacementCandidates(current, {
        contract: contract,
        targetKind: 'process_step',
        anchorNodeId: 'n-20',
        connectionDirection: 'outgoing',
        preferredFlowDirection: 'left_to_right',
        limit: 3,
    });
    if (result.candidates.length !== 3) {
        throw new Error('benchmark expected exactly three placement candidates');
    }
}, 7);
const reroute = measure(function () {
    const result = spatial.routeOrthogonalEdge(scene, 'e-20', { contract: contract });
    if (!result || typeof result.accepted !== 'boolean') {
        throw new Error('benchmark route did not return a routing result');
    }
}, 9);

const report = {
    fixture: { nodes: 250, edges: 400 },
    compileDiagnose: compileDiagnose,
    threeCandidates: candidates,
    rerouteOneConnection: reroute,
    thresholds: {
        compileDiagnoseMedianMs: 150,
        threeCandidatesMedianMs: 400,
        threeCandidatesP95Ms: 1000,
        rerouteMedianMs: 100,
    },
};

const failures = [];
if (compileDiagnose.medianMs > 150) failures.push('compile+diagnose median');
if (candidates.medianMs > 400) failures.push('candidate median');
if (candidates.p95Ms > 1000) failures.push('candidate p95');
if (reroute.medianMs > 100) failures.push('reroute median');
console.log(JSON.stringify(report, null, 2));
if (failures.length) {
    console.error('Performance gate failed: ' + failures.join(', '));
    process.exitCode = 1;
}
