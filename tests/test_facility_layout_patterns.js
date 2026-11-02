'use strict';

const assert = require('assert');
const path = require('path');
const patterns = require('../static/facility_layout_patterns.js');
const kf4Strategies = require(path.join(
    __dirname,
    'fixtures',
    'facility_layout',
    'cell_intelligence',
    'kf4-strategy-fixtures.json'
));

let checks = 0;

function check(name, fn) {
    fn();
    checks += 1;
    process.stdout.write(`PASS ${name}\n`);
}

function near(actual, expected, epsilon) {
    assert.ok(
        Math.abs(actual - expected) <= (epsilon || 1e-6),
        `${actual} is not near ${expected}`
    );
}

function placement(id, x, z, width, depth, mode) {
    return {
        placementId: id,
        assetId: `asset-${id}`,
        assetDefinitionRevision: `rev-${id}`,
        transform: {
            position: { x, y: 0, z },
            quaternion: { x: 0, y: 0, z: 0, w: 1 },
            scale: 1,
        },
        positionMode: mode || 'manual',
        metadata: {},
        dimensions: { width, depth },
    };
}

function catalogFor(values) {
    return values.map(item => ({
        assetId: item.assetId,
        assetDefinitionRevision: item.assetDefinitionRevision,
        width: item.dimensions.width,
        depth: item.dimensions.depth,
        height: item.dimensions.height || 1.5,
    }));
}

function fixture() {
    const placements = [
        placement('mill', 2, 2, 2.4, 2.1),
        placement('bench', 5, 2, 1.8, 0.8),
        placement('rack', 4, 5, 3.2, 0.7),
    ];
    return {
        layout: {
            placements,
            floorMarkings: [{
                markingId: 'fm-flow',
                markingType: 'direction_arrow',
                width: 0.8,
                depth: 1.6,
                transform: {
                    position: { x: 3, y: 0, z: 3 },
                    rotationDegrees: 0,
                },
                positionMode: 'manual',
            }],
            zones: [{
                zoneId: 'zone-cell',
                zoneType: 'workcell',
                label: 'Machining cell',
                floorElevation: 0,
                boundary: [
                    { x: 0, z: 0 },
                    { x: 7, z: 0 },
                    { x: 7, z: 6 },
                    { x: 0, z: 6 },
                ],
            }],
        },
        catalog: catalogFor(placements),
    };
}

check('selected zone expands to contained equipment and floor markings', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['zone-cell'],
        { expandZones: true, includeZones: true }
    );
    assert.deepStrictEqual(
        seed.map(item => item.id),
        ['zone-cell', 'mill', 'bench', 'rack', 'fm-flow']
    );
});

check('linear pattern count includes the mixed-object seed', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['mill', 'fm-flow'],
        { expandZones: true, includeZones: true }
    );
    const result = patterns.buildLinearPattern(seed, {
        count: 4,
        pitch: 6,
        angleDegrees: 0,
    });
    assert.strictEqual(result.copies.length, 6);
    assert.deepStrictEqual(
        result.copies.map(copy => copy.instanceIndex),
        [1, 1, 2, 2, 3, 3]
    );
    near(result.copies[0].position.x, 8);
    near(result.copies[1].position.x, 9);
    near(result.guide.end.x - result.guide.start.x, 18);
});

check('linear pattern preserves all relative cell geometry', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['zone-cell'],
        { expandZones: true, includeZones: true }
    );
    const result = patterns.buildLinearPattern(seed, {
        count: 2,
        pitch: 10,
        angleDegrees: 90,
    });
    const mill = result.copies.find(copy => copy.sourceId === 'mill');
    const bench = result.copies.find(copy => copy.sourceId === 'bench');
    near(bench.position.x - mill.position.x, 3);
    near(bench.position.z - mill.position.z, 0);
    const zone = result.copies.find(copy => copy.sourceId === 'zone-cell');
    assert.strictEqual(zone.boundary.length, 4);
    near(zone.boundary[0].x, 0);
    near(zone.boundary[0].z, -10);
});

