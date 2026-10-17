'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {assertArtworkReady}=require('./artwork.cjs');
const source={artworkId:'a',imagePath:'/a.png'};
const layout={extensions:{facilityPerimeterWalls:{settings:{exteriorFinish:{fittedArtworks:[source]}}}}};
const ready={...source,status:'ready',visible:true};
test('artwork gate accepts every saved graphic loaded and visible',()=>{
    assert.equal(assertArtworkReady(layout,{exteriorArtwork:[ready]}).ready,1);
});
test('artwork gate refuses absent, failed, hidden or mismatched graphics',()=>{
    for(const records of [[],[{...ready,status:'failed'}],[{...ready,status:'loading'}],
        [{...ready,visible:false}],[{...ready,imagePath:'/old.png'}],[{...ready,artworkId:'wrong'}]]){
        assert.throws(()=>assertArtworkReady(layout,{exteriorArtwork:records}));
    }
});
