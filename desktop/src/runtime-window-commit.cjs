'use strict';
// The renderer must remain alive until cleanup and durable discard both finish.
async function commitRuntimeWindow({ request, control, finalizeDiscard, stop, replace, close, record = () => {} }) {
  control.assertCurrent();
  if (request.reason === 'reload') {
    if (finalizeDiscard) await finalizeDiscard();
    control.assertCurrent(); await replace(); return { status: 'reloaded' };
  }
  const cleanup = await stop(); control.assertCurrent(); record(cleanup);
  if (!cleanup.terminationConfirmed || !cleanup.stdioClosed || !cleanup.resourcesClosed) {
    throw Object.assign(new Error('Backend cleanup could not be fully verified. Diagnostics were retained.'), { code: 'desktop_cleanup_unverified' });
  }
  if (finalizeDiscard) await finalizeDiscard();
  control.assertCurrent(); await close(cleanup); return { status: 'closed' };
}
module.exports = { commitRuntimeWindow };
