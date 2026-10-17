'use strict';

// Capture only the test chat stream, before unrelated CAD loads can evict it.
function captureStream(debuggerApi, requestId, turn, maxBytes = 4 * 1024 * 1024) {
  let started;
  let prefix = Buffer.alloc(0);
  let chunks = [];
  let bytes = 0;
  let finished = false;
  const fail = error => {
    turn.evidenceError = error.message;
    prefix = Buffer.alloc(0);
    chunks = [];
  };
  const decode = encoded => {
    const chunk = Buffer.from(encoded || '', 'base64');
    bytes += chunk.length;
    if (bytes > maxBytes) throw new Error('Chat evidence exceeded its byte limit');
    return chunk;
  };
  const finish = async () => {
    if (finished) return;
    finished = true;
    try {
      if (!started) throw new Error('Chat response headers were not observed');
      await started;
      if (turn.evidenceError || turn.networkError) return;
      const text = Buffer.concat([prefix, ...chunks]).toString('utf8');
      const events = text.split(/\r?\n/).filter(line => line.startsWith('data: '))
        .map(line => JSON.parse(line.slice(6)));
      turn.phases = [...new Set(events.map(event => event.phase).filter(Boolean))];
      turn.textDeltas = events.filter(event => event.event === 'text_delta').length;
      turn.terminal = events.findLast(event =>
        ['response_completed', 'response_error', 'response_cancelled'].includes(event.event));
      if (!turn.terminal) throw new Error('Chat stream ended without a terminal event');
      turn.elapsedSeconds = (Date.now() - turn.startedAt) / 1000;
    } catch (error) {
      fail(error);
    } finally {
      prefix = Buffer.alloc(0);
      chunks = [];
    }
  };
  return (method, params) => {
    if (params.requestId !== requestId) return;
    if (method === 'Network.responseReceived' && !started) {
      started = debuggerApi.sendCommand('Network.streamResourceContent', { requestId })
        .then(({ bufferedData }) => {
          if (!turn.evidenceError && !turn.networkError) prefix = decode(bufferedData);
        }).catch(fail);
    }
    if (method === 'Network.dataReceived' && params.data && !finished && !turn.evidenceError) {
      try { chunks.push(decode(params.data)); } catch (error) { fail(error); }
    }
    if (method === 'Network.loadingFailed') {
      turn.networkError = params.errorText;
      finished = true;
      prefix = Buffer.alloc(0);
      chunks = [];
    }
    if (method === 'Network.loadingFinished') return finish();
  };
}

module.exports = { captureStream };
