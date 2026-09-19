'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');

const mainPath = path.resolve(__dirname, '../src/main.cjs');
const mainSource = fs.readFileSync(mainPath, 'utf8');
const clone = value => JSON.parse(JSON.stringify(value));
const displayFor = (width = 1536, height = 816) => ({ id: 17, scaleFactor: 1.25,
  bounds: { x: 0, y: 0, width, height: height + 48 }, workArea: { x: 0, y: 0, width, height } });

function chromeLayout(width = 886, height = 638) {
  const viewport = { x: 0, y: 0, width, height };
  const item = (id, x, y, w, h) => ({ id, visible: true, bounds: { x, y, width: w, height: h },
    clipBounds: { ...viewport }, labelBounds: [{ x: x + 4, y: y + 5, width: w - 8, height: 15 }], ancestorIds: [] });
  return { revision: 'chrome-layout-v1', viewport: { width, height }, violations: [],
    toolbar: { bounds: { x: 0, y: 0, width, height: 42 }, controls: [item('brand', 8, 4, 130, 32), item('search', 160, 4, 150, 32)] },
    tabbar: { bounds: { x: 286, y: 42, width: width - 332, height: 60 },
      tabs: ['drawing', '3dmodel', 'assembly', 'training', 'dfm', 'report', 'usage', 'sessions']
        .map((id, index) => item(id, 290 + index % 4 * 130, 44 + Math.floor(index / 4) * 28, 126, 26)) } };
}

/**
 * Run the real main entry point and real window-policy/lifecycle helpers, with
 * Electron, backend I/O, filesystem writes and capture replaced. This tests
 * orchestration only; it does not claim native paint, preload or GPU coverage.
 */
