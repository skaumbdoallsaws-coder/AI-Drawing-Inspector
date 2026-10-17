'use strict';
// Native read-only acceptance of an isolated lunchroom candidate.
const {app}=require('electron');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const profileFile=process.argv[process.argv.indexOf('--profile-file')+1];
const output=path.dirname(profileFile);
const openKitchen=process.argv.includes('--open-kitchen');
process.argv=process.argv.filter(value=>value!=='--open-kitchen');
const expectedLegacyWalls=openKitchen?20:19;
const current='window._trainFacilityLayoutAuthoringApp';
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const assetIds=['asset-5589t51-round-plastic-folding-table','asset-chair-black','asset-kitchen-assembly',
  'asset-green-garbage-container','asset-user-library-sink-1'];

async function verify(window) {
  const profile=JSON.parse(await fs.readFile(profileFile,'utf8'));
  assert.equal(profile.profileId,'factory02-lunchroom');
  const target=path.join(profile.facilityRoot,'layouts/local/site-local/layouts/fl-independent-factory-20260928.json');
  const before=await fs.readFile(target);
  const report={status:'running',candidateHash:sha(before),captures:{}};
  const persist=()=>fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
  const stage=async name=>{report.stage=name;await persist();};
  const js=code=>window.webContents.executeJavaScript(code,true);
  async function until(code,timeout=180000) {
    const end=Date.now()+timeout;
    while(Date.now()<end){if(await js(code))return;await pause(250);}
    throw Error('Timed out: '+code);
  }
  async function resize(width,height) {
    if(window.isMaximized())window.unmaximize();
    await pause(300);window.setSize(width,height);await pause(500);
    const actual=window.getSize();
    assert.ok(Math.abs(actual[0]-width)<=1&&Math.abs(actual[1]-height)<=1,
      'Unexpected window bounds: '+actual);
  }
  async function camera(position,target) {
    await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position=${JSON.stringify(position)};v.target=${JSON.stringify(target)};v.up={x:0,y:1,z:0};v.fov=45;v.near=.05;v.far=2000;a.applyCameraView(v);})()`);
    await pause(500);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0`);
  }
  async function capture(name,canvas=true) {
    await js('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
    await pause(800);
    const image=await window.webContents.capturePage();assert.equal(image.isEmpty(),false);
    await fs.writeFile(path.join(output,name+'.png'),image.toPNG());
    report.captures[name]={size:image.getSize(),windowSize:window.getSize()};
    if(canvas) {
      const rect=await js(`(()=>{const r=${current}.workspace.threeAdapter.getRecordingCanvas().getBoundingClientRect();return{x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)};})()`);
      const bitmap=(await window.webContents.capturePage(rect)).toBitmap(),colors=new Set();
      for(let i=0;i+4<=bitmap.length;i+=116)colors.add(bitmap.readUInt32LE(i));
      assert.ok(colors.size>40,'Blank 3D canvas');report.captures[name].canvasColors=colors.size;
    }
    await persist();
  }
  async function walls(visible) {
    await js(`(()=>{const w=${current}.workspace;w._setLayerPanelOpen(true);const b=w.layerPanel.querySelector('[data-facility-layer="walls"]');if(b.checked!==${visible})b.click();w._setLayerPanelOpen(false);})()`);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().visibleLegacyWallPlacementCount===${visible?expectedLegacyWalls:0}`);
  }
  try {
    await stage('waiting-for-workspace');await resize(1440,900);
    await until(`${current}?.session?.getState().loaded`);
    const actual=await js(`${current}.session.getState().layout`);
    assert.deepEqual(actual,JSON.parse(before));assert.equal(actual.placements.length,openKitchen?1050:1049);
    if(openKitchen){
      assert.equal(actual.extensions.facilityPerimeterWalls,undefined);
      assert.equal(actual.placements.filter(p=>p.placementId==='pl-lunchroom-wall-kitchen-back').length,1);
    }
    assert.equal(actual.extensions.facilityNavigation.movementPrograms.length,40);
    const furniture=actual.placements.filter(p=>p.placementId.startsWith('pl-independent-cafeteria-'));
    report.furnitureCounts=assetIds.slice(0,3).map(id=>furniture.filter(p=>p.assetId===id).length);
    assert.deepEqual(report.furnitureCounts,[24,96,1]);
    assert.equal(actual.placements.filter(p=>p.placementId.startsWith('pl-parking-office-cubicle-')).length,10);
    assert.equal(actual.placements.filter(p=>p.placementId.startsWith('pl-parking-office-car-')).length,20);
    assert.equal(await js(`${current}.session.getState().dirty`),false);
    await js(`${current}.workspace._setViewMode('plan')`);
    await capture('00-plan',false);
    await stage('loading-3d');await js(`${current}.workspace._setViewMode('3d')`);
    await until(`!!${current}.workspace.threeAdapter`);
    await until(`!!${current}.workspace.lastLayoutFingerprint&&${current}.workspace.lastThreeFitFingerprint===${current}.workspace.lastLayoutFingerprint`);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0&&${current}.workspace.threeAdapter.getDiagnostics().assetGroupCount>0`);
    await stage('positioning-lunchroom');
    await camera({x:349,y:37,z:17},{x:317,y:0,z:45});
    await until(`(()=>{const d=${current}.workspace.threeAdapter.getDiagnostics();return d.pendingLoads===0&&${JSON.stringify(assetIds)}.every(id=>d.representationGroups.some(g=>g.assetId===id&&['overview','detail'].includes(g.representation)));})()`);
    report.diagnostics=await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
    assert.equal(report.diagnostics.degraded,false);
    assert.equal(report.diagnostics.placementTransformAudit.transformMismatchCount,0);
    assert.equal(report.diagnostics.placementTransformAudit.missingPlacementCount,0);
    assert.equal(report.diagnostics.visibleLegacyWallPlacementCount,expectedLegacyWalls);
    assert.equal(report.diagnostics.visiblePerimeterWallCount,actual.extensions.facilityPerimeterWalls?.panels.length||0);
    await capture('01-lunchroom-overview');
    await stage('capturing-connections');
    await camera({x:374,y:62,z:-1},{x:325,y:0,z:35});
    await capture('02-office-lunchroom-parking');
    await camera({x:313.25,y:2,z:31},{x:313.25,y:1,z:57});
    await capture('03-dining-eye-level');
    await camera({x:321,y:2.0,z:55.3},{x:328.3,y:1,z:55.3});
    await capture('04-kitchen-serving');
    await camera({x:313.25,y:2,z:26.9},{x:313.25,y:1.3,z:34});
    await capture('05-office-entrance');
    await camera({x:297,y:2,z:44.2},{x:308,y:1.2,z:44.2});
    await capture('06-factory-entrance');
    await stage('checking-wall-toggle');await walls(false);
    await js(`${current}.workspace.threeAdapter.topView({minimum:{x:299,y:0,z:27},maximum:{x:335,y:6,z:62}})`);
    await capture('07-top-walls-hidden');await walls(true);
    await resize(900,700);
    await camera({x:351,y:52,z:2},{x:317,y:0,z:45});
    await capture('08-narrow');
    assert.deepEqual(await js(`${current}.session.getState().layout`),actual);
    assert.equal(await js(`${current}.session.getState().dirty`),false);
    assert.equal(sha(await fs.readFile(target)),report.candidateHash);
    report.savedDocumentUnchanged=true;report.status='passed';
  } catch(error) {
    report.status='failed';report.error=error.stack;
    report.failureDiagnostics=await js(`${current}?.workspace?.threeAdapter?.getDiagnostics()`).catch(()=>null);
    report.failureCamera=await js(`${current}?.workspace?.threeAdapter?.getCameraView()`).catch(()=>null);
    await capture('failure',false).catch(()=>{});
  } finally {await persist();app.quit();}
}
app.once('browser-window-created',(_event,window)=>{
  window.webContents.once('dom-ready',()=>void verify(window).catch(async error=>{
    await fs.writeFile(path.join(output,'driver-error.json'),JSON.stringify({error:error.stack}));app.quit();
  }));
});
require('../src/entry.cjs');
