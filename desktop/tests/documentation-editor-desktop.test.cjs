'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {randomUUID}=require('node:crypto');
const C=require('../tools/documentation-editor-contract.cjs');
const {reportShape,REQUIRED}=require('../../tests/smoke_documentation_editor_desktop.cjs');
function fixture(t) {
  const base=fs.mkdtempSync(path.join(os.tmpdir(),'de-native-'));
  t.after(()=>fs.rmSync(base,{recursive:true,force:true}));
  const root=path.join(base,'snapshot'), source=path.join(base,'source');fs.mkdirSync(root);fs.mkdirSync(source);
  C.writeReport(path.join(root,'desktop-checkpoint.json'),{schemaVersion:1,source});
  C.writeReport(path.join(root,'desktop-source-manifest.json'),[]);
  const output=path.join(root,'.runtime','gate');fs.mkdirSync(output,{recursive:true});
  const profile={schemaVersion:1,mode:'application',profileId:'de-native-0123abcd',origin:'http://127.0.0.1:49151',
    backendId:randomUUID(),storeId:randomUUID(),startupLayoutId:null,dataRoot:path.join(output,'d'),
    facilityRoot:path.join(output,'d','f'),libraryRoot:path.join(output,'d','l')};
  const stores=Object.fromEntries(Object.entries(C.ROOTS).map(([k,v])=>[k,path.join(output,'d',v)]));
  for(const dir of [...Object.values(stores),profile.dataRoot,profile.facilityRoot,profile.libraryRoot,path.join(output,'e')])fs.mkdirSync(dir,{recursive:true});
  const marker={schemaVersion:1,disposable:true,codeRoot:root,output,profileId:profile.profileId,storeId:profile.storeId,stores,dependencies:[],inputs:[]};
  const file=path.join(output,'profile.json'), flag=path.join(profile.dataRoot,'documentation-editor-check.json');
  const electron=path.join(base,'electron.exe'),python=path.join(base,'python.exe');fs.writeFileSync(electron,'');fs.writeFileSync(python,'');
  const save=()=>{C.writeReport(file,profile);C.writeReport(flag,marker);};save();
  return {base,root,source,output,profile,marker,file,flag,electron,python,save,args:{root,electron,python,profileFile:file,output:path.join(output,'e')}};
}
test('runner imports without Electron and accepts only its marked snapshot stores',t=>{
  const f=fixture(t), config=C.validateRun(f.args);assert.equal(config.profile.mode,'application');assert.equal(config.base,f.output);
  assert.ok(!Object.keys(require.cache).some(key=>key.endsWith('native-entry.cjs')));
});
for(const mutate of [f=>{f.marker.disposable=false;},f=>{delete f.marker.disposable;},f=>{f.marker.storeId=randomUUID();},f=>{f.profile.profileId='user-profile';}])
  test('unmarked or foreign disposable profile is refused',t=>{const f=fixture(t);mutate(f);f.save();assert.throws(()=>C.validateRun(f.args));});
