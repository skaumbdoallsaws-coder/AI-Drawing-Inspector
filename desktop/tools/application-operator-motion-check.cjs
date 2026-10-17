'use strict';
// Normal Electron entry and protected managed backend, using an isolated manual layout.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const driver = require.resolve('./application-check.cjs');
require(driver);
require.cache[driver].exports = { run: async ({ window, profile, output, root }) => {
    const source = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'application-check-source.json'), 'utf8'));
    assert.equal(profile.facilityRoot, source.isolatedFacilityRoot);
    assert.notEqual(path.resolve(profile.facilityRoot), path.resolve(root, '.runtime/facility-layout'));
    await fs.mkdir(output, { recursive: true });
    const report = { status: 'running', stages: [], captures: [], errors: [] };
    const save = () => fs.writeFile(path.join(output, 'operator-motion-check.json'), JSON.stringify(report, null, 2));
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    const stage = async name => { report.stage = name; report.stages.push({ name, at: new Date().toISOString() }); await save(); };
    const js = code => window.webContents.executeJavaScript(code, true);
    const until = async (code, timeout = 120000) => {
        const deadline = Date.now() + timeout;
        while (Date.now() < deadline) { if (await js(code)) return; await delay(100); }
        throw Error('Timeout: ' + code);
    };
    const app = '_trainFacilityLayoutAuthoringApp', w = app + '.workspace', a = w + '.threeAdapter';
    const state = () => js(a + '.activity.getState()');
    const click = async selector => {
        const point = await js('(()=>{const e=document.querySelector(' + JSON.stringify(selector) + ');if(!e||e.disabled||e.closest("[inert]"))throw Error("Unavailable control");const r=e.getBoundingClientRect();if(!r.width||!r.height)throw Error("Hidden control");return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};})()');
        window.webContents.sendInputEvent({ type: 'mouseMove', ...point });
        window.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...point });
        window.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, ...point });
        await delay(150);
    };
    const shot = async name => {
        const image = await window.webContents.capturePage(); assert(!image.isEmpty());
        await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
        const pixels = image.toBitmap(), colors = new Set();
        for (let i = 0; i < pixels.length; i += 64) colors.add(pixels.subarray(i, i + 3).toString('hex'));
        assert(colors.size > 100); report.captures.push({ name, ...image.getSize(), colors: colors.size });
    };
    const seek = async seconds => {
        await js(a + '.activity.pause();' + a + '.activity.seek(' + seconds + ')');
        await until('!' + a + '.getDiagnostics().demandRendering.pendingFrame');
        return state();
    };
    window.webContents.on('console-message', details => {
        if (details?.level === 'error' && /Shader Error|WebGL.*error/i.test(details.message)) report.errors.push(details.message);
    });
    try {
        await stage('manual-load');
        window.setTitle('InspectorPro - Isolated operator motion check');
        await until('!!window.' + app + '?.session.getState().loaded');
        const original = await js(app + '.session.getState()');
        assert.equal(original.layout.placements.length, 827);
        const saved = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', original.layout.layoutId + '.json');
        const hash = async file => createHash('sha256').update(await fs.readFile(file)).digest('hex');
        const savedHash = await hash(saved);
        await click('#trainFacilityLayoutAuthoring [data-view="3d"]');
        await until(a + '.getDiagnostics().pendingLoads===0 && ' + a + '.getDiagnostics().assetGroupCount>0', 240000);
        const groups = await js(a + '.getDiagnostics().representationGroups');
        const operator = groups.find(g => g.assetId === 'asset-operator');
        assert.equal(operator.representation, 'operator-avatar'); assert(operator.instanced);
        assert.equal(operator.placementIds.length, 20);
        report.standingOperators = { count: 20, representation: operator.representation, instanced: true };
        await stage('complete-reference-motion');
        await js('window.__operatorMotion={};' + w + '.startActivityPlayback({preset:"reference_complete_navigation",prototypeMode:true,maximumActors:23}).then(r=>window.__operatorMotion={done:true,result:r}).catch(e=>window.__operatorMotion={done:true,error:e.message,code:e.code})');
        await until('window.__operatorMotion.done', 600000);
        const result = await js('window.__operatorMotion'); assert(!result.error, JSON.stringify(result));
        const first = await seek(3.17);
        const operators = first.actors.filter(t => t.actorType === 'operator');
        assert(operators.length >= 2);
        assert(operators.every(t => t.visualSource === 'animated-operator-avatar' && !t.exactCatalogVisual && t.sourcePlacementSuppressed));
        assert(first.actors.filter(t => t.actorType === 'vehicle').every(t => t.exactCatalogVisual));
        assert.deepEqual(first.duplicateVisiblePlacementIds, []);
        const worker = operators.find(t => t.visible && t.avatar.animation === 'walk' && Math.abs(t.avatar.leftHip) > .01);
        assert(worker);
        report.activity = first;
        await js('(()=>{const a=' + a + ',v=a.getCameraView(),p=' + JSON.stringify(worker.pose) + ';v.position={x:p.x+3,y:2.6,z:p.z+4};v.target={x:p.x,y:.9,z:p.z};a.applyCameraView(v);})()');
        await until('!' + a + '.getDiagnostics().demandRendering.pendingFrame');
        await shot('01-walking-a');
        const second = await seek(3.51);
        assert.notEqual(second.actors.find(t => t.actorId === worker.actorId).avatar.phase, worker.avatar.phase);
        await shot('02-walking-b');
        assert.deepEqual((await seek(3.17)).actors.find(t => t.actorId === worker.actorId).avatar, worker.avatar);
        await stage('native-play-pause');
        await click('[data-motion-action="toggle-play"]');
        await until(a + '.activity.getState().elapsedSeconds>4');
        await click('[data-motion-action="toggle-play"]');
        const frozen = await state(); await delay(500);
        assert.deepEqual((await state()).actors, frozen.actors);
        await click('#trainFacilityLayoutAuthoring [data-view="plan"]');
        await shot('03-plan-motion');
        await click('#trainFacilityLayoutAuthoring [data-view="3d"]');
        window.setSize(900, 700); await delay(500); await shot('04-narrow-motion');
        await click('[data-motion-action="close"]');
        assert.equal((await state()).loaded, false);
        const final = await js(app + '.session.getState()');
        for (const key of ['layout','selection','history','historyCursor','baseRevision','draftRevision','dirty']) assert.deepEqual(final[key], original[key], key);
        assert.equal(await hash(saved), savedHash);
        assert.equal(await hash(source.originalPath), source.originalSha256);
        assert.deepEqual(report.errors, []);
        report.savedLayoutsUnchanged = true; report.status = 'passed'; await stage('complete');
    } catch (error) {
        report.status = 'failed'; report.error = error.stack;
        try { await shot('failure'); } catch (_) {}
        throw error;
    } finally { await save(); }
} };
require('../src/application-main.cjs');

