'use strict';
const { app, BrowserWindow, Menu, ipcMain, dialog, session, shell } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { parseRuntimeOptions, localPath } = require('./runtime-settings.cjs');
const { loadApplicationProfile } = require('./application-profile.cjs');
const { createManagedRuntime } = require('./runtime-supervisor.cjs');
const { createApplicationNetwork } = require('./application-network.cjs');
const { installApplicationLinks } = require('./application-links.cjs');
const { authorizeTransition, transitionStep } = require('./application-lifecycle.cjs');
const { ICON_PATH, brandApplication, brandWindow } = require('./application-branding.cjs');
const { documentURL, createDocumentPreview } = require('./document-preview.cjs');
brandApplication(app);
const root = path.resolve(__dirname, '../..');
let window, runtime, network, closing = false, transition = false, booted = false, profile;
let closeRequested = false, transitionStatus = null;
let acceptanceOutput = null;
let browser = null, browserPromise = null, documents = null, pythonPath, applicationOverlay = false;
let chatgptAccount = null;
let evidenceWrites = Promise.resolve();
const trusted = event => !!window && !window.isDestroyed() && event.sender === window.webContents
  && event.senderFrame === window.webContents.mainFrame && network.local(event.senderFrame.url);
function isDocument(url) { try { documentURL(url, profile.origin); return true; } catch (_) { return false; } }
async function ensureBrowser() {
  if (closing || transition || !booted) throw new Error('Browser is unavailable during an application transition.');
  if (!browserPromise) browserPromise = (async () => {
    documents = await createDocumentPreview({ electron: require('electron'), origin: profile.origin,
      getCredential: () => runtime.getCredential(), python: pythonPath });
    try {
      const pane = await require('./research-pane.cjs').createResearchPane({ window, electron: require('electron'), isApplicationSender: trusted,
        topInset: 42, initialSplit: 0.5, homePage: 'https://www.google.com/', documentPreview: documents, downloadDocument: url => window.webContents.downloadURL(url),
        onLayout: value => { if (!window.isDestroyed()) window.webContents.send('ip-browser-layout', {
          ...value, reservedCssPixels: value.visible && !value.obscuresApp ? value.chrome.width / window.webContents.getZoomFactor() : 0 }); },
        onState: value => { if (!window.isDestroyed()) window.webContents.send('ip-browser-state', value); },
        onFocus: () => window.webContents.send('ip-browser-release-pointer'),
        createDetachedWindow: () => {
          const detached = new BrowserWindow({ title: 'InspectorPro Browser', icon: ICON_PATH, width: 1100, height: 800,
            minWidth: 480, minHeight: 400, show: false, autoHideMenuBar: true, backgroundColor: '#eef2f5',
            webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, webviewTag: false } });
          detached.setMenu(null); brandWindow(detached); return detached;
        },
      });
      browser = pane; pane.suspend(applicationOverlay, 'application-overlay'); return pane;
    } catch (error) { await documents.dispose(); documents = null; throw error; }
  })().catch(error => { browserPromise = null; throw error; });
  return browserPromise;
}
async function openBrowser(url = null) {
  try {
    const pane = await ensureBrowser();
    if (closing || transition) return;
    if (url === null) pane.show();
    else {
      const parsed = new URL(url);
      if (parsed.protocol === 'http:' && !network.local(url)) { parsed.protocol = 'https:'; url = parsed.href; }
      pane.open(url);
    }
  } catch (error) { if (!closing) await message('Browser could not open this page.', error.code || error.message); }
}
ipcMain.handle('ip-browser-command', async (event, request) => {
  if (!trusted(event) || !request || Object.keys(request).some(key => !['action', 'url'].includes(key))) throw new Error('Browser request rejected');
  if (request.action === 'state') return browser?.snapshot() || { visible: false, tabs: [] };
  const pane = await ensureBrowser();
  if (closing || transition) throw new Error('Browser is unavailable during an application transition.');
  if (request.action === 'toggle') { if (pane.snapshot().visible) pane.hide(); else pane.show(); }
  else if (request.action === 'open' && typeof request.url === 'string') await openBrowser(request.url);
  else if (request.action === 'detach') { pane.show(); pane.detach(); }
  else throw new Error('Browser command rejected');
  return pane.snapshot();
});
ipcMain.on('ip-browser-overlay', (event, value) => {
  if (trusted(event)) { applicationOverlay = value === true; browser?.suspend(applicationOverlay, 'application-overlay'); }
});
const observations = new Map();
function observe() {
  return new Promise((resolve, reject) => {
    const id = randomUUID();
    const timer = setTimeout(() => { observations.delete(id); reject(new Error('Workflow observation timed out. The window was kept open.')); }, 5000);
    observations.set(id, { resolve, timer });
    window.webContents.send('ip-application-observe', id);
  });
}
ipcMain.on('ip-application-observed', (event, id, value) => {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) return;
  const item = observations.get(id); if (!item) return;
  clearTimeout(item.timer); observations.delete(id); item.resolve(value);
});
function transitionNotice(detail) {
  transitionStatus = detail;
  if (!window || window.isDestroyed()) return;
  // A renderer notice stays visible even if the native dialog fails to appear.
  window.show(); window.focus();
  window.webContents.send('ip-application-transition-status', detail);
}
async function message(message, detail = '') {
  try {
    return await transitionStep('Application message', signal => dialog.showMessageBox(window,
      { type: 'info', title: 'InspectorPro', message, detail, buttons: ['OK'], signal }), 30000);
  } catch (error) {
    transitionNotice(message + ' ' + detail + ' ' + error.message);
    return { response: 0 };
  }
}
function writeEvidence(evidence, signal) {
  const content = JSON.stringify(evidence, null, 2);
  const write = evidenceWrites.then(() => {
    signal?.throwIfAborted();
    return fs.writeFile(path.join(profile.dataRoot, 'last-application-run.json'), content);
  });
  // Keep the actual write in the queue after a caller's deadline expires.
  // A retry must not overlap it; an expired queued attempt must never start.
  evidenceWrites = write.catch(() => {});
  return write;
}
async function shutdown() {
  const errors = [];
  const attempt = async (label, action, timeoutMs) => {
    try { return await transitionStep(label, action, timeoutMs); }
    catch (error) { errors.push({ step: label, code: error.code || 'desktop_cleanup_failed', message: error.message }); }
  };
  await attempt('Account helper cleanup', () => chatgptAccount?.close());
  if (browserPromise) {
    const pane = await attempt('Browser initialization', () => browserPromise.catch(() => null));
    await attempt('Browser cleanup', () => pane?.dispose());
    if (!errors.length) { browser = null; browserPromise = null; }
  }
  await attempt('Document cleanup', () => documents?.dispose());
  if (!errors.length) documents = null;
  // Always attempt owned backend cleanup, even when a browser/session step fails.
  const cleanup = await attempt('Backend cleanup', () => runtime?.stop(), 30000);
  if (profile) await attempt('Cleanup evidence', signal => writeEvidence({
    backends: runtime?.getEvidence(), network: network?.getEvidence(), cleanup: cleanup || null,
    ...(errors.length ? { cleanupErrors: errors.slice() } : {}),
  }, signal), 5000);
  if (errors.length) throw new Error(errors.map(error => error.step + ': ' + error.message).join('\n'));
  if (!acceptanceOutput && cleanup && (!cleanup.terminationConfirmed || !cleanup.stdioClosed || !cleanup.resourcesClosed)) {
    transitionNotice('Backend cleanup was not fully confirmed. The diagnostic log has been retained. No unrelated server was stopped.');
    await message('Backend cleanup was not fully confirmed.', 'The diagnostic log has been retained. No unrelated server was stopped.');
  }
  return cleanup;
}
async function change(kind, destination) {
  if (closing) {
    if (kind === 'close') transitionNotice('Application shutdown is already in progress.');
    return;
  }
  if (transition) {
    if (kind === 'close') {
      if (transition !== 'close') closeRequested = true;
      transitionNotice('Close requested. Waiting for the current ' + transition + ' step or its deadline. '
        + 'If the Unsaved work dialog is open, respond there; confirmation is still required.');
    }
    return;
  }
  if (!booted) {
    if (kind === 'close') {
      transitionNotice('The application is still loading. Close is unavailable until its workflow state can be checked. Please retry Close.');
      await message('The application is still loading.', 'Close is unavailable until its workflow state can be checked. Please retry Close.');
    }
    return;
  }
  transition = kind;
  try {
    browser?.suspend(true, 'application-transition');
    if (kind === 'close') transitionNotice('Checking for unsaved work before closing...');
    const authorized = await authorizeTransition({ kind, observe, confirmDiscard: async (state, signal) => {
      const result = await dialog.showMessageBox(window, { type: 'warning', title: 'Unsaved work', signal,
        message: kind === 'close' ? 'Close without saving your changes?' : 'Reload without saving your changes?',
        detail: 'Affected workflows: ' + state.affected.join(', ') + '. Cancel to return to the application and use Save.',
        buttons: ['Cancel', kind === 'close' ? 'Close without saving' : 'Reload without saving'], defaultId: 0, cancelId: 0 });
      return result.response === 1;
    }});
    if (!authorized.allowed) {
      transitionNotice(authorized.cancelled ? 'Close or reload cancelled. Your unsaved work remains open.' : authorized.reason);
      if (!authorized.cancelled) await message(authorized.reason);
      return;
    }
    if (kind === 'reload') {
      await transitionStep('Application reload', () => destination ? window.loadURL(destination) : window.webContents.reload(),
        15000, () => window.webContents.stop());
      return;
    }
    if (kind === 'restart') {
      window.webContents.send('ip-application-freeze', true);
      network.setEnabled(false);
      try {
        await transitionStep('Backend restart', signal => runtime.restart({ signal }), 165000);
        network.setEnabled(true); window.webContents.send('ip-application-freeze', false);
      } catch (error) {
        transitionNotice('Backend restart failed. Your draft remains in this window. ' + error.message);
        await message('Backend restart failed. Your draft remains in this window.', error.code || 'See the backend log. Retry Restart backend.');
      }
      return;
    }
    transitionNotice('Closing: cleaning up the browser and owned backend...');
    window.webContents.send('ip-application-freeze', true, 'InspectorPro is closing. Your draft remains in this window until cleanup finishes.');
    network.setEnabled(false);
    await shutdown();
    closing = true;
    window.destroy(); app.quit();
  } catch (error) {
    closing = false;
    transitionNotice('The window was kept open. ' + error.message);
    await message('The window was kept open.', error.message);
  } finally {
    transition = false;
    try { if (!closing) browser?.suspend(false, 'application-transition'); }
    catch (error) { transitionNotice('The browser could not resume. ' + error.message + ' Please retry Close.'); }
    finally {
      if (closeRequested && !closing) { closeRequested = false; void change('close'); }
    }
  }
}
async function external(url) {
  let parsed; try { parsed = new URL(url); } catch (_) { return; }
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) return;
  if ((await dialog.showMessageBox(window, { type: 'question', title: 'Open external link',
    message: 'Open this page in your browser?', detail: parsed.href, buttons: ['Cancel', 'Open'], defaultId: 0, cancelId: 0 })).response === 1) {
    await shell.openExternal(parsed.href);
  }
}
async function start() {
  const options = parseRuntimeOptions(process.argv.slice(app.isPackaged ? 1 : 2));
  acceptanceOutput = options.codexAcceptanceOutput || options.generationAcceptanceOutput
    || options.browserAcceptanceOutput || options.workflowAcceptanceOutput || options.acceptanceOutput || null;
  if (options.startupDiagnosticsOutput || options.researchAcceptanceOutput) throw new Error('Application mode does not use restricted acceptance flags.');
  profile = await loadApplicationProfile(options.profileFile);
  const python = await localPath(options.python);
  pythonPath = python;
  await fs.mkdir(profile.stateRoot, { recursive: true });
  app.setPath('userData', profile.stateRoot);
  if (!app.requestSingleInstanceLock()) { app.quit(); return; }
  app.on('second-instance', () => { if (window) { if (window.isMinimized()) window.restore(); window.show(); window.focus(); } });
  await app.whenReady();
  // Normal mode loads the complete configured application, unlike the isolated
  // milestone fixture. Keep the fixture's 45s gate unchanged; bound cold normal
  // startup separately (the browser launcher already allows 180s).
  runtime = createManagedRuntime({ profile, python, appRoot: root, startupTimeoutMs: 120000, onState: state => {
    if (state.status === 'interrupted' && window && !window.isDestroyed()) {
      network?.setEnabled(false); window.webContents.send('ip-application-freeze', true);
      void message('The backend stopped. Your draft remains in this window.', 'Use Backend > Restart backend. No pending operation is automatically repeated.');
    }
  }});
  await runtime.start();
  const browserSession = session.fromPartition(profile.partition);
  window = new BrowserWindow({ title: 'InspectorPro', width: 1440, height: 860, minWidth: 800, minHeight: 600,
    icon: ICON_PATH,
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#111d2a', symbolColor: '#d8dee6', height: 42 },
    show: false, autoHideMenuBar: true, backgroundColor: '#eef2f5', webPreferences: {
      preload: path.join(__dirname, 'application-preload.cjs'), session: browserSession,
      contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true, webviewTag: false,
    } });
  brandWindow(window);
  network = createApplicationNetwork({ origin: profile.origin, getWindow: () => window, getCredential: () => runtime.getCredential(),
    confirmPermission: async question => (await dialog.showMessageBox(window, { type: 'question', title: 'InspectorPro permission',
      message: question, buttons: ['Deny', 'Allow'], defaultId: 0, cancelId: 0 })).response === 1 });
  network.install(browserSession);
  browserSession.on('will-download', (event, item, contents) => {
    if (!event.defaultPrevented && contents === window.webContents) browser?.trackDownload(item);
  });
  installApplicationLinks({ window, network, external, reload: url => change('reload', url), openBrowser, isDocument });
  window.webContents.on('did-finish-load', () => {
    browser?.refresh();
    if (transitionStatus) transitionNotice(transitionStatus);
  });
  window.webContents.on('will-attach-webview', event => event.preventDefault());
  window.webContents.on('before-input-event', (event, input) => {
    if (input.type === 'keyDown' && (input.key === 'F5' || ((input.control || input.meta) && input.key.toLowerCase() === 'r'))) {
      event.preventDefault(); if (!browser?.reloadFocused()) void change('reload');
    }
  });
  window.on('close', event => { if (!closing) { event.preventDefault(); void change('close'); } });
  chatgptAccount = require('./chatgpt-account.cjs').createChatGPTAccountLauncher({
    python, root, profileFile: options.profileFile,
    onError: () => { if (!closing) void message('ChatGPT sign-in could not open.', 'Your existing account and layout were not changed.'); },
  });
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'File', submenu: [{ label: 'Close', accelerator: 'Alt+F4', click: () => change('close') }] },
    { label: 'Edit', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
    { label: 'View', submenu: [{ label: 'Reload', click: () => change('reload') }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] },
    { label: 'Browser', submenu: [
      { label: 'Toggle browser', accelerator: 'CmdOrCtrl+Shift+B', click: () => { if (browser?.snapshot().visible) browser.hide(); else void openBrowser(); } },
      { label: 'New browser tab', click: () => void ensureBrowser().then(pane => pane.open()).catch(error => message('Browser unavailable', error.message)) },
      { label: 'Open in separate window', click: () => void ensureBrowser().then(pane => { pane.show(); pane.detach(); }).catch(error => message('Browser unavailable', error.message)) },
    ] },
    { label: 'Backend', submenu: [{ label: 'Restart backend', click: () => change('restart') }] },
    { label: 'Sage', submenu: [{ label: 'ChatGPT account', enabled: !!profile.codexRuntime,
      click: () => { if (!chatgptAccount.open()) void message('The ChatGPT account page is already open in your browser.'); } }] },
  ]));
  const url = new URL(profile.origin);
  if (profile.startupLayoutId) url.searchParams.set('facilityLayoutId', profile.startupLayoutId);
  await window.loadURL(url.href);
  booted = true; window.show(); window.focus();
  if (options.acceptanceOutput || options.workflowAcceptanceOutput || options.browserAcceptanceOutput || options.generationAcceptanceOutput || options.codexAcceptanceOutput) {
    let acceptanceTimer;
    const output = options.codexAcceptanceOutput || options.generationAcceptanceOutput || options.browserAcceptanceOutput || options.workflowAcceptanceOutput || options.acceptanceOutput;
    const { run } = options.codexAcceptanceOutput ? require('../tools/application-codex-check.cjs') : options.generationAcceptanceOutput ? require('../tools/application-generation-check.cjs') : options.browserAcceptanceOutput ? require('../tools/application-browser-check.cjs') : options.workflowAcceptanceOutput
      ? require('../tools/application-workflows-check.cjs') : require('../tools/application-check.cjs');
    try {
      const work=run({ window, runtime, network, profile, root, output, observe, change, ensureBrowser });
      if(options.browserAcceptanceOutput) await Promise.race([work,new Promise((_,reject)=>{
        acceptanceTimer=setTimeout(()=>reject(new Error('Browser acceptance exceeded its eight-minute deadline')),480000);
      })]);
      else await work;
    }
    catch (error) {
      await fs.mkdir(output, { recursive: true });
      await fs.writeFile(path.join(output, 'driver-failure.json'), JSON.stringify({
        status: 'failed', message: error.message, stack: error.stack,
      }, null, 2));
      if (options.workflowAcceptanceOutput || options.browserAcceptanceOutput) {
        const file = path.join(output, options.browserAcceptanceOutput ? 'browser-check.json' : 'workflows-check.json');
        const report = await fs.readFile(file, 'utf8').then(JSON.parse).catch(() => ({}));
        await fs.writeFile(file, JSON.stringify({ ...report, status: 'failed', driverError: error.message }, null, 2));
      }
    }
    finally { clearTimeout(acceptanceTimer); closing = true; await shutdown(); window.destroy(); app.quit(); }
  }
}
app.on('before-quit', event => { if (!closing && window && !window.isDestroyed()) { event.preventDefault(); void change('close'); } });
app.on('window-all-closed', () => { if (closing) app.quit(); });
async function failStartup(error) {
  if (!acceptanceOutput) {
    if (app.isReady()) await dialog.showMessageBox({ type: 'error', title: 'InspectorPro startup',
      message: 'InspectorPro could not start.', detail: (error.code || error.message) + '\nNo existing server was replaced.' });
    await runtime?.stop(); closing = true; window?.destroy(); app.exit(1);
    return;
  }
  // Automated runs have no operator to dismiss a startup or cleanup dialog.
  closing = true;
  const startupFailure = { code: error.code || 'desktop_startup_failed', message: error.message };
  let cleanup = null, cleanupError = null;
  try { cleanup = await shutdown(); }
  catch (caught) { cleanupError = { code: caught.code || 'desktop_cleanup_failed', message: caught.message }; }
  try {
    const backends = runtime?.getEvidence() || [];
    const evidence = { backends, network: network?.getEvidence() || null,
      cleanup: cleanup || backends.at(-1)?.cleanup || null, startupFailure,
      ...(cleanupError ? { cleanupError } : {}) };
    await fs.mkdir(acceptanceOutput, { recursive: true });
    await fs.writeFile(path.join(acceptanceOutput, 'driver-failure.json'), JSON.stringify({
      status: 'failed', phase: 'startup', ...startupFailure, desktop: evidence,
    }, null, 2));
    if (profile) await transitionStep('Cleanup evidence', signal => writeEvidence(evidence, signal), 5000);
  } catch (caught) {
    console.error('Could not retain startup failure evidence:', caught.code || caught.message);
  } finally {
    if (window && !window.isDestroyed()) window.destroy();
    app.exit(1);
  }
}
start().catch(failStartup);
