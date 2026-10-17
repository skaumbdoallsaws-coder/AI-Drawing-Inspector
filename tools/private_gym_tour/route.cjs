'use strict';
const assert = require('node:assert/strict');
const geometry = require('../../static/facility_layout_editor.js');
const navigation = require('../../static/facility_layout_three_adapter.js');
const walls = require('../../static/facility_layout_walls.js');
const ground = require('../../static/facility_layout_ground.js');

const eyeHeight = 1.7;
const walk = (name, x, z, target) => ({kind:'walk', name, point:{x,z}, target});
const fly = (name, position, target, duration=8000) => ({kind:'fly', name, position, target, duration});
const land = name => ({kind:'land',name});
const route = [
    fly('campus-reveal',[99,51,93],[39,1,26],10000),
    fly('above-reception',[10.6,14,8.8],[3.8,1.3,3.5]),
    fly('enter-reception',[10.6,eyeHeight,8.8],[3.8,1.3,3.5],7000),
    land('reception'),
    walk('cardio',34,8.5,[20,1.2,3.8]),
    walk('functional-training',39,10.8,[46,.8,5.3]),
    walk('recovery',54.5,8.7,[58.2,1.1,4.3]),
    walk('cables-and-upper-body',39.5,14,[44.8,1.2,24]),
    walk('washrooms',52.2,20.6,[57.2,1.2,16]),
    walk('lockers',52.5,28.4,[57,1.1,24]),
    walk('strength-machines',29.5,13.2,[24,1.2,24]),
    walk('free-weights',15.1,13,[6.5,1.15,23]),
    walk('hall-door-approach',21.1,1.2),
    walk('warrior-hall',21.1,-1.55,[34,1.6,-2.7]),
    walk('private-office',31.1,-4.5,[33.2,1.15,-8.2]),
    walk('conference',23.1,-4.1,[26,1.1,-8.3]),
    walk('lounge-entrance',6,-5,[16.6,1.1,-6.4]),
    walk('piano-and-guitars',5.8,-7.4,[2.7,1.35,-3.65]),
    walk('billiards',4.8,-14.8,[2.5,.82,-11.4]),
    walk('social-lounge',6.15,-15.8,[16.6,1.1,-6.4]),
    walk('table-games',16.5,-13.6,[20.1,.9,-16.3]),
    walk('kitchen',27,-12,[24.3,1.1,-16]),
    walk('cafe',34.9,-12.1,[30.3,.9,-15.3]),
    walk('return-through-lounge',6,-5),
    walk('hallway-to-pool',34,-1.55,[45,1.3,-5]),
    walk('pool-and-spa',47.1,-3.1,[41.6,.4,-11]),
    walk('pool-artwork',46.7,-14.7,[41.3,2,-.1]),
    fly('rise-over-wellness-wing',[46.7,14,-14.7],[32,0,-7]),
    fly('fly-to-boxing',[62.4,14,13.8],[74,1.5,7.5],10000),
    fly('descend-to-boxing',[62.4,eyeHeight,13.8],[74,1,7.5],7000),
    land('boxing'),
    walk('boxing-ring-and-bags',75.3,13.4,[77,1.5,5]),
    walk('basketball-entry',70.4,18.7,[71,2.8,35.8]),
    walk('basketball-court',70.4,28,[71,3,36]),
    fly('rise-over-basketball',[70.4,16,28],[71,0,27]),
    fly('fly-to-soccer',[39.7,16,59],[17,1,44],10000),
    fly('descend-to-soccer',[39.7,eyeHeight,59],[17,.2,44],7000),
    land('soccer'),
    walk('soccer-action-wall',39,38,[15,2.4,61.6]),
    walk('soccer-door',44,38),
    walk('outdoor-entry',46,42,[60,1,48]),
    walk('outdoor-training',66,58.6,[53,2.3,39.9]),
    walk('calisthenics-and-powerlifting',65.5,61.4,[54.8,1.1,67]),
    walk('barbecue-patio',81,61.9,[74.5,1.1,68]),
    fly('rise-from-patio',[81,18,61.9],[69,0,62]),
    fly('closing-campus',[111,69,108],[40,0,28],14000),
];

function scene(layout, catalog) {
    const surfaces = ground.surfaces(layout);
    const bounds = ground.bounds(surfaces);
    assert.ok(bounds, 'Missing authoritative floor surfaces');
    const volumes = layout.placements.map(p => {
        const asset = catalog.find(a => a.assetId===p.assetId && a.assetDefinitionRevision===p.assetDefinitionRevision);
        assert.ok(asset, 'Missing exact asset revision: '+p.assetId);
        const b = asset.definition.geometry.aabb;
        const q = p.transform.quaternion;
        // Current gym assets are upright; reject pitched assets rather than
        // silently underestimating their vertical collision envelope.
        assert.ok(Math.abs(q.x)<1e-7 && Math.abs(q.z)<1e-7,'Pitched asset requires a full transformed envelope');
        return {id:p.placementId,polygon:geometry.placementFootprint(p,{assetCatalog:catalog}),
            minimumY:p.transform.position.y+b.minimum.y*p.transform.scale,
            maximumY:p.transform.position.y+b.maximum.y*p.transform.scale};
    }).concat(walls.panels(layout).map((polygon,i)=>({id:'perimeter-'+i,polygon,
        minimumY:0,maximumY:walls.data(layout).settings.heightMeters})));
    return {surfaces,bounds,volumes,obstacles:volumes.map(v=>v.polygon)};
}

