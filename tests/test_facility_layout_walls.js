'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const walls = require('../static/facility_layout_walls.js');

test('exterior surfaces face outward for either boundary winding and leave doors clear',()=>{
    const finish={color:'#282b2d',jointColor:'#111111',panelWidthMeters:2,panelHeightMeters:1,jointWidthMeters:.012};
    for(const boundary of [[{x:0,z:0},{x:10,z:0},{x:10,z:8},{x:0,z:8}],
        [{x:10,z:0},{x:0,z:0},{x:0,z:8},{x:10,z:8}]]) {
        const layout={extensions:{facilityPerimeterWalls:{version:1,settings:{boundarySource:'polygon',boundary,
            heightMeters:3,thicknessMeters:.2,openings:[{edge:0,startMeters:4,endMeters:6}],exteriorFinish:finish}}}};
        const surfaces=walls.exteriorSurfaces(layout);
        assert.ok(surfaces.length>30);
        const front=surfaces.filter(s=>s.edge===0);
        assert.ok(front.every(s=>s.nz===-1&&s.z<-.1));
        assert.ok(front.every(s=>s.x+s.width/2<=4.00001||s.x-s.width/2>=5.99999));
        assert.ok(surfaces.every(s=>s.width>0&&s.height>0));
    }
    assert.deepEqual(walls.exteriorSurfaces({}),[]);
});

test('artwork and accent surfaces preserve source UV and original inside faces',()=>{
    const artwork={artworkId:'logo',edge:0,startMeters:1,widthMeters:3,bottomMeters:.2,heightMeters:2,imagePath:'/generated/facility-wall-art/a.png',uv:[.1,.2,.9,.8],backingColor:'#aaaaaa'};
    const layout={extensions:{facilityPlan:{widthMeters:10,depthMeters:8},facilityPerimeterWalls:{version:1,settings:{boundarySource:'plan',heightMeters:3,thicknessMeters:.2,openings:[],
        exteriorFinish:{color:'#222222',jointColor:'#111111',panelWidthMeters:2,panelHeightMeters:1,jointWidthMeters:.012,artworks:[artwork],accentStrips:[{edge:0,startMeters:5,widthMeters:.05,color:'#bb9911'}]}}}}};
    const before=JSON.stringify(layout),surfaces=walls.exteriorSurfaces(layout);
    assert.equal(JSON.stringify(layout),before);
    assert.equal(surfaces.find(s=>s.artwork).artwork,artwork);
    assert.equal(surfaces.filter(s=>s.color==='#bb9911').length,1);
    assert.ok(surfaces.filter(s=>s.edge===0).every(s=>s.z<0));
});

test('wall identity uses explicit tags or structure metadata, not category or labels', () => {
    assert.equal(walls.isWallAsset({tags:['wall']}),true);
    assert.equal(walls.isWallAsset({tags:[],definition:{tags:['wall']}}),true);
    assert.equal(walls.isWallAsset({assetDefinition:{structureKind:'wall'}}),true);
    assert.equal(walls.isWallAsset({displayName:'Wall desk',category:'Building Structures'}),false);
    assert.equal(walls.isWallAsset(null),false);
});

test('interior paint faces inward, clears doors, and leaves exterior and graphics intact',()=>{
    for(const boundary of [[{x:0,z:0},{x:10,z:0},{x:10,z:8},{x:0,z:8}],
        [{x:10,z:0},{x:0,z:0},{x:0,z:8},{x:10,z:8}]]) {
        const settings={boundarySource:'polygon',boundary,heightMeters:3,thicknessMeters:.2,
            openings:[{edge:0,startMeters:4,endMeters:6}],interiorColor:'#3b4147'};
        const layout={extensions:{facilityPerimeterWalls:{version:1,settings}}};
        const standalone=walls.exteriorSurfaces(layout);
        assert.equal(standalone.length,5);
        assert.ok(standalone.every(s=>s.color==='#3b4147'));
        assert.ok(standalone.filter(s=>s.edge===0).every(s=>s.nz===1&&Math.abs(s.z-.102)<1e-8));
        assert.ok(standalone.filter(s=>s.edge===0).every(s=>s.x+s.width/2<=4.00001||s.x-s.width/2>=5.99999));
        settings.exteriorFinish={color:'#111111',jointColor:'#222222',panelWidthMeters:2,panelHeightMeters:1,
            jointWidthMeters:.012,artworks:[{artworkId:'inside',side:'interior',edge:0,startMeters:1,
                widthMeters:2,bottomMeters:.3,heightMeters:2}]};
        const combined=walls.exteriorSurfaces(layout);
        assert.deepEqual(combined.filter(s=>s.color==='#3b4147'),standalone);
        delete settings.interiorColor;
        assert.deepEqual(combined.filter(s=>s.color!=='#3b4147'),walls.exteriorSurfaces(layout));
        assert.ok(combined.find(s=>s.artwork).z>standalone[0].z);
    }
});

