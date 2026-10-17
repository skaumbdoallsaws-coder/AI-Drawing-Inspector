'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {route,eyeHeight,scene,checkFlight,checkWalkingDynamics,flightView} = require('./route.cjs');
const {TourControl,verifyArrival} = require('../factory02_tour/control.cjs');

const volume={id:'wall',minimumY:0,maximumY:4,polygon:[
    {x:0,z:0},{x:10,z:0},{x:10,z:.2},{x:0,z:.2},
]};
test('aerial movement rejects crossing walls but permits clearing their tops',()=>{
    assert.throws(()=>checkFlight([5,2,-2],[5,2,2],[volume]),/Flight intersects wall/);
    assert.throws(()=>checkFlight([5,4.2,-2],[5,4.2,2],[volume]),/Flight intersects wall/);
    assert.ok(checkFlight([5,4.5,-2],[5,4.5,2],[volume]).samples>30);
});
test('takeoff and landing validate endpoints as well as intermediate samples',()=>{
    assert.throws(()=>checkFlight([5,2,.1],[5,8,.1],[volume]),/Flight intersects/);
    assert.throws(()=>checkFlight([5,8,.1],[5,2,.1],[volume]),/Flight intersects/);
});
test('every walking block has an explicit continuous aerial landing',()=>{
    let flying=true,previous;
    for(const step of route){
        if(step.kind==='fly')flying=true;
        if(step.kind==='land'){
            assert.equal(previous.kind,'fly');assert.equal(previous.position[1],eyeHeight);flying=false;
        }
        if(step.kind==='walk')assert.equal(flying,false);
        previous=step;
    }
    assert.equal(new Set(route.map(s=>s.name)).size,route.length);
});
test('scene refuses a missing asset revision rather than using a guessed footprint',()=>{
    const layout={placements:[{assetId:'a',assetDefinitionRevision:'r'}],extensions:{facilityGround:{surfaces:[{
        surfaceId:'floor',minX:0,maxX:10,minZ:0,maxZ:10,startElevation:0,endElevation:0,slopeAxis:'x',
    }]}}};
    assert.throws(()=>scene(layout,[]),/Missing exact asset revision/);
});
test('pause clock excludes suspended time and changes navigation epoch',()=>{
    let time=0;const control=new TourControl(false,()=>time);
    time=100;control.toggle();time=10000;assert.equal(control.now(),100);
    control.toggle();time=10100;assert.equal(control.now(),200);assert.equal(control.epoch,2);
    control.stop();assert.throws(()=>control.check(),/tour_stopped/);
});
test('arrival requires real movement completion, not just a nearby camera',()=>{
    const state={active:true,route:{active:false,reason:'arrived'},position:{x:2,z:3}};
    assert.equal(verifyArrival(state,{x:2,z:3}),0);
    assert.throws(()=>verifyArrival({...state,route:{active:false,reason:'blocked'}},{x:2,z:3}),/did not arrive/);
    assert.throws(()=>verifyArrival(state,{x:3,z:3}),/ended short/);
});
test('movement preflight exercises the actual collision solver at six frame intervals',()=>{
    const data={volumes:[volume],bounds:{minimum:{x:-3,y:0,z:-3},maximum:{x:13,y:0,z:3}},
        surfaces:[{surfaceId:'floor',minX:-3,maxX:13,minZ:-3,maxZ:3,startElevation:0,endElevation:0,slopeAxis:'x'}]};
    assert.throws(()=>checkWalkingDynamics({points:[{x:5,z:-2},{x:5,z:2}]},data),/Movement collision/);
    assert.equal(checkWalkingDynamics({points:[{x:5,z:-2},{x:7,z:-2}]},data).length,6);
});
test('opposing aerial headings never pass through the orbit polar clamp',()=>{
    const start={position:{x:46.7,y:14,z:-14.7},target:{x:32,y:0,z:-7}};
    const end={x:62.4,y:14,z:13.8},target={x:74,y:1.5,z:7.5};
    for(let i=0;i<=1000;i++){
        const v=flightView(start,end,target,i/1000);
        const dx=v.target.x-v.position.x,dy=v.target.y-v.position.y,dz=v.target.z-v.position.z;
        const pitch=Math.atan2(dy,Math.hypot(dx,dz));
        assert.ok(pitch<-.03&&pitch>-Math.PI/2+.03);
        assert.equal(v.position.y,14);
    }
    assert.deepEqual(flightView(start,end,target,1).position,end);
});
