'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const API = require('../static/process_operator.js');
const helper = require('../static/facility_layout_three_adapter.js');
const {createAvatar} = require('../static/facility_layout_avatar.js');
async function main() {
    const fs=require('node:fs'),vm=require('node:vm');
    const html=fs.readFileSync(path.resolve(__dirname,'../static/index.html'),'utf8');
    const start=html.indexOf('function _viewerRenderGeometryOverride(');
    const end=html.indexOf('function _partsManualCreateHiddenLinesRemovedPass(',start);
    const context={};vm.runInNewContext(html.slice(start,end),context);
    const rigid={isMesh:true,material:{name:'rigid'}},skin={isMesh:true,isSkinnedMesh:true,material:[{name:'skin'}]};
    const originals=[rigid.material,skin.material],override={name:'original-override'};
    const scene={overrideMaterial:override,traverse:fn=>[rigid,skin].forEach(fn)};
    const rigidPass={},skinPass={skinning:true};
    const renderer={render(){assert.equal(scene.overrideMaterial,null);
        assert.equal(rigid.material,rigidPass);assert.equal(skin.material,skinPass);throw new Error('render fault');}};
    assert.throws(()=>context._viewerRenderGeometryOverride(renderer,scene,{},rigidPass,skinPass),/render fault/);
    assert.equal(rigid.material,originals[0]);assert.equal(skin.material,originals[1]);assert.equal(scene.overrideMaterial,override);
    const cancelContext={_trainPlantSpatialWalk:{guide:{cancel(){this.cancelled=true;}},pendingCue:{step:{}},pointing:true}};
    const guide=cancelContext._trainPlantSpatialWalk.guide;
    vm.runInNewContext(html.slice(html.indexOf('function _trainCancelPlantOperatorGuide('),
        html.indexOf('function _trainTogglePlantOperatorCamera(')),cancelContext);
    cancelContext._trainCancelPlantOperatorGuide();
    assert(guide.cancelled);assert.equal(cancelContext._trainPlantSpatialWalk.guide,null);
    assert.equal(cancelContext._trainPlantSpatialWalk.pendingCue,null);assert.equal(cancelContext._trainPlantSpatialWalk.pointing,false);
    const T = await import(pathToFileURL(path.resolve(__dirname,'../static/vendor/three/0.184.0/build/three.module.min.js')).href);
    const avatar = createAvatar(T);
    const limits = {standing:1.95,crouching:1.2,kneeling:1.5,crawling:.65};
    for (const posture of Object.keys(limits)) {
        for(let i=0;i<100;i++) {
            avatar.update({position:{x:0,y:0,z:0},posture,grounding:true,
                snapPose:i===0,distance:posture==='kneeling'?0:.005,deltaSeconds:.02});
            avatar.root.updateMatrixWorld(true);
            const b = new T.Box3().setFromObject(avatar.root,true);
            assert(b.min.y>-.03,posture+' floor penetration '+b.min.y);
            assert(b.max.y<limits[posture],posture+' height '+b.max.y);
        }
    }
    avatar.dispose();
    const legacy = require('../static/vendor/three/0.128.0/build/three.min.js');
    const old = createAvatar(legacy);
    old.update({position:{x:0,y:0,z:0},posture:'crawling',snapPose:true,grounding:true});
    old.root.updateMatrixWorld(true);
    const box = new legacy.Box3(), vector = new legacy.Vector3();
    old.root.traverse(mesh => {
        if(!mesh.isMesh)return;
        if(mesh.isSkinnedMesh)assert(mesh.material.skinning);
        const p=mesh.geometry.attributes.position;
        for(let i=0;i<p.count;i++) {
            vector.fromBufferAttribute(p,i);
            if(mesh.isSkinnedMesh)mesh.boneTransform(i,vector);
            box.expandByPoint(vector.applyMatrix4(mesh.matrixWorld));
        }
    });
    assert(box.min.y>-.03 && box.max.y<.65);
    old.dispose();old.dispose();
    const polygon = (x,z,w,d)=>[{x,z},{x:x+w,z},{x:x+w,z:z+d},{x,z:z+d}];
    const outer=polygon(-2,-2,4,4),inner=polygon(-1,-1,1,1),separate=polygon(3,-1,1,1);
    assert.deepEqual(API.groundObstacles([inner,outer,outer,separate]),[outer,separate]);
    const gap=[polygon(-2,-2,1,4),polygon(1,-2,1,4)];
    assert.deepEqual(API.groundObstacles(gap),gap,'Disconnected rectangles must not bridge an open corridor');
    const g={modelScale:1,floorY:0,radius:.3,walkSpeed:1.4,maximumStepUp:.24,maximumStepDown:.34,supportClearance:.075,
        bounds:{minimum:{x:-5,z:-5},maximum:{x:5,z:5}},obstacles:[],obstacleVolumes:[],
        walkSurfaces:[{id:'floor',kind:'ground',elevation:0,polygon:polygon(-5,-5,10,10)}],
        postureProfiles:{...helper.walkthroughPostureProfiles(1),kneeling:{radius:.3,bodyHeight:1.5,eyeHeight:1.2}}};
    assert(API.approach(helper,g,{x:-3,y:0,z:0},{min:{x:0,z:-.5},max:{x:1,z:.5}},'kneeling').ok);
    assert.equal(API.approach(helper,g,{x:-3,y:0,z:0},null).reason,'operator_target_missing');
    assert.equal(API.stairRoute(helper,g,{x:-3,y:0,z:0}).reason,'operator_stairs_unavailable');
    g.obstacleVolumes.push({id:'ceiling',minimumY:.8,maximumY:1.1,polygon:polygon(-2,-2,4,4)});
    assert(API.poseFits(helper,g,{x:0,y:0,z:0},'crawling',0).ok);
    assert(!API.poseFits(helper,g,{x:0,y:0,z:0},'standing',0).ok);
    g.obstacleVolumes.push({id:'head-wall',minimumY:0,maximumY:2,polygon:polygon(-.5,-1,.9,.1)});
    assert(!API.poseFits(helper,g,{x:0,y:0,z:0},'crawling',0).ok,'Crawl head has independent clearance checks');
    let p={x:0,y:0,z:0}, posture='standing';
    const host={position:()=>p,scale:1,speed:1,face(){},point(){},posture:v=>{posture=v;return true;},
        move:d=>{p={...p,x:p.x+d.x,z:p.z+d.z};return Math.hypot(d.x,d.z);}};
    const actions=[{kind:'move',points:[{x:1,z:0}]},{kind:'pose',posture:'kneeling',seconds:1}];
    const t=API.createTimeline(actions);
    t.tick(.1,host); t.pause(); const before={...p}, state=t.snapshot();
    t.tick(50,host); assert.deepEqual(p,before);assert.deepEqual(t.snapshot(),state);
    t.resume(); for(let i=0;i<80;i++) t.tick(.05,host);
    assert.equal(t.snapshot().status,'complete');assert.equal(posture,'kneeling');
    const cancelled=API.createTimeline(actions), cancelPosition={...p};
    cancelled.cancel();cancelled.tick(.5,host);assert.deepEqual(p,cancelPosition);
    assert.equal(cancelled.snapshot().status,'cancelled');
    const blocked=API.createTimeline([{kind:'move',points:[{x:3,z:0}]}]);
    for(let i=0;i<30;i++)blocked.tick(.05,{...host,move:()=>0});
    assert.equal(blocked.snapshot().reason,'operator_route_blocked');
    const turn=API.createTimeline([{kind:'pose',posture:'crawling',heading:Math.PI}]);
    turn.tick(.05,{...host,face:()=>false});
    assert.equal(turn.snapshot().reason,'operator_turn_blocked');
    assert(!API.transitionFits(helper,g,{x:0,y:0,z:0},'crawling','standing',0,0).ok);
    if(process.argv[2]) {
        const actual=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
        for (const dt of [.05,.25]) {
        const started=performance.now(),start={...actual.stairEntry,y:actual.floorY};
        const target=API.approach(helper,actual,start,actual.filterBox,'kneeling');assert(target.ok,JSON.stringify(target));
        const climb=API.stairRoute(helper,actual,target.end);assert(climb.ok,JSON.stringify(climb));
        const tour=API.createTimeline([{kind:'move',points:target.points},
            {kind:'pose',posture:'kneeling',heading:target.heading,seconds:4},
            {kind:'pose',posture:'standing',seconds:1},{kind:'move',points:climb.points},
            {kind:'pose',seconds:5,pointing:true},{kind:'move',points:climb.descent}]);
        let position={...start},pose='standing',heading=0,maxY=start.y;
        const host={position:()=>position,scale:actual.modelScale,speed:actual.walkSpeed,point(){},
            posture(value){if(!API.transitionFits(helper,actual,position,pose,value,heading,heading).ok)return false;pose=value;return true;},
            face(value){if(!API.transitionFits(helper,actual,position,pose,pose,heading,value).ok)return false;heading=value;return true;},
            move(delta){const next=helper.resolveMultiLevelWalkthroughMovement(API.movementInput(actual,position,delta,pose));
                const end={...next.position,y:next.elevation};if(!API.poseFits(helper,actual,end,pose,heading).ok)return 0;
                const distance=Math.hypot(position.x-end.x,position.z-end.z);position=end;maxY=Math.max(maxY,end.y);return distance;}};
        let ticks=0;
        while(tour.snapshot().status==='playing' && ticks++<6000)tour.tick(dt,host);
        assert.equal(tour.snapshot().status,'complete',JSON.stringify({state:tour.snapshot(),position}));
        assert(maxY-start.y>1);assert(Math.abs(position.y-actual.floorY)<.01);
        console.log(JSON.stringify({realGeometry:true,dt,ticks,maxElevation:maxY,finalPosition:position,elapsedMs:performance.now()-started}));
        }
    }
    console.log('Process operator: posture geometry, clearance, routing, pause/resume, cancellation and blocked motion passed');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
