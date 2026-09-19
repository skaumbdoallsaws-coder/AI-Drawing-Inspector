'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
const { performance } = require('node:perf_hooks');

const REPLACEMENT_DELAYS_MS = Object.freeze([20, 50, 100, 200, 400]);
const REPLACEMENT_WINDOW_MS = 1000;
const WINDOWS_REPLACEMENT_ERRORS = new Set(['EPERM', 'EACCES', 'EBUSY']);
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

function fail(code, message) { return Object.assign(new Error(message), { code }); }
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort()
    .map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
function jsonData(value, depth = 0, seen = new Set()) {
  if (depth > 32) throw fail('recovery_schema_invalid', 'Record nesting is too deep');
  if (value === null || typeof value === 'string' || typeof value === 'boolean'
      || (typeof value === 'number' && Number.isFinite(value))) return;
  if (!value || typeof value !== 'object' || seen.has(value)
      || (!Array.isArray(value) && Object.getPrototypeOf(value) !== Object.prototype
        && Object.getPrototypeOf(value) !== null)) {
    throw fail('recovery_schema_invalid', 'Records must contain only acyclic JSON data');
  }
  seen.add(value);
  for (const item of Object.values(value)) jsonData(item, depth + 1, seen);
  seen.delete(value);
}
function textField(value) { return typeof value === 'string' && value.length > 0 && value.length <= 512; }
function validIdentity(value) { return value && ['backendId', 'storeId', 'principalId'].every(key => textField(value[key])); }