async function runMain({ display = displayFor(), smoke = true, actualSize, onCapture, initiallyLocked = true, expectedPage = 'inert-fixture', onProbe } = {}) {
  const files = new Map(), instances = [], captureCalls = [], errors = [];
  const ipcMain = new EventEmitter(), app = new EventEmitter(), screen = new EventEmitter();
  const origin = 'http://127.0.0.1:8197';
  const options = { origin, identityFile: '/mock/identity.json', stateRoot: '/mock/state',
    smokeOutput: smoke ? '/mock/output' : null, expectedPage };
  let currentDisplay = clone(display), primaryReads = 0, finish;
  const finished = new Promise(resolve => { finish = resolve; });
  const report = () => {
    const entry = [...files].find(([name]) => path.basename(name) === 'report.json');
    return entry ? JSON.parse(entry[1]) : null;
  };
  Object.assign(app, {
    setPath() {}, setName() {}, requestSingleInstanceLock: () => true,
    whenReady: () => ({ then(start) {
      const running = Promise.resolve().then(start);
      running.then(() => { if (!smoke) finish({ regularCompleted: true }); }, () => {});
      return running;
    } }),
    exit: code => finish({ code }), quit: () => finish({ code: 0 }),
  });
  Object.assign(screen, {
    getPrimaryDisplay: () => { primaryReads++; return currentDisplay; },
    getDisplayMatching: () => currentDisplay,
    getAllDisplays: () => [currentDisplay],
    dipToScreenRect: (_window, rect) => ({ ...rect,
      width: rect.width * currentDisplay.scaleFactor, height: rect.height * currentDisplay.scaleFactor }),
  });
  class FakeWindow extends EventEmitter {
    constructor(settings) {
      super();
      this.settings = clone(settings);
      this.bounds = { x: settings.x || 0, y: settings.y || 0,
        width: actualSize?.[0] ?? settings.width, height: actualSize?.[1] ?? settings.height };
      this.destroyed = false; this.locked = initiallyLocked;
      this.contentView = { children: [] };
      this.webContents = new EventEmitter();
      const contents = this.webContents;
      contents.id = 1;
      contents.mainFrame = { url: origin + '/' };
      contents.session = new EventEmitter();
      for (const method of ['setPermissionRequestHandler', 'setPermissionCheckHandler',
        'setDevicePermissionHandler', 'setDisplayMediaRequestHandler']) contents.session[method] = () => {};
      contents.session.webRequest = { onBeforeRequest() {} };
      contents.setWindowOpenHandler = () => {};
      contents.getLastWebPreferences = () => settings.webPreferences;
      contents.getZoomFactor = () => 1;
      contents.getURL = () => origin + '/';
      contents.loadURL = async () => {
        ipcMain.emit('desktop-spike:frozen', { sender: contents, senderFrame: contents.mainFrame });
        this.emit('ready-to-show');
      };
      let probeIndex = 0;
      contents.executeJavaScript = async () => { const current = { title: 'InspectorPro fixture', bodyChildren: 1, frozen: this.locked,
        lockEvidence: { uniqueBanner: true, unlockedRootCount: this.locked ? 0 : 1, totalRoots: 1 },
        preloadLockDiagnostics: { schemaVersion: 1, acknowledged: true,
          current: { allProtectedRootsLocked: this.locked, protectedRootCount: 1 } },
        desktopMarker: 'rendering-spike', nodeExposed: false, banner: 'Preview',
        capabilities: { schemaVersion: 1, mode: 'rendering-spike', interactive: false,
          researchBrowsing: false, managedBackend: false, durableWorkflowRecovery: false },
        markup: { kind: 'inert-fixture', fixture: { visible: true } } };
        if (expectedPage === 'full-application') {
          current.title = 'InspectorPro'; current.chromeLayout = chromeLayout(...this.getContentSize());
          current.markup = { kind: 'full-application', profileLabel: 'Profiles: 0', contextRibbonExists: true, errorText: '',
            elements: Object.fromEntries(['toolbar', 'main', 'viewport', 'tabs', 'content', 'upload', 'empty'].map(key => [key, { visible: true }])),
            tabs: ['drawing', '3dmodel', 'assembly', 'training', 'dfm', 'report', 'usage', 'sessions'].map(id => ({ id, selected: id === 'drawing' })) };
        }
        if (onProbe) onProbe({ window: this, evidence: current, index: probeIndex });
        probeIndex++; return current;
      };
      instances.push(this);
    }
    getBounds() { return { ...this.bounds }; }
    getNormalBounds() { return this.getBounds(); }
    getSize() { return [this.bounds.width, this.bounds.height]; }
    getContentSize() { return [this.bounds.width - 14, this.bounds.height - 63]; }
    getContentBounds() { const [width, height] = this.getContentSize(); return { ...this.bounds, width, height }; }
    getMinimumSize() { return [800, 600]; }
    getMaximumSize() { return [0, 0]; }
    isDestroyed() { return this.destroyed; }
    isVisible() { return this.settings.show; }
    isMinimized() { return false; }
    isMaximized() { return false; }
    isFullScreen() { return false; }
    isMenuBarVisible() { return true; }
    isMenuBarAutoHide() { return false; }
    setSize(width, height) { this.bounds.width = width; this.bounds.height = height; this.emit('resize'); }
    close() {
      let prevented = false;
      this.emit('close', { preventDefault() { prevented = true; } });
      if (!prevented) setImmediate(() => {
        this.destroyed = true; this.emit('closed'); app.emit('window-all-closed');
      });
    }
  }
  const captureRenderedPage = async args => {
    const call = { expected: clone(args.expectedOuterSize), actual: args.window.getSize(), reportBefore: report() };
    captureCalls.push(call);
    if (call.actual.some((value, index) => value !== call.expected[index])) {
      throw Object.assign(new Error('Unexpected native dimensions'), { code: 'capture_outer_size_mismatch' });
    }
    if (onCapture) await onCapture({ index: captureCalls.length - 1, screen, window: args.window, report,
      originalDisplay: clone(display), setDisplay: value => { currentDisplay = clone(value); } });
    return { outerSize: { width: call.actual[0], height: call.actual[1] }, bytes: 100,
      outputPath: args.outputPath, attempts: 1, frameCheckpoint: { viewport: { width: args.window.getContentSize()[0], height: args.window.getContentSize()[1] } } };
  };
  const mockedModules = {
    electron: { app, BrowserWindow: FakeWindow, ipcMain, screen,
      Menu: { buildFromTemplate: template => template, setApplicationMenu() {} },
      dialog: { showMessageBox: async () => ({ response: 0 }) },
      webContents: { getAllWebContents: () => instances.map(item => item.webContents) } },
    'node:fs': { mkdirSync() {}, writeFileSync: (name, data) => files.set(name, data), appendFileSync() {} },
    'node:fs/promises': { mkdir: async () => {} },
    './backend-profile.cjs': { parseOptions: () => options,
      verifyBackend: async () => ({ identity: { backendId: 'backend', storeId: 'store' } }),
      bindProfile: async () => ({ partition: 'persist:mock' }) },
    '../tools/rendering-capture.cjs': { captureRenderedPage },
    '../tools/fixture-focus-proof.cjs': { FIXTURE_FOCUS_SCRIPT: 'fixture focus double', assertFixtureFocusProof() {} },
  };
  const localRequire = name => Object.hasOwn(mockedModules, name) ? mockedModules[name]
    : require(name.startsWith('.') ? path.resolve(path.dirname(mainPath), name) : name);
  vm.runInNewContext(mainSource, { require: localRequire, __dirname: path.dirname(mainPath),
    process: { argv: ['electron', mainPath], pid: 777, versions: { electron: '44.3.0' } },
    console: { error: message => errors.push(message) }, URL, setTimeout, clearTimeout, setImmediate,
  }, { filename: mainPath, timeout: 1000 });
  let timer;
  try {
    const outcome = await Promise.race([finished, new Promise((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error('Mocked main did not settle')), 2000);
    })]);
    return { ...outcome, report: report(), instances, captureCalls, primaryReads, screen, errors };
  } finally { clearTimeout(timer); }
}

