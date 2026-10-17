'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { randomBytes, randomUUID } = require('node:crypto');
const { isDeepStrictEqual } = require('node:util');
const { performance } = require('node:perf_hooks');
const { validateRuntime } = require('./runtime-settings.cjs');
const failure = (code, message = code) => Object.assign(new Error(message), { code });
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
function childEnvironment(profile, python, source = process.env) {
  if (profile.mode === 'application') {
    const result = { ...require('./codex-config.cjs').isolateCodexEnvironment(source), PYTHONUNBUFFERED: '1', PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8' };
    for (const key of Object.keys(result)) if (/^(ELECTRON_|NODE_OPTIONS$|PYTHON_DOTENV_DISABLED$)/i.test(key)) delete result[key];
    if (profile.modelGateway) {
      // The selected native profile, not inherited shell settings, owns this binding.
      const inheritedPath = Object.keys(result).find(key => key.toUpperCase() === 'PYTHONPATH');
      const searchPath = inheritedPath ? result[inheritedPath] : '';
      for (const key of Object.keys(result)) if (/^(INSPECTORPRO_LLM_GATEWAY_CONFIG|PYTHONPATH)$/i.test(key)) delete result[key];
      result.INSPECTORPRO_LLM_GATEWAY_CONFIG = profile.modelGateway.configPath;
      result.PYTHONPATH = [profile.modelGateway.dependencyRoot, searchPath].filter(Boolean).join(path.delimiter);
    }
    return result;
  }
  const result = {};
  for (const key of ['SystemRoot','WINDIR','COMSPEC','PATHEXT','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMDATA','TEMP','TMP','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE']) {
    const actual = Object.keys(source).find(name => name.toLowerCase() === key.toLowerCase());
    if (actual && source[actual]) result[key] = source[actual];
  }
  result.PATH = [path.dirname(python), path.join(result.SystemRoot || result.WINDIR || 'C:\\Windows', 'System32')].join(path.delimiter);
  Object.assign(result, { PYTHONUNBUFFERED: '1', PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8', PYTHON_DOTENV_DISABLED: '1' });
  return result;
}
async function readJson(response, limit = 16 * 1024 * 1024) {
  if (!response?.body?.getReader) throw failure('desktop_response_invalid');
  const reader = response.body.getReader(), chunks = []; let bytes = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      bytes += value.length; if (bytes > limit) throw failure('desktop_response_too_large');
      chunks.push(value);
    }
  } finally { await reader.cancel().catch(() => {}); }
  const result = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if (!response.ok) {
    const error = failure(result?.error?.code || 'desktop_backend_request_failed', result?.error?.message || 'The protected backend rejected the request');
    error.status = response.status; throw error;
  }
  return result;
}
function createManagedRuntime({ profile, python, appRoot, logRoot = path.join(profile.dataRoot, 'desktop-logs'),
  startupTimeoutMs = 45000, stopTimeoutMs = 15000, forceTimeoutMs = 5000,
  startupDiagnostics = false, fetchImpl = fetch, spawnImpl = spawn, onState = () => {} } = {}) {
  for (const value of [startupTimeoutMs, stopTimeoutMs, forceTimeoutMs]) if (!Number.isSafeInteger(value) || value < 1 || value > 120000) throw failure('desktop_deadline_invalid');
  if (typeof startupDiagnostics !== 'boolean') throw failure('desktop_diagnostics_option_invalid');
  if (!path.isAbsolute(python) || !path.isAbsolute(appRoot)) throw failure('desktop_executable_path_invalid');
  fs.mkdirSync(logRoot, { recursive: true });
  let state = 'idle', owned = null, starting = null, stopping = null, restarting = null, stableBinding = null;
  const history = [];
  const elapsed = item => Math.max(0, Math.round(performance.now() - item.startedMonotonic));
  function diagnosticCheckpoint(item, line) {
    const summary = item.startupCheckpoints;
    let value;
    try {
      value = JSON.parse(line);
      if (!value || value.schemaVersion !== 1 || !/^[a-z][a-z0-9-]{0,79}$/.test(value.phase)
          || value.phase.includes(item.credential)
          || !Number.isSafeInteger(value.processId) || value.processId < 1 || typeof value.instanceId !== 'string'
          || (value.sequence !== undefined && (!Number.isSafeInteger(value.sequence) || value.sequence < 1))
          || (value.previousPhase != null && (!/^[a-z][a-z0-9-]{0,79}$/.test(value.previousPhase) || value.previousPhase.includes(item.credential)))
          || ['elapsedMs', 'previousPhaseDurationMs'].some(key => value[key] != null
            && (typeof value[key] !== 'number' || !Number.isFinite(value[key]) || value[key] < 0 || value[key] > 3600000))) throw new Error();
    } catch (_) { summary.invalidCount++; return; }
    if (value.processId !== item.child?.pid || value.instanceId !== item.instanceId) { summary.foreignCount++; return; }
    // Only fixed diagnostic metadata is projected. Extra keys, paths, stack
    // content, and arbitrary error text cannot enter the control evidence.
    const record = { phase: value.phase, processId: value.processId, instanceId: value.instanceId,
      sequence: value.sequence ?? null, elapsedMs: value.elapsedMs ?? null,
      previousPhase: value.previousPhase ?? null, previousPhaseDurationMs: value.previousPhaseDurationMs ?? null,
      observedElapsedMs: elapsed(item) };
    summary.records.push(record);
    if (summary.records.length > 64) { summary.records.shift(); summary.truncatedCount++; }
    summary.lastPhase = record.phase;
  }
  function diagnosticError(item, line) {
    let value;
    try {
      value = JSON.parse(line);
      if (!value || value.schemaVersion !== 1 || !Number.isSafeInteger(value.processId) || value.processId < 1
          || !['start', 'bind', 'capture-shutdown', 'stop'].includes(value.operation)
          || typeof value.errorType !== 'string' || !/^[A-Za-z_][A-Za-z0-9_]{0,95}$/.test(value.errorType)
          || value.errorType.includes(item.credential)
          || !(typeof value.instanceId === 'string' || (value.instanceId === null && value.operation === 'start'))) throw new Error();
    } catch (_) { item.diagnosticErrorCounts.invalidCount++; return; }
    if (value.processId !== item.child?.pid || (value.instanceId !== item.instanceId
        && !(value.instanceId === null && value.operation === 'start'))) { item.diagnosticErrorCounts.foreignCount++; return; }
    item.diagnosticErrors.push({ processId: value.processId, instanceId: value.instanceId, operation: value.operation,
      errorType: value.errorType, observedElapsedMs: elapsed(item) });
    if (item.diagnosticErrors.length > 16) { item.diagnosticErrors.shift(); item.diagnosticErrorCounts.truncatedCount++; }
  }
  function importTiming(item, content) {
    if (!startupDiagnostics) return;
    // Count completed CPython timing records, never the header or a partial
    // final line. Keep a bounded tail across arbitrary stderr chunk boundaries.
    let offset = 0;
    for (;;) {
      const newline = content.indexOf('\n', offset);
      const segment = content.slice(offset, newline < 0 ? content.length : newline);
      if (!item.importTimingDiscarding) {
        if (item.importTimingCarry.length + segment.length > 4096) {
          item.importTimingCarry = ''; item.importTimingDiscarding = true;
        } else item.importTimingCarry += segment;
      }
      if (newline < 0) return;
      if (!item.importTimingDiscarding && /^import time:\s+\d+\s*\|\s*\d+\s*\|\s+\S[^\r\n]*\r?$/.test(item.importTimingCarry)) {
        item.importTimingLines = Math.min(Number.MAX_SAFE_INTEGER, item.importTimingLines + 1);
      }
      item.importTimingCarry = ''; item.importTimingDiscarding = false;
      offset = newline + 1;
    }
  }
  function diagnosticsFiles(item) {
    if (!startupDiagnostics) return null;
    const directory = path.join(profile.dataRoot, 'desktop-logs');
    function inspect(suffix, metadata = false) {
      const file = path.join(directory, item.instanceId + suffix), result = { path: file, exists: false, sizeBytes: null };
      if (metadata) result.metadataValid = false;
      else result.baselinePresent = false;
      try {
        const stat = fs.lstatSync(file);
        const normalize = value => process.platform === 'win32' ? path.resolve(value).toLowerCase() : path.resolve(value);
        if (!stat.isFile() || stat.isSymbolicLink() || normalize(fs.realpathSync(file)) !== normalize(file)) return result;
        result.exists = true; result.sizeBytes = stat.size;
        if (metadata && stat.size <= 1024 * 1024) {
          const value = JSON.parse(fs.readFileSync(file, 'utf8'));
          result.metadataValid = value?.schemaVersion === 1 && value.instanceId === item.instanceId && value.processId === item.child?.pid
            && value.importTimeEnabled === true && value.mode === 'cpython-importtime-with-bounded-stacks';
        } else if (!metadata && stat.size > 0) {
          const descriptor = fs.openSync(file, 'r');
          try {
            const buffer = Buffer.alloc(Math.min(stat.size, 65536));
            const bytes = fs.readSync(descriptor, buffer, 0, buffer.length, 0);
            const text = buffer.subarray(0, bytes).toString('utf8');
            result.baselinePresent = text.startsWith('InspectorPro import stack baseline (no locals or source)\n')
              && /(?:^|\n)\s*File "[^"\r\n]+", line \d+ in [^\r\n]+/.test(text);
          } finally { fs.closeSync(descriptor); }
        }
      } catch (_) { /* Missing, partial or unreadable diagnostics never replace the primary result. */ }
      return result;
    }
    return { stacks: inspect('-import-stacks.log'), imports: inspect('-import-diagnostics.json', true) };
  }
  function project() { return { status: state, instanceId: owned?.instanceId || null, processId: owned?.child?.pid || null, logPath: owned?.logPath || null, runtime: owned?.runtime || null }; }
  function changed(status) { state = status; try { onState(project()); } catch (_) { /* Observer cannot grant or stop authority. */ } }
  function log(item, content, stream, final = false) {
    item.logCarry ||= { stdout: '', stderr: '' };
    const combined = item.logCarry[stream] + String(content);
    let sanitized = combined.replaceAll(item.credential, '[redacted]');
    // Child stream chunk boundaries are arbitrary. Retain only the longest
    // suffix that could begin the private credential, independently per stream.
    // This keeps diagnostics incremental and carry bounded to 63 characters.
    let carryLength = 0;
    for (let length = Math.min(item.credential.length - 1, sanitized.length); length > 0; length--) {
      if (sanitized.endsWith(item.credential.slice(0, length))) { carryLength = length; break; }
    }
    item.logCarry[stream] = carryLength ? sanitized.slice(-carryLength) : '';
    if (carryLength) sanitized = sanitized.slice(0, -carryLength);
    if (final && item.logCarry[stream]) { sanitized += '[redacted incomplete credential]'; item.logCarry[stream] = ''; }
    if (item.logBytes >= 8 * 1024 * 1024) return;
    const bytes = Buffer.from(sanitized).subarray(0, 8 * 1024 * 1024 - item.logBytes);
    const began = performance.now();
    try { fs.appendFileSync(item.logPath, bytes); item.logBytes += bytes.length; }
    finally {
      item.timings.maximumLogWriteMs = Math.max(item.timings.maximumLogWriteMs || 0,
        Math.round(performance.now() - began));
    }
  }
  async function requestWith(item, endpoint, body, timeoutMs = 15000) {
    if (owned !== item || item.exited || !item.readyObserved || !/^\/(?!\/)[^\r\n#]*$/.test(endpoint)) throw failure('desktop_backend_unavailable');
    const response = await fetchImpl(profile.origin + endpoint, { redirect: 'error', signal: AbortSignal.timeout(timeoutMs),
      method: body === undefined ? 'GET' : 'POST', headers: { Accept: 'application/json', 'X-InspectorPro-Desktop-Token': item.credential,
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (owned !== item || item.exited) throw failure('desktop_backend_changed');
    const result = await readJson(response);
    if (owned !== item || item.exited) throw failure('desktop_backend_changed');
    return result;
  }
  async function stopOwned(item) {
    if (!item) return { terminationConfirmed: true, stdioClosed: true, resourcesClosed: true, notStarted: true };
    if (item.cleanup) return item.cleanup;
    const requestId = randomUUID(); item.shutdownRequestId = requestId;
    item.timings.shutdownRequestedElapsedMs = elapsed(item);
    if (!item.exited) {
      try { item.child.stdin.write(JSON.stringify({ schemaVersion: 1, command: 'shutdown', requestId }) + '\n'); }
      catch (_) { /* Still wait for observed exit; forced termination remains a failure. */ }
    }
    const until = Date.now() + stopTimeoutMs;
    while (!item.closed && Date.now() < until) await wait(Math.min(25, Math.max(1, until - Date.now())));
    let forced = false;
    if (!item.closed && !item.exited) {
      forced = true; try { item.child.kill('SIGKILL'); } catch (_) { /* Report unconfirmed termination below. */ }
    }
    const forceUntil = Date.now() + forceTimeoutMs;
    while (!item.closed && Date.now() < forceUntil) await wait(Math.min(25, Math.max(1, forceUntil - Date.now())));
    const receipt = item.shutdown;
    const resourcesClosed = Boolean(receipt && receipt.schemaVersion === 1 && receipt.instanceId === item.instanceId
      && receipt.resourcesClosed === true && receipt.requestId === requestId);
    const result = { instanceId: item.instanceId, processId: item.child?.pid || null, terminationConfirmed: item.exited || item.spawnError,
      stdioClosed: item.closed, resourcesClosed, forced, exitCode: item.exitCode, shutdown: receipt || null, logPath: item.logPath };
    item.cleanup = result;
    fs.writeFileSync(path.join(logRoot, item.instanceId + '-process.json'), JSON.stringify(result, null, 2));
    if (!item.closed) { item.child?.stdin?.destroy(); item.child?.stdout?.destroy(); item.child?.stderr?.destroy(); item.child?.unref?.(); }
    return result;
  }
  function start() {
    if (starting) return starting;
    if (state === 'ready') return Promise.resolve(owned.runtime);
    if (stopping || (owned && !owned.closed)) return Promise.reject(failure('desktop_backend_still_owned'));
    starting = (async () => {
      const instanceId = randomUUID();
      const item = { instanceId, credential: randomBytes(32).toString('hex'), runtime: null, exited: false, closed: false,
        logBytes: 0, logPath: path.join(logRoot, instanceId + '.log'), readyObserved: false, spawnError: false, exitCode: null,
        startedMonotonic: performance.now(), timings: { spawnStartedUnixMs: Date.now() },
        startupCheckpoints: { records: [], lastPhase: null, invalidCount: 0, foreignCount: 0, truncatedCount: 0 },
        diagnosticErrors: [], diagnosticErrorCounts: { invalidCount: 0, foreignCount: 0, truncatedCount: 0 },
        importTimingLines: 0, importTimingCarry: '', importTimingDiscarding: false };
      owned = item; history.push(item); fs.writeFileSync(item.logPath, 'InspectorPro managed runtime starting\n'); changed('starting');
      let stdout = '';
      const startedAt = Date.now();
      try {
        const entry = profile.mode === 'application' ? 'application_backend.py' : 'managed_backend.py';
        item.child = spawnImpl(python, ['-u', ...(startupDiagnostics ? ['-X', 'importtime'] : []), path.join(appRoot, 'desktop', 'runtime', entry), '--profile-file', profile.profileFile],
          { cwd: appRoot, env: childEnvironment(profile, python), windowsHide: true, shell: false, stdio: ['pipe','pipe','pipe'] });
        item.timings.spawnReturnedElapsedMs = elapsed(item);
        item.child.stdin.on('error', () => {});
        item.child.on('error', error => { item.spawnError = !item.child.pid; item.startError = failure('desktop_process_error', error.message); });
        item.child.on('exit', code => { item.exited = true; item.exitCode = code; item.timings.processExitElapsedMs = elapsed(item); if (owned === item && state === 'ready') changed('interrupted'); });
        item.child.on('close', code => {
          try { log(item, '', 'stdout', true); log(item, '', 'stderr', true); }
          catch (_) { item.startError ||= failure('desktop_diagnostic_write_failed'); }
          item.exited = true; item.closed = true; item.exitCode = code; item.timings.stdioClosedElapsedMs = elapsed(item);
        });
        for (const stream of [item.child.stdout, item.child.stderr]) stream.on('error', () => { item.startError ||= failure('desktop_diagnostic_stream_failed'); });
        item.child.stderr.on('data', bytes => {
          item.timings.firstStderrElapsedMs ??= elapsed(item);
          const content = bytes.toString('utf8');
          importTiming(item, content);
          try { log(item, content, 'stderr'); } catch (_) { item.startError ||= failure('desktop_diagnostic_write_failed'); }
        });
        item.child.stdout.on('data', bytes => {
          item.timings.firstStdoutElapsedMs ??= elapsed(item);
          try {
            log(item, bytes.toString('utf8'), 'stdout'); stdout += bytes.toString('utf8');
            if (stdout.length > 131072) throw failure('desktop_control_line_too_large');
            for (;;) {
              const newline = stdout.indexOf('\n'); if (newline < 0) break;
              const line = stdout.slice(0, newline).trim(); stdout = stdout.slice(newline + 1);
              if (line.startsWith('INSPECTORPRO_DESKTOP_RUNTIME_CHECKPOINT ')) {
                diagnosticCheckpoint(item, line.slice('INSPECTORPRO_DESKTOP_RUNTIME_CHECKPOINT '.length));
                continue;
              }
              if (line.startsWith('INSPECTORPRO_DESKTOP_RUNTIME_DIAGNOSTIC_ERROR ')) {
                diagnosticError(item, line.slice('INSPECTORPRO_DESKTOP_RUNTIME_DIAGNOSTIC_ERROR '.length));
                continue;
              }
              for (const [prefix, field] of [['INSPECTORPRO_DESKTOP_RUNTIME_READY ', 'ready'], ['INSPECTORPRO_DESKTOP_RUNTIME_SHUTDOWN ', 'shutdown']]) {
                if (line.startsWith(prefix)) {
                  const value = JSON.parse(line.slice(prefix.length));
                  if (value.instanceId !== instanceId) throw failure('desktop_private_channel_identity_mismatch');
                  item[field] = value;
                }
              }
            }
          } catch (error) { item.startError ||= error; }
        });
        item.child.stdin.write(JSON.stringify({ schemaVersion: 1, credential: item.credential, instanceId }) + '\n');
        item.timings.startControlSentElapsedMs = elapsed(item);
        while (!item.ready && !item.startError && !item.exited && Date.now() - startedAt < startupTimeoutMs) await wait(25);
        if (item.startError) throw item.startError;
        if (item.exited) throw failure('desktop_backend_early_exit');
        if (!item.ready) throw failure('desktop_backend_startup_timeout', 'Backend startup exceeded its deadline; inspect the retained runtime log');
        // Private stdout proof must match the directly owned process before any
        // credential is sent to this port. Never pair with a discovered server.
        if (item.ready.processId !== item.child.pid || item.ready.origin !== profile.origin) throw failure('desktop_owned_ready_mismatch');
        item.readyObserved = true;
        item.timings.readyObservedElapsedMs = elapsed(item);
        const remaining = startupTimeoutMs - (Date.now() - startedAt);
        if (remaining <= 0) throw failure('desktop_backend_startup_timeout');
        const actual = validateRuntime(await requestWith(item, '/api/desktop-shell/runtime', undefined, remaining), profile, instanceId);
        if (actual.processId !== item.child.pid) throw failure('desktop_owned_runtime_mismatch');
        const binding = { identity: actual.identity, owner: actual.owner, storeBinding: actual.storeBinding, document: actual.document };
        if (stableBinding && !isDeepStrictEqual(binding, stableBinding)) throw failure('desktop_restarted_store_mismatch');
        stableBinding = binding; item.runtime = actual; item.startupMs = Date.now() - startedAt;
        item.startupElapsedMs = elapsed(item); item.timings.runtimeVerifiedElapsedMs = item.startupElapsedMs; changed('ready');
        return actual;
      } catch (error) {
        item.startupElapsedMs = elapsed(item); item.timings.failureElapsedMs = item.startupElapsedMs;
        item.failure = { code: error.code || 'desktop_startup_failed', message: error.message };
        if (!item.child) { item.spawnError = true; item.exited = true; item.closed = true; }
        await stopOwned(item); changed('failed'); throw error;
      }
    })().finally(() => { starting = null; });
    return starting;
  }
  function stop() {
    if (stopping) return stopping;
    if (starting && owned && !owned.runtime) owned.startError ||= failure('desktop_startup_cancelled');
    stopping = (async () => { if (starting) await starting.catch(() => {}); changed('stopping'); const receipt = await stopOwned(owned);
      changed(receipt.terminationConfirmed && receipt.stdioClosed && receipt.resourcesClosed ? 'stopped' : 'cleanup-failed'); return receipt;
    })().finally(() => { stopping = null; }); return stopping;
  }
  function restart() {
    if (restarting) return restarting;
    restarting = (async () => { const stopped = await stop(); if (!stopped.terminationConfirmed || !stopped.stdioClosed || !stopped.resourcesClosed) throw failure('desktop_cleanup_unverified'); return start(); })()
      .finally(() => { restarting = null; }); return restarting;
  }
  return { start, stop, restart, getState: project,
    request(endpoint, body) { if (state !== 'ready') return Promise.reject(failure('desktop_backend_unavailable')); return requestWith(owned, endpoint, body); },
    getCredential() { return state === 'ready' && owned && !owned.exited ? owned.credential : null; },
    getEvidence() { return history.map(item => ({ instanceId: item.instanceId, processId: item.child?.pid || null, startupMs: item.startupMs,
      startupElapsedMs: item.startupElapsedMs, startupDiagnosticsEnabled: startupDiagnostics,
      importTimingLines: item.importTimingLines,
      timings: { ...item.timings }, startupCheckpoints: JSON.parse(JSON.stringify(item.startupCheckpoints)), diagnosticsFiles: diagnosticsFiles(item),
      diagnosticErrors: item.diagnosticErrors.map(value => ({ ...value })), diagnosticErrorCounts: { ...item.diagnosticErrorCounts },
      runtime: item.runtime, failure: item.failure || null, cleanup: item.cleanup || null, logPath: item.logPath })); } };
}
module.exports = { createManagedRuntime, childEnvironment, readJson };
