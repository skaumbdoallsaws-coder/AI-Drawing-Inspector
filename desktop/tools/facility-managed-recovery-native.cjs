'use strict';
const fsSync=require('node:fs');
fsSync.writeSync(1,'INSPECTORPRO_MANAGED_RECOVERY_NATIVE_ENTERED\n');
const {app,BrowserWindow,ipcMain,session,screen}=require('electron');
const fs=require('node:fs/promises');
const path=require('node:path');
const {createFacilityRecoveryAdapter}=require('../src/facility-recovery-adapter.cjs');
const {createCheckpointDiagnosticSink}=require('./recovery-checkpoint-diagnostics.cjs');
const {runManagedScenarios,atomicJson}=require('./facility-managed-recovery-scenarios.cjs');
const {until}=require('./facility-recovery-scenarios.cjs');
const {editLabelInRenderer}=require('./facility-managed-setup.cjs');
let win,config,adapter,operation=null,backendAccess=true;
const events=[];
const error=(code,message=code)=>Object.assign(new Error(message),{code});
const evaluate=expression=>{if(!win||win.isDestroyed())throw error('renderer_unavailable');return win.webContents.executeJavaScript(expression,true);};
const invoke=(name,value)=>evaluate(`window.__facilityHarness[${JSON.stringify(name)}](${value===undefined?'':JSON.stringify(value)})`);
async function main(){
  if(process.env.INSPECTORPRO_FACILITY_RECOVERY_HARNESS!=='1'||process.env.INSPECTORPRO_FACILITY_MANAGED_RESTART_HARNESS!=='1')throw error('isolated_managed_harness_required');
  const configPath=process.argv.find(value=>/facility-managed-check\.json$/.test(value));
  if(!configPath)throw error('harness_config_missing');
  config=JSON.parse(await fs.readFile(configPath,'utf8'));
  if(!path.isAbsolute(config.dataRoot)||!path.isAbsolute(config.output)||!path.isAbsolute(config.controlDirectory)||!/^http:\/\/127\.0\.0\.1:\d+$/.test(config.origin))throw error('harness_config_invalid');
  const marker=JSON.parse(await fs.readFile(path.join(config.dataRoot,'facility-recovery-fixture.json'),'utf8'));
  if(marker.identity.origin!==config.origin||marker.fixtureRoot!==config.dataRoot)throw error('harness_fixture_mismatch');
  const token=(await fs.readFile(config.tokenFile,'utf8')).trim();
  const userData=path.join(config.dataRoot,'managed-electron-profile');await fs.mkdir(userData,{recursive:true});app.setPath('userData',userData);
  const request=async(endpoint,body)=>{
    const response=await fetch(config.origin+endpoint,{redirect:'error',method:body===undefined?'GET':'POST',headers:{'X-InspectorPro-Recovery-Test':token,...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const result=await response.json();if(!response.ok)throw error(result.error?.code||'backend_error',result.error?.message||'Backend request failed');return result;
  };
  const binding=await request('/__facility-recovery__/identity');
  await app.whenReady();
  const browser=session.fromPartition('persist:isolated-managed-facility-recovery');
  browser.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));browser.setPermissionCheckHandler(()=>false);
  browser.on('will-download',event=>event.preventDefault());
  browser.webRequest.onBeforeRequest((details,callback)=>{
    const local=details.url.startsWith(config.origin+'/');
    callback({cancel:!((local&&backendAccess)||details.url.startsWith('blob:'+config.origin+'/')||details.url.startsWith('data:'))});
  });
  browser.webRequest.onBeforeSendHeaders((details,callback)=>{
    const headers={...details.requestHeaders};
    if(backendAccess&&win&&!win.isDestroyed()&&details.webContentsId===win.webContents.id&&details.url.startsWith(config.origin+'/')){
      headers['X-InspectorPro-Recovery-Test']=token;
      if(operation)headers['X-InspectorPro-Recovery-Request']=operation.requestId;
    }else{delete headers['X-InspectorPro-Recovery-Test'];delete headers['X-InspectorPro-Recovery-Request'];}
    callback({requestHeaders:headers});
  });
  const area=screen.getPrimaryDisplay().workArea;
  win=new BrowserWindow({width:Math.min(1440,area.width),height:Math.min(960,area.height),show:false,
    webPreferences:{session:browser,preload:path.join(__dirname,'facility-managed-recovery-preload.cjs'),sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true,allowRunningInsecureContent:false,additionalArguments:['--isolated-facility-managed-recovery-harness']}});
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',(event,url)=>{if(url!==config.origin+'/__facility-recovery__/page')event.preventDefault();});
  win.webContents.on('will-attach-webview',event=>event.preventDefault());
  win.on('close',event=>event.preventDefault());
  win.webContents.on('render-process-gone',(_event,detail)=>events.push({event:'render-process-gone',...detail}));
  function sender(event){if(!win||win.isDestroyed()||event.sender!==win.webContents||event.senderFrame!==win.webContents.mainFrame||event.senderFrame.url!==config.origin+'/__facility-recovery__/page'||!adapter)throw error('harness_sender_rejected');}
  ipcMain.handle('facility-managed-test:persist',async(event,record)=>{sender(event);const receipt=await adapter.persistOperation(record);operation={requestId:record.requestId};return receipt;});
  ipcMain.handle('facility-managed-test:clear',async(event,record)=>{sender(event);return adapter.clearOperation(record);});
  const paint=new Promise(resolve=>win.once('ready-to-show',resolve));
  await win.loadURL(config.origin+'/__facility-recovery__/page');
  await until(async()=>{const value=await evaluate('window.__facilityHarness&&({ready:window.__facilityHarness.ready,error:window.__facilityHarness.error})');if(value?.error)throw new Error(value.error.message);return value?.ready;},'Facility editor failed to initialize',60000);
  const editor={};for(const name of ['snapshot','freeze','unfreeze','restoreRecovery','acceptReconciliation','setStartupRecoveryGate'])editor[name]=value=>invoke(name,value);
  const lookups=[];let driver;
  adapter=await createFacilityRecoveryAdapter({authorizedIsolatedHarness:true,...binding,editor,recoveryDirectory:path.join(config.dataRoot,'desktop-recovery'),
    onRecoveryDiagnostic:createCheckpointDiagnosticSink(config.output),
    lookupOperation:async value=>{const clientSaveGate=await driver.assertSessionSaveBlocked();const result=await request('/__facility-recovery__/transaction',value);lookups.push({...result,clientSaveGate});if(['lease_expired','ownership_conflict'].includes(result.status))throw error(result.status,'Explicit recovery required: '+result.status);return result;},
    commitLifecycle:async()=>{throw error('managed_restart_must_retain_renderer');},timeoutMs:15000,lookupTimeoutMs:15000});
  const preferences=win.webContents.getLastWebPreferences();
  const world=await evaluate('({requireType:typeof require,processType:typeof process})');
  if(preferences.sandbox!==true||preferences.contextIsolation!==true||preferences.nodeIntegration!==false||preferences.webSecurity!==true||world.requireType!=='undefined'||world.processType!=='undefined')throw error('native_isolation_failed');
  const rendererPid=win.webContents.getOSProcessId();
  driver={mode:'native',binding,adapter,editor,lookups,request,snapshot:()=>invoke('snapshot'),setBackendAccess:allowed=>{backendAccess=allowed;},
    editLabel:(id,label)=>editLabelInRenderer(evaluate,id,label),
    begin:async(kind,reference,beforeAcknowledgement=false)=>{await invoke('configureManagedHold',{beforeAcknowledgement});return invoke(kind==='apply'?'beginApply':'beginUndo',reference);},
    paused:()=>evaluate('window.__facilityHarness.paused'),release:()=>invoke('release'),dropHeldAcknowledgement:()=>invoke('dropHeldAcknowledgement'),settled:()=>invoke('settled'),operationError:()=>evaluate('window.__facilityHarness.operationError'),
    assertSessionSaveBlocked:async()=>{const result=await evaluate('(async()=>{const h=window.__facilityHarness,b=h.app.workspace.toolbar.querySelector("[data-command=save]"),ui={canSave:h.session.getState().canSave,saveButtonPresent:!!b,saveButtonDisabled:!!b&&b.disabled};try{await h.session.save();return {...ui,allowed:true};}catch(e){return {...ui,allowed:false,code:e.code,message:e.message};}})()');if(result.allowed||result.canSave!==false||!result.saveButtonPresent||!result.saveButtonDisabled||!/busy|recovery|frozen|unresolved/i.test(result.message))throw error('session_save_gate_failed');return {...result,uiChecked:true};},
    showRecoveryOutcome:result=>{
      const message=result.status==='reconciled'?'Managed backend recovered. Draft, selection, and Undo history retained. Transaction reconciled without replay.'
        :'Recovery required: '+(result.code||'backend unavailable')+'. Draft, selection, Undo history, and recovery handle retained. Save remains blocked. Ownership and transaction state must be resolved before editing resumes.';
      return evaluate(`(()=>{let panel=document.getElementById('managed-recovery-status');if(!panel){panel=document.createElement('section');panel.id='managed-recovery-status';panel.setAttribute('role','status');panel.style.cssText='padding:12px 16px;background:#fff1cc;color:#302513;font:14px system-ui;flex:none';document.body.insertBefore(panel,document.getElementById('facility'));}panel.textContent=${JSON.stringify(message)};return panel.textContent;})()`);
    },
    captureEvidence:async()=>{
      if(win.webContents.getOSProcessId()!==rendererPid)throw error('renderer_process_changed');
      await Promise.race([paint,new Promise((_resolve,reject)=>setTimeout(()=>reject(error('first_paint_timeout')),15000))]);
      await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
      const capture=await win.webContents.capturePage();if(capture.isEmpty())throw error('empty_capture');
      await fs.writeFile(path.join(config.output,'managed-recovery.png'),capture.toPNG());
      const evidence={isolation:{sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true,rendererWorld:world},rendererPidBefore:rendererPid,rendererPidAfter:win.webContents.getOSProcessId(),events,backendAccess,screenshot:'managed-recovery.png'};
      await atomicJson(path.join(config.output,'native-evidence.json'),evidence);return evidence;
    },
  };
  return runManagedScenarios(driver,config);
}
main().then(async report=>{fsSync.writeSync(1,JSON.stringify({status:report.status,case:report.case,checks:report.checks})+'\n');if(win&&!win.isDestroyed())win.destroy();app.exit(0);})
  .catch(error=>{fsSync.writeSync(2,(error.stack||error.message)+'\n');if(win&&!win.isDestroyed())win.destroy();app.exit(1);});
