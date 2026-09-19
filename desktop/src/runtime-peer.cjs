'use strict';
const { randomUUID } = require('node:crypto');
const METHODS = new Set(['snapshot','freeze','unfreeze','setStartupRecoveryGate','restoreRecovery','acceptReconciliation','inspectOtherWorkflows']);
const fail = code => Object.assign(new Error(code), { code });
function createRuntimePeer({ getContents, timeoutMs = 15000 }) {
  const pending = new Map(); let disposed = false;
  function run(method, args, control) {
    if (disposed || !METHODS.has(method) || pending.size >= 16) return Promise.reject(fail('desktop_renderer_rpc_unavailable'));
    try { control?.assertCurrent(); } catch (error) { return Promise.reject(error); }
    const contents = getContents();
    if (!contents || contents.isDestroyed()) return Promise.reject(fail('desktop_renderer_unavailable'));
    const requestId = randomUUID();
    const wire = { requestId, method, args: args === undefined ? null : args, deadlineUnixMs: Date.now() + timeoutMs };
    try { if (Buffer.byteLength(JSON.stringify(wire)) > 16 * 1024 * 1024) throw fail('desktop_renderer_rpc_too_large'); }
    catch (error) { return Promise.reject(error); }
    return new Promise((resolve, reject) => {
      let timer;
      function finish(error, value, cancel = false) {
        if (!pending.delete(requestId)) return;
        clearTimeout(timer); control?.signal?.removeEventListener('abort', aborted);
        if (cancel && !contents.isDestroyed()) contents.send('desktop-runtime:facility-cancel', { requestId });
        if (error) reject(error); else {
          try { control?.assertCurrent(); resolve(value); } catch (failure) { reject(failure); }
        }
      }
      function aborted() { finish(control.signal.reason || fail('desktop_renderer_rpc_cancelled'), null, true); }
      pending.set(requestId, { finish });
      timer = setTimeout(() => finish(fail('desktop_renderer_rpc_timeout'), null, true), timeoutMs);
      control?.signal?.addEventListener('abort', aborted, { once: true });
      if (control?.signal?.aborted) { aborted(); return; }
      try { contents.send('desktop-runtime:facility-command', wire); } catch (error) { finish(error); }
    });
  }
  function reply(value) {
    if (!value || typeof value.requestId !== 'string' || typeof value.ok !== 'boolean') return false;
    const task = pending.get(value.requestId); if (!task) return false;
    if (value.ok) task.finish(null, value.result);
    else { const error = fail(typeof value.error?.code === 'string' ? value.error.code.slice(0,128) : 'desktop_renderer_operation_failed');
      error.message = typeof value.error?.message === 'string' ? value.error.message.slice(0,1024) : error.message; task.finish(error); }
    return true;
  }
  return { run, reply, dispose() { disposed = true; for (const entry of [...pending.values()]) entry.finish(fail('desktop_renderer_disposed'), null, true); },
    get pendingCount() { return pending.size; } };
}
module.exports = { createRuntimePeer };
