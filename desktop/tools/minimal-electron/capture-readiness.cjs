'use strict';

function codedError(code, message) {
  return Object.assign(new Error(message), { code });
}

function timeoutValue(value = 10000) {
  if (!Number.isSafeInteger(value) || value < 1 || value > 60000) {
    throw new TypeError('timeoutMs must be an integer between 1 and 60000');
  }
  return value;
}

/**
 * Attach before loadFile/loadURL. did-finish-load and a successful DOM query do
 * not establish this condition: only ready-to-show records first-paint evidence.
 * No Promise or timer exists until wait(), so a startup failure/closed window
 * before wait cannot cause an eager unhandled rejection. Repeated wait calls
 * share the first wait and its deadline. dispose() is idempotent.
 */
function createFirstPaintGate(window) {
  if (!window || !['on', 'removeListener', 'isDestroyed'].every(name => typeof window[name] === 'function')) {
    throw new TypeError('A BrowserWindow-compatible event source is required');
  }
  let observed = false;
  let failure = null;
  let waiting = null;
  let resolveWait;
  let rejectWait;
  let timer;
  let settled = false;

  function detach() {
    clearTimeout(timer);
    timer = undefined;
    window.removeListener('ready-to-show', onReady);
    window.removeListener('closed', onClosed);
  }
  function rejectWith(error) {
    if (settled) return;
    failure = failure || error;
    detach();
    if (waiting) {
      settled = true;
      rejectWait(failure);
    }
  }
  function complete() {
    if (!waiting || settled || failure || !observed) return;
    if (window.isDestroyed()) return onClosed();
    settled = true;
    detach();
    resolveWait({ event: 'ready-to-show', observed: true });
  }
  function onReady() {
    if (failure || settled) return;
    if (window.isDestroyed()) return onClosed();
    observed = true;
    // Retain the closed listener until wait consumes the latched observation.
    window.removeListener('ready-to-show', onReady);
    complete();
  }
  function onClosed() {
    rejectWith(codedError('first_paint_window_closed', 'Window closed before first-paint wait completed'));
  }
  window.on('ready-to-show', onReady);
  window.on('closed', onClosed);
  if (window.isDestroyed()) onClosed();

  function wait({ timeoutMs = 10000 } = {}) {
    const duration = timeoutValue(timeoutMs);
    if (waiting) return waiting;
    if (!failure && window.isDestroyed()) onClosed();
    // Assign waiting before settling; Promise executors run synchronously.
    waiting = new Promise((resolve, reject) => { resolveWait = resolve; rejectWait = reject; });
    if (failure) rejectWith(failure);
    else if (observed) complete();
    else timer = setTimeout(() => rejectWith(codedError('first_paint_timeout',
      'Window did not emit ready-to-show before the first-paint deadline')), duration);
    return waiting;
  }

  function dispose() {
    if (settled) { detach(); return; }
    rejectWith(codedError('first_paint_disposed', 'First-paint gate was disposed'));
  }
  return Object.freeze({ wait, dispose });
}

/**
 * Invoke once, settle once, and observe a late rejection without retrying or
 * running a follow-up stage. This cannot stop arbitrary callback code. Callback
 * continuations that have their own side effects must propagate signal and call
 * assertCurrent immediately before those effects after each await.
 */
function withDeadline(callback, { timeoutMs = 10000, code = 'capture_stage_timeout' } = {}) {
  if (typeof callback !== 'function') throw new TypeError('A callback is required');
  const duration = timeoutValue(timeoutMs);
  if (typeof code !== 'string' || !code || code.length > 128) throw new TypeError('A bounded diagnostic error code is required');
  const controller = new AbortController();
  let active = true;
  const control = Object.freeze({ signal: controller.signal,
    isCurrent: () => active && !controller.signal.aborted,
    assertCurrent() {
      if (!active || controller.signal.aborted) throw controller.signal.reason
        || codedError('capture_stage_settled', 'Capture stage authority expired');
    } });
  return new Promise((resolve, reject) => {
    function settle(outcome, value) {
      if (!active) return;
      active = false;
      clearTimeout(timer);
      controller.abort(outcome === 'fulfilled' ? codedError('capture_stage_settled', 'Capture stage completed')
        : value || codedError('capture_stage_failed', 'Capture stage failed'));
      if (outcome === 'rejected') reject(value); else resolve(value);
    }
    const timer = setTimeout(() => settle('rejected', codedError(code, 'Capture stage exceeded its deadline')), duration);
    Promise.resolve().then(() => {
      control.assertCurrent();
      return callback(control);
    }).then(value => settle('fulfilled', value), error => settle('rejected', error));
  });
}

module.exports = { createFirstPaintGate, withDeadline };
