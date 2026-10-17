'use strict';
const {app, dialog} = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const out = path.dirname(profileFile);
const root = path.resolve(__dirname, '../..');
const current = 'window._trainFacilityLayoutAuthoringApp';
const adapter = current + '.workspace.threeAdapter';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = value => createHash('sha256').update(value).digest('hex');
const xyz = a => ({x:a[0], y:a[1], z:a[2]});
// Camera positions are inside the existing room boundaries; cuts between rooms
// are intentional. Only within-room movements are interpolated.
const shots = [
    ['03-complete-gym', [106,84,111], [40,0,27]],
    ['04-campus-reveal', [99,51,93], [39,1,26]],
    ['05-reception', [10.6,2.15,8.8], [3.8,1.3,3.5]],
    ['06-cardio', [34,2.3,8.5], [20,1.2,3.8]],
    ['07-free-weights', [15.1,2.3,13], [6.5,1.15,23]],
    ['08-strength-machines', [29.5,2.5,13.2], [24,1.2,24]],
    ['09-cables-and-upper-body', [39.5,2.5,14], [44.8,1.2,24]],
    ['10-functional-training', [38,2.2,9], [46,0.8,5.3]],
    ['11-boxing', [62.4,2.5,13.8], [74,1.5,7.5]],
    ['12-basketball', [70.4,2.8,18.7], [71,2.8,35.8]],
    ['13-soccer', [39.7,3.1,59], [17,2,44]],
    ['14-recovery', [54.5,2,8.7], [58.2,1.1,4.3]],
    ['15-lockers', [52.5,2.1,28.4], [57,1.1,24]],
    ['16-washrooms', [52.2,2,20.6], [57.2,1.2,16]],
    ['17-warrior-hall', [33.9,1.75,-1.55], [15,1.6,-2.7]],
    ['18-private-office', [31.1,2.1,-4.5], [33.2,1.15,-8.2]],
    ['19-conference', [23.1,2.15,-4.1], [26,1.1,-8.3]],
    ['20-kitchen', [27,2,-12], [24.3,1.1,-16]],
    ['21-cafe', [34.9,2.15,-12.1], [30.3,0.9,-15.3]],
    ['22-pool-and-spa', [47.1,3,-3.1], [41.6,0.4,-11]],
    ['23-pool-artwork', [46.7,2.1,-14.7], [41.3,2,-0.1]],
    ['24-social-lounge', [6.15,2.45,-15.8], [16.6,1.1,-6.4]],
    ['25-piano-and-guitars', [5.8,2,-7.4], [2.7,1.35,-3.65]],
    ['26-billiards', [4.8,2.1,-14.8], [2.5,0.82,-11.4]],
    ['27-table-games', [16.5,2.2,-13.6], [20.1,0.9,-16.3]],
    ['28-outdoor-training', [79.5,9,61], [57,0.7,49]],
    ['29-calisthenics-and-powerlifting', [65.5,3.5,61.4], [54.8,1.1,67]],
    ['30-barbecue-patio', [81,3.1,61.9], [74.5,1.1,68]],
    ['31-outdoor-identity', [66,3.2,58.6], [53,2.3,39.9]],
    ['32-closing-campus', [111,69,108], [40,0,28]],
];

const originalDialog = dialog.showMessageBox.bind(dialog);
dialog.showMessageBox = async (...args) => {
    if (args.at(-1).title !== 'InspectorPro startup') return originalDialog(...args);
    await fs.writeFile(path.join(out, 'startup-error.json'), JSON.stringify(args.at(-1)));
    app.quit();
    return {response:0, checkboxChecked:false};
};

