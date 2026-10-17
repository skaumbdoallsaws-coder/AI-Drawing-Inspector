'use strict';
const path = require('node:path');
const { spawn } = require('node:child_process');

function createChatGPTAccountLauncher({ python, root, profileFile, onError = () => {}, spawnProcess = spawn }) {
  let child = null;
  return {
    open() {
      if (child && child.exitCode === null && !child.killed) return false;
      child = spawnProcess(python, ['-B', path.join(root, 'tools', 'connect_chatgpt_account.py'),
        '--profile', profileFile, '--open-browser'], {
        cwd: root, shell: false, windowsHide: true, stdio: 'ignore',
        // The account helper loads only its explicit profile, never inherited API keys.
        env: Object.fromEntries(Object.entries(process.env).filter(([key]) =>
          !/^(INSPECTORPRO_CODEX_|CODEX_|OPENAI_|ANTHROPIC_|ACCESS_TOKEN$|INSPECTORPRO_CHATGPT_)/i.test(key))),
      });
      const owned = child;
      child.on('error', () => { if (child === owned) child = null; onError(); });
      child.on('exit', code => { if (child === owned) child = null; if (code && !owned.killed) onError(); });
      return true;
    },
    close() {
      if (child && child.exitCode === null && !child.killed) child.kill();
      child = null;
    },
  };
}
module.exports = { createChatGPTAccountLauncher };
