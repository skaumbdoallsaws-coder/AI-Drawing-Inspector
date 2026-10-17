'use strict';
// Exercise the normal ribbon/transport/playback against an isolated saved copy.
const {app} = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile);
const target = 'fl-independent-factory-20260928';
const current = 'window._trainFacilityLayoutAuthoringApp';
const workspace = current + '.workspace';
const adapter = workspace + '.threeAdapter';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function check(window) {
    const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
    const report = {status:'running', stages:[], saveCalls:0};
    const persist = () => fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
    const js = code => window.webContents.executeJavaScript(code,true);
    const until = async (code, timeout=180000) => {
        const end=Date.now()+timeout;
        while(Date.now()<end) { if(await js(code))return; await pause(250); }
        throw Error('Timeout: '+code);
    };
    const hashes = async () => Object.fromEntries(await Promise.all([target,'fl-reference-manual-20260812'].map(async id => [id,
        createHash('sha256').update(await fs.readFile(path.join(profile.facilityRoot,'layouts/local/site-local/layouts',id+'.json'))).digest('hex')])));
    const capture = async name => {
        await js(`${adapter}.renderRecordingFrame()`);
        await pause(600);
        const pic=await window.webContents.capturePage();
        await fs.writeFile(path.join(output,name+'.png'),pic.toPNG());
        const rect=await js(`(()=>{const r=${workspace}.root.querySelector('canvas').getBoundingClientRect();return {x:Math.ceil(r.x),y:Math.ceil(r.y),width:Math.floor(r.width),height:Math.floor(r.height)};})()`);
        const bitmap=(await window.webContents.capturePage(rect)).toBitmap();
        const colors=new Set();for(let i=0;i<bitmap.length;i+=64)colors.add(bitmap.subarray(i,i+3).toString('hex'));
        assert.ok(colors.size>30, 'blank viewport');
        const framing=await js(`(()=>{const THREE=${workspace}.options.threeOptions.THREE,a=${adapter}.activity.getState().actors[0],
            root=window.__layer3Scene?.getObjectByName('FacilityActivityActor:'+a.actorId),camera=window.__layer3Camera;
            if(!root||!camera)return null;root.updateWorldMatrix(true,true);const b=new THREE.Box3().setFromObject(root),c=b.getCenter(new THREE.Vector3());
            return {bounds:{min:b.min.toArray(),max:b.max.toArray()},projected:c.clone().project(camera).toArray(),camera:${adapter}.getCameraView(),fit:${adapter}.getDiagnostics().lastFit};})()`);
        report.stages.push({name,canvasColors:colors.size,framing,activity:await js(`${adapter}.activity.getState()`)});
        await persist();
        assert.ok(framing && Math.abs(framing.projected[0])<.95 && Math.abs(framing.projected[1])<.95, 'selected actor outside viewport');
        await js(`(()=>{const a=${adapter}.activity.getState().actors[0];window.__layer3Scene.getObjectByName('FacilityActivityActor:'+a.actorId).visible=false;${adapter}.renderRecordingFrame();})()`);
        await pause(250);
        const hidden=(await window.webContents.capturePage(rect)).toBitmap();
        await js(`(()=>{const a=${adapter}.activity.getState().actors[0];window.__layer3Scene.getObjectByName('FacilityActivityActor:'+a.actorId).visible=true;${adapter}.renderRecordingFrame();})()`);
        let changed=0;for(let i=0;i<Math.min(bitmap.length,hidden.length);i+=4)if(bitmap[i]!==hidden[i]||bitmap[i+1]!==hidden[i+1]||bitmap[i+2]!==hidden[i+2])changed++;
        report.stages.at(-1).visibleActorPixels=changed;await persist();assert.ok(changed>100,'selected actor contributes no visible pixels');
        assert.ok(changed<bitmap.length/40,'camera or scene changed during the isolated avatar pixel check');
    };
    const click = async selector => {
        assert.equal(await js(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e||e.disabled)return false;e.click();return true;})()`),true,selector);
    };
    const prepare = async label => {
        await click('#facilityLayoutOverflowMenuRibbon');
        await click('[data-facility-ribbon-command="saved-movement"]');
        await until('!!document.querySelector("[data-saved-movement-group]")');
        const options=await js(`Array.from(document.querySelector('[data-saved-movement-group]').options).map(o=>({value:o.value,label:o.textContent}))`);
        const option=label ? options.find(o=>o.label===label) : options[0];assert.ok(option,label);
        if(!label) assert.equal(option.label,'All saved movement (40 actors)');
        await js(`document.querySelector('[data-saved-movement-group]').value=${JSON.stringify(option.value)}`);
        const start=Date.now();await click('[data-saved-movement-prepare]');
        await until(`!${workspace}.activityRequestPending`,900000);
        assert.equal(await js(`${adapter}.activity.getState().loaded`),true,await js(`${workspace}.savedMovementDialog?.textContent||''`));
        assert.equal(await js(`${adapter}.activity.getState().playing`),true,'Play movement must start the loaded actors');
        await click('[data-motion-action="toggle-play"]');
        report.stages.push({name:'prepared '+option.label,seconds:(Date.now()-start)/1000,options:options.length,autoplay:true});await persist();
    };
    const frameActor = async id => {
        await until(`${adapter}.activity.focusActor(${JSON.stringify(id)})===true`,30000);
        await js(`(()=>{const a=${adapter};const v=a.getCameraView();
            for(const k of ['x','y','z'])v.position[k]=v.target[k]+(v.position[k]-v.target[k])*3;a.applyCameraView(v);})()`);
        await pause(600);
    };
    try {
        // This isolated check must animate even while the user works in another window.
        window.webContents.setBackgroundThrottling(false);
        report.before=await hashes();await persist();window.setSize(1440,900);window.show();
        await until(`!!${current}?.session?.getState().loaded`);
        if(await js(`${current}.session.getState().layout.layoutId`) !== target) await js(`_trainFacilitySheets.activate('${target}')`);
        await until(`${current}.session.getState().layout.layoutId==='${target}'`);
        await js(`(()=>{const w=${workspace};window.__layer3Before=JSON.stringify(w.session.getState().layout);window.__layer3SaveCalls=0;
            const save=w.session.save;w.session.save=function(...a){window.__layer3SaveCalls++;return save.apply(this,a);};w._setViewMode('3d');})()`);
        await until(`${adapter}.getDiagnostics().pendingLoads===0 && ${adapter}.getDiagnostics().assetGroupCount>0`);
        await js(`(()=>{const w=${workspace};w.options.threeOptions.onRendererReady=r=>{const render=r.render.bind(r);r.render=(s,c)=>{window.__layer3Scene=s;window.__layer3Camera=c;return render(s,c);};};w.threeAdapter.park();w.threeAdapter.resume();})()`);
        await until(`${adapter}.getDiagnostics().pendingLoads===0 && ${adapter}.getDiagnostics().assetGroupCount>0`);
        const focusOnly=profile.profileId.includes('focus');
        const allActors=profile.profileId.includes('all');
        const replayOnly=profile.profileId.includes('replay');
        await prepare(allActors?null:replayOnly?'R01 attendant':focusOnly?'Q1 inspector':'Machining - 12 operators');
        let state=await js(`${adapter}.activity.getState()`);
        assert.equal(state.actors.length,allActors?40:(focusOnly||replayOnly)?1:12);assert.equal(state.duplicateVisiblePlacementIds.length,0);
        assert.equal(state.suppressedStationaryOperatorCount,0);
        assert.ok(state.actors.every(a=>a.cycleClosed&&a.sourcePlacementSuppressed));
        await frameActor(state.actors[0].actorId);
        await capture('01-machining-ready');
        await click('[data-motion-action="toggle-play"]');
        await until(`Math.abs(${adapter}.activity.getState().elapsedSeconds-${state.elapsedSeconds})>.75`,30000);
        await click('[data-motion-action="toggle-play"]');
        const moving=await js(`${adapter}.activity.getState()`);
        assert.ok(moving.elapsedSeconds>0);
        const distances=moving.actors.map((a,i)=>Math.hypot(a.pose.x-state.actors[i].pose.x,a.pose.z-state.actors[i].pose.z));
        report.motionVerification={startSeconds:state.elapsedSeconds,endSeconds:moving.elapsedSeconds,
            actorCount:distances.length,movedActorCount:distances.filter(d=>d>.1).length,minimumDisplacementMeters:Math.min(...distances)};
        await persist();assert.ok(distances.every(d=>d>.1));
        await frameActor(state.actors[0].actorId);
        await capture('02-machining-moving');
        await js(`${workspace}._setViewMode('plan')`);await pause(400);
        await fs.writeFile(path.join(output,'03-plan-paths.png'),(await window.webContents.capturePage()).toPNG());
        await js(`${workspace}._setViewMode('3d')`);await pause(500);
        await click('[data-motion-action="close"]');
        assert.equal(await js(`${adapter}.activity.getState().loaded`),false);
        await prepare(focusOnly?'R01 attendant':'A01 operator');
        state=await js(`${adapter}.activity.getState()`);assert.equal(state.actors.length,1);
        await js(`${adapter}.activity.seek(${state.durationSeconds*.25})`);
        await until(`Math.abs(${adapter}.activity.getState().actors[0].localElapsedSeconds-${state.durationSeconds*.25})<.001`,30000);
        await frameActor(state.actors[0].actorId);
        await capture('04-assembly-cycle');
        window.setSize(900,700);await pause(500);await frameActor(state.actors[0].actorId);
        await capture('05-narrow-cycle');
        await click('[data-motion-action="close"]');
        assert.equal(await js(`JSON.stringify(${workspace}.session.getState().layout)===window.__layer3Before`),true);
        assert.equal(await js(`${workspace}.session.getState().dirty`),false);
        report.saveCalls=await js('window.__layer3SaveCalls');assert.equal(report.saveCalls,0);
        report.after=await hashes();assert.deepEqual(report.before,report.after);report.status='passed';
    } catch(error) {
        report.status='failed';report.error=error.stack;
        await fs.writeFile(path.join(output,'failure.png'),(await window.webContents.capturePage()).toPNG());
        report.ui=await js(`({commands:Array.from(document.querySelectorAll('[data-facility-ribbon-command]')).map(e=>({command:e.dataset.facilityRibbonCommand,disabled:e.disabled})),dialog:${workspace}?.savedMovementDialog?.textContent})`).catch(()=>null);
    }
    finally { await persist();app.quit(); }
}
app.once('browser-window-created',(_event,window)=>window.webContents.once('did-finish-load',()=>void check(window).catch(async error=>{
    await fs.writeFile(path.join(output,'driver-error.txt'),error.stack);app.quit();
})));
require('../src/entry.cjs');