check('vertical stack uses authoritative height and emits stack semantics', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['rack'],
        { includeZones: false }
    );
    const result = patterns.buildVerticalStack(seed, {
        count: 4,
        gap: 0.1,
        stackId: 'stack-test-rack',
    });
    assert.strictEqual(result.mode, 'vertical-stack');
    assert.strictEqual(result.copies.length, 3);
    result.copies.forEach((copy, index) => {
        near(copy.position.y, [1.6, 3.2, 4.8][index]);
    });
    assert.deepStrictEqual(
        result.copies.map(copy => copy.snapRelationship.level),
        [1, 2, 3]
    );
    assert.strictEqual(
        result.relationships[0].snapRelationship.level,
        0
    );
    near(result.guide.totalHeightMeters, 6.3);
});

check('surface stack packs three distinct items in one support local frame', () => {
    const support = placement('table', 10, 8, 3.2, 1.8);
    support.dimensions.height = 0.8;
    const computer = placement('computer', 0, 0, 0.45, 0.35);
    computer.dimensions.height = 0.5;
    const keyboard = placement('keyboard', 0, 0, 0.55, 0.2);
    keyboard.dimensions.height = 0.04;
    const mouse = placement('mouse', 0, 0, 0.12, 0.08);
    mouse.dimensions.height = 0.04;
    const values = [support, computer, keyboard, mouse];
    const seed = patterns.collectSelection(
        { placements: values, zones: [], floorMarkings: [] },
        catalogFor(values),
        values.map(item => item.placementId),
        { includeZones: false }
    );
    const result = patterns.buildSurfaceStack(seed, {
        supportPlacementId: 'table',
        side: 'above',
        gap: 0,
        itemGap: 0.1,
        inset: 0.1,
    });
    assert.strictEqual(result.mode, 'surface-stack');
    assert.strictEqual(result.moves.length, 3);
    assert.strictEqual(result.relationships.length, 3);
    assert.strictEqual(new Set(result.relationships.map(item => (
        item.snapRelationship.supportPlacementId
    ))).size, 1);
    assert.strictEqual(new Set(result.relationships.map(item => (
        JSON.stringify(item.snapRelationship.localPosition)
    ))).size, 3);
    result.moves.forEach(move => near(move.position.y, 0.8));
});

check('surface stack follows a rotated support and can hang below it', () => {
    const support = placement('rotated-table', 4, 6, 2, 2);
    support.dimensions.height = 1;
    support.transform.quaternion = {
        x: 0,
        y: Math.SQRT1_2,
        z: 0,
        w: Math.SQRT1_2,
    };
    const device = placement('device', 0, 0, 0.5, 0.5);
    device.dimensions.height = 0.25;
    const values = [support, device];
    const seed = patterns.collectSelection(
        { placements: values, zones: [], floorMarkings: [] },
        catalogFor(values),
        ['rotated-table', 'device'],
        { includeZones: false }
    );
    const result = patterns.buildSurfaceStack(seed, {
        supportPlacementId: 'rotated-table',
        side: 'below',
        gap: 0.1,
        inset: 0.1,
    });
    near(result.moves[0].position.y, 0.65);
    assert.strictEqual(result.relationships[0].snapRelationship.side, 'below');
    assert.strictEqual(result.moves[0].rotationDegrees, 90);
});

check('surface stack honors a catalog-defined support frame and allowed side', () => {
    const support = placement('defined-table', 5, 4, 2, 1);
    support.dimensions.height = 1.4;
    const device = placement('defined-device', 0, 0, 0.4, 0.2);
    device.dimensions.height = 0.25;
    const values = [support, device];
    const catalog = catalogFor(values);
    catalog[0].supportSurfaces = [{
        surfaceId: 'worktop',
        label: 'Worktop',
        localFrame: {
            origin: { x: 0.1, y: 0.72, z: -0.2 },
            xAxis: { x: 1, y: 0, z: 0 },
            zAxis: { x: 0, y: 0, z: 1 },
            normal: { x: 0, y: 1, z: 0 },
        },
        bounds: {
            minimumX: -0.6,
            maximumX: 0.6,
            minimumZ: -0.3,
            maximumZ: 0.3,
        },
        allowedSides: ['above'],
        evidenceStatus: 'derived',
    }];
    const seed = patterns.collectSelection(
        { placements: values, zones: [], floorMarkings: [] },
        catalog,
        ['defined-table', 'defined-device'],
        { includeZones: false }
    );
    const result = patterns.buildSurfaceStack(seed, {
        supportPlacementId: 'defined-table',
        surfaceId: 'worktop',
        side: 'above',
        gap: 0,
        itemGap: 0.05,
        inset: 0.05,
    });
    near(result.moves[0].position.y, 0.72);
    near(result.relationships[0].snapRelationship.localPosition.x, -0.25);
    near(result.relationships[0].snapRelationship.localPosition.z, -0.35);
    assert.strictEqual(
        result.relationships[0].snapRelationship.surfaceSource,
        'asset_definition'
    );
    assert.throws(() => patterns.buildSurfaceStack(seed, {
        supportPlacementId: 'defined-table',
        surfaceId: 'worktop',
        side: 'below',
    }), /does not allow placement/);
});

