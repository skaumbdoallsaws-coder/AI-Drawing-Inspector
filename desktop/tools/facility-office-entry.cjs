'use strict';
// Isolated visual review of authored furniture in the normal desktop application.
const { app } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile);
const target = 'fl-independent-factory-20260928';
const current = 'window._trainFacilityLayoutAuthoringApp';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const fanReview = process.env.INSPECTORPRO_OFFICE_FAN_REVIEW === '1';
const placementCount = fanReview ? 852 : 850;

async function verify(window) {
  const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
  const targetPath = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', target + '.json');
  const before = sha(await fs.readFile(targetPath));
  const report = { status: 'running', stages: [], captures: {} };
  const persist = () => fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  const js = code => window.webContents.executeJavaScript(code, true);
  async function until(code, timeout = 180000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const result = await js(code);
      if (result) return result;
      await pause(250);
    }
    throw Error('Timed out: ' + code);
  }
  async function capture(name) {
    await js('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
    await pause(800);
    const image = await window.webContents.capturePage();
    assert.equal(image.isEmpty(), false);
    await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
    const rect = await js(`(()=>{const c=${current}.workspace.threeAdapter.getRecordingCanvas();const r=c.getBoundingClientRect();return {x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)};})()`);
    const canvas = await window.webContents.capturePage(rect);
    const bitmap = canvas.toBitmap(), colors = new Set();
    for (let i = 0; i < bitmap.length; i += 4 * 29) colors.add(bitmap.readUInt32LE(i));
    assert.ok(colors.size > 40, '3D canvas is unexpectedly blank');
    report.captures[name] = { size: image.getSize(), canvasColors: colors.size };
    await persist();
  }
  async function camera(position, targetPoint) {
    await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position=${JSON.stringify(position)};v.target=${JSON.stringify(targetPoint)};v.up={x:0,y:1,z:0};v.fov=45;v.near=0.01;v.far=2000;a.applyCameraView(v);})()`);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads === 0`);
  }
  try {
    window.setSize(1440, 900);
    await until(`${current}?.session?.getState().loaded`);
    const actual = await js(`${current}.session.getState().layout`);
    assert.deepEqual(actual, JSON.parse(await fs.readFile(targetPath, 'utf8')));
    assert.equal(actual.placements.length, placementCount);
    if (fanReview) {
      const fans = actual.placements.filter(p => p.placementId.startsWith('pl-independent-office-fan-'));
      assert.equal(fans.length, 2);
      assert.ok(fans.every(p => p.assetId === 'asset-floor-fan-white'));
      report.fanPlacements = fans;
    }
    assert.equal(actual.zones.length, 59);
    assert.equal(actual.extensions.facilityNavigation.movementPrograms.length, 40);
    assert.equal(await js(`${current}.session.getState().dirty`), false);
    report.stages.push('exact-saved-candidate');
    await persist();
    await js(`${current}.workspace._setViewMode('3d')`);
    await until(`!!${current}.workspace.threeAdapter`);
    await camera({x:63,y:5,z:17}, {x:56.9,y:0.6,z:10.8});
    await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0 && ${current}.workspace.threeAdapter.getDiagnostics().assetGroupCount>0`);
    // Initial asset loading may auto-fit the scene once. Frame after that fit.
    await pause(1000);
    await camera({x:63,y:5,z:17}, {x:56.9,y:0.6,z:10.8});
    if (fanReview) {
      await until(`${current}.workspace.threeAdapter.getDiagnostics().representationGroups.some(g=>g.assetId==='asset-floor-fan-white' && ['overview','detail'].includes(g.representation))`);
    }
    report.diagnostics = await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
    assert.equal(report.diagnostics.degraded, false);
    assert.equal(report.diagnostics.placementCount, placementCount);
    assert.equal(report.diagnostics.placementTransformAudit.transformMismatchCount, 0);
    const furniture = new Set(actual.placements.filter(p=>p.placementId.startsWith('pl-independent-office-')).map(p=>p.assetId));
    report.furnitureGroups = report.diagnostics.representationGroups.filter(g=>furniture.has(g.assetId));
    assert.equal(report.furnitureGroups.length, fanReview ? 8 : 7);
    assert.ok(report.furnitureGroups.every(g=>g.meshCount>0 && ['overview','detail'].includes(g.representation)));
    await capture('01-office-overview');
    await camera({x:59.4,y:2.4,z:11.2}, {x:56.85,y:0.72,z:9.0});
    await capture('02-workstation-detail');
    await js(`${current}.workspace.threeAdapter.topView({minimum:{x:53,y:0,z:5},maximum:{x:65,y:3,z:17}})`);
    await capture('03-office-top');
    await camera({x:86,y:75,z:116}, {x:38,y:0,z:49});
    await capture('04-dispatch-context');
    window.setSize(900, 700);
    await pause(400);
    await camera({x:64,y:6,z:17}, {x:57.1,y:0.5,z:10.8});
    await capture('05-office-narrow');
    assert.equal(sha(await fs.readFile(targetPath)), before);
    report.savedDocumentUnchanged = true;
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.error = error.stack;
    await capture('failure').catch(()=>{});
  } finally {
    await persist();
    app.quit();
  }
}
app.once('browser-window-created', (_event, window) => {
  window.webContents.once('did-finish-load', () => void verify(window).catch(async error => {
    await fs.writeFile(path.join(output, 'driver-error.json'), JSON.stringify({error:error.stack}));
    app.quit();
  }));
});
require('../src/entry.cjs');
