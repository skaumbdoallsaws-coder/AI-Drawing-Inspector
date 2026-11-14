'use strict';
// Shared by the outer Node runner and the in-Electron driver. No Electron import.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const ROOTS = Object.freeze({ PARTS_MANUAL_ROOT:'p', OPERATIONS_MANUAL_ROOT:'o',
  SPECIFICATION_SHEET_ROOT:'s', WORK_INSTRUCTION_ROOT:'w', INSPECTION_SHEET_ROOT:'i',
  ASSEMBLY_APPEARANCE_ROOT:'a', PART_APPEARANCE_ROOT:'b' });
const fail = message => Object.assign(new Error(message), { code:'documentation_desktop_refused' });
function local(value) {
  if (typeof value !== 'string' || !path.isAbsolute(value) || value.startsWith('\\\\')) throw fail('An absolute local path is required');
  const result = path.resolve(value);
  for (let p=result;;p=path.dirname(p)) {
    if (fs.existsSync(p) && fs.lstatSync(p).isSymbolicLink()) throw fail('Linked paths are refused');
    if (p===path.dirname(p)) break;
  }
  return result;
}
function inside(value, parent) {
  const relative = path.relative(local(parent), local(value));
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}
function json(file) { return JSON.parse(fs.readFileSync(local(file), 'utf8')); }
function snapshot(root) {
  root=local(root);
  if (fs.existsSync(path.join(root,'.git')) || !fs.existsSync(path.join(root,'desktop-checkpoint.json')))
    throw fail('Never launch this renderer from a live checkout; use prepare-snapshot.py');
  const marker=json(path.join(root,'desktop-checkpoint.json'));
  if (marker.schemaVersion!==1 || !marker.source || inside(root,marker.source) || inside(marker.source,root)
      || !fs.existsSync(path.join(root,'desktop-source-manifest.json'))) throw fail('Incomplete or overlapping snapshot');
  if ([root,path.dirname(root)].some(p=>fs.existsSync(path.join(p,'.env')))) throw fail('Snapshot dotenv lookup sites must be absent');
  return root;
}
function validateRun({ root, electron, python, profileFile, output }) {
  root=snapshot(root); profileFile=local(profileFile); output=local(output);
  for (const file of [local(electron),local(python),profileFile]) if (!fs.statSync(file).isFile()) throw fail('A supplied executable or profile is not a file');
  const profile=json(profileFile);
  if (profile.mode!=='application' || !/^de-native-[a-f0-9]{8}$/.test(profile.profileId || '')
      || Object.keys(profile).some(k=>!['schemaVersion','mode','profileId','origin','backendId','storeId','startupLayoutId','dataRoot','facilityRoot','libraryRoot'].includes(k)))
    throw fail('Only the disposable documentation application profile is allowed');
  const markerFile=local(path.join(local(profile.dataRoot),'documentation-editor-check.json'));
  if (!fs.existsSync(markerFile)) throw fail('Profile is not marked disposable');
  const marker=json(markerFile);
  if (marker.disposable!==true || marker.schemaVersion!==1 || marker.profileId!==profile.profileId
      || marker.storeId!==profile.storeId || local(marker.codeRoot)!==root) throw fail('Profile is not marked disposable for this snapshot');
  const base=local(marker.output);
  if (!inside(base,path.join(root,'.runtime')) || base===path.join(root,'.runtime') || local(path.join(base,'e'))!==output
      || local(path.join(base,'profile.json'))!==profileFile) throw fail('Evidence/profile is outside its disposable output folder');
  const expected={dataRoot:path.join(base,'d'),facilityRoot:path.join(base,'d','f'),libraryRoot:path.join(base,'d','l')};
  for (const [key,value] of Object.entries(expected)) if (local(profile[key])!==value || !inside(profile[key],base)) throw fail('Store outside disposable output folder');
  if (Object.keys(marker.stores || {}).sort().join()!==Object.keys(ROOTS).sort().join()) throw fail('Document stores are incomplete');
  for (const [key,short] of Object.entries(ROOTS)) if (local(marker.stores[key])!==path.join(base,'d',short)) throw fail('Store outside disposable output folder');
  const url=new URL(profile.origin);
  if (url.origin!==profile.origin || url.protocol!=='http:' || url.hostname!=='127.0.0.1'
      || +url.port<1024 || +url.port===8480 || url.username || url.password) throw fail('Only a private free loopback port is allowed; never 8480');
  if (!Array.isArray(marker.dependencies)) throw fail('Dependency folder list is required');
  for (const folder of marker.dependencies) if (!fs.statSync(local(folder)).isDirectory() || inside(folder,base)) throw fail('Invalid dependency folder');
  for (const item of marker.inputs || []) {
    const file=local(item.destination);
    if (!inside(file,root) || /(?:^|[\\/])(?:\.env[^\\/]*|ui-data)(?:[\\/]|$)/i.test(file)) throw fail('Invalid fixture destination');
    if (!item.seed && sha(fs.readFileSync(file))!==item.sha256) throw fail('Prepared fixture input changed: '+item.source);
  }
  return {root,profileFile,output,base,profile,marker,electron:local(electron),python:local(python)};
}
function environment(config, source=process.env) {
  // Deliberate allowlist: do not inherit provider keys, proxies, user profiles,
  // NODE_OPTIONS or a user's PYTHONPATH. Application runtime forwards these roots.
  const env={};
  for (const key of ['SystemRoot','WINDIR','COMSPEC','PATHEXT','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE']) {
    const found=Object.keys(source).find(k=>k.toLowerCase()===key.toLowerCase()); if (found) env[key]=source[found];
  }
  const os=path.join(config.base,'os'), tmp=path.join(config.base,'tmp');
  // Windows resolves its roaming and local folders as %USERPROFILE%\AppData\Roaming and ...\Local. Electron
  // stops at start-up (0x80000003, before the application's own userData path is set) when the stand-in
  // profile has no AppData\Roaming, so the stand-in keeps the standard layout.
  const roaming=path.join(os,'AppData','Roaming'), localData=path.join(os,'AppData','Local');
  for (const dir of [os,tmp,roaming,localData]) fs.mkdirSync(dir,{recursive:true});
  Object.assign(env,{USERPROFILE:os,HOME:os,APPDATA:roaming,LOCALAPPDATA:localData,TEMP:tmp,TMP:tmp,
    PATH:[path.dirname(config.python),path.join(env.SystemRoot || 'C:\\Windows','System32')].join(path.delimiter),
    PYTHONPATH:config.marker.dependencies.join(path.delimiter),PYTHONNOUSERSITE:'1',PYTHONDONTWRITEBYTECODE:'1',
    PYTHONUNBUFFERED:'1',PYTHONIOENCODING:'utf-8',INSPECTORPRO_DOCUMENTATION_RICH_TEXT:'1',
    INSPECTORPRO_METRICS_DB:path.join(config.profile.dataRoot,'metrics.sqlite'),
    INSPECTORPRO_MEMORY_DB_PATH:path.join(config.profile.dataRoot,'memory.sqlite'),INSPECTORPRO_MEMORY_V1_MODE:'off'});
  for (const [key,value] of Object.entries(config.marker.stores)) env['INSPECTORPRO_'+key]=value;
  return env;
}
function sha(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
function canonical(value) {
  if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  if (value && typeof value==='object') return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value);
}
function newReport(config, stage) {
  return {schemaVersion:1,phase:'P5b-1',stage,status:'running',startedAt:new Date().toISOString(),
    applicationMode:true,profileId:config.profile.profileId,origin:config.profile.origin,
    codeRoot:config.root,evidence:config.output,python:config.python,dependencyFolders:config.marker.dependencies,
    checks:[],notRun:[],requests:[],windowOpens:[],blockedNavigations:[],consoleErrors:[],failedRequests:[],artifacts:[],screenshots:[]};
}
function check(report,name,passed,detail={}) {
  if (report.checks.some(c=>c.name===name)) throw new Error('Duplicate check: '+name);
  report.checks.push({name,passed:passed===true,detail}); return passed===true;
}
function finish(report) { report.status=report.checks.some(c=>!c.passed)?'failed':'passed'; report.finishedAt=new Date().toISOString(); return report; }
function writeReport(file,value) { fs.writeFileSync(file,JSON.stringify(value,null,2)+'\n','utf8'); }
function diskScene(config,kind) {
  const key=kind==='illustrated_parts_manual'?'PARTS_MANUAL_ROOT':'OPERATIONS_MANUAL_ROOT';
  const file=local(path.join(config.marker.stores[key],'mmle-50d','documentation-scene.json'));
  if (!fs.existsSync(file)) return {file,exists:false,sha256:null,canonicalSha256:null,revision:null,scene:null};
  const bytes=fs.readFileSync(file), scene=JSON.parse(bytes);
  return {file,exists:true,sha256:sha(bytes),canonicalSha256:sha(canonical(scene)),revision:scene.editRevision,scene};
}
function optionalRequest(item) {
  const p=new URL(item.url).pathname;
  return item.method==='GET' && ((item.status===404 && /^\/api\/(?:drawing-map|drawing-pdf|part-features)\/[^/]+$/.test(p))
    || (item.status===404 && /^\/api\/training\/(?:process-map|process-map-for-assembly)\/[^/]+$/.test(p))
    || (item.status===500 && /^\/api\/reference-views\/[^/]+$/.test(p)));
}
module.exports={ROOTS,local,inside,json,snapshot,validateRun,environment,sha,canonical,newReport,check,finish,writeReport,diskScene,optionalRequest};
