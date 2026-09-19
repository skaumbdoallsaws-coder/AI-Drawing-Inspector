'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { captureRenderedPage } = require('../tools/rendering-capture.cjs');
const { createFirstPaintGate } = require('../tools/minimal-electron/capture-readiness.cjs');

function png(width, height) {
  // NativeImage double: only the signature/IHDR needed for dimension inspection.
  const buffer = Buffer.alloc(33);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(buffer);
  buffer.writeUInt32BE(13, 8); buffer.write('IHDR', 12, 'ascii');
  buffer.writeUInt32BE(width, 16); buffer.writeUInt32BE(height, 20);
  return buffer;
}
function image(width, height, encodedWidth = width, encodedHeight = height) {
  return { isEmpty: () => false, getSize: () => ({ width, height }), toPNG: () => png(encodedWidth, encodedHeight) };
}
function nextTurn() { return new Promise(resolve => setImmediate(resolve)); }
function deferred() {
  let resolve, reject;
  const promise = new Promise((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}
class WindowDouble extends EventEmitter {
  constructor() {
    super();
    this.outer = [900, 600]; this.content = [884, 561]; this.scale = 1;
    this.url = 'http://127.0.0.1:8123/'; this.destroyed = false;
    this.autoFrames = true; this.frames = []; this.frameCount = 0;
    this.scriptCalls = 0; this.captureCalls = [];
    this.webContents = new EventEmitter();
    this.webContents.getURL = () => this.url;
    this.webContents.isDestroyed = () => this.destroyed;
    this.webContents.executeJavaScript = script => {
      this.scriptCalls++;
      if (this.executeOverride) return this.executeOverride(script);
      const context = { document: { readyState: 'complete' }, location: { href: this.url },
        requestAnimationFrame: callback => {
          this.frames.push(callback);
          if (this.autoFrames) queueMicrotask(() => this.flushFrame());
        } };
      Object.defineProperties(context, {
        innerWidth: { get: () => (this.viewport || this.content)[0] },
        innerHeight: { get: () => (this.viewport || this.content)[1] },
        devicePixelRatio: { get: () => this.scale },
        outerWidth: { get: () => this.outer[0] },
        outerHeight: { get: () => this.outer[1] },
        visualViewport: { get: () => this.visualViewport || { width: this.content[0], height: this.content[1], scale: 1 } },
      });
      return vm.runInNewContext(script, context);
    };
    this.webContents.capturePage = (...args) => {
      this.captureCalls.push(args);
      return this.captureOverride ? this.captureOverride()
        : Promise.resolve(image(this.content[0], this.content[1]));
    };
  }
  isDestroyed() { return this.destroyed; }
  getSize() { return this.outer.slice(); }
  getContentSize() { return this.content.slice(); }
  flushFrame() { const callback = this.frames.shift(); if (callback) callback(++this.frameCount * 16); }
}
async function fixture(t) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'inspectorpro-render-capture-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  return { window: new WindowDouble(), outputPath: path.join(directory, 'capture.png') };
}
async function noFile(outputPath) { await assert.rejects(fs.stat(outputPath), { code: 'ENOENT' }); }
function clean(window) {
  assert.equal(window.listenerCount('resize'), 0);
  assert.equal(window.listenerCount('closed'), 0);
  assert.equal(window.webContents.listenerCount('did-start-navigation'), 0);
}

test('waits for first paint, two real renderer callbacks, and capture validation before writing PNG', async t => {
  const f = await fixture(t), rendered = deferred();
  f.window.autoFrames = false;
  f.window.captureOverride = () => rendered.promise;
  const firstPaintGate = createFirstPaintGate(f.window);
  const records = [];
  const capturing = captureRenderedPage({ ...f, firstPaintGate, expectedOuterSize: [900, 600],
    record: (event, details) => records.push({ event, details }) });
  await nextTurn();
  assert.equal(f.window.scriptCalls, 0); await noFile(f.outputPath);
  f.window.emit('ready-to-show'); await nextTurn();
  assert.equal(f.window.frames.length, 1);
  f.window.flushFrame(); await nextTurn();
  assert.equal(f.window.captureCalls.length, 0); await noFile(f.outputPath);
  f.window.flushFrame(); await nextTurn();
  assert.deepEqual(f.window.captureCalls, [[]], 'Exactly one capturePage call with unchanged default options');
  await noFile(f.outputPath);
  rendered.resolve(image(884, 561));
  const evidence = await capturing;
  assert.equal(evidence.frameCheckpoint.frames, 2);
  assert.equal(evidence.firstPaintObserved, true);
  assert.deepEqual(evidence.contentSize, { width: 884, height: 561 });
  assert.equal(evidence.attempts, 1);
  assert.equal(evidence.timings.totalMs >= 0, true);
  assert.equal((await fs.readFile(f.outputPath)).length, 33);
  assert.equal(records.at(-1).event, 'capture-written');
  clean(f.window);
});

test('resized viewport must match the actual native content size', async t => {
  const f = await fixture(t);
  f.window.outer = [700, 500]; f.window.content = [684, 461];
  const result = await captureRenderedPage({ ...f, expectedOuterSize: [700, 500] });
  assert.deepEqual(result.outerSize, { width: 700, height: 500 });
  assert.deepEqual(result.encodedSize, { width: 684, height: 461 });
  clean(f.window);
});

test('an expected setSize notification arriving before the second renderer frame is accepted', async t => {
  const f = await fixture(t);
  // Native size changes first; its resize event arrives after capture starts.
  f.window.outer = [900, 700]; f.window.content = [884, 661];
  f.window.autoFrames = false;
  const capturing = captureRenderedPage({ ...f, expectedOuterSize: [900, 700] });
  await nextTurn(); f.window.flushFrame(); await nextTurn();
  f.window.emit('resize');
  assert.equal(f.window.captureCalls.length, 0); await noFile(f.outputPath);
  f.window.flushFrame();
  const result = await capturing;
  assert.equal(result.acceptedPreCheckpointResizes, 1);
  assert.deepEqual(result.outerSize, { width: 900, height: 700 });
  assert.deepEqual(result.contentSize, { width: 884, height: 661 });
  assert.equal(f.window.captureCalls.length, 1);
  clean(f.window);
});

test('a wrong pending resize stays invalid even if size is restored before the checkpoint', async t => {
  const f = await fixture(t);
  f.window.outer = [900, 700]; f.window.content = [884, 661];
  f.window.autoFrames = false;
  const capturing = captureRenderedPage({ ...f, expectedOuterSize: [900, 700] });
  await nextTurn();
  f.window.outer = [800, 700]; f.window.content = [784, 661]; f.window.emit('resize');
  f.window.outer = [900, 700]; f.window.content = [884, 661];
  f.window.flushFrame(); await nextTurn(); f.window.flushFrame();
  await assert.rejects(capturing, { code: 'capture_outer_size_mismatch' });
  assert.equal(f.window.captureCalls.length, 0);
  await noFile(f.outputPath); clean(f.window);
});

test('an unrequested resize before the checkpoint is rejected', async t => {
  const f = await fixture(t); f.window.autoFrames = false;
  const capturing = captureRenderedPage(f); await nextTurn();
  f.window.emit('resize'); f.window.flushFrame(); await nextTurn(); f.window.flushFrame();
  await assert.rejects(capturing, { code: 'capture_stale_frame' });
  assert.equal(f.window.captureCalls.length, 0);
  await noFile(f.outputPath); clean(f.window);
});

for (const boundary of ['capture-renderer-frames-complete', 'capture-validated']) {
  test('an expected-size resize at ' + boundary + ' is too late and prevents PNG write', async t => {
    const f = await fixture(t);
    await assert.rejects(captureRenderedPage({ ...f, expectedOuterSize: [900, 600],
      record(event) { if (event === boundary) f.window.emit('resize'); } }), { code: 'capture_stale_frame' });
    assert.equal(f.window.captureCalls.length, boundary === 'capture-validated' ? 1 : 0);
    await noFile(f.outputPath); clean(f.window);
  });
}

test('an unverified gate result cannot be reported as first-paint evidence', async t => {
  const f = await fixture(t);
  await assert.rejects(captureRenderedPage({ ...f, firstPaintGate: { wait: async () => ({ observed: false }) } }),
    { code: 'first_paint_evidence_invalid' });
  assert.equal(f.window.scriptCalls, 0);
  assert.equal(f.window.captureCalls.length, 0);
  await noFile(f.outputPath); clean(f.window);
});

for (const [name, nativeSize, encodedSize] of [
  ['DIP NativeImage with physical PNG', [884, 561], [1105, 701]],
  ['physical NativeImage and PNG', [1105, 701], [1105, 701]],
  ['one pixel native rounding', [1106, 702], [1105, 701]],
]) {
  test('DPI-aware capture accepts ' + name, async t => {
    const f = await fixture(t); f.window.scale = 1.25;
    f.window.captureOverride = async () => image(...nativeSize, ...encodedSize);
    const result = await captureRenderedPage(f);
    assert.equal(result.pngMode, 'device-pixels');
  });
}

for (const [name, change, code] of [
  ['old viewport after resize', f => { f.window.viewport = [884, 561]; f.window.content = [684, 461]; }, 'capture_viewport_mismatch'],
  ['wrong outer size', f => { f.expectedOuterSize = [700, 500]; }, 'capture_outer_size_mismatch'],
  ['zero viewport', f => { f.window.viewport = [0, 561]; }, 'capture_dimensions_invalid'],
  ['zero DPI', f => { f.window.scale = 0; }, 'capture_dimensions_invalid'],
]) {
  test(name + ' rejects before capture or PNG write', async t => {
    const f = await fixture(t); change(f);
    await assert.rejects(captureRenderedPage(f), { code });
    assert.equal(f.window.captureCalls.length, 0);
    await noFile(f.outputPath); clean(f.window);
  });
}

test('a stale invocation checkpoint is rejected even at identical dimensions', async t => {
  const f = await fixture(t);
  f.window.executeOverride = async () => ({ checkpointId: 'old', frames: 2, frameTimes: [16, 32],
    readyState: 'complete', href: f.window.url, viewport: { width: 884, height: 561, scale: 1 } });
  await assert.rejects(captureRenderedPage(f), { code: 'capture_stale_frame' });
  assert.equal(f.window.captureCalls.length, 0);
  await noFile(f.outputPath); clean(f.window);
});

for (const [name, makeImage, code] of [
  ['empty image', () => ({ isEmpty: () => true }), 'capture_empty'],
  ['zero image dimension', () => image(0, 561), 'capture_dimensions_mismatch'],
  ['mixed-axis DPI scaling', () => image(1768, 561), 'capture_dimensions_mismatch'],
  ['invalid PNG', () => ({ ...image(884, 561), toPNG: () => Buffer.alloc(0) }), 'capture_png_invalid'],
  ['mismatched encoded PNG', () => image(884, 561, 680, 461), 'capture_dimensions_mismatch'],
]) {
  test(name + ' cannot be written as successful capture', async t => {
    const f = await fixture(t); f.window.scale = 2;
    f.window.captureOverride = async () => makeImage();
    await assert.rejects(captureRenderedPage(f), { code });
    assert.equal(f.window.captureCalls.length, 1);
    await noFile(f.outputPath); clean(f.window);
  });
}

for (const stage of ['paint', 'frames', 'capture']) {
  test(stage + ' timeout does not start later work or write a late PNG', async t => {
    const f = await fixture(t), late = deferred();
    f.timeoutMs = 10;
    if (stage === 'paint') f.firstPaintGate = { wait: () => late.promise };
    if (stage === 'frames') f.window.executeOverride = () => late.promise;
    if (stage === 'capture') f.window.captureOverride = () => late.promise;
    const code = { paint: 'first_paint_timeout', frames: 'renderer_frames_timeout', capture: 'capture_timeout' }[stage];
    await assert.rejects(captureRenderedPage(f), { code });
    late.resolve(image(884, 561)); await nextTurn();
    assert.equal(f.window.captureCalls.length, stage === 'capture' ? 1 : 0);
    await noFile(f.outputPath); clean(f.window);
  });
}

for (const change of ['navigation', 'resize', 'silent-size-change', 'closed']) {
  test(change + ' during capture invalidates the result before PNG write', async t => {
    const f = await fixture(t), captured = deferred();
    f.window.captureOverride = () => captured.promise;
    const running = captureRenderedPage(f); await nextTurn();
    assert.equal(f.window.captureCalls.length, 1);
    if (change === 'navigation') f.window.webContents.emit('did-start-navigation', { isMainFrame: true });
    if (change === 'resize') f.window.emit('resize');
    if (change === 'silent-size-change') f.window.content = [680, 460];
    if (change === 'closed') { f.window.destroyed = true; f.window.emit('closed'); }
    captured.resolve(image(884, 561));
    await assert.rejects(running, { code: change === 'closed' ? 'capture_window_closed' : 'capture_stale_frame' });
    await noFile(f.outputPath); clean(f.window);
  });
}

test('subframe navigation alone does not invalidate a main-frame checkpoint', async t => {
  const f = await fixture(t);
  f.window.captureOverride = async () => {
    f.window.webContents.emit('did-start-navigation', { isMainFrame: false });
    return image(884, 561);
  };
  assert.equal((await captureRenderedPage(f)).attempts, 1);
});

test('failed capture preserves an earlier evidence file unchanged', async t => {
  const f = await fixture(t);
  const previous = Buffer.from('previous verified capture');
  await fs.writeFile(f.outputPath, previous);
  f.window.captureOverride = async () => ({ isEmpty: () => true });
  await assert.rejects(captureRenderedPage(f), { code: 'capture_empty' });
  assert.deepEqual(await fs.readFile(f.outputPath), previous);
});

test('outer-size failure records requested and actual geometry before validation stops capture', async t => {
  const f = await fixture(t), records = [];
  f.window.outer = [1000, 700]; f.window.content = [984, 661]; f.window.scale = 1.25;
  const native = { display: { scaleFactor: 1.25, workArea: { width: 1000, height: 700 } } };
  await assert.rejects(captureRenderedPage({ ...f, expectedOuterSize: [1440, 960],
    readDiagnostics: () => native, record: (event, details) => records.push({ event, details }) }),
  { code: 'capture_outer_size_mismatch' });
  const started = records.find(item => item.event === 'capture-geometry-started').details;
  const observed = records.find(item => item.event === 'capture-geometry-observed').details;
  const failed = records.find(item => item.event === 'capture-failed').details;
  assert.deepEqual(started.requestedOuterSize, { width: 1440, height: 960 });
  assert.deepEqual(started.actualOuterSize, { width: 1000, height: 700 });
  assert.equal(started.frameCheckpoint, null);
  assert.deepEqual(observed.actualOuterSize, { width: 1000, height: 700 });
  assert.deepEqual(observed.actualContentSize, { width: 984, height: 661 });
  assert.deepEqual(observed.rendererViewport, { width: 984, height: 661, scale: 1.25 });
  assert.equal(observed.frameCheckpoint.outerWidth, 1000);
  assert.equal(observed.frameCheckpoint.outerHeight, 700);
  assert.deepEqual(observed.frameCheckpoint.visualViewport, { width: 984, height: 661, scale: 1 });
  assert.deepEqual(observed.nativeDiagnostics, native);
  assert.notEqual(observed.nativeDiagnostics, native, 'Diagnostic copies never alias the callback result');
  assert.deepEqual(observed.diagnosticsErrors, []);
  assert.deepEqual(failed.actualOuterSize, { width: 1000, height: 700 });
  assert.equal(failed.frameCheckpoint.checkpointId, observed.frameCheckpoint.checkpointId);
  assert.equal(failed.code, 'capture_outer_size_mismatch');
  assert.equal(records.some(item => item.event === 'capture-started'), false);
  assert.equal(f.window.captureCalls.length, 0);
  await noFile(f.outputPath); clean(f.window);
});

test('throwing native diagnostic getter cannot mask the strict geometry failure', async t => {
  const f = await fixture(t), records = [];
  f.window.outer = [1000, 700]; f.window.content = [984, 661];
  await assert.rejects(captureRenderedPage({ ...f, expectedOuterSize: [1440, 960],
    readDiagnostics: () => { throw Object.assign(new Error('Display getter failed'), { code: 'DISPLAY_GONE' }); },
    record: (event, details) => records.push({ event, details }) }), { code: 'capture_outer_size_mismatch' });
  const observed = records.find(item => item.event === 'capture-geometry-observed').details;
  const failed = records.find(item => item.event === 'capture-failed').details;
  assert.deepEqual(observed.actualOuterSize, { width: 1000, height: 700 });
  assert.equal(observed.nativeDiagnostics, null);
  assert.deepEqual(observed.diagnosticsErrors, [{ source: 'readDiagnostics', code: 'DISPLAY_GONE', message: 'Display getter failed' }]);
  assert.equal(failed.code, 'capture_outer_size_mismatch');
  assert.equal(failed.diagnosticsErrors[0].code, 'DISPLAY_GONE');
  assert.equal(f.window.captureCalls.length, 0);
  await noFile(f.outputPath); clean(f.window);
});

test('initial observation and failure retain geometry when renderer frames time out', async t => {
  const f = await fixture(t), records = [];
  f.window.executeOverride = () => new Promise(() => {});
  await assert.rejects(captureRenderedPage({ ...f, timeoutMs: 10,
    readDiagnostics: () => ({ display: { scaleFactor: 1 } }),
    record: (event, details) => records.push({ event, details }) }), { code: 'renderer_frames_timeout' });
  assert.equal(records[0].event, 'capture-geometry-started');
  assert.deepEqual(records.at(-1).details.actualOuterSize, { width: 900, height: 600 });
  assert.equal(records.at(-1).details.frameCheckpoint, null);
  assert.equal(records.at(-1).details.lastGeometryObservation.nativeDiagnostics.display.scaleFactor, 1);
  assert.equal(f.window.captureCalls.length, 0);
  await noFile(f.outputPath); clean(f.window);
});

test('bounded diagnostic data and throwing data properties are recorded without affecting validation', async t => {
  for (const diagnostics of [() => ({ text: 'x'.repeat(20000) }),
    () => ({ get display() { throw new Error('Native property unavailable'); } })]) {
    const f = await fixture(t), records = [];
    const result = await captureRenderedPage({ ...f, readDiagnostics: diagnostics,
      record: (event, details) => records.push({ event, details }) });
    const observed = records.find(item => item.event === 'capture-geometry-observed').details;
    assert.equal(observed.nativeDiagnostics, null);
    assert.equal(observed.diagnosticsErrors[0].source, 'readDiagnostics');
    assert.equal(result.attempts, 1);
    assert.equal((await fs.readFile(f.outputPath)).length, 33);
    clean(f.window);
  }
});

test('editing a diagnostic copy cannot change measurements used for strict validation', async t => {
  const f = await fixture(t);
  f.window.outer = [1000, 700]; f.window.content = [984, 661];
  await assert.rejects(captureRenderedPage({ ...f, expectedOuterSize: [1440, 960], record(event, details) {
    if (event === 'capture-geometry-observed') {
      details.actualOuterSize.width = 1440; details.actualOuterSize.height = 960;
      details.rendererViewport.width = 1424; details.frameCheckpoint.viewport.width = 1424;
    }
  } }), { code: 'capture_outer_size_mismatch' });
  assert.deepEqual(f.window.outer, [1000, 700]);
  assert.equal(f.window.captureCalls.length, 0);
  await noFile(f.outputPath); clean(f.window);
});