function checkFlight(from,to,volumes) {
    const distance=Math.hypot(...to.map((v,i)=>v-from[i]));
    const count=Math.max(1,Math.ceil(distance/.1));
    for(let i=0;i<=count;i++) {
        const t=i/count,p={x:from[0]+(to[0]-from[0])*t,y:from[1]+(to[1]-from[1])*t,z:from[2]+(to[2]-from[2])*t};
        const hit=volumes.find(v=>navigation.sphereIntersectsDroneVolume(p,.35,v));
        assert.ok(!hit,'Flight intersects '+hit?.id+' at '+JSON.stringify(p));
    }
    return {distance,samples:count+1};
}

function checkWalkingDynamics(plan,data) {
    const index=navigation.buildDroneSpatialIndex(data.volumes.map(v=>({...v,minimumY:0,maximumY:1})));
    const frameIntervals=[.016,.033,.05,.07,.1,.2];
    for(const dt of frameIntervals){
        let p={...plan.points[0],y:0};
        for(const goal of plan.points.slice(1)){
            let steps=0;
            while(true){
                const dx=goal.x-p.x,dz=goal.z-p.z,length=Math.hypot(dx,dz);
                if(length<1e-7)break;
                assert.ok(++steps<10000,'Walking simulation did not converge');
                const travel=Math.min(length,navigation.DEFAULT_WALKTHROUGH_SETTINGS.navigationSpeed*dt);
                const delta={x:dx/length*travel,z:dz/length*travel};
                const near=navigation.walkthroughSweptObstacles(index,p,delta,.3);
                const result=navigation.resolveWalkthroughMovement({start:p,delta,radius:.3,bounds:data.bounds,obstacles:near});
                const grounded=ground.move(data.surfaces,p,result.position);
                assert.ok(!result.collided&&!grounded.collided,'Movement collision at '+JSON.stringify(p)+'; dt='+dt);
                p=grounded.position;
            }
        }
    }
    return frameIntervals;
}

function flightView(start,position,target,u) {
    const angles=(p,t)=>{
        const dx=t.x-p.x,dy=t.y-p.y,dz=t.z-p.z;
        const pitch=Math.atan2(dy,Math.hypot(dx,dz));
        assert.ok(pitch<=-.03+1e-8&&pitch>=-Math.PI/2+.03-1e-8,'Flight gaze exceeds orbit limits');
        return {yaw:Math.atan2(dx,dz),pitch};
    };
    const a=angles(start.position,start.target),b=angles(position,target);
    const yaw=a.yaw+Math.atan2(Math.sin(b.yaw-a.yaw),Math.cos(b.yaw-a.yaw))*u;
    const pitch=a.pitch+(b.pitch-a.pitch)*u;
    const p=Object.fromEntries(['x','y','z'].map(k=>[k,start.position[k]+(position[k]-start.position[k])*u]));
    // Interpolate heading and tilt, not world-space look targets. Opposing
    // targets can otherwise pass directly below the camera and trigger the
    // orbit controller's polar clamp even when both endpoints are valid.
    return {...start,position:p,target:{x:p.x+10*Math.sin(yaw)*Math.cos(pitch),
        y:p.y+10*Math.sin(pitch),z:p.z+10*Math.cos(yaw)*Math.cos(pitch)},up:{x:0,y:1,z:0},fov:60,near:.05,far:600};
}

function preflight(layout,catalog) {
    const data=scene(layout,catalog),results=[];
    let position=[106,84,111];
    for(const step of route) {
        if(step.kind==='fly') {
            results.push({name:step.name,kind:step.kind,...checkFlight(position,step.position,data.volumes)});
            position=step.position;
        } else if(step.kind==='land') {
            assert.ok(Math.abs(position[1]-eyeHeight)<.001,'Landing must match eye height');
            assert.ok(navigation.walkthroughPointValid({x:position[0],z:position[2]},.3,data.bounds,data.obstacles));
        } else {
            const plan=navigation.planWalkthroughRoute({start:{x:position[0],z:position[2]},goal:step.point,
                radius:.3,bounds:data.bounds,obstacles:data.obstacles});
            assert.ok(plan.ok,step.name+': '+plan.reason);
            for(let j=1;j<plan.points.length;j++) {
                const a=plan.points[j-1],b=plan.points[j],n=Math.ceil(Math.hypot(b.x-a.x,b.z-a.z)/.1);
                for(let k=0;k<=n;k++) {
                    const t=n?k/n:0,p={x:a.x+(b.x-a.x)*t,z:a.z+(b.z-a.z)*t};
                    const floor=ground.sample(data.surfaces,p,0);
                    assert.ok(floor&&Math.abs(floor.y)<.01,step.name+': unsupported walking surface');
                }
            }
            const frameIntervals=checkWalkingDynamics(plan,data);
            results.push({name:step.name,kind:step.kind,plan,frameIntervals});
            position=[step.point.x,eyeHeight,step.point.z];
        }
    }
    return {results,scene:data};
}

module.exports={route,eyeHeight,scene,checkFlight,checkWalkingDynamics,flightView,preflight};