check('surface stack transforms packing through a rotated local surface frame', () => {
    const support = placement('rotated-table', 10, 8, 4, 2);
    support.dimensions.height = 1.2;
    const device = placement('rotated-device', 0, 0, 0.4, 0.2);
    device.dimensions.height = 0.25;
    const catalog = catalogFor([support, device]);
    catalog[0].supportSurfaces = [{
        surfaceId: 'side-worktop',
        label: 'Side worktop',
        localFrame: {
            origin: { x: 0.5, y: 0.7, z: -0.25 },
            xAxis: { x: 0, y: 0, z: -1 },
            zAxis: { x: 1, y: 0, z: 0 },
            normal: { x: 0, y: 1, z: 0 },
        },
        bounds: {
            minimumX: -0.6,
            maximumX: 0.6,
            minimumZ: -0.3,
            maximumZ: 0.3,
        },
        allowedSides: ['above'],
        evidenceStatus: 'derived',
    }];
    const seed = patterns.collectSelection(
        { placements: [support, device], zones: [], floorMarkings: [] },
        catalog,
        ['rotated-table', 'rotated-device'],
        { includeZones: false }
    );
    const result = patterns.buildSurfaceStack(seed, {
        supportPlacementId: 'rotated-table',
        surfaceId: 'side-worktop',
        side: 'above',
        inset: 0.05,
    });
    near(result.relationships[0].snapRelationship.localPosition.x, 0.35);
    near(result.relationships[0].snapRelationship.localPosition.z, 0.1);
    near(result.relationships[0].snapRelationship.localRotationDegrees, 90);
    near(result.moves[0].position.x, 10.35);
    near(result.moves[0].position.z, 8.1);
    near(result.moves[0].rotationDegrees, 90);
});

check('full circular pattern omits the duplicate 360-degree endpoint', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['mill'],
        { includeZones: false }
    );
    const result = patterns.buildCircularPattern(seed, {
        count: 4,
        centerX: 0,
        centerZ: 2,
        sweepDegrees: 360,
        rotateWithPattern: true,
    });
    assert.strictEqual(result.copies.length, 3);
    assert.strictEqual(result.guide.stepDegrees, 90);
    near(result.copies[0].position.x, 0);
    near(result.copies[0].position.z, 0);
    near(result.copies[0].rotationDegrees, 90);
    near(result.copies[2].position.x, 0);
    near(result.copies[2].position.z, 4);
});

check('partial circular pattern includes both arc endpoints', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['mill'],
        { includeZones: false }
    );
    const result = patterns.buildCircularPattern(seed, {
        count: 3,
        centerX: 0,
        centerZ: 2,
        sweepDegrees: 180,
        rotateWithPattern: false,
    });
    assert.strictEqual(result.guide.stepDegrees, 90);
    near(result.copies[1].position.x, -2);
    near(result.copies[1].position.z, 2);
    near(result.copies[1].rotationDegrees, 0);
});

