'use strict';

function failure(code, message) { return Object.assign(new Error(message), { code }); }

/**
 * The inert rendering diagnostic must observe actual window closure as well as
 * the lifecycle decision. Electron window.close() only requests a close; page
 * beforeunload processing can finish after the commit callback returns.
 * This helper does not quit, destroy, retry, or authorize another close. A
 * timeout cannot revoke a close already dispatched by requestClose().
 */
async function closeRenderingPreview({ window, requestClose, timeoutMs = 10000 } = {}) {
  if (!window || !['on', 'removeListener', 'isDestroyed'].every(name => typeof window[name] === 'function')) {
    throw new TypeError('A BrowserWindow-compatible window is required');
  }
  if (typeof requestClose !== 'function') throw new TypeError('A lifecycle close callback is required');
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000) {
    throw new TypeError('timeoutMs must be between 1 and 60000');
  }
  if (window.isDestroyed()) throw failure('lifecycle_close_already_destroyed', 'Preview was already destroyed before its close was requested');

  return new Promise((resolve, reject) => {
    let active = true, closed = false, committed = false, decision, timer;
    function settle(outcome, error) {
      if (!active) return;
      active = false;
      clearTimeout(timer);
      window.removeListener('closed', onClosed);
      if (outcome === 'rejected') reject(error); else resolve(decision);
    }
    function complete() {
      if (!active || !closed || !committed) return;
      try {
        if (!window.isDestroyed()) throw failure('lifecycle_close_not_destroyed', 'Preview emitted closed without confirmed destruction');
        settle('fulfilled');
      } catch (error) { settle('rejected', error); }
    }
    function onClosed() { closed = true; complete(); }

    // Attach before invoking requestClose, which can emit closed synchronously.
    window.on('closed', onClosed);
    timer = setTimeout(() => settle('rejected', failure('lifecycle_close_timeout',
      'Preview lifecycle decision and closed event were not both confirmed before the deadline')), timeoutMs);
    Promise.resolve().then(() => {
      if (!active) return;
      if (window.isDestroyed()) throw failure('lifecycle_close_already_destroyed', 'Preview was destroyed before lifecycle close dispatch');
      return requestClose();
    }).then(result => {
      if (!active) return;
      if (result?.status !== 'committed') {
        settle('rejected', failure('lifecycle_close_not_committed', 'Preview lifecycle close did not commit'));
        return;
      }
      decision = result;
      committed = true;
      complete();
    }).catch(error => settle('rejected', error));
  });
}

module.exports = { closeRenderingPreview };
