'use strict';
const assert=require('node:assert/strict');
const {test}=require('node:test');
const walls=require('../static/facility_layout_walls.js');
function layout() {
    return {extensions:{facilityPlan:{widthMeters:10,depthMeters:8},facilityPerimeterWalls:{version:1,
        settings:{boundarySource:'plan',heightMeters:3,thicknessMeters:.2,openings:[],exteriorFinish:{
            fittedArtworks:[{artworkId:'art',target:{edge:0,side:'interior'},region:[.1,0,.9,1],coverage:.97,uv:[0,0,1,1]}]
        }}}}};
}
test('fitted perimeter plane uses 97 percent and recomputes on resize',()=>{
    const doc=layout(),original=JSON.stringify(doc);
    let s=walls.fittedArtworkSurfaces(doc)[0];
    assert.equal(s.width,8*.97);assert.equal(s.height,3*.97);assert.ok(Math.abs(s.nx)<1e-8);assert.equal(s.nz,1);
    assert.ok(Math.abs(s.z-.114)<1e-8);assert.equal(JSON.stringify(doc),original);
    doc.extensions.facilityPlan.widthMeters=20;doc.extensions.facilityPerimeterWalls.settings.heightMeters=6;
    s=walls.fittedArtworkSurfaces(doc)[0];assert.equal(s.width,16*.97);assert.equal(s.height,6*.97);assert.equal(s.x,10);
});
test('all four perimeter faces point inward',()=>{
    const doc=layout();
    for(let edge=0;edge<4;edge++) {
        doc.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks[0].target.edge=edge;
        const s=walls.fittedArtworkSurfaces(doc)[0], normal=[[0,1],[-1,0],[0,-1],[1,0]][edge];
        assert.ok(Math.abs(s.nx-normal[0])<1e-8&&Math.abs(s.nz-normal[1])<1e-8);
    }
});
test('fitted artwork never covers doors',()=>{
    const doc=layout();doc.extensions.facilityPerimeterWalls.settings.openings=[{edge:0,startMeters:4,endMeters:6}];
    assert.deepEqual(walls.fittedArtworkSurfaces(doc),[]);
});
test('placed artwork resolves the current wall and all four faces',()=>{
    const doc=layout(),art=doc.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks[0];
    art.region=[0,0,1,1];
    const bounds={minimum:{x:-3,y:0,z:-.1},maximum:{x:3,y:3,z:.1}};
    const placement={placementId:'wall',transform:{position:{x:20,y:0,z:10}}};
    for(const [face,normal] of [['positive_z',[0,1]],['negative_z',[0,-1]],['positive_x',[1,0]],['negative_x',[-1,0]]]) {
        art.target={placementId:'wall',face};
        const s=walls.fittedArtworkSurfaces(doc,id=>({entry:{tags:['wall']},bounds,placement}))[0];
        assert.equal(s.placement,placement);assert.equal(s.nx,normal[0]);assert.equal(s.nz,normal[1]);
        assert.ok(face.endsWith('_z')?Math.abs(s.z)>.1:Math.abs(s.x)>3);
    }
    art.target.face='positive_z';bounds.maximum.y=5;bounds.maximum.x=4;
    const s=walls.fittedArtworkSurfaces(doc,()=>({entry:{tags:['wall']},bounds,placement}))[0];
    assert.equal(s.height,5*.97);assert.equal(s.width,7*.97);
    assert.deepEqual(walls.fittedArtworkSurfaces(doc,()=>null),[]);
    assert.deepEqual(walls.fittedArtworkSurfaces(doc,()=>({entry:{tags:['desk']},bounds,placement})),[]);
});
test('UV margin trim maximizes fit without distortion or cropping lettering',()=>{
    for(const uv of [[0,0,1,1],[.05,.25,.95,.75]]) {
        const f=walls.fittedArtworkFrame(8,3,1122,1402,uv);
        assert.ok(Math.abs((8*f.width)/(3*f.height)-1122*(uv[2]-uv[0])/(1402*(uv[3]-uv[1])))<1e-8);
        assert.ok(f.x>=0&&f.y>=0&&f.width<=1&&f.height<=1);
        assert.ok(Math.abs(f.width-1)<1e-8||Math.abs(f.height-1)<1e-8);
    }
});
