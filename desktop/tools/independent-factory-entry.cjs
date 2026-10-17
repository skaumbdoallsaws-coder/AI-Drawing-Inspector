'use strict';
// Local authoring challenge: inspect the normal app without opening a debug port.
const { app } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile);
const target = 'fl-independent-factory-20260928';
const source = 'fl-reference-manual-20260812';
const layer2 = process.argv.includes('--layer2');
const cncSides = process.argv.includes('--cnc-sides');
const walls = process.argv.includes('--walls');
const expectedPlacements = walls ? 836 : 830;
process.argv = process.argv.filter(value => !['--layer2', '--cnc-sides', '--walls'].includes(value));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

async function verify(window) {
  const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
  const sourcePath = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', source + '.json');
  const before = sha(await fs.readFile(sourcePath));
  const targetPath = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', target + '.json');
  const targetBefore = sha(await fs.readFile(targetPath));
  const report = { status: 'running', sourceSha256: before, stages: [], captures: {} };
  const persist = () => fs.writeFile(path.join(output, 'native-check.json'), JSON.stringify(report, null, 2));
  const js = code => window.webContents.executeJavaScript(code, true);
  const current = 'window._trainFacilityLayoutAuthoringApp';
  async function until(code, timeout = 120000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) { const result = await js(code); if (result) return result; await pause(250); }
    throw Error('Timed out: ' + code);
  }
  async function stage(name) { report.stages.push(name); await persist(); }
  async function capture(name) {
    await js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
    await pause(800);
    const image = await window.webContents.capturePage();
    assert.equal(image.isEmpty(), false);
    const bytes = image.toPNG();
    const pixels = image.toBitmap();
    const colors = new Set();
    for (let i = 0; i < pixels.length; i += 4 * 127) colors.add(pixels.readUInt32LE(i));
    assert.ok(colors.size > 100, 'Rendered view has insufficient pixel diversity');
    await fs.writeFile(path.join(output, name + '.png'), bytes);
    report.captures[name] = { sha256: sha(bytes), size: image.getSize(), sampledColors: colors.size };
    const rect = (layer2 || cncSides || walls) && await js(`(()=>{const c=${current}?.workspace?.threeAdapter?.getRecordingCanvas();if(!c)return null;const r=c.getBoundingClientRect();return r.width>0&&r.height>0?{x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)}:null;})()`);
    if (rect) {
      const canvasImage = await window.webContents.capturePage(rect);
      const bitmap = canvasImage.toBitmap(), canvasColors = new Set();
      for (let i = 0; i < bitmap.length; i += 4 * 97) canvasColors.add(bitmap.readUInt32LE(i));
      assert.ok(canvasColors.size > 30, '3D canvas is unexpectedly blank');
      report.captures[name].canvasSampledColors = canvasColors.size;
    }
    await persist();
  }
  try {
    window.maximize();
    await until(`!!${current}?.session?.getState().loaded`);
    await stage('original-manual-sheet');
    assert.equal(await js(`${current}.session.getState().layout.layoutId`), source);
    await js(`_trainFacilitySheets.activate(${JSON.stringify(target)})`);
    await until(`${current}.session.getState().layout.layoutId === ${JSON.stringify(target)}`);
    await stage('new-sheet-plan');
    await js(`${current}.workspace._setViewMode('plan'); ${current}.workspace.executeCommand('fit-layout');`);
    report.plan = await js(`(()=>{const s=${current}.session.getState();return {id:s.layout.layoutId,placements:s.layout.placements.length,zones:s.layout.zones.length,routes:s.layout.routes.length,markings:s.layout.floorMarkings.length,dirty:s.dirty,sheets:_trainFacilitySheets.state().layouts};})()`);
    assert.equal(report.plan.placements, expectedPlacements);
    assert.equal(report.plan.dirty, false);
    assert.equal(report.plan.sheets.length, 2);
    await capture('01-independent-plan');
    await stage('real-glb-3d');
    await js(`${current}.workspace._setViewMode('3d')`);
    await until(`${current}.workspace.threeAdapter?.getDiagnostics().pendingLoads === 0 && ${current}.workspace.threeAdapter?.getDiagnostics().assetGroupCount > 0`, 180000);
    report.three = await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
    assert.equal(report.three.placementCount, expectedPlacements);
    assert.equal(report.three.degraded, false);
    await js(`${current}.workspace.threeAdapter.isometricView()`);
    await capture('02-independent-3d');
    await js(`${current}.workspace.threeAdapter.topView({minimum:{x:200,y:0,z:109},maximum:{x:222,y:8,z:134}})`);
    await capture('03-robot-cell-detail');
    if (walls) {
      const actual = await js(`${current}.session.getState().layout`);
      assert.deepEqual(actual, JSON.parse(await fs.readFile(targetPath, 'utf8')));
      assert.equal(actual.zones.length, 58);
      report.walls = actual.placements.filter(p => p.assetId.startsWith('asset-factory02-perimeter-'));
      assert.equal(report.walls.length, 6);
      assert.ok(report.walls.every(p => p.positionMode === 'locked'));
      const groups = report.three.representationGroups.filter(g => g.assetId.startsWith('asset-factory02-perimeter-'));
      assert.equal(groups.length, 3);
      assert.ok(groups.every(g => g.representation === 'overview' && g.meshCount > 0));
      assert.equal(report.three.placementTransformAudit.transformMismatchCount, 0);
      for (const [name, position, targetPoint] of [
        ['walls-corner', {x:20,y:10,z:20}, {x:0,y:2,z:0}],
        ['walls-opening', {x:24,y:10,z:110}, {x:0,y:2,z:98}],
        ['walls-overview', {x:340,y:290,z:335}, {x:150,y:0,z:100}],
      ]) {
        await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position=${JSON.stringify(position)};v.target=${JSON.stringify(targetPoint)};v.up={x:0,y:1,z:0};v.fov=45;v.near=0.01;v.far=2000;a.applyCameraView(v);})()`);
        await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads === 0`);
        await capture(name);
      }
      report.wallSpawn = await js(`${current}.workspace.threeAdapter.enterWalkthrough({ignoreSelection:true,worldPoint:{x:0.35,z:50}})`);
      assert.equal(report.wallSpawn.active, true);
      assert.equal(report.wallSpawn.obstacleCount, expectedPlacements);
      assert.ok(report.wallSpawn.position.x >= 0.55 - 1e-6, 'Walkthrough must not spawn through the wall');
      await js(`${current}.workspace.threeAdapter.exitWalkthrough()`);
      report.openingSpawn = await js(`${current}.workspace.threeAdapter.enterWalkthrough({ignoreSelection:true,worldPoint:{x:0.4,z:98}})`);
      assert.equal(report.openingSpawn.active, true);
      assert.ok(Math.abs(report.openingSpawn.position.x - 0.4) < 1e-6);
      assert.ok(Math.abs(report.openingSpawn.position.z - 98) < 1e-6);
      await js(`${current}.workspace.threeAdapter.exitWalkthrough()`);
      window.unmaximize();
      window.setSize(900, 700);
      await pause(500);
      await js(`${current}.workspace.threeAdapter.isometricView()`);
      await capture('walls-narrow');
      window.maximize();
      await pause(500);
    }
    if (cncSides) {
      const actual = await js(`${current}.session.getState().layout`);
      assert.deepEqual(actual, JSON.parse(await fs.readFile(targetPath, 'utf8')));
      report.cncPlacements = actual.placements.filter(p => p.assetId === 'asset-cnc-mill');
      for (const [name, dx, dz] of [
        ['plus-z', 0, 9], ['minus-z', 0, -9], ['plus-x', 9, 0], ['minus-x', -9, 0],
        ['oblique', 6, 9],
      ]) {
        await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position={x:${88 + dx},y:4,z:${146 + dz}};v.target={x:88,y:1.2,z:146};v.up={x:0,y:1,z:0};v.fov=45;v.near=0.01;v.far=2000;a.applyCameraView(v);})()`);
        await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads === 0`);
        await capture('cnc-' + name);
      }
      report.cncDiagnostics = await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
    }
    if (layer2) {
      const audit = JSON.parse(await fs.readFile(path.join(output, 'report.json'), 'utf8'));
      const actual = await js(`JSON.stringify(${current}.session.getState().layout)`);
      const saved = JSON.parse(await fs.readFile(targetPath, 'utf8'));
      assert.deepEqual(JSON.parse(actual), saved);
      const candidate = JSON.parse(await fs.readFile(path.join(output, 'after.json'), 'utf8'));
      // Repository Save owns updatedAt; all other fields must match the evaluated candidate.
      candidate.updatedAt = saved.updatedAt;
      assert.deepEqual(candidate, saved);
      assert.equal(audit.status, 'saved');
      assert.equal(report.plan.markings, 90);
      report.layer2 = { zones: [], savedRevision: audit.savedRevision, exactDocumentMatch: true };
      const zones = await js(`${current}.session.getState().layout.zones`);
      for (const zone of zones) {
        const xs = zone.boundary.map(p => p.x), zs = zone.boundary.map(p => p.z);
        const bounds = { minimum: { x: Math.min(...xs) - 1, y: 0, z: Math.min(...zs) - 1 },
          maximum: { x: Math.max(...xs) + 1, y: 8, z: Math.max(...zs) + 1 } };
        await js(`${current}.workspace.threeAdapter.topView(${JSON.stringify(bounds)})`);
        await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads === 0`);
        const name = 'zone-' + zone.zoneId.replace('zn-independent-', '');
        await capture(name);
        report.layer2.zones.push({ id: zone.zoneId, label: zone.label, capture: name + '.png' });
      }
      for (const [name, x, z, span] of [
        ['detail-robot', 211, 121, 21], ['detail-assembly', 90, 28, 13],
        ['detail-inspection', 213, 18, 12], ['detail-packing', 242, 18, 14],
        ['detail-cnc-mill', 88, 146, 12], ['detail-haas', 88, 170, 12],
      ]) {
        await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position={x:${x + span * 0.55},y:${span * 0.75},z:${z + span}};v.target={x:${x},y:0.6,z:${z}};v.up={x:0,y:1,z:0};v.fov=45;v.near=0.01;v.far=2000;a.applyCameraView(v);})()`);
        await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads === 0`);
        await capture(name);
      }
      await persist();
    }
    await stage('switch-back-and-forth');
    await js(`_trainFacilitySheets.activate(${JSON.stringify(source)})`);
    assert.equal(await js(`${current}.session.getState().layout.placements.length`), 827);
    await js(`_trainFacilitySheets.activate(${JSON.stringify(target)})`);
    assert.equal(await js(`${current}.session.getState().layout.placements.length`), expectedPlacements);
    await js(`${current}.workspace._setViewMode('plan'); ${current}.workspace.executeCommand('fit-layout');`);
    await capture('04-two-layout-sheets');
    assert.equal(sha(await fs.readFile(sourcePath)), before);
    assert.equal(sha(await fs.readFile(targetPath)), targetBefore);
    report.targetUnchangedDuringNativeReview = true;
    report.sourceUnchanged = true;
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.error = error.stack;
    await capture('failure').catch(() => {});
  } finally { await persist(); if (cncSides || walls) app.quit(); }
}

app.once('browser-window-created', (_event, window) => {
  window.webContents.once('did-finish-load', () => {
    void verify(window).catch(async error => {
      await fs.writeFile(path.join(output, 'native-driver-failure.json'), JSON.stringify({ error: error.stack }));
    });
  });
});
require('../src/entry.cjs');
