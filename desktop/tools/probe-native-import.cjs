'use strict';
const { spawn } = require('node:child_process');
async function sample(mode) {
  return new Promise(resolve => {
    const code = `import sys,threading,time,json,os\nt=time.perf_counter()\ndef read():\n while True:\n  try:\n   os.read(0,4096)\n   return\n  except BlockingIOError: time.sleep(0.025)\n${mode === 'nonblocking' ? 'os.set_blocking(0,False)\n' : ''}thread=threading.Thread(target=${mode === 'nonblocking' ? 'read' : 'lambda:sys.stdin.buffer.readline()'})\n${mode !== 'deferred' ? 'thread.start()\n' : ''}import numpy\nprint(json.dumps({'mode':'${mode}','seconds':time.perf_counter()-t}),flush=True)\n${mode === 'deferred' ? 'thread.start()\n' : ''}thread.join(3)\n`;
    const child = spawn('C:\\Python314\\python.exe', ['-u', '-c', code], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '', errors = '', timedOut = false;
    const timer = setTimeout(() => { timedOut = true; child.kill(); }, 8000);
    child.stdin.on('error', () => {});
    child.stdout.on('data', value => { output += value; if (!child.stdin.writableEnded) child.stdin.end('\n'); });
    child.stderr.on('data', value => { errors += value; });
    child.on('close', exit => { clearTimeout(timer); resolve({ mode, timedOut, exit, output, errors: errors.slice(0, 2000) }); });
  });
}
(async () => { for (const mode of ['blocking', 'deferred', 'nonblocking', 'nonblocking']) console.log(JSON.stringify(await sample(mode))); })();
