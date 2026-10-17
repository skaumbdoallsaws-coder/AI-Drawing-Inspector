'use strict';
// Author through normal session gestures. Detail review Save requires a separate,
// candidate-bound approval file after the native and human visual checks.
const { app } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile);
const current = 'window._trainFacilityLayoutAuthoringApp';
const pause = ms => new Promise(r => setTimeout(r, ms));
const digest = b => createHash('sha256').update(b).digest('hex');

async function review(window) {
  const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
  assert.ok(['private-gym-review','private-gym-detail-review'].includes(profile.profileId));
  const detail = profile.profileId === 'private-gym-detail-review';
  const candidate = JSON.parse(await fs.readFile(path.join(output, 'candidate.json'), 'utf8'));
  const operations = JSON.parse(await fs.readFile(path.join(output, 'operations.json'), 'utf8'));
  const layoutDir = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts');
  const hashes = async () => {
    const result = {};
    for (const name of await fs.readdir(layoutDir)) if (name.endsWith('.json')) {
      result[name] = digest(await fs.readFile(path.join(layoutDir, name)));
    }
    return result;
  };
  const before = await hashes();
  const report = {status:'running', captures:{}, checks:{}, startedAt:new Date().toISOString()};
  const persist = () => fs.writeFile(path.join(output,'native-check.json'),JSON.stringify(report,null,2));
  const stage = async name => {report.stage=name;await persist();};
  const js = code => window.webContents.executeJavaScript(code, true);
  async function until(code, timeout=180000) {
    const end=Date.now()+timeout;
    while(Date.now()<end) {if(await js(code))return;await pause(250);}
    throw Error('Timed out: '+code);
  }
  async function capture(name, canvas=false) {
    await pause(700);
    await fs.writeFile(path.join(output,name+'.png'),(await window.webContents.capturePage()).toPNG());
    if(canvas) {
      const rect=await js(`(()=>{const r=${current}.workspace.threeAdapter.getRecordingCanvas().getBoundingClientRect();return {x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)};})()`);
      const frame=await window.webContents.capturePage(rect),pixels=frame.toBitmap(),colors=new Set();
      for(let i=0;i+4<=pixels.length;i+=388)colors.add(pixels.readUInt32LE(i));
      assert.ok(colors.size>40,'Blank 3D canvas');
      report.captures[name]={canvasColors:colors.size,size:frame.getSize()};
    } else report.captures[name]={captured:true};
    await persist();
  }
  async function camera(position,target) {
    await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();Object.assign(v,{position:${JSON.stringify(position)},target:${JSON.stringify(target)},up:{x:0,y:1,z:0},fov:45,near:.15,far:500});a.applyCameraView(v);})()`);
    await pause(600);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0`);
  }
  try {
    window.maximize();window.show();window.webContents.setBackgroundThrottling(false);
    await stage('waiting-for-blank-sheet');
    await until(`${current}?.session?.getState().loaded`);
    assert.equal(await js(`${current}.session.getState().layout.layoutId`),candidate.layoutId);
    assert.equal(await js(`${current}.session.getState().layout.placements.length`),0);
    await stage('authoring-zones');
    const zones=candidate.zones.map(z=>({...z,minX:Math.min(...z.boundary.map(p=>p.x)),minZ:Math.min(...z.boundary.map(p=>p.z)),
      width:Math.max(...z.boundary.map(p=>p.x))-Math.min(...z.boundary.map(p=>p.x)),depth:Math.max(...z.boundary.map(p=>p.z))-Math.min(...z.boundary.map(p=>p.z))}));
    await js(`${current}.session.createZones(${JSON.stringify(zones)}).then(()=>null)`);
    await stage('authoring-equipment');
    const requests=candidate.placements.map(p=>({...p,position:p.transform.position,quaternion:p.transform.quaternion,scale:1}));
    await js(`${current}.session.placeAssets(${JSON.stringify(requests)}).then(()=>null)`);
    await js(`(async()=>{const s=${current}.session;s.selectMany(s.getState().layout.placements.filter(p=>p.metadata.gymRole==='architecture').map(p=>p.placementId));await s.setSelectedAppearance('#d8e2df');s.clearSelection();})()`);
    if(detail) await js(`(async()=>{const s=${current}.session;s.selectMany(s.getState().layout.placements.filter(p=>p.metadata.gymRole==='floor-mat').map(p=>p.placementId));await s.setSelectedAppearance('#397e7f');s.clearSelection();})()`);
    await stage('authoring-finishes-and-routes');
    for(const op of operations) {
      if(op.op==='add_floor_marking')await js(`${current}.session.createFloorMarking(${JSON.stringify(op.floorMarking)}).then(()=>null)`);
      if(op.op==='add_aisle')await js(`${current}.session.createAisle(${JSON.stringify(op.aisle)}).then(()=>null)`);
      if(op.op==='set_perimeter_walls')await js(`${current}.session.setPerimeterWalls(${JSON.stringify(op.wallSettings)}).then(()=>null)`);
    }
    const actual=await js(`${current}.session.getState().layout`);
    const normalize=placements=>placements.map(({placementId,...p})=>p).sort((a,b)=>a.metadata.instanceLabel.localeCompare(b.metadata.instanceLabel));
    assert.deepEqual(normalize(actual.placements),normalize(candidate.placements));
    assert.equal(actual.zones.length,candidate.zones.length);
    assert.equal(actual.routes.length,candidate.routes.length);
    assert.equal(await js(`${current}.session.getState().dirty`),true);
    await fs.writeFile(path.join(output,'desktop-draft.json'),JSON.stringify(actual,null,2));
    await fs.writeFile(path.join(output,'desktop-operations.json'),JSON.stringify(await js(`${current}.session.getOperations()`),null,2));
    await stage('checking-undo-redo');
    await js(`${current}.session.undo().then(()=>null)`);
    assert.equal(await js(`!!${current}.session.getState().layout.extensions.facilityPerimeterWalls`),false);
    await js(`${current}.session.redo().then(()=>null)`);
    assert.deepEqual(await js(`${current}.session.getState().layout`),actual);
    report.checks.undoRedo=true;
    await js(`${current}.workspace._setViewMode('plan');${current}.workspace.executeCommand('fit-layout');_setLeftPanelContent('structure',{reveal:true})`);
    await capture('01-plan');
    await stage('loading-real-cad');
    const loadStart=Date.now();
    await js(`${current}.workspace._setViewMode('3d')`);
    await until(`!!${current}.workspace.threeAdapter`);
    await camera({x:71,y:64,z:77},{x:30,y:0,z:15});
    report.coldLoadMs=Date.now()-loadStart;
    await capture('02-overview',true);
    for(const [name,position,target] of [
      ['03-cardio',{x:29,y:6,z:13},{x:24,y:.7,z:4}],
      ['04-strength',{x:16,y:8,z:11},{x:8,y:1,z:23}],
      ['05-cables',{x:42,y:7,z:12},{x:36,y:1,z:22}],
      ['06-functional',{x:54,y:7,z:13},{x:45,y:.5,z:5}],
      ['07-reception',{x:11,y:5,z:10},{x:5,y:1,z:3}],
    ]) {await stage(name);await camera(position,target);await capture(name,true);}
    if(detail) {
      await camera({x:51,y:7,z:19},{x:55,y:.7,z:26});await capture('09-changing',true);
      await camera({x:50,y:5,z:10},{x:57,y:.7,z:4});await capture('10-staff',true);
      await camera({x:47,y:2.2,z:11},{x:42.3,y:0,z:7.55});await capture('11-mat',true);
    }
    await stage('checking-walkthrough');
    const starts=[{x:11.2,z:9},{x:21.8,z:18},{x:36.4,z:24},{x:45.8,z:24},{x:37,z:7}];
    report.walkthrough=[];
    for(const point of starts) {
      const state=await js(`${current}.workspace.threeAdapter.enterWalkthrough({ignoreSelection:true,worldPoint:${JSON.stringify(point)}})`);
      assert.equal(state.active,true);
      assert.ok(Math.hypot(state.position.x-point.x,state.position.z-point.z)<.1,'Unexpected spawn displacement');
      report.walkthrough.push(state);
      await js(`${current}.workspace.threeAdapter.exitWalkthrough('review')`);
    }
    if(detail) {
      await stage('walking-member-route');report.continuousWalk=[];
      await js(`${current}.workspace.threeAdapter.enterWalkthrough({ignoreSelection:true,worldPoint:{x:6,z:1}})`);
      for(const point of [{x:6,z:3.6},{x:11.2,z:3.6},{x:11.7,z:22},{x:21.8,z:24},
                         {x:36.4,z:29},{x:45.8,z:29},{x:57,z:25},{x:56,z:21},
                         {x:58.2,z:8},{x:37,z:7},{x:34.8,z:1}]) {
        const plan=await js(`${current}.workspace.threeAdapter.navigateWalkthroughToPoint(${JSON.stringify(point)})`);
        assert.equal(plan.ok,true,'Walking route refused: '+JSON.stringify({point,reason:plan.reason}));
        const started=Date.now();
        await until(`!${current}.workspace.threeAdapter.getWalkthroughState().route.active`,90000);
        const walked=await js(`${current}.workspace.threeAdapter.getWalkthroughState()`);
        assert.ok(Math.hypot(walked.position.x-point.x,walked.position.z-point.z)<.3,'Walk failed to arrive');
        report.continuousWalk.push({goal:point,position:walked.position,elapsedMs:Date.now()-started,performance:walked.performance});
        await persist();
      }
      await js(`${current}.workspace.threeAdapter.exitWalkthrough('review')`);
    }
    await camera({x:71,y:64,z:77},{x:30,y:0,z:15});
    report.diagnostics=await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
    assert.equal(report.diagnostics.degraded,false);
    assert.equal(report.diagnostics.placementTransformAudit.transformMismatchCount,0);
    window.unmaximize();window.setSize(1000,760);await pause(500);
    await camera({x:71,y:70,z:90},{x:30,y:0,z:15});
    await capture('08-narrow',true);
    window.maximize();await pause(500);
    await js(`${current}.workspace._setViewMode('plan');${current}.workspace.executeCommand('fit-layout')`);
    assert.deepEqual(await hashes(),before);
    report.checks.savedBytesUnchanged=true;report.checks.equipmentSaved=false;
    report.status='passed';
    if(detail) {
      report.candidateFileHash=digest(await fs.readFile(path.join(output,'candidate.json')));
      report.status='awaiting-visual-review';await persist();
      const deadline=Date.now()+30*60*1000;
      let approved=false;
      while(Date.now()<deadline&&!window.isDestroyed()) {
        const approval=await fs.readFile(path.join(output,'save-approval.json'),'utf8').then(JSON.parse).catch(()=>null);
        if(approval?.save===true && approval.candidateFileHash===report.candidateFileHash) {approved=true;break;}
        await pause(1000);
      }
      assert.ok(approved,'Save approval not received; draft left unsaved');
      assert.deepEqual(await js(`${current}.session.getState().layout`),actual,'Draft changed after review');
      assert.deepEqual(await hashes(),before,'Saved base changed after review');
      await stage('saving-approved-gym');
      await js(`${current}.session.save().then(()=>null)`);
      assert.equal(await js(`${current}.session.getState().dirty`),false);
      const saved=JSON.parse(await fs.readFile(path.join(layoutDir,candidate.layoutId+'.json'),'utf8'));
      assert.deepEqual({...saved,updatedAt:actual.updatedAt},actual);
      const after=await hashes();
      for(const [name,hash] of Object.entries(before)) if(name!==candidate.layoutId+'.json'&&name!=='registry.json') assert.equal(after[name],hash);
      await js(`${current}.session.reload().then(()=>null)`);
      assert.deepEqual(await js(`${current}.session.getState().layout`),saved);
      report.checks.equipmentSaved=true;report.checks.savedReloadMatches=true;
      report.checks.otherLayoutsUnchanged=true;report.savedRevision=after[candidate.layoutId+'.json'];
      await fs.writeFile(path.join(output,'saved.json'),JSON.stringify(saved,null,2));
      await js(`${current}.workspace._setViewMode('3d');_setLeftPanelContent('structure',{reveal:true})`);
      await camera({x:64,y:43,z:62},{x:30,y:0,z:15});await capture('12-saved-overview',true);
      report.status='saved-and-verified';
    }
  } catch(error) {
    report.status='failed';report.error=error.stack;
    await capture('failure').catch(()=>{});
  }
  await persist();
  // Leave the user's draft open. Normal close/Save/Undo behavior stays in charge.
}
app.once('browser-window-created',(_event,window)=>{
  window.webContents.once('did-finish-load',()=>void review(window).catch(async error=>{
    await fs.writeFile(path.join(output,'driver-error.json'),JSON.stringify({error:error.stack}));
  }));
});
require('../src/entry.cjs');
