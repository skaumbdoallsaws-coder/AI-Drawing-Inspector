'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const WorkerRuntime = require('../static/facility_layout_spatial_worker.js');

const fixture = JSON.parse(fs.readFileSync(path.join(
    __dirname,
    'fixtures',
    'facility_layout',
    'spatial',
    'p6-browser-advisory.json'
), 'utf8'));

const tests = [];
function test(name, fn) { tests.push({ name, fn }); }

function payload(position) {
    return {
        layoutRevision: 'rev-1',
        layout: fixture.layout,
        assetCatalog: fixture.assetCatalog,
        ghost: {
            assetId: 'asset-machine',
            assetDefinitionRevision: 'revision-asset-machine',
            worldPosition: position,
        },
    };
}

class FakeScope {
    constructor() {
        this.listeners = new Set();
        this.messages = [];
    }

    addEventListener(type, listener) {
        if (type === 'message') this.listeners.add(listener);
    }

    removeEventListener(type, listener) {
        if (type === 'message') this.listeners.delete(listener);
    }

    postMessage(message) {
        this.messages.push(JSON.parse(JSON.stringify(message)));
    }

    emit(message) {
        this.listeners.forEach(listener => listener({ data: message }));
    }
}

test('coarse overlap and zone results are explicitly non-authoritative', () => {
    const advisory = WorkerRuntime.evaluateAdvisory(
        payload({ x: 3.5, y: 0, z: 3 })
    );
    assert.strictEqual(advisory.authority, 'browser-advisory');
    assert.strictEqual(advisory.authoritative, false);
    assert.strictEqual(advisory.status, 'attention');
    assert.deepStrictEqual(advisory.overlapPlacementIds, ['pl-existing']);
    assert.deepStrictEqual(advisory.containingZoneIds, ['zn-machines']);
    assert.ok(advisory.findings.some(item => item.code === 'coarse_overlap'));
    assert.strictEqual('safe' in advisory, false);
});

test('clear placement reports compatible containing zone', () => {
    const advisory = WorkerRuntime.evaluateAdvisory(
        payload({ x: 7, y: 0, z: 3 })
    );
    assert.strictEqual(advisory.status, 'clear');
    assert.deepStrictEqual(advisory.overlapPlacementIds, []);
    assert.deepStrictEqual(advisory.compatibleZoneIds, ['zn-machines']);
});

test('outside-zone feedback remains advisory rather than a validity verdict', () => {
    const advisory = WorkerRuntime.evaluateAdvisory(
        payload({ x: 14, y: 0, z: 4 })
    );
    assert.strictEqual(advisory.status, 'attention');
    assert.ok(advisory.findings.some(
        item => item.code === 'outside_authored_zones'
    ));
    assert.strictEqual('valid' in advisory, false);
});

test('worker runtime cancels queued work and only emits the latest request', () => {
    const scope = new FakeScope();
    const queue = [];
    const cleanup = WorkerRuntime.installWorkerRuntime(scope, {
        schedule(callback) { queue.push(callback); },
    });
    scope.emit({
        type: 'analyze',
        requestId: 'request-1',
        payload: payload({ x: 3, y: 0, z: 3 }),
    });
    scope.emit({
        type: 'analyze',
        requestId: 'request-2',
        payload: payload({ x: 7, y: 0, z: 3 }),
    });
    queue.forEach(callback => callback());
    assert.strictEqual(scope.messages.length, 1);
    assert.strictEqual(scope.messages[0].requestId, 'request-2');
    assert.strictEqual(scope.messages[0].advisory.status, 'clear');
    cleanup();
    assert.strictEqual(scope.listeners.size, 0);
});

(async () => {
    let passed = 0;
    for (const item of tests) {
        await item.fn();
        passed += 1;
        console.log('ok - ' + item.name);
    }
    console.log('Facility layout spatial worker tests: '
        + passed + '/' + tests.length + ' passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
