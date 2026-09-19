'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

/**
 * Run one directly owned process. This does not discover or terminate unrelated
 * processes, and does not claim ownership of an arbitrary descendant tree.
 * Execution failures resolve as evidence; invalid config or an unavailable log
 * throws before a process is started. A confirmed exit is distinct from drained
 * stdio, because descendants can retain inherited pipe handles after an exit.
 */
async function runOwnedChild({ executable, args = [], cwd, env = process.env, logPath,
  timeoutMs = 60000, terminationGraceMs = 2000, forceKillGraceMs = 2000,
  drainGraceMs = 2000, maxLogBytes = 8 * 1024 * 1024, spawnImpl = spawn } = {}) {
  if (typeof executable !== 'string' || !executable || !Array.isArray(args) ||
      args.some(value => typeof value !== 'string') || typeof logPath !== 'string' || !logPath ||
      typeof spawnImpl !== 'function') throw new TypeError('Executable, string arguments and logPath are required');
  for (const [name, value] of Object.entries({ timeoutMs, terminationGraceMs, forceKillGraceMs, drainGraceMs })) {
    if (!Number.isSafeInteger(value) || value < 1 || value > 600000) throw new TypeError(`${name} must be between 1 and 600000`);
  }
  if (!Number.isSafeInteger(maxLogBytes) || maxLogBytes < 1024 || maxLogBytes > 64 * 1024 * 1024) {
    throw new TypeError('maxLogBytes must be between 1024 and 67108864');
  }
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  const fd = fs.openSync(logPath, 'a');

  return new Promise(resolve => {
    let child; let settled = false; let code = null; let signal = null;
    let exited = false; let closed = false; let spawnFailed = false; let timedOut = false;
    let cleanupStarted = false; let processError = null; let logError = null;
    let workTimer; let terminationTimer; let forceTimer; let drainTimer;
    let tail = Buffer.alloc(0); let writtenOutput = 0; let outputTruncated = false;
    const pid = () => Number.isSafeInteger(child?.pid) && child.pid > 0 ? child.pid : null;
    const clearTimers = () => [workTimer, terminationTimer, forceTimer, drainTimer].forEach(clearTimeout);

    function write(bytes) {
      if (logError) return;
      try {
        const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
        for (let offset = 0; offset < buffer.length;) {
          const count = fs.writeSync(fd, buffer, offset, buffer.length - offset);
          if (count === 0) throw new Error('Diagnostic write made no progress');
          offset += count;
        }
      }
      catch (error) { logError = `Cannot persist child diagnostics: ${error.message}`; }
    }
    function marker(message) { write(`\n[owned-child ${new Date().toISOString()}] ${message}\n`); }
    function output(bytes) {
      if (settled) return;
      const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
      tail = Buffer.concat([tail, buffer]).subarray(-12000);
      const available = maxLogBytes - writtenOutput;
      if (available > 0) { const retained = buffer.subarray(0, available); write(retained); writtenOutput += retained.length; }
      if (buffer.length > available && !outputTruncated) {
        outputTruncated = true; marker(`Output exceeds ${maxLogBytes} bytes; retaining its final tail in the result`);
      }
      if (logError) beginCleanup();
    }
    function finish(fallback) {
      if (settled) return;
      settled = true;
      clearTimers();
      const terminationConfirmed = exited || closed || spawnFailed;
      let status = fallback || (logError ? 'log-error' : processError ? (spawnFailed ? 'spawn-error' : 'process-error')
        : timedOut ? 'timed-out' : 'exited');
      const error = fallback === 'termination-unconfirmed' ? 'Owned child termination could not be confirmed after SIGTERM and SIGKILL'
        : fallback === 'stdio-unconfirmed' ? 'Owned child exited, but stdio did not close before the drain deadline'
          : logError || processError || (timedOut ? 'Owned child exceeded its execution deadline' : null);
      if (outputTruncated) { marker('Final diagnostic tail'); write(tail); }
      marker(`Finished status=${status} code=${code} signal=${signal} pid=${pid()} terminationConfirmed=${terminationConfirmed} stdioClosed=${closed}`);
      try { fs.fsyncSync(fd); } catch (failure) { logError ||= `Cannot flush child diagnostics: ${failure.message}`; }
      try { fs.closeSync(fd); } catch (failure) { logError ||= `Cannot close child diagnostics: ${failure.message}`; }
      if (logError && !fallback) status = 'log-error';
      // Only after the bounded drain/termination failure is recorded, detach our
      // handles so an uncooperative process cannot keep the harness alive. This
      // is reported as failure, never as a successfully stopped child.
      if (!closed) {
        child?.stdout?.destroy(); child?.stderr?.destroy(); child?.unref?.();
      }
      resolve(Object.freeze({ ok: status === 'exited' && code === 0 && signal === null,
        status, code, signal, pid: pid(), terminationConfirmed, stdioClosed: closed,
        logPath, diagnostics: tail.toString('utf8'), timedOut, outputTruncated,
        ...(logError || error ? { error: logError || error } : {}) }));
    }
    function awaitDrain() {
      clearTimeout(workTimer); clearTimeout(terminationTimer); clearTimeout(forceTimer);
      if (!drainTimer) drainTimer = setTimeout(() => finish('stdio-unconfirmed'), drainGraceMs);
    }
    function signalOwned(value) {
      if (settled || exited || closed) return;
      try { marker(`Sending ${value} to owned pid=${pid()}; accepted=${child.kill(value)}`); }
      catch (error) { marker(`${value} failed for owned pid=${pid()}: ${error.message}`); }
    }
    function beginCleanup() {
      if (settled || cleanupStarted) return;
      cleanupStarted = true; clearTimeout(workTimer);
      if (exited || closed || spawnFailed) { awaitDrain(); return; }
      marker('Waiting for owned child cleanup');
      signalOwned('SIGTERM');
      terminationTimer = setTimeout(() => {
        if (settled || exited || closed) return;
        signalOwned('SIGKILL');
        forceTimer = setTimeout(() => {
          if (!settled && !exited && !closed) finish('termination-unconfirmed');
        }, forceKillGraceMs);
      }, terminationGraceMs);
    }

    marker('Starting owned process');
    if (logError) { spawnFailed = true; finish(); return; }
    try {
      child = spawnImpl(executable, args, { cwd, env, windowsHide: true, shell: false,
        stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (error) {
      spawnFailed = true; processError = `Spawn threw: ${error.message}`;
      // No child or streams were created, so there is nothing left to drain.
      closed = true; marker(processError); finish(); return;
    }
    marker(`Spawn returned owned pid=${pid()}`);
    for (const [name, stream] of [['stdout', child.stdout], ['stderr', child.stderr]]) {
      stream?.on('data', output);
      stream?.on('error', error => {
        if (settled) return;
        processError ||= `${name} read failed: ${error.message}`;
        marker(processError); beginCleanup();
      });
    }
    child.on('error', error => {
      if (settled) return;
      processError ||= `Child process error: ${error.message}`;
      spawnFailed = pid() === null;
      marker(processError);
      if (spawnFailed) awaitDrain(); else beginCleanup();
    });
    child.on('exit', (exitCode, exitSignal) => {
      if (settled) return;
      exited = true; code = exitCode; signal = exitSignal;
      marker(`Exit received code=${code} signal=${signal}; awaiting stdio close`);
      awaitDrain();
    });
    child.on('close', (exitCode, exitSignal) => {
      if (settled) return;
      closed = true; code = exitCode; signal = exitSignal;
      finish();
    });
    workTimer = setTimeout(() => { timedOut = true; marker(`Execution exceeded ${timeoutMs}ms`); beginCleanup(); }, timeoutMs);
    if (logError) beginCleanup();
  });
}

module.exports = { runOwnedChild };
