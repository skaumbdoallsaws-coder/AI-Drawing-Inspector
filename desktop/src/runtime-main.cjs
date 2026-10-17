'use strict';
const electron = require('electron');
const { app, BrowserWindow, Menu, ipcMain, dialog, session } = electron;
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const path = require('node:path');
const { parseRuntimeOptions, loadRuntimeProfile, localPath, hasCompleteStartupDiagnostics } = require('./runtime-settings.cjs');
const { createManagedRuntime } = require('./runtime-supervisor.cjs');
const { createRuntimeNetwork } = require('./runtime-network.cjs');
const { createRuntimePeer } = require('./runtime-peer.cjs');
const { createRuntimeLifecycle } = require('./runtime-lifecycle.cjs');
const { commitRuntimeWindow } = require('./runtime-window-commit.cjs');
const { createFirstPaintGate } = require('../tools/minimal-electron/capture-readiness.cjs');
const fail = (code, message = code) => Object.assign(new Error(message), { code });
let options, profile, supervisor, window, network, peer, lifecycle, currentRuntime, exiting = false;
let rendererFailed = false, startupError = null;
let research = null, researchPromise = null;
const appRoot = path.resolve(__dirname, '../..');
const startupTime = Date.now();
const events = [];
function evidence(event, details = {}) {
  events.push({ event, at: new Date().toISOString(), ...details });
  if (events.length > 250) events.shift();
  if (profile) {
    fsSync.mkdirSync(path.join(profile.dataRoot, 'desktop-logs'), { recursive: true });
    fsSync.writeFileSync(path.join(profile.dataRoot, 'desktop-logs', 'desktop-session.json'), JSON.stringify({ schemaVersion: 1,
      mode: 'desktop-managed', generalEditing: false, researchBrowsing: false, events, backend: supervisor?.getEvidence() || [] }, null, 2));
  }
}
function lockInput() { if (window && !window.isDestroyed()) window.webContents.send('desktop-runtime:input-lock', { locked: true }); }
function updateStatus(value) {
  if (window && !window.isDestroyed()) window.webContents.send('desktop-runtime:status-changed', value);
  evidence('status', { status: value.status, code: value.code || null });
}
function trusted(event) {
  if (!window || window.isDestroyed() || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) return false;
  try { const url = new URL(event.senderFrame.url); return url.origin === profile.origin && url.pathname === '/'; } catch (_) { return false; }
}
function assertSender(event) { if (!trusted(event)) throw fail('desktop_sender_rejected'); }
function publicRuntime() {
  const state = supervisor?.getState();
  if (state?.status !== 'ready' || !currentRuntime) return { schemaVersion: 1, mode: 'desktop-managed', status: state?.status || 'starting',
    capabilities: { generalEditing: false, researchBrowsing: false, facilityAcceptance: false, save: false } };
  return { schemaVersion: 1, mode: 'desktop-managed', status: 'ready', origin: currentRuntime.origin, instanceId: currentRuntime.instanceId,
    identity: currentRuntime.identity, owner: currentRuntime.owner, document: currentRuntime.document,
    capabilities: { ...currentRuntime.capabilities, researchBrowsing: !!research,
      ...(research ? { researchIsolation: 'public-https-proxy-v1' } : {}), save: false } };
}
async function openResearch(url = null) {
  if (!options.researchAcceptanceOutput) throw fail('desktop_research_acceptance_pending', 'Research browsing is awaiting native-window acceptance.');
  if (supervisor?.getState().status !== 'ready' || !network?.enabled || !(await lifecycle.status()).ready) throw fail('desktop_research_backend_not_ready');
  if (!researchPromise) {
    researchPromise = require('./research-pane.cjs').createResearchPane({ window, electron, isApplicationSender: trusted,
      onLayout: value => { if (!window.isDestroyed()) window.webContents.send('desktop-runtime:research-layout', {
        ...value, reservedCssPixels: value.visible && !value.obscuresApp ? value.chrome.width / window.webContents.getZoomFactor() : 0 }); },
      onFocus: () => { if (!window.isDestroyed()) window.webContents.send('desktop-runtime:release-pointer'); }
    }).then(value => { research = value; window.webContents.send('desktop-runtime:research-ready'); return value; })
      .catch(error => { researchPromise = null; throw error; });
  }
  const pane = await researchPromise;
  if (url) pane.open(url); else pane.show();
  return pane;
}
async function closeResearch() { if (researchPromise) { const pane = await researchPromise; await pane.dispose(); research = null; researchPromise = null; } }
async function reportError(error) {
  evidence('error', { code: error.code || 'desktop_operation_failed', message: String(error.message).slice(0, 1024) });
  if (window && !window.isDestroyed()) {
    updateStatus({ status: 'blocked', code: error.code, message: error.message });
    if (!options.acceptanceOutput) await dialog.showMessageBox(window, { type: 'error', title: 'InspectorPro',
      message: error.message || 'The desktop operation could not finish.', detail: 'Your retained recovery data has not been discarded.', buttons: ['Keep open'] });
  }
}
let acceptanceQuiesce = null;
async function closeConnections() {
  if (acceptanceQuiesce) await acceptanceQuiesce();
  if (window && !window.isDestroyed()) await window.webContents.session.closeAllConnections();
}
async function commitWindow(request, control, finalizeDiscard) {
  control.assertCurrent(); lockInput(); network?.setEnabled(false);
  research?.suspend(true);
  // A failed initial start has never loaded the application or received an
  // editor binding. Retain every checkpoint and diagnostic, but do not trap
  // the user in a window because a lifespan that never started has no receipt.
  if (!currentRuntime && request.reason === 'close') {
    const cleanup = await supervisor.stop(); control.assertCurrent();
    evidence('failed-startup-close', cleanup);
    if (!cleanup.terminationConfirmed || !cleanup.stdioClosed) throw fail('desktop_process_cleanup_unverified');
    exiting = true; peer?.dispose(); window.destroy(); app.quit(); return { status: 'closed', applicationCleanupVerified: cleanup.resourcesClosed === true };
  }
  return commitRuntimeWindow({ request, control, finalizeDiscard, stop: () => supervisor.stop(),
    record: cleanup => evidence('backend-stop', cleanup),
    replace: async () => { peer.dispose(); installLifecycle(); rendererFailed = false; network.setEnabled(true); await window.loadURL(applicationURL()); },
    close: async cleanup => {
      if (options.acceptanceOutput) {
        const result = { schemaVersion: 1, status: 'passed', finalClose: 'closed-without-save', saveCalls: network.getEvidence().saveCalls,
          discardFinalized: Boolean(finalizeDiscard), cleanup, backends: supervisor.getEvidence() };
        await fs.writeFile(path.join(options.acceptanceOutput, 'runtime-final-result.json'), JSON.stringify(result, null, 2));
      }
      await closeResearch();
      exiting = true; peer?.dispose(); window.destroy(); app.quit();
    } });
}
async function decideClose(prepared) {
  research?.suspend(true, 'close-dialog');
  try {
    if (options.acceptanceOutput && acceptanceDecision !== null) return acceptanceDecision;
    const canDiscard = prepared.status === 'needsDecision';
    const result = await dialog.showMessageBox(window, { type: 'question', title: 'InspectorPro',
      message: canDiscard ? 'Close without saving these facility edits?' : 'Facility work is still pending or needs recovery.',
      detail: canDiscard ? 'The saved layout will remain unchanged.' : 'Keep the window open until the pending operation is resolved.',
      buttons: canDiscard ? ['Cancel', 'Close without saving'] : ['Keep open'], defaultId: 0, cancelId: 0, noLink: true });
    return canDiscard && result.response === 1 ? 'discard' : 'cancel';
  } finally { research?.suspend(false, 'close-dialog'); }
}
let acceptanceDecision = null;
function installLifecycle() {
  peer = createRuntimePeer({ getContents: () => window?.webContents });
  const editor = {};
  for (const method of ['snapshot','freeze','unfreeze','restoreRecovery','acceptReconciliation','setStartupRecoveryGate']) editor[method] = (args, control) => peer.run(method, args, control);
  lifecycle = createRuntimeLifecycle({ profile, supervisor, editor, lockInput, closeConnections,
    inspectOtherWorkflows: control => peer.run('inspectOtherWorkflows', null, control),
    setBackendAccess: value => network?.setEnabled(value), commitWindow, decideClose, notify: updateStatus });
}
function installIPC() {
  ipcMain.handle('desktop-runtime:status', event => { assertSender(event); return publicRuntime(); });
  ipcMain.handle('desktop-runtime:facility-attach', async (event, value) => {
    assertSender(event); const result = await lifecycle.attach(value);
    if (result.ready && research) {
      window.webContents.send('desktop-runtime:research-ready');
      research.suspend(false); research.suspend(false, 'backend-restart'); research.refresh();
    }
    return result;
  });
  ipcMain.handle('desktop-runtime:facility-persist', (event, value) => { assertSender(event); return lifecycle.persist(value); });
  ipcMain.handle('desktop-runtime:facility-clear', (event, value) => { assertSender(event); return lifecycle.clear(value); });
  ipcMain.handle('desktop-runtime:close', event => { assertSender(event); return lifecycle.close(); });
  ipcMain.handle('desktop-runtime:restart', event => { assertSender(event); return restartBackend(); });
  ipcMain.handle('desktop-runtime:open-research', (event, url) => { assertSender(event); if (typeof url !== 'string') throw fail('research_address_rejected'); return openResearch(url).then(() => ({ opened: true })); });
  ipcMain.on('desktop-runtime:overlay', (event, value) => { if (trusted(event)) research?.suspend(value === true, 'application-overlay'); });
  ipcMain.on('desktop-runtime:facility-reply', (event, value) => { if (trusted(event)) peer.reply(value); });
}
function applicationURL() { return profile.origin + '/' + (profile.acceptanceLayoutId ? '?facilityLayoutId=' + encodeURIComponent(profile.acceptanceLayoutId) : ''); }
async function restartBackend() {
  research?.suspend(true, 'backend-restart');
  try {
    const result = await lifecycle.restart();
    if (result.status === 'reconciled') currentRuntime = supervisor.getState().runtime;
    evidence('restart-result', { status: result.status, code: result.code || null }); return result;
  } finally {
    if (supervisor?.getState().status === 'ready' && network?.enabled) research?.suspend(false, 'backend-restart');
  }
}
async function reviewRecovery() {
  const entries = (await lifecycle.retainedRecovery()).filter(item => !item.supersededBy && item.needsRestore);
  if (!entries.length) { await dialog.showMessageBox(window, { message: 'No retained facility draft needs restoration.', buttons: ['OK'] }); return; }
  if (entries.length !== 1) throw fail('desktop_recovery_review_required', 'Multiple retained checkpoints require review; none was selected or discarded automatically.');
  const result = await dialog.showMessageBox(window, { title: 'Facility recovery', message: 'Restore the retained facility draft?',
    detail: 'Ownership and transaction state will be checked before editing resumes.', buttons: ['Cancel', 'Restore draft'], defaultId: 0, cancelId: 0 });
  if (result.response === 1) { const entry = entries[0]; await lifecycle.restoreRetained(entry.key, entry.checkpointId); }
}
async function finishStartupDiagnostics(startError = null) {
  let error = startError, cleanup = null, backends = [];
  // Diagnostic persistence must never run before attempting owned cleanup.
  try { cleanup = await supervisor?.stop(); }
  catch (stopError) { error ||= stopError; }
  if (!cleanup || !cleanup.terminationConfirmed || !cleanup.stdioClosed || !cleanup.resourcesClosed || cleanup.forced === true) {
    error ||= fail('desktop_startup_diagnostic_cleanup_unverified');
  }
  if (!currentRuntime) error ||= fail('desktop_startup_diagnostic_not_ready');
  try { backends = supervisor?.getEvidence() || []; }
  catch (readError) { error ||= readError; }
  if (!hasCompleteStartupDiagnostics(backends, cleanup)) error ||= fail('desktop_startup_diagnostic_evidence_incomplete');
  let preferences = null;
  try { preferences = window?.webContents?.getLastWebPreferences?.(); }
  catch (readError) { error ||= readError; }
  if (preferences?.sandbox !== true || preferences?.contextIsolation !== true
      || preferences?.nodeIntegration !== false || preferences?.webSecurity !== true) {
    error ||= fail('desktop_startup_diagnostic_isolation_failed');
  }
  const result = { schemaVersion: 1, mode: 'managed-backend-startup-diagnostics',
    status: error ? 'failed' : 'passed', startupDiagnosticsOnly: true, nativeAcceptance: false,
    applicationLoaded: false, facilityAttached: false, editorExercised: false, screenshotCaptured: false,
    generalEditing: false, researchBrowsing: false, saveCalls: 0, startupDeadlineMs: 45000,
    elapsedMs: Date.now() - startupTime, runtimeVerified: Boolean(currentRuntime),
    isolation: preferences ? { sandbox: preferences.sandbox, contextIsolation: preferences.contextIsolation,
      nodeIntegration: preferences.nodeIntegration, webSecurity: preferences.webSecurity } : null,
    cleanup, backends,
    error: error ? { code: error.code || 'desktop_startup_failed' } : null };
  try {
    const output = await localPath(options.startupDiagnosticsOutput, { mustExist: false });
    await fs.mkdir(output, { recursive: true });
    await fs.writeFile(path.join(output, 'startup-diagnostics-result.json'), JSON.stringify(result, null, 2));
  } catch (writeError) {
    result.status = 'failed'; result.diagnosticWriteError = { code: writeError.code || 'desktop_diagnostic_write_failed' };
    // The launcher retains this stream even if the output directory is locked.
    console.error('INSPECTORPRO_STARTUP_DIAGNOSTIC_RESULT ' + JSON.stringify(result));
  } finally {
    exiting = true; peer?.dispose();
    if (window && !window.isDestroyed()) window.destroy();
    app.exit(result.status === 'passed' ? 0 : 1);
  }
  return result;
}
async function start() {
  const browser = session.fromPartition(profile.partition);
  window = new BrowserWindow({ title: 'InspectorPro', width: 1400, height: 850, minWidth: 800, minHeight: 600, show: !(options.acceptanceOutput || options.startupDiagnosticsOutput),
    backgroundColor: '#142333', webPreferences: { session: browser, preload: path.join(__dirname, 'runtime-preload.cjs'), sandbox: true,
      contextIsolation: true, nodeIntegration: false, webSecurity: true, allowRunningInsecureContent: false, devTools: false,
      additionalArguments: ['--inspectorpro-desktop-managed'] } });
  const firstPaintGate = createFirstPaintGate(window);
  installLifecycle(); installIPC();
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//i.test(url)) void openResearch(url).catch(reportError);
    return { action: 'deny' };
  });
  window.webContents.on('will-attach-webview', event => event.preventDefault());
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.on('will-redirect', event => event.preventDefault());
  window.webContents.on('render-process-gone', (_event, detail) => { rendererFailed = true; lockInput(); network?.setEnabled(false); peer.dispose();
    evidence('renderer-failed', { reason: detail.reason, exitCode: detail.exitCode }); });
  window.on('close', event => { if (!exiting) { event.preventDefault(); void lifecycle.close().catch(reportError); } });
  app.on('before-quit', event => { if (!exiting) { event.preventDefault(); void lifecycle.close().catch(reportError); } });
  Menu.setApplicationMenu(Menu.buildFromTemplate([{ label: 'File', submenu: [
    { label: 'Review retained facility draft', click: () => void reviewRecovery().catch(reportError) },
    { label: 'Close', accelerator: 'Alt+F4', click: () => void lifecycle.close().catch(reportError) }] },
    { label: 'View', submenu: [{ label: 'Reload focused view', accelerator: 'CmdOrCtrl+R', click: () => { if (!research?.reloadFocused()) void lifecycle.close('reload').catch(reportError); } }] },
    { label: 'Research', submenu: [{ label: 'Open research pane', enabled: !!options.researchAcceptanceOutput, accelerator: 'CmdOrCtrl+Shift+L', click: () => void openResearch().catch(reportError) },
      { label: 'Hide research pane', click: () => research?.hide() }] },
    { label: 'Backend', submenu: [{ label: 'Restart backend', click: () => void restartBackend().catch(reportError) }] }]));
  window.webContents.on('before-input-event', (event, input) => {
    if (input.type === 'keyDown' && (input.key === 'F5' || ((input.control || input.meta) && input.key.toLowerCase() === 'r'))) {
      event.preventDefault(); void lifecycle.close('reload').catch(reportError);
    }
  });
  await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"></head><body style="background:#142333;color:white;font:18px system-ui;padding:48px">Starting InspectorPro…</body></html>'));
  currentRuntime = await supervisor.start();
  if (options.startupDiagnosticsOutput) { await finishStartupDiagnostics(); return; }
  network = createRuntimeNetwork({ origin: profile.origin, getWindow: () => window, getCredentials: () => supervisor.getCredential(),
    getRequestId: () => lifecycle.getOperationRequestId(), getOwnerSession: () => currentRuntime?.owner.sessionId });
  network.install(browser);
  await window.loadURL(applicationURL());
  evidence('application-loaded', { elapsedMs: Date.now() - startupTime, profileId: profile.profileId, facilityAcceptance: Boolean(profile.acceptanceLayoutId) });
  if (options.acceptanceOutput) {
    if (!profile.acceptanceLayoutId) throw fail('desktop_acceptance_profile_required');
    const { runRuntimeAcceptance } = require('../tools/runtime-integration-check.cjs');
    const report = await runRuntimeAcceptance({ window, lifecycle, supervisor, profile, output: options.acceptanceOutput, peer,
      restartBackend, setCloseDecision(value) { acceptanceDecision = value; },
      setQuiesce(value) { acceptanceQuiesce = value; }, publicRuntime, firstPaintGate,
      getRequestEvidence: () => network.getEvidence(),
      onPending: options.researchAcceptanceOutput ? async () => { const pane = await openResearch(); pane.hide(); } : null });
    evidence('acceptance-result', { status: report.status });
    if (report.status !== 'passed') throw fail('desktop_runtime_acceptance_failed');
    if (options.researchAcceptanceOutput) {
      const pane = await openResearch();
      await require('../tools/research-acceptance.cjs').runResearchAcceptance({ window, pane, profile, peer,
        output: options.researchAcceptanceOutput, getRequestEvidence: () => network.getEvidence() });
    }
    acceptanceDecision = 'discard';
    const closed = await lifecycle.close();
    if (closed.status !== 'committed') throw fail('desktop_runtime_final_close_blocked', JSON.stringify(closed.blockers || []));
  }
}
async function bootstrap() {
  options = parseRuntimeOptions(process.argv.slice(2));
  if (options.workflowAcceptanceOutput || options.browserAcceptanceOutput || options.generationAcceptanceOutput) throw fail('desktop_workflow_check_requires_application');
  profile = await loadRuntimeProfile(options.profileFile); await localPath(options.python);
  if (options.acceptanceOutput && !profile.acceptanceLayoutId) throw fail('desktop_acceptance_profile_required');
  await fs.mkdir(profile.stateRoot, { recursive: true });
  app.setPath('userData', profile.stateRoot); app.setName('InspectorPro');
  if (!app.requestSingleInstanceLock()) throw fail('desktop_profile_already_open', 'This desktop profile is already open.');
  if (options.startupDiagnosticsOutput) await localPath(options.startupDiagnosticsOutput, { mustExist: false });
  supervisor = createManagedRuntime({ profile, python: options.python, appRoot, startupDiagnostics: Boolean(options.startupDiagnosticsOutput), onState(value) {
    if (value.status !== 'ready') { network?.setEnabled(false); lockInput(); }
    updateStatus(value);
  } });
  await app.whenReady(); await start();
}
bootstrap().catch(async error => {
  if (exiting) return;
  if (options?.startupDiagnosticsOutput) { startupError = error; await finishStartupDiagnostics(error); return; }
  startupError = error; evidence('startup-failed', { code: error.code || 'desktop_startup_failed', message: String(error.message).slice(0,1024) });
  if (options?.acceptanceOutput) {
    fsSync.mkdirSync(options.acceptanceOutput, { recursive: true });
    fsSync.writeFileSync(path.join(options.acceptanceOutput, 'startup-failure.json'), JSON.stringify({ status: 'failed', code: error.code, message: error.message, backend: supervisor?.getEvidence() || [] }, null, 2));
    await closeResearch().catch(cleanupError => evidence('research-cleanup-failed', { code: cleanupError.code || 'research_cleanup_failed' }));
    await supervisor?.stop(); exiting = true; if (window && !window.isDestroyed()) window.destroy(); app.exit(1);
  } else if (window && !window.isDestroyed()) await reportError(error);
  else { await app.whenReady(); dialog.showErrorBox('InspectorPro startup', error.message); app.exit(1); }
});