/** A single-main-process journal. It does not establish backend authorization. */
async function createRecoveryStore(options) {
  if (!options || !path.isAbsolute(options.directory || '') || !validIdentity(options.identity)) {
    throw new TypeError('Main-selected absolute directory and verified identity are required');
  }
  const directory = path.resolve(options.directory);
  jsonData(options.identity);
  const identity = JSON.parse(JSON.stringify(options.identity));
  if (options.onDiagnostic !== undefined && typeof options.onDiagnostic !== 'function') throw new TypeError('Invalid recovery diagnostic observer');
  function diagnostic(value) {
    // Diagnostics never authorize a write, alter a result, or expose the record.
    try { Promise.resolve(options.onDiagnostic?.(JSON.parse(JSON.stringify(value)))).catch(() => {}); }
    catch (_) {}
  }
  const maxRecordBytes = options.maxRecordBytes ?? 8 * 1024 * 1024;
  const maxRecords = options.maxRecords ?? 100;
  const maxTotalBytes = options.maxTotalBytes ?? 32 * 1024 * 1024;
  if (![maxRecordBytes, maxRecords, maxTotalBytes].every(n => Number.isSafeInteger(n) && n > 0)
      || maxRecordBytes > 8 * 1024 * 1024 || maxRecords > 1000 || maxTotalBytes > 256 * 1024 * 1024) {
    throw new TypeError('Invalid recovery store limits');
  }
  await fs.mkdir(directory, { recursive: true, mode: 0o700 });
  const marker = path.join(directory, 'identity.json');
  try {
    const markerHandle = await fs.open(marker, 'wx', 0o600);
    try { await markerHandle.writeFile(JSON.stringify({ schemaVersion: 1, identity })); await markerHandle.sync(); }
    finally { await markerHandle.close(); }
  } catch (error) { if (error.code !== 'EEXIST') throw error; }
  const markerStat = await fs.stat(marker);
  if (markerStat.size > 8192) throw fail('recovery_identity_mismatch', 'Recovery identity marker is invalid');
  const stored = JSON.parse(await fs.readFile(marker, 'utf8'));
  if (stored.schemaVersion !== 1 || canonical(stored.identity) !== canonical(identity)) {
    throw fail('recovery_identity_mismatch', 'Recovery directory belongs to another identity');
  }

  function filename(key) {
    if (typeof key !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(key)) {
      throw fail('recovery_key_invalid', 'Recovery key must be opaque, not a path');
    }
    return path.join(directory, createHash('sha256').update(key).digest('hex') + '.json');
  }
  function validate(record) {
    jsonData(record);
    if (!record || record.schemaVersion !== 1 || !validIdentity(record.identity)
        || canonical(record.identity) !== canonical(identity)) {
      throw fail('recovery_identity_mismatch', 'Record identity does not match the verified backend');
    }
    if (Object.keys(record).some(key => !['schemaVersion', 'identity', 'document', 'handle', 'payload'].includes(key))
        || !record.document || !['tenantId', 'siteId', 'documentId', 'baseRevision', 'draftRevision']
          .every(key => textField(record.document[key]))
        || !record.handle || !['pending', 'unknown', 'reconciled'].includes(record.handle.state)
        || !textField(record.handle.phase)
        || (!textField(record.handle.requestId) && !textField(record.handle.transactionId))
        || (record.handle.requestId !== undefined && !textField(record.handle.requestId))
        || (record.handle.transactionId !== undefined && !textField(record.handle.transactionId))
        || !record.payload || typeof record.payload !== 'object' || Array.isArray(record.payload)) {
      throw fail('recovery_schema_invalid', 'Record requires document revisions and an operation handle');
    }
  }
  async function read(key) {
    const file = filename(key);
    let stat;
    try { stat = await fs.stat(file); } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
    if (stat.size > maxRecordBytes) throw fail('recovery_record_too_large', 'Stored record exceeds the configured limit');
    const envelope = JSON.parse(await fs.readFile(file, 'utf8'));
    if (envelope.schemaVersion !== 1 || envelope.key !== key || !textField(envelope.checkpointId)) {
      throw fail('recovery_schema_invalid', 'Stored recovery envelope is invalid');
    }
    validate(envelope.record);
    return envelope;
  }
  async function inventory(includeTemporary = false) {
    const names = (await fs.readdir(directory)).filter(name => /^[a-f0-9]{64}\.json$/.test(name)
      || (includeTemporary && /^\.[a-f0-9-]{36}\.tmp$/.test(name)));
    if (names.filter(name => name.endsWith('.json')).length > maxRecords) {
      throw fail('recovery_store_full', 'Recovery directory exceeds the record quota');
    }
    const sizes = await Promise.all(names.map(async name => ({ name, size: (await fs.stat(path.join(directory, name))).size })));
    return sizes;
  }
  let queue = Promise.resolve();
  function serial(callback) {
    const operation = queue.then(callback);
    queue = operation.catch(() => {});
    return operation;
  }
  async function syncDirectory() {
    // Windows Node cannot portably flush a directory. The acknowledgment names
    // exactly the file-sync/atomic-rename guarantee instead of claiming more.
    if (process.platform === 'win32') return false;
    const handle = await fs.open(directory, 'r');
    try { await handle.sync(); return true; } finally { await handle.close(); }
  }
  async function targetBytes(target) {
    try {
      const stat = await fs.stat(target);
      if (!stat.isFile() || stat.size > maxRecordBytes) throw fail('recovery_schema_invalid', 'Replacement target is not a bounded recovery file');
      return await fs.readFile(target);
    } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
  }
  async function observeTarget(target, priorBytes, candidateBytes) {
    try {
      const bytes = await targetBytes(target);
      return { targetState: bytes === null ? 'missing' : priorBytes && bytes.equals(priorBytes) ? 'previous-checkpoint'
        : bytes.equals(candidateBytes) ? 'candidate-checkpoint' : 'different-checkpoint',
        observedTargetSha256: bytes && digest(bytes) };
    } catch (error) { return { targetState: 'unreadable', observationError: error.code || 'unknown' }; }
  }
  async function replaceCheckpoint(temporary, target, priorBytes, candidateBytes, context) {
    const started = performance.now();
    const failures = [];
    let retryIndex = 0;
    while (true) {
      // Compare exact bytes again after each delay. An unexpected writer or a
      // missing/changed checkpoint never becomes permission to overwrite it.
      const current = await targetBytes(target);
      if (priorBytes === null ? current !== null : current === null || !current.equals(priorBytes)) {
        throw fail('recovery_checkpoint_conflict', 'Recovery checkpoint changed before replacement');
      }
      context.stage = 'rename';
      context.attempts += 1;
      try { await fs.rename(temporary, target); }
      catch (error) {
        const elapsedMs = Math.round(performance.now() - started);
        const delayMs = REPLACEMENT_DELAYS_MS[retryIndex];
        const retry = process.platform === 'win32' && WINDOWS_REPLACEMENT_ERRORS.has(error.code)
          && delayMs !== undefined && elapsedMs + delayMs <= REPLACEMENT_WINDOW_MS;
        failures.push({ attempt: context.attempts, code: error.code || 'unknown', errno: error.errno ?? null,
          syscall: error.syscall || 'rename', elapsedMs, retryDelayMs: retry ? delayMs : null });
        context.failures = failures;
        diagnostic({ ...context, event: 'replacement-attempt-failed', elapsedMs, willRetry: retry });
        if (!retry) throw error;
        retryIndex += 1;
        await new Promise(resolve => setTimeout(resolve, delayMs));
        if (performance.now() - started > REPLACEMENT_WINDOW_MS) throw error;
        context.stage = 'retry-checkpoint-validation';
        continue;
      }
      context.replaced = true;
      context.stage = 'directory-sync';
      const directorySynced = await syncDirectory();
      if (failures.length) diagnostic({ ...context, event: 'replacement-retry-succeeded',
        elapsedMs: Math.round(performance.now() - started), ...(await observeTarget(target, priorBytes, candidateBytes)) });
      return directorySynced;
    }
  }
  function write({ key, record, expectedCheckpointId } = {}) {
    // Freeze caller data before joining the write queue.
    validate(record);
    const clone = JSON.parse(JSON.stringify(record));
    const target = filename(key);
    return serial(async () => {
      const prior = await read(key);
      if ((prior && expectedCheckpointId !== prior.checkpointId) || (!prior && expectedCheckpointId)) {
        throw fail('recovery_checkpoint_conflict', 'Recovery checkpoint changed');
      }
      const priorBytes = await targetBytes(target);
      if (prior ? priorBytes === null || canonical(JSON.parse(priorBytes)) !== canonical(prior) : priorBytes !== null) {
        throw fail('recovery_checkpoint_conflict', 'Recovery checkpoint changed while preparing replacement');
      }
      if (prior) {
        if (canonical(prior.record.document) !== canonical(clone.document)) {
          throw fail('recovery_binding_conflict', 'Document revision binding cannot change under an existing recovery key');
        }
        for (const field of ['requestId', 'transactionId']) {
          if (prior.record.handle[field] && prior.record.handle[field] !== clone.handle[field]) {
            throw fail('recovery_binding_conflict', 'An unresolved operation handle cannot be replaced');
          }
        }
        if (prior.record.handle.state === 'reconciled' && clone.handle.state !== 'reconciled') {
          throw fail('recovery_binding_conflict', 'Reconciled checkpoint cannot be reused for new work');
        }
      }
      const checkpointId = randomUUID();
      const envelope = { schemaVersion: 1, key, checkpointId, writtenAt: new Date().toISOString(), record: clone };
      const data = Buffer.from(JSON.stringify(envelope));
      if (data.length > maxRecordBytes) throw fail('recovery_record_too_large', 'Recovery record exceeds limit');
      // Unacknowledged temporary files left by a killed process consume quota
      // too. They are never interpreted as successful checkpoints or deleted
      // automatically while transaction recovery coverage is incomplete.
      const entries = await inventory(true);
      const existingSize = entries.find(entry => entry.name === path.basename(target))?.size || 0;
      if ((!prior && entries.filter(entry => entry.name.endsWith('.json')).length >= maxRecords)
          || entries.reduce((sum, entry) => sum + entry.size, 0) - existingSize + data.length > maxTotalBytes) {
        throw fail('recovery_store_full', 'Recovery quota exceeded; unresolved records were retained');
      }
      const temporary = path.join(directory, '.' + randomUUID() + '.tmp');
      const context = { schemaVersion: 1, revision: 'recovery-checkpoint-replacement-v1', pid: process.pid,
        platform: process.platform, key, target, temporary, priorCheckpointId: prior?.checkpointId || null,
        candidateCheckpointId: checkpointId, priorSha256: priorBytes && digest(priorBytes), candidateSha256: digest(data),
        attempts: 0, replaced: false, stage: 'temporary-open', failures: [] };
      let handle;
      try {
        handle = await fs.open(temporary, 'wx', 0o600);
        context.stage = 'temporary-write';
        await handle.writeFile(data);
        context.stage = 'temporary-sync';
        await handle.sync();
        context.stage = 'temporary-close';
        await handle.close(); handle = null;
        const directorySynced = await replaceCheckpoint(temporary, target, priorBytes, data, context);
        return { key, checkpointId, bytes: data.length, acknowledged: true,
          durability: directorySynced ? 'file-and-directory-sync-atomic-replace' : 'file-sync-atomic-replace' };
      } catch (error) {
        if (handle) await handle.close().catch(() => {});
        // Only this operation's uncommitted temporary file is removed.
        let temporaryCleanup = 'removed';
        try { await fs.unlink(temporary); } catch (cleanupError) {
          temporaryCleanup = cleanupError.code === 'ENOENT' ? 'absent' : 'retained';
          if (cleanupError.code !== 'ENOENT') context.temporaryCleanupError = cleanupError.code || 'unknown';
        }
        const detail = { ...context, event: 'checkpoint-write-failed', acknowledged: false,
          errorCode: error.code || 'unknown', errno: error.errno ?? null, syscall: error.syscall || null,
          temporaryCleanup, ...(await observeTarget(target, priorBytes, data)) };
        error.recoveryReplacement = JSON.parse(JSON.stringify(detail));
        diagnostic(detail);
        throw error;
      }
    });
  }
  function clear({ key, expectedCheckpointId } = {}) {
    return serial(async () => {
      const prior = await read(key);
      if (!prior || prior.checkpointId !== expectedCheckpointId) {
        throw fail('recovery_checkpoint_conflict', 'Recovery checkpoint changed or is missing');
      }
      if (prior.record.handle.state !== 'reconciled') {
        throw fail('recovery_unresolved', 'Unknown and pending transaction handles cannot be cleared');
      }
      await fs.unlink(filename(key));
      await syncDirectory();
      return { key, cleared: true };
    });
  }
  async function list() {
    const entries = await inventory();
    const summaries = [];
    for (const entry of entries) {
      if (entry.size > maxRecordBytes) throw fail('recovery_record_too_large', 'Stored record exceeds limit');
      const envelope = JSON.parse(await fs.readFile(path.join(directory, entry.name), 'utf8'));
      const verified = await read(envelope.key);
      if (!verified || path.basename(filename(envelope.key)) !== entry.name) {
        throw fail('recovery_schema_invalid', 'Recovery filename binding is invalid');
      }
      summaries.push({ key: verified.key, checkpointId: verified.checkpointId,
        document: verified.record.document, handle: verified.record.handle, bytes: entry.size });
    }
    return summaries;
  }
  return Object.freeze({ write, read, list, clear });
}

module.exports = { createRecoveryStore };
