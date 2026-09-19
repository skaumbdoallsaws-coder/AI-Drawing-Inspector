'use strict';

// Standalone diagnostic entry point. Do not import InspectorPro or its preload.
const fs = require('node:fs');
const path = require('node:path');
const { app, BrowserWindow, Menu } = require('electron');
const { createFirstPaintGate, withDeadline } = require('./capture-readiness.cjs');

const output = process.env.INSPECTORPRO_MINIMAL_OUTPUT;
const stateRoot = process.env.INSPECTORPRO_MINIMAL_STATE;
const captureMode = process.env.INSPECTORPRO_MINIMAL_CAPTURE_MODE || 'after-paint';
if (!output || !stateRoot || !path.isAbsolute(output) || !path.isAbsolute(stateRoot)
    || !['after-paint', 'immediate'].includes(captureMode)) {
  console.error('Run this page through tools/electron-minimal.cjs');
  app.exit(1);
} else {
  fs.mkdirSync(output, { recursive: true });
  const report = { schemaVersion: 2, diagnosticRevision: 'capture-readiness-v1',
    status: 'starting', stage: 'setup', captureMode, mainPid: process.pid, versions: process.versions,
    preload: false, inspectorProLoaded: false, events: [],
    checks: { pageLoad: 'pending', pageAssertions: 'pending', isolation: 'pending',
      firstPaint: 'pending', rendererFrames: captureMode === 'immediate' ? 'skipped' : 'pending', capture: 'pending' } };
  const persist = () => fs.writeFileSync(path.join(output, 'minimal-report.json'), JSON.stringify(report, null, 2) + '\n');
  const record = (name, details = {}) => {
    const entry = { at: new Date().toISOString(), name, ...details };
    report.events.push(entry);
    fs.appendFileSync(path.join(output, 'minimal-events.jsonl'), JSON.stringify(entry) + '\n');
    console.log(JSON.stringify(entry));
    persist();
  };
  let finished = false;
  let timer;
  let firstPaint;
  const stage = name => { report.stage = name; record('stage-started', { stage: name }); };
  const pass = (name, details = {}) => { report.checks[name] = 'passed'; record(name + '-passed', details); };
  function fail(error) {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    firstPaint?.dispose();
    report.status = 'failed';
    report.failedStage = report.stage;
    if (report.checks[report.stage] === 'pending') report.checks[report.stage] = 'failed';
    report.error = { name: error.name, message: error.message, code: error.code || null };
    record('failed', { stage: report.stage, ...report.error });
    app.exit(1);
  }
  try {
    app.enableSandbox();
    for (const [key, folder] of [['userData', 'profile'], ['sessionData', 'sessions'], ['temp', 'temp']]) {
      const directory = path.join(stateRoot, folder);
      fs.mkdirSync(directory, { recursive: true });
      app.setPath(key, directory);
    }
    record('main-entered', { sandboxRequested: true });
    app.on('child-process-gone', (_event, details) => record('child-process-gone', details));
    app.on('render-process-gone', (_event, contents, details) => {
      record('render-process-gone', { webContentsId: contents.id, ...details });
      fail(new Error('Minimal renderer ' + details.reason + ' (exit ' + details.exitCode + ')'));
    });
    timer = setTimeout(() => fail(new Error('Minimal page timed out')), 30000);
    app.whenReady().then(async () => {
      record('app-ready');
      Menu.setApplicationMenu(null);
      const window = new BrowserWindow({ width: 900, height: 600, show: false,
        paintWhenInitiallyHidden: true,
        webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false,
          webSecurity: true, allowRunningInsecureContent: false, devTools: false } });
      const contents = window.webContents;
      // Subscribe before loadFile: first paint may precede did-finish-load.
      firstPaint = createFirstPaintGate(window);
      window.once('ready-to-show', () => pass('firstPaint', { windowVisible: window.isVisible() }));
      contents.setWindowOpenHandler(() => ({ action: 'deny' }));
      contents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
      contents.session.setPermissionCheckHandler(() => false);
      contents.on('did-finish-load', () => {
        pass('pageLoad', { rendererPid: contents.getOSProcessId() });
        record('did-finish-load', { rendererPid: contents.getOSProcessId() });
      });
      contents.on('did-fail-load', (_event, code, description) => record('did-fail-load', { code, description }));
      record('window-created', { webContentsId: contents.id });
      stage('pageLoad');
      await contents.loadFile(path.join(__dirname, 'page.html'));
      stage('pageAssertions');
      const evidence = await withDeadline(() => contents.executeJavaScript(`({ title: document.title,
        text: document.querySelector('h1')?.textContent,
        nodeExposed: typeof window.require !== 'undefined' || typeof window.process !== 'undefined',
        readyState: document.readyState, visibilityState: document.visibilityState,
        viewport: { width: innerWidth, height: innerHeight, scale: devicePixelRatio },
        paintEntries: performance.getEntriesByType('paint').map(({name, startTime}) => ({name, startTime})) })`),
      { timeoutMs: 5000, code: 'page_assertions_timeout' });
      const preferences = contents.getLastWebPreferences();
      report.evidence = evidence;
      report.preferences = { sandbox: preferences.sandbox, contextIsolation: preferences.contextIsolation,
        nodeIntegration: preferences.nodeIntegration, webSecurity: preferences.webSecurity,
        preload: preferences.preload || null, backgroundThrottling: contents.getBackgroundThrottling() };
      if (evidence.title !== 'Electron minimal page' || evidence.text !== 'Electron minimal page'
          || evidence.readyState !== 'complete') throw new Error('Minimal page assertions failed');
      pass('pageAssertions');
      stage('isolation');
      if (evidence.nodeExposed || !preferences.sandbox
          || !preferences.contextIsolation || preferences.nodeIntegration || !preferences.webSecurity || preferences.preload) {
        throw new Error('Minimal isolation assertions failed');
      }
      pass('isolation');
      if (captureMode === 'after-paint') {
        stage('firstPaint');
        await firstPaint.wait({ timeoutMs: 10000 });
        stage('rendererFrames');
        // This is a renderer scheduling checkpoint, not proof of compositor readiness.
        report.frameCheckpoint = await withDeadline(() => contents.executeJavaScript(`new Promise(resolve => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve({
            at: performance.now(), readyState: document.readyState, visibilityState: document.visibilityState,
            viewport: { width: innerWidth, height: innerHeight, scale: devicePixelRatio },
            paintEntries: performance.getEntriesByType('paint').map(({name, startTime}) => ({name, startTime}))
          })));
        })`), { timeoutMs: 5000, code: 'renderer_frames_timeout' });
        pass('rendererFrames');
      }
      stage('capture');
      report.captureAttempt = { startedAt: new Date().toISOString(), windowVisible: window.isVisible(),
        minimized: window.isMinimized(), contentBounds: window.getContentBounds(),
        rendererPid: contents.getOSProcessId(), firstPaintObserved: report.checks.firstPaint === 'passed',
        api: 'webContents.capturePage()', options: 'unchanged defaults', attempts: 1 };
      record('capture-started', report.captureAttempt);
      const capture = await withDeadline(() => contents.capturePage(), { timeoutMs: 10000, code: 'capture_timeout' });
      if (capture.isEmpty()) throw new Error('Minimal page screenshot is empty');
      report.captureAttempt.size = capture.getSize();
      fs.writeFileSync(path.join(output, 'minimal-page.png'), capture.toPNG());
      report.captureAttempt.completedAt = new Date().toISOString();
      pass('capture', { size: capture.getSize() });
      report.status = 'passed';
      report.stage = 'complete';
      record('passed', { rendererPid: contents.getOSProcessId() });
      finished = true;
      clearTimeout(timer);
      firstPaint.dispose();
      window.destroy();
      app.quit();
    }).catch(fail);
  } catch (error) { fail(error); }
}
