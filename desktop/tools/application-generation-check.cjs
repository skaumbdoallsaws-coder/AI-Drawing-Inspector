'use strict';
// Explicit native test entry only. Prompts are external inputs, never runtime recipes.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { ownedWindowSource } = require('./owned-window-source.cjs');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function verifyRestart(runtime, before) {
  const after = runtime.getEvidence();
  assert.equal(after.length, before.length + 1, 'Restart did not start a new backend');
  const latest = after.at(-1);
  assert.notEqual(latest.instanceId, before.at(-1).instanceId);
  if (latest.failure) throw Object.assign(new Error('Backend restart failed: ' + latest.failure.code), { code: latest.failure.code });
  const state = runtime.getState();
  assert.equal(state.status, 'ready', 'Restarted backend did not become ready');
  assert.equal(state.instanceId, latest.instanceId, 'Ready backend differs from restarted backend');
  assert.ok(latest.runtime, 'Restarted backend identity was not verified');
  return after;
}
async function run({ window, runtime, profile, root, output, change, ensureBrowser }) {
  const source = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'application-check-source.json'), 'utf8'));
  assert.equal(profile.facilityRoot, source.isolatedFacilityRoot);
  assert.notEqual(path.resolve(profile.facilityRoot), path.resolve(root, '.runtime/facility-layout'));
  const scenario = JSON.parse(await fs.readFile(path.join(output, 'scenario.json'), 'utf8'));
  assert.equal(typeof scenario.prompt, 'string');
  assert.ok(scenario.correction === undefined || typeof scenario.correction === 'string');
  const report = { status: 'running', scope: 'normal Electron application; live provider; isolated store', stages: [], turns: [], requests: [], responses: [], errors: [] };
  const persist = () => fs.writeFile(path.join(output, 'generation-check.json'), JSON.stringify(report, null, 2));
  const stage = async name => { report.stage = name; report.stages.push({ name, at: new Date().toISOString() }); await persist(); };
  const js = code => window.webContents.executeJavaScript(`(async()=>(${code}))()`, true);
  const app = 'window._trainFacilityLayoutAuthoringApp';
  const until = async (code, message, timeout = 60000) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) { const value = await js(code); if (value) return value; await delay(200); }
    throw new Error(message);
  };
  const chatRequests = new Map();
  const planningRequests = new Map();
  const responseReads = new Set();
  const shot = async (name, includeChildren = false) => {
    window.show(); window.focus(); window.webContents.focus();
    let timer;
    await Promise.race([
      js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))'),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Renderer frame wait timed out: ' + name)), 15000); }),
    ]).finally(() => clearTimeout(timer));
    window.webContents.invalidate();
    await delay(500); const image = includeChildren
      ? (await ownedWindowSource({ window, desktopCapturer: require('electron').desktopCapturer })).image
      : await window.webContents.capturePage();
    assert.equal(image.isEmpty(), false);
    const png = image.toPNG();
    await fs.writeFile(path.join(output, name + '.png'), png);
    report.captures ??= {};
    report.captures[name] = { sha256: hash(png), size: image.getSize(),
      bounds: window.getContentBounds(), focused: window.isFocused(),
      state: await js(`({visibility:document.visibilityState,view:${app}.session.getState().viewMode,preview:${app}.workspace.generationPlanningView.activePreviewRef(),placements:${app}.workspace.generationPlanningView.activeLayout()?.placements.length})`) };
    await persist();
  };
  const click = async (code, { navigates = false } = {}) => {
    window.focus(); window.webContents.focus();
    await delay(400);
    await js(`(()=>{const e=${code};if(!e)throw Error('Missing control');e.scrollIntoView({block:'center',inline:'nearest'});})()`);
    await delay(400);
    const point = await js(`(()=>{const e=${code};if(!e||e.disabled||e.closest('[inert]'))throw Error('Unavailable control');const r=e.getBoundingClientRect();if(!r.width||!r.height)throw Error('Hidden control');const p={x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};const hit=document.elementFromPoint(p.x,p.y);if(!hit||!(hit===e||e.contains(hit)))throw Error('Control is occluded: '+e.textContent);window.__generationNativeClick=false;window.addEventListener('click',event=>{window.__generationNativeClick=event.composedPath().includes(e);},{capture:true,once:true});return p;})()`);
    report.lastClick = { code, point, zoom: window.webContents.getZoomFactor(), bounds: window.getContentBounds(), viewport: await js('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})') };
    await persist();
    window.webContents.sendInputEvent({ type: 'mouseMove', ...point });
    window.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...point });
    window.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...point });
    if (!navigates) await until('window.__generationNativeClick === true', 'Native click was not delivered: ' + code, 3000);
  };
  window.webContents.on('console-message', detail => { if (detail.level === 'error') report.errors.push(String(detail.message).slice(0, 1000)); });
  window.webContents.debugger.attach('1.3');
  await window.webContents.debugger.sendCommand('Network.enable');
  window.webContents.debugger.on('message', (_event, method, params) => {
    if (method === 'Network.requestWillBeSent' && params.request.url.startsWith(profile.origin + '/api/')) {
      report.requests.push({ method: params.request.method, url: params.request.url });
      if (params.request.url.includes('/api/facility-layout-planning/')) {
        const entry = { requestId: params.requestId, url: params.request.url, submittedAt: Date.now() };
        (report.planningRequests ??= []).push(entry);
        planningRequests.set(params.requestId, entry);
      }
      if (/\/api\/agent\/chat(?:\/v2\/stream)?$/.test(params.request.url)) {
        const entry = { requestId: params.requestId, submittedAt: Date.now(), payload: null };
        report.responses.push(entry);
        chatRequests.set(params.requestId, entry);
      }
    }
    if (planningRequests.has(params.requestId)) {
      const entry = planningRequests.get(params.requestId);
      if (method === 'Network.responseReceived') Object.assign(entry, { status: params.response.status, receivedAt: Date.now() });
      if (method === 'Network.loadingFailed') Object.assign(entry, { failedAt: Date.now(), error: params.errorText });
      if (method === 'Network.loadingFinished') Object.assign(entry, { completedAt: Date.now(), encodedDataLength: params.encodedDataLength });
    }
    if (method === 'Network.loadingFinished' && chatRequests.has(params.requestId)) {
      const entry = chatRequests.get(params.requestId);
      chatRequests.delete(params.requestId);
      const pending = window.webContents.debugger.sendCommand('Network.getResponseBody', { requestId: params.requestId })
        .then(({ body, base64Encoded }) => {
          const text = base64Encoded ? Buffer.from(body, 'base64').toString('utf8') : body;
          const events = text.split(/\r?\n/).filter(line => line.startsWith('data: ')).map(line => JSON.parse(line.slice(6)));
          const terminal = events.find(item => ['response_completed', 'response_error'].includes(item.event));
          Object.assign(entry, { events, payload: terminal?.final || terminal || JSON.parse(text), completedAt: Date.now() });
        }).catch(error => report.errors.push('Chat evidence capture: ' + error.message))
        .finally(() => responseReads.delete(pending));
      responseReads.add(pending);
    }
  });
  try {
    await stage('isolated-manual-copy');
    window.maximize();
    await until(`!!${app}?.session?.getState().loaded`, 'workspace mount timed out');
    const manual = await js(`${app}.session.getState()`);
    assert.equal(manual.baseRevision, source.originalSha256);
    if (scenario.inputProbeOnly) {
      report.scope = 'native input diagnostic; no provider or generation';
      await js(`(()=>{const e=document.createElement('a');e.id='generation-input-probe';e.href='https://example.com/';e.textContent='Native link probe';e.style.cssText='position:fixed;left:60%;top:45%;z-index:99999;background:white;color:black;padding:20px';document.body.appendChild(e);})()`);
      await click("document.getElementById('generation-input-probe')");
      const pane = await ensureBrowser();
      const deadline = Date.now() + 30000;
      while (Date.now() < deadline && !pane.snapshot().visible) await delay(250);
      report.sourceBrowser = pane.snapshot();
      assert.equal(report.sourceBrowser.visible, true);
      assert.equal(hash(await fs.readFile(source.originalPath)), source.originalSha256);
      report.status = 'passed'; return;
    }
    await click("document.querySelector('[data-generation-planning=\"open\"]')");
    await stage('create-concept');
    await until("!!document.querySelector('.ip-flw-generation-body details summary')", 'New concept is unavailable');
    await click("document.querySelector('.ip-flw-generation-body details summary')");
    await js(`(()=>{for(const [label,value] of ${JSON.stringify([['Name', 'Native generation verification'], ['Width (m)', scenario.widthMeters], ['Depth (m)', scenario.depthMeters]])}){const e=document.querySelector('.ip-flw-generation-body input[aria-label="'+label+'"]');if(!e)throw Error('Missing concept input: '+label);e.value=String(value);e.dispatchEvent(new Event('input',{bubbles:true}));}})()`);
    await click("document.querySelector('.ip-flw-generation-body details input[type=checkbox]')");
    await shot('00-new-concept');
    await click("[...document.querySelectorAll('.ip-flw-generation-body button')].find(e=>e.textContent==='Create and open')", { navigates: true });
    await until(`!!${app}?.session?.getState().loaded && ${app}.session.getState().layout.layoutId.startsWith('fl-concept-')`, 'new concept did not mount');
    const original = await js(`${app}.session.getState()`);
    report.destination = { layoutId: original.layout.layoutId, revision: original.baseRevision };
    const conceptPath = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', original.layout.layoutId + '.json');
    const conceptHash = hash(await fs.readFile(conceptPath));
    assert.equal(original.layout.placements.length, 0);
    await click("document.querySelector('[data-generation-planning=\"open\"]')");
    await js(`(()=>{window._selectAgent('deviation-analyst');if(!document.getElementById('agentInput').getBoundingClientRect().width)window._toggleAgentPanel();})()`);
    await click("document.getElementById('agentChatNewBtn')");
    let prior = null;
    for (const prompt of [scenario.prompt, scenario.correction].filter(Boolean)) {
      await stage(prior ? 'live-correction' : 'live-generation');
      await js(`(()=>{window._selectAgent('deviation-analyst');const e=document.getElementById('agentInput');e.value=${JSON.stringify(prompt)};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      const start = Date.now();
      const responseIndex = report.responses.length;
      await click("document.getElementById('agentSendBtn')");
      const deadline = Date.now() + 480000;
      let ref, previewObservedAt;
      while (Date.now() < deadline) {
        const completed = report.responses[responseIndex]?.payload;
        if (completed && completed.facility_generation_planning?.status !== 'preview_ready') {
          report.turns.push({ prompt, elapsedSeconds: (Date.now() - start) / 1000, failed: true, payload: completed });
          await persist();
          throw Error('Live conversation completed without a validated preview: ' + JSON.stringify(completed.facility_generation_planning?.blockers || completed.error));
        }
        const observed = await js(`({ref:${app}.workspace.generationPlanningView.activePreviewRef(),pending:!!document.querySelector('#agentMessages .agent-stream-pending')})`);
        if (observed.ref && observed.ref.previewRevision !== (prior?.previewRevision || null)) {
          previewObservedAt ??= Date.now();
          if (!observed.pending) ref = observed.ref;
        }
        if (ref) break;
        await delay(200);
      }
      if (!ref) {
        report.previewHandoff = await js(`(()=>{const state=${app}.session.getState();return {
          preview:${app}.workspace.generationPlanningView.activePreviewRef(),
          pendingMessages:document.querySelectorAll('#agentMessages .agent-stream-pending').length,
          panel:document.querySelector('.ip-flw-generation-body')?.innerText,
          chat:document.getElementById('agentMessages')?.innerText,
          editor:{baseRevision:state.baseRevision,draftRevision:state.draftRevision,
            editorGenerationId:state.editorGenerationId,dirty:state.dirty,busy:state.busy,conflict:state.conflict}
        };})()`);
        await persist();
      }
      assert.ok(ref, 'Live conversation did not produce a new preview within its deadline');
      const layout = await js(`${app}.workspace.generationPlanningView.activeLayout()`);
      report.turns.push({ prompt, elapsedSeconds: (Date.now() - start) / 1000,
        previewVisibleSeconds: (previewObservedAt - start) / 1000, ref, layout,
        response: await js("document.getElementById('agentMessages').innerText") });
      await shot(`turn-${report.turns.length}-preview`);
      prior = ref; await persist();
    }
    if (scenario.correction) assert.notEqual(report.turns[0].ref.candidateRevision, prior.candidateRevision);
    if (scenario.expectedPlacementCounts) assert.deepEqual(report.turns.map(turn => turn.layout.placements.length), scenario.expectedPlacementCounts);
    if (scenario.requireResearch) {
      await stage('source-card-browser');
      const target = "[...document.querySelectorAll('.agent-source-links a')].find(e=>!new URL(e.href).pathname.toLowerCase().endsWith('.pdf'))";
      const url = await js(`(${target}).href`);
      await click(target);
      const pane = await ensureBrowser();
      const deadline = Date.now() + 60000;
      while (Date.now() < deadline && !pane.snapshot().tabs.length) await delay(250);
      const opened = pane.snapshot().tabs.find(tab => tab.url === url);
      assert.ok(opened, 'Source click did not open its URL');
      while (Date.now() < deadline && pane.snapshot().tabs.find(tab => tab.id === opened.id)?.loading) await delay(250);
      report.sourceBrowser = pane.snapshot();
      assert.equal(report.sourceBrowser.visible, true);
      assert.ok(report.sourceBrowser.tabs.some(tab => tab.id === opened.id && !tab.loading && !tab.error), 'Source link did not load in the research pane');
      await shot('00-source-browser', true);
      pane.hide();
    }
    await stage('plan-and-real-three');
    await js(`${app}.workspace.executeCommand('fit')`); await shot('01-plan');
    await js(`${app}.workspace._setViewMode('3d')`);
    await until(`${app}.workspace.threeAdapter?.getDiagnostics().pendingLoads===0 && ${app}.workspace.threeAdapter?.getDiagnostics().assetGroupCount>0`, 'real GLB load timed out', 120000);
    report.three = await js(`${app}.workspace.threeAdapter.getDiagnostics()`);
    assert.equal(report.three.degraded, false);
    await shot('02-three');
    assert.notEqual(report.captures['01-plan'].sha256, report.captures['02-three'].sha256, 'Plan and 3D captures are identical; visual acceptance is not established');
    await stage('apply-unsaved');
    await click("[...document.querySelectorAll('.ip-flw-generation-body button')].find(e=>e.textContent==='Apply unsaved')");
    await until(`(()=>{const error=document.querySelector('.ip-flw-generation-body [role=alert]');if(error)throw Error(error.textContent);return !!${app}.session.getState().designProposalDraft && !${app}.session.getState().busy;})()`, 'Apply failed');
    const applied = await js(`${app}.session.getState()`);
    assert.equal(applied.draftRevision, prior.candidateRevision); assert.equal(applied.dirty, true);
    await shot('03-applied');
    await stage('owned-backend-restart');
    const beforeRestart = runtime.getEvidence();
    await change('restart');
    report.backend = verifyRestart(runtime, beforeRestart);
    const restarted = await js(`${app}.session.getState()`);
    assert.deepEqual(restarted.layout, applied.layout);
    assert.deepEqual(restarted.history, applied.history);
    if (scenario.saveAfterApply === true) {
      await stage('explicit-save');
      await click("[...document.querySelectorAll('[data-facility-ribbon-command=save]')].find(e=>e.getBoundingClientRect().width>0)");
      await until(`!${app}.session.getState().busy && !${app}.session.getState().dirty && !${app}.session.getState().designProposalDraft`, 'Explicit Save did not complete');
      const saved = await js(`${app}.session.getState()`);
      const { updatedAt: _appliedAt, ...candidateBody } = applied.layout;
      const { updatedAt: _savedAt, ...savedBody } = saved.layout;
      assert.deepEqual(savedBody, candidateBody, 'Save changed more than its timestamp');
      assert.deepEqual(JSON.parse(await fs.readFile(conceptPath, 'utf8')), saved.layout);
      await stage('reload-saved-concept');
      await window.webContents.reload();
      await until(`!!${app}?.session?.getState().loaded && ${app}.session.getState().baseRevision === ${JSON.stringify(saved.baseRevision)}`, 'Saved concept did not reload');
      assert.deepEqual(await js(`${app}.session.getState().layout`), saved.layout);
      report.savedRevision = saved.baseRevision;
      await shot('04-saved-reloaded');
    } else {
      await stage('exact-undo');
      await js(`${app}.session.undo()`);
      const restored = await js(`${app}.session.getState()`);
      for (const key of ['layout', 'draftRevision', 'baseRevision', 'selectedIds', 'history', 'dirty']) assert.deepEqual(restored[key], original[key], key);
      report.restoredRevision = restored.draftRevision;
    }
    report.saveCalls = report.requests.filter(item => item.method === 'POST' && /\/save(?:\?|$)/.test(item.url)).length;
    assert.equal(report.saveCalls, scenario.saveAfterApply === true ? 1 : 0);
    assert.equal(hash(await fs.readFile(source.originalPath)), source.originalSha256);
    const copied = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', manual.layout.layoutId + '.json');
    assert.equal(hash(await fs.readFile(copied)), source.originalSha256);
    const finalConceptHash = hash(await fs.readFile(conceptPath));
    if (scenario.saveAfterApply !== true) assert.equal(finalConceptHash, conceptHash);
    report.savedHashes = { manual: source.originalSha256, manualUnchanged: true,
      conceptBefore: conceptHash, conceptAfter: finalConceptHash, conceptUnchanged: finalConceptHash === conceptHash };
    report.backend = runtime.getEvidence(); report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.failure = { code: error.code || null, message: error.message, stack: error.stack };
    await shot('failure').catch(() => {}); throw error;
  } finally {
    report.backend = runtime.getEvidence();
    report.saveCalls = report.requests.filter(item => item.method === 'POST' && /\/save(?:\?|$)/.test(item.url)).length;
    for (const pending of responseReads) await pending;
    window.webContents.debugger.detach(); await persist();
  }
}
module.exports = { run, verifyRestart };
