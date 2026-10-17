'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const fail = (code, message = code) => Object.assign(new Error(message), { code });
function canonicalOrigin(value) {
  let url; try { url = new URL(value); } catch (_) { throw fail('desktop_origin_invalid'); }
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.origin !== value
      || !/^\d+$/.test(url.port) || +url.port < 1024 || +url.port > 65535) throw fail('desktop_origin_invalid');
  return value;
}
async function localPath(value, { mustExist = true } = {}) {
  if (typeof value !== 'string' || !path.isAbsolute(value) || value.startsWith('\\\\')) throw fail('desktop_local_path_required');
  const selected = path.resolve(value);
  for (let current = selected;; current = path.dirname(current)) {
    try { if ((await fs.lstat(current)).isSymbolicLink()) throw fail('desktop_link_path_refused'); }
    catch (error) { if (error.code !== 'ENOENT' || (current === selected && mustExist)) throw error; }
    if (path.dirname(current) === current) break;
  }
  return selected;
}
function parseRuntimeOptions(args) {
  if (args[0] === '--') args = args.slice(1);
  const values = {}, allowed = new Set(['--profile-file', '--python', '--acceptance-output', '--startup-diagnostics-output', '--research-acceptance-output', '--workflow-acceptance-output', '--browser-acceptance-output', '--generation-acceptance-output', '--codex-acceptance-output']);
  for (let index = 0; index < args.length; index += 2) {
    if (!allowed.has(args[index]) || Object.hasOwn(values, args[index]) || !args[index + 1] || args[index + 1].startsWith('--')) {
      throw fail('desktop_options_invalid', 'Use npm start -- --profile-file ABSOLUTE_PROFILE_JSON --python ABSOLUTE_PYTHON_EXE');
    }
    values[args[index]] = args[index + 1];
  }
  if (!values['--profile-file'] || !values['--python']) throw fail('desktop_profile_required', 'Create an isolated desktop profile, then supply --profile-file and --python. See docs/desktop-runtime-integration.md.');
  if (values['--codex-acceptance-output'] && [...allowed].some(key => key.endsWith('-output') && key !== '--codex-acceptance-output' && values[key])) throw fail('desktop_options_invalid');
  if (values['--generation-acceptance-output'] && [...allowed].some(key => key.endsWith('-output') && key !== '--generation-acceptance-output' && values[key])) throw fail('desktop_options_invalid');
  if (values['--browser-acceptance-output'] && ['--acceptance-output', '--startup-diagnostics-output', '--research-acceptance-output', '--workflow-acceptance-output'].some(key => values[key])) throw fail('desktop_options_invalid');
  if (values['--acceptance-output'] && values['--startup-diagnostics-output']) throw fail('desktop_options_invalid', 'Startup diagnostics and application acceptance are separate modes.');
  if (values['--workflow-acceptance-output'] && ['--acceptance-output', '--startup-diagnostics-output', '--research-acceptance-output'].some(key => values[key])) {
    throw fail('desktop_options_invalid', 'Workflow acceptance is a separate normal-application check.');
  }
  if (values['--research-acceptance-output'] && !values['--acceptance-output']) throw fail('desktop_options_invalid', 'Research acceptance requires full application acceptance.');
  for (const value of Object.values(values)) if (!path.isAbsolute(value)) throw fail('desktop_local_path_required');
  return { ...(values['--codex-acceptance-output'] ? { codexAcceptanceOutput: values['--codex-acceptance-output'] } : {}), ...(values['--generation-acceptance-output'] ? { generationAcceptanceOutput: values['--generation-acceptance-output'] } : {}), ...(values['--browser-acceptance-output'] ? { browserAcceptanceOutput: values['--browser-acceptance-output'] } : {}), ...(values['--workflow-acceptance-output'] ? { workflowAcceptanceOutput: values['--workflow-acceptance-output'] } : {}), ...(values['--research-acceptance-output'] ? { researchAcceptanceOutput: values['--research-acceptance-output'] } : {}), profileFile: values['--profile-file'], python: values['--python'], acceptanceOutput: values['--acceptance-output'] || null,
    startupDiagnosticsOutput: values['--startup-diagnostics-output'] || null };
}
async function loadRuntimeProfile(profileFile) {
  profileFile = await localPath(profileFile);
  const stat = await fs.stat(profileFile);
  if (!stat.isFile() || stat.size > 16384) throw fail('desktop_profile_invalid');
  const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
  const keys = ['schemaVersion','mode','profileId','origin','dataRoot','backendId','storeId','acceptanceLayoutId'];
  if (!profile || Object.keys(profile).some(key => !keys.includes(key)) || keys.some(key => !Object.hasOwn(profile, key))
      || profile.schemaVersion !== 1 || profile.mode !== 'managed' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(profile.profileId)
      || !UUID.test(profile.backendId) || !UUID.test(profile.storeId)
      || !(profile.acceptanceLayoutId === null || /^fl-[A-Za-z0-9._-]{1,128}$/.test(profile.acceptanceLayoutId))) throw fail('desktop_profile_invalid');
  canonicalOrigin(profile.origin);
  profile.dataRoot = await localPath(profile.dataRoot);
  const stateRoot = path.join(profile.dataRoot, 'desktop-client');
  const binding = { schemaVersion: 1, origin: profile.origin, backendId: profile.backendId, storeId: profile.storeId, profileId: profile.profileId };
  const partition = 'persist:ip-runtime-' + createHash('sha256').update(JSON.stringify(binding)).digest('hex').slice(0, 32);
  return Object.freeze({ ...profile, profileFile, stateRoot, partition });
}
function validateRuntime(value, profile, instanceId) {
  if (profile.mode === 'application') return require('./application-profile.cjs').validateApplicationRuntime(value, profile, instanceId);
  const identity = value?.identity || value;
  if (!value || value.schemaVersion !== 1 || value.product !== 'InspectorPro' || value.mode !== 'desktop-managed'
      || identity.backendId !== profile.backendId || identity.storeId !== profile.storeId
      || value.profileId !== profile.profileId || value.origin !== profile.origin || value.instanceId !== instanceId
      || !Number.isSafeInteger(value.processId) || value.processId < 1
      || value.capabilities?.generalEditing !== false || value.capabilities?.researchBrowsing !== false
      || value.capabilities?.facilityAcceptance !== Boolean(profile.acceptanceLayoutId)
      || !/^[a-zA-Z0-9._-]{1,128}$/.test(identity.principalId)
      || !['sessionId','ownerId'].every(key => typeof value.owner?.[key] === 'string' && value.owner[key].length > 0 && value.owner[key].length <= 512)
      || typeof value.storeBinding !== 'string' || !/^[a-f0-9]{64}$/.test(value.storeBinding)) throw fail('desktop_runtime_identity_mismatch');
  if (value.document?.tenantId !== 'local' || value.document?.siteId !== 'site-local'
      || value.document?.documentId !== profile.acceptanceLayoutId) throw fail('desktop_runtime_document_mismatch');
  return JSON.parse(JSON.stringify({ ...value, identity: { backendId: identity.backendId, storeId: identity.storeId, principalId: identity.principalId },
    document: profile.acceptanceLayoutId ? { tenantId: 'local', siteId: 'site-local', documentId: profile.acceptanceLayoutId } : null }));
}
function hasCompleteStartupDiagnostics(backends, cleanup) {
  if (!Array.isArray(backends) || backends.length !== 1 || !cleanup) return false;
  const value = backends[0], timings = value?.timings, checkpoints = value?.startupCheckpoints, files = value?.diagnosticsFiles;
  const time = number => typeof number === 'number' && Number.isFinite(number) && number >= 0;
  const cleanCounts = counts => counts && ['invalidCount', 'foreignCount', 'truncatedCount'].every(key => counts[key] === 0);
  if (!value || typeof value.instanceId !== 'string' || !value.instanceId || !Number.isSafeInteger(value.processId) || value.processId < 1
      || value.instanceId !== cleanup.instanceId || value.processId !== cleanup.processId
      || value.runtime?.instanceId !== value.instanceId || value.runtime?.processId !== value.processId
      || JSON.stringify(value.cleanup) !== JSON.stringify(cleanup) || value.failure !== null
      || value.startupDiagnosticsEnabled !== true || !Array.isArray(value.diagnosticErrors) || value.diagnosticErrors.length
      || !Number.isSafeInteger(value.importTimingLines) || value.importTimingLines < 1
      || !cleanCounts(value.diagnosticErrorCounts) || !time(value.startupElapsedMs) || !timings
      || !time(timings.spawnStartedUnixMs) || timings.spawnStartedUnixMs === 0) return false;
  const ordered = ['readyObservedElapsedMs', 'runtimeVerifiedElapsedMs', 'shutdownRequestedElapsedMs', 'processExitElapsedMs', 'stdioClosedElapsedMs'];
  if (ordered.some((key, index) => !time(timings[key]) || (index > 0 && timings[key] < timings[ordered[index - 1]]))
      || value.startupElapsedMs !== timings.runtimeVerifiedElapsedMs) return false;
  if (!cleanCounts(checkpoints) || !Array.isArray(checkpoints.records) || !checkpoints.records.length
      || checkpoints.lastPhase !== checkpoints.records.at(-1).phase
      || !checkpoints.records.some(record => record.phase === 'application-ready')
      || checkpoints.records.some(record => record.instanceId !== value.instanceId || record.processId !== value.processId
        || !Number.isSafeInteger(record.sequence) || record.sequence < 1 || !time(record.elapsedMs) || !time(record.observedElapsedMs))) return false;
  return files?.stacks?.exists === true && files.stacks.baselinePresent === true
    && Number.isSafeInteger(files.stacks.sizeBytes) && files.stacks.sizeBytes > 0 && typeof files.stacks.path === 'string'
    && files.imports?.exists === true && files.imports.metadataValid === true && typeof files.imports.path === 'string';
}
module.exports = { canonicalOrigin, parseRuntimeOptions, loadRuntimeProfile, validateRuntime, localPath, hasCompleteStartupDiagnostics };
