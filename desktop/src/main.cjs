'use strict';

const path = require('node:path');
const fs = require('node:fs/promises');
const { mkdirSync, writeFileSync, appendFileSync } = require('node:fs');
const { randomUUID } = require('node:crypto');
const { app, BrowserWindow, Menu, ipcMain, dialog, webContents, screen } = require('electron');
const { parseOptions, verifyBackend, bindProfile } = require('./backend-profile.cjs');
const { classifyNavigation } = require('./navigation-policy.cjs');
const { createPermissionPolicy } = require('./permission-policy.cjs');
const { createLifecycleCoordinator } = require('./lifecycle-coordinator.cjs');
const { createFirstPaintGate, withDeadline } = require('../tools/minimal-electron/capture-readiness.cjs');
const { captureRenderedPage } = require('../tools/rendering-capture.cjs');
const { readWindowGeometry } = require('../tools/window-geometry.cjs');
const { planRenderingWindows, assertRenderingDisplay } = require('../tools/rendering-window-policy.cjs');
const { closeRenderingPreview } = require('../tools/close-rendering-preview.cjs');
const { EVIDENCE_SCRIPT, assertRenderingEvidence, assertChromeLayoutCapture } = require('./rendering-evidence.cjs');
const { FIXTURE_FOCUS_SCRIPT, assertFixtureFocusProof } = require('../tools/fixture-focus-proof.cjs');

let smokeReport;
function recordSmoke(name, details = {}) {
  if (!smokeReport) return;
  if (name === 'capture-failed') smokeReport.captureFailure = details;
  smokeReport.events.push({ at: new Date().toISOString(), ...details, name });
  writeFileSync(path.join(options.smokeOutput, 'report.json'), JSON.stringify(smokeReport, null, 2) + '\n');
  appendFileSync(path.join(options.smokeOutput, 'events.jsonl'), JSON.stringify(smokeReport.events.at(-1)) + '\n');
}
function smokeStage(name) { if (smokeReport) { smokeReport.stage = name; recordSmoke('stage-started', { stage: name }); } }
function smokePass(name) { if (smokeReport) { smokeReport.checks[name] = 'passed'; recordSmoke(name + '-passed'); } }
function startupFailed(error) {
  console.error('Desktop startup refused: ' + error.message);
  if (smokeReport) {
    smokeReport.status = 'failed'; smokeReport.failedStage = smokeReport.stage;
    smokeReport.error = { message: error.message, code: error.code || null };
    if (smokeReport.checks[smokeReport.stage] === 'pending') smokeReport.checks[smokeReport.stage] = 'failed';
    try { recordSmoke('failed', { stage: smokeReport.stage, ...smokeReport.error }); }
    catch (logError) { console.error('Cannot preserve rendering report: ' + logError.message); }
  }
  app.exit(1);
}

let options;
try { options = parseOptions(process.argv.slice(2), path.resolve(__dirname, '..')); }
catch (error) { console.error(error.message); app.exit(1); }

if (options) {
  try {
  if (options.smokeOutput) {
    mkdirSync(options.smokeOutput, { recursive: true });
    smokeReport = { schemaVersion: 2, diagnosticRevision: 'rendering-readiness-v1',
      geometryDiagnosticsRevision: 'window-geometry-v1', inputLockRevision: 'html-root-lock-v1', status: 'running',
      stage: 'setup', expectedPage: options.expectedPage, events: [], captures: {},
      checks: Object.fromEntries(['backendIdentity', 'inputLock', 'markup', 'isolation', 'firstPaint',
        'wideCapture', 'narrowCapture', 'lifecycleClose'].map(key => [key, 'pending'])) };
    recordSmoke('main-entered', { pid: process.pid });
  }
  mkdirSync(path.join(options.stateRoot, 'sessions'), { recursive: true });
  mkdirSync(path.join(options.stateRoot, 'temp'), { recursive: true });
  app.setPath('userData', options.stateRoot);
  app.setPath('sessionData', path.join(options.stateRoot, 'sessions'));
  app.setPath('temp', path.join(options.stateRoot, 'temp'));
  app.setName('InspectorPro Desktop Preview');
  if (!app.requestSingleInstanceLock()) { console.error('Desktop profile is already locked or its instance lock is unavailable'); app.exit(1); }
  else app.whenReady().then(start).catch(startupFailed);
  } catch (error) { startupFailed(error); }
}

