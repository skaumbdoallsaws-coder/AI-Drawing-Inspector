'use strict';

const { parseApplicationUrl, validateApplicationOrigin } = require('./navigation-policy.cjs');

const CAPABILITY_ACTIONS = Object.freeze({
  microphone: new Set(['start-voice', 'start-recording']),
  'clipboard-read': new Set(['paste']),
  'clipboard-write': new Set(['copy', 'export']),
  'pointer-lock': new Set(['enter-walkthrough', 'enter-drone']),
});
const MAX_GRANT_LIFETIME_MS = 10000;

function capabilityFor(permission, phase, details) {
  if (permission === 'media') {
    // Media request and check callbacks use different Electron detail fields.
    if (phase === 'request') {
      return Array.isArray(details.mediaTypes) && details.mediaTypes.length === 1 &&
        details.mediaTypes[0] === 'audio' &&
        (details.mediaType === undefined || details.mediaType === 'audio') ? 'microphone' : null;
    }
    return details.mediaType === 'audio' &&
      (details.mediaTypes === undefined || (Array.isArray(details.mediaTypes) &&
        details.mediaTypes.length === 1 && details.mediaTypes[0] === 'audio')) ? 'microphone' : null;
  }
  return ({
    'clipboard-read': 'clipboard-read',
    'clipboard-sanitized-write': 'clipboard-write',
    pointerLock: 'pointer-lock',
  })[permission] || null;
}

/**
 * Both Electron permission handlers share this fail-closed policy. The spike
 * never supplies grants. Interactive grants are a future main-process contract:
 * they must come from verified user actions, be revoked on navigation/blur and
 * must never be copied directly from renderer permission details or IPC data.
 * These unit-tested predicates do not establish working voice or pointer lock.
 */
function createPermissionPolicy({
  mode = 'rendering-spike',
  applicationOrigin,
  applicationWebContentsId,
  getActionGrant = () => null,
  now = Date.now,
} = {}) {
  if (!['rendering-spike', 'interactive'].includes(mode)) throw new TypeError('Unknown permission policy mode');
  const origin = validateApplicationOrigin(applicationOrigin);
  if (!Number.isSafeInteger(applicationWebContentsId) || applicationWebContentsId < 1) {
    throw new TypeError('An explicit application WebContents identity is required');
  }
  if (typeof getActionGrant !== 'function' || typeof now !== 'function') throw new TypeError('Invalid permission policy callbacks');

  function evaluate({ webContents, permission, phase, requestingOrigin, details } = {}) {
    if (mode !== 'interactive') return false;
    try {
      if (!webContents || webContents.id !== applicationWebContentsId ||
          webContents.isDestroyed() || !webContents.isFocused() ||
          !details || details.isMainFrame !== true || !['request', 'check'].includes(phase)) return false;
      const frame = webContents.mainFrame;
      if (!frame || frame.isDestroyed?.() === true) return false;
      const top = parseApplicationUrl(webContents.getURL());
      const source = parseApplicationUrl(details.requestingUrl);
      const frameUrl = parseApplicationUrl(frame.url);
      if (top.origin !== origin || source.origin !== origin || frameUrl.url !== top.url || source.url !== top.url) return false;
      // Check callbacks require their separate origin argument. Requests derive
      // it from requestingUrl, then reject any conflicting optional identity.
      if (phase === 'check' && validateApplicationOrigin(requestingOrigin) !== origin) return false;
      for (const value of [details.securityOrigin, details.embeddingOrigin, details.requestingOrigin]) {
        if (value !== undefined && validateApplicationOrigin(value) !== origin) return false;
      }
      const capability = capabilityFor(permission, phase, details);
      if (!capability) return false;
      const grant = getActionGrant({ capability, webContents, frame, url: top.url });
      const timestamp = now();
      return Boolean(grant && grant.capability === capability && grant.webContentsId === applicationWebContentsId &&
        grant.frame === frame && grant.documentUrl === top.url && grant.origin === origin &&
        grant.userInitiated === true && grant.consented === true && grant.revoked !== true &&
        CAPABILITY_ACTIONS[capability].has(grant.action) &&
        Number.isFinite(timestamp) && Number.isFinite(grant.issuedAt) && Number.isFinite(grant.expiresAt) &&
        grant.issuedAt <= timestamp && grant.expiresAt > timestamp &&
        grant.expiresAt > grant.issuedAt && grant.expiresAt - grant.issuedAt <= MAX_GRANT_LIFETIME_MS);
    } catch {
      // Destroyed frames, ambiguous identity and grant-store failures deny.
      return false;
    }
  }

  return Object.freeze({
    evaluate,
    requestHandler(webContents, permission, callback, details) {
      callback(evaluate({ webContents, permission, phase: 'request', details }));
    },
    checkHandler(webContents, permission, requestingOrigin, details) {
      return evaluate({ webContents, permission, phase: 'check', requestingOrigin, details });
    },
    deviceHandler() { return false; },
    displayMediaHandler(_request, callback) { callback({}); },
  });
}

module.exports = { createPermissionPolicy };
