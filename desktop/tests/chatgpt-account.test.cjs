'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { createChatGPTAccountLauncher } = require('../src/chatgpt-account.cjs');

test('account helper is hidden, credential-free and singly owned', () => {
  const calls = [], children = [];
  const old = process.env.INSPECTORPRO_CHATGPT_ACCESS_TOKEN;
  process.env.INSPECTORPRO_CHATGPT_ACCESS_TOKEN = 'must-not-inherit';
  try {
    const launcher = createChatGPTAccountLauncher({ python: 'pythonw.exe', root: 'C:/app',
      profileFile: 'C:/profile.json', spawnProcess(...args) {
        calls.push(args);
        const child = new EventEmitter();
        child.exitCode = null;
        child.kill = () => { child.killed = true; };
        children.push(child);
        return child;
      } });
    assert.equal(launcher.open(), true);
    assert.equal(launcher.open(), false);
    assert.equal(calls[0][2].windowsHide, true);
    assert.equal(calls[0][2].shell, false);
    assert.equal(calls[0][2].stdio, 'ignore');
    assert.equal(calls[0][2].env.INSPECTORPRO_CHATGPT_ACCESS_TOKEN, undefined);
    assert.ok(calls[0][1].includes('C:/profile.json'));
    launcher.close();
    assert.equal(children[0].killed, true);
    assert.equal(launcher.open(), true);
    children[0].emit('exit', 0);
    assert.equal(launcher.open(), false);
    launcher.close();
  } finally {
    if (old === undefined) delete process.env.INSPECTORPRO_CHATGPT_ACCESS_TOKEN;
    else process.env.INSPECTORPRO_CHATGPT_ACCESS_TOKEN = old;
  }
});