test('main constructs the planned work-area window and passes both exact effective targets to capture', async () => {
  const result = await runMain();
  assert.equal(result.code, 0);
  assert.equal(result.report.status, 'passed');
  const settings = result.instances[0].settings;
  assert.deepEqual([settings.x, settings.y, settings.width, settings.height], [48, 0, 1440, 816]);
  assert.equal(settings.useContentSize, false); assert.equal(settings.frame, true);
  assert.deepEqual(result.captureCalls.map(call => call.expected), [[1440, 816], [900, 700]]);
  assert.notEqual(result.report.referenceWideCapture.status, 'passed');
  assert.deepEqual(result.report.referenceWideCapture.requestedOuterSize, [1440, 960]);
  assert.equal(result.screen.listenerCount('display-metrics-changed'), 0);
  assert.equal(result.screen.listenerCount('display-removed'), 0);
  assert.deepEqual(Object.fromEntries(['sandbox', 'contextIsolation', 'nodeIntegration', 'webSecurity',
    'allowRunningInsecureContent'].map(key => [key, settings.webPreferences[key]])), {
    sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, allowRunningInsecureContent: false,
  });
});

test('large-display reference coverage becomes passed only after the exact wide capture succeeds', async () => {
  const result = await runMain({ display: displayFor(1920, 1080) });
  assert.equal(result.code, 0);
  assert.deepEqual(result.captureCalls.map(call => call.expected), [[1440, 960], [900, 700]]);
  assert.equal(result.captureCalls[0].reportBefore.referenceWideCapture.status, 'pending');
  assert.equal(result.captureCalls[1].reportBefore.referenceWideCapture.status, 'passed');
  assert.equal(result.report.referenceWideCapture.status, 'passed');
  const failed = await runMain({ display: displayFor(1920, 1080), onCapture: () => { throw new Error('Capture failed'); } });
  assert.equal(failed.code, 1);
  assert.notEqual(failed.report.referenceWideCapture.status, 'passed');
});

test('display change then restoration cannot erase the invalidated window policy', async () => {
  const result = await runMain({ onCapture: ({ screen, originalDisplay, setDisplay }) => {
    const changed = { ...originalDisplay, scaleFactor: 1.5 };
    setDisplay(changed); screen.emit('display-metrics-changed', {}, changed, ['scaleFactor']);
    setDisplay(originalDisplay); screen.emit('display-metrics-changed', {}, originalDisplay, ['scaleFactor']);
  } });
  assert.equal(result.code, 1); assert.equal(result.report.status, 'failed');
  assert.equal(result.report.failedStage, 'wideCapture');
  assert.equal(result.captureCalls.length, 1);
});

test('delayed display-change payload remains invalid even if current display state has already restored', async () => {
  const result = await runMain({ onCapture: ({ screen, originalDisplay }) => {
    screen.emit('display-metrics-changed', {}, { ...originalDisplay, scaleFactor: 1.5 }, ['scaleFactor']);
    screen.emit('display-metrics-changed', {}, originalDisplay, ['scaleFactor']);
  } });
  assert.equal(result.code, 1); assert.equal(result.report.status, 'failed');
  assert.equal(result.captureCalls.length, 1);
});

test('selected-display removal cannot be concealed by a replacement using the same current geometry', async () => {
  const result = await runMain({ onCapture: ({ screen, originalDisplay }) => {
    screen.emit('display-removed', {}, originalDisplay);
  } });
  assert.equal(result.code, 1); assert.equal(result.report.status, 'failed');
  assert.equal(result.captureCalls.length, 1);
});