for(const key of ['dataRoot','facilityRoot','libraryRoot'])test('profile '+key+' cannot leave output',t=>{
  const f=fixture(t);f.profile[key]=f.source;f.save();assert.throws(()=>C.validateRun(f.args));
});
for(const key of Object.keys(C.ROOTS))test('document store '+key+' cannot leave output',t=>{
  const f=fixture(t);f.marker.stores[key]=f.source;f.save();assert.throws(()=>C.validateRun(f.args),/Store outside/);
});
test('live checkout, overlapping snapshot and incomplete snapshot are refused',t=>{
  const f=fixture(t);fs.mkdirSync(path.join(f.root,'.git'));assert.throws(()=>C.validateRun(f.args),/live checkout/);fs.rmdirSync(path.join(f.root,'.git'));
  C.writeReport(path.join(f.root,'desktop-checkpoint.json'),{schemaVersion:1,source:f.root});assert.throws(()=>C.validateRun(f.args),/overlapping/);
  fs.unlinkSync(path.join(f.root,'desktop-checkpoint.json'));assert.throws(()=>C.validateRun(f.args),/live checkout/);
});
test('own desktop port, remote origins, foreign evidence and optional account profiles are refused',t=>{
  const f=fixture(t);
  for(const origin of ['http://127.0.0.1:8480','http://localhost:49151','https://example.com','http://127.0.0.1:49151/path']) {
    f.profile.origin=origin;f.save();assert.throws(()=>C.validateRun(f.args));
  }
  f.profile.origin='http://127.0.0.1:49151';f.save();assert.throws(()=>C.validateRun({...f.args,output:f.source}));
  f.profile.codexRuntime={};f.save();assert.throws(()=>C.validateRun(f.args));
});
test('environment forwards document roots and excludes inherited credentials, proxies and user paths',t=>{
  const f=fixture(t), config=C.validateRun(f.args), env=C.environment(config,{SystemRoot:'C:\\Windows',OPENAI_API_KEY:'test',HTTP_PROXY:'test',NODE_OPTIONS:'test',PYTHONPATH:'foreign',APPDATA:'foreign'});
  assert.equal(env.INSPECTORPRO_DOCUMENTATION_RICH_TEXT,'1');
  for(const [key,value] of Object.entries(f.marker.stores))assert.equal(env['INSPECTORPRO_'+key],value);
  for(const key of ['OPENAI_API_KEY','HTTP_PROXY','NODE_OPTIONS'])assert.equal(env[key],undefined);
  assert.equal(env.PYTHONPATH,'');assert.ok(C.inside(env.APPDATA,f.output));
  // The stand-in profile keeps Windows' standard layout; Electron does not start without AppData\Roaming.
  assert.equal(env.APPDATA,path.join(env.USERPROFILE,'AppData','Roaming'));assert.equal(env.LOCALAPPDATA,path.join(env.USERPROFILE,'AppData','Local'));
  assert.ok(fs.statSync(env.APPDATA).isDirectory() && fs.statSync(env.LOCALAPPDATA).isDirectory());assert.ok(C.inside(env.INSPECTORPRO_METRICS_DB,f.output));
});
test('reports retain failures, omitted steps, raw request evidence and distinct checks',t=>{
  const f=fixture(t), r=C.newReport(C.validateRun(f.args),'edit');
  r.notRun.push({step:'e_source_conflict',reason:'No production test route'});r.requests.push({url:f.profile.origin+'/api/test',method:'GET',status:200});
  C.check(r,'disk',true,{documentType:'illustrated_parts_manual',pageId:'page-cover',objectId:'obj',revisionBefore:1,revisionAfter:2,persistedState:'scene.json'});
  C.check(r,'dirty_close',false,{outcome:'silently-lost'});C.finish(r);
  assert.equal(r.status,'failed');assert.equal(reportShape(r,'edit'),true);assert.throws(()=>C.check(r,'disk',true));
  assert.equal(reportShape({...r,checks:[]},'edit'),false);assert.equal(reportShape({...r,status:'running'},'edit'),false);
  assert.ok(REQUIRED.restart.includes('dirty_close'));assert.ok(REQUIRED.export.includes('customer-docx'));
});
test('disk evidence compares canonical state and retains the exact stored bytes',t=>{
  const f=fixture(t), config=C.validateRun(f.args);assert.equal(C.diskScene(config,'illustrated_parts_manual').exists,false);
  const dir=path.join(f.marker.stores.PARTS_MANUAL_ROOT,'mmle-50d');fs.mkdirSync(dir);
  const text='{"pages":{},"editRevision":2,"commands":[]}\n';fs.writeFileSync(path.join(dir,'documentation-scene.json'),text);
  const saved=C.diskScene(config,'illustrated_parts_manual');assert.equal(saved.sha256,C.sha(text));assert.equal(saved.revision,2);
  assert.equal(saved.canonicalSha256,C.sha(C.canonical({commands:[],editRevision:2,pages:{}})));
});
test('optional failures are narrowly scoped GETs from the browser fixture',()=>{
  assert.equal(C.optionalRequest({url:'http://127.0.0.1:1234/api/drawing-map/MMLE-50D',status:404,method:'GET'}),true);
  assert.equal(C.optionalRequest({url:'http://127.0.0.1:1234/api/drawing-map/MMLE-50D',status:404,method:'POST'}),false);
  assert.equal(C.optionalRequest({url:'http://127.0.0.1:1234/api/operations-manual/MMLE-50D/pdf',status:500,method:'POST'}),false);
});

test('existing application runtime forwards the isolated roots and selected dependency folders',t=>{
  const f=fixture(t), config=C.validateRun(f.args);
  const inherited=C.environment(config), backend=require('../src/runtime-supervisor.cjs').childEnvironment(config.profile,config.python,inherited);
  for(const key of Object.keys(C.ROOTS))assert.equal(backend['INSPECTORPRO_'+key],inherited['INSPECTORPRO_'+key]);
  for(const key of ['PYTHONPATH','PYTHONNOUSERSITE','INSPECTORPRO_DOCUMENTATION_RICH_TEXT','INSPECTORPRO_METRICS_DB','INSPECTORPRO_MEMORY_DB_PATH'])assert.equal(backend[key],inherited[key]);
});
test('the driver keeps native policies, observed dialogs and folded ribbon routing',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../tools/documentation-editor-native-entry.cjs'),'utf8');
  assert.ok(source.includes("require('../src/application-main.cjs')"));
  assert.ok(source.includes('e._documentationSource===document.querySelector('));
  assert.ok(source.includes("originalDialog.apply(this,args)"));
  assert.ok(source.includes("await change('close')"));
  // Dialogs are answered by a press on a named button, armed per scenario, and the runner checks who answered.
  assert.ok(source.includes("'press-dialog'"));assert.ok(!source.includes('cancel-dialog'));
  assert.ok(source.includes("armedDialog=answer;await change('close')"));
  const runner=fs.readFileSync(path.join(__dirname,'../../tests/smoke_documentation_editor_desktop.cjs'),'utf8');
  assert.ok(runner.includes("'native_dialogs_answered_by_helper'"));
  assert.ok(!source.includes('setWindowOpenHandler('));assert.ok(!source.includes('setPermissionRequestHandler('));
  assert.ok(!source.includes('webRequest.onBeforeRequest('));assert.ok(!source.includes('editor.commands.'));
});
