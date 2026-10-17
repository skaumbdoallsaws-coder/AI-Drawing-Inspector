'use strict';
// Read-only native benchmark using the normal application and a separate profile.
const { app } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile);
const current = 'window._trainFacilityLayoutAuthoringApp';
const target = 'fl-independent-factory-20260928';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

async function benchmark(window) {
  const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
  const report = { status: 'running', runs: [], profileId: profile.profileId };
  const persist = () => fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  const js = code => window.webContents.executeJavaScript(code, true);
  async function until(code, timeout = 180000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) { if (await js(code)) return; await pause(200); }
    throw Error('Timed out: ' + code);
  }
  const hashes = async () => {
    const result = {};
    for (const id of [target, 'fl-reference-manual-20260812']) {
      result[id] = sha(await fs.readFile(path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', id + '.json')));
    }
    return result;
  };
  try {
    report.before = await hashes();
    await persist();
    window.setSize(1440, 820);
    window.show();
    window.focus();
    await until(`!!${current}?.session?.getState().loaded`);
    assert.equal(await js(`${current}.session.getState().dirty`), false);
    await js(`_trainFacilitySheets.activate(${JSON.stringify(target)})`);
    await until(`${current}.session.getState().layout.layoutId === ${JSON.stringify(target)}`);
    await js(`${current}.workspace._setViewMode('3d')`);
    await until(`${current}.workspace.threeAdapter?.getDiagnostics().pendingLoads === 0 && ${current}.workspace.threeAdapter?.getDiagnostics().assetGroupCount > 0`);
    assert.equal(await js(`${current}.workspace.threeAdapter.getDiagnostics().placementCount`), 836);
    report.gpu = await app.getGPUInfo('basic');
    report.gpuFeatures = app.getGPUFeatureStatus();
    report.webgl = await js(`(()=>{const c=${current}.workspace.threeAdapter.getRecordingCanvas();const gl=c.getContext('webgl2');if(!gl)return null;const e=gl.getExtension('WEBGL_debug_renderer_info');return {renderer:gl.getParameter(e?e.UNMASKED_RENDERER_WEBGL:gl.RENDERER),vendor:gl.getParameter(e?e.UNMASKED_VENDOR_WEBGL:gl.VENDOR)};})()`);
    report.loaded = await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
    for (let run = 0; run < 3; run++) {
      window.focus();
      await js(`(()=>{const a=${current}.workspace.threeAdapter; a.exitWalkthrough();const v=a.getCameraView();v.position={x:140,y:1.7,z:98};v.target={x:150,y:1.7,z:98};v.up={x:0,y:1,z:0};a.applyCameraView(v);a.setWalkthroughCameraMode('third-person');a.setWalkthroughCameraSettings({distance:6,height:1.5,fov:45});a.enterWalkthrough({ignoreSelection:true,worldPoint:{x:150,z:98}});})()`);
      await until(`${current}.workspace.threeAdapter.getWalkthroughState().locked`, 10000);
      await pause(600);
      const profiling = run === 2;
      if (profiling) {
        window.webContents.debugger.attach('1.3');
        await window.webContents.debugger.sendCommand('Profiler.enable');
        await window.webContents.debugger.sendCommand('Profiler.start');
      }
      const result = await js(`new Promise(resolve=>{
        const a=${current}.workspace.threeAdapter, frames=[], start=a.getWalkthroughState();
        const began=performance.now();let previous=began;
        document.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyW',key:'w',bubbles:true}));
        function sample(now){frames.push(now-previous);previous=now;
          if(now-began<6000){requestAnimationFrame(sample);return;}
          document.dispatchEvent(new KeyboardEvent('keyup',{code:'KeyW',key:'w',bubbles:true}));
          const end=a.getWalkthroughState(),d=a.getDiagnostics();
          resolve({durationMs:now-began,frames,start,end,rendering:d.rendering,
            performance:d.navigation.walkthrough.performance,placementCount:d.placementCount,
            degraded:d.degraded,canvas:(()=>{const r=a.getRecordingCanvas().getBoundingClientRect();return {x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)};})()});
        }requestAnimationFrame(sample);
      })`);
      if (profiling) {
        const { profile: cpu } = await window.webContents.debugger.sendCommand('Profiler.stop');
        await fs.writeFile(path.join(output, 'walking.cpuprofile'), JSON.stringify(cpu));
        const nodes = new Map(cpu.nodes.map(node => [node.id, node]));
        const timeById = new Map();
        (cpu.samples || []).forEach((id, i) => timeById.set(id, (timeById.get(id) || 0) + (cpu.timeDeltas[i] || 0)));
        report.cpu = Array.from(timeById, ([id, time]) => ({ms:time / 1000,...nodes.get(id).callFrame})).sort((a,b)=>b.ms-a.ms).slice(0,25);
        window.webContents.debugger.detach();
      }
      assert.equal(result.end.active && result.end.locked, true, 'Focus/pointer lock was lost during benchmark');
      assert.equal(result.end.collisionCount, 0);
      assert.equal(result.degraded, false);
      const sorted = result.frames.slice().sort((a,b)=>a-b);
      result.fps = result.frames.length / (result.durationMs / 1000);
      result.p95FrameMs = sorted[Math.ceil(sorted.length * 0.95) - 1];
      result.distanceMeters = Math.hypot(result.end.position.x-result.start.position.x,result.end.position.z-result.start.position.z);
      result.speedMetersPerSecond = result.distanceMeters / (result.durationMs / 1000);
      result.profiling = profiling;
      report.runs.push(result);
      await persist();
      if (run === 1) {
        await pause(400);
        const capture = await window.webContents.capturePage(result.canvas);
        await fs.writeFile(path.join(output, 'walking.png'), capture.toPNG());
        const bytes = capture.toBitmap(), colors = new Set();
        for (let i=0;i<bytes.length;i+=4*31) colors.add(bytes.readUInt32LE(i));
        assert.ok(colors.size>30, '3D canvas is blank');
        report.canvasColors = colors.size;
      }
      await js(`${current}.workspace.threeAdapter.exitWalkthrough()`);
    }
    report.after = await hashes();
    assert.deepEqual(report.after, report.before);
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed';report.error=error.stack;
  } finally {
    if (window.webContents.debugger.isAttached()) window.webContents.debugger.detach();
    await persist();
    app.quit();
  }
}
app.once('browser-window-created', (_event, window) => {
  window.webContents.once('did-finish-load', () => void benchmark(window).catch(async error => {
    await fs.writeFile(path.join(output, 'driver-error.txt'), error.stack);app.quit();
  }));
});
require('../src/entry.cjs');
