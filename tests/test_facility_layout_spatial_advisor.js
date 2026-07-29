'use strict';

const assert = require('assert');
const Advisor = require('../static/facility_layout_spatial_advisor.js');

const tests = [];
function test(name, fn) { tests.push({ name, fn }); }

class FakeWorker {
    constructor() {
        this.listeners = { message: new Set(), error: new Set() };
        this.messages = [];
        this.terminated = false;
    }

    addEventListener(type, listener) {
        this.listeners[type].add(listener);
    }

    removeEventListener(type, listener) {
        this.listeners[type].delete(listener);
    }

    postMessage(message) {
        this.messages.push(JSON.parse(JSON.stringify(message)));
    }

    emit(message) {
        this.listeners.message.forEach(listener => listener({ data: message }));
    }

    terminate() {
        this.terminated = true;
    }
}

function envelope(status) {
    return {
        authority: 'browser-advisory',
        authoritative: false,
        status,
        summary: status,
    };
}

test('latest request wins and stale worker messages are ignored', async () => {
    const worker = new FakeWorker();
    const advisor = Advisor.createSpatialAdvisor({
        workerFactory: () => worker,
    });
    const first = advisor.request({ sequence: 1 });
    const firstId = worker.messages[0].requestId;
    const second = advisor.request({ sequence: 2 });
    const analyzeMessages = worker.messages.filter(
        item => item.type === 'analyze'
    );
    const secondId = analyzeMessages[1].requestId;
    await assert.rejects(first, error => error.name === 'AbortError');
    assert.ok(worker.messages.some(item => (
        item.type === 'cancel' && item.requestId === firstId
    )));
    worker.emit({
        type: 'advisory-result',
        requestId: firstId,
        advisory: envelope('attention'),
    });
    worker.emit({
        type: 'advisory-result',
        requestId: secondId,
        advisory: envelope('clear'),
    });
    assert.strictEqual((await second).status, 'clear');
    assert.strictEqual(advisor.getState().activeRequestId, null);
    advisor.destroy();
});

test('AbortSignal cancels the worker request', async () => {
    const worker = new FakeWorker();
    const advisor = Advisor.createSpatialAdvisor({
        workerFactory: () => worker,
    });
    const controller = new AbortController();
    const pending = advisor.request({ sequence: 1 }, {
        signal: controller.signal,
    });
    const requestId = worker.messages[0].requestId;
    controller.abort();
    await assert.rejects(pending, error => error.name === 'AbortError');
    assert.ok(worker.messages.some(item => (
        item.type === 'cancel' && item.requestId === requestId
    )));
    advisor.destroy();
});

test('rejects any worker envelope that claims authority', async () => {
    const worker = new FakeWorker();
    const advisor = Advisor.createSpatialAdvisor({
        workerFactory: () => worker,
    });
    const pending = advisor.request({});
    worker.emit({
        type: 'advisory-result',
        requestId: worker.messages[0].requestId,
        advisory: {
            authority: 'server-authoritative',
            authoritative: true,
        },
    });
    await assert.rejects(
        pending,
        error => error.code === 'facility_spatial_advisory_protocol_error'
    );
    advisor.destroy();
});

test('destroy cancels pending work and terminates exactly once', async () => {
    const worker = new FakeWorker();
    const advisor = Advisor.createSpatialAdvisor({
        workerFactory: () => worker,
    });
    const pending = advisor.request({});
    assert.strictEqual(advisor.destroy(), true);
    assert.strictEqual(advisor.destroy(), false);
    await assert.rejects(pending, error => error.name === 'AbortError');
    assert.strictEqual(worker.terminated, true);
});

(async () => {
    let passed = 0;
    for (const item of tests) {
        await item.fn();
        passed += 1;
        console.log('ok - ' + item.name);
    }
    console.log('Facility layout spatial advisor tests: '
        + passed + '/' + tests.length + ' passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
