'use strict';
const assert = require('node:assert/strict');

function assertArtworkReady(layout, diagnostics) {
    const finish=layout.extensions?.facilityPerimeterWalls?.settings?.exteriorFinish||{};
    const expected=[...(finish.artworks||[]),...(finish.fittedArtworks||[])];
    const records=diagnostics.exteriorArtwork||[];
    assert.equal(records.length,expected.length,'Wall artwork count differs from saved layout');
    assert.equal(new Set(records.map(a=>a.artworkId)).size,records.length,'Duplicate artwork diagnostics');
    for(const source of expected){
        const record=records.find(a=>a.artworkId===source.artworkId);
        assert.ok(record,'Missing wall artwork: '+source.artworkId);
        assert.equal(record.imagePath,source.imagePath,'Wrong artwork image: '+source.artworkId);
        assert.equal(record.status,'ready','Artwork did not load: '+source.artworkId);
        assert.equal(record.visible,true,'Artwork is hidden: '+source.artworkId);
    }
    return {expected:expected.length,ready:records.length,records};
}
module.exports={assertArtworkReady};
