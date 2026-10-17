'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const runtime = require('../static/chat_stream_runtime.js');
const memoryRuntime = require('../static/chat_memory_runtime.js');

const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
const streamStart = html.indexOf('async function _requestAgentChatStream(');
const streamEnd = html.indexOf('window.__agentChatStreamV1 =', streamStart);
const sendStart = html.lastIndexOf('let data = null;', html.indexOf('const streamedReply = await _requestAgentChatStream('));
const sendEnd = html.indexOf('terminalResponseData = data;', sendStart);
assert(streamStart >= 0 && streamEnd > streamStart && sendStart >= 0 && sendEnd > sendStart);
const nativePrompt = 'Walk me through the saved layout facts: inspect the zones and equipment in this gym. Keep it brief and do not change anything.';
const tick = () => new Promise(resolve => setImmediate(resolve));

function jsonResponse(status, body) {
    return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function waitForAbort(signal) {
    return new Promise((resolve, reject) => {
        const abort = () => reject(new DOMException('Aborted', 'AbortError'));
        if (signal.aborted) abort();
        else signal.addEventListener('abort', abort, { once: true });
    });
}

function fixture(options = {}) {
    const listeners = new Set(), timers = new Set(), requests = [];
    const state = { loaded: true, dirty: false, conflict: null, baseRevision: 'r1', draftRevision: 'r1',
        layout: { layoutId: 'gym', association: { siteId: 'site' } } };
    const session = { requestId: 1, chatSessionId: 'chat', activeStream: null };
    const app = { session: { getState: () => state, subscribe: fn => {
        listeners.add(fn); return () => listeners.delete(fn);
    } } };
    let released = 0;
    const working = { setOperation() {}, beginStreaming() {} };
    const payload = { message: nativePrompt, inspection_context: { attachments: {
        session: { active_mode: options.mode || 'facility_layout' },
        facility_layout: { siteId: 'site', layoutId: 'gym', revision: 'r1' },
    } } };
    const status = Object.hasOwn(options, 'status') ? options.status
        : { facilityRuntime: 'codex', enabled: true, agents: ['sage', 'iris'] };
    const context = {
        AbortController, TextDecoder, currentAgent: 'deviation-analyst', state: { activeTab: 'training' },
        _getChatStreamingStatus: async () => status,
        _agentStreamingName: agent => agent === 'deviation-analyst' ? 'sage' : 'iris',
        _trainFacilityLayoutAuthoringApp: app, _trainIsFacilityLayoutMode: () => true,
        _chatMemoryRuntime: memoryRuntime, _parseAgentStreamEventLine: runtime.parseEventLine,
        ensureAgentWorkingState: () => working, setWaiting() {}, removeTypingIndicator() {},
        createStreamingAssistantMessage: () => ({ message: { meta: {} }, appendInitialText() {}, appendText() {} }),
        window: { InspectorProChatStreamRuntime: { ...runtime,
            guardSavedFacilityContext: args => runtime.guardSavedFacilityContext({ ...args,
                setInterval: fn => { timers.add(fn); return fn; }, clearInterval: fn => timers.delete(fn),
            }),
        } },
        fetch: async (url, init) => {
            const request = { url, ...init };
            requests.push(request);
            if (url === '/api/agent/chat') return options.batchResponse || jsonResponse(200, { response: 'legacy' });
            if (options.fetchStream) return options.fetchStream(request, stream);
            return stream();
        },
    };
    function stream(events = [{ event: 'response_completed', final: { response: 'saved facts', tool_calls: [] } }], after) {
        const packets = events.map((event, seq) => new TextEncoder().encode(
            'data: ' + JSON.stringify({ v: 1, response_id: 'response', seq, ...event }) + '\n\n'));
        return { ok: true, status: 200, body: { getReader: () => ({
            read: async () => packets.length ? { done: false, value: packets.shift() }
                : after ? after() : { done: true },
            releaseLock: () => released++,
        }) } };
    }
    vm.createContext(context);
    vm.runInContext(html.slice(streamStart, streamEnd) + '\n' +
        'async function send(payload, originAgent, originSession, turnId, workingAssistant) {' +
        'let streamingAssistant, streamTrace;\n' + html.slice(sendStart, sendEnd) + '\nreturn data;\n}', context);
    return { state, session, context, requests, payload, working,
        send: () => context.send(payload, options.agent || 'deviation-analyst', session, 1, working),
        notify: () => { for (const fn of listeners) fn(); },
        poll: () => { for (const fn of timers) fn(); },
        assertClean: () => {
            assert.equal(listeners.size, 0); assert.equal(timers.size, 0);
            assert.equal(session.activeStream, null);
        },
        released: () => released,
    };
}

function required(error) {
    assert.equal(error.agentServiceFailure, true);
    assert.equal(error.agentErrorCode, 'codex_stream_required');
    assert.equal(error.streamRetryable, false);
    return true;
}

test('native walkthrough wording uses cancellable SSE and disposes the saved-context guard', async () => {
    const f = fixture();
    assert.equal((await f.send()).response, 'saved facts');
    assert.deepEqual(f.requests.map(item => item.url), ['/api/agent/chat/v2/stream']);
    assert(f.requests[0].signal instanceof AbortSignal);
    assert.equal(f.released(), 1);
    f.assertClean();
});

for (const status of [
    { facilityRuntime: 'codex', enabled: false, agents: ['sage'] },
    { facilityRuntime: 'codex', enabled: true, agents: ['iris'] },
    { facilityRuntime: 'codex', enabled: true },
]) {
    test('known Codex uses SSE independently of legacy streaming gates: ' + JSON.stringify(status), async () => {
        const f = fixture({ status });
        assert.equal((await f.send()).response, 'saved facts');
        assert.deepEqual(f.requests.map(item => item.url), ['/api/agent/chat/v2/stream']);
        assert(f.requests[0].signal instanceof AbortSignal);
        f.assertClean();
    });
}

const failures = {
    network: () => { throw new TypeError('network unavailable'); },
    'HTTP 404': () => jsonResponse(404, {}),
    'HTTP 409': () => jsonResponse(409, {}),
    'empty stream': (_, stream) => stream([]),
    'unterminated stream': (_, stream) => stream([{ event: 'status', phase: 'codex_inspecting' }]),
    'missing final': (_, stream) => stream([{ event: 'response_completed' }]),
    'reader failure': (_, stream) => stream([], () => { throw new TypeError('read failed'); }),
    'partial reader failure': (_, stream) => stream([{ event: 'text_delta', text: 'Facts' }],
        () => { throw new TypeError('read failed'); }),
    'missing body': () => ({ ok: true, body: null }),
};
for (const [name, fetchStream] of Object.entries(failures)) {
    test('Codex fails closed without batch inference: ' + name, async () => {
        const f = fixture({ fetchStream });
        await assert.rejects(f.send(), required);
        assert.deepEqual(f.requests.map(item => item.url), ['/api/agent/chat/v2/stream']);
        f.assertClean();
    });
}

for (const [name, fetchStream, code] of [
    ['HTTP failure', () => jsonResponse(503, { detail: { error: { code: 'codex_runtime_failed', message: 'Unavailable' } } }), 'codex_runtime_failed'],
    ['terminal error', (_, stream) => stream([{ event: 'response_error', code: 'codex_runtime_stopped', retryable: false }]), 'codex_runtime_stopped'],
]) {
    test('Codex preserves classified failures without batch fallback: ' + name, async () => {
        const f = fixture({ fetchStream });
        await assert.rejects(f.send(), error => error.agentServiceFailure && error.agentErrorCode === code);
        assert.equal(f.requests.length, 1);
        f.assertClean();
    });
}

for (const phase of ['fetch', 'read']) {
    for (const [name, mutate] of Object.entries({
        dirty: f => { f.state.dirty = true; },
        revision: f => { f.state.baseRevision = 'r2'; },
        layout: f => { f.state.layout.layoutId = 'other'; },
        app: f => { f.context._trainFacilityLayoutAuthoringApp = {}; },
    })) {
        test('native walkthrough cancels on ' + name + ' during ' + phase + ', never batch', async () => {
            const f = fixture({ fetchStream: (request, stream) => phase === 'fetch'
                ? waitForAbort(request.signal) : stream([], () => waitForAbort(request.signal)) });
            const result = assert.rejects(f.send(), error => error.streamCancelled === true);
            await tick();
            mutate(f); f.notify(); f.poll();
            await result;
            assert.equal(f.requests.length, 1);
            assert.equal(f.requests[0].signal.aborted, true);
            f.assertClean();
        });
    }
}

test('user Stop remains cancellation rather than a retry or batch fallback', async () => {
    const f = fixture({ fetchStream: request => waitForAbort(request.signal) });
    const result = assert.rejects(f.send(), error => error.streamCancelled && !error.agentServiceFailure);
    await tick();
    f.session.activeStream.controller.abort();
    await result;
    assert.equal(f.requests.length, 1);
    f.assertClean();
});

for (const status of [null, { facilityRuntime: 'legacy', enabled: true, agents: ['sage'] }]) {
    test('unknown or cached legacy status surfaces the batch HTTP rejection: ' + JSON.stringify(status), async () => {
        const f = fixture({ status, batchResponse: jsonResponse(409, { detail: { error: {
            code: 'codex_stream_required', message: 'Use streaming', retryable: false,
        } } }) });
        await assert.rejects(f.send(), required);
        assert.deepEqual(f.requests.map(item => item.url), ['/api/agent/chat']);
        f.assertClean();
    });
}

for (const [name, options] of [
    ['legacy walkthrough', { status: { facilityRuntime: 'legacy', enabled: true, agents: ['sage'] } }],
    ['legacy streaming disabled', { status: { facilityRuntime: 'legacy', enabled: false, agents: ['sage'] } }],
    ['non-facility walkthrough', { mode: 'assembly' }],
    ['another agent walkthrough', { agent: 'inspector' }],
    ['non-facility streaming disabled', { mode: 'assembly', status: { facilityRuntime: 'codex', enabled: false, agents: [] } }],
    ['another agent streaming disabled', { agent: 'inspector', status: { facilityRuntime: 'codex', enabled: false, agents: [] } }],
]) {
    test(name + ' retains batch behavior', async () => {
        const f = fixture(options);
        assert.equal((await f.send()).response, 'legacy');
        assert.deepEqual(f.requests.map(item => item.url), ['/api/agent/chat']);
        f.assertClean();
    });
}

test('legacy SSE transport failure retains its batch fallback', async () => {
    const f = fixture({ status: { facilityRuntime: 'legacy', enabled: true, agents: ['sage'] },
        fetchStream: failures.network });
    f.payload.message = 'Inspect this layout';
    assert.equal((await f.send()).response, 'legacy');
    assert.deepEqual(f.requests.map(item => item.url), ['/api/agent/chat/v2/stream', '/api/agent/chat']);
    f.assertClean();
});

test('required-stream failure uses an actionable message without provider details', () => {
    const start = html.indexOf('function _agentServiceFailureText(');
    const format = new Function('AGENTS', html.slice(start, streamStart) + '\nreturn _agentServiceFailureText;')({
        'deviation-analyst': { name: 'Configured agent' },
    });
    const message = format('deviation-analyst', { agentErrorCode: 'codex_stream_required', message: 'secret' });
    assert(message.includes('Configured agent'));
    assert(message.includes('live streaming connection'));
    assert(message.includes('Reload the app'));
    assert(!message.includes('secret'));
});

test('partial answers display budget failures rather than mislabeling them as user Stop', async () => {
    const f = fixture({ fetchStream: (_, stream) => stream([
        { event: 'text_delta', text: 'I will create the court.' },
        { event: 'response_error', code: 'codex_time_budget_exhausted', retryable: false },
    ]) });
    let failure;
    await assert.rejects(f.send(), error => { failure = error; return error.agentServiceFailure; });
    assert.equal(failure.streamPartial, true);
    const start = html.indexOf('function _agentServiceFailureText(');
    const format = new Function('AGENTS', html.slice(start, streamStart) + '\nreturn _agentPartialFailureText;')({
        'deviation-analyst': { name: 'Configured agent' },
    });
    const message = format('deviation-analyst', failure);
    assert(message.includes('execution time limit'));
    assert(message.includes('No engineering changes were saved'));
    assert(!message.includes('less busy'));
    assert(format('deviation-analyst', { streamCancelled: true }).startsWith('Response stopped.'));
    assert(html.includes('err.streamingMessage.fail(_agentPartialFailureText(originAgent, err))'));
    assert.equal(f.requests.length, 1);
    f.assertClean();
});
