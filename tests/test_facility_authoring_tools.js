'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const walls=require('../static/facility_layout_walls.js');
const decals=require('../static/facility_layout_decals.js');
const materials=require('../static/facility_layout_component_materials.js');
const replacement=require('../static/facility_layout_replace_asset.js');
const lettering=require('../static/facility_layout_lettering.js');

test('normalized workspace catalog retains measured wall targets and replacement dimensions',()=>{
    const entry={assetId:'asset-wall',assetDefinitionRevision:'a'.repeat(64),label:'Office wall',source:{definition:{tags:['wall'],geometry:{aabb:{minimum:{x:-3,y:0,z:-.1},maximum:{x:3,y:3,z:.1}}}}}};
    const layout={placements:[{placementId:'pl-wall',assetId:entry.assetId,assetDefinitionRevision:entry.assetDefinitionRevision,transform:{scale:1}}]};
    const targets=decals.targets(layout,[entry]);
    assert.equal(targets.length,4);assert.equal(targets[0].width,6);assert.match(targets[0].label,/Office wall/);
    assert.deepEqual(replacement.dimensions(entry),{x:6,y:3,z:.2});
});
test('interior wall volumes and decal surfaces share dimensions and normals',()=>{
    const wall={wallId:'iw-test',start:{x:2,z:3},end:{x:12,z:3},heightMeters:4,thicknessMeters:.2,baseElevation:0,color:'#45484b',openings:[],panels:[[{x:2,z:2.9},{x:12,z:2.9},{x:12,z:3.1},{x:2,z:3.1}]]};
    const art={artworkId:'text',target:{wallId:'iw-test',side:'left'},region:[.1,.1,.9,.9],coverage:1};
    const layout={extensions:{facilityInteriorWalls:{version:1,walls:[wall]},facilityDecals:{version:1,artworks:[art]}}};
    assert.equal(walls.volumes(layout)[0].maximumY,4);
    const face=walls.fittedArtworkSurfaces(layout)[0];
    assert.equal(face.width,8);assert.equal(face.height,3.2);assert.equal(face.x,7);assert.equal(face.nz,1);assert.equal(face.z,3.114);
});
test('slot keys remain stable for unnamed meshes and material arrays',()=>{
    const color=()=>({value:'#aaaaaa',set(v){this.value=v;}});
    const a={color:color()},b={color:color()},c={color:color()};
    const object={traverse(fn){fn({isMesh:true,name:'Frame',material:a});fn({isMesh:true,material:[b,c]});}};
    assert.deepEqual(materials.slots(object).map(s=>s.key),['m0-s0','m1-s0','m1-s1']);
    const config={representation:'overview',overrides:[{key:'m1-s1',color:'#c99b39',roughness:.3,metalness:.7}]};
    materials.apply(object,config,'detail');assert.equal(c.color.value,'#aaaaaa');
    materials.apply(object,config,'overview');assert.equal(c.color.value,'#c99b39');assert.equal(a.color.value,'#aaaaaa');assert.equal(b.color.value,'#aaaaaa');assert.equal(c.metalness,.7);
});
test('lettering rejects unbounded text and unsupported settings',()=>{
    const value={text:'Build with purpose',reference:'APEX',font:'Arial',align:'center',color:'#c99b39'};
    assert.deepEqual(lettering.validate(value),value);
    for(const patch of [{text:''},{text:'a'.repeat(1001)},{font:'arbitrary-font'},{align:'justify'},{color:'gold'}])assert.throws(()=>lettering.validate({...value,...patch}));
});
test('replacement footprint fallback uses measured geometry rather than guessed dimensions',()=>{
    const entry={source:{definition:{geometry:{footprintPolygons:[[{x:-2,z:-1},{x:2,z:1}]],heightInterval:{minimumY:0,maximumY:3}}}}};
    assert.deepEqual(replacement.dimensions(entry,2),{x:8,y:6,z:4});
    assert.equal(replacement.dimensions({assetId:'missing-measurements'}),null);
});
test('column volumes stand on their base to their top, in their color or a plain grey under a library finish',()=>{
    const square=[{x:4.8,z:4.8},{x:5.2,z:4.8},{x:5.2,z:5.2},{x:4.8,z:5.2}];
    const layout={extensions:{facilityColumns:{version:1,columns:[
        {columnId:'col-a',label:'A',baseElevation:0.5,heightMeters:6,appearance:{color:'#336699'},footprint:square},
        {columnId:'col-b',label:'B',baseElevation:0,heightMeters:8,appearance:{appearanceId:'concrete-smooth'},footprint:square},
        {columnId:'col-c',label:'C',baseElevation:0,heightMeters:8,appearance:{color:'#000000'},footprint:[]}]}}};
    const [a,b,...rest]=walls.columnVolumes(layout);
    assert.deepEqual([a.id,a.columnId,a.minimumY,a.maximumY,a.color,a.polygon],['layout-column-col-a','col-a',0.5,6.5,'#336699',square]);
    assert.deepEqual([b.color,b.appearance],['#8f969c',{appearanceId:'concrete-smooth'}]);
    assert.deepEqual(rest,[]);  // no outline, nothing to draw
    assert.deepEqual(walls.columnVolumes({extensions:{}}),[]);
    assert.equal(walls.volumes(layout).length,0);  // columns are not walls
});