check('rectangular perimeter repeats a guarding module around four sides', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['bench'],
        { includeZones: false }
    );
    const result = patterns.buildRectangularPerimeter(seed, {
        shape: 'rectangle',
        widthCount: 3,
        depthCount: 2,
        clearGap: 0,
        angleDegrees: 0,
    });
    assert.strictEqual(result.mode, 'perimeter');
    assert.strictEqual(result.count, 10);
    assert.strictEqual(result.copies.length, 9);
    assert.deepStrictEqual(
        result.copies.reduce((counts, copy) => {
            counts[copy.perimeterSide] = (counts[copy.perimeterSide] || 0) + 1;
            return counts;
        }, {}),
        { south: 2, east: 2, north: 3, west: 2 }
    );
    near(result.guide.width, 5.402);
    near(result.guide.depth, 3.601);
    near(result.copies[0].position.x, 6.801);
    near(result.copies[0].position.z, 2);
    near(result.copies[2].position.x, 9.903);
    near(result.copies[2].position.z, 2.9);
    near(result.copies[2].rotationDegrees, 270);
});

check('perimeter pattern propagates a multi-item module and validates gap', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['mill', 'bench'],
        { includeZones: false }
    );
    const result = patterns.buildRectangularPerimeter(seed, {
        shape: 'square',
        widthCount: 2,
        clearGap: 0.5,
    });
    assert.strictEqual(result.guide.widthCount, 2);
    assert.strictEqual(result.guide.depthCount, 2);
    assert.strictEqual(result.copies.length, 14);
    assert.strictEqual(
        result.copies.filter(copy => copy.instanceIndex === 1).length,
        2
    );
    assert.throws(
        () => patterns.buildRectangularPerimeter(seed, {
            widthCount: 2,
            depthCount: 2,
            clearGap: -0.01,
        }),
        /must not be negative/
    );
});

check('perimeter uses authoritative AABB and follows a guarding panels long axis', () => {
    const data = fixture();
    data.catalog.push({
        assetId: 'guard',
        assetDefinitionRevision: 'guard-r1',
        definition: {
            geometry: {
                aabb: {
                    minimum: { x: -0.075, y: 0, z: -0.425 },
                    maximum: { x: 0.075, y: 1.7, z: 0.425 },
                },
            },
        },
    });
    data.layout.placements.push({
        placementId: 'guard-1',
        assetId: 'guard',
        assetDefinitionRevision: 'guard-r1',
        positionMode: 'manual',
        transform: {
            position: { x: 5, y: 0, z: 5 },
            quaternion: { x: 0, y: 0, z: 0, w: 1 },
            scale: 1,
        },
    });
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['guard-1'],
        { includeZones: false }
    );
    assert.strictEqual(seed[0].width, 0.15);
    assert.strictEqual(seed[0].depth, 0.85);
    const result = patterns.buildRectangularPerimeter(seed, {
        widthCount: 4,
        depthCount: 3,
        clearGap: 0,
        angleDegrees: 0,
    });
    assert.strictEqual(result.guide.requestedAngleDegrees, 0);
    assert.strictEqual(result.guide.angleDegrees, 90);
    assert.strictEqual(result.guide.clearGap, 0);
    assert.strictEqual(result.guide.effectiveClearGap, 0.001);
    near(result.guide.width, 3.403);
    near(result.guide.depth, 2.552);
    const positions = result.copies.map(copy => (
        copy.position.x.toFixed(5) + ':' + copy.position.z.toFixed(5)
    ));
    assert.strictEqual(new Set(positions).size, positions.length);
});

check('mirror reflects a placement and its orientation across a grid axis', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['mill'],
        { includeZones: false }
    );
    const result = patterns.buildMirror(seed, {
        axisStart: { x: 5, z: 0 },
        axisEnd: { x: 5, z: 10 },
    });
    assert.strictEqual(result.mode, 'mirror');
    assert.strictEqual(result.copies.length, 1);
    near(result.copies[0].position.x, 8);
    near(result.copies[0].position.z, 2);
    // No reviewed side: its north side (+Z, a model file's front) is kept as the
    // mirror image, so across a north-south line the copy does not turn.
    near(result.copies[0].rotationDegrees, 0);
    assert.strictEqual(result.copies[0].mirrored, true);
    assert.deepStrictEqual(result.guide, {
        kind: 'mirror',
        start: { x: 5, z: 0 },
        end: { x: 5, z: 10 },
    });
});

