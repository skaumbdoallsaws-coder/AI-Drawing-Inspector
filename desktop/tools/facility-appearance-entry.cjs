'use strict';
// Runs only against a copied store and an isolated desktop profile.
const {app} = require('electron');
const fs = require('node:fs/promises'), path = require('node:path');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile), current = 'window._trainFacilityLayoutAuthoringApp';
const pause = ms => new Promise(r => setTimeout(r, ms));
const sha = b => createHash('sha256').update(b).digest('hex');

async function verify(window) {
    const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
    assert.equal(profile.profileId, 'facility-appearance-review');
    assert.equal(path.resolve(profile.facilityRoot), path.join(output, 'store'));
    const relative = 'layouts/local/site-local/layouts/fl-independent-factory-20260928.json';
    const target = path.join(profile.facilityRoot, relative);
    const live = path.resolve(__dirname, '../../.runtime/facility-layout', relative);
    const liveHash = sha(await fs.readFile(live));
    const before = await fs.readFile(target), original = JSON.parse(before);
    const racks = original.placements.filter(p => p.assetId === 'asset-pallet-rack').slice(0, 3);
    const wall = original.placements.find(p => p.placementId === 'pl-yard-west-R2-before');
    assert.equal(racks.length, 3); assert.ok(wall);
    const report = {status:'running', liveHash, captures:{}};
    const persist = () => fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    const js = code => window.webContents.executeJavaScript(code, true);
    async function until(code, timeout=120000) {
        const end = Date.now() + timeout;
        while (Date.now() < end) { if (await js(code)) return; await pause(150); }
        throw Error('Timed out: ' + code);
    }
    async function capture(name) {
        await js('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
        await pause(400);
        const image = await window.webContents.capturePage();
        assert.ok(!image.isEmpty());
        await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
        const rect = await js(`(()=>{const r=${current}.workspace.threeAdapter.getRecordingCanvas().getBoundingClientRect();return{x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)}})()`);
        const pixels = (await window.webContents.capturePage(rect)).toBitmap(), colors = new Set();
        for (let i=0; i+4<=pixels.length; i+=116) colors.add(pixels.readUInt32LE(i));
        assert.ok(colors.size > 40, 'Blank 3D canvas');
        report.captures[name] = {size:image.getSize(), colors:colors.size}; await persist();
    }
    async function color(ids, value, custom=false) {
        await js(`${current}.session.selectMany(${JSON.stringify(ids)})`);
        await js(`document.querySelector('[data-facility-ribbon-command="appearance"]').click()`);
        await until(`${current}.workspace.appearanceDialog != null`);
        await js(`(()=>{const d=${current}.workspace.appearanceDialog;${value === null
            ? "d.querySelector('[data-appearance-reset]').click();"
            : custom ? `const p=d.querySelector('[data-appearance-color]');p.value=${JSON.stringify(value)};p.dispatchEvent(new Event('change',{bubbles:true}));`
            : `d.querySelector('[data-appearance-swatch="${value}"]').click();`}
            d.querySelector('[data-appearance-apply]').click();})()`);
        await until(`!${current}.workspace.appearanceDialog && !${current}.session.getState().busy`);
    }
    const state = () => js(`${current}.session.getState()`);
    try {
        if (window.isMaximized()) window.unmaximize(); window.setSize(1440, 900);
        await until(`${current}?.session?.getState().loaded`, 180000);
        assert.deepEqual((await state()).layout, original);
        await js(`${current}.workspace._setViewMode('3d')`);
        await until(`!!${current}.workspace.lastLayoutFingerprint && ${current}.workspace.lastThreeFitFingerprint===${current}.workspace.lastLayoutFingerprint`);
        await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position={x:28,y:17,z:121};v.target={x:9,y:2,z:146};v.up={x:0,y:1,z:0};a.applyCameraView(v);})()`);
        await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0`);
        report.stage='rack-color'; await persist();
        await color([racks[0].placementId], '#2478bc');
        let edited = await state();
        assert.equal(edited.layout.placements.find(p=>p.placementId===racks[0].placementId).appearance.color, '#2478bc');
        assert.deepEqual(edited.layout.placements.find(p=>p.placementId===racks[1].placementId), racks[1]);
        assert.equal(sha(await fs.readFile(target)), sha(before));
        await js(`${current}.session.clearSelection()`); await capture('01-one-blue-rack');
        await js(`${current}.session.undo()`); assert.deepEqual((await state()).layout, original);
        await js(`${current}.session.redo()`); assert.deepEqual((await state()).layout, edited.layout);
        await color([racks[0].placementId], null); assert.deepEqual((await state()).layout, original);
        await color([racks[0].placementId, racks[1].placementId], '#28866b');
        await color([wall.placementId], '#e8ecef', true);
        edited = await state();
        assert.equal(edited.layout.placements.find(p=>p.placementId===wall.placementId).appearance.color, '#e8ecef');
        const clean = doc => doc.placements.map(p => {const q={...p};delete q.appearance;return q;});
        assert.deepEqual(clean(edited.layout), clean(original));
        assert.equal(edited.layout.placements.find(p=>p.placementId===racks[2].placementId).appearance, undefined);
        await js(`${current}.session.clearSelection()`);
        await capture('02-green-racks-white-wall');
        await js(`${current}.session.selectMany(${JSON.stringify([racks[0].placementId, wall.placementId])})`);
        await js(`${current}.workspace.openAppearanceDialog()`);
        assert.equal(await js(`${current}.workspace.appearanceDialog.querySelector('.ip-flw-appearance-value').textContent`), 'Mixed colors');
        await capture('02-mixed-appearance');
        window.setSize(900,700); await pause(700);
        report.dialogBounds = await js(`(()=>{const r=${current}.workspace.appearanceDialog.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:innerWidth,height:innerHeight}})()`);
        const b=report.dialogBounds; assert.ok(b.x>=0 && b.y>=0 && b.right<=b.width && b.bottom<=b.height);
        report.dialogContentsFit = await js(`(()=>{const d=${current}.workspace.appearanceDialog,r=d.getBoundingClientRect();return Array.from(d.querySelectorAll('button,input')).every(e=>{const b=e.getBoundingClientRect();return b.left>=r.left&&b.right<=r.right&&b.top>=r.top&&b.bottom<=r.bottom})&&d.querySelector('.ip-flw-precision-body').scrollWidth<=d.querySelector('.ip-flw-precision-body').clientWidth})()`);
        assert.equal(report.dialogContentsFit, true);
        await capture('03-narrow');
        await js(`${current}.session.select(${JSON.stringify(racks[2].placementId)})`);
        assert.equal(await js(`${current}.workspace.appearanceDialog.querySelector('[data-appearance-apply]').disabled`), true);
        await js(`${current}.workspace.closeAppearanceDialog()`);
        report.stage='isolated-save'; await persist();
        await js(`${current}.session.save()`);
        assert.equal((await state()).dirty, false);
        assert.equal(JSON.parse(await fs.readFile(target,'utf8')).placements.find(p=>p.placementId===wall.placementId).appearance.color, '#e8ecef');
        await js(`${current}.session.reload()`);
        assert.equal((await state()).layout.placements.find(p=>p.placementId===racks[0].placementId).appearance.color, '#28866b');
        assert.equal(sha(await fs.readFile(live)), liveHash);
        report.liveLayoutUnchanged=true; report.status='passed';
    } catch(error) {
        report.status='failed'; report.error=error.stack;
        report.session=await state().then(s=>({busy:s.busy,lastError:s.lastError,dirty:s.dirty})).catch(()=>null);
        await capture('failure').catch(()=>{});
    } finally {
        await persist();
        if (report.status !== 'passed') await js(`${current}?.session?.reload()`).catch(()=>{});
        app.quit();
    }
}
app.once('browser-window-created', (_event, window) => window.webContents.once('dom-ready', () => void verify(window).catch(async error => {
    await fs.writeFile(path.join(output,'driver-error.json'), JSON.stringify({error:error.stack}));app.quit();
})));
require('../src/entry.cjs');