test('interior graphics and optional frames face inward for both polygon windings',()=>{
    for(const boundary of [[{x:0,z:0},{x:10,z:0},{x:10,z:8},{x:0,z:8}],
        [{x:10,z:0},{x:0,z:0},{x:0,z:8},{x:10,z:8}]]) {
        const art={artworkId:'inside',side:'interior',edge:0,startMeters:1,widthMeters:2,
            bottomMeters:.3,heightMeters:2,uv:[0,0,1,1],backingColor:'#aaaaaa',borderColor:'#bbbbbb'};
        const finish={color:'#222222',jointColor:'#111111',panelWidthMeters:2,panelHeightMeters:1,
            jointWidthMeters:.012,artworks:[art]};
        const layout={extensions:{facilityPerimeterWalls:{version:1,settings:{boundarySource:'polygon',boundary,
            heightMeters:3,thicknessMeters:.2,openings:[],exteriorFinish:finish}}}};
        const surfaces=walls.exteriorSurfaces(layout),graphic=surfaces.find(s=>s.artwork);
        assert.ok(Math.abs(graphic.z-.114)<1e-8);
        assert.equal(graphic.nz,1);
        assert.equal(graphic.artwork,art);
        assert.equal(surfaces.filter(s=>s.color==='#bbbbbb').length,4);
        assert.ok(surfaces.filter(s=>['#aaaaaa','#bbbbbb'].includes(s.color)).every(s=>s.nz===1&&s.z>.1));
        assert.ok(surfaces.filter(s=>s.edge===0&&!s.artwork&&!['#aaaaaa','#bbbbbb'].includes(s.color)).every(s=>s.z<-.1));
    }
});

test('all four interior artwork faces point toward the room without modifying source UVs',()=>{
    const artworks=[0,1,2,3].map(edge=>({artworkId:'art-'+edge,side:'interior',edge,startMeters:1,widthMeters:2,
        bottomMeters:.2,heightMeters:2,uv:[0,0,1,1]}));
    const layout={extensions:{facilityPlan:{widthMeters:10,depthMeters:8},facilityPerimeterWalls:{version:1,settings:{
        boundarySource:'plan',heightMeters:3,thicknessMeters:.2,openings:[],exteriorFinish:{color:'#222222',
        jointColor:'#111111',panelWidthMeters:2,panelHeightMeters:1,jointWidthMeters:.012,artworks}}}}};
    const original=JSON.stringify(layout);
    for(const s of walls.exteriorSurfaces(layout).filter(s=>s.artwork)) {
        const [nx,nz]=[[0,1],[-1,0],[0,-1],[1,0]][s.edge];
        assert.ok(Math.abs(s.nx-nx)<1e-8&&Math.abs(s.nz-nz)<1e-8);
        assert.ok(s.x>0&&s.x<10&&s.z>0&&s.z<8);
        assert.deepEqual(s.artwork.uv,[0,0,1,1]);
    }
    assert.equal(JSON.stringify(layout),original);
});
test('panels come from the represented layout and absent walls do not create geometry', () => {
    const panels=[[{x:0,z:0},{x:1,z:0},{x:1,z:1}]];
    assert.equal(walls.panels({extensions:{facilityPerimeterWalls:{version:1,panels}}}),panels);
    assert.deepEqual(walls.panels({}),[]);
});
test('read-only, busy, conflicted and preview states cannot edit walls', () => {
    let state={loaded:true};
    const workspace={capabilities:{manualAuthoring:true},session:{getState:()=>state}};
    assert.equal(walls.canEdit(workspace),true);
    for(const field of ['busy','conflict','generatedDraft','layoutProposal','placementAlternatives']) {
        state={loaded:true,[field]:true}; assert.equal(walls.canEdit(workspace),false,field);
    }
    state={loaded:true};workspace.constructionPreview={};assert.equal(walls.canEdit(workspace),false);
    workspace.constructionPreview=null;workspace.generationPlanningView={activeLayout:()=>({})};
    assert.equal(walls.canEdit(workspace),false);
    workspace.generationPlanningView=null;workspace.capabilities.manualAuthoring=false;
    assert.equal(walls.canEdit(workspace),false);
});