async function start() {
  smokeStage('backendIdentity');
  const verified = await verifyBackend({ origin: options.origin, identityFile: options.identityFile });
  const profile = await bindProfile(options.stateRoot, verified);
  if (smokeReport) smokeReport.backendIdentity = verified.identity;
  smokePass('backendIdentity');
  let windowSizePolicy = null;
  if (smokeReport) {
    smokeStage('windowSizePolicy');
    windowSizePolicy = planRenderingWindows(screen.getPrimaryDisplay());
    smokeReport.windowSizePolicy = windowSizePolicy;
    smokeReport.referenceWideCapture = { requestedOuterSize: [1440, 960],
      status: windowSizePolicy.exactWide ? 'pending' : 'not-exercised',
      ...(!windowSizePolicy.exactWide ? { reason: 'The selected display work area cannot fit the nominal 1440x960 DIP window.' } : {}) };
    recordSmoke('window-size-policy-selected', { policy: windowSizePolicy });
  }
  const wideSize = windowSizePolicy?.wide || [1440, 960], narrowSize = windowSizePolicy?.narrow || [900, 700];
  let requestedOuterSize = wideSize;
  const window = new BrowserWindow({ title: 'InspectorPro · Desktop rendering preview',
    ...(windowSizePolicy ? { ...windowSizePolicy.wideBounds, useContentSize: false, frame: true } : {}),
    width: wideSize[0], height: wideSize[1], minWidth: 800, minHeight: 600, show: !options.smokeOutput,
    paintWhenInitiallyHidden: true, backgroundColor: '#142333', webPreferences: { preload: path.join(__dirname, 'preload.cjs'),
      partition: profile.partition, sandbox: true, contextIsolation: true, nodeIntegration: false,
      webSecurity: true, allowRunningInsecureContent: false, spellcheck: false, devTools: false } });
  const contents = window.webContents;
  const firstPaint = options.smokeOutput ? createFirstPaintGate(window) : null;
  // The planned target never follows a later OS clamp or monitor change.
  let windowPolicyFailure = null;
  const assertWindowPolicy = () => {
    if (!windowSizePolicy) return;
    if (windowPolicyFailure) throw windowPolicyFailure;
    try {
      const bounds = window.getBounds();
      assertRenderingDisplay(windowSizePolicy, screen.getDisplayMatching(bounds));
      const area = windowSizePolicy.availableWorkArea;
      if (bounds.x < area.x || bounds.y < area.y || bounds.x + bounds.width > area.x + area.width
          || bounds.y + bounds.height > area.y + area.height) {
        throw Object.assign(new Error('Rendering window left the selected display work area'), { code: 'rendering_window_outside_work_area' });
      }
    } catch (error) { windowPolicyFailure = error; throw error; }
  };
  const latchWindowPolicy = phase => {
    if (windowPolicyFailure) return;
    try { assertWindowPolicy(); }
    catch (error) { recordSmoke('window-size-policy-invalidated', { phase, code: error.code || null, message: error.message }); }
  };
  const readDiagnostics = () => readWindowGeometry({ window, screen, requestedOuterSize });
  const observeGeometry = phase => {
    if (smokeReport) recordSmoke('window-geometry', { phase, geometry: readDiagnostics() });
  };
  if (firstPaint) {
    observeGeometry('after-construction');
    window.once('ready-to-show', () => { observeGeometry('first-paint'); smokePass('firstPaint'); });
    window.once('closed', () => firstPaint.dispose());
    app.on('child-process-gone', (_event, details) => recordSmoke('child-process-gone', { details }));
    window.on('resize', () => { latchWindowPolicy('resize-event'); observeGeometry('resize-event'); });
    window.on('move', () => { latchWindowPolicy('move-event'); observeGeometry('move-event'); });
    const onDisplayMetricsChanged = (_event, changedDisplay) => {
      // The notification snapshot can differ from current state if a monitor
      // changed and restored before Electron delivered its queued event.
      if (!windowPolicyFailure && changedDisplay?.id === windowSizePolicy.display.id) {
        try { assertRenderingDisplay(windowSizePolicy, changedDisplay); }
        catch (error) {
          windowPolicyFailure = error;
          recordSmoke('window-size-policy-invalidated', { phase: 'display-metrics-snapshot', code: error.code || null, message: error.message });
        }
      }
      latchWindowPolicy('display-metrics-current'); observeGeometry('display-metrics-changed');
    };
    const onDisplayRemoved = (_event, removedDisplay) => {
      if (!windowPolicyFailure && removedDisplay?.id === windowSizePolicy.display.id) {
        windowPolicyFailure = Object.assign(new Error('The selected rendering display was removed'), { code: 'rendering_display_removed' });
        recordSmoke('window-size-policy-invalidated', { phase: 'display-removed', code: windowPolicyFailure.code, message: windowPolicyFailure.message });
      }
      latchWindowPolicy('display-removed-current'); observeGeometry('display-removed');
    };
    screen.on('display-metrics-changed', onDisplayMetricsChanged);
    screen.on('display-removed', onDisplayRemoved);
    window.once('closed', () => {
      screen.removeListener('display-metrics-changed', onDisplayMetricsChanged);
      screen.removeListener('display-removed', onDisplayRemoved);
    });
  }
  const policy = createPermissionPolicy({ mode: 'rendering-spike', applicationOrigin: options.origin,
    applicationWebContentsId: contents.id });
  contents.session.setPermissionRequestHandler(policy.requestHandler);
  contents.session.setPermissionCheckHandler(policy.checkHandler);
  contents.session.setDevicePermissionHandler(policy.deviceHandler);
  contents.session.setDisplayMediaRequestHandler(policy.displayMediaHandler);
  contents.session.on('will-download', event => event.preventDefault());
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  const guardNavigation = event => {
    if (classifyNavigation(event.url, options.origin).action !== 'allow-app') event.preventDefault();
  };
  contents.on('will-navigate', guardNavigation);
  contents.on('will-redirect', guardNavigation);
  contents.on('will-attach-webview', event => event.preventDefault());
  // The rendering spike has no external embedded content and no privileged network credential.
  // Restrict its application requests too; the backend independently denies non-allowlisted APIs.
  contents.session.webRequest.onBeforeRequest((details, callback) => {
    const url = new URL(details.url);
    const same = url.origin === options.origin;
    const allowed = same && ['GET', 'HEAD'].includes(details.method);
    callback({ cancel: !allowed && !['data:', 'blob:', 'devtools:'].includes(url.protocol) });
  });
  let rendererGeneration = randomUUID(); let frozen = false; let closing = false; let actionRunning = false;
  let rendererFailed = false;
  const identity = { backendId: verified.identity.backendId, storeId: verified.identity.storeId, principalId: 'isolated-rendering-fixture' };
  const snapshot = ({ intentId }) => ({ intentId, rendererGeneration, stateSequence: 0, identity,
    // Only this verified inert fixture can close after a crash without editor recovery.
    coverage: [{ workflowId: 'application', status: frozen || rendererFailed ? 'covered' : 'unknown' }],
    documents: [], pendingOperations: [], activeJobs: [], recovery: { status: 'none' } });
  const coordinator = createLifecycleCoordinator({ identity, prepare: snapshot, revalidate: snapshot,
    cancel: async () => {}, commit: async ({ reason }) => {
      if (reason === 'reload') { frozen = false; rendererFailed = false; rendererGeneration = randomUUID(); contents.reload(); }
      else { closing = true; window.close(); }
    } });
  async function requestLifecycle(reason) {
    if (actionRunning) return;
    actionRunning = true;
    try {
      const decision = await coordinator.prepare(reason);
      if (decision.status === 'ready') return await coordinator.commit(decision);
      else {
        await coordinator.cancel(decision.intentId);
        if (options.smokeOutput) throw new Error('Lifecycle blocked: ' + JSON.stringify(decision.blockers));
        await dialog.showMessageBox(window, { type: 'info', title: 'Preview is loading',
          message: 'The rendering preview has not finished its input-lock handshake. Please wait, then close again.', buttons: ['OK'] });
      }
    } finally { actionRunning = false; }
  }
  const trusted = event => event.sender === contents && event.senderFrame === contents.mainFrame &&
    new URL(event.senderFrame.url).origin === options.origin;
  ipcMain.on('desktop-spike:frozen', event => { if (trusted(event)) frozen = true; });
  ipcMain.on('desktop-spike:close', event => { if (trusted(event)) void requestLifecycle('close'); });
  contents.on('render-process-gone', (_event, details) => {
    frozen = false; rendererFailed = true;
    recordSmoke('render-process-gone', { details });
    if (options.smokeOutput) startupFailed(new Error('Rendering process ' + details.reason));
  });
  window.on('close', event => { if (!closing) { event.preventDefault(); void requestLifecycle('close'); } });
  app.on('before-quit', event => { if (!closing) { event.preventDefault(); void requestLifecycle('close'); } });
  app.on('window-all-closed', () => {
    closing = true;
    // Acceptance records the completed lifecycle decision before quitting.
    if (!options.smokeOutput) app.quit();
  });
  observeGeometry('before-menu');
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'File', submenu: [{ label: 'Close preview', accelerator: 'Alt+F4', click: () => void requestLifecycle('close') }] },
    { label: 'View', submenu: [{ label: 'Reload preview', accelerator: 'CmdOrCtrl+R', click: () => void requestLifecycle('reload') },
      { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] },
  ]));
  observeGeometry('after-menu');
  contents.on('page-title-updated', event => event.preventDefault());
  smokeStage('pageLoad');
  await contents.loadURL(options.origin + '/');
  if (options.smokeOutput) {
    await fs.mkdir(options.smokeOutput, { recursive: true });
    smokeStage('inputLock');
    const deadline = Date.now() + 10000;
    while (!frozen && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
    if (!frozen) throw new Error('Preload input lock did not initialize');
    smokePass('inputLock');
    // This bounded test hook runs only when explicitly requested by the local CLI.
    smokeStage('markup');
    let evidence;
    const markupDeadline = Date.now() + 15000;
    do {
      evidence = await withDeadline(() => contents.executeJavaScript(EVIDENCE_SCRIPT), { timeoutMs: 5000, code: 'markup_read_timeout' });
      if (evidence.markup.kind === options.expectedPage) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    } while (Date.now() < markupDeadline);
    Object.assign(smokeReport, evidence);
    assertRenderingEvidence(evidence, options.expectedPage);
    if (options.expectedPage === 'inert-fixture') {
      // Only this disposable fixture contains the parser-time focus baseline.
      // The full application is inspected without issuing focus actions.
      smokeReport.fixtureFocusProof = await withDeadline(() => contents.executeJavaScript(FIXTURE_FOCUS_SCRIPT),
        { timeoutMs: 5000, code: 'fixture_focus_timeout' });
      recordSmoke('fixture-focus-proof', { proof: smokeReport.fixtureFocusProof });
      assertFixtureFocusProof(smokeReport.fixtureFocusProof);
    }
    const recheckInputLock = async (phase, capture = null) => {
      const current = await withDeadline(() => contents.executeJavaScript(EVIDENCE_SCRIPT),
        { timeoutMs: 5000, code: 'input_lock_read_timeout' });
      recordSmoke('input-lock-rechecked', { phase, ...current });
      assertRenderingEvidence(current, options.expectedPage);
      if (capture && options.expectedPage === 'full-application') assertChromeLayoutCapture(current.chromeLayout, capture);
    };
    smokePass('markup');
    smokeStage('isolation');
    const preferences = contents.getLastWebPreferences();
    smokeReport.preferences = { sandbox: preferences.sandbox, contextIsolation: preferences.contextIsolation,
      nodeIntegration: preferences.nodeIntegration, webSecurity: preferences.webSecurity,
      allowRunningInsecureContent: preferences.allowRunningInsecureContent };
    smokeReport.electron = process.versions.electron;
    smokeReport.researchViews = window.contentView.children.length;
    smokeReport.webContentsCount = webContents.getAllWebContents().length;
    if (!preferences.sandbox || !preferences.contextIsolation || preferences.nodeIntegration
        || !preferences.webSecurity || preferences.allowRunningInsecureContent
        || smokeReport.researchViews !== 0 || smokeReport.webContentsCount !== 1) throw new Error('Native renderer isolation assertion failed');
    smokePass('isolation');
    smokeStage('firstPaint');
    await firstPaint.wait({ timeoutMs: 10000 });
    smokeStage('wideCapture');
    await recheckInputLock('before-wide-capture');
    assertWindowPolicy();
    smokeReport.captures.wide = await captureRenderedPage({ window, firstPaintGate: firstPaint,
      expectedOuterSize: wideSize, outputPath: path.join(options.smokeOutput, 'desktop-wide.png'),
      readDiagnostics, record: recordSmoke });
    assertWindowPolicy();
    await recheckInputLock('after-wide-capture', smokeReport.captures.wide);
    if (windowSizePolicy.exactWide) smokeReport.referenceWideCapture.status = 'passed';
    smokePass('wideCapture');
    smokeStage('narrowCapture');
    observeGeometry('before-narrow-size-request');
    requestedOuterSize = narrowSize;
    assertWindowPolicy();
    window.setSize(narrowSize[0], narrowSize[1]);
    observeGeometry('after-narrow-size-request');
    assertWindowPolicy();
    await recheckInputLock('before-narrow-capture');
    smokeReport.captures.narrow = await captureRenderedPage({ window, expectedOuterSize: narrowSize,
      outputPath: path.join(options.smokeOutput, 'desktop-narrow.png'), readDiagnostics, record: recordSmoke });
    assertWindowPolicy();
    await recheckInputLock('after-narrow-capture', smokeReport.captures.narrow);
    smokePass('narrowCapture');
    smokeStage('lifecycleClose');
    const closed = await closeRenderingPreview({ window, requestClose: () => requestLifecycle('close') });
    if (closed?.status !== 'committed' || !window.isDestroyed()) throw new Error('Inert preview lifecycle close did not commit');
    smokePass('lifecycleClose');
    smokeReport.status = 'passed'; smokeReport.stage = 'complete'; recordSmoke('passed');
    firstPaint.dispose();
    app.quit();
  }
}
