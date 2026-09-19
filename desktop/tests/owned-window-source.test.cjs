'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { ownedWindowSource } = require('../tools/owned-window-source.cjs');
const window = { isDestroyed: () => false, getSize: () => [1400,800], getMediaSourceId: () => 'window:42:1' };
const source = (id, empty = false) => ({ id, thumbnail: { isEmpty: () => empty } });

test('capture waits for its own newly shown window, not other windows', async () => {
  const own = source('window:42:0'); let calls = 0, waits = 0;
  const result = await ownedWindowSource({ window, desktopCapturer: { async getSources(options) {
    assert.deepEqual(options.types,['window']); return ++calls === 1 ? [source('window:7:1')] : [own];
  } }, wait: async () => { waits++; } });
  assert.equal(result.image,own.thumbnail); assert.equal(calls,2); assert.equal(waits,1);
});

test('missing and empty owned sources refuse within the attempt budget', async () => {
  let calls = 0;
  await assert.rejects(ownedWindowSource({ window, attempts: 3, desktopCapturer: { async getSources() {
    calls++; return [source('window:7:1'),source('window:42:1',true)];
  } }, wait: async () => {} }), error => error.observations.length === 3);
  assert.equal(calls,3);
});

test('capture refuses a destroyed owner and preserves enumeration failure', async () => {
  await assert.rejects(ownedWindowSource({ window:{...window,isDestroyed:()=>true} }),/destroyed/);
  await assert.rejects(ownedWindowSource({ window, desktopCapturer:{getSources:async()=>{throw new Error('enumeration failed');}} }),/enumeration failed/);
});
