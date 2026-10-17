'use strict';
// Runs only against the isolated stores made by the wall verification launcher.
const { app } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile);
const current = 'window._trainFacilityLayoutAuthoringApp';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
require('electron').dialog.showErrorBox = (title, content) => {
  require('node:fs').writeFileSync(path.join(output,'startup-error.json'),JSON.stringify({title,content}));
};

async function verify(window) {
  const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
  assert.match(profile.profileId, /^facility-walls-/);
  const targetPath = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', profile.startupLayoutId + '.json');
  const before = sha(await fs.readFile(targetPath));
  const report = { status:'running', stages:[], captures:{} };
  const persist = () => fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
  const js = code => window.webContents.executeJavaScript(code,true);
  async function until(code, timeout=180000) {
    const end=Date.now()+timeout;
    while(Date.now()<end) { const result=await js(code); if(result)return result; await pause(200); }
    throw Error('Timed out: '+code);
  }
  async function stage(name) { report.stages.push(name); await persist(); }
  async function capture(name) {
    await pause(600);
    const image=await window.webContents.capturePage();
    assert.equal(image.isEmpty(),false);
    await fs.writeFile(path.join(output,name+'.png'),image.toPNG());
    const rect=await js(`(()=>{const r=${current}.workspace.threeAdapter.getRecordingCanvas().getBoundingClientRect();return {x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)}})()`);
    const bitmap=(await window.webContents.capturePage(rect)).toBitmap(),colors=new Set();
    for(let i=0;i<bitmap.length;i+=4*29)colors.add(bitmap.readUInt32LE(i));
    assert.ok(colors.size>40);
    report.captures[name]={size:image.getSize(),canvasColors:colors.size};await persist();
  }
  const diagnostics=()=>js(`${current}.workspace.threeAdapter.getDiagnostics()`);
  async function toggle(visible) {
    await js(`(()=>{const w=${current}.workspace;w._setLayerPanelOpen(true);const box=w.layerPanel.querySelector('[data-facility-layer="walls"]');if(box.checked!==${visible})box.click()})()`);
  }
  try {
    await persist();
    window.setSize(1440,900);
    await until(`${current}?.session?.getState().loaded`);
    const base=await js(`${current}.session.getState()`);
    assert.equal(base.layout.layoutId,profile.startupLayoutId);
    await stage('loaded-exact-layout');
    if(profile.startupLayoutId==='fl-walls-native') {
      await js(`${current}.session.select('zn-wall-boundary')`);
      await js(`(()=>{const w=${current}.workspace;w._setLayerPanelOpen(true);w.layerPanel.querySelector('[data-layer-action="perimeter-walls"]').click()})()`);
      await until(`!!document.querySelector('.ip-flw-wall-dialog[open]')`);
      await fs.writeFile(path.join(output,'00-wall-settings.png'),(await window.webContents.capturePage()).toPNG());
      await js(`(()=>{const d=document.querySelector('.ip-flw-wall-dialog'),s=d.querySelector('[aria-label="Wall boundary"]');s.value='selected';s.dispatchEvent(new Event('change'));d.querySelector('[aria-label="Height (m)"]').value=4;d.querySelector('[aria-label="Thickness (m)"]').value=.3;Array.from(d.querySelectorAll('button')).find(b=>b.textContent==='Add opening').click();d.querySelector('[aria-label="Opening start (m)"]').value=9;d.querySelector('[aria-label="Opening end (m)"]').value=13;d.querySelector('form').requestSubmit()})()`);
      await until(`!document.querySelector('.ip-flw-wall-dialog')`);
      const changed=await js(`${current}.session.getState()`);
      assert.equal(changed.dirty,true);assert.notEqual(changed.draftRevision,base.draftRevision);
      assert.equal(changed.layout.extensions.facilityPerimeterWalls.settings.boundarySource,'polygon');
      report.panels=changed.layout.extensions.facilityPerimeterWalls.panels.length;
      assert.equal(await js(`document.querySelectorAll('[data-layer="walls"] polygon').length`),report.panels);
      await stage('polygon-with-opening-applied-through-dialog');
    }
    await js(`${current}.workspace._setViewMode('3d')`);
    await until(`${current}.workspace.threeAdapter && ${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0`);
    await pause(1500);
    const position=profile.startupLayoutId==='fl-walls-native'?{x:48,y:45,z:55}:{x:340,y:280,z:350};
    const target=profile.startupLayoutId==='fl-walls-native'?{x:16,y:0,z:14}:{x:150,y:0,z:100};
    await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position=${JSON.stringify(position)};v.target=${JSON.stringify(target)};v.up={x:0,y:1,z:0};v.fov=45;v.near=.01;v.far=2000;a.applyCameraView(v)})()`);
    report.visible=await diagnostics();
    const countField=profile.startupLayoutId==='fl-walls-native'?'visiblePerimeterWallCount':'visibleLegacyWallPlacementCount';
    assert.equal(report.visible[countField],report.panels||6);
    await js(`${current}.workspace._setLayerPanelOpen(false)`);
    await capture('01-walls-visible');
    const beforeToggle=await js(`${current}.session.getState()`);
    await toggle(false);report.hidden=await diagnostics();assert.equal(report.hidden[countField],0);
    const afterToggle=await js(`${current}.session.getState()`);
    assert.deepEqual(afterToggle.layout,beforeToggle.layout);assert.equal(afterToggle.draftRevision,beforeToggle.draftRevision);
    await capture('02-walls-hidden');await stage('visibility-is-presentation-only');
    await toggle(true);
    if(profile.startupLayoutId==='fl-walls-native') {
      await js(`${current}.workspace.threeAdapter.enterWalkthrough({})`);
      report.walkthrough=await js(`${current}.workspace.threeAdapter.getWalkthroughState()`);
      assert.equal(report.walkthrough.active,true);assert.equal(report.walkthrough.obstacleCount,report.panels);
      await toggle(false);
      assert.equal(await js(`${current}.workspace.threeAdapter.getWalkthroughState().obstacleCount`),report.panels);
      await js(`${current}.workspace.threeAdapter.exitWalkthrough('test-complete')`);
      await toggle(true);await stage('hidden-walls-retain-walkthrough-obstacles');
      window.setSize(900,700);await pause(500);
      await js(`${current}.workspace._setLayerPanelOpen(false)`);await capture('03-walls-narrow');
      await js(`${current}.session.undo()`);
      const restored=await js(`${current}.session.getState()`);
      assert.deepEqual(restored.layout,base.layout);assert.equal(restored.draftRevision,base.draftRevision);
      assert.deepEqual(restored.selection,['zn-wall-boundary']);
      assert.equal(restored.dirty,false);await stage('exact-undo');
      await js(`${current}.session.setPerimeterWalls({boundarySource:'plan',heightMeters:3,thicknessMeters:.2,openings:[]})`);
      await js(`${current}.session.setPlanSettings({widthMeters:55,depthMeters:36,gridSpacingMeters:1,majorGridSpacingMeters:5})`);
      const resized=await js(`${current}.session.getState().layout.extensions.facilityPerimeterWalls`);
      assert.equal(Math.max(...resized.panels.flat().map(p=>p.x)),55.1);
      await js(`${current}.session.undo()`);await js(`${current}.session.undo()`);
      assert.equal(await js(`${current}.session.getState().draftRevision`),base.draftRevision);
      await stage('plan-walls-follow-resize-and-undo');
    }
    assert.equal(sha(await fs.readFile(targetPath)),before);
    report.savedDocumentUnchanged=true;report.status='passed';
  } catch(error) {
    report.status='failed';report.error=error.stack;
    report.dialogError=await js(`document.querySelector('.ip-flw-wall-error')?.textContent`).catch(()=>null);
    await capture('failure').catch(()=>{});
  } finally { await persist();app.quit(); }
}
app.once('browser-window-created',(_event,window)=>{
  window.webContents.once('did-finish-load',()=>void verify(window).catch(async error=>{
    await fs.writeFile(path.join(output,'driver-error.json'),JSON.stringify({error:error.stack}));app.quit();
  }));
});
require('../src/entry.cjs');