async function rehearse(window) {
    const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
    const options = JSON.parse(await fs.readFile(path.join(out, 'tour.json'), 'utf8'));
    const relative = 'layouts/local/site-local/layouts/fl-private-gym-20261007.json';
    const saved = path.join(profile.facilityRoot, relative);
    const live = path.join(root, '.runtime/facility-layout', relative);
    const expected = JSON.parse(await fs.readFile(saved, 'utf8'));
    const report = {status:'running', stage:'starting', captures:[], blockedWrites:[], errors:[]};
    const persist = () => fs.writeFile(path.join(out, 'report.json'), JSON.stringify(report,null,2));
    let paused = false, stopped = false;
    const js = code => window.webContents.executeJavaScript(code, true);
    const key = (event,input) => {
        if (input.type !== 'keyDown' || input.isAutoRepeat) return;
        if (input.key === 'F8') { event.preventDefault(); paused = !paused; }
        if (input.key === 'F9') { event.preventDefault(); stopped = true; }
    };
    window.webContents.on('before-input-event',key);
    window.webContents.session.webRequest.onBeforeRequest(
        {urls:[profile.origin + '/api/*']}, (details,callback) => {
            const blocked = !['GET','HEAD','OPTIONS'].includes(details.method);
            if(blocked) report.blockedWrites.push({url:details.url,method:details.method});
            callback({cancel:blocked});
        });
    async function gate() {
        const deadline = Date.now()+300000;
        while(paused && !stopped && Date.now()<deadline) await sleep(100);
        if(stopped || paused) throw new Error(stopped?'Tour stopped':'Pause timeout');
    }
    async function hold(ms) {
        for(let remaining=ms;remaining>0;remaining-=100) {await gate();await sleep(Math.min(100,remaining));}
    }
    async function until(code,timeout=120000) {
        const end=Date.now()+timeout;
        while(Date.now()<end) {await gate();if(await js(code))return;await sleep(250);}
        throw new Error('Timed out: '+code);
    }
    async function unchanged() {
        const state=await js(`${current}.session.getState()`);
        assert.deepEqual(state.layout,expected);
        assert.equal(state.dirty,false);
        assert.equal(hash(await fs.readFile(live)),options.originalHash);
        assert.equal(hash(await fs.readFile(saved)),options.originalHash);
    }
    async function capture(name) {
        await unchanged();
        const shot=await window.webContents.capturePage();
        assert.ok(!shot.isEmpty());
        const bitmap=shot.toBitmap(),colors=new Set();
        for(let i=0;i+4<=bitmap.length;i+=116)colors.add(bitmap.readUInt32LE(i));
        assert.ok(colors.size>100,'Blank capture');
        await fs.writeFile(path.join(out,name+'.png'),shot.toPNG());
        const d=await js(`${adapter}?.getDiagnostics()`);
        report.captures.push({name,colors:colors.size,pendingLoads:d?.pendingLoads,
            warnings:d?.warnings,rendering:d?.rendering,performance:d?.performance,
            representations:d?.representationGroups?.map(g=>({assetId:g.assetId,representation:g.representation})),
            camera:d?.camera});
        await persist();
    }
    async function camera(position,target,fov=65) {
        await js(`(()=>{const a=${adapter},v=a.getCameraView();
            Object.assign(v,{position:${JSON.stringify(xyz(position))},target:${JSON.stringify(xyz(target))},
                up:{x:0,y:1,z:0},fov:${fov},near:.05,far:600});a.applyCameraView(v);})()`);
    }
    try {
        await persist(); window.maximize();
        await until(`${current}?.session?.getState().loaded`);
        window.show();window.maximize();window.focus();
        await hold(500);
        await unchanged();
        report.placementCount=expected.placements.length;
        report.maximized=window.isMaximized();
        await js(`${current}.session.selectMany([]);${current}.workspace._setViewMode('plan');
            if(document.getElementById('structureTreeHost').offsetParent)window._toggleLeftPanel();`);
        await js(`(()=>{const w=${current}.workspace;w.layerVisibility.zones=false;
            w.layerVisibility.cells=false;w._applyLayerVisibility();w._setPlanPreference('showGrid',false);})()`);
        await hold(1800);
        await js(`${current}.workspace.controller.fit()`);
        await hold(500);await capture('01-plan');
        await js(`${current}.workspace._setViewMode('3d')`);
        await until(`!!${adapter}&&${current}.workspace.lastThreeFitFingerprint===${current}.workspace.lastLayoutFingerprint`);
        report.stage='warming-detailed-models';await persist();
        // Exercise the normal selection-priority loader, then clear the visual
        // selection. No placement, material, or application loading policy changes.
        await js(`${adapter}.setSelection(${JSON.stringify(expected.placements.map(p=>p.placementId))});
            ${adapter}.setSelection([])`);
        await until(`(()=>{const d=${adapter}.getDiagnostics();return d.pendingLoads===0&&
            d.representationGroups.every(g=>['overview','detail'].includes(g.representation));})()`,240000);
        report.allModelsReady=true;await persist();
        await js(`${adapter}.setGridVisible(false);${adapter}.topView()`);
        await hold(options.fast?1000:4000);await capture('02-top');
        for (const [name,position,target] of shots) {
            const overview=['03-complete-gym','04-campus-reveal','32-closing-campus'].includes(name);
            if(options.overviewsOnly&&!overview)continue;
            const fov=name==='04-campus-reveal'?40:65;
            report.stage=name;await persist();await gate();
            await camera(position,target,fov);
            // A static frame first lets proximity-based mesh promotion catch up.
            await hold(1600);
            await until(`${adapter}.getDiagnostics().pendingLoads===0`,90000);
            await hold(options.fast?500:2600);
            await capture(name);
            if(!options.fast && !['03-complete-gym','32-closing-campus'].includes(name)) {
                // Small, local dolly rather than crossing walls between rooms.
                const end=position.map((v,i)=>v+(target[i]-v)*.04);
                for(let step=1;step<=60;step++) {
                    await gate();const t=step/60,u=t*t*(3-2*t);
                    await camera(position.map((v,i)=>v+(end[i]-v)*u),target,fov);
                    await sleep(40);
                }
                await hold(900);
            }
        }
        await unchanged();
        const d=await js(`${adapter}.getDiagnostics()`);
        assert.equal(d.degraded,false);
        report.audit=d.placementTransformAudit;
        report.status='passed'; report.savedStateUnchanged=true;
    } catch(error) {
        report.status=stopped?'stopped':'failed';report.error=error.stack;
        await capture('failure').catch(()=>{});
    } finally {
        window.webContents.removeListener('before-input-event',key);
        await unchanged().then(()=>report.savedStateUnchanged=true).catch(e=>{
            report.status='failed';report.savedStateUnchanged=false;report.errors.push(e.message);
        });
        report.finished=new Date().toISOString();await persist();
        await sleep(3000);app.quit();
    }
}

app.once('browser-window-created',(_event,window)=>{
    window.maximize();
    window.webContents.once('dom-ready',()=>void rehearse(window).catch(async error=>{
        await fs.writeFile(path.join(out,'driver-error.txt'),error.stack);app.quit();
    }));
});
require('../../desktop/src/entry.cjs');