check('mirror keeps a machine\'s operator side, else its front, else its north side', () => {
    // A turn cannot mirror a model, so the copy turns to keep that side as the
    // mirror image of the original's.
    const data = fixture();
    const index = data.catalog.findIndex(item => item.assetId === 'asset-mill');
    const record = data.catalog[index];
    const mill = data.layout.placements.find(item => item.placementId === 'mill');
    mill.transform.quaternion = { x: 0, y: -Math.SQRT1_2, z: 0, w: Math.SQRT1_2 };
    const northSouth = { axisStart: { x: 5, z: 0 }, axisEnd: { x: 5, z: 10 } };
    const eastWest = { axisStart: { x: 0, z: 5 }, axisEnd: { x: 10, z: 5 } };
    function mirrored(axis) {
        const seed = patterns.collectSelection(
            data.layout,
            data.catalog,
            ['mill'],
            { includeZones: false }
        );
        return [seed[0].facingSideDegrees, patterns.buildMirror(seed, axis).copies[0]];
    }
    // Operator side south: turned 270 it faces east, and its mirror image across
    // a north-south line faces west (the old turn left it facing east). Across an
    // east-west line it still faces east.
    record.facilitySemantics = { functionalSides: {
        front: { side: 'north' },
        operator: { side: 'south', evidenceStatus: 'inferred' },
    } };
    assert.strictEqual(mirrored(northSouth)[0], 180);
    near(mirrored(northSouth)[1].rotationDegrees, 90);
    near(mirrored(eastWest)[1].rotationDegrees, 270);
    // No operator side: the front. Front west, turned 270, faces south, and
    // stays south across a north-south line.
    record.facilitySemantics = { functionalSides: { front: { side: 'west' } } };
    assert.strictEqual(mirrored(northSouth)[0], 270);
    near(mirrored(northSouth)[1].rotationDegrees, 270);
    // The workspace's catalog keeps the catalog record as source.
    data.catalog[index] = {
        assetId: record.assetId,
        assetDefinitionRevision: record.assetDefinitionRevision,
        width: record.width,
        depth: record.depth,
        height: record.height,
        source: { facilitySemantics: record.facilitySemantics },
    };
    assert.strictEqual(mirrored(northSouth)[0], 270);
    near(mirrored(northSouth)[1].rotationDegrees, 270);
    // No reviewed side: the north side. Turned 270 it faces west; mirrored, east.
    data.catalog[index].source = {};
    assert.strictEqual(mirrored(northSouth)[0], null);
    near(mirrored(northSouth)[1].rotationDegrees, 90);
});

check('mirror copies a complete mixed cell across a construction line', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['zone-cell'],
        { expandZones: true, includeZones: true }
    );
    const result = patterns.buildMirror(seed, {
        axisStart: { x: 0, z: 0 },
        axisEnd: { x: 10, z: 10 },
    });
    assert.strictEqual(result.copies.length, 5);
    const mill = result.copies.find(copy => copy.sourceId === 'mill');
    const marking = result.copies.find(copy => copy.sourceId === 'fm-flow');
    const zone = result.copies.find(copy => copy.sourceId === 'zone-cell');
    near(mill.position.x, 2);
    near(mill.position.z, 2);
    // Its north side, mirrored across a line at 45 degrees, faces east.
    near(mill.rotationDegrees, 90);
    near(marking.position.x, 3);
    near(marking.position.z, 3);
    // A marking keeps its east side as the mirror image, as before.
    near(marking.rotationDegrees, 270);
    assert.strictEqual(zone.boundary.length, 4);
    near(zone.boundary[0].x, 6);
    near(zone.boundary[0].z, 0);
    near(zone.boundary[3].x, 0);
    near(zone.boundary[3].z, 0);
});

check('mirror rejects a degenerate construction axis', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['mill'],
        { includeZones: false }
    );
    assert.throws(
        () => patterns.buildMirror(seed, {
            axisStart: { x: 2, z: 2 },
            axisEnd: { x: 2, z: 2 },
        }),
        /must be different/
    );
});

