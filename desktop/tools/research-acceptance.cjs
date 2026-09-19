'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { desktopCapturer, screen } = require('electron');
const { ownedWindowSource } = require('./owned-window-source.cjs');
const { readWindowGeometry } = require('./window-geometry.cjs');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(read, message, timeout = 45000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const result = await read(); if (result) return result; await delay(100); }
  throw new Error(message);
}
async function runResearchAcceptance({ window, pane, profile, peer, output, getRequestEvidence }) {
  const report = { schemaVersion: 1, status: 'running', checks: {}, saveCalls: null, nativeCompositeAvailable: true, nativeAcceptance: false };
  const save = () => fs.writeFile(path.join(output, 'research-check.json'), JSON.stringify(report, null, 2));
  const evaluate = code => window.webContents.executeJavaScript(code, true);
  const frame = () => peer.run('snapshot');
  const originalSize = window.getSize();
  const initial = await frame(), rendererId = window.webContents.id;
  async function capture(name) {
    window.show(); window.focus(); await delay(300);
    const geometry = readWindowGeometry({ window, screen, requestedOuterSize: window.getSize() });
    (report.windowGeometry ||= []).push({ name, ...geometry });
    assert.equal(geometry.state.isVisible, true, 'Native capture requires an actually visible window');
    if (!pane.snapshot().visible) {
      await fs.writeFile(path.join(output,name),(await window.webContents.capturePage()).toPNG());
      (report.captures ||= []).push({name,method:'application-webcontents-no-research-overlay'}); return;
    }
    try {
    try {
      const owned = await ownedWindowSource({ window, desktopCapturer });
      await fs.writeFile(path.join(output,name),owned.image.toPNG());
      (report.captures ||= []).push({name,method:'owned-window-desktop-capturer',observations:owned.observations}); return;
    } catch (error) { (report.enumerationFailures ||= []).push({name,message:error.message,observations:error.observations}); }
    const nativeHandle = window.getNativeWindowHandle();
    const handle = nativeHandle.length === 8 ? nativeHandle.readBigUInt64LE().toString() : String(nativeHandle.readUInt32LE());
    const result = await new Promise((resolve,reject) => {
      const powershell = path.join(process.env.SystemRoot || process.env.WINDIR || 'C:\\Windows','System32','WindowsPowerShell','v1.0','powershell.exe');
      const child = spawn(powershell,['-NoProfile','-NonInteractive','-File',path.join(__dirname,'capture-owned-window.ps1'),
        '-WindowHandle',handle,'-OwnerProcessId',String(process.pid),'-OutputPath',path.join(output,name)],{windowsHide:true,stdio:['ignore','pipe','pipe']});
      let stdout='',stderr='',expired=false;
      const timer=setTimeout(()=>{expired=true;child.kill();},15000);
      child.stdout.on('data',data=>{stdout+=data.toString();});child.stderr.on('data',data=>{stderr+=data.toString();});
      child.on('error',error=>{clearTimeout(timer);reject(error);});child.on('close',code=>{clearTimeout(timer);if(code!==0||expired)reject(new Error('Owned native capture failed: '+stderr.slice(0,1500)));else {try{resolve(JSON.parse(stdout));}catch(error){reject(error);}}});
    });
    (report.captures ||= []).push({name,...result});
    } catch(error) {
      report.nativeCompositeAvailable = false;
      (report.captureErrors ||= []).push({name,message:error.message});
      // These are separately identified renderer surfaces, never a fabricated
      // composite or a substitute for the missing native-window acceptance.
      await fs.writeFile(path.join(output,name.replace('.png','-application.png')),(await window.webContents.capturePage()).toPNG());
      await fs.writeFile(path.join(output,name.replace('.png','-controls.png')),(await pane.chrome.webContents.capturePage()).toPNG());
      const selected = pane.snapshot().activeId;
      const index = pane.snapshot().tabs.findIndex(tab=>tab.id===selected);
      await fs.writeFile(path.join(output,name.replace('.png','-page.png')),(await pane.getViews()[index].webContents.capturePage()).toPNG());
    }
  }
  try {
    report.stage = 'public-page'; await save();
    const id = pane.open('https://example.com/');
    assert.equal(pane.open('https://example.com/'), id);
    const view = pane.getViews().at(-1), contents = view.webContents;
    await until(() => pane.snapshot().tabs.some(tab => tab.id === id && !tab.loading && tab.title === 'Example Domain'), 'Public HTTPS page did not finish');
    report.isolation = contents.getLastWebPreferences();
    for (const key of ['sandbox','contextIsolation','webSecurity']) assert.equal(report.isolation[key], true);
    assert.equal(report.isolation.nodeIntegration, false); assert.ok(!report.isolation.preload);
    const exposed = await contents.executeJavaScript('({process:typeof process,require:typeof require,bridge:typeof InspectorProDesktop,research:typeof research})');
    assert.deepEqual(exposed,{process:'undefined',require:'undefined',bridge:'undefined',research:'undefined'});
    report.checks.publicHTTPSAndIsolation = true;
    report.stage = 'private-network'; await save();
    const target = profile.origin;
    report.network = await contents.executeJavaScript(`(async()=>{const urls=${JSON.stringify([target + '/api/profiles', target.replace('127.0.0.1','localhost') + '/api/profiles', target.replace('127.0.0.1','2130706433') + '/api/profiles', target.replace('http:','https:') + '/api/profiles'])};return Promise.all(urls.map(async url=>{try{await fetch(url,{mode:'no-cors'});return {url,blocked:false};}catch(_){return {url,blocked:true};}}));})()`);
    assert.ok(report.network.every(item => item.blocked)); report.localNetworkBlocked = true;
    report.stage = 'native-layout'; await save();
    for (const [name, size] of [['wide', originalSize], ['narrow',[900,700]]]) {
      window.setSize(...size); await delay(500); pane.layout(); await delay(300);
      const state = pane.snapshot(); assert.equal(state.visible,true);
      const chromeBounds = pane.chrome.getBounds(), pageBounds = view.getBounds(), windowBounds = window.getContentBounds();
      assert.equal(pageBounds.x + pageBounds.width,windowBounds.width);
      assert.equal(pageBounds.y + pageBounds.height,windowBounds.height);
      assert.equal(chromeBounds.y + chromeBounds.height,pageBounds.y);
      const overlap = await pane.chrome.webContents.executeJavaScript(`(()=>{const nodes=[...document.querySelectorAll('form>button,form>input,.top>button,.top>strong,#tabs')];const v=nodes.filter(n=>!n.hidden).map(n=>n.getBoundingClientRect());return v.some(r=>r.x<0||r.y<0||r.right>innerWidth+1||r.bottom>innerHeight+1);})()`);
      assert.equal(overlap,false);
      if (chromeBounds.x > 0) {
        const toolbar = await evaluate(`(()=>{const area=document.body.getBoundingClientRect(),root=document.querySelector('.app-container > .toolbar');const bounds=n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};const nodes=[...root.querySelectorAll('.toolbar-brand,.app-menu-label,.toolbar-icons button,.toolbar-right > button,.toolbar-search-wrap,.status-indicator')].filter(n=>n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden');return {area:bounds(document.body),items:nodes.map(n=>({label:n.getAttribute('title')||n.textContent.trim().slice(0,80),...bounds(n)}))};})()`);
        assert.ok(toolbar.items.every(r=>r.x>=toolbar.area.x-1&&r.right<=toolbar.area.right+1), 'Toolbar exceeds available application width');
        for (let i=0;i<toolbar.items.length;i++) for (let j=i+1;j<toolbar.items.length;j++) {
          const a=toolbar.items[i],b=toolbar.items[j];
          assert.ok(Math.min(a.right,b.right)-Math.max(a.x,b.x)<=1 || Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)<=1, 'Toolbar overlap: '+a.label+' / '+b.label);
        }
        (report.applicationToolbar ||= []).push({name,...toolbar});
      }
      await capture('research-' + name + '.png');
    }
    window.setSize(...originalSize); pane.hide(); await delay(500);
    assert.equal(window.webContents.id,rendererId); assert.deepEqual((await frame()).editorFrame,initial.editorFrame);
    pane.show(); await delay(200); assert.deepEqual((await frame()).editorFrame,initial.editorFrame);
    pane.suspend(true); assert.equal(view.getVisible(),false); pane.suspend(false); assert.equal(view.getVisible(),true);
    pane.hide(); report.exactFrameRetained = true; report.checks.boundsHideReopenAndOverlay = true;
    report.stage = 'actual-facility-assets'; await save();
    await evaluate("_trainFacilityLayoutAuthoringApp.workspace._setViewMode('3d')");
    await until(() => evaluate(`(()=>{const a=_trainFacilityLayoutAuthoringApp.workspace.threeAdapter,d=a?.getDiagnostics();return d?.status==='ready'&&d.pendingLoads===0;})()`),'Facility 3D initialization failed',120000);
    const priorSelection = await evaluate('_trainFacilityLayoutAuthoringApp.workspace.threeAdapter.getDiagnostics().selectedPlacementIds');
    await evaluate(`(()=>{const a=_trainFacilityLayoutAuthoringApp,seen=new Set(),ids=[];for(const p of a.session.getState().layout.placements){const key=p.assetId+'|'+p.assetDefinitionRevision;if(!seen.has(key)){seen.add(key);ids.push(p.placementId);}}a.workspace.threeAdapter.setSelection(ids);})()`);
    report.meshes = await until(async () => {
      const diagnostics = await evaluate('_trainFacilityLayoutAuthoringApp.workspace.threeAdapter.getDiagnostics()');
      report.assetDiagnostics = diagnostics;
      const groups = diagnostics.representationGroups || [];
      const ids = new Set(groups.filter(group => ['overview','detail'].includes(group.representation) && group.meshCount > 0 && group.prototypeMeshCount > 0).flatMap(group => group.placementIds));
      if (diagnostics.degraded || diagnostics.contextLost || diagnostics.loadTrace?.some(item=>item.status==='failed')) throw new Error('Facility mesh loading or renderer failed');
      return diagnostics.pendingLoads === 0 && diagnostics.rendering.deferredGroupCount === 0 && diagnostics.placementCount === 827 && ids.size === 827 && diagnostics.placementTransformAudit?.status === 'match' && diagnostics.placementTransformAudit.auditedPlacementCount === 827
        ? {realPlacements:ids.size,assetGroups:diagnostics.assetGroupCount,transformAudit:diagnostics.placementTransformAudit} : null;
    },'Real GLBs did not replace every placement proxy',120000);
    await evaluate("_trainFacilityLayoutAuthoringApp.workspace.threeAdapter.fitLayout();_trainFacilityLayoutAuthoringApp.workspace.openAssetBrowser()");
    report.library = await evaluate(`(()=>{const w=_trainFacilityLayoutAuthoringApp.workspace;return {open:w.assetBrowserState.open,cards:w.assetGrid.querySelectorAll('article[data-asset-id]').length};})()`);
    assert.equal(report.library.open,true); assert.ok(report.library.cards >= 37);
    await delay(500);
    await capture('research-facility-assets.png');
    await evaluate(`_trainFacilityLayoutAuthoringApp.workspace.threeAdapter.setSelection(${JSON.stringify(priorSelection)})`);
    await evaluate('_trainFacilityLayoutAuthoringApp.workspace.closeAssetBrowser(false)');
    await delay(500); await capture('research-facility-scene.png');
    report.checks.realMeshesAndLibrary = true;
    report.saveCalls = getRequestEvidence().saveCalls; assert.equal(report.saveCalls,0);
    report.engineChecksPassed = true;
    report.nativeAcceptance = report.nativeCompositeAvailable;
    report.status = report.nativeCompositeAvailable ? 'passed' : 'pending-native-composite'; report.stage = 'complete';
  } catch (error) { report.status = 'failed'; report.error = {message:error.message,stack:error.stack}; throw error; }
  finally { pane.hide(); window.setSize(...originalSize); report.browser = pane.evidence(); await save(); }
}
module.exports = { runResearchAcceptance };
