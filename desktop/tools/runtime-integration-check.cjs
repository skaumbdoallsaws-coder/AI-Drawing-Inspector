'use strict';
// Main-process-only acceptance driver. The ordinary renderer bridge has no
// evaluation, interception, credential, or test-control capability.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { captureRenderedPage } = require('./rendering-capture.cjs');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const fail = code => Object.assign(new Error(code), { code });
const hash = value => crypto.createHash('sha256').update(Buffer.isBuffer(value) ? value : JSON.stringify(value)).digest('hex');
async function until(read, code, timeout = 60000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { const value = await read(); if (value) return value; await delay(50); }
  throw fail(code);
}
async function runRuntimeAcceptance({ window, lifecycle, supervisor, profile, output, peer,
  restartBackend, setCloseDecision, setQuiesce, publicRuntime, firstPaintGate, getRequestEvidence, onPending = null }) {
  if (!profile.acceptanceLayoutId) throw fail('desktop_acceptance_profile_required');
  await fs.mkdir(output, { recursive: true });
  const report = { schemaVersion: 1, mode: 'normal-entry-full-application', status: 'running',
    generalEditing: false, researchBrowsing: false, checks: {}, events: [] };
  const save = () => fs.writeFile(path.join(output, 'runtime-integration-check.json'), JSON.stringify(report, null, 2));
  const stage = async name => { report.stage = name; await save(); };
  const evaluate = code => window.webContents.executeJavaScript(code, true);
  const snapshot = () => peer.run('snapshot');
  const assertFacilityInput = async label => {
    const diagnostics = await evaluate(`(()=>{const root=document.getElementById('trainFacilityLayoutAuthoring');
      return {...window.InspectorProDesktop.getInputLockDiagnostics(),inertAncestor:!!root?.closest('[inert]')};})()`);
    for (const key of ['facilityInputAllowed','attached','nativeInertSupported','facilityConnected']) assert.equal(diagnostics[key], true, label + ':' + key);
    for (const key of ['gateBlocked','forcedLock','frozen','inertAncestor']) assert.equal(diagnostics[key], false, label + ':' + key);
    (report.facilityInputChecks ||= []).push({ label, ...diagnostics });
  };
  const app = '_trainFacilityLayoutAuthoringApp';
  const proposal = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'runtime-proposal.json'), 'utf8'));
  const layoutPath = path.join(profile.dataRoot, 'facility/layouts/local/site-local/layouts', profile.acceptanceLayoutId + '.json');
  let held = null, intercept = null;
  const debug = window.webContents.debugger;
  try {
    report.savedHashBefore = hash(await fs.readFile(layoutPath));
    await stage('full-application-attach');
    await until(async () => {
      const startup = await evaluate('window.InspectorProDesktopRuntimeBridge?.getStartupStatus?.() || {status:"bridge-unavailable"}');
      if (JSON.stringify(startup) !== JSON.stringify(report.startup)) { report.startup = startup; await save(); }
      if (startup.status === 'failed') throw fail(startup.code || 'desktop_runtime_startup_failed');
      return startup.status === 'ready' && (await lifecycle.status()).ready;
    }, 'desktop_full_application_attach_timeout');
    assert.equal((await lifecycle.status()).recoveryRequired, false);
    await assertFacilityInput('attached');
    const preferences = window.webContents.getLastWebPreferences();
    report.isolation = { sandbox: preferences.sandbox, contextIsolation: preferences.contextIsolation,
      nodeIntegration: preferences.nodeIntegration, webSecurity: preferences.webSecurity,
      renderer: await evaluate('({requireType:typeof require,processType:typeof process})') };
    assert.deepEqual(report.isolation, { sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true,
      renderer: { requireType: 'undefined', processType: 'undefined' } });
    report.runtime = publicRuntime();
    report.rendererPid = window.webContents.getOSProcessId();
    const ui = await evaluate(`(()=>{const a=${app},r=document.getElementById('trainFacilityLayoutAuthoring');
      const allowed=[r,...document.querySelectorAll('.facility-layout-ribbon .facility-ribbon-commandbar,#trainFacilityLayoutAssets,#trainRightRailPlayback,#trainFacilityMotionPlaybackHost,#themeToggleBtn')];
      const outside=Array.from(document.querySelectorAll('button,input,select,textarea,a[href]')).filter(e=>!allowed.some(root=>root.contains(e))&&!e.closest('[inert]'));
      return {loaded:!!a&&!!r,canSave:a.session.getState().canSave,outsideUnlocked:outside.length,
        externalCommandSurface:a.workspace.externalCommandSurface,
        duplicateToolbarHidden:getComputedStyle(r.querySelector('.ip-flw-toolbar')).display==='none',
        capabilities:window.InspectorProDesktop.getCapabilities()};})()`);
    assert.equal(ui.loaded, true); assert.equal(ui.canSave, false); assert.equal(ui.outsideUnlocked, 0);
    assert.equal(ui.externalCommandSurface, true); assert.equal(ui.duplicateToolbarHidden, true);
    assert.equal(ui.capabilities.generalEditing, false); assert.equal(ui.capabilities.researchBrowsing, false);
    report.inputGate = ui; report.checks.fullApplicationAndIsolation = 'passed';
    await stage('integrated-facility-controls');
    window.show(); window.focus();
    const clickControl = async selector => {
      const point = await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});
        if(!e || e.disabled || e.closest('[inert]')) throw new Error('Unavailable control: '+${JSON.stringify(selector)});
        const r=e.getBoundingClientRect();if(!r.width||!r.height)throw new Error('Hidden control');
        return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()`);
      window.webContents.sendInputEvent({ type: 'mouseMove', ...point });
      window.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...point });
      window.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...point });
    };
    const ribbon = '.facility-ribbon-commandbar ';
    await clickControl(ribbon + '[data-facility-ribbon-command="pan"]');
    await until(() => evaluate(`${app}.workspace.getCommandStates().pan.active`), 'desktop_ribbon_pan_unresponsive');
    await clickControl(ribbon + '[data-facility-ribbon-command="select"]');
    await until(() => evaluate(`${app}.workspace.getCommandStates().select.active`), 'desktop_ribbon_select_unresponsive');
    await clickControl('#trainFacilityLayoutAssets');
    await until(() => evaluate(`${app}.workspace.assetBrowserState.open`), 'desktop_asset_library_unresponsive');
    await clickControl('#trainFacilityLayoutAssets');
    await until(() => evaluate(`!${app}.workspace.assetBrowserState.open`), 'desktop_asset_library_close_unresponsive');
    const previousTheme = await evaluate('document.documentElement.dataset.theme');
    await clickControl('#themeToggleBtn');
    await until(async () => (await evaluate('document.documentElement.dataset.theme')) !== previousTheme, 'desktop_theme_unresponsive');
    if (await evaluate('document.documentElement.dataset.theme') !== 'light') await clickControl('#themeToggleBtn');
    await clickControl('#trainFacilityLayoutAuthoring [data-view="3d"]');
    await until(() => evaluate(`${app}.workspace.viewMode==='3d'`), 'desktop_3d_tab_unresponsive');
    report.integratedControls = { trustedInput: true, pan: true, select: true, assetLibrary: true, theme: true, threeD: true };
    report.uiCapture = await captureRenderedPage({ window, firstPaintGate, expectedOuterSize: window.getSize(),
      outputPath: path.join(output, 'integrated-facility-3d.png'), record(event, details) { report.events.push({ event, ...details }); } });
    await clickControl('#trainFacilityLayoutAuthoring [data-view="plan"]');
    await until(() => evaluate(`${app}.workspace.viewMode==='plan'`), 'desktop_plan_tab_unresponsive');
    report.checks.integratedFacilityControls = 'passed';
    await stage('two-edits-close-cancel');
    await evaluate(`(async()=>{const s=${app}.session;s.select(${JSON.stringify(proposal.zoneId)});
      await s.editZoneLabel(${JSON.stringify(proposal.zoneId)},${JSON.stringify(proposal.labels.edit1)});
      await s.editZoneLabel(${JSON.stringify(proposal.zoneId)},${JSON.stringify(proposal.labels.edit2)});})()`);
    const manual = await snapshot();
    setCloseDecision('cancel'); assert.equal((await lifecycle.close()).status, 'cancelled');
    assert.deepEqual(await snapshot(), manual); report.checks.twoEditsCloseCancel = 'passed';
    await assertFacilityInput('manual-close-cancel');
    await stage('uncovered-process-map-lifecycle');
    const coverage = await peer.run('inspectOtherWorkflows');
    require('../../static/desktop_workflow_observation.js').assertEmpty(coverage, manual.rendererGeneration);
    report.otherWorkflowCoverage = coverage;
    const backendBeforeGuard = supervisor.getState().runtime.instanceId;
    await evaluate(`(()=>{
      const live=document.getElementById('trainViewportHost');
      if(!live || live.__processMapEditor) throw new Error('Unexpected existing process map');
      const host=document.createElement('div');host.hidden=true;document.body.appendChild(host);
      const editor=window.InspectorProProcessMap.mount(host,{editable:true,revision:'desktop-control',
        map:{schemaVersion:3,mapId:'desktop-control',productId:'desktop-control',
          sourceStructureRevision:'desktop-control',canvasNodes:[],canvasEdges:[]},
        onSave:()=>{throw new Error('Process map Save is forbidden');}});
      live.__processMapEditor=editor;
      window.__desktopProcessMapControl={host,live,editor};
      editor.addProcessStep('operation');editor.addProcessStep('inspection');
      return true;
    })()`);
    const processMapFrame = () => evaluate(`(()=>{const e=window.__desktopProcessMapControl.editor;
      return {map:e.processMap,undo:e.history.undoStack,redo:e.history.redoStack,dirty:e.dirty,
        selectedNodeIds:Array.from(e.selectedNodeIds),transform:e.transform};})()`);
    try {
      const before = await processMapFrame();
      assert.equal(before.dirty, true); assert.equal(before.undo.length, 2);
      const observed = await peer.run('inspectOtherWorkflows');
      assert.equal(observed.workflows.find(row => row.workflowId === 'processMap').dirty, true);
      await assert.rejects(lifecycle.close(), { code: 'desktop_workflow_recovery_not_enabled' });
      assert.deepEqual(await processMapFrame(), before); assert.deepEqual(await snapshot(), manual);
      await assert.rejects(lifecycle.restart(), { code: 'desktop_workflow_recovery_not_enabled' });
      assert.deepEqual(await processMapFrame(), before); assert.deepEqual(await snapshot(), manual);
      assert.equal(supervisor.getState().runtime.instanceId, backendBeforeGuard);
      await assertFacilityInput('uncovered-workflow-refused');
      assert.equal(await evaluate('window.__desktopProcessMapControl.editor.undo()'), true);
      assert.deepEqual((await processMapFrame()).map, before.undo.at(-1));
      report.checks.uncoveredProcessMapBlocksLifecycle = 'passed';
    } finally {
      await evaluate(`(()=>{const c=window.__desktopProcessMapControl;
        if(c){c.editor.destroy();delete c.live.__processMapEditor;c.host.remove();
          delete window.__desktopProcessMapControl;}return true;})()`);
    }
    debug.attach('1.3');
    intercept = async (_event, method, params) => {
      if (method !== 'Fetch.requestPaused') return;
      if (!params.responseStatusCode || params.responseStatusCode < 200 || params.responseStatusCode >= 300) {
        try { await debug.sendCommand('Fetch.continueRequest', { requestId: params.requestId }); } catch (_) {}
        return;
      }
      if (held) { report.interceptionError = 'duplicate_acknowledgment_response'; return; }
      held = { requestId: params.requestId, url: params.request.url, status: params.responseStatusCode };
    };
    debug.on('message', intercept);
    setQuiesce(async () => {
      if (held) { const pending = held; held = null; await debug.sendCommand('Fetch.failRequest', { requestId: pending.requestId, errorReason: 'Aborted' }); }
      await until(() => evaluate('window.__runtimeAcceptanceOperation?.settled'), 'desktop_held_operation_unsettled', 15000);
    });
    for (const kind of ['apply', 'undo']) {
      await stage(kind + '-pending-restart'); held = null;
      await debug.sendCommand('Fetch.enable', { patterns: [{ urlPattern: profile.origin + '/api/facility-layout-design/site-local/' + profile.acceptanceLayoutId + '/transactions/*/' + kind + '/acknowledge', requestStage: 'Response' }] });
      // Do not await the held transport from executeJavaScript. Its settlement
      // is observed separately, and a response is lost only after dispatch.
      await evaluate(`(()=>{const state=window.__runtimeAcceptanceOperation={settled:false,error:null};
        const s=${app}.session;Promise.resolve().then(()=>${kind === 'apply' ? 's.applyDesignProposal(' + JSON.stringify(proposal.proposal) + ')' : 's.undoDesignProposal()'})
          .catch(e=>{state.error={code:e.code||null,message:e.message};}).finally(()=>{state.settled=true;});return true;})()`);
      await until(async () => { const state = await evaluate('window.__runtimeAcceptanceOperation');
        if (state.settled && !held) throw fail(state.error?.code || 'desktop_acknowledgment_not_held'); return held; }, 'desktop_acknowledgment_hold_timeout', 45000);
      assert.equal(report.interceptionError, undefined);
      const pending = await snapshot();
      if (onPending) {
        await onPending(kind); assert.deepEqual(await snapshot(), pending);
        (report.researchDuringPending ||= []).push(kind);
      }
      assert.equal((await lifecycle.close()).status, 'cancelled'); assert.deepEqual(await snapshot(), pending);
      await assertFacilityInput(kind + '-close-cancel');
      const result = await restartBackend();
      assert.equal(result.status, 'reconciled'); assert.equal(result.exactDraftSelectionHistoryRetained, true);
      assert.equal(result.verifiedProposalMetadataAdopted, true);
      await assertFacilityInput(kind + '-reconciled');
      assert.equal(window.webContents.getOSProcessId(), report.rendererPid);
      const after = await snapshot(); if (kind === 'undo') assert.deepEqual(after.editorFrame, manual.editorFrame);
      report[kind] = { status: result.status, beforeFrameHash: hash(pending.editorFrame), afterFrameHash: hash(after.editorFrame),
        resolutions: result.resolutions.map(value => ({ requestId: value.requestId, transactionId: value.transactionId, outcome: value.outcome })) };
      const saveGate = await evaluate(`(async()=>{const s=${app}.session;try{await s.save();return {allowed:true};}catch(e){return {allowed:false,code:e.code,canSave:s.getState().canSave};}})()`);
      assert.equal(saveGate.allowed, false); assert.equal(saveGate.canSave, false);
      report.checks[kind + 'PendingRestart'] = 'passed';
      await debug.sendCommand('Fetch.disable');
    }
    setQuiesce(null); debug.removeListener('message', intercept); intercept = null; debug.detach();
    await stage('full-application-capture');
    report.capture = await captureRenderedPage({ window, firstPaintGate, expectedOuterSize: window.getSize(),
      outputPath: path.join(output, 'full-application-recovered.png'), record(event, details) { report.events.push({ event, ...details }); } });
    report.requests = getRequestEvidence(); report.saveCalls = report.requests.saveCalls;
    assert.equal(report.saveCalls, 0);
    assert.equal(Object.keys(report.requests.transactionRequests).length, 5);
    for (const count of Object.values(report.requests.transactionRequests)) assert.equal(count, 1);
    report.checks.transactionRequestsOnce = 'passed';
    report.savedHashAfter = hash(await fs.readFile(layoutPath)); assert.equal(report.savedHashAfter, report.savedHashBefore);
    report.checks.savedLayoutUnchanged = 'passed'; report.checks.recoveredScreenshot = 'captured-awaiting-visual-review';
    report.status = 'passed'; report.stage = 'awaiting-final-close-and-cleanup';
  } catch (error) { report.status = 'failed'; report.error = { code: error.code || null, message: error.message, stack: error.stack }; }
  finally {
    setQuiesce(null);
    if (debug.isAttached()) {
      if (held) { try { await debug.sendCommand('Fetch.failRequest', { requestId: held.requestId, errorReason: 'Aborted' }); } catch (_) {} }
      if (intercept) debug.removeListener('message', intercept);
      try { await debug.sendCommand('Fetch.disable'); } catch (_) {} debug.detach();
    }
    report.backends = supervisor.getEvidence(); await save();
  }
  return report;
}
module.exports = { runRuntimeAcceptance };
