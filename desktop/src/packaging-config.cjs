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
// Strict. A refusal carries the first check that failed as error.reason, from a fixed set and never with a value:
// settings, dependency-folder, package:<name>, storage or step-python. The Python loader checks in the same order.
async function validatePackagingConfig(value, profile) {
  let reason = 'settings';
  try {
    if (!value || typeof value !== 'object' || Array.isArray(value)
        || KEYS.some(key => !Object.hasOwn(value, key))
        || Object.keys(value).some(key => ![...KEYS, 'geometryPython'].includes(key))
        || value.schemaVersion !== 1) throw Error();
    reason = 'dependency-folder';
    const dependencyRoot = await checkedPath(value.dependencyRoot), stores = [];
    reason = 'storage';
    for (const key of ['dataRoot', 'facilityRoot', 'libraryRoot']) {
      const root = await checkedPath(profile[key]);
      if (!(await fs.stat(root)).isDirectory()) throw Error();
      stores.push(root);
    }
    reason = 'dependency-folder';
    if (!(await fs.stat(dependencyRoot)).isDirectory() || stores.some(root => overlaps(root, dependencyRoot))) throw Error();
    for (const name of PACKAGES) {
      reason = 'package:' + name;
      if (!(await fs.stat(await checkedPath(path.join(dependencyRoot, name, '__init__.py')))).isFile()) throw Error();
    }
    reason = 'storage';
    const root = await checkedPath(path.join(stores[0], 'packaging'), false);
    for (const target of [root, await checkedPath(path.join(root, 'step-jobs'), false)]) {
      try { if (!(await fs.stat(target)).isDirectory()) throw Error(); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
    if (stores.slice(1).some(store => overlaps(root, store))) throw Error();
    const result = { ...value, dependencyRoot };
    if (Object.hasOwn(value, 'geometryPython')) {
      reason = 'step-python';
      const python = await checkedPath(value.geometryPython);
      if (!(await fs.stat(python)).isFile() || [...stores, dependencyRoot].some(root => overlaps(root, python))) throw Error();
      result.geometryPython = python;
    }
    return Object.freeze(result);
  } catch (_) {
    throw Object.assign(new Error('desktop_packaging_config_invalid'), { code: 'desktop_packaging_config_invalid', reason });
  }
}
// Startup never depends on Packaging. An unusable runtime turns Packaging off for this session, or only STEP import
// when just the STEP Python is unusable, and the reason is kept for the window's notice. Nothing from a refused
// runtime is used. Enabling Packaging (tools/enable_desktop_packaging.py) stays strict.
async function loadPackagingRuntime(value, profile) {
  try { return { runtime: await validatePackagingConfig(value, profile), unavailable: null }; }
  catch (error) {
    if (error.reason === 'step-python') {
      const { geometryPython: _, ...rest } = value;
      try { return { runtime: await validatePackagingConfig(rest, profile), unavailable: error.reason }; }
      catch (_) { /* Report the original reason below. */ }
    }
    return { runtime: null, unavailable: error.reason || 'settings' };
  }
}
const CAUSES = {
  settings: 'its settings in the application profile are not valid',
  'dependency-folder': 'its dependency folder is missing or not allowed (a link, a network path, or inside an InspectorPro data folder)',
  storage: 'its storage folder in the application data folder cannot be used (a file or link is in the way)',
};
const REPAIR = ' To turn it back on, repair the packagingRuntime entry of the application profile or the folders it names, then restart InspectorPro.';
function packagingNotice(reason) {
  if (!reason) return null;
  if (reason === 'step-python') {
    return 'STEP import is off for this session: the STEP Python configured for Packaging & Shipping is missing or not allowed.'
      + ' Manual packing, reports and the rest of InspectorPro work normally.' + REPAIR;
  }
  const name = /^package:([A-Za-z0-9_]+)$/.exec(reason)?.[1];
  const cause = name && PACKAGES.includes(name) ? 'its dependency folder is missing the ' + name + ' package' : CAUSES[reason] || CAUSES.settings;
  return 'Packaging & Shipping is off for this session: ' + cause + '. The rest of InspectorPro works normally.' + REPAIR;
}
function isolatePackagingEnvironment(source) {
  const result = { ...source };
  for (const key of Object.keys(result)) if (/^(INSPECTORPRO_PACKAGING_|INSPECTORPRO_CODEX_PACKAGING$)/i.test(key)) delete result[key];
  return result;
}
module.exports = { validatePackagingConfig, loadPackagingRuntime, packagingNotice, isolatePackagingEnvironment };
