'use strict';
// Native File > Open Layout acceptance; saved documents are never modified.
const { app } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile);
const manual = 'fl-reference-manual-20260812';
const factory = 'fl-independent-factory-20260928';
const current = 'window._trainFacilityLayoutAuthoringApp';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function check(window) {
    const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
    const report = {status: 'running', stages: []};
    const persist = () => fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    const js = code => window.webContents.executeJavaScript(code, true);
    const until = async (code, timeout = 120000) => {
        const end = Date.now() + timeout;
        while (Date.now() < end) { if (await js(code)) return; await pause(200); }
        throw Error('Timeout: ' + code);
    };
    const click = async selector => assert.equal(await js(`(()=>{
        const e=document.querySelector(${JSON.stringify(selector)});
        if(!e||e.disabled)return false;e.click();return true;})()`), true, selector);
    const hashes = async () => {
        const result = {};
        for (const id of [manual, factory]) result[id] = createHash('sha256').update(await fs.readFile(
            path.join(profile.facilityRoot, 'layouts/local/site-local/layouts', id + '.json'))).digest('hex');
        return result;
    };
    const capture = async name => {
        await pause(400);
        const shot = await window.webContents.capturePage();
        assert.equal(shot.isEmpty(), false);
        await fs.writeFile(path.join(output, name + '.png'), shot.toPNG());
        report.stages.push(name); await persist();
    };
    const open = async () => {
        await click('[data-menu="file"] .app-menu-label');
        await click('[data-action="open-layout"]');
        await until('!!document.querySelector("dialog[open] [data-open-layout-choice]")');
    };
    try {
        window.webContents.setBackgroundThrottling(false);
        window.setSize(1440, 900); window.show();
        report.before = await hashes(); await persist();
        await until(`!!${current}?.session?.getState().loaded && !!document.querySelector('.ip-layout-sheet-tab')`);
        assert.equal(await js(`${current}.session.getState().layout.layoutId`), manual);
        assert.equal(await js(`document.querySelectorAll('.ip-layout-sheet-tab').length`), 1);
        assert.equal(await js(`!!document.querySelector('.ip-layout-sheet-open')`), false);
        await open();
        assert.equal(await js(`Array.from(document.querySelector('[data-open-layout-choice]').options).some(o=>o.value==='${factory}'&&o.textContent==='Factory 02 - Integrated Production')`), true);
        await js(`document.querySelector('[data-open-layout-choice]').value='${factory}'`);
        await capture('01-open-layout-wide');
        await click('dialog[open] button[type="button"]');
        assert.equal(await js(`document.querySelectorAll('.ip-layout-sheet-tab').length`), 1);
        await js(`(async()=>{const a=${current};window.__sheetManualApp=a;
            await a.session.renameLayout('Manual draft retention check');
            a.session.select(a.session.getState().layout.placements[0].placementId);
            window.__sheetSnapshot=()=>{const s=window.__sheetManualApp.session.getState();
                return JSON.stringify(Object.fromEntries(['layout','draftRevision','operations','selection','history','historyCursor'].map(k=>[k,s[k]])));};
            window.__sheetBefore=window.__sheetSnapshot();})()`);
        await open();
        await js(`(()=>{const s=document.querySelector('[data-open-layout-choice]');s.value='${factory}';s.form.requestSubmit();})()`);
        await until(`${current}.session.getState().layout.layoutId==='${factory}' && !_trainFacilitySheets.state().busy`);
        report.factory = await js(`(()=>{const s=${current}.session.getState();return {
            id:s.layout.layoutId,placements:s.layout.placements.length,
            movementPrograms:s.layout.extensions.facilityNavigation.movementPrograms.length,dirty:s.dirty};})()`);
        assert.equal(report.factory.placements, 836);
        assert.equal(report.factory.movementPrograms, 40);
        assert.equal(report.factory.dirty, false);
        assert.equal(await js(`document.querySelectorAll('.ip-layout-sheet-tab').length`), 2);
        await js(`_setLeftPanelContent('structure',{reveal:true})`);
        await capture('02-factory-opened');
        await click(`.ip-layout-sheet-tab[data-layout-id="${manual}"]`);
        await until(`${current}===window.__sheetManualApp && !_trainFacilitySheets.state().busy`);
        assert.equal(await js('window.__sheetSnapshot()===window.__sheetBefore'), true);
        assert.equal(await js(`${current}.session.getState().dirty`), true);
        await js(`${current}.session.undo()`);
        assert.equal(await js(`${current}.session.getState().dirty`), false);
        await click(`.ip-layout-sheet-tab[data-layout-id="${factory}"]`);
        await until(`${current}.session.getState().layout.layoutId==='${factory}' && !_trainFacilitySheets.state().busy`);
        window.setSize(900, 700); await pause(500);
        await open();
        await js(`document.querySelector('[data-open-layout-choice]').value='${factory}'`);
        report.bounds = await js(`(()=>{const d=document.querySelector('dialog[open]').getBoundingClientRect();return {
            x:d.x,y:d.y,right:d.right,bottom:d.bottom,width:innerWidth,height:innerHeight};})()`);
        assert.ok(report.bounds.x >= 0 && report.bounds.y >= 0 && report.bounds.right <= report.bounds.width && report.bounds.bottom <= report.bounds.height);
        await capture('03-open-layout-narrow');
        await click('dialog[open] button[type="button"]');
        await click('.tab[data-tab="drawing"]');
        await click('[data-menu="file"] .app-menu-label');
        assert.equal(await js(`document.querySelector('[data-action="open-layout"]').disabled`), true);
        report.after = await hashes(); assert.deepEqual(report.after, report.before);
        report.status = 'passed';
    } catch (error) {
        report.status = 'failed'; report.error = error.stack;
        await capture('failure').catch(() => {});
        report.ui = await js(`({error:document.querySelector('.ip-layout-sheet-error')?.textContent,
            dialog:document.querySelector('dialog[open]')?.textContent,layout:${current}?.session.getState().layout.layoutId})`).catch(() => null);
    } finally { await persist(); app.quit(); }
}
app.once('browser-window-created', (_event, window) => window.webContents.once('did-finish-load', () => {
    void check(window).catch(async error => { await fs.writeFile(path.join(output, 'driver-error.txt'), error.stack); app.quit(); });
}));
require('../src/entry.cjs');