check('U-cell layout arranges heterogeneous equipment on three sides', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['mill', 'bench', 'rack'],
        { includeZones: false }
    );
    const result = patterns.buildCellLayout(seed, {
        shape: 'u',
        width: 10,
        depth: 8,
        gap: 1,
        orientation: 'face-center',
    });
    assert.strictEqual(result.moves.length, 3);
    const center = result.guide.center;
    near(result.moves[0].position.x,
        center.x - result.guide.usableWidth / 2);
    near(result.moves[0].position.z,
        center.z - result.guide.usableDepth / 2);
    near(result.moves[1].position.x, center.x);
    near(result.moves[1].position.z,
        center.z + result.guide.usableDepth / 2);
    near(result.moves[2].position.x,
        center.x + result.guide.usableWidth / 2);
    near(result.moves[2].position.z,
        center.z - result.guide.usableDepth / 2);
    result.moves.forEach((move, index) => {
        const item = seed[index];
        const radius = Math.hypot(item.width, item.depth) / 2;
        assert.ok(
            Math.abs(move.position.x - center.x) + radius
                <= result.guide.width / 2 + 1e-6
        );
        assert.ok(
            Math.abs(move.position.z - center.z) + radius
                <= result.guide.depth / 2 + 1e-6
        );
    });
    assert.ok(result.moves.every(move => Number.isFinite(move.rotationDegrees)));
});

check('cell face center turns the side a machine works from to the centre', () => {
    // The user's circle of mills (2026-11-01): face center turned each model's
    // +Z to the centre, so a mill working from its south side faced out.
    const data = fixture();
    const record = data.catalog.find(item => item.assetId === 'asset-mill');
    function apart(first, second) {
        return Math.abs((((first - second) % 360) + 540) % 360 - 180);
    }
    function mill(orientation) {
        const seed = patterns.collectSelection(
            data.layout,
            data.catalog,
            ['mill', 'bench', 'rack'],
            { includeZones: false }
        );
        const result = patterns.buildCellLayout(seed, {
            shape: 'loop', width: 10, depth: 8, gap: 1, orientation: orientation,
        });
        const move = result.moves[seed.findIndex(item => item.id === 'mill')];
        const center = result.guide.center;
        const toward = Math.atan2(
            center.x - move.position.x,
            center.z - move.position.z
        ) * 180 / Math.PI;
        return { rotation: move.rotationDegrees, toward: toward };
    }
    // Turned R, a side at heading h in the model's own axes faces R + h.
    record.facilitySemantics = { functionalSides: {
        front: { side: 'north' },
        operator: { side: 'south', evidenceStatus: 'inferred' },
    } };
    let turned = mill('face-center');
    assert.ok(apart(turned.rotation + 180, turned.toward) < 1e-6);
    turned = mill('face-outward');
    assert.ok(apart(turned.rotation + 180, turned.toward + 180) < 1e-6);
    record.facilitySemantics = { functionalSides: { front: { side: 'west' } } };
    turned = mill('face-center');
    assert.ok(apart(turned.rotation + 270, turned.toward) < 1e-6);
    delete record.facilitySemantics;
    turned = mill('face-center');
    assert.ok(apart(turned.rotation, turned.toward) < 1e-6);
    near(patterns.cellFacingSideDegrees({ kind: 'floor-marking', facingSideDegrees: 90 }), 0);
});

check('U-cell opening can be inverted without changing its center or footprint', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['mill', 'bench', 'rack'],
        { includeZones: false }
    );
    const normal = patterns.buildCellLayout(seed, {
        shape: 'u', width: 10, depth: 8, gap: 1,
    });
    const inverted = patterns.buildCellLayout(seed, {
        shape: 'u', width: 10, depth: 8, gap: 1, invertU: true,
    });
    assert.strictEqual(inverted.inverted, true);
    assert.strictEqual(inverted.guide.inverted, true);
    assert.deepStrictEqual(inverted.guide.center, normal.guide.center);
    assert.strictEqual(inverted.guide.width, normal.guide.width);
    assert.strictEqual(inverted.guide.depth, normal.guide.depth);
    normal.moves.forEach((move, index) => {
        near(inverted.moves[index].position.x, move.position.x);
        near(
            inverted.moves[index].position.z,
            2 * normal.guide.center.z - move.position.z
        );
    });
});

