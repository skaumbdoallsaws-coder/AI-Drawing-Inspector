'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../static/documentation_objects_core.js');
const vectors = JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/documentation_object_vectors.json'),'utf8'));
function near(a,b,tolerance=1e-9) {
    if(typeof a==='number') assert.ok(Math.abs(a-b)<=tolerance, `${a} != ${b}`);
    else if(Array.isArray(a)){assert.equal(a.length,b.length);a.forEach((v,i)=>near(v,b[i],tolerance));}
    else {assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort());for(const k of Object.keys(a))near(a[k],b[k],tolerance);}
}
test('Python placement and rotated box vectors',()=>{
    assert.ok(vectors.placement.length>=150 && vectors.box.length>=150);
    for(const v of vectors.placement) near(core.placement(v.value,v.size,v.pixels),v.expected);
    for(const v of vectors.box)near(core.box(v.frame,v.size),v.expected);
});
function anchor(f,size,handle) {
    const sx=handle.includes('e')?1:handle.includes('w')?-1:0;
    const sy=handle.includes('s')?1:handle.includes('n')?-1:0;
    const w=f.width*size[0],h=f.height*size[1];
    const [dx,dy]=core.turn(-sx*w/2,-sy*h/2,f.rotation);
    return [f.x*size[0]+w/2+dx,f.y*size[1]+h/2+dy];
}
for(const size of [[960,540],[612,792]])for(const rotation of [0,90,180,270,30])
for(const handle of core.HANDLES)for(const locked of [false,true]){
    test(`resize ${size} ${rotation} ${handle} locked=${locked}`,()=>{
        const f={x:.3,y:.3,width:.3,height:.2,rotation};
        const next=core.resize(f,size,handle,[37,-19],locked);
        near(anchor(f,size,handle),anchor(next,size,handle));
        if(locked)near(next.width/next.height,f.width/f.height);
        if(!locked && handle.length===1) {
            if(handle==='n'||handle==='s')near(next.width,f.width);else near(next.height,f.height);
        }
        assert.ok(core.valid(next));
    });
}
test('shift corner, minimum dimensions, bounds and edge ratio',()=>{
    const size=[960,540],f={x:.1,y:.1,width:.2,height:.1,rotation:30};
    for(const handle of core.HANDLES){
        const next=core.resize(f,size,handle,core.turn(handle.includes('w')?10000:-10000,
            handle.includes('n')?10000:-10000,30),true);
        assert.ok(next.width*size[0]>=Math.max(8,size[0]*.01)-1e-9);
        assert.ok(next.height*size[1]>=Math.max(8,size[1]*.01)-1e-9);
        near(anchor(f,size,handle),anchor(next,size,handle));
        near(next.width/next.height,f.width/f.height);
    }
    for(const h of ['nw','ne','sw','se']) {
        const next=core.resize(f,size,h,[19,41],false,true);
        near(next.width/next.height,f.width/f.height);near(anchor(f,size,h),anchor(next,size,h));
    }
    const limit={x:1.95,y:1.95,width:.05,height:.05,rotation:30};
    assert.ok(core.valid(core.resize(limit,size,'se',[10000,10000])));
});
test('move and nudge in points preserve the complete selection',()=>{
    const size=[960,540],frames=[{x:.1,y:.2,width:.3,height:.1,rotation:30},{x:.7,y:.5,width:.2,height:.2,rotation:0}];
    const moved=core.move(frames,size,37,-19);
    moved.forEach((f,i)=>{near((f.x-frames[i].x)*960,37);near((f.y-frames[i].y)*540,-19);});
    const nudged=core.nudge(core.nudge(frames,size,3,0),size,0,1,true);
    near(nudged[0].x,frames[0].x+3/960);near(nudged[0].y,frames[0].y+10/540);
    const clamped=core.move(frames,size,50000,-50000);
    near(clamped[1].x,2);near(clamped[0].y,-1);
    near(clamped[1].x-clamped[0].x,frames[1].x-frames[0].x);
    assert.deepEqual(frames[0],{x:.1,y:.2,width:.3,height:.1,rotation:30});
});
test('crop layout preserves placement and crop result preserves the chosen rectangle',()=>{
    for(const rotation of [0,90,180,270,30]){
        const value={objectId:'image',contentMode:'contain',aspectLock:true,
            frame:{x:.2,y:.2,width:.4,height:.4,rotation}};
        const layout=core.cropLayout(value,[1000,500],[200,100]);
        near(layout.kept,{x:0,y:0,width:400,height:200});
        near(core.cropFrame(layout,layout.kept),value.frame);
        const rect=core.cropDrag(layout,layout.kept,'sw',core.turn(200,-100,rotation));
        near(rect,{x:200,y:0,width:200,height:100});
        const ops=core.cropResult(layout,rect);
        assert.equal(ops.length,2);near(ops[0].crop,{x:.5,y:0,width:.5,height:.5});
        assert.equal(ops[1].aspectLock,true);
        const expected=core.rounded(core.cropFrame(layout,rect));
        for(const k of ['x','y','width','height'])near(ops[1][k],expected[k]);
        assert.deepEqual(core.cropResult(layout,layout.kept),[]);
    }
});
test('cover starting state, reset, whole crop, limits, masks and no-op filtering',()=>{
    const value={objectId:'image',contentMode:'cover',frame:{x:.2,y:.2,width:.2,height:.4,rotation:90}};
    const layout=core.cropLayout(value,[1000,500],[200,100]);
    near(layout.source,{x:.25,y:0,width:.5,height:1});
    near(layout.whole,{x:-100,y:0,width:400,height:200});
    assert.deepEqual(core.cropResult(layout,layout.kept),[]);
    const reset=core.cropResult(layout,layout.kept,true);
    assert.equal(reset.length,1);assert.equal(reset[0].operation,'set_object_frame');
    const moved=core.cropDrag(layout,layout.kept,'move',[10000,10000]);
    assert.ok(moved.x>=layout.whole.x && moved.x+moved.width<=layout.whole.x+layout.whole.width+1e-9);
    const small=core.cropDrag(layout,layout.kept,'se',core.turn(-10000,-10000,90));
    assert.ok(small.width>=10-1e-9 && small.height>=8-1e-9);
    const masks=core.cropMasks(layout,layout.kept);
    near(masks.reduce((n,r)=>n+r.width*r.height,0)+layout.kept.width*layout.kept.height,layout.whole.width*layout.whole.height);
    const cropped={...value,contentMode:'contain',crop:{height:.5,width:.5,y:0,x:.5}};
    const partial=core.cropLayout(cropped,[1000,500],[200,100]);
    const cleared=core.cropResult(partial,partial.kept,true);
    assert.equal(cleared[0].crop,null);
});
test('order availability and arrangement no-ops',()=>{
    assert.deepEqual(core.orderMoves(['a','b','c'],'a'),{front:true,forward:true,back:false,backward:false});
    assert.deepEqual(core.orderMoves(['a','b','c'],'c'),{front:false,forward:false,back:true,backward:true});
    assert.deepEqual(core.orderMoves(['a'],'a'),{front:false,forward:false,back:false,backward:false});
    assert.deepEqual(core.orderMoves(['a'],'missing'),{front:false,forward:false,back:false,backward:false});
    const rows=[.1,.3,.5].map(x=>({frame:{x,y:.2,width:.1,height:.1,rotation:0}}));
    assert.equal(core.arrangementChanges(rows,[960,540],'distribute_horizontal'),false);
    assert.equal(core.arrangementChanges(rows,[960,540],'align_left'),true);
});
test('image insertion uses displayed proportions and the height cap',()=>{
    const f=core.insertedImage([960,540],[200,100]);near(f.width,.4);near(f.height,.355556,1e-9);
    near((f.x+f.width/2),.5);near((f.y+f.height/2),.38,1e-6);
    const tall=core.insertedImage([960,540],[100,1000]);near(tall.height,.5);near(tall.width,.028125);
});

test('a thin legacy picture cannot preview a crop outside its whole picture',()=>{
    const value={contentMode:'contain',frame:{x:.1,y:.1,width:.2,height:.2,rotation:0}};
    const layout=core.cropLayout(value,[960,540],[10000,1]);
    near(core.cropDrag(layout,layout.kept,'se',[20,20]),layout.kept);
});
