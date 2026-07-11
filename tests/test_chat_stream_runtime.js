'use strict';

const assert = require('assert');
const runtime = require('../static/chat_stream_runtime.js');

let passed = 0;
function test(name, fn) {
    try {
        fn();
        passed += 1;
        console.log('PASS ' + name);
    } catch (error) {
        console.error('FAIL ' + name + ': ' + error.message);
        process.exitCode = 1;
    }
}

function event(seq, type, id = 'r1', extra = {}) {
    return { v: 1, event: type, response_id: id, seq, ts: 1, ...extra };
}

test('SSE decoder tolerates byte-boundary line splits', () => {
    const decoder = new runtime.SseDecoder();
    const wire = 'data: ' + JSON.stringify(event(0, 'response_started')) + '\n\n'
        + 'data: ' + JSON.stringify(event(1, 'text_delta', 'r1', { text: 'hello' })) + '\n\n';
    const output = [];
    for (const char of wire) output.push(...decoder.push(char));
    output.push(...decoder.finish());
    assert.deepStrictEqual(output.map(item => item.event), ['response_started', 'text_delta']);
    assert.strictEqual(output[1].text, 'hello');
});

test('event gate drops duplicate and reordered sequence numbers', () => {
    const gate = runtime.createEventGate();
    assert.strictEqual(gate.accept(event(0, 'response_started')), true);
    assert.strictEqual(gate.accept(event(1, 'text_delta')), true);
    assert.strictEqual(gate.accept(event(1, 'text_delta')), false);
    assert.strictEqual(gate.accept(event(0, 'text_delta')), false);
    assert.strictEqual(gate.lastSeq, 1);
});

test('event gate drops stale response IDs', () => {
    const gate = runtime.createEventGate();
    assert.strictEqual(gate.accept(event(0, 'response_started', 'active')), true);
    assert.strictEqual(gate.accept(event(1, 'text_delta', 'stale')), false);
    assert.strictEqual(gate.accept(event(1, 'text_delta', 'active')), true);
});

test('event gate accepts one terminal event only', () => {
    const gate = runtime.createEventGate();
    assert.strictEqual(gate.accept(event(0, 'response_started')), true);
    assert.strictEqual(gate.accept(event(1, 'response_completed')), true);
    assert.strictEqual(gate.accept(event(2, 'response_error')), false);
    assert.strictEqual(gate.terminal, true);
});

test('garbage and unsupported envelopes are ignored', () => {
    assert.strictEqual(runtime.parseEventLine('garbage'), null);
    assert.strictEqual(runtime.parseEventLine('data: not-json'), null);
    assert.strictEqual(runtime.parseEventLine('data: {"v":2,"event":"x"}'), null);
});

console.log(passed + ' passed, ' + (process.exitCode ? 1 : 0) + ' failed');
