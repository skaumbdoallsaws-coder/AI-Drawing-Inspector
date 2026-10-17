'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { parseRuntimeOptions } = require('../src/runtime-settings.cjs');
test('Codex acceptance is explicit and mutually exclusive with other acceptance modes', () => {
  const out = path.resolve('test-output');
  const args = ['--profile-file', path.resolve('profile.json'), '--python', path.resolve('python.exe')];
  assert.equal(parseRuntimeOptions(args).codexAcceptanceOutput, undefined);
  assert.equal(parseRuntimeOptions([...args, '--codex-acceptance-output', out]).codexAcceptanceOutput, out);
  for (const flag of ['--acceptance-output', '--startup-diagnostics-output', '--research-acceptance-output',
    '--workflow-acceptance-output', '--browser-acceptance-output', '--generation-acceptance-output']) {
    assert.throws(() => parseRuntimeOptions([...args, '--codex-acceptance-output', out, flag, out]));
  }
});
