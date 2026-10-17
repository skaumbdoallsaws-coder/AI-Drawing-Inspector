'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const g=require('../static/facility_layout_ground.js');
const tile=(id,a,b,y,end=y)=>({surfaceId:id,minX:a,maxX:b,minZ:0,maxZ:10,startElevation:y,endElevation:end,slopeAxis:'x',color:'#888888'});
const rows=[tile('yard',-30,-20,-1.35),tile('ramp',-20,0,-1.35,0),tile('factory',0,40,0)];
test('ground bounds include lower annex without moving factory',()=>{
 assert.deepEqual(g.bounds(rows),{minimum:{x:-30,y:-1.35,z:0},maximum:{x:40,y:0,z:10}});
 assert.equal(g.sample(rows,{x:-10,z:5},0).y,-.675);
 assert.equal(g.surfaces({}),null);
});
test('walk up and down continuous ramp including large deltas',()=>{
 for(const [a,b,y0,y1] of [[-25,5,-1.35,0],[5,-25,0,-1.35]]){
  const r=g.move(rows,{x:a,y:y0,z:5},{x:b,z:5});assert.equal(r.collided,false);assert.equal(r.position.y,y1);
 }
});
test('dock drops, gaps and steep slopes block movement',()=>{
 for(const surfaces of [[tile('yard',-20,0,-1.35),tile('factory',0,20,0)],[tile('yard',-20,-1,0),tile('factory',0,20,0)],[tile('ramp',-20,0,-10,0)]]){
  const y=g.sample(surfaces,{x:-5,z:5},0).y;
  assert.equal(g.move(surfaces,{x:-5,y,z:5},{x:5,z:5}).collided,true);
 }
});
test('rendered ramp vertices and navigation elevation agree',()=>{
 const v=g.vertices(rows[1],.1);assert.equal(v.positions.length,24);assert.equal(v.indices.length,36);
 for(let i=0;i<12;i+=3)assert.equal(v.positions[i+1],g.sample(rows,{x:v.positions[i],z:v.positions[i+2]},v.positions[i+1]).y);
});
