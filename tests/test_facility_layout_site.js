'use strict';

// Site tab helpers (site context, SC1): the property frame is +X east, +Z north.
const assert = require('assert');
const path = require('path');
const test = require('node:test');

const site = require(path.join(__dirname, '..', 'static', 'facility_layout_site.js'));

function close(actual, expected, tolerance) {
    assert.ok(Math.abs(actual - expected) <= (tolerance || 1e-9), actual + ' != ' + expected);
}

test('a building pose maps the layout frame into the property frame and back', () => {
    const pose = { x: 12, z: -5, bearingDegrees: 30 };
    [[0, 0], [48, 0], [48, 32], [3.5, 17.25]].forEach(([x, z]) => {
        const property = site.buildingToProperty(pose, x, z);
        const back = site.propertyToBuilding(pose, property.x, property.z);
        close(back.x, x);
        close(back.z, z);
    });
    // Plan north turned to a bearing of 90 degrees points east.
    const turned = site.buildingToProperty({ x: 0, z: 0, bearingDegrees: 90 }, 0, 10);
    close(turned.x, 10);
    close(turned.z, 0);
});

test('the default pose centres the building on the site origin', () => {
    const layout = { extensions: { facilityPlan: { widthMeters: 48, depthMeters: 32 } } };
    const context = { georeference: { originLatitude: 45, originLongitude: -93 },
        buildingPose: { x: -24, z: -16, bearingDegrees: 0 } };
    assert.deepStrictEqual(site.buildingOutline(layout, context),
        [{ x: -24, z: -16 }, { x: 24, z: -16 }, { x: 24, z: 16 }, { x: -24, z: 16 }]);
});

test('a point on the photo maps to latitude and longitude by proportion', () => {
    const image = {
        corners: [{ x: -200, z: -150 }, { x: 200, z: -150 }, { x: 200, z: 150 }, { x: -200, z: 150 }],
        geoBounds: { south: 44.0, west: -93.2, north: 44.1, east: -93.0 },
    };
    const centre = site.latLonAt(image, 0, 0);
    close(centre.latitude, 44.05);
    close(centre.longitude, -93.1);
    const northEast = site.latLonAt(image, 200, 150);
    close(northEast.latitude, 44.1);
    close(northEast.longitude, -93.0);
    assert.strictEqual(site.latLonAt(image, 250, 0), null);
});

test('coordinates parse from text and scale bars use round lengths', () => {
    assert.deepStrictEqual(site.parseCoordinates('44.9778, -93.2650'), { latitude: 44.9778, longitude: -93.265 });
    assert.deepStrictEqual(site.parseCoordinates('44.9778 -93.2650'), { latitude: 44.9778, longitude: -93.265 });
    assert.strictEqual(site.parseCoordinates('95, 10'), null);
    assert.strictEqual(site.parseCoordinates('somewhere'), null);
    assert.strictEqual(site.niceLength(37), 50);
    assert.strictEqual(site.niceLength(120), 200);
    assert.strictEqual(site.niceLength(0.7), 1);
});

test('only a layout with a georeference has a site', () => {
    assert.strictEqual(site.siteContextOf({ extensions: {} }), null);
    assert.strictEqual(site.siteContextOf(null), null);
    const value = { version: 1, georeference: { originLatitude: 1, originLongitude: 2 } };
    assert.strictEqual(site.siteContextOf({ extensions: { facilitySiteContext: value } }), value);
});

test('typed property vertices preserve edge order and reject malformed coordinates', () => {
    assert.deepStrictEqual(site.parseBoundary('0,0\n0,20\n30,20\n30,0'),
        [{x:0,z:0},{x:0,z:20},{x:30,z:20},{x:30,z:0}]);
    assert.throws(() => site.parseBoundary('0,0\nno,20\n30,20'));
    assert.throws(() => site.parseBoundary('0,0\n10,10'));
});
test('moving a boundary vertex retains entrance position along its edge without mutation', () => {
    const p = {boundary:[{x:0,z:0},{x:10,z:0},{x:10,z:10}], streetEdges:[0],rearEdges:[],
        entrances:[{entranceId:'a',edgeIndex:0,x:5,z:0,widthMeters:2,use:'cars'}]};
    const before=JSON.stringify(p);
    const changed=site.replaceBoundary(p,[{x:0,z:0},{x:20,z:0},{x:10,z:10}]);
    assert.equal(JSON.stringify(p),before);
    assert.equal(changed.entrances[0].x,10);
    const replaced=site.replaceBoundary(p,[{x:0,z:0},{x:20,z:0},{x:20,z:20},{x:0,z:20}]);
    assert.deepStrictEqual(replaced.entrances,[]);
    assert.deepStrictEqual(replaced.streetEdges,[]);
});
test('shared polygon sketch preserves plan Y values and suppresses duplicate clicks', () => {
    const points=[];
    site.appendPolygonVertex(points,{x:0,y:0,z:0});site.appendPolygonVertex(points,{x:0,y:0,z:0});
    site.appendPolygonVertex(points,{x:10,y:0,z:0});
    assert.deepStrictEqual(points,[{x:0,y:0,z:0},{x:10,y:0,z:0}]);
});
test('site surfaces map property vertices back to the building without mutating document geometry', () => {
    const layout={coordinateFrame:{floorElevation:2},extensions:{facilitySiteContext:{georeference:{},
        buildingPose:{x:10,z:20,bearingDegrees:90},areas:[{areaId:'lot',label:'Lot',surface:'grass',
            boundary:[{x:10,z:20},{x:20,z:20},{x:20,z:10}]}]}}};
    const before=JSON.stringify(layout), surfaces=site.areaSurfaces(layout);
    close(surfaces[0].boundary[1].x,0);close(surfaces[0].boundary[1].z,10);
    close(surfaces[0].elevation,1.975);assert.equal(surfaces[0].material,'turf');
    assert.equal(JSON.stringify(layout),before);assert.deepStrictEqual(site.areaSurfaces({}),[]);
});
test('traced existing pavement is a reference outline, not a 3D ground surface', () => {
    const area=(areaId,kind,surface,size)=>({areaId,label:areaId,kind,surface,
        boundary:[{x:0,z:0},{x:size,z:0},{x:size,z:size}]});
    const layout={extensions:{facilitySiteContext:{georeference:{},buildingPose:{x:0,z:0,bearingDegrees:0},
        areas:[area('area-existing-pavement','existing_pavement','asphalt',50),area('area-truck-court','truck_court','concrete',10)]}}};
    assert.deepStrictEqual(site.areaSurfaces(layout).map(s=>s.surfaceId),['area-truck-court']);
});

