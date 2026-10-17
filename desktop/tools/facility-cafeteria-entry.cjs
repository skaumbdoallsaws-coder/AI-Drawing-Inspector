'use strict';
// Read-only native review of the isolated cafeteria candidate.
const { app } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile);
const current = 'window._trainFacilityLayoutAuthoringApp';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const assetIds = ['asset-5589t51-round-plastic-folding-table', 'asset-chair-black', 'asset-kitchen-assembly'];
const kitchenWalls = process.env.INSPECTORPRO_KITCHEN_WALL_REVIEW === '1';

async function verify(window) {
  const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
  assert.match(profile.profileId, /^factory02-(cafeteria|kitchen-walls)$/);
  const targetPath = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts/fl-independent-factory-20260928.json');
  const before = sha(await fs.readFile(targetPath));
  const report = { status: 'running', captures: {} };
  const persist = () => fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  const stage = async name => { report.stage = name; await persist(); };
  const js = code => window.webContents.executeJavaScript(code, true);
  async function until(code, timeout = 180000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await js(code)) return;
      await pause(250);
    }
    throw Error('Timed out: ' + code);
  }
  async function camera(position, target) {
    await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position=${JSON.stringify(position)};v.target=${JSON.stringify(target)};v.up={x:0,y:1,z:0};v.fov=45;v.near=0.01;v.far=2000;a.applyCameraView(v);})()`);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0`);
  }
  async function toggleWalls(visible) {
    await js(`(()=>{const w=${current}.workspace;w._setLayerPanelOpen(true);const box=w.layerPanel.querySelector('[data-facility-layer="walls"]');if(box.checked!==${visible})box.click();w._setLayerPanelOpen(false);})()`);
    await until(`${current}.workspace.threeAdapter.getDiagnostics().visiblePerimeterWallCount===${visible ? 10 : 0}`);
  }
  async function capture(name) {
    await js('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
    await pause(800);
    const image = await window.webContents.capturePage();
    assert.equal(image.isEmpty(), false);
    await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
    const rect = await js(`(()=>{const r=${current}.workspace.threeAdapter.getRecordingCanvas().getBoundingClientRect();return {x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)};})()`);
    const bitmap = (await window.webContents.capturePage(rect)).toBitmap();
    const colors = new Set();
    for (let i = 0; i < bitmap.length; i += 116) colors.add(bitmap.readUInt32LE(i));
    assert.ok(colors.size > 40, '3D canvas is unexpectedly blank');
    report.captures[name] = { size: image.getSize(), canvasColors: colors.size };
    await persist();
  }
  try {
    await stage('waiting-for-workspace');
    window.setSize(1440, 900);
    await until(`${current}?.session?.getState().loaded`);
    const actual = await js(`${current}.session.getState().layout`);
    assert.deepEqual(actual, JSON.parse(await fs.readFile(targetPath, 'utf8')));
    assert.equal(actual.placements.length, 873);
    assert.equal(actual.zones.length, kitchenWalls ? 61 : 60);
    assert.equal(actual.routes.length, kitchenWalls ? 12 : 11);
    assert.equal(actual.extensions.facilityNavigation.movementPrograms.length, 40);
    assert.equal(await js(`${current}.session.getState().dirty`), false);
    report.furniture = actual.placements.filter(p => p.placementId.startsWith('pl-independent-cafeteria-'));
    assert.equal(report.furniture.length, 21);
    assert.deepEqual(assetIds.map(id => report.furniture.filter(p => p.assetId === id).length), [4, 16, 1]);
    if (kitchenWalls) {
      await stage('checking-plan-walls');
      await js(`${current}.workspace._setViewMode('plan')`);
      report.wallSettings = actual.extensions.facilityPerimeterWalls.settings;
      assert.equal(report.wallSettings.heightMeters, 2.8);
      assert.equal(report.wallSettings.thicknessMeters, 0.15);
      assert.deepEqual(report.wallSettings.openings, [{edge:0,startMeters:2.6,endMeters:4.4}]);
      report.wallPanels = actual.extensions.facilityPerimeterWalls.panels.length;
      assert.equal(report.wallPanels, 10);
      await until(`document.querySelectorAll('[data-layer="walls"] polygon').length===10`);
      await fs.writeFile(path.join(output, '00-plan-walls.png'), (await window.webContents.capturePage()).toPNG());
    }
    await stage('loading-3d');
    await js(`${current}.workspace._setViewMode('3d')`);
    await until(`!!${current}.workspace.threeAdapter`);
    await camera({x:68,y:11,z:12}, {x:57.3,y:0.8,z:25.5});
    await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0 && ${current}.workspace.threeAdapter.getDiagnostics().assetGroupCount>0`);
    await pause(1000);
    await camera({x:68,y:11,z:12}, {x:57.3,y:0.8,z:25.5});
    await until(`(()=>{const d=${current}.workspace.threeAdapter.getDiagnostics();return ${JSON.stringify(assetIds)}.every(id=>d.representationGroups.some(g=>g.assetId===id&&['overview','detail'].includes(g.representation)));})()`);
    report.diagnostics = await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
    assert.equal(report.diagnostics.degraded, false);
    assert.equal(report.diagnostics.placementTransformAudit.transformMismatchCount, 0);
    report.furnitureGroups = report.diagnostics.representationGroups.filter(g => assetIds.includes(g.assetId));
    assert.ok(report.furnitureGroups.every(g => g.meshCount > 0 && ['overview','detail'].includes(g.representation)));
    if (kitchenWalls) {
      assert.equal(report.diagnostics.visiblePerimeterWallCount, 10);
      assert.equal(report.diagnostics.visibleLegacyWallPlacementCount, 6);
    }
    await stage('capturing-views');
    await capture('01-cafeteria-overview');
    await camera({x:60.8,y:2.1,z:17}, {x:57.3,y:1.05,z:30.3});
    await capture('02-seating-eye-level');
    await camera(kitchenWalls ? {x:57.3,y:2.0,z:26} : {x:62,y:3.7,z:27.5}, {x:57.3,y:1.0,z:32});
    await capture('03-kitchen-detail');
    await js(`${current}.workspace.threeAdapter.topView({minimum:{x:52,y:0,z:16},maximum:{x:64,y:3,z:37}})`);
    await capture('04-cafeteria-top');
    window.setSize(900, 700);
    await pause(400);
    await camera({x:72,y:16,z:7}, {x:57.3,y:0.7,z:25.5});
    await capture('05-cafeteria-narrow');
    if (kitchenWalls) {
      await stage('checking-wall-toggle-and-walkthrough');
      const revision = await js(`${current}.session.getState().draftRevision`);
      await js(`${current}.workspace.threeAdapter.enterWalkthrough({})`);
      report.walkthrough = await js(`${current}.workspace.threeAdapter.getWalkthroughState()`);
      assert.equal(report.walkthrough.active, true);
      assert.ok(report.walkthrough.obstacleCount >= report.wallPanels);
      await toggleWalls(false);
      report.hidden = await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
      assert.equal(report.hidden.visibleLegacyWallPlacementCount, 0);
      assert.equal(await js(`${current}.workspace.threeAdapter.getWalkthroughState().obstacleCount`), report.walkthrough.obstacleCount);
      await js(`${current}.workspace.threeAdapter.exitWalkthrough('test-complete')`);
      await camera({x:68,y:11,z:12}, {x:57.3,y:0.8,z:25.5});
      await capture('06-walls-hidden');
      await toggleWalls(true);
      assert.equal(await js(`${current}.session.getState().draftRevision`), revision);
      assert.deepEqual(await js(`${current}.session.getState().layout`), actual);
      assert.equal(await js(`${current}.session.getState().dirty`), false);
      report.wallVisibilityIsPresentationOnly = true;
    }
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
  void fs.writeFile(path.join(output, 'window-created.json'), JSON.stringify({at: new Date().toISOString()}));
  window.webContents.once('dom-ready', () => void verify(window).catch(async error => {
    await fs.writeFile(path.join(output, 'driver-error.json'), JSON.stringify({error:error.stack}));
    app.quit();
  }));
});
require('../src/entry.cjs');