test('unexpected OS size is not adopted as the effective capture target', async () => {
  const result = await runMain({ actualSize: [1440, 800] });
  assert.equal(result.code, 1);
  assert.equal(result.report.error.code, 'capture_outer_size_mismatch');
  assert.deepEqual(result.captureCalls[0].expected, [1440, 816]);
  assert.deepEqual(result.captureCalls[0].actual, [1440, 800]);
  assert.deepEqual(result.report.windowSizePolicy.wide, [1440, 816]);
});

test('ordinary non-smoke preview retains its previous constructor and does not select a rendering plan', async () => {
  const result = await runMain({ smoke: false });
  assert.equal(result.regularCompleted, true);
  assert.equal(result.primaryReads, 0); assert.equal(result.captureCalls.length, 0);
  const settings = result.instances[0].settings;
  assert.deepEqual([settings.width, settings.height, settings.show], [1440, 960, true]);
  for (const key of ['x', 'y', 'useContentSize', 'frame']) assert.equal(Object.hasOwn(settings, key), false);
});


test('an earlier preload acknowledgment cannot bypass a current unlocked DOM root', async () => {
  const result = await runMain({ initiallyLocked: false });
  assert.equal(result.code, 1);
  assert.equal(result.report.checks.inputLock, 'passed');
  assert.equal(result.report.failedStage, 'markup');
  assert.equal(result.report.error.code, 'rendering_input_lock_incomplete');
  assert.equal(result.captureCalls.length, 0);
});

test('lock loss after wide capture prevents the wide pass and narrow capture', async () => {
  const result = await runMain({ onCapture: ({ window }) => { window.locked = false; } });
  assert.equal(result.code, 1);
  assert.equal(result.report.failedStage, 'wideCapture');
  assert.equal(result.report.error.code, 'rendering_input_lock_incomplete');
  assert.equal(result.report.checks.wideCapture, 'failed');
  assert.equal(result.captureCalls.length, 1);
  const check = result.report.events.find(event => event.name === 'input-lock-rechecked' && event.phase === 'after-wide-capture');
  assert.equal(check.frozen, false);
});


test('full application records fresh geometry at every capture boundary, permitting resize transition before narrow', async () => {
  const result = await runMain({ expectedPage: 'full-application', onProbe: ({ evidence, index }) => {
    if (index === 3) evidence.chromeLayout = chromeLayout(1426, 753); // Renderer has not resized yet.
  } });
  assert.equal(result.code, 0);
  const rechecks = result.report.events.filter(event => event.name === 'input-lock-rechecked');
  assert.equal(rechecks.length, 4);
  assert.ok(rechecks.every(item => item.markup.kind === 'full-application'));
  assert.deepEqual(rechecks.map(item => item.chromeLayout.viewport.width), [1426, 1426, 1426, 886]);
});

test('old narrow toolbar overlap prevents the narrow capture from starting', async () => {
  const result = await runMain({ expectedPage: 'full-application', onProbe: ({ evidence, index }) => {
    if (index === 3) {
      evidence.chromeLayout.toolbar.controls[1].bounds.x = 100;
      evidence.chromeLayout.toolbar.controls[1].labelBounds[0].x = 104;
    }
  } });
  assert.equal(result.code, 1); assert.equal(result.report.failedStage, 'narrowCapture');
  assert.equal(result.report.error.code, 'rendering_chrome_layout_invalid');
  assert.equal(result.captureCalls.length, 1);
});

test('clipped Sessions tab after narrow capture prevents a narrow pass', async () => {
  const result = await runMain({ expectedPage: 'full-application', onProbe: ({ evidence, index }) => {
    if (index === 4) evidence.chromeLayout.tabbar.tabs[7].bounds.x = 860;
  } });
  assert.equal(result.code, 1); assert.equal(result.report.failedStage, 'narrowCapture');
  assert.equal(result.report.error.code, 'rendering_chrome_layout_invalid');
  assert.equal(result.captureCalls.length, 2);
  assert.equal(result.report.checks.narrowCapture, 'failed');
});

test('post-capture geometry from the old wide viewport is not accepted as narrow evidence', async () => {
  const result = await runMain({ expectedPage: 'full-application', onProbe: ({ evidence, index }) => {
    if (index === 4) evidence.chromeLayout = chromeLayout(1426, 753);
  } });
  assert.equal(result.code, 1); assert.equal(result.report.error.code, 'rendering_chrome_layout_stale');
  assert.equal(result.report.checks.narrowCapture, 'failed');
});
