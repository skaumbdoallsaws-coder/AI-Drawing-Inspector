'use strict';
// Main-process-only test driver. No evaluation bridge is exposed to the page.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = b => createHash('sha256').update(b).digest('hex');
async function run({ window, runtime, network, profile, root, output, observe, change }) {
  const source = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'application-check-source.json'), 'utf8'));
  assert.equal(profile.facilityRoot, source.isolatedFacilityRoot);
  assert.notEqual(path.resolve(profile.facilityRoot), path.resolve(root, '.runtime/facility-layout'));
  await fs.mkdir(output, { recursive: true });
  const report = { schemaVersion: 1, status: 'running', stages: [], errors: [], requests: [] };
  const save = () => fs.writeFile(path.join(output, 'application-check.json'), JSON.stringify(report, null, 2));
  const stage = async name => { report.stage = name; report.stages.push({ name, time: new Date().toISOString() }); await save(); };
  const js = async code => {
    const result = await window.webContents.executeJavaScript(`(async()=>{try{return {ok:true,value:await (${code})};}catch(e){return {ok:false,error:{message:e.message,stack:e.stack}};}})()`, true);
    if (!result.ok) throw Object.assign(new Error(result.error.message), { stack: result.error.stack });
    return result.value;
  };
  const app = '_trainFacilityLayoutAuthoringApp';
  const until = async (code, label, timeout = 90000) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) { const result = await js(code); if (result) return result; await delay(150); }
    throw new Error(label);
  };
  const click = async selector => {
    window.focus();
    window.webContents.focus();
    await delay(400);
    const point = await js(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e||e.disabled||e.closest('[inert]'))throw Error('Control unavailable: '+${JSON.stringify(selector)});
      const r=e.getBoundingClientRect();if(!r.width||!r.height)throw Error('Control hidden');return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()`);
    window.webContents.sendInputEvent({ type: 'mouseMove', ...point });
    window.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...point });
    window.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...point });
    await delay(200);
  };
  const shot = async name => { await delay(700); const img = await window.webContents.capturePage(); assert.equal(img.isEmpty(), false);
    await fs.writeFile(path.join(output, name + '.png'), img.toPNG()); };
  window.webContents.on('console-message', details => {
    if (details?.level === 'error') report.errors.push(String(details.message).slice(0, 700));
  });
  try {
    await stage('application-ready');
    window.setTitle('InspectorPro - Native verification');
    await until(`!!window._trainFacilityLayoutAuthoringApp?.session?.getState().loaded`, 'manual-layout-mount-timeout');
    const state = await js(`${app}.session.getState()`);
    assert.equal(state.baseRevision, source.originalSha256, 'Use a fresh copy for the revision-bound motion preset');
    assert.equal(state.layout.layoutId, profile.startupLayoutId); assert.equal(state.layout.placements.length, 827);
    report.layout = { layoutId: state.layout.layoutId, placements: state.layout.placements.length, zones: state.layout.zones.length, revision: state.baseRevision };
    report.isolation = await js(`({node:typeof require,managed:typeof window.InspectorProDesktop,inert:!!document.querySelector('[inert]'),externalToolbar:${app}.workspace.externalCommandSurface})`);
    assert.equal(report.isolation.node, 'undefined'); assert.equal(report.isolation.managed, 'undefined');
    assert.equal(report.isolation.inert, false); assert.equal(report.isolation.externalToolbar, true);
    report.observation = await observe();
    assert.equal(report.observation.busy, false);
    await stage('integrated-native-titlebar');
    const beforeResize = window.getBounds();
    report.titlebar = [];
    for (const narrow of [false, true]) {
      if (narrow) window.setSize(900, 700);
      await delay(700);
      const chrome = await js(`(()=>{const overlay=navigator.windowControlsOverlay;const safe=overlay.getTitlebarAreaRect();const bar=document.querySelector('.app-container > .toolbar');const b=bar.getBoundingClientRect();const children=[...bar.querySelectorAll('button,input,nav')].filter(e=>e.getBoundingClientRect().width);return {overlay:overlay.visible,safe:{x:safe.x,width:safe.width},header:{top:b.top,height:b.height},duplicateControls:getComputedStyle(bar.querySelector('.window-controls')).display,drag:getComputedStyle(bar).getPropertyValue('-webkit-app-region'),overlap:children.filter(e=>{const r=e.getBoundingClientRect();return r.right>safe.right+1;}).map(e=>e.id||e.tagName),controlsDraggable:children.filter(e=>getComputedStyle(e).getPropertyValue('-webkit-app-region')!=='no-drag').map(e=>e.id||e.tagName)};})()`);
      assert.equal(chrome.overlay, true);
      assert.equal(chrome.header.top, 0);
      assert.equal(chrome.duplicateControls, 'none');
      assert.equal(chrome.drag, 'drag');
      assert.deepEqual(chrome.overlap, []);
      assert.deepEqual(chrome.controlsDraggable, []);
      report.titlebar.push({ narrow, ...chrome });
      await shot(narrow ? '00b-native-header-narrow' : '00a-native-header-wide');
    }
    window.setBounds(beforeResize);
    await delay(700);
    const unauthenticated = await fetch(profile.origin + '/api/profiles'); assert.equal(unauthenticated.status, 401);
    await stage('ribbon-library-and-workflow-tabs');
    await click('.facility-ribbon-commandbar [data-facility-ribbon-command="pan"]');
    await until(`${app}.workspace.getCommandStates().pan.active`, 'pan-not-active');
    await click('.facility-ribbon-commandbar [data-facility-ribbon-command="select"]');
    await click('#trainFacilityLayoutAssets');
    await until(`${app}.workspace.assetBrowserState.open`, 'library-not-open');
    report.catalog = await js(`(async()=>{const r=await fetch('/api/industrial-assets');return {status:r.status,data:await r.json()};})()`);
    assert.equal(report.catalog.status, 200);
    await shot('01-plan-and-library');
    await click('#trainFacilityLayoutAssets');
    // Use the actual visible tab identifiers, not names guessed by the driver.
    report.tabs = await js(`Array.from(document.querySelectorAll('.tab[data-tab]')).filter(e=>e.getBoundingClientRect().width).map(e=>({id:e.dataset.tab,disabled:e.matches(':disabled')||e.getAttribute('aria-disabled')==='true',inert:!!e.closest('[inert]')}))`);
    assert.equal(report.tabs.length, 8);
    for (const tab of report.tabs) {
      assert.equal(tab.disabled, false); assert.equal(tab.inert, false);
      await click('.tab[data-tab=' + JSON.stringify(tab.id) + ']');
      await until(`document.querySelector('.tab.active[data-tab]')?.dataset.tab===${JSON.stringify(tab.id)}`, 'workflow-tab-did-not-activate:' + tab.id);
      tab.activated = true;
    }
    await click('.tab[data-tab="training"]');
    await until(`!!document.querySelector('#trainFacilityLayoutAuthoring [data-view="3d"]') && ${app}.workspace.root.isConnected`, 'facility-root-not-restored');
    await stage('three-dimensional-assets');
    await click('#trainFacilityLayoutAuthoring [data-view="3d"]');
    await until(`${app}.workspace.threeAdapter?.getDiagnostics().pendingLoads===0 && ${app}.workspace.threeAdapter?.getDiagnostics().assetGroupCount>0`, 'glb-load-timeout', 150000);
    report.three = await js(`${app}.workspace.threeAdapter.getDiagnostics()`);
    assert.equal(report.three.placementCount, 827); assert.equal(report.three.degraded, false);
    await shot('02-three-dimensional-assets');
    await stage('close-up-real-robot-mesh');
    await js(`(()=>{const p=${app}.session.getState().layout.placements.find(p=>p.assetId==='asset-abb-irb6650-robot').transform.position;return ${app}.workspace.threeAdapter.topView({minimum:{x:p.x-6,y:0,z:p.z-6},maximum:{x:p.x+6,y:7,z:p.z+6}});})()`);
    // Large layouts intentionally keep GLB overview meshes; a fallback is one box.
    await until(`${app}.workspace.threeAdapter.getDiagnostics().representationGroups.some(g=>g.assetId==='asset-abb-irb6650-robot' && ['overview','detail'].includes(g.representation) && g.prototypeMeshCount===13) && ${app}.workspace.threeAdapter.getDiagnostics().pendingLoads===0`, 'real-robot-mesh-timeout');
    report.robotMesh = await js(`${app}.workspace.threeAdapter.getDiagnostics().representationGroups.filter(g=>g.assetId==='asset-abb-irb6650-robot')`);
    await shot('02b-robot-real-glb');
    await click('#trainFacilityLayoutAuthoring [data-view="plan"]');
    const original = await js(`${app}.session.getState()`);
    const zone = original.layout.zones[0];
    async function verifyMotion() {
    await stage('sage-chat-to-complete-motion');
    const prompt = 'Show the prototype movement candidate map for all moving objects in this reference factory. Use the existing operators and forklifts, display the pending handoff links, keep fixed machines stationary, and do not save.';
    await js(`(()=>{window._selectAgent('deviation-analyst');const input=document.getElementById('agentInput');if(!input.getBoundingClientRect().width)window._toggleAgentPanel();return true;})()`);
    await click('#agentChatNewBtn');
    await js(`(()=>{window._selectAgent('deviation-analyst');return true;})()`);
    await js(`(()=>{const input=document.getElementById('agentInput');if(input.disabled||input.closest('[inert]'))throw Error('Sage input disabled');input.focus();input.value=${JSON.stringify(prompt)};input.dispatchEvent(new Event('input',{bubbles:true}));return true;})()`);
    await until(`document.getElementById('agentInput').value===${JSON.stringify(prompt)}`, 'sage-input-not-entered');
    await click('#agentSendBtn');
    await until(`(()=>{const text=document.getElementById('agentMessages').innerText;if(!document.querySelector('#agentMessages .agent-stream-pending') && /could not (?:start|generate)/i.test(text))throw Error('Sage refused: '+text.slice(-1600));return ${app}.workspace.threeAdapter.activity.getState().loaded && ${app}.workspace.threeAdapter.activity.getState().actors.length===23 && !document.querySelector('#agentMessages .agent-stream-pending') && ${app}.workspace.threeAdapter.getDiagnostics().pendingLoads===0;})()`, 'sage-motion-timeout', 240000);
    report.sage = { prompt, response: await js(`document.getElementById('agentMessages').innerText`) };
    const activity = `${app}.workspace.threeAdapter.activity`;
    await click('#trainFacilityMotionPlaybackHost .ip-flw-motion-play');
    await until(`!${activity}.getState().playing`, 'native-pause-did-not-work');
    await click('#trainFacilityMotionPlaybackHost .ip-flw-motion-play');
    await until(`${activity}.getState().playing`, 'native-play-did-not-work');
    const pathsInitiallyVisible = await js(`${activity}.getState().pathsVisible`);
    await click('#trainFacilityMotionPlaybackHost [data-activity-paths]');
    await until(`${activity}.getState().pathsVisible===${!pathsInitiallyVisible}`, 'native-path-toggle-did-not-work');
    await click('#trainFacilityMotionPlaybackHost [data-activity-paths]');
    report.playbackControls = await js(`(()=>{const button=document.querySelector('#trainFacilityMotionPlaybackHost .ip-flw-motion-play');const style=getComputedStyle(button);return {disabled:button.disabled,foreground:style.color,background:style.backgroundColor};})()`);
    assert.equal(report.playbackControls.disabled, false);
    // seek schedules pose evaluation on the renderer's next animation frame.
    const seek = seconds => js(`(async()=>{${activity}.pause();${activity}.seek(${seconds});await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));return true;})()`);
    await seek(0);
    report.motion = { initial: await js(`${activity}.getState()`), samples: [] };
    for (const seconds of [2.5, 7.5, 17.5]) {
      await seek(seconds);
      report.motion.samples.push(await js(`${activity}.getState()`));
    }
    const actors = report.motion.initial.actors;
    assert.equal(actors.length, 23);
    assert.equal(new Set(actors.map(a => a.placementId)).size, 23);
    assert.equal(actors.filter(a => a.exactCatalogVisual && a.sourcePlacementSuppressed).length, 23);
    assert.deepEqual(report.motion.initial.duplicateVisiblePlacementIds, []);
    report.motion.movedActorIds = actors.filter(a => report.motion.samples.some(sample => {
      const b = sample.actors.find(b => b.actorId === a.actorId);
      return Math.hypot(b.pose.x - a.pose.x, b.pose.z - a.pose.z) > 0.01 || Math.abs(b.pose.heading - a.pose.heading) > 0.01;
    })).map(a => a.actorId);
    assert.equal(report.motion.movedActorIds.length, 23);
    await shot('04-sage-motion-plan');
    await stage('drone-and-motion-restoration');
    await js(`(()=>{if(document.getElementById('agentInput').getBoundingClientRect().width)window._toggleAgentPanel();${app}.workspace._setViewMode('3d');return true;})()`);
    const operator = await js(`${app}.workspace.activityPresentation.scenario.actors.find(a=>a.actorType==='operator')`);
    report.drone = await js(`${app}.workspace.threeAdapter.enterDrone({placementId:${JSON.stringify(operator.placementId)}})`);
    assert.equal(report.drone.active, true);
    await js(`${activity}.play()`); await delay(2300); await js(`${activity}.pause()`);
    report.motion.drone = await js(`${activity}.getState()`);
    assert.deepEqual(report.motion.drone.duplicateVisiblePlacementIds, []);
    assert.deepEqual(report.motion.drone.visibleSourcePlacementIds, []);
    await shot('05-drone-moving-existing-operator');
    await js(`${app}.workspace.threeAdapter.exitDrone('acceptance_complete')`);
    await click('.tab[data-tab="drawing"]');
    await click('.tab[data-tab="training"]');
    await until(`${app}.workspace.motionPanel.isConnected && ${app}.workspace.root.isConnected && !${app}.getState().suspended`, 'playback-pane-not-restored');
    assert.equal(await js(`${activity}.getState().actors.length`), 23);
    assert.deepEqual(await js(`${activity}.getState().duplicateVisiblePlacementIds`), []);
    report.motion.retainedAfterTabSwitch = true;
    assert.equal(await js(`${app}.session.getState().dirty`), false);
    await shot('06-restored-docked-playback');
    }
    async function verifyEditingAndRestart() {
    await stage('edit-undo-save-on-copy');
    await click('#trainFacilityLayoutAuthoring [data-view="plan"]');
    await js(`${app}.session.editZoneLabel(${JSON.stringify(zone.zoneId)},'Desktop unsaved test')`);
    assert.equal(await js(`${app}.session.getState().canSave`), true);
    assert.equal((await observe()).dirty, true);
    await js(`${app}.session.undo()`);
    assert.deepEqual((await js(`${app}.session.getState()`)).layout, original.layout);
    await js(`${app}.session.editZoneLabel(${JSON.stringify(zone.zoneId)},'Desktop copy save verification')`);
    await js(`${app}.session.save()`);
    assert.equal(await js(`${app}.session.getState().dirty`), false);
    report.copySavedRevision = await js(`${app}.session.getState().baseRevision`);
    assert.notEqual(report.copySavedRevision, original.baseRevision);
    // Restoring geometry still advances updatedAt and the authoritative revision.
    await js(`${app}.session.editZoneLabel(${JSON.stringify(zone.zoneId)},${JSON.stringify(zone.label)})`);
    await js(`${app}.session.save()`);
    await stage('restart-retains-unsaved-history');
    await js(`${app}.session.editZoneLabel(${JSON.stringify(zone.zoneId)},'Draft retained through backend restart')`);
    const before = await js(`${app}.session.getState()`);
    const instance = runtime.getState().instanceId;
    await change('restart');
    assert.notEqual(runtime.getState().instanceId, instance); assert.equal(runtime.getState().status, 'ready');
    const after = await js(`${app}.session.getState()`);
    for (const key of ['layout', 'draftRevision', 'history', 'historyCursor', 'selection']) assert.deepEqual(after[key], before[key]);
    await js(`${app}.session.undo()`);
    await shot('03-restored-plan');
    }
    await stage('native-downloads');
    async function download(name, trigger) {
      const target = path.join(output, name);
      let listener;
      const complete = new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Download timeout: ' + name)), 20000);
        listener = (_event, item) => {
          item.setSavePath(target);
          item.once('done', (_event, state) => {
            clearTimeout(timer);
            if (state === 'completed') resolve(); else reject(new Error('Download ' + state + ': ' + name));
          });
        };
        window.webContents.session.once('will-download', listener);
      });
      try { await trigger(); await complete; }
      finally { window.webContents.session.removeListener('will-download', listener); }
      return fs.readFile(target);
    }
    const exported = await download('layout-export.json', () => js(`downloadFile('layout-export.json',JSON.stringify(${app}.session.getState().layout),'application/json')`));
    assert.deepEqual(JSON.parse(exported), (await js(`${app}.session.getState()`)).layout);
    const profiles = await download('profiles-download.json', () => js(`(()=>{window.open('/api/profiles','_blank');return true;})()`));
    assert.ok(Array.isArray(JSON.parse(profiles)));
    report.downloads = { blobExportBytes: exported.length, authenticatedArtifactBytes: profiles.length };
    await stage('native-close-cancel');
    await js(`${app}.session.editZoneLabel(${JSON.stringify(zone.zoneId)},'Cancel preserves this draft')`);
    const beforeCancel = await js(`${app}.session.getState()`);
    await change('close');
    assert.equal(window.isDestroyed(), false);
    const afterCancel = await js(`${app}.session.getState()`);
    for (const key of ['layout', 'draftRevision', 'history', 'historyCursor', 'selection']) assert.deepEqual(afterCancel[key], beforeCancel[key]);
    report.closeCancelled = true;
    await js(`${app}.session.undo()`);
    await shot('07-cancel-preserved-draft-and-undo');
    await verifyMotion();
    await verifyEditingAndRestart();
    report.network = network.getEvidence();
    assert.equal(report.network.saveCalls, 2);
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.failure = { message: error.message, stack: error.stack };
    report.network = network.getEvidence();
    try { report.playbackAtFailure = await js(`(()=>{const w=${app}.workspace;return {pending:w.activityRequestPending,activity:w.threeAdapter.activity.getState(),controller:w.controller.getState(),viewUpdates:w.controller.pendingViewUpdates.length,pendingLoads:w.threeAdapter.getDiagnostics().pendingLoads};})()`); } catch (_) {}
    try { report.chatAtFailure = await js(`document.getElementById('agentMessages')?.innerText`); } catch (_) {}
    try { report.observationAtFailure = await observe(); await shot('failure'); } catch (_) {}
    throw error;
  } finally {
    report.originalSha256After = hash(await fs.readFile(source.originalPath));
    report.originalUnchanged = report.originalSha256After === source.originalSha256;
    if (!report.originalUnchanged) report.status = 'failed';
    await save();
  }
}
module.exports = { run };
