'use strict';
const {app,dialog} = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const {createHash} = require('node:crypto');
const {TourControl,verifyArrival,withTimeout} = require('../factory02_tour/control.cjs');
const itinerary = require('./route.cjs');
const {assertArtworkReady} = require('./artwork.cjs');
const profileFile = process.argv[process.argv.indexOf('--profile-file')+1];
const out = path.dirname(profileFile),root = path.resolve(__dirname,'../..');
const current = 'window._trainFacilityLayoutAuthoringApp',adapter = current+'.workspace.threeAdapter';
const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));
const hash = value => createHash('sha256').update(value).digest('hex');
const xyz = a => ({x:a[0],y:a[1],z:a[2]});
const vector = v => {const q=v.quaternion;return {x:-2*(q.x*q.z+q.w*q.y),y:-2*(q.y*q.z-q.w*q.x),z:2*(q.x*q.x+q.y*q.y)-1};};
const targetFromView = v => {const d=vector(v);return {x:v.position.x+d.x*10,y:v.position.y+d.y*10,z:v.position.z+d.z*10};};
const distance = (a,b) => Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z);

const originalDialog=dialog.showMessageBox.bind(dialog);
dialog.showMessageBox=async(...args)=>{
    if(args.at(-1).title!=='InspectorPro startup')return originalDialog(...args);
    await fs.writeFile(path.join(out,'startup-error.json'),JSON.stringify(args.at(-1)));
    app.quit();return {response:0,checkboxChecked:false};
};

