'use strict';
const assert=require('node:assert/strict');
const {test}=require('node:test');
const decals=require('../static/facility_layout_decals.js');
const walls=require('../static/facility_layout_walls.js');
const transport=require('../static/facility_layout_transport.js');
function layout() { return {placements:[],extensions:{facilityPlan:{widthMeters:40,depthMeters:30},facilityPerimeterWalls:{version:1,
    settings:{boundarySource:'plan',heightMeters:4,thicknessMeters:.2,openings:[{edge:0,startMeters:5,endMeters:8}]}}}}; }
const imported={imagePath:'/api/facility-decal-images/site-a/'+'a'.repeat(64)+'.png',uv:[.1,.2,.9,.8]};
test('targets use actual dimensions and split both wall sides around doors',()=>{
    const doc=layout(),before=JSON.stringify(doc),list=decals.targets(doc,[]);
    assert.equal(list.length,10);assert.equal(JSON.stringify(doc),before);
    assert.deepEqual(list.filter(s=>s.target.edge===0&&s.target.side==='interior').map(s=>[s.start,s.end]),[[0,5],[8,40]]);
    assert.equal(list[0].height,4);
    doc.extensions.facilityPerimeterWalls.settings={boundarySource:'polygon',boundary:[{x:2,z:3},{x:14,z:3},{x:14,z:9},{x:7,z:9},{x:7,z:13},{x:2,z:13}],heightMeters:3,openings:[]};
    assert.equal(decals.targets(doc,[]).length,12);
    assert.equal(decals.targets(doc,[])[0].width,12);
});
test('interior wall targets require exact catalog identity and wall metadata',()=>{
    const doc={placements:[{placementId:'p',assetId:'wall',assetDefinitionRevision:'a',transform:{scale:2}}]};
    const entry={assetId:'wall',assetDefinitionRevision:'a',definition:{tags:['wall'],geometry:{aabb:{minimum:{x:-3,y:0,z:-.1},maximum:{x:3,y:3,z:.1}}}}};
    const list=decals.targets(doc,[entry]);assert.equal(list.length,4);assert.equal(list[0].width,12);assert.equal(list[0].height,6);
    assert.equal(decals.targets(doc,[{...entry,assetDefinitionRevision:'b'}]).length,0);
    assert.equal(decals.targets(doc,[]).length,0);
});
test('decal region is bounded, proportional and does not modify its wall',()=>{
    const doc=layout(),s=decals.targets(doc,[])[0],before=JSON.stringify(doc);
    const values={label:'Logo',width:4,height:3,offset:.5,bottom:.5,trim:true};
    const record=decals.makeRecord(s,values,imported,'decal');
    assert.deepEqual(record.region,[.0125,.125,.1125,.875]);assert.deepEqual(record.uv,imported.uv);
    assert.deepEqual(decals.makeRecord(s,{...values,trim:false},imported,'decal').uv,[0,0,1,1]);
    assert.throws(()=>decals.makeRecord(s,{...values,width:6},imported,'decal'),/fit/);
    assert.throws(()=>decals.makeRecord(s,{...values,bottom:-1},imported,'decal'),/fit/);
    assert.throws(()=>decals.makeRecord(s,values,null,'decal'),/image/);
    assert.equal(JSON.stringify(doc),before);
    doc.extensions.facilityDecals={version:1,artworks:[record]};
    assert.equal(walls.fittedArtworkSurfaces(doc)[0].width,4);
    assert.equal(walls.exteriorSurfaces(doc).length,0);
});
test('standalone decal renders without perimeter walls and follows placed wall dimensions',()=>{
    const bounds={minimum:{x:-4,y:0,z:-.1},maximum:{x:4,y:3,z:.1}},placement={placementId:'p'};
    const doc={extensions:{facilityDecals:{version:1,artworks:[{artworkId:'x',target:{placementId:'p',face:'negative_z'},region:[0,0,1,1],coverage:1}]}}};
    const resolve=()=>({bounds,placement,entry:{tags:['wall']}});
    assert.equal(walls.fittedArtworkSurfaces(doc,resolve)[0].width,8);
    bounds.maximum.x=6;assert.equal(walls.fittedArtworkSurfaces(doc,resolve)[0].width,10);
    assert.equal(walls.fittedArtworkSurfaces(doc,()=>null).length,0);
});
test('image transport retains scope and authority, rejects unsupported input, and propagates failures',async()=>{
    const calls=[];let ok=true;
    const api=transport.createHttpTransport({siteId:'site-a',layoutId:'fl-demo',sessionId:'session-decals',headers:{Authorization:'test-only'},
        fetch:async(url,init)=>{calls.push({url,init});return {ok,status:ok?200:422,json:async()=>ok?imported:{error:{code:'bad_image',message:'Invalid image'}}};}});
    const file={type:'image/png',size:123},controller=new AbortController();
    assert.deepEqual(await api.importDecalImage(file,{signal:controller.signal}),imported);
    assert.equal(calls[0].url,'/api/facility-layouts/site-a/fl-demo/decal-images');
    assert.equal(calls[0].init.body,file);assert.equal(calls[0].init.headers.Authorization,'test-only');
    assert.equal(calls[0].init.headers['X-InspectorPro-Session'],'session-decals');
    assert.equal(calls[0].init.signal,controller.signal);
    await assert.rejects(()=>api.importDecalImage({type:'image/svg+xml',size:100}),/PNG or JPEG/);
    await assert.rejects(()=>api.importDecalImage({type:'image/png',size:11*1024*1024}),/10 MB/);
    assert.equal(calls.length,1);ok=false;
    await assert.rejects(()=>api.importDecalImage(file),error=>error.code==='bad_image');
});
