'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { captureStream } = require('../tools/codex-stream-evidence.cjs');
const data = text => Buffer.from(text).toString('base64');
const event = value => 'data: ' + JSON.stringify(value) + '\n\n';
const terminal = { event: 'response_completed', final: { response: 'Checked' } };

test('captures prefix and live bytes in order without reading the evictable response cache', async () => {
  let resolve;
  const commands = [];
  const turn = { startedAt: Date.now() };
  const observe = captureStream({ sendCommand(method, params) {
    commands.push({ method, params });
    return new Promise(done => { resolve = done; });
  } }, 'chat', turn);
  observe('Network.responseReceived', { requestId: 'chat' });
  const full = Buffer.from(event({ event: 'text_delta', text: '240 m\u00b2', phase: 'inspecting' }) + event(terminal));
  const split = full.indexOf(Buffer.from('\u00b2')) + 1;
  observe('Network.dataReceived', { requestId: 'other', data: data('unrelated CAD bytes') });
  observe('Network.dataReceived', { requestId: 'chat', data: full.subarray(split).toString('base64') });
  const completed = observe('Network.loadingFinished', { requestId: 'chat' });
  resolve({ bufferedData: full.subarray(0, split).toString('base64') });
  await completed;
  assert.deepEqual(commands, [{ method: 'Network.streamResourceContent', params: { requestId: 'chat' } }]);
  assert.deepEqual(turn.terminal, terminal);
  assert.deepEqual(turn.phases, ['inspecting']);
  assert.equal(turn.textDeltas, 1);
  assert.ok(turn.elapsedSeconds >= 0);
  assert.equal(turn.evidenceError, undefined);
});

test('reports streaming setup errors instead of misreporting a model timeout', async () => {
  const turn = {};
  const observe = captureStream({ sendCommand: async () => { throw new Error('Streaming unavailable'); } }, 'chat', turn);
  observe('Network.responseReceived', { requestId: 'chat' });
  await observe('Network.loadingFinished', { requestId: 'chat' });
  assert.equal(turn.evidenceError, 'Streaming unavailable');
  assert.equal(turn.terminal, undefined);
});

test('bounds buffered and live evidence together', async () => {
  const turn = {};
  const observe = captureStream({ sendCommand: async () => ({ bufferedData: data('12345') }) }, 'chat', turn, 8);
  observe('Network.responseReceived', { requestId: 'chat' });
  observe('Network.dataReceived', { requestId: 'chat', data: data('6789') });
  await observe('Network.loadingFinished', { requestId: 'chat' });
  assert.match(turn.evidenceError, /byte limit/);
  assert.equal(turn.terminal, undefined);
});

test('does not claim completion for an interrupted or truncated stream', async () => {
  for (const failed of [false, true]) {
    const turn = {};
    const observe = captureStream({ sendCommand: async () => ({ bufferedData: data(event({ event: 'text_delta', text: 'partial' })) }) }, 'chat', turn);
    observe('Network.responseReceived', { requestId: 'chat' });
    if (failed) observe('Network.loadingFailed', { requestId: 'chat', errorText: 'net::ERR_ABORTED' });
    await observe('Network.loadingFinished', { requestId: 'chat' });
    assert.equal(turn.terminal, undefined);
    if (failed) assert.equal(turn.networkError, 'net::ERR_ABORTED');
    else assert.match(turn.evidenceError, /without a terminal event/);
  }
});
