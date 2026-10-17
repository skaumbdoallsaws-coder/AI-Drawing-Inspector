'use strict';
// Isolated native acceptance. Never opens or saves the user's live editor session.
const {app}=require('electron');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const profileFile=process.argv[process.argv.indexOf('--profile-file')+1],output=path.dirname(profileFile);
const current='window._trainFacilityLayoutAuthoringApp',pause=ms=>new Promise(r=>setTimeout(r,ms));
const sha=b=>createHash('sha256').update(b).digest('hex');

async function verify(window){
 const profile=JSON.parse(await fs.readFile(profileFile,'utf8'));assert.equal(profile.profileId,'factory02-truck-yard');
 const target=path.join(profile.facilityRoot,'layouts/local/site-local/layouts/fl-independent-factory-20260928.json');
 const before=await fs.readFile(target),expected=JSON.parse(before);
 const report={status:'running',candidateHash:sha(before),captures:{}};
 const persist=()=>fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
 const js=code=>window.webContents.executeJavaScript(code,true);
 const stage=async name=>{report.stage=name;await persist();};
 async function until(code,timeout=180000){const end=Date.now()+timeout;while(Date.now()<end){if(await js(code))return;await pause(250);}throw Error('Timed out '+code);}
 async function camera(position,target){await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position=${JSON.stringify(position)};v.target=${JSON.stringify(target)};v.up={x:0,y:1,z:0};v.fov=45;v.near=.03;v.far=2000;a.applyCameraView(v);})()`);await pause(600);await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0`);}
 async function capture(name,canvas=true){
  await js('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');await pause(600);
  const image=await window.webContents.capturePage();assert.ok(!image.isEmpty());await fs.writeFile(path.join(output,name+'.png'),image.toPNG());
  report.captures[name]={size:image.getSize()};
  if(canvas){const rect=await js(`(()=>{const r=${current}.workspace.threeAdapter.getRecordingCanvas().getBoundingClientRect();return{x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)}})()`);
   const pixels=(await window.webContents.capturePage(rect)).toBitmap(),colors=new Set();for(let i=0;i+4<=pixels.length;i+=116)colors.add(pixels.readUInt32LE(i));assert.ok(colors.size>40,'Blank canvas');report.captures[name].colors=colors.size;}
  await persist();
 }
 async function walk(from,to){
  await js(`${current}.workspace.threeAdapter.exitWalkthrough('test')`);
  const start=await js(`${current}.workspace.threeAdapter.enterWalkthrough({worldPoint:${JSON.stringify(from)},ignoreSelection:true,cameraMode:'third-person'})`);
  assert.equal(start.active,true);assert.ok(Math.abs(start.position.y-from.y)<1e-5);
  await js(`${current}.workspace.threeAdapter.setWalkthroughCameraMode('third-person')`);
  const route=await js(`${current}.workspace.threeAdapter.navigateWalkthroughToPoint(${JSON.stringify(to)})`);assert.ok(route.ok,JSON.stringify(route));
  await until(`!${current}.workspace.threeAdapter.getWalkthroughState().route.active`,60000);
  const end=await js(`${current}.workspace.threeAdapter.getWalkthroughState()`);
  assert.ok(Math.hypot(end.position.x-to.x,end.position.z-to.z)<.1,JSON.stringify(end));
  assert.ok(Math.abs(end.position.y-to.y)<.01,JSON.stringify(end));return {start,end};
 }
 try{
  await stage('workspace');if(window.isMaximized())window.unmaximize();window.setSize(1440,900);
  await until(`${current}?.session?.getState().loaded`);
  assert.deepEqual(await js(`${current}.session.getState().layout`),expected);
  assert.equal(expected.placements.filter(p=>p.placementId.startsWith('pl-yard-truck-')).length,6);
  assert.equal(expected.placements.filter(p=>p.placementId.startsWith('pl-yard-waiting-')).length,4);
  assert.equal(expected.extensions.facilityNavigation.movementPrograms.length,40);
  await js(`${current}.workspace._setViewMode('plan')`);await capture('00-plan',false);
  report.planProjection=await js(`(()=>{const a=${current}.workspace.topAdapter,p=a.worldToClient({x:-40,y:-1.35,z:100});return a.clientToWorld({clientX:p.x,clientY:p.y})})()`);
  assert.ok(Math.abs(report.planProjection.y+1.35)<1e-5);
  await stage('3d');await js(`${current}.workspace._setViewMode('3d')`);
  await until(`!!${current}.workspace.lastLayoutFingerprint&&${current}.workspace.lastThreeFitFingerprint===${current}.workspace.lastLayoutFingerprint`);
  await camera({x:-132,y:114,z:235},{x:-6,y:0,z:100});
  await until(`(()=>{const d=${current}.workspace.threeAdapter.getDiagnostics();return d.pendingLoads===0&&['asset-truck-40ft-container-straight','asset-truck-20ft-container'].every(id=>d.representationGroups.some(g=>g.assetId===id&&['overview','detail'].includes(g.representation)))})()`);
  report.diagnostics=await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
  assert.equal(report.diagnostics.degraded,false);assert.equal(report.diagnostics.placementTransformAudit.transformMismatchCount,0);assert.equal(report.diagnostics.placementTransformAudit.missingPlacementCount,0);
  await capture('01-yard-overview');
  await camera({x:-43,y:26,z:93},{x:-3,y:0,z:151});await capture('02-receiving');
  await camera({x:-43,y:26,z:94},{x:-3,y:0,z:40});await capture('03-shipping');
  await camera({x:-9,y:6,z:9},{x:-2,y:0,z:20});await capture('04-dock-height');
  await camera({x:-33,y:8,z:113},{x:-4,y:0,z:98});await capture('05-central-ramp');
  await stage('walk-ramp');
  report.walkUp=await walk({x:-25,y:-1.35,z:98},{x:2,y:0,z:98});await capture('06-walk-factory');
  report.walkDown=await walk({x:2,y:0,z:98},{x:-25,y:-1.35,z:98});await capture('07-walk-yard');
  await js(`${current}.workspace.threeAdapter.exitWalkthrough('test')`);
  // Dock-edge route must stop at the drop even though its 2D line is unobstructed.
  await js(`${current}.workspace.threeAdapter.enterWalkthrough({worldPoint:{x:2,z:104,y:0},ignoreSelection:true})`);
  await js(`${current}.workspace.threeAdapter.navigateWalkthroughToPoint({x:-2,z:104})`);
  await until(`!${current}.workspace.threeAdapter.getWalkthroughState().route.active`,15000);
  report.edge=await js(`${current}.workspace.threeAdapter.getWalkthroughState()`);assert.ok(report.edge.position.x>=-.01);assert.equal(report.edge.position.y,0);
  await js(`${current}.workspace.threeAdapter.exitWalkthrough('test')`);
  await stage('walls-and-narrow');
  await js(`(()=>{const w=${current}.workspace;w._setLayerPanelOpen(true);const b=w.layerPanel.querySelector('[data-facility-layer="walls"]');if(b.checked)b.click();w._setLayerPanelOpen(false)})()`);
  assert.equal(await js(`${current}.workspace.threeAdapter.getDiagnostics().visibleLegacyWallPlacementCount`),0);
  window.setSize(900,700);await camera({x:-115,y:115,z:224},{x:-12,y:0,z:102});await capture('08-narrow-walls-off');
  assert.deepEqual(await js(`${current}.session.getState().layout`),expected);assert.equal(await js(`${current}.session.getState().dirty`),false);assert.equal(sha(await fs.readFile(target)),report.candidateHash);
  report.savedDocumentUnchanged=true;report.status='passed';
 }catch(error){report.status='failed';report.error=error.stack;report.failureDiagnostics=await js(`${current}?.workspace?.threeAdapter?.getDiagnostics()`).catch(()=>null);await capture('failure',false).catch(()=>{});}
 finally{await persist();app.quit();}
}
app.once('browser-window-created',(_event,window)=>window.webContents.once('dom-ready',()=>void verify(window).catch(async error=>{await fs.writeFile(path.join(output,'driver-error.json'),JSON.stringify({error:error.stack}));app.quit();})));
require('../src/entry.cjs');
