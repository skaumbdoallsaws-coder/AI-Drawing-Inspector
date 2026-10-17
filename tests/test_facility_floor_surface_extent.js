const test=require('node:test');
const assert=require('node:assert/strict');
const {extent}=require('../static/facility_layout_floor_surfaces.js');
test('floor finish preview follows the rectangular plan without explicit ground',()=>{
    assert.deepEqual(extent({extensions:{facilityPlan:{widthMeters:60,depthMeters:30}}}),{minX:0,minZ:0,maxX:60,maxZ:30});
    assert.equal(extent({}),null);
});
test('outdoor extensions and negative coordinates remain visible in the preview',()=>{
    assert.deepEqual(extent({extensions:{facilityPlan:{widthMeters:60,depthMeters:30},facilityGround:{surfaces:[
        {minX:0,minZ:0,maxX:60,maxZ:30},{minX:-20,minZ:-15,maxX:0,maxZ:25}]}}}),
        {minX:-20,minZ:-15,maxX:60,maxZ:30});
});
