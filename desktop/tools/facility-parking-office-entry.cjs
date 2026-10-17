'use strict';
// Native rendering acceptance against an isolated store, never the live layout.
const {app} = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile);
const current = 'window._trainFacilityLayoutAuthoringApp';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const assetIds = ['asset-import-car-93','asset-import-tesla-roadster','asset-import-cubicle','asset-chair-black'];

async function verify(window) {
  const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
  assert.equal(profile.profileId, 'factory02-parking-office');
  const targetPath = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts/fl-independent-factory-20260928.json');
  const before = await fs.readFile(targetPath);
  const report = {status:'running',candidateHash:sha(before),captures:{}};
  const persist = () => fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
  const stage = async name => {report.stage=name;await persist();};
  const js = code => window.webContents.executeJavaScript(code,true);
  async function until(code,timeout=180000) {
    const end=Date.now()+timeout;
    while(Date.now()<end) {if(await js(code))return;await pause(250);}
    throw Error('Timed out: '+code);
  }
  async function camera(position,target) {
    await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position=${JSON.stringify(position)};v.target=${JSON.stringify(target)};v.up={x:0,y:1,z:0};v.fov=45;v.near=.01;v.far=2000;a.applyCameraView(v);})()`);
    await pause(500);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0`);
  }
  async function resize(width,height) {
    if(window.isMaximized())window.unmaximize();
    await pause(300);
    window.setSize(width,height);
    await pause(500);
    const actual=window.getSize();
    // Windows fractional display scaling can round the native bounds by 1 DIP.
    assert.ok(Math.abs(actual[0]-width)<=1 && Math.abs(actual[1]-height)<=1,
      `Unexpected window size: ${actual}; requested ${width},${height}`);
  }
  async function capture(name,canvas=true) {
    await js('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
    await pause(800);
    const image=await window.webContents.capturePage();
    assert.equal(image.isEmpty(),false);
    await fs.writeFile(path.join(output,name+'.png'),image.toPNG());
    report.captures[name]={size:image.getSize(),windowSize:window.getSize()};
    if(canvas) {
      const rect=await js(`(()=>{const r=${current}.workspace.threeAdapter.getRecordingCanvas().getBoundingClientRect();return{x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)};})()`);
      const bitmap=(await window.webContents.capturePage(rect)).toBitmap(),colors=new Set();
      for(let i=0;i+4<=bitmap.length;i+=116)colors.add(bitmap.readUInt32LE(i));
      assert.ok(colors.size>40,'Unexpectedly blank 3D canvas');
      report.captures[name].canvasColors=colors.size;
    }
    await persist();
  }
  try {
    await stage('waiting-for-workspace');
    await resize(1440,900);
    await until(`${current}?.session?.getState().loaded`);
    const actual=await js(`${current}.session.getState().layout`);
    assert.deepEqual(actual,JSON.parse(before));
    assert.equal(actual.placements.length,940);
    assert.equal(actual.extensions.facilityNavigation.movementPrograms.length,40);
    const added=actual.placements.filter(p=>p.placementId.startsWith('pl-parking-office-'));
    report.counts={cars:added.filter(p=>assetIds.slice(0,2).includes(p.assetId)).length,
      cubicles:added.filter(p=>p.assetId===assetIds[2]).length,
      chairs:added.filter(p=>p.assetId===assetIds[3]).length};
    assert.deepEqual(report.counts,{cars:20,cubicles:10,chairs:10});
    assert.equal(await js(`${current}.session.getState().dirty`),false);
    await js(`${current}.workspace._setViewMode('plan')`);
    await capture('00-plan',false);
    await stage('loading-3d');
    await js(`${current}.workspace._setViewMode('3d')`);
    await until(`!!${current}.workspace.threeAdapter`);
    await until(`${current}.workspace.lastThreeFitFingerprint===${current}.workspace.lastLayoutFingerprint`);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0 && ${current}.workspace.threeAdapter.getDiagnostics().assetGroupCount>0`);
    // Initial asset setup can schedule a fit after the adapter first appears.
    // Set the inspection camera after it settles, as the cafeteria harness does.
    await pause(1000);
    await stage('positioning-overview');
    await camera({x:367,y:49,z:-24},{x:334,y:0,z:19});
    await pause(1000);
    await camera({x:367,y:49,z:-24},{x:334,y:0,z:19});
    await until(`(()=>{const d=${current}.workspace.threeAdapter.getDiagnostics();return d.pendingLoads===0&&${JSON.stringify(assetIds)}.every(id=>d.representationGroups.some(g=>g.assetId===id&&['overview','detail'].includes(g.representation)));})()`);
    report.diagnostics=await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
    assert.equal(report.diagnostics.degraded,false);
    assert.equal(report.diagnostics.placementTransformAudit.transformMismatchCount,0);
    await capture('01-extension-overview');
    await stage('capturing-parking-and-office');
    await camera({x:367,y:24,z:0},{x:348,y:0,z:18});
    await capture('02-parking');
    await camera({x:328,y:20,z:3},{x:313.5,y:.7,z:19.2});
    await capture('03-office');
    await camera({x:323.5,y:2,z:19},{x:304,y:1,z:19});
    await capture('04-office-eye-level');
    await js(`${current}.workspace.threeAdapter.topView({minimum:{x:300,y:0,z:4},maximum:{x:375,y:6,z:31}})`);
    await capture('05-top');
    await stage('checking-wall-visibility');
    report.visibleWalls=report.diagnostics.visibleLegacyWallPlacementCount;
    assert.equal(report.visibleWalls,13);
    await js(`(()=>{const w=${current}.workspace;w._setLayerPanelOpen(true);const b=w.layerPanel.querySelector('[data-facility-layer="walls"]');if(b.checked)b.click();w._setLayerPanelOpen(false);})()`);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().visibleLegacyWallPlacementCount===0`);
    await capture('06-walls-hidden');
    await js(`(()=>{const w=${current}.workspace;w._setLayerPanelOpen(true);const b=w.layerPanel.querySelector('[data-facility-layer="walls"]');if(!b.checked)b.click();w._setLayerPanelOpen(false);})()`);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().visibleLegacyWallPlacementCount===13`);
    await resize(900,700);
    await camera({x:375,y:60,z:-38},{x:334,y:0,z:19});
    await capture('07-narrow');
    assert.deepEqual(await js(`${current}.session.getState().layout`),actual);
    assert.equal(await js(`${current}.session.getState().dirty`),false);
    assert.equal(sha(await fs.readFile(targetPath)),report.candidateHash);
    report.savedDocumentUnchanged=true;
    report.status='passed';
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
