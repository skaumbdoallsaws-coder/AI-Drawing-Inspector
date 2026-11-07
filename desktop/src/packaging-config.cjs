'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { localPath } = require('./runtime-settings.cjs');
const PACKAGES = ['py3dbp', 'trimesh', 'reportlab', 'numpy', 'PIL']; // numpy and PIL: the GLB worker imports them directly.
const KEYS = ['schemaVersion', 'dependencyRoot'];
const normalize = value => process.platform === 'win32' ? value.toLowerCase() : value;
const overlaps = (a, b) => {
  a = normalize(a); b = normalize(b);
  return a === b || a.startsWith(b.endsWith(path.sep) ? b : b + path.sep)
    || b.startsWith(a.endsWith(path.sep) ? a : a + path.sep);
};
async function checkedPath(value, mustExist = true) {
  if (typeof value !== 'string' || !value || /[\x00-\x1f]/.test(value)
      || /^[\\/]{2}/.test(value) || value.split(/[\\/]/).includes('..')
      || (process.platform === 'win32' && !/^[A-Za-z]:[\\/]/.test(value))
      || value.slice(process.platform === 'win32' && /^[A-Za-z]:/.test(value) ? 2 : 0).includes(':')) throw Error();
  return localPath(value, { mustExist });
}
async function validatePackagingConfig(value, profile) {
  try {
    if (!value || typeof value !== 'object' || Array.isArray(value)
        || KEYS.some(key => !Object.hasOwn(value, key))
        || Object.keys(value).some(key => ![...KEYS, 'geometryPython'].includes(key))
        || value.schemaVersion !== 1) throw Error();
    const dependencyRoot = await checkedPath(value.dependencyRoot), stores = [];
    for (const key of ['dataRoot', 'facilityRoot', 'libraryRoot']) {
      const root = await checkedPath(profile[key]);
      if (!(await fs.stat(root)).isDirectory()) throw Error();
      stores.push(root);
    }
    if (!(await fs.stat(dependencyRoot)).isDirectory() || stores.some(root => overlaps(root, dependencyRoot))) throw Error();
    for (const name of PACKAGES) {
      if (!(await fs.stat(await checkedPath(path.join(dependencyRoot, name, '__init__.py')))).isFile()) throw Error();
    }
    const root = await checkedPath(path.join(stores[0], 'packaging'), false);
    for (const target of [root, await checkedPath(path.join(root, 'step-jobs'), false)]) {
      try { if (!(await fs.stat(target)).isDirectory()) throw Error(); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
    if (stores.slice(1).some(store => overlaps(root, store))) throw Error();
    const result = { ...value, dependencyRoot };
    if (Object.hasOwn(value, 'geometryPython')) {
      const python = await checkedPath(value.geometryPython);
      if (!(await fs.stat(python)).isFile() || [...stores, dependencyRoot].some(root => overlaps(root, python))) throw Error();
      result.geometryPython = python;
    }
    return Object.freeze(result);
  } catch (_) {
    throw Object.assign(new Error('desktop_packaging_config_invalid'), { code: 'desktop_packaging_config_invalid' });
  }
}
function isolatePackagingEnvironment(source) {
  const result = { ...source };
  for (const key of Object.keys(result)) if (/^(INSPECTORPRO_PACKAGING_|INSPECTORPRO_CODEX_PACKAGING$)/i.test(key)) delete result[key];
  return result;
}
module.exports = { validatePackagingConfig, isolatePackagingEnvironment };
