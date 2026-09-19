'use strict';
// Dedicated acceptance entry point. Normal desktop main/preload never import it.
// Synchronous writes preserve the last JavaScript checkpoint if native startup exits abruptly.
const fsSync=require('node:fs');
fsSync.writeSync(1,'INSPECTORPRO_FACILITY_NATIVE_SCRIPT_ENTERED\n');
const nativeStarted=process.hrtime.bigint();
const nativeProgress={schemaVersion:1,revision:'facility-native-progress-v1',pid:process.pid,phase:null,elapsedMs:0,checkpoints:[]};
let nativeProgressPath=null;
function checkpoint(phase){
  const elapsedMs=Number((process.hrtime.bigint()-nativeStarted)/1000000n);
  const entry={sequence:nativeProgress.checkpoints.length+1,phase,elapsedMs};
  nativeProgress.phase=phase;nativeProgress.elapsedMs=elapsedMs;nativeProgress.checkpoints.push(entry);
  fsSync.writeSync(1,'INSPECTORPRO_FACILITY_NATIVE_CHECKPOINT '+JSON.stringify({pid:process.pid,...entry})+'\n');
  if(nativeProgressPath){
    const descriptor=fsSync.openSync(nativeProgressPath,'w');
    try{fsSync.writeFileSync(descriptor,JSON.stringify(nativeProgress,null,2));fsSync.fsyncSync(descriptor);}
    finally{fsSync.closeSync(descriptor);}
  }
}
checkpoint('script-entered');
const {app,BrowserWindow,ipcMain,session,screen}=require('electron');
const fs=require('node:fs/promises');
const path=require('node:path');
const {createFacilityRecoveryAdapter}=require('../src/facility-recovery-adapter.cjs');
const {runScenarios,until}=require('./facility-recovery-scenarios.cjs');
checkpoint('modules-loaded');
let win,config,adapter,currentOperation=null,committed=false,lastClose=null;
const observed=[];
function error(code,message=code){return Object.assign(new Error(message),{code});}
async function evalPage(expression){
  if(!win||win.isDestroyed())throw error('renderer_unavailable');
  return win.webContents.executeJavaScript(expression,true);
}
const invoke=(name,arg)=>evalPage(`window.__facilityHarness[${JSON.stringify(name)}](${arg===undefined?'':JSON.stringify(arg)})`);
async function main(){
  if(process.env.INSPECTORPRO_FACILITY_RECOVERY_HARNESS!=='1')throw error('isolated_harness_required');
  const configPath=process.argv.find(value=>/facility-check-phase-[12]\.json$/.test(value));
  if(!configPath)throw error('harness_config_missing');
  config=JSON.parse(await fs.readFile(configPath,'utf8'));
  if(!path.isAbsolute(config.dataRoot)||!path.isAbsolute(config.output)||!/^http:\/\/127\.0\.0\.1:\d+$/.test(config.origin))throw error('harness_config_invalid');
  nativeProgressPath=path.join(config.output,'progress.json');checkpoint('config-loaded');
  const marker=JSON.parse(await fs.readFile(path.join(config.dataRoot,'facility-recovery-fixture.json'),'utf8'));
  if(marker.identity.origin!==config.origin||marker.fixtureRoot!==config.dataRoot)throw error('harness_fixture_mismatch');
  const token=(await fs.readFile(config.tokenFile,'utf8')).trim();
  const stateRoot=path.join(config.dataRoot,'electron-test-profile');await fs.mkdir(stateRoot,{recursive:true});app.setPath('userData',stateRoot);
  const request=async(endpoint,body)=>{
    const response=await fetch(config.origin+endpoint,{method:body===undefined?'GET':'POST',headers:{'X-InspectorPro-Recovery-Test':token,...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const result=await response.json();if(!response.ok)throw error(result.error?.code||'backend_error',result.error?.message||'Backend request failed');return result;
  };
  const binding=await request('/__facility-recovery__/identity');
  await app.whenReady();
  checkpoint('app-ready');
  const browserSession=session.fromPartition('persist:isolated-facility-recovery');
  browserSession.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));browserSession.setPermissionCheckHandler(()=>false);
  browserSession.on('will-download',event=>event.preventDefault());
  browserSession.webRequest.onBeforeRequest((details,callback)=>{
    const allowed=details.url.startsWith(config.origin+'/')||details.url.startsWith('blob:'+config.origin+'/')||details.url.startsWith('data:');
    callback({cancel:!allowed});
  });
  browserSession.webRequest.onBeforeSendHeaders((details,callback)=>{
    const headers={...details.requestHeaders};
    if(win&&!win.isDestroyed()&&details.webContentsId===win.webContents.id&&details.url.startsWith(config.origin+'/')){
      headers['X-InspectorPro-Recovery-Test']=token;
      if(currentOperation)headers['X-InspectorPro-Recovery-Request']=currentOperation.requestId;
    }
    callback({requestHeaders:headers});
  });
  const workArea=screen.getPrimaryDisplay().workArea;
  win=new BrowserWindow({width:Math.min(1440,workArea.width),height:Math.min(960,workArea.height),show:false,
    webPreferences:{session:browserSession,preload:path.join(__dirname,'facility-recovery-preload.cjs'),sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true,allowRunningInsecureContent:false,
      additionalArguments:['--isolated-facility-recovery-harness']}});
  checkpoint('window-created');
  win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  win.webContents.on('will-navigate',(event,url)=>{if(url!==config.origin+'/__facility-recovery__/page')event.preventDefault();});
  win.webContents.on('will-attach-webview',event=>event.preventDefault());
  win.on('close',event=>{
    if(committed)return;
    event.preventDefault();
    if(adapter)lastClose=adapter.prepare('close');
  });
  function validSender(event){
    if(!win||win.isDestroyed()||event.sender!==win.webContents||event.senderFrame!==win.webContents.mainFrame||event.senderFrame.url!==config.origin+'/__facility-recovery__/page')throw error('harness_sender_rejected');
    if(!adapter)throw error('harness_adapter_unavailable');
  }
  ipcMain.handle('facility-test:persist',async(event,record)=>{validSender(event);const receipt=await adapter.persistOperation(record);currentOperation={requestId:record.requestId};return receipt;});
  ipcMain.handle('facility-test:clear',async(event,record)=>{validSender(event);return adapter.clearOperation(record);});
  win.webContents.on('render-process-gone',(_event,details)=>observed.push({event:'render-process-gone',...details}));
  win.webContents.on('did-fail-load',(_event,code,description)=>observed.push({event:'did-fail-load',code,description}));
  win.webContents.on('console-message',(_event,details)=>{if(details?.level==='error')observed.push({event:'console-error',message:details.message});});
  const firstPaint=new Promise(resolve=>win.once('ready-to-show',resolve));
  checkpoint('page-load-start');
  await win.loadURL(config.origin+'/__facility-recovery__/page');
  checkpoint('page-load-complete');
  await until(async()=>{
    const state=await evalPage('window.__facilityHarness && ({ready:window.__facilityHarness.ready,error:window.__facilityHarness.error})');
    if(state?.error)throw new Error(state.error.message);return state?.ready;
  },'Facility app did not initialize',60000);
  checkpoint('facility-ready');
  const editor={};for(const name of ['snapshot','freeze','unfreeze','restoreRecovery','acceptReconciliation','setStartupRecoveryGate'])editor[name]=arg=>invoke(name,arg);
  adapter=await createFacilityRecoveryAdapter({authorizedIsolatedHarness:true,...binding,editor,recoveryDirectory:path.join(config.dataRoot,'desktop-recovery'),
    lookupOperation:value=>request('/__facility-recovery__/transaction',value),commitLifecycle:async()=>{committed=true;win.destroy();},timeoutMs:15000,lookupTimeoutMs:15000});
  const capabilities=await evalPage('window.FacilityRecoveryTest.capabilities()');
  const preferences=win.webContents.getLastWebPreferences();
  const rendererWorld=await evalPage('({requireType:typeof require,processType:typeof process})');
  if(preferences.sandbox!==true||preferences.contextIsolation!==true||preferences.nodeIntegration!==false||preferences.webSecurity!==true||capabilities.researchBrowsing!==false
    ||rendererWorld.requireType!=='undefined'||rendererWorld.processType!=='undefined')throw error('harness_isolation_failed');
  const isolation={sandbox:preferences.sandbox,contextIsolation:preferences.contextIsolation,nodeIntegration:preferences.nodeIntegration,webSecurity:preferences.webSecurity,rendererWorld};
  const capture=async name=>{
    await Promise.race([firstPaint,new Promise((_resolve,reject)=>setTimeout(()=>reject(error('first_paint_timeout')),15000))]);
    await evalPage('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
    const image=await win.webContents.capturePage();if(image.isEmpty())throw error('empty_capture');await fs.writeFile(path.join(config.output,name),image.toPNG());
  };
  const driver={mode:'real-native-renderer-real-backend-two-process-harness',binding,adapter,request,snapshot:()=>invoke('snapshot'),
    prepareClose:async()=>{lastClose=null;win.close();return until(()=>lastClose,'Native close event was not handled');},isClosed:()=>win.isDestroyed(),
    editLabel:(id,label)=>evalPage(`(async()=>{const s=window.__facilityHarness.session;s.select(${JSON.stringify(id)});await s.editZoneLabel(${JSON.stringify(id)},${JSON.stringify(label)});})()`),
    begin:(kind,reference)=>invoke(kind==='apply'?'beginApply':'beginUndo',reference),paused:()=>evalPage('window.__facilityHarness.paused'),
    release:()=>invoke('release'),settled:()=>invoke('settled'),operationError:()=>evalPage('window.__facilityHarness.operationError'),
    assertSessionSaveBlocked:async()=>{const result=await evalPage('(async()=>{const h=window.__facilityHarness,b=h.app.workspace.toolbar.querySelector("[data-command=save]"),ui={canSave:h.session.getState().canSave,saveButtonPresent:!!b,saveButtonDisabled:!!b&&b.disabled};try{await h.session.save();return {...ui,allowed:true};}catch(e){return {...ui,allowed:false,code:e.code,message:e.message};}})()');if(result.allowed||result.canSave!==false||!result.saveButtonPresent||!result.saveButtonDisabled||!/busy|recovery|frozen|unresolved/i.test(result.message))throw error('session_save_gate_failed');return {...result,uiChecked:true};},
    checkAssets:async()=>{
      const required=marker.assets.map(asset=>asset.assetId),cardEvidence=[];
      const reportPath=path.join(config.output,'facility-asset-evidence.json');
      const saveEvidence=async(stage,evidence)=>fs.writeFile(reportPath,JSON.stringify({revision:'facility-assets-v1',stage,evidence,cards:cardEvidence},null,2));
      const normalizedPath=url=>new URL(url,config.origin).pathname;
      await evalPage("window.__facilityHarness.app.workspace._setViewMode('3d')");
      const priorSelection=await evalPage('window.__facilityHarness.app.workspace.threeAdapter.getDiagnostics().selectedPlacementIds');
      try {
        await until(async()=>{
          const evidence=await invoke('assetEvidence'),d=evidence.diagnostics;
          if(evidence.errors.length||d.degraded||d.contextLost)throw error('facility_asset_renderer_failed',JSON.stringify({errors:evidence.errors,status:d.status,warnings:d.warnings}));
          return d.mounted&&!d.suspended&&d.status==='ready'&&d.pendingLoads===0&&d.assetGroupCount===required.length;
        },'Actual Three adapter did not finish the initial facility scene',120000);
        // The normal large-layout loader defers heavy visual groups. Selecting
        // one real instance of each asset asks that same loader to resolve them.
        await evalPage(`(()=>{const h=window.__facilityHarness,seen=new Set(),ids=[];for(const p of h.session.getState().layout.placements){const key=p.assetId+'|'+p.assetDefinitionRevision;if(!seen.has(key)){seen.add(key);ids.push(p.placementId);}}h.app.workspace.threeAdapter.setSelection(ids);return ids.length;})()`);
        await until(async()=>{
          const evidence=await invoke('assetEvidence'),d=evidence.diagnostics;
          if(evidence.errors.length||d.degraded||d.contextLost||d.loadTrace.some(item=>item.status==='failed')
             ||d.warnings.some(item=>item.code==='asset_revision_mismatch'))throw error('facility_asset_renderer_failed',JSON.stringify({errors:evidence.errors,status:d.status,warnings:d.warnings}));
          const loaded=new Set(evidence.loadedGlbs.filter(v=>v.meshes>0).map(v=>normalizedPath(v.url)));
          const real=d.representationGroups.filter(g=>['overview','detail'].includes(g.representation)&&g.meshCount>0&&g.prototypeMeshCount>0);
          const represented=new Set(real.flatMap(g=>g.placementIds));
          return d.status==='ready'&&d.pendingLoads===0&&d.rendering.deferredGroupCount===0
            &&evidence.placementIds.length===marker.layout.counts.placements&&d.placementCount===evidence.placementIds.length
            &&evidence.placementIds.every(id=>represented.has(id))&&represented.size===evidence.placementIds.length
            &&required.every(id=>real.some(g=>g.assetId===id)&&d.loadTrace.some(t=>t.assetId===id&&['overview','detail'].includes(t.stage)&&t.status==='resolved'))
            &&marker.assets.every(asset=>loaded.has(normalizedPath(asset.route)))
            &&d.placementTransformAudit.status==='match'&&d.placementTransformAudit.auditedPlacementCount===evidence.placementIds.length;
        },'All referenced GLBs must be installed as real scene meshes with matching placement transforms',120000);
        await evalPage(`(()=>{const a=window.__facilityHarness.app.workspace.threeAdapter;a.setSelection(${JSON.stringify(priorSelection)});a.fitLayout();})()`);
        await capture('facility-real-glbs.png');
        const evidence=await invoke('assetEvidence');
        await saveEvidence('real-scene-verified',evidence);
        const opened=await evalPage('window.__facilityHarness.app.workspace.openAssetBrowser()');
        if(!opened)throw error('asset_library_open_failed');
        const cards=await evalPage(`(()=>{const w=window.__facilityHarness.app.workspace;return {open:w.assetBrowserState.open,hidden:w.assetBrowser.hidden,ids:[...w.assetGrid.querySelectorAll(':scope > article.ip-flw-asset-card[data-asset-id]')].map(c=>c.dataset.assetId)};})()`);
        if(!cards.open||cards.hidden||cards.ids.some(id=>typeof id!=='string'||!id.trim())
          ||new Set(cards.ids).size!==cards.ids.length||!required.every(id=>cards.ids.includes(id)))throw error('asset_library_dom_cards_missing');
        for(const asset of marker.assets){
          await evalPage(`(()=>{const w=window.__facilityHarness.app.workspace;const c=[...w.assetGrid.children].find(c=>c.dataset.assetId===${JSON.stringify(asset.assetId)});if(!c)throw new Error('Asset card missing');c.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});})()`);
          const card=await until(async()=>{
            const measured=await evalPage(`(()=>{const w=window.__facilityHarness.app.workspace,c=[...w.assetGrid.children].find(c=>c.dataset.assetId===${JSON.stringify(asset.assetId)}),g=w.assetGrid,b=w.assetBrowser;
              const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
              const within=(a,p)=>a.width>0&&a.height>0&&a.x>=p.x-1&&a.y>=p.y-1&&a.x+a.width<=p.x+p.width+1&&a.y+a.height<=p.y+p.height+1;
              const shown=e=>{const s=getComputedStyle(e);return e.isConnected&&!e.hidden&&s.display!=='none'&&s.visibility==='visible'&&Number(s.opacity)>0;};
              const viewport={x:0,y:0,width:innerWidth,height:innerHeight},grid=rect(g),bounds=rect(c),title=c.querySelector('.ip-flw-asset-card-copy strong'),image=c.querySelector('img');
              grid.x+=g.clientLeft;grid.y+=g.clientTop;grid.width=g.clientWidth;grid.height=g.clientHeight;
              const range=document.createRange();range.selectNodeContents(title);const labels=[...range.getClientRects()].map(r=>({x:r.x,y:r.y,width:r.width,height:r.height}));
              const center={x:bounds.x+bounds.width/2,y:bounds.y+bounds.height/2},hit=document.elementFromPoint(center.x,center.y);
              return {assetId:c.dataset.assetId,revision:c.dataset.assetRevision,label:title.textContent.trim(),bounds,grid,viewport,labelBounds:labels,
                visible:w.assetBrowserState.open&&shown(b)&&shown(g)&&shown(c)&&within(bounds,viewport)&&within(bounds,grid)&&labels.length>0&&labels.every(r=>within(r,bounds)&&within(r,grid))&&Boolean(hit&&(hit===c||c.contains(hit))),
                thumbnail:image?{url:image.currentSrc||image.src,loaded:image.complete&&image.naturalWidth>0&&image.naturalHeight>0,width:image.naturalWidth,height:image.naturalHeight}:null};})()`);
            return measured.visible&&measured.label&&measured.thumbnail?.loaded&&normalizedPath(measured.thumbnail.url)===normalizedPath(asset.thumbnailRoute)?measured:null;
          },'Actual asset card/label/thumbnail did not become visible: '+asset.assetId,15000);
          cardEvidence.push(card);
        }
        await evalPage('window.__facilityHarness.app.workspace.assetGrid.scrollTo({top:0,behavior:"instant"})');
        await capture('facility-asset-library.png');
        const result={...evidence,library:{open:true,actualDomCardCount:cards.ids.length,referencedAssetTypesVisible:cardEvidence.length,
          visibilityMethod:'Each actual card scrolled into the library viewport; bounds, labels, hit-test and loaded local thumbnail verified.',cards:cardEvidence},
          isolation};
        await saveEvidence('scene-and-visible-library-verified',result);
        return result;
      }catch(failure){
        await saveEvidence('failed',await invoke('assetEvidence').catch(()=>null)).catch(()=>{});
        throw failure;
      }finally{
        await evalPage(`(()=>{const w=window.__facilityHarness.app.workspace;w.threeAdapter.setSelection(${JSON.stringify(priorSelection)});if(w.assetBrowserState.open)w.closeAssetBrowser(false);})()`).catch(()=>{});
      }
    },
  };
  checkpoint('scenarios-start');
  const report=await runScenarios(driver,config);
  checkpoint('scenarios-complete');
  await fs.writeFile(path.join(config.output,'native-evidence.json'),JSON.stringify({capabilities,isolation,events:observed,progress:nativeProgress,processExitPurpose:report.exitPurpose||'Lifecycle commit closed the test window'},null,2));
  return report;
}
app.on('window-all-closed',()=>{});
main().then(report=>{process.stdout.write(JSON.stringify({status:report.status,phase:report.phase,checks:report.checks})+'\n');app.exit(0);}).catch(async failure=>{
  try{checkpoint('failed');}catch(diagnosticError){nativeProgress.diagnosticError=diagnosticError.code||'checkpoint_write_failed';}
  if(config?.output)await fs.writeFile(path.join(config.output,'native-failure.json'),JSON.stringify({status:'failed',code:failure.code,message:failure.message,stack:failure.stack,events:observed,progress:nativeProgress},null,2)).catch(()=>{});
  process.stderr.write((failure.stack||failure.message)+'\n');app.exit(1);
});