check('swap exchanges two placements without changing their orientation', () => {
    const data = fixture();
    const result = patterns.buildSwap(
        data.layout,
        data.catalog,
        ['mill', 'bench']
    );
    assert.strictEqual(result.mode, 'swap');
    assert.strictEqual(result.moves.length, 2);
    const mill = result.moves.find(move => move.sourceId === 'mill');
    const bench = result.moves.find(move => move.sourceId === 'bench');
    assert.deepStrictEqual(mill.position, { x: 5, y: 0, z: 2 });
    assert.deepStrictEqual(bench.position, { x: 2, y: 0, z: 2 });
    assert.strictEqual(mill.rotationDegrees, 0);
    assert.strictEqual(bench.rotationDegrees, 0);
});

check('swap exchanges complete zone cells with their contained objects', () => {
    const data = fixture();
    const lathe = placement('lathe', 12, 2, 2, 1);
    data.layout.placements.push(lathe);
    data.catalog.push(...catalogFor([lathe]));
    data.layout.zones.push({
        zoneId: 'zone-lathe',
        zoneType: 'workcell',
        label: 'Lathe cell',
        floorElevation: 0,
        boundary: [
            { x: 10, z: 0 }, { x: 16, z: 0 },
            { x: 16, z: 6 }, { x: 10, z: 6 },
        ],
    });
    const result = patterns.buildSwap(
        data.layout,
        data.catalog,
        ['zone-cell', 'zone-lathe']
    );
    const firstZone = result.moves.find(move => move.sourceId === 'zone-cell');
    const secondZone = result.moves.find(move => move.sourceId === 'zone-lathe');
    const mill = result.moves.find(move => move.sourceId === 'mill');
    const latheMove = result.moves.find(move => move.sourceId === 'lathe');
    assert.strictEqual(result.moves.length, 7);
    assert.deepStrictEqual(firstZone.position, { x: 13, y: 0, z: 3 });
    assert.deepStrictEqual(secondZone.position, { x: 3.5, y: 0, z: 3 });
    near(mill.position.x, 11.5);
    near(latheMove.position.x, 2.5);
    assert.deepStrictEqual(firstZone.boundary[0], { x: 9.5, z: 0 });
    assert.deepStrictEqual(secondZone.boundary[0], { x: 0.5, z: 0 });
});

check('all manufacturing cell presets return one deterministic move per item', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['mill', 'bench', 'rack', 'fm-flow'],
        { includeZones: false }
    );
    assert.deepStrictEqual(patterns.cellShapes, kf4Strategies.strategyIds);
    patterns.cellShapes.forEach(shape => {
        const first = patterns.buildCellLayout(seed, {
            shape,
            ...kf4Strategies.browserValidOptions,
        });
        const second = patterns.buildCellLayout(seed, {
            shape,
            ...kf4Strategies.browserValidOptions,
        });
        assert.strictEqual(first.moves.length, seed.length, shape);
        assert.deepStrictEqual(first, second, shape);
    });
});

check('locked equipment cannot be rearranged but can remain a pattern seed', () => {
    const data = fixture();
    data.layout.placements[0].positionMode = 'locked';
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['mill', 'bench'],
        { includeZones: false }
    );
    assert.throws(
        () => patterns.buildCellLayout(seed, { shape: 'line' }),
        /unlock 'mill'/
    );
    assert.strictEqual(
        patterns.buildLinearPattern(seed, { count: 2, pitch: 4 }).copies.length,
        2
    );
});

check('unsafe pattern sizes fail before producing operations', () => {
    const data = fixture();
    const seed = patterns.collectSelection(
        data.layout,
        data.catalog,
        ['zone-cell'],
        { includeZones: true }
    );
    assert.throws(
        () => patterns.buildLinearPattern(seed, { count: 51, pitch: 2 }),
        /between 2 and 50/
    );
    assert.throws(
        () => patterns.buildCellLayout(seed, {
            shape: 'u', width: 3, depth: 3, gap: 1,
        }),
        /contain the selected equipment footprints/
    );
});

process.stdout.write(`${checks}/${checks} facility pattern checks passed\n`);