test('measuring gives metres and feet between two photo points', () => {
    close(site.measureDistance({ x: 1, z: 2 }, { x: 4, z: 6 }), 5);
    assert.strictEqual(site.formatDistance(7.5), '7.50 m (24.6 ft)');
    assert.strictEqual(site.formatDistance(238.707), '238.7 m (783.2 ft)');
    assert.strictEqual(site.formatDistance(1234.5), '1.234 km (4,050 ft)');
    assert.strictEqual(site.formatDistance(NaN), '');
});

test('road names sit on each road\'s longest stretch, upright, with a highway\'s route name', () => {
    const roads = [
        { label: '3rd St N (State Hwy 95)', kind: 'arterial', names: ['3rd St N', 'State Hwy 95'],
            line: [{ x: 0, z: 0 }, { x: 0, z: 10 }, { x: 0, z: 200 }] },
        { label: '4th Ave N', kind: 'local', names: ['4th Ave N'], line: [{ x: 100, z: 50 }, { x: -100, z: 50 }] },
        { label: 'Railroad', kind: 'railroad', names: [], line: [{ x: 5, z: 0 }, { x: 5, z: 100 }] },
        { label: 'Unnamed road', kind: 'local', names: [], line: [{ x: 0, z: 0 }, { x: 9, z: 9 }] },
    ];
    const labels = site.roadLabels(roads);
    assert.deepStrictEqual(labels.map(label => label.text), ['State Hwy 95', '4th Ave N']);
    const highway = labels[0];
    assert.deepStrictEqual([highway.x, highway.z, highway.angle], [0, 105, 90]);  // reads bottom to top
    assert.strictEqual(labels[1].angle, 0);  // drawn east to west, still reads left to right
});

test('a trace is summarised in acres, metres and the way its long side runs', () => {
    const text = site.traceSummary({ areaAcres: 5.2381, areaSquareMeters: 21196.3, lengthMeters: 229.4, widthMeters: 129.9,
        longAxisBearingDegrees: 88.1, perimeterMeters: 722.0, accuracyMeters: 1.5, touchesPhotoEdge: false });
    assert.strictEqual(text, 'Traced 5.24 ac (21,196 sq m), about 229 x 130 m, long side east-west, perimeter 722 m. '
        + 'Accurate to about 1.5 m. Existing pavement as seen on the photo, not a property line. '
        + 'Check the corners, then Apply area.');
    assert.match(site.traceSummary({ areaAcres: 1, areaSquareMeters: 4047, lengthMeters: 80, widthMeters: 50,
        longAxisBearingDegrees: 178, perimeterMeters: 260, accuracyMeters: 1.5, touchesPhotoEdge: true }),
    /long side north-south.*runs past the photo's edge/);
});

test('routes are drawn one line each way, on the right of travel, with arrowheads and the highway name', () => {
    const north = [{x:0,z:0},{x:0,z:100}];
    const right = site.offsetLine(north, 5), back = site.offsetLine(north.slice().reverse(), 5);
    close(right[0].x, 5); close(back[0].x, -5);  // heading north keeps to the east; heading south, to the west
    const arrows = site.arrowsAlong(north, 30, 2);
    assert.equal(arrows.length, 4);  // at 15, 45 and 75 m, and at the end
    close(arrows[arrows.length - 1][0].z, 100);  // the last one points to the end
    const roads = [{label:'St Croix Trl N (State Hwy 95, 3rd St N)', names:['St Croix Trl N','State Hwy 95','3rd St N']}];
    assert.equal(site.routeTarget({mainRoad:'St Croix Trl N (State Hwy 95, 3rd St N)'}, roads), 'State Hwy 95');
    assert.equal(site.routeTarget({mainRoad:'Main St'}, []), 'Main St');
});

test('an outgoing route is cut into dashes of the given length', () => {
    const pieces = site.dashes([{x:0,z:0},{x:20,z:0}], 7, 5);
    assert.equal(pieces.length, 2);  // 0-7 and 12-19
    close(pieces[0][pieces[0].length - 1].x, 7); close(pieces[1][0].x, 12); close(pieces[1][pieces[1].length - 1].x, 19);
    assert.equal(site.routeColor('cars'), '#38bdf8'); assert.equal(site.routeColor('unknown'), '#c084fc');
});
