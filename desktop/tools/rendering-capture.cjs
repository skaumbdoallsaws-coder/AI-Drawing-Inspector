'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { performance } = require('node:perf_hooks');
const { withDeadline } = require('./minimal-electron/capture-readiness.cjs');

function fail(code, message) { return Object.assign(new Error(message), { code }); }
function positive(value) { return Number.isFinite(value) && value > 0; }
function size(value) {
  if (!Array.isArray(value) || value.length !== 2 || !value.every(positive)) {
    throw fail('capture_dimensions_invalid', 'Window dimensions must be positive');
  }
  return { width: value[0], height: value[1] };
}
function nearSize(actual, expected, tolerance = 1) {
  return actual && positive(actual.width) && positive(actual.height)
    && Math.abs(actual.width - expected.width) <= tolerance
    && Math.abs(actual.height - expected.height) <= tolerance;
}
function imageScaleMode(actual, viewport, scale) {
  if (nearSize(actual, viewport)) return 'viewport';
  if (nearSize(actual, { width: viewport.width * scale, height: viewport.height * scale })) return 'device-pixels';
  throw fail('capture_dimensions_mismatch', 'Captured image dimensions do not match the observed viewport/DPI');
}
function pngSize(buffer) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (!Buffer.isBuffer(buffer) || buffer.length < 33 || !buffer.subarray(0, 8).equals(signature)
      || buffer.readUInt32BE(8) !== 13 || buffer.toString('ascii', 12, 16) !== 'IHDR') {
    throw fail('capture_png_invalid', 'Capture did not encode a nonempty PNG with an IHDR header');
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

function diagnosticError(error) {
  const read = (field, fallback) => {
    try { return String(error?.[field] || fallback).slice(0, 512); } catch (_error) { return fallback; }
  };
  return { code: read('code', 'capture_diagnostics_failed'), message: read('message', 'Diagnostic read failed') };
}

function boundedDiagnosticCopy(value) {
  let remaining = 256;
  const ancestors = new Set();
  function copy(item, depth = 0) {
    if (--remaining < 0 || depth > 8) throw fail('capture_diagnostics_limit', 'Diagnostic data exceeded its structural limit');
    if (item === null || typeof item === 'boolean') return item;
    if (typeof item === 'number' && Number.isFinite(item)) return item;
    if (typeof item === 'string' && item.length <= 4096) return item;
    if (!item || typeof item !== 'object' || ancestors.has(item)
        || (!Array.isArray(item) && Object.prototype.toString.call(item) !== '[object Object]')) {
      throw fail('capture_diagnostics_invalid', 'Diagnostics must be bounded synchronous JSON data');
    }
    const entries = Object.entries(item);
    if (entries.length > 64) throw fail('capture_diagnostics_limit', 'Diagnostic collection exceeded its limit');
    ancestors.add(item);
    const result = Array.isArray(item) ? entries.map(([, entry]) => copy(entry, depth + 1))
      : Object.fromEntries(entries.map(([key, entry]) => [key, copy(entry, depth + 1)]));
    ancestors.delete(item);
    return result;
  }
  const result = copy(value);
  if (Buffer.byteLength(JSON.stringify(result)) > 16384) {
    throw fail('capture_diagnostics_limit', 'Diagnostic data exceeded 16 KiB');
  }
  return result;
}

/**
 * Diagnostic capture only: no retries, artificial delay, security changes, or
 * alternate capturePage options. Create firstPaintGate BEFORE loading the page.
 * Two renderer frames are a scheduling checkpoint, not compositor proof.
 * NativeImage dimensions have differed between Electron releases: accept either
 * viewport units or actual device pixels, but never an arbitrary scale/aspect.
 * See https://www.electronjs.org/docs/latest/api/native-image .
 * readDiagnostics is an optional main-owned, synchronous, read-only callback.
 * It must return promptly; JavaScript cannot preempt a blocking native getter.
 * Its JSON result is bounded/copied and never participates in capture approval.
 * record must synchronously persist diagnostic events if durable failure evidence
 * is required. Native/diagnostic getter failures are evidence, not replacements
 * for the capture's original failure.
 */
async function captureRenderedPage({ window, outputPath, firstPaintGate,
  expectedOuterSize, record = () => {}, readDiagnostics, timeoutMs = 10000 } = {}) {
  if (!window || !['getSize', 'getContentSize', 'isDestroyed', 'on', 'removeListener']
    .every(name => typeof window[name] === 'function') || !window.webContents) {
    throw new TypeError('A BrowserWindow-compatible window is required');
  }
  const contents = window.webContents;
  if (!['executeJavaScript', 'capturePage', 'getURL', 'isDestroyed', 'on', 'removeListener']
    .every(name => typeof contents[name] === 'function')) throw new TypeError('Live webContents is required');
  if (!path.isAbsolute(outputPath || '') || typeof record !== 'function') {
    throw new TypeError('A main-selected absolute output path and record callback are required');
  }
  if (readDiagnostics !== undefined && typeof readDiagnostics !== 'function') {
    throw new TypeError('readDiagnostics must be a synchronous callback');
  }
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000) {
    throw new TypeError('timeoutMs must be between 1 and 60000');
  }
  const expected = expectedOuterSize === undefined ? null : size(expectedOuterSize);
  const startedAt = new Date().toISOString(), start = performance.now();
  const checkpointId = randomUUID();
  const timings = {};
  let invalidation = null, frameCheckpointLocked = false, acceptedPreCheckpointResizes = 0;
  let observedFrameCheckpoint = null, latestGeometry = null;
  function observeGeometry(frameCheckpoint = null) {
    const diagnosticsErrors = [];
    function read(source, callback) {
      try { return boundedDiagnosticCopy(callback()); }
      catch (error) { diagnosticsErrors.push({ source, ...diagnosticError(error) }); return null; }
    }
    function nativeSize(source, getter) {
      return read(source, () => {
        const measured = getter();
        // Preserve invalid but serializable measurements; strict checks below
        // decide validity. Copies cannot mutate native or renderer inputs.
        return Array.isArray(measured) && measured.length === 2
          ? { width: measured[0], height: measured[1] } : measured;
      });
    }
    return {
      observedAt: new Date().toISOString(), requestedOuterSize: expected ? { ...expected } : null,
      actualOuterSize: nativeSize('window.getSize', () => window.getSize()),
      actualContentSize: nativeSize('window.getContentSize', () => window.getContentSize()),
      rendererViewport: frameCheckpoint ? read('rendererViewport', () => frameCheckpoint.viewport) : null,
      frameCheckpoint: frameCheckpoint ? read('frameCheckpoint', () => frameCheckpoint) : null,
      nativeDiagnostics: readDiagnostics ? read('readDiagnostics', readDiagnostics) : null,
      diagnosticsErrors,
    };
  }
  function invalidate(code, message) { invalidation = invalidation || fail(code, message); }
  function onNavigation(details, _url, _inPlace, legacyMainFrame) {
    const mainFrame = typeof details?.isMainFrame === 'boolean' ? details.isMainFrame : legacyMainFrame;
    if (mainFrame !== false) invalidate('capture_stale_frame', 'Main-frame navigation invalidated the capture checkpoint');
  }
  function onResize() {
    if (frameCheckpointLocked) {
      invalidate('capture_stale_frame', 'Window resized after the renderer checkpoint');
      return;
    }
    // setSize() may return before its resize notification arrives. Accept that
    // notification only for the explicitly requested outer size and only while
    // the two renderer frames are still pending. The checkpoint below separately
    // requires the final viewport to match the native content size.
    if (expected && !window.isDestroyed()) {
      try {
        if (nearSize(size(window.getSize()), expected, 0)) {
          acceptedPreCheckpointResizes++;
          return;
        }
      } catch (_error) { /* Invalid dimensions fail through the same boundary. */ }
      invalidate('capture_outer_size_mismatch', 'A pending resize did not match the requested outer size');
    } else invalidate('capture_stale_frame', 'An unrequested resize invalidated the renderer checkpoint');
  }
  function onClosed() { invalidate('capture_window_closed', 'Window closed before capture validation completed'); }
  function cleanup() {
    contents.removeListener('did-start-navigation', onNavigation);
    window.removeListener('resize', onResize);
    window.removeListener('closed', onClosed);
  }
  function current() {
    if (invalidation) throw invalidation;
    if (window.isDestroyed() || contents.isDestroyed()) throw fail('capture_window_closed', 'Capture window is unavailable');
  }
  contents.on('did-start-navigation', onNavigation);
  window.on('resize', onResize);
  window.on('closed', onClosed);

  try {
    latestGeometry = observeGeometry();
    record('capture-geometry-started', { checkpointId, ...latestGeometry });
    current();
    if (firstPaintGate) {
      if (typeof firstPaintGate.wait !== 'function') throw new TypeError('firstPaintGate must expose wait()');
      const phaseStart = performance.now();
      record('capture-first-paint-started', { checkpointId });
      const paint = await withDeadline(() => firstPaintGate.wait({ timeoutMs }), { timeoutMs, code: 'first_paint_timeout' });
      if (paint?.event !== 'ready-to-show' || paint.observed !== true) {
        throw fail('first_paint_evidence_invalid', 'First-paint gate did not return an observed ready-to-show event');
      }
      timings.firstPaintMs = performance.now() - phaseStart;
      current();
      record('capture-first-paint-complete', { checkpointId, elapsedMs: timings.firstPaintMs });
    }

    const framesStart = performance.now();
    record('capture-renderer-frames-started', { checkpointId });
    // The nonce binds the response to THIS invocation, including repeated sizes.
    const frameCheckpoint = await withDeadline(() => contents.executeJavaScript(`(() => {
      const checkpointId = ${JSON.stringify(checkpointId)};
      return new Promise(resolve => {
        requestAnimationFrame(first => requestAnimationFrame(second => resolve({
          checkpointId, frames: 2, frameTimes: [first, second],
          readyState: document.readyState, href: location.href,
          viewport: { width: innerWidth, height: innerHeight, scale: devicePixelRatio },
          outerWidth: typeof outerWidth === 'number' ? outerWidth : null,
          outerHeight: typeof outerHeight === 'number' ? outerHeight : null,
          visualViewport: typeof visualViewport === 'object' && visualViewport ? {
            width: visualViewport.width, height: visualViewport.height, scale: visualViewport.scale
          } : null
        })));
      });
    })()`), { timeoutMs, code: 'renderer_frames_timeout' });
    // Lock before validation/report callbacks. No resize is acceptable after
    // this response, even if its eventual dimensions return to the same values.
    frameCheckpointLocked = true;
    timings.rendererFramesMs = performance.now() - framesStart;
    observedFrameCheckpoint = frameCheckpoint;
    latestGeometry = observeGeometry(frameCheckpoint);
    record('capture-geometry-observed', { checkpointId, ...latestGeometry });
    current();
    const viewport = frameCheckpoint?.viewport;
    if (frameCheckpoint?.checkpointId !== checkpointId || frameCheckpoint.frames !== 2
        || !Array.isArray(frameCheckpoint.frameTimes) || frameCheckpoint.frameTimes.length !== 2
        || !frameCheckpoint.frameTimes.every(value => Number.isFinite(value) && value >= 0)
        || frameCheckpoint.frameTimes[1] < frameCheckpoint.frameTimes[0]
        || frameCheckpoint.readyState !== 'complete' || frameCheckpoint.href !== contents.getURL()) {
      throw fail('capture_stale_frame', 'Renderer checkpoint does not match the current page and capture request');
    }
    if (!viewport || !positive(viewport.width) || !positive(viewport.height)
        || !positive(viewport.scale) || viewport.scale > 16) {
      throw fail('capture_dimensions_invalid', 'Renderer viewport/DPI must be positive');
    }
    const outerSize = size(window.getSize()), contentSize = size(window.getContentSize());
    if (expected && !nearSize(outerSize, expected, 0)) {
      throw fail('capture_outer_size_mismatch', 'Window has not reached the requested outer size');
    }
    if (!nearSize(viewport, contentSize)) {
      throw fail('capture_viewport_mismatch', 'Renderer viewport has not reached the current content size');
    }
    record('capture-renderer-frames-complete', { checkpointId, frameCheckpoint, outerSize, contentSize,
      acceptedPreCheckpointResizes });

    const captureStart = performance.now();
    current();
    record('capture-started', { checkpointId, attempts: 1, options: 'unchanged defaults' });
    current();
    const capture = await withDeadline(() => contents.capturePage(), { timeoutMs, code: 'capture_timeout' });
    timings.captureMs = performance.now() - captureStart;
    current();
    if (contents.getURL() !== frameCheckpoint.href || !nearSize(size(window.getSize()), outerSize, 0)
        || !nearSize(size(window.getContentSize()), contentSize, 0)) {
      throw fail('capture_stale_frame', 'Page or window dimensions changed after the renderer checkpoint');
    }
    if (!capture || typeof capture.isEmpty !== 'function' || capture.isEmpty()
        || typeof capture.getSize !== 'function' || typeof capture.toPNG !== 'function') {
      throw fail('capture_empty', 'Renderer returned an empty screenshot');
    }
    const imageSize = capture.getSize();
    const imageMode = imageScaleMode(imageSize, viewport, viewport.scale);
    const png = capture.toPNG();
    const encodedSize = pngSize(png);
    const pngMode = imageScaleMode(encodedSize, viewport, viewport.scale);
    current();
    record('capture-validated', { checkpointId, imageSize, encodedSize, imageMode, pngMode, bytes: png.length });
    current();
    // Capture has been validated, including events from the final report hook.
    // No async boundary separates this check from dispatching the file write.
    // Once dispatched, later navigation cannot alter these validated PNG bytes.
    cleanup();
    const writeStart = performance.now();
    await fs.writeFile(outputPath, png);
    timings.writeMs = performance.now() - writeStart;
    timings.totalMs = performance.now() - start;
    const evidence = { outputPath, checkpointId, startedAt, completedAt: new Date().toISOString(),
      firstPaintObserved: Boolean(firstPaintGate), frameCheckpoint, outerSize, contentSize,
      imageSize, encodedSize, imageMode, pngMode, acceptedPreCheckpointResizes,
      geometry: latestGeometry, bytes: png.length, attempts: 1, timings };
    record('capture-written', evidence);
    return evidence;
  } catch (error) {
    const failure = invalidation || error;
    const finalGeometry = observeGeometry(observedFrameCheckpoint);
    // A failed diagnostic writer must not replace the capture failure either.
    // The caller remains responsible for persisting this final evidence record.
    try {
      record('capture-failed', { checkpointId, ...finalGeometry, lastGeometryObservation: latestGeometry,
        code: failure.code || 'capture_failed', message: failure.message });
    } catch (_recordError) { /* Preserve the primary capture failure. */ }
    throw failure;
  } finally { cleanup(); }
}

module.exports = { captureRenderedPage };
