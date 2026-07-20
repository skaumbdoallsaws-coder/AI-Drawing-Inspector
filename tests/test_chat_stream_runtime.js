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

test('visual queue preserves every streamed character in order', () => {
    const queue = runtime.createVisualTextQueue();
    const expected = 'Natural model chunks can arrive by word, but display stays smooth.';
    queue.push(expected.slice(0, 17));
    queue.push(expected.slice(17, 38));
    queue.push(expected.slice(38));

    let rendered = '';
    for (let now = 0; queue.pendingLength && now < 5000; now += 20) {
        const step = queue.drain(now);
        rendered += step.appended;
    }
    assert.strictEqual(rendered, expected);
    assert.strictEqual(queue.displayedText, expected);
    assert.strictEqual(queue.visibleText, expected);
    assert.strictEqual(queue.pendingLength, 0);
});

test('visual queue accelerates when backlog grows', () => {
    assert(runtime.visualDisplayRate(81) > runtime.visualDisplayRate(79));
    assert(runtime.visualDisplayRate(241) > runtime.visualDisplayRate(239));
    assert(runtime.visualDisplayRate(1201) > runtime.visualDisplayRate(1199));

    const queue = runtime.createVisualTextQueue();
    queue.push('x'.repeat(1300));
    queue.drain(0);
    const step = queue.drain(40);
    assert(step.rate >= 850);
    assert(step.appended.length > 1);
});

test('visual queue flushes immediately at terminal commit', () => {
    const queue = runtime.createVisualTextQueue();
    queue.push('authoritative final text');
    queue.drain(0);
    const flushed = queue.flush();
    assert.strictEqual(queue.pendingLength, 0);
    assert.strictEqual(queue.visibleText, 'authoritative final text');
    assert(flushed.appended.length > 0);
});

test('visual queue waits for visible text but retains leading whitespace', () => {
    const queue = runtime.createVisualTextQueue();
    queue.push('  \nHello');
    const first = queue.revealFirstVisible();
    assert.strictEqual(first.appended, '  \nH');
    assert.strictEqual(queue.displayedText, '  \nH');
    assert.strictEqual(queue.visibleText, '  \nHello');
    queue.flush();
    assert.strictEqual(queue.displayedText, '  \nHello');
});

test('disposed visual queues ignore late deltas and drains', () => {
    const queue = runtime.createVisualTextQueue();
    queue.push('abc');
    queue.drain(0);
    const before = queue.displayedText;
    queue.dispose();
    queue.push('late');
    const step = queue.drain(20);
    assert.strictEqual(step.changed, false);
    assert.strictEqual(queue.displayedText, before);
    assert.strictEqual(queue.pendingLength, 0);
});

console.log(passed + ' passed, ' + (process.exitCode ? 1 : 0) + ' failed');
