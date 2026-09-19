'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createPermissionPolicy } = require('../src/permission-policy.cjs');

const ORIGIN = 'http://127.0.0.1:8187';
const URL = `${ORIGIN}/?facilityLayoutId=pilot`;

function fixture(options = {}) {
  const frame = { url: URL, isDestroyed: () => false };
  const webContents = { id: 7, mainFrame: frame, getURL: () => URL, isDestroyed: () => false, isFocused: () => true };
  const grant = { capability: 'microphone', action: 'start-voice', origin: ORIGIN,
    webContentsId: 7, frame, documentUrl: URL, userInitiated: true, consented: true,
    issuedAt: 1000, expiresAt: 6000 };
  const policy = createPermissionPolicy({ mode: 'interactive', applicationOrigin: ORIGIN,
    applicationWebContentsId: 7, getActionGrant: () => grant, now: () => 2000, ...options });
  const details = { isMainFrame: true, requestingUrl: URL, mediaTypes: ['audio'] };
  const context = { webContents, permission: 'media', phase: 'request', details };
  return { policy, webContents, grant, details, context };
}

test('rendering spike denies every permission even if a grant is supplied', () => {
  const f = fixture({ mode: 'rendering-spike' });
  for (const permission of ['media', 'pointerLock', 'clipboard-read', 'clipboard-sanitized-write', 'fullscreen', 'unknown']) {
    assert.equal(f.policy.evaluate({ ...f.context, permission }), false, permission);
    assert.equal(f.policy.checkHandler(f.webContents, permission, ORIGIN, f.details), false, permission);
  }
});

test('application identity and a known mode are mandatory at construction', () => {
  for (const options of [{}, { applicationOrigin: ORIGIN }, { applicationOrigin: ORIGIN, applicationWebContentsId: -1 },
    { applicationOrigin: 'https://example.com', applicationWebContentsId: 7 },
    { applicationOrigin: ORIGIN, applicationWebContentsId: 7, mode: 'research' }]) {
    assert.throws(() => createPermissionPolicy(options), TypeError);
  }
});

test('request and check share audio-only grant policy with their different media fields', () => {
  const f = fixture();
  const results = [];
  f.policy.requestHandler(f.webContents, 'media', result => results.push(result), f.details);
  assert.deepEqual(results, [true]);
  const checks = { isMainFrame: true, requestingUrl: URL, securityOrigin: ORIGIN, mediaType: 'audio' };
  assert.equal(f.policy.checkHandler(f.webContents, 'media', ORIGIN, checks), true);
  for (const details of [
    { ...f.details, mediaTypes: undefined }, { ...f.details, mediaTypes: [] },
    { ...f.details, mediaTypes: ['video'] }, { ...f.details, mediaTypes: ['audio', 'video'] },
    { ...f.details, mediaType: 'video' },
  ]) assert.equal(f.policy.evaluate({ ...f.context, details }), false);
  for (const mediaType of [undefined, 'video', 'unknown']) {
    assert.equal(f.policy.checkHandler(f.webContents, 'media', ORIGIN, { ...checks, mediaType }), false);
  }
  assert.equal(f.policy.checkHandler(f.webContents, 'media', ORIGIN, { ...checks, mediaTypes: ['video'] }), false);
});

test('wrong senders, subframes, workers, absent identity and background requests deny', () => {
  for (const mutate of [
    f => { f.context.webContents = null; },
    f => { f.webContents.id = 8; },
    f => { f.webContents.isFocused = () => false; },
    f => { f.webContents.isDestroyed = () => true; },
    f => { f.webContents.mainFrame = null; },
    f => { f.details.isMainFrame = false; },
    f => { delete f.details.isMainFrame; },
    f => { delete f.details.requestingUrl; },
    f => { f.details.requestingUrl = 'http://localhost:8187/'; },
    f => { f.details.requestingUrl = `${ORIGIN}/other`; },
    f => { f.details.securityOrigin = 'https://example.com'; },
    f => { f.details.embeddingOrigin = 'null'; },
    f => { f.details.requestingOrigin = `${ORIGIN}/path`; },
    f => { f.webContents.getURL = () => 'https://example.com'; },
    f => { f.webContents.mainFrame.url = `${ORIGIN}/other`; },
  ]) {
    const f = fixture(); mutate(f);
    assert.equal(f.policy.evaluate(f.context), false, mutate.toString());
  }
  const f = fixture();
  assert.equal(f.policy.checkHandler(f.webContents, 'media', undefined, { ...f.details, mediaType: 'audio' }), false);
  assert.equal(f.policy.checkHandler(f.webContents, 'media', 'https://example.com', { ...f.details, mediaType: 'audio' }), false);
});

test('grants require explicit consent, correct user action, document binding and short lifetime', () => {
  for (const change of [
    { capability: 'clipboard-read' }, { action: 'background' }, { origin: 'https://example.com' },
    { webContentsId: 8 }, { frame: {} }, { documentUrl: `${ORIGIN}/other` },
    { userInitiated: false }, { consented: false }, { revoked: true },
    { issuedAt: 3000 }, { expiresAt: 2000 }, { expiresAt: 999999 },
    { issuedAt: NaN }, { expiresAt: Infinity },
  ]) {
    const f = fixture(); Object.assign(f.grant, change);
    assert.equal(f.policy.evaluate(f.context), false, JSON.stringify(change));
  }
  assert.equal(fixture({ getActionGrant: () => null }).policy.evaluate(fixture().context), false);
  const f = fixture({ getActionGrant: () => { throw new Error('store unavailable'); } });
  assert.equal(f.policy.evaluate(f.context), false);
});

test('clipboard and viewport capabilities require their declared actions', () => {
  for (const [permission, capability, action] of [
    ['clipboard-read', 'clipboard-read', 'paste'],
    ['clipboard-sanitized-write', 'clipboard-write', 'copy'],
    ['pointerLock', 'pointer-lock', 'enter-walkthrough'],
  ]) {
    const f = fixture(); Object.assign(f.grant, { capability, action });
    assert.equal(f.policy.evaluate({ ...f.context, permission }), true, permission);
    f.grant.action = 'start-voice';
    assert.equal(f.policy.evaluate({ ...f.context, permission }), false, permission);
  }
});

test('all other capabilities and supplemental device/display callbacks deny', () => {
  const f = fixture();
  for (const permission of ['fullscreen', 'display-capture', 'openExternal', 'notifications', 'usb', 'hid', 'serial',
    'geolocation', 'fileSystem', 'clipboard-write', 'microphone', 'unknown', 'future-permission', '__proto__']) {
    assert.equal(f.policy.evaluate({ ...f.context, permission }), false, permission);
  }
  assert.equal(f.policy.deviceHandler({ deviceType: 'usb', origin: ORIGIN }), false);
  let streams;
  f.policy.displayMediaHandler({}, value => { streams = value; });
  assert.deepEqual(streams, {});
});
