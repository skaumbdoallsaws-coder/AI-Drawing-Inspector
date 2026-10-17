'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { withDeadline } = require('../tools/application-codex-check.cjs');

test('native driver returns renderer results and preserves failures', async () => {
  assert.equal(await withDeadline(Promise.resolve(42), 'Renderer'), 42);
  const original = new Error('Renderer closed');
  await assert.rejects(withDeadline(Promise.reject(original), 'Renderer'), error => error === original);
});

test('native driver bounds a renderer that never finishes', async () => {
  await assert.rejects(withDeadline(new Promise(() => {}), 'Desktop renderer', 10), /Desktop renderer did not respond/);
});

test('a late screenshot rejection remains handled after the deadline', async () => {
  let reject;
  const capture = new Promise((_resolve, failed) => { reject = failed; });
  await assert.rejects(withDeadline(capture, 'Desktop screenshot', 10), /Desktop screenshot did not respond/);
  reject(new Error('Window closed after timeout'));
  await new Promise(resolve => setImmediate(resolve));
});
