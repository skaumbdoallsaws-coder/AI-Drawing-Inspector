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
async function authorizeTransition({ kind, observe, confirmDiscard }) {
  const initial = validateObservation(await observe());
  if (initial.busy || initial.pending) return { allowed: false, reason: 'Finish or cancel the active operation before ' + kind + '.' };
  // Restart preserves the live renderer; close and reload destroy its draft.
  if (kind !== 'restart' && initial.dirty && !await confirmDiscard(initial)) return { allowed: false, cancelled: true };
  const current = validateObservation(await observe());
  if (current.busy || current.pending || current.fingerprint !== initial.fingerprint) {
    return { allowed: false, reason: 'The workflow changed. Review it before trying again.' };
  }
  return { allowed: true, observation: current };
}
module.exports = { validateObservation, authorizeTransition };
