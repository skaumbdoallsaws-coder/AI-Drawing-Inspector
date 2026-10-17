'use strict';
// Read-only review of the exact staged palette through the normal desktop app.
const {app} = require('electron');
const fs = require('node:fs/promises'), path = require('node:path');
const assert = require('node:assert/strict'), {createHash} = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile), current = 'window._trainFacilityLayoutAuthoringApp';
const pause = ms => new Promise(r => setTimeout(r, ms));
const sha = b => createHash('sha256').update(b).digest('hex');

async function verify(window) {
    const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
    assert.equal(profile.profileId, 'factory02-palette-review');
    assert.equal(path.resolve(profile.facilityRoot), path.join(output, 'store'));
    const relative = 'layouts/local/site-local/layouts/fl-independent-factory-20260928.json';
    const target = path.join(profile.facilityRoot, relative);
    const live = path.resolve(__dirname, '../../.runtime/facility-layout', relative);
    const before = await fs.readFile(target), expected = JSON.parse(before);
    const liveHash = sha(await fs.readFile(live));
    const report = {status:'running', candidateHash:sha(before), liveHash, captures:{}};
    const persist = () => fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    const js = code => window.webContents.executeJavaScript(code, true);
    async function until(code, timeout=180000) {
        const end = Date.now() + timeout;
        while (Date.now() < end) {if (await js(code)) return; await pause(200);}
        throw Error('Timed out: ' + code);
    }
    async function camera(position, target) {
        await js(`(()=>{const a=${current}.workspace.threeAdapter,v=a.getCameraView();v.position=${JSON.stringify(position)};v.target=${JSON.stringify(target)};v.up={x:0,y:1,z:0};v.fov=45;v.near=.03;v.far=2000;a.applyCameraView(v);})()`);
        await pause(1200);
        await until(`${current}.workspace.threeAdapter.getDiagnostics().pendingLoads===0`);
    }
    async function capture(name, canvas=true) {
        await js('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
        await pause(500);
        const image = await window.webContents.capturePage();
        assert.ok(!image.isEmpty());
        await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
        report.captures[name] = {size:image.getSize()};
        if (canvas) {
            const rect = await js(`(()=>{const r=${current}.workspace.threeAdapter.getRecordingCanvas().getBoundingClientRect();return{x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)}})()`);
            const pixels = (await window.webContents.capturePage(rect)).toBitmap(), colors = new Set();
            for (let i=0; i+4<=pixels.length; i+=116) colors.add(pixels.readUInt32LE(i));
            assert.ok(colors.size > 40, 'Blank 3D canvas');
            report.captures[name].colors = colors.size;
        }
        await persist();
    }
    try {
        if (window.isMaximized()) window.unmaximize(); window.setSize(1440,900);
        await until(`${current}?.session?.getState().loaded`);
        assert.deepEqual(await js(`${current}.session.getState().layout`), expected);
        await js(`${current}.workspace._setViewMode('plan')`);
        await capture('00-plan', false);
        await js(`${current}.workspace._setViewMode('3d')`);
        await until(`!!${current}.workspace.lastLayoutFingerprint && ${current}.workspace.lastThreeFitFingerprint===${current}.workspace.lastLayoutFingerprint`);
        await js(`(()=>{const w=${current}.workspace;w._setLayerPanelOpen(true);const b=w.layerPanel.querySelector('[data-facility-layer="walls"]');if(!b.checked)b.click();w._setLayerPanelOpen(false);})()`);
        await camera({x:435,y:315,z:375}, {x:145,y:0,z:100});
        await capture('01-factory-overview');
        await camera({x:28,y:17,z:121}, {x:9,y:2,z:146});
        await capture('02-racks-and-walls');
        await camera({x:156,y:20,z:112}, {x:143,y:1,z:150});
        await capture('03-machining');
        await camera({x:195,y:19,z:102}, {x:216,y:1,z:126});
        await capture('04-robot-cells');
        await camera({x:320,y:13,z:26}, {x:311,y:0,z:47});
        await capture('05-lunchroom');
        report.diagnostics = await js(`${current}.workspace.threeAdapter.getDiagnostics()`);
        assert.equal(report.diagnostics.degraded, false);
        assert.equal(report.diagnostics.placementTransformAudit.transformMismatchCount, 0);
        assert.equal(report.diagnostics.placementTransformAudit.missingPlacementCount, 0);
        assert.ok(report.diagnostics.visibleLegacyWallPlacementCount > 0);
        window.setSize(900,700);
        await camera({x:28,y:17,z:121}, {x:9,y:2,z:146});
        await capture('06-narrow');
        await js(`${current}.session.reload()`);
        assert.deepEqual(await js(`${current}.session.getState().layout`), expected);
        assert.equal(await js(`${current}.session.getState().dirty`), false);
        assert.equal(sha(await fs.readFile(target)), report.candidateHash);
        assert.equal(sha(await fs.readFile(live)), liveHash);
        report.savedDocumentUnchanged = true;
        report.status = 'passed';
    } catch(error) {
        report.status = 'failed'; report.error = error.stack;
        await capture('failure', false).catch(()=>{});
    } finally {await persist(); app.quit();}
}
app.once('browser-window-created', (_event, window) => window.webContents.once('dom-ready', () => void verify(window).catch(async error => {
    await fs.writeFile(path.join(output,'driver-error.json'), JSON.stringify({error:error.stack})); app.quit();
})));
require('../src/entry.cjs');
