'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { localPath } = require('./runtime-settings.cjs');
const KEYS = ['schemaVersion', 'model', 'editPreviews', 'allowPaidInference', 'dependencyRoot', 'binary', 'pilotRoot', 'credentialTarget', 'packageSha256'];
const overlaps = (a, b) => a === b || a.startsWith(b + path.sep) || b.startsWith(a + path.sep);
async function validateCodexConfig(value, profile) {
  try {
    const subscription = value?.schemaVersion === 2;
    const keys = subscription ? [...KEYS, 'authMode'] : KEYS;
    if (!value || typeof value !== 'object' || Array.isArray(value)
        || Object.keys(value).sort().join(',') !== [...keys].sort().join(',')
        || ![1, 2].includes(value.schemaVersion) || (subscription && value.authMode !== 'chatgpt_plan')
        || value.model !== (subscription ? 'gpt-6.1-sol' : 'gpt-5.5') || typeof value.editPreviews !== 'boolean'
        || typeof value.packageSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.packageSha256)
        || value.allowPaidInference !== !subscription
        || value.credentialTarget !== (subscription ? 'InspectorPro/ChatGPT/' : 'InspectorPro/Codex/') + profile.profileId) throw Error();
    const dependencyRoot = await localPath(value.dependencyRoot), binary = await localPath(value.binary);
    const pilotRoot = await localPath(value.pilotRoot, { mustExist: false });
    if (!(await fs.stat(dependencyRoot)).isDirectory() || !(await fs.stat(binary)).isFile()
        || binary !== path.join(dependencyRoot, 'codex_cli_bin', 'bin', 'codex.exe')
        || pilotRoot !== path.join(profile.dataRoot, 'codex-pilot')
        || [profile.dataRoot, profile.facilityRoot, profile.libraryRoot].some(root => overlaps(root.toLowerCase(), dependencyRoot.toLowerCase()))
        || [profile.facilityRoot, profile.libraryRoot, dependencyRoot].some(root => overlaps(root.toLowerCase(), pilotRoot.toLowerCase()))) throw Error();
    return Object.freeze({ ...value, dependencyRoot, binary, pilotRoot });
  } catch (_) {
    throw Object.assign(new Error('desktop_codex_config_invalid'), { code: 'desktop_codex_config_invalid' });
  }
}
function isolateCodexEnvironment(source) {
  const result = { ...source };
  for (const key of Object.keys(result)) if (/^(INSPECTORPRO_CODEX_|INSPECTORPRO_CHATGPT_|CODEX_)/i.test(key)) delete result[key];
  return result;
}
module.exports = { validateCodexConfig, isolateCodexEnvironment };
