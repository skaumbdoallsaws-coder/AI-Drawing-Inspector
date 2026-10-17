'use strict';
// Preview an exact candidate without editing the session. Reload only once the
// revision-bound repository publication receipt proves the requested wall change.
const { app } = require('electron');
const fs = require('node:fs/promises'), path = require('node:path');
const assert = require('node:assert/strict');
const {createHash}=require('node:crypto');
const profileFile=process.argv[process.argv.indexOf('--profile-file')+1];
const output=path.dirname(profileFile), current='window._trainFacilityLayoutAuthoringApp';
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const sha=b=>createHash('sha256').update(b).digest('hex');

async function review(window) {
  const profile=JSON.parse(await fs.readFile(profileFile,'utf8'));
  const config=await fs.readFile(path.join(output,'review-config.json'),'utf8').then(JSON.parse).catch(error=>{
    if(error.code!=='ENOENT')throw error;
    return {profileId:'private-gym-art-review',shots:[
      {name:'01-reception-front',position:{x:7.5,y:2.1,z:8.5},target:{x:6,y:1.65,z:.38}},
      {name:'02-reception-context',position:{x:11,y:3.7,z:9},target:{x:6,y:1.5,z:.38}}
    ],finalShot:{name:'03-saved-reception',position:{x:7.5,y:2.1,z:8.5},target:{x:6,y:1.65,z:.38}}};
  });
  assert.equal(profile.profileId,config.profileId);
  const raw=await fs.readFile(path.join(output,'candidate.json'));
  const candidate=JSON.parse(raw),before=JSON.parse(await fs.readFile(path.join(output,'before.json'),'utf8'));
  const report={status:'running',candidateHash:sha(raw),captures:{}};
  window.webContents.session.webRequest.onErrorOccurred(details=>{
    const errors=report.networkErrors||(report.networkErrors=[]);
    if(errors.length<100) errors.push({path:new URL(details.url).pathname,error:details.error});
  });
  const persist=()=>fs.writeFile(path.join(output,'native-check.json'),JSON.stringify(report,null,2));
  const js=code=>window.webContents.executeJavaScript(code,true);
  async function until(code,timeout=180000) {
    const end=Date.now()+timeout;
    while(Date.now()<end){if(await js(code))return;await pause(250);}
    throw Error('Timeout: '+code);
  }
  async function camera(position,target) {
    await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();Object.assign(v,{position:${JSON.stringify(position)},target:${JSON.stringify(target)},up:{x:0,y:1,z:0},near:.15,far:300});if(${Number.isFinite(config.cameraFov)})v.fov=${Number(config.cameraFov)||45};a.applyCameraView(v);})()`);
    await pause(800);await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0`);
  }
  async function artworkReady() {
    await until(`(()=>{const d=${current}.workspace.threeAdapter.getDiagnostics();return d.pendingLoads===0&&${JSON.stringify(config.requiredAssets||[])}.every(id=>d.representationGroups.some(g=>g.assetId===id&&['overview','detail'].includes(g.representation)&&g.sourcePrototypeMeshCount>=${Number(config.minimumAssetMeshes||2)}));})()`);
    await pause(1200);
    await until(`(()=>{const d=${current}.workspace.threeAdapter.getDiagnostics();return ${JSON.stringify(config.requiredWallArt||[])}.every(id=>(d.exteriorArtwork||[]).some(a=>a.artworkId===id&&a.status==='ready'));})()`);
    if (config.requiredEmbeddedLights) {
      await until(`(()=>{const d=${current}.workspace.threeAdapter.getDiagnostics();return d.representationGroups.filter(g=>${JSON.stringify(config.requiredAssets||[])}.includes(g.assetId)).reduce((n,g)=>n+(g.renderedLightCount||0),0)===${Number(config.requiredEmbeddedLights)};})()`);
    }
  }
  async function capture(name,thresholds={red:500,yellow:500,blue:500}) {
    await pause(800);const shot=await window.webContents.capturePage();
    await fs.writeFile(path.join(output,name+'.png'),shot.toPNG());
    const rect=await js(`(()=>{const r=${current}.workspace.threeAdapter.getRecordingCanvas().getBoundingClientRect();return{x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)}})()`);
    const pixels=(await window.webContents.capturePage(rect)).toBitmap();let red=0,yellow=0,blue=0,dark=0;
    const detail=new Set();
    for(let i=0;i<pixels.length;i+=4){const b=pixels[i],g=pixels[i+1],r=pixels[i+2];if(r>120&&r>g*1.4&&r>b*1.4)red++;if(r>140&&g>100&&b<g*.65)yellow++;if(b>120&&b>r*1.4&&g>b*.4)blue++;if(r<70&&g<70&&b<70)dark++;detail.add((r<<16)|(g<<8)|b);}
    const counts={red,yellow,blue,dark,detail:detail.size};
    for(const [key,min] of Object.entries(thresholds))assert.ok(counts[key]>min,`${name}: missing ${key} pixels`);
    report.captures[name]=counts;await persist();
  }
  try {
    window.maximize();window.show();window.webContents.setBackgroundThrottling(false);await persist();
    await until(`${current}?.session?.getState().loaded`);
    assert.deepEqual(await js(`${current}.session.getState().layout`),config.verifySavedOnly ? candidate : before);
    assert.equal(await js(`${current}.session.getState().dirty`),false);
    await js(`${current}.workspace._setViewMode('3d')`);
    await until(`!!${current}.workspace.threeAdapter`);
    if (!config.verifySavedOnly) await js(`window.__gymArtCandidate=${JSON.stringify(candidate)};${current}.workspace.threeAdapter.setScene({layout:window.__gymArtCandidate,assetCatalog:${current}.workspace.assetCatalog.map(r=>r.source||r),selectedIds:[]})`);
    // Visibility-dependent CAD loading needs the review camera before readiness.
    if (config.shots.length) await camera(config.shots[0].position,config.shots[0].target);
    await artworkReady();
    for(const shot of config.shots){await camera(shot.position,shot.target);await capture(shot.name,shot.thresholds);}
    if(config.fittedArtworkProbe) {
      const probe=config.fittedArtworkProbe;
      const baseline=await js(`${current}.workspace.threeAdapter.getDiagnostics().exteriorArtwork`);
      await js(`(()=>{const layout=JSON.parse(JSON.stringify(window.__gymArtCandidate));
        layout.extensions.facilityPerimeterWalls.settings.heightMeters*=1.2;
        const wall=layout.placements.find(p=>p.placementId===${JSON.stringify(probe.placementId)});
        wall.transform.scale*=1.2;wall.transform.position.x+=.25;
        ${current}.workspace.threeAdapter.setScene({layout,assetCatalog:${current}.workspace.assetCatalog.map(r=>r.source||r),selectedIds:[]});})()`);
      await artworkReady();
      const resized=await js(`${current}.workspace.threeAdapter.getDiagnostics().exteriorArtwork`);
      for(const id of [probe.placedArtworkId,probe.perimeterArtworkId]) {
        const a=baseline.find(a=>a.artworkId===id),b=resized.find(a=>a.artworkId===id);
        assert.ok(Math.abs(b.worldHeight/a.worldHeight-1.2)<1e-6,'Artwork did not refit resized wall: '+id);
      }
      const a=baseline.find(a=>a.artworkId===probe.placedArtworkId),b=resized.find(a=>a.artworkId===probe.placedArtworkId);
      assert.ok(b.worldPosition.x>a.worldPosition.x+.2,'Artwork did not follow wall translation');
      assert.ok(Math.abs(b.worldWidth/a.worldWidth-1.2)<1e-6,'Artwork did not follow wall width');
      await js(`${current}.workspace.threeAdapter.setScene({layout:window.__gymArtCandidate,assetCatalog:${current}.workspace.assetCatalog.map(r=>r.source||r),selectedIds:[]})`);
      await artworkReady();
      const restored=await js(`${current}.workspace.threeAdapter.getDiagnostics().exteriorArtwork`);
      for(const id of [probe.placedArtworkId,probe.perimeterArtworkId]) {
        assert.deepEqual(restored.find(a=>a.artworkId===id),baseline.find(a=>a.artworkId===id));
      }
      report.responsiveArtworkVerified=true;
    }
    assert.deepEqual(await js(`${current}.session.getState().layout`),config.verifySavedOnly ? candidate : before);
    report.diagnostics=await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
    assert.equal(report.diagnostics.degraded,false);
    assert.equal(report.diagnostics.placementTransformAudit.transformMismatchCount,0);
    assert.equal(report.diagnostics.pendingLoads,0);
    for(const id of config.requiredAssets||[])assert.ok(report.diagnostics.representationGroups.some(g=>g.assetId===id),'Missing artwork: '+id);
    report.status='preview-verified';await persist();
    const deadline=Date.now()+30*60*1000;let published=config.verifySavedOnly===true;
    while(!published&&Date.now()<deadline&&!window.isDestroyed()) {
      const saved=await fs.readFile(path.join(output,'report.json'),'utf8').then(JSON.parse);
      if(saved.status==='saved'){published=true;break;}await pause(1000);
    }
    assert.ok(published,'Publication not completed; saved base was not edited by this driver');
    await js(`${current}.session.reload().then(()=>null)`);
    const saved=JSON.parse(await fs.readFile(path.join(output,'saved.json'),'utf8'));
    assert.deepEqual(await js(`${current}.session.getState().layout`),saved);
    assert.equal(await js(`${current}.session.getState().dirty`),false);
    await camera(config.finalShot.position,config.finalShot.target);
    await artworkReady();
    await capture(config.finalShot.name,config.finalShot.thresholds);
    report.savedDiagnostics=await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
    assert.equal(report.savedDiagnostics.degraded,false);
    assert.equal(report.savedDiagnostics.placementTransformAudit.transformMismatchCount,0);
    report.status='saved-and-verified';report.savedReloadMatches=true;
  }catch(error){report.status='failed';report.error=error.stack;
    try {report.failureDiagnostics=await js(`${current}?.workspace?.threeAdapter?.getDiagnostics()`);}catch(_ignored){}
  }
  await persist();
}
app.once('browser-window-created',(_event,window)=>window.webContents.once('did-finish-load',()=>void review(window).catch(async error=>{
  await fs.writeFile(path.join(output,'driver-error.json'),JSON.stringify({error:error.stack}));
})));
require('../src/entry.cjs');