async function rehearse(window) {
    const profile=JSON.parse(await fs.readFile(profileFile,'utf8'));
    const options=JSON.parse(await fs.readFile(path.join(out,'tour.json'),'utf8'));
    const relative='layouts/local/site-local/layouts/fl-private-gym-20261007.json';
    const saved=path.join(profile.facilityRoot,relative),live=path.join(root,'.runtime/facility-layout',relative);
    const expected=JSON.parse(await fs.readFile(saved,'utf8'));
    const catalog=JSON.parse(await fs.readFile(path.join(out,'catalog.json'),'utf8'));
    const report={status:'running',stage:'preflight',captures:[],walks:[],flights:[],handoffs:[],errors:[],blockedWrites:[],resourceFailures:[]};
    window.webContents.session.webRequest.onCompleted({urls:[profile.origin+'/generated/*']},details=>{
        if(details.statusCode>=400)report.resourceFailures.push({url:details.url,statusCode:details.statusCode});
    });
    window.webContents.session.webRequest.onErrorOccurred({urls:[profile.origin+'/generated/*']},details=>{
        report.resourceFailures.push({url:details.url,error:details.error});
    });
    const persist=()=>fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));
    const js=code=>withTimeout(window.webContents.executeJavaScript(code,true),'Renderer command');
    const control=new TourControl(false);
    let pausedForFocus=false,focusLossTime=null,sequence=0,checked,walkMode=false;
    async function command(stop=false) {
        if(stop)control.stop();else control.toggle();
        await js(`${adapter}?.cancelWalkthroughNavigation('tour_paused')`);
    }
    const key=(e,input)=>{
        if(input.type!=='keyDown'||input.isAutoRepeat||!['F8','F9'].includes(input.key))return;
        e.preventDefault();pausedForFocus=false;
        void command(input.key==='F9').catch(e=>report.errors.push(e.message));
    };
    const blur=()=>{
        focusLossTime=Date.now();
        if(!control.paused&&!control.stopped){pausedForFocus=true;void command().catch(e=>report.errors.push(e.message));}
    };
    const focus=()=>{
        if(pausedForFocus&&control.paused&&!control.stopped){pausedForFocus=false;void command().catch(e=>report.errors.push(e.message));}
    };
    window.webContents.on('before-input-event',key);
    window.webContents.session.webRequest.onBeforeRequest({urls:[profile.origin+'/api/*']},(details,callback)=>{
        const blocked=!['GET','HEAD','OPTIONS'].includes(details.method);
        if(blocked)report.blockedWrites.push({url:details.url,method:details.method});
        callback({cancel:blocked});
    });
    async function until(code,timeout=120000) {
        const end=Date.now()+timeout;
        while(Date.now()<end){control.check();if(await js(code))return;await sleep(200);}
        throw Error('Timed out: '+code);
    }
    async function gate() {
        control.check();
        while(control.paused){await sleep(100);control.check();if(control.pauseTimedOut())throw Error('Pause timeout');}
        if(focusLossTime!==null){
            const lostAt=focusLossTime;focusLossTime=null;
            const s=await js('window.__gymTourWalkSnapshot||null');
            if(walkMode&&s&&s.time>=lostAt-1000){
                const target=targetFromView(s.camera);
                const restored=await js(`(()=>{const a=${adapter};
                    if(!a.getWalkthroughState().active){a.applyCameraView(${JSON.stringify(s.camera)});
                        a.enterWalkthrough({worldPoint:${JSON.stringify(s.state.position)},ignoreSelection:true});}
                    else a.enterWalkthrough({ignoreSelection:true});
                    a.lookWalkthroughAt(${JSON.stringify(target)});return a.getWalkthroughState();})()`);
                assert.ok(restored.active&&distance(restored.position,s.state.position)<.001,'Resume changed walking position');
                await until(`${adapter}.getWalkthroughState().locked`,5000);
                report.focusRestores=(report.focusRestores||0)+1;
            }
        }
    }
    async function hold(ms) {
        const end=control.now()+ms;
        while(control.now()<end){await gate();await sleep(Math.max(1,Math.min(60,end-control.now())));}
    }
    async function unchanged() {
        const s=await js(`${current}.session.getState()`);
        assert.deepEqual(s.layout,expected);assert.equal(s.dirty,false);
        assert.equal(hash(await fs.readFile(saved)),options.originalHash);
        assert.equal(hash(await fs.readFile(live)),options.originalHash);
    }
    async function capture(name) {
        await unchanged();
        if(report.allArtworkReady&&report.status==='running')assertArtworkReady(expected,await js(`${adapter}.getDiagnostics()`));
        const shot=await withTimeout(window.webContents.capturePage(),'Screenshot',15000);
        assert.ok(!shot.isEmpty());const bitmap=shot.toBitmap(),colors=new Set();
        for(let i=0;i+4<=bitmap.length;i+=116)colors.add(bitmap.readUInt32LE(i));
        assert.ok(colors.size>100,'Blank screenshot');
        const filename=String(++sequence).padStart(3,'0')+'-'+name+'.png';
        await fs.writeFile(path.join(out,filename),shot.toPNG());
        report.captures.push({name,file:filename,colors:colors.size,camera:await js(`${adapter}?.getCameraView()`)});
        await persist();
    }
    async function apply(view) {
        const actual=await js(`(()=>{const a=${adapter};a.applyCameraView(${JSON.stringify(view)});return a.getCameraView();})()`);
        assert.ok(distance(actual.position,view.position)<.002,'Orbit controls moved the requested camera');
        return actual;
    }
    async function look(target,duration=1800) {
        const start=await js(`${adapter}.getCameraView()`),direction=vector(start);
        const delta={x:target.x-start.position.x,y:target.y-start.position.y,z:target.z-start.position.z};
        const yaw=Math.atan2(direction.x,direction.z),pitch=Math.atan2(direction.y,Math.hypot(direction.x,direction.z));
        const endYaw=Math.atan2(delta.x,delta.z),endPitch=Math.atan2(delta.y,Math.hypot(delta.x,delta.z));
        const yawDelta=Math.atan2(Math.sin(endYaw-yaw),Math.cos(endYaw-yaw)),started=control.now();
        do{
            await gate();const t=Math.min(1,(control.now()-started)/duration),u=t*t*(3-2*t);
            const y=yaw+yawDelta*u,p=pitch+(endPitch-pitch)*u;
            const target={x:start.position.x+10*Math.sin(y)*Math.cos(p),y:start.position.y+10*Math.sin(p),z:start.position.z+10*Math.cos(y)*Math.cos(p)};
            await js(`${adapter}.lookWalkthroughAt(${JSON.stringify(target)})`);
            if(t===1)break;await hold(40);
        }while(true);
    }
    async function flight(step) {
        const wasWalking=await js(`${adapter}.getWalkthroughState().active`);
        if(wasWalking){
            const before=await js(`${adapter}.getCameraView()`),d=vector(before);
            const horizontal=Math.hypot(d.x,d.z);
            // The existing orbit camera stops slightly short of the horizon.
            // Settle the gaze first, while still on foot, to avoid its clamp
            // moving the camera during the handoff.
            if(Math.atan2(d.y,horizontal)>-.06){
                await look({x:before.position.x+d.x/horizontal*10,
                    y:before.position.y-Math.tan(.06)*10,z:before.position.z+d.z/horizontal*10},1200);
            }
        }
        const start=await js(`${adapter}.getCameraView()`);
        start.target=targetFromView(start);
        itinerary.checkFlight([start.position.x,start.position.y,start.position.z],step.position,checked.scene.volumes);
        walkMode=false;
        if(wasWalking){
            await js(`${adapter}.exitWalkthrough('guided_aerial');${adapter}.exitDrone('guided_aerial');
                ${adapter}.applyCameraView(${JSON.stringify(start)})`);
            const actual=await js(`${adapter}.getCameraView()`);
            assert.ok(distance(actual.position,start.position)<.001,'Walking-to-flight camera jump');
            report.handoffs.push({name:step.name,kind:'takeoff',positionDelta:distance(actual.position,start.position)});
        }
        const began=control.now(),duration=options.fast?Math.max(3000,step.duration*.6):step.duration;
        const travel={name:step.name,from:start.position,to:xyz(step.position),samples:[]};
        let midpoint=false;
        do{
            await gate();const t=Math.min(1,(control.now()-began)/duration),u=t*t*(3-2*t);
            const view=itinerary.flightView(start,xyz(step.position),xyz(step.target),u);
            await apply(view);travel.samples.push({t,position:view.position});
            if(!midpoint&&t>=.5){midpoint=true;await capture(step.name+'-midflight');}
            if(t===1)break;await hold(40);
        }while(true);
        travel.elapsedMs=control.now()-began;report.flights.push(travel);
        await hold(options.fast?300:1500);await capture(step.name);
    }
    async function land(step) {
        const before=await js(`${adapter}.getCameraView()`),target=targetFromView(before);
        window.focus();window.webContents.focus();
        await gate();
        walkMode=true;
        await js(`${adapter}.setWalkthroughCameraMode('first-person');
            ${adapter}.enterWalkthrough({worldPoint:${JSON.stringify(before.position)},ignoreSelection:true});
            ${adapter}.lookWalkthroughAt(${JSON.stringify(target)})`);
        for(let attempt=0;attempt<5;attempt++){
            await hold(500);
            if(await js(`${adapter}.getWalkthroughState().locked`))break;
            window.focus();window.webContents.focus();
            await js(`${adapter}.enterWalkthrough({ignoreSelection:true})`);
        }
        await until(`${adapter}.getWalkthroughState().locked`,5000);
        const after=await js(`${adapter}.getCameraView()`);
        assert.ok(distance(before.position,after.position)<.01,'Landing moved the camera');
        report.handoffs.push({name:step.name,kind:'landing',positionDelta:distance(before.position,after.position)});
        await hold(options.fast?500:2500);await capture(step.name);
    }
    async function walk(step) {
        const start=await js(`${adapter}.getWalkthroughState()`);
        const planned=checked.results.find(r=>r.name===step.name).plan;
        const next=planned.points[1];
        if(next)await look({x:next.x,y:start.position.y+start.eyeHeight,z:next.z},1200);
        const began=control.now(),trace=[];
        let epoch=-1,plan,lookingAt=-1,midpoint=false;
        while(true){
            await gate();
            if(epoch!==control.epoch){
                assert.ok(await js(`${adapter}.getWalkthroughState().active`),'Walkthrough exited');
                await js(`${adapter}.enterWalkthrough({ignoreSelection:true})`);
                await until(`${adapter}.getWalkthroughState().locked`,5000);
                plan=await js(`${adapter}.navigateWalkthroughToPoint(${JSON.stringify(step.point)})`);
                assert.ok(plan.ok,step.name+': '+JSON.stringify(plan));epoch=control.epoch;lookingAt=-1;
                report.activeWalk={name:step.name,plan,trace};await persist();
                if(options.pauseCheck&&!report.pauseVerified){
                    await sleep(800);await command();const stopped=await js(`${adapter}.getWalkthroughState()`);
                    await sleep(700);const held=await js(`${adapter}.getWalkthroughState()`);
                    assert.deepEqual(held.position,stopped.position);assert.equal(held.route.active,false);
                    report.pauseVerified=true;await command();continue;
                }
            }
            const state=await js(`${adapter}.getWalkthroughState()`);
            if(control.paused||epoch!==control.epoch)continue;
            if(state.route.reason==='window_blurred'&&!window.isFocused()){blur();continue;}
            assert.ok(state.active&&state.locked,'Lost walkthrough control');
            trace.push({t:control.now()-began,position:state.position});
            if(!state.route.active){verifyArrival(state,step.point);break;}
            if(state.route.pointIndex!==lookingAt){
                const p=plan.points[state.route.pointIndex];
                if(p)await js(`${adapter}.lookWalkthroughAt({x:${p.x},y:${state.position.y+state.eyeHeight},z:${p.z}})`);
                lookingAt=state.route.pointIndex;
            }
            if(!midpoint&&control.now()-began>2000){midpoint=true;await capture(step.name+'-walking');}
            await hold(150);assert.ok(control.now()-began<180000,'Walking timed out');
        }
        const end=await js(`${adapter}.getWalkthroughState()`);
        report.walks.push({name:step.name,from:start.position,to:end.position,elapsedMs:control.now()-began,
            collisions:end.collisionCount-start.collisionCount,trace,plan});
        report.activeWalk=null;
        if(step.target)await look(xyz(step.target));
        await hold(options.fast?400:3000);await capture(step.name);
    }
    try{
        await persist();checked=itinerary.preflight(expected,catalog);
        report.preflight=checked.results;await persist();
        await until(`${current}?.session?.getState().loaded`);
        window.show();window.maximize();window.focus();window.webContents.focus();await hold(500);await unchanged();
        report.maximized=window.isMaximized();report.placementCount=expected.placements.length;
        if(!options.preflightOnly){
            await js(`${current}.session.selectMany([]);${current}.workspace._setViewMode('plan');
                if(getComputedStyle(document.querySelector('.left-panel')).display!=='none')window._toggleLeftPanel();
                ${current}.workspace._setPlanPreference('showGrid',false)`);
            await js(`(()=>{const w=${current}.workspace;w.layerVisibility.zones=false;
                w.layerVisibility.cells=false;w._applyLayerVisibility();})()`);
            await hold(1000);
            report.planFraming=await js(`(()=>{const a=${current}.workspace.topAdapter;a.fitFacility();
                const r=a.svg.getBoundingClientRect(),v=a.getViewportState(),b=v.worldBounds;
                const center={x:(b.minX+b.maxX)/2,z:(b.minZ+b.maxZ)/2};
                const scale=Math.min(v.projection.width/(b.maxX-b.minX+12),v.projection.height/(b.maxZ-b.minZ+12));
                a.setScaleAt({clientX:r.left+r.width/2,clientY:r.top+r.height/2},scale);
                const p=a.worldToClient(center);
                a.panByPixels((r.left+r.width/2-p.x)*v.projection.width/r.width,
                    (r.top+r.height/2-p.y)*v.projection.height/r.height);
                const lo=a.worldToClient({x:b.minX,z:b.minZ}),hi=a.worldToClient({x:b.maxX,z:b.maxZ});
                return {inside:lo.x>r.left&&hi.x<r.right&&hi.y>r.top&&lo.y<r.bottom,
                    worldBounds:b,projection:a.getViewportState().projection};})()`);
            assert.equal(report.planFraming.inside,true,'Plan extends outside viewport');
            await hold(800);await capture('plan');
            await js(`${current}.workspace._setViewMode('3d')`);
            await until(`!!${adapter}&&${current}.workspace.lastThreeFitFingerprint===${current}.workspace.lastLayoutFingerprint`);
            report.stage='warming-models';await persist();
            await js(`${adapter}.setSelection(${JSON.stringify(expected.placements.map(p=>p.placementId))});${adapter}.setSelection([])`);
            await until(`(()=>{const d=${adapter}.getDiagnostics();return d.pendingLoads===0&&d.representationGroups.every(g=>['overview','detail'].includes(g.representation));})()`,240000);
            report.allModelsReady=true;
            report.artworkBefore=await js(`${adapter}.getDiagnostics().exteriorArtwork`);
            report.artwork=assertArtworkReady(expected,await js(`${adapter}.getDiagnostics()`));
            report.allArtworkReady=true;
            await persist();
            if(options.artworkCheck){
                await js(`${adapter}.setGridVisible(false)`);
                const views=[
                    ['hall-viking',[31.2,2,-.4],[31.2,1.5,-3]],
                    ['hall-zulu',[23,2,-.4],[23,1.5,-3]],
                    ['hall-gallery',[12,2,-.4],[12,1.5,-3]],
                    ['kitchen-art',[27.5,2,-14],[27.5,1.8,-11]],
                    ['soccer-mural',[15,3.8,47],[15,2,34]],
                    ['soccer-west',[12,3.2,48],[0,2,48]],
                    ['soccer-east',[31,3.2,48],[42,2,48]],
                ];
                for(const [name,position,target] of views){
                    report.stage='artwork-check-'+name;await persist();
                    await apply({...(await js(`${adapter}.getCameraView()`)),position:xyz(position),target:xyz(target),up:{x:0,y:1,z:0},fov:65,near:.05,far:600});
                    await hold(1200);await capture(name);
                }
                report.artworkAfter=await js(`${adapter}.getDiagnostics().exteriorArtwork`);
                await js(`${adapter}.setLayerVisibility({walls:false});${adapter}.setLayerVisibility({walls:true})`);
                assertArtworkReady(expected,await js(`${adapter}.getDiagnostics()`));
                report.artworkToggleVerified=true;
                report.status='passed';return;
            }
            await js(`${adapter}.setGridVisible(false);${adapter}.topView()`);
            await hold(options.fast?600:4000);await capture('top');
            await apply({...(await js(`${adapter}.getCameraView()`)),position:xyz([106,84,111]),target:xyz([40,0,27]),up:{x:0,y:1,z:0},fov:60,near:.05,far:600});
            await hold(1500);await capture('overview');
            await js(`(()=>{const remember=()=>{const a=${adapter},state=a.getWalkthroughState();
                if(state.active)window.__gymTourWalkSnapshot={time:Date.now(),state,camera:a.getCameraView()};};
                window.addEventListener('blur',remember,true);
                document.addEventListener('pointerlockchange',()=>{if(!document.pointerLockElement)remember();},true);})()`);
            window.on('blur',blur);window.on('focus',focus);
            for(const step of options.introOnly?itinerary.route.slice(0,5):itinerary.route){
                report.stage=step.name;await persist();await gate();
                if(step.kind==='fly')await flight(step);
                else if(step.kind==='land')await land(step);
                else await walk(step);
            }
            const d=await js(`${adapter}.getDiagnostics()`);assert.equal(d.degraded,false);report.audit=d.placementTransformAudit;
        }
        await unchanged();report.savedStateUnchanged=true;report.status='passed';
    }catch(error){
        report.status=control.stopped?'stopped':'failed';report.error=error.stack;
        report.failureState=await js(`({walk:${adapter}?.getWalkthroughState(),diagnostics:${adapter}?.getDiagnostics(),
            focused:document.hasFocus(),pointerLocked:!!document.pointerLockElement})`).catch(()=>null);
        report.windowFocused=window.isFocused();
        await js(`${adapter}?.cancelWalkthroughNavigation('tour_failed')`).catch(()=>{});
        await capture('failure').catch(()=>{});
    }finally{
        window.removeListener('blur',blur);window.removeListener('focus',focus);
        window.webContents.removeListener('before-input-event',key);
        await unchanged().then(()=>report.savedStateUnchanged=true).catch(e=>{report.status='failed';report.errors.push(e.message);});
        report.finished=new Date().toISOString();await persist();await sleep(2500);app.quit();
    }
}
app.once('browser-window-created',(_event,window)=>{
    window.maximize();window.webContents.once('dom-ready',()=>void rehearse(window).catch(async error=>{
        await fs.writeFile(path.join(out,'driver-error.txt'),error.stack);app.quit();
    }));
});
require('../../desktop/src/entry.cjs');
