'use strict';
function validateObservation(value) {
  if (!value || value.schemaVersion !== 1 || typeof value.dirty !== 'boolean'
      || typeof value.busy !== 'boolean' || typeof value.pending !== 'boolean'
      || typeof value.fingerprint !== 'string' || value.fingerprint.length > 65536
      || !Array.isArray(value.affected) || value.affected.length > 12
      || value.affected.some(v => typeof v !== 'string' || !/^[a-zA-Z]{1,32}$/.test(v))) {
    throw Object.assign(new Error('The application has not provided its current workflow state.'), { code: 'desktop_workflow_state_unavailable' });
  }
  return { schemaVersion: 1, dirty: value.dirty, busy: value.busy, pending: value.pending,
    fingerprint: value.fingerprint, affected: value.affected.slice() };
}
// Expire each await separately so a late reply cannot resume its caller.
async function transitionStep(label, action, timeoutMs = 10000, onTimeout = () => {}) {
  const controller = new AbortController();
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(() => action(controller.signal)),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          const error = Object.assign(new Error(label + ' timed out. The window was kept open; retry Close when ready.'),
            { code: 'desktop_transition_timeout' });
          reject(error);
          controller.abort(error);
          try { onTimeout(); } catch (_) { /* The deadline still releases the caller. */ }
        }, timeoutMs);
      }),
    ]);
  } finally { clearTimeout(timer); }
}
async function authorizeTransition({ kind, observe, confirmDiscard, step = transitionStep }) {
  const initial = validateObservation(await step('Workflow observation', observe, 5000));
  if (initial.busy || initial.pending) return { allowed: false, reason: 'Finish or cancel the active operation before ' + kind + '.' };
  // Restart preserves the live renderer; close and reload destroy its draft.
  if (kind !== 'restart' && initial.dirty && !await step('Unsaved work confirmation', signal => confirmDiscard(initial, signal), 60000)) return { allowed: false, cancelled: true };
  const current = validateObservation(await step('Workflow observation', observe, 5000));
  if (current.busy || current.pending || current.fingerprint !== initial.fingerprint) {
    return { allowed: false, reason: 'The workflow changed. Review it before trying again.' };
  }
  return { allowed: true, observation: current };
}
module.exports = { validateObservation, authorizeTransition, transitionStep };
