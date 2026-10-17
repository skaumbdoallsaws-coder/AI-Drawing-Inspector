'use strict';
// Read-only normal desktop reproduction, including sheet parking and immersive modes.
const { app } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const profileFile = process.argv[process.argv.indexOf('--profile-file') + 1];
const output = path.dirname(profileFile);
const current = 'window._trainFacilityLayoutAuthoringApp';
const adapter = current + '.workspace.threeAdapter';
const target = 'fl-independent-factory-20260928';
const manual = 'fl-reference-manual-20260812';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function check(window) {
    const profile = JSON.parse(await fs.readFile(profileFile, 'utf8'));
    const report = {status:'running', stages:[]};
    const persist = () => fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report,null,2));
    const js = code => window.webContents.executeJavaScript(code, true);
    const until = async code => {
        const end=Date.now()+180000;
        while(Date.now()<end) { if(await js(code))return;await pause(200); }
        throw Error('Timeout: '+code);
    };
    const hashes = async () => Object.fromEntries(await Promise.all([target,manual].map(async id => [id,
        createHash('sha256').update(await fs.readFile(path.join(profile.facilityRoot,'layouts/local/site-local/layouts',id+'.json'))).digest('hex')])));
    const loaded = () => until(`${adapter}?.getDiagnostics().pendingLoads===0 && ${adapter}?.getDiagnostics().assetGroupCount>0`);
    const capture = async name => {
        await js(`${adapter}.renderRecordingFrame()`);
        const data=await js(`(()=>{const a=${adapter},d=a.getDiagnostics(),live={};
            window.__visibilityScene.traverse(o=>{if(!o.isMesh)return;let p=o,assetId=null,visible=true;
                while(p){if(p.visible===false)visible=false;if(p.userData?.assetId)assetId=p.userData.assetId;p=p.parent;}
                if(!assetId)return;if(!live[assetId])live[assetId]={visibleIds:[],counts:[]};
                if(o.isInstancedMesh){live[assetId].counts.push(o.count);if(visible){const matrix=new (${current}.workspace.options.threeOptions.THREE.Matrix4)();
                    for(let i=0;i<o.count;i++){o.getMatrixAt(i,matrix);if(matrix.determinant()!==0)live[assetId].visibleIds.push(o.userData.facilityInstancePlacementIds[i]);}}}
                else if(visible){let q=o;while(q&&!q.userData?.placementId)q=q.parent;if(q)live[assetId].visibleIds.push(q.userData.placementId);}
            });
            for(const v of Object.values(live))v.visibleIds=[...new Set(v.visibleIds)].sort();
            return {layoutId:${current}.session.getState().layout.layoutId,dirty:${current}.session.getState().dirty,
                groups:d.representationGroups.filter(g=>/operator|perimeter/.test(g.assetId)).map(g=>({assetId:g.assetId,representation:g.representation,ids:g.placementIds,live:live[g.assetId]})),
                navigation:d.navigation,audit:d.placementTransformAudit,warnings:d.warnings,rendering:d.rendering};})()`);
        report.stages.push({name,...data});await persist();
        await fs.writeFile(path.join(output,name+'.png'),(await window.webContents.capturePage()).toPNG());
        assert.equal(data.dirty,false);assert.equal(data.audit.transformMismatchCount,0);
        for(const group of data.groups) {
            assert.deepEqual(group.live.visibleIds,group.ids.slice().sort(),name+': missing '+group.assetId);
        }
        if (data.navigation.drone.active) {
            assert.equal(data.navigation.drone.distanceCulling,false);
            assert.equal(data.navigation.drone.visiblePlacementCount,data.audit.expectedPlacementCount);
        }
        return data;
    };
    const hook = async () => {
        await js(`(()=>{const w=${current}.workspace;w.options.threeOptions.onRendererReady=r=>{
            if(r.__visibilityHook)return;r.__visibilityHook=true;const render=r.render.bind(r);
            r.render=(s,c)=>{window.__visibilityScene=s;return render(s,c);};};
            w.threeAdapter.park();w.threeAdapter.resume();})()`);
        await loaded();
    };
    try {
        report.before=await hashes();await persist();window.setSize(1440,900);window.show();window.focus();
        await until(`!!${current}?.session?.getState().loaded`);
        assert.equal(await js(`${current}.session.getState().dirty`),false);
        await js(`_trainFacilitySheets.activate('${target}')`);
        await until(`${current}.session.getState().layout.layoutId==='${target}'`);
        await js(`${current}.workspace._setViewMode('3d')`);await loaded();await hook();
        await js(`${adapter}.isometricView();${adapter}.fitFacility()`);
        await capture('01-factory-orbit');
        await js(`(()=>{const a=${adapter},v=a.getCameraView();v.position={x:150,y:8,z:98};v.target={x:280,y:2,z:98};a.applyCameraView(v);a.enterDrone({ignoreSelection:true});})()`);
        await until(`${adapter}.getDroneState().locked`);await capture('02-factory-drone');
        await js(`${adapter}.switchImmersiveMode('walkthrough')`);
        await until(`${adapter}.getWalkthroughState().locked`);await capture('03-factory-walk');
        await js(`${adapter}.exitWalkthrough();${adapter}.fitFacility()`);
        await capture('04-after-immersive');
        for(let i=0;i<2;i++) {
            await js(`_trainFacilitySheets.activate('${manual}')`);await until(`${current}.session.getState().layout.layoutId==='${manual}'`);
            await js(`${current}.workspace._setViewMode('3d')`);await loaded();await hook();await capture('05-manual-'+i);
            await js(`_trainFacilitySheets.activate('${target}')`);await until(`${current}.session.getState().layout.layoutId==='${target}'`);
            await js(`${current}.workspace._setViewMode('3d')`);await loaded();await hook();await capture('06-restored-factory-'+i);
        }
        report.after=await hashes();assert.deepEqual(report.before,report.after);report.status='passed';
    } catch(error) {report.status='failed';report.error=error.stack;}
    finally {await persist();app.quit();}
}
app.once('browser-window-created',(_event,window)=>window.webContents.once('did-finish-load',()=>void check(window).catch(async error=>{
    await fs.writeFile(path.join(output,'driver-error.txt'),error.stack);app.quit();
})));
require('../src/entry.cjs');
