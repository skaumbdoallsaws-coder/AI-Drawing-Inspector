'use strict';
// Exercise the normal Electron application with copied layout data only.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const driver = require.resolve('./application-check.cjs');
require(driver);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
require.cache[driver].exports = { run: async ({ window, profile, output, root, network, runtime }) => {
    const source = JSON.parse(await fs.readFile(path.join(profile.dataRoot, 'application-check-source.json'), 'utf8'));
    assert.equal(profile.facilityRoot, source.isolatedFacilityRoot);
    assert.notEqual(path.resolve(profile.facilityRoot), path.resolve(root, '.runtime/facility-layout'));
    const copied = path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', path.basename(source.originalPath));
    const before = { original: sha(await fs.readFile(source.originalPath)), copy: sha(await fs.readFile(copied)) };
    assert.equal(before.original, source.originalSha256);
    assert.equal(before.copy, before.original);
    await fs.mkdir(output, { recursive: true });
    const report = { status: 'running', scope: 'Native ribbon and dialogs on copied Private Gym; no Save', commands: [], scripts: [], captures: [] };
    const persist = () => fs.writeFile(path.join(output, 'authoring-native.json'), JSON.stringify(report, null, 2));
    const js = code => window.webContents.executeJavaScript(code, true);
    const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
    const current = 'window._trainFacilityLayoutAuthoringApp';
    async function until(code, label, timeout = 120000) {
        const deadline = Date.now() + timeout;
        while (Date.now() < deadline) { if (await js(code)) return; await pause(200); }
        throw Error(label);
    }
    async function capture(name) {
        await pause(300);
        const image = await window.webContents.capturePage();
        assert.ok(!image.isEmpty(), 'Empty native capture');
        await fs.writeFile(path.join(output, name + '.png'), image.toPNG());
        report.captures.push({ name, size: image.getSize() });
        await persist();
    }
    async function clickCommand(command) {
        const result = await js(`(()=>{
            const command=${JSON.stringify(command)}, visible=n=>!!n&&n.checkVisibility();
            const find=()=>Array.from(document.querySelectorAll('[data-facility-ribbon-command]')).find(n=>n.dataset.facilityRibbonCommand===command&&visible(n));
            let button=find();
            if(!button){
                const menu=Array.from(document.querySelectorAll('[data-facility-command-menu]')).find(n=>n.dataset.facilityCommandMenu.split(',').includes(command)&&visible(n));
                if(menu)menu.click();else document.getElementById('facilityLayoutOverflowMenuRibbon')?.click();
                button=find();
            }
            if(!button||button.disabled)return {ok:false,reason:'No enabled visible ribbon command: '+command};
            button.click();return {ok:true};
        })()`);
        assert.equal(result.ok, true, result.reason);
    }
    async function dialog(command, title, width) {
        report.stage = command + '-' + width; await persist();
        await clickCommand(command);
        await until(`!!document.querySelector('dialog[open][aria-label=${JSON.stringify(title)}]')`, 'Dialog did not open: ' + title);
        if (command === 'component-materials') {
            await until(`!!document.querySelector('dialog[open] select[aria-label="Component"]')`, 'CAD material components did not load');
            report.materialSlots = await js(`document.querySelector('dialog[open] select[aria-label="Component"]').options.length`);
            assert.ok(report.materialSlots > 0);
        }
        const bounds = await js(`(()=>{const d=document.querySelector('dialog[open]'),r=d.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:innerWidth,height:innerHeight,overflow:d.scrollWidth>d.clientWidth};})()`);
        assert.ok(bounds.x >= 0 && bounds.y >= 0 && bounds.right <= bounds.width && bounds.bottom <= bounds.height, JSON.stringify(bounds));
        assert.equal(bounds.overflow, false);
        await capture(command + '-' + width);
        await js(`Array.from(document.querySelector('dialog[open]').querySelectorAll('button')).find(b=>b.textContent.trim()==='Cancel').click()`);
        await until(`!document.querySelector('dialog[open]')`, 'Dialog did not cancel');
        report.commands.push({ command, width, dialogFits: true, cancelled: true });
    }
    try {
        await persist();
        window.maximize(); window.webContents.setBackgroundThrottling(false);
        await until(`${current}?.session?.getState().loaded`, 'Private Gym did not mount', 180000);
        const initial = await js(`${current}.session.getState()`);
        assert.equal(initial.layout.layoutId, profile.startupLayoutId);
        assert.equal(initial.baseRevision, before.original);
        const selected = initial.layout.placements.find(p => p.assetId === 'asset-gym-commercial-workout-bench-apex');
        assert.ok(selected, 'Real CAD bench fixture missing');
        await js(`${current}.session.select(${JSON.stringify(selected.placementId)})`);
        for (const name of ['decals', 'lettering', 'authoring_dialog', 'component_materials', 'interior_walls', 'floor_surfaces', 'replace_asset']) {
            const relative = 'static/facility_layout_' + name + '.js';
            const expected = sha(await fs.readFile(path.join(root, relative)));
            const actual = await js(`(async()=>{const r=await fetch('/${relative}',{cache:'no-store'});if(!r.ok)throw Error('Static module failed: '+r.status);const b=await r.arrayBuffer();return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',b))).map(v=>v.toString(16).padStart(2,'0')).join('');})()`);
            assert.equal(actual, expected, 'Desktop served stale module: ' + name);
            report.scripts.push({ name, sha256: expected, current: true });
        }
        await capture('01-ribbon');
        const tools = [['decals', 'Wall decals'], ['lettering', 'Wall lettering'], ['interior-walls', 'Interior Walls'], ['floor-surfaces', 'Floor Surfaces'], ['replace-asset', 'Replace Asset'], ['component-materials', 'Component Materials']];
        for (const [command, title] of tools) await dialog(command, title, 'wide');
        window.unmaximize(); window.setSize(1000, 760); await pause(500);
        for (const [command, title] of tools.filter(([c])=>c!=='component-materials')) await dialog(command, title, 'compact');
        const final = await js(`${current}.session.getState()`);
        assert.equal(final.draftRevision, initial.draftRevision);
        assert.deepEqual(final.layout, initial.layout);
        assert.deepEqual(final.history, initial.history);
        assert.equal(final.dirty, false);
        report.after = { original: sha(await fs.readFile(source.originalPath)), copy: sha(await fs.readFile(copied)) };
        assert.deepEqual(report.after, before);
        report.layoutsUnchanged = true;
        report.runtime = { origin: profile.origin, layoutId: profile.startupLayoutId, backendReady: runtime.getState().status === 'ready' };
        report.status = 'passed'; report.stage = 'complete';
    } catch (error) {
        report.status = 'failed'; report.error = error.stack;
        report.dialogText = await js(`document.querySelector('dialog[open]')?.textContent`).catch(()=>null);
        await capture('failure').catch(()=>{});
        throw error;
    } finally { await persist(); }
} };
require('../src/application-main.cjs');
