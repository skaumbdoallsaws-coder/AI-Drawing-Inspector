'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { canonicalOrigin, localPath } = require('./runtime-settings.cjs');
const fail = code => Object.assign(new Error(code), { code });
const KEYS = ['schemaVersion', 'mode', 'profileId', 'origin', 'dataRoot', 'backendId', 'storeId', 'facilityRoot', 'libraryRoot', 'startupLayoutId'];
async function loadApplicationProfile(file) {
  file = await localPath(file);
  if ((await fs.stat(file)).size > 16384) throw fail('desktop_profile_invalid');
  const p = JSON.parse(await fs.readFile(file, 'utf8'));
  if (!p || Object.keys(p).some(k => !KEYS.includes(k) && !['modelGateway', 'codexRuntime'].includes(k)) || KEYS.some(k => !Object.hasOwn(p, k))
      || p.schemaVersion !== 1 || p.mode !== 'application'
      || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(p.profileId)
      || ['backendId', 'storeId'].some(k => !/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(p[k]))
      || !(p.startupLayoutId === null || /^fl-[A-Za-z0-9._-]{1,128}$/.test(p.startupLayoutId))) throw fail('desktop_profile_invalid');
  canonicalOrigin(p.origin);
  for (const k of ['dataRoot', 'facilityRoot', 'libraryRoot']) p[k] = await localPath(p[k]);
  if (Object.hasOwn(p, 'modelGateway')) {
    const gateway = p.modelGateway;
    if (!gateway || typeof gateway !== 'object' || Array.isArray(gateway)
        || Object.keys(gateway).sort().join(',') !== 'configPath,dependencyRoot') throw fail('desktop_gateway_profile_invalid');
    const configPath = await localPath(gateway.configPath), dependencyRoot = await localPath(gateway.dependencyRoot);
    const config = await fs.stat(configPath);
    if (!config.isFile() || config.size > 65536 || !(await fs.stat(dependencyRoot)).isDirectory()
        || !(await fs.stat(await localPath(path.join(dependencyRoot, 'litellm', '__init__.py')))).isFile()) {
      throw fail('desktop_gateway_profile_invalid');
    }
    p.modelGateway = Object.freeze({ configPath, dependencyRoot });
  }
  if (Object.hasOwn(p, 'codexRuntime')) p.codexRuntime = await require('./codex-config.cjs').validateCodexConfig(p.codexRuntime, p);
  const binding = [p.backendId, p.storeId, p.facilityRoot, p.libraryRoot].join('\n');
  return Object.freeze({ ...p, profileFile: file, stateRoot: path.join(p.dataRoot, 'desktop-client'),
    partition: 'persist:ip-application-' + createHash('sha256').update(binding).digest('hex').slice(0, 32) });
}
function validateApplicationRuntime(v, p, instanceId) {
  if (!v || v.schemaVersion !== 1 || v.product !== 'InspectorPro' || v.mode !== 'desktop-application'
      || v.profileId !== p.profileId || v.origin !== p.origin || v.instanceId !== instanceId
      || !Number.isSafeInteger(v.processId) || v.processId < 1
      || v.identity?.backendId !== p.backendId || v.identity?.storeId !== p.storeId
      || typeof v.identity?.principalId !== 'string' || !v.identity.principalId
      || v.capabilities?.generalEditing !== true || v.capabilities?.applicationRoutes !== true
      || v.document?.documentId !== p.startupLayoutId
      || v.document?.tenantId !== 'local' || v.document?.siteId !== 'site-local'
      || ['facilityRoot', 'libraryRoot'].some(k => path.resolve(v.stores?.[k] || '') !== p[k])
      || !/^[a-f0-9]{64}$/.test(v.storeBinding)) throw fail('desktop_application_identity_mismatch');
  return JSON.parse(JSON.stringify(v));
}
module.exports = { loadApplicationProfile, validateApplicationRuntime };
