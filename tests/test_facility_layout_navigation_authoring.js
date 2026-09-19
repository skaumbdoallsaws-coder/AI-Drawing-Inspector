'use strict';

const assert = require('assert');
const navigation = require('../static/facility_layout_navigation_authoring.js');

let checks = 0;
function check(name, callback) {
    callback();
    checks += 1;
    process.stdout.write('PASS ' + name + '\n');
}

function layout() {
    return {
        placements: [{
            placementId: 'pl-operator-01',
            assetId: 'asset-operator',
            assetDefinitionRevision: 'a'.repeat(64),
            transform: {
                position: { x: 2, y: 0, z: 3 },
                quaternion: { x: 0, y: 0, z: 0, w: 1 },
                scale: 1,
            },
            metadata: { instanceLabel: 'Operator 01' },
        }, {
            placementId: 'pl-forklift-01',
            assetId: 'asset-forklift',
            assetDefinitionRevision: 'b'.repeat(64),
            transform: {
                position: { x: 10, y: 0, z: 3 },
                quaternion: { x: 0, y: 0, z: 0, w: 1 },
                scale: 1,
            },
            metadata: { instanceLabel: 'Forklift 01' },
        }, {
            placementId: 'pl-workbench-01',
            assetId: 'asset-workbench',
            assetDefinitionRevision: 'e'.repeat(64),
            transform: {
                position: { x: 7, y: 0, z: 6 },
                quaternion: { x: 0, y: 0, z: 0, w: 1 },
                scale: 1,
            },
            metadata: { instanceLabel: 'Worktable 01' },
        }],
        extensions: {},
    };
}

check('builds a closed operator loop bound to one existing placement', () => {
    const value = navigation.buildManualPathIntent(layout(), {
        actorPlacementId: 'pl-operator-01',
        points: [{ x: 2, z: 3 }, { x: 8, z: 3 }, { x: 8, z: 8 }],
        loopMode: 'closed_loop',
        direction: 'forward',
        baseRevision: 'c'.repeat(64),
    });
    assert.strictEqual(value.actorClass, 'pedestrian');
    assert.strictEqual(value.points.length, 4);
    assert.deepStrictEqual(value.points[0], value.points.at(-1));
    assert.strictEqual(
        value.facilityNavigation.movementPrograms[0].actorPlacementId,
        'pl-operator-01'
    );
    assert.strictEqual(
        value.facilityNavigation.manualPathConstraints[0].positionAuthority,
        'ui_authored'
    );
});

check('vehicle authoring refuses an unspecified vehicle profile', () => {
    assert.throws(() => navigation.buildManualPathIntent(layout(), {
        actorPlacementId: 'pl-forklift-01',
        points: [{ x: 10, z: 3 }, { x: 20, z: 3 }],
        loopMode: 'paired_lane_return',
        baseRevision: 'c'.repeat(64),
    }), /exact published vehicle-profile/);
});

check('vehicle authoring binds the exact supplied profile', () => {
    const value = navigation.buildManualPathIntent(layout(), {
        actorPlacementId: 'pl-forklift-01',
        actorClass: 'vehicle',
        actorProfileRef: {
            profileKind: 'vehicle',
            profileId: 'vp-forklift-one',
            profileRevision: 'd'.repeat(64),
        },
        points: [{ x: 10, z: 3 }, { x: 20, z: 3 }],
        loopMode: 'paired_lane_return',
        baseRevision: 'c'.repeat(64),
    });
    assert.deepStrictEqual(
        value.actorProfileRef,
        {
            profileKind: 'vehicle',
            profileId: 'vp-forklift-one',
            profileRevision: 'd'.repeat(64),
        }
    );
});

check('arc-length sampling gives the same geometric midpoint independent of segments', () => {
    const sampled = navigation.samplePathAtNormalizedTime([
        { x: 0, z: 0 },
        { x: 2, z: 0 },
        { x: 10, z: 0 },
    ], 0.5);
    assert.strictEqual(sampled.x, 5);
    assert.strictEqual(sampled.z, 0);
    assert.strictEqual(sampled.heading, 0);
    assert.strictEqual(sampled.distanceMeters, 5);
});

check('reverse insert and delete preserve exact waypoint coordinates', () => {
    const source = [{ x: 0, z: 0 }, { x: 4, z: 0 }, { x: 4, z: 4 }];
    assert.deepStrictEqual(navigation.reversePath(source), source.slice().reverse());
    const inserted = navigation.insertWaypoint(source, 0, { x: 2, z: 0 });
    assert.deepStrictEqual(inserted[1], { x: 2, z: 0 });
    assert.deepStrictEqual(navigation.deleteWaypoint(inserted, 1), source);
});

check('anchor authoring records UI authority and semantic use', () => {
    const result = navigation.addNavigationAnchor(layout(), {
        ownerPlacementId: 'pl-operator-01',
        anchorKind: 'fifo_output',
        position: { x: 7, z: 9 },
    });
    const anchor = result.facilityNavigation.anchors[0];
    assert.strictEqual(anchor.positionAuthority, 'ui_authored');
    assert.strictEqual(anchor.interactionKind, 'handoff');
    assert.deepStrictEqual(anchor.localPosition, { x: 7, z: 9 });
});

check('semantic intent uses existing identities and preserves authored geometry', () => {
    const first = navigation.addNavigationAnchor(layout(), {
        ownerPlacementId: 'pl-operator-01',
        anchorKind: 'actor_home',
        position: { x: 2, z: 3 },
    });
    const withFirst = layout();
    withFirst.extensions.facilityNavigation = first.facilityNavigation;
    const second = navigation.addNavigationAnchor(withFirst, {
        ownerPlacementId: 'pl-operator-01',
        anchorKind: 'station_operate',
        position: { x: 8, z: 3 },
    });
    const source = layout();
    source.routes = [{ routeId: 'rt-operator-spine' }];
    source.zones = [{ zoneId: 'zone-restricted' }];
    source.extensions.facilityNavigation = second.facilityNavigation;
    const authoredGeometry = JSON.stringify(
        source.extensions.facilityNavigation.anchors
    );

    const result = navigation.buildSemanticProgramIntent(source, {
        actorPlacementId: 'pl-operator-01',
        orderedAnchorIds: [
            first.navigationAnchorId,
            second.navigationAnchorId,
        ],
        loopMode: 'out_and_return',
        requiredRouteIds: ['rt-operator-spine'],
        forbiddenZoneIds: ['zone-restricted'],
        forbiddenRouteIds: [],
        baseRevision: 'c'.repeat(64),
    });
    const program = result.facilityNavigation.movementPrograms[0];
    assert.strictEqual(program.evidenceStatus, 'inferred');
    assert.strictEqual(program.reviewStatus, 'pending');
    assert.deepStrictEqual(program.requiredRouteIds, ['rt-operator-spine']);
    assert.deepStrictEqual(program.forbiddenZoneIds, ['zone-restricted']);
    assert.strictEqual(
        JSON.stringify(result.facilityNavigation.anchors),
        authoredGeometry
    );
    assert.strictEqual(JSON.stringify(result.semanticDiff).includes('"x"'), false);
    assert.strictEqual(JSON.stringify(result.semanticDiff).includes('"z"'), false);
});

check('automatic intent binds ordered destinations without authoring geometry', () => {
    const result = navigation.buildAutomaticProgramIntent(layout(), {
        actorPlacementId: 'pl-operator-01',
        orderedTargetPlacementIds: ['pl-workbench-01'],
        loopMode: 'task_cycle',
        baseRevision: 'c'.repeat(64),
    });
    const anchors = result.facilityNavigation.anchors;
    const program = result.facilityNavigation.movementPrograms[0];
    const target = anchors.find(item => (
        item.derivedPositionRef
        && item.derivedPositionRef.sourceKind === 'placement_access'
    ));

    assert.ok(target);
    assert.strictEqual(target.positionAuthority, 'derived');
    assert.strictEqual(target.localPosition, null);
    assert.strictEqual(target.derivedPositionRef.sourceId, 'pl-workbench-01');
    assert.strictEqual(
        target.derivedPositionRef.sourceRevision,
        'e'.repeat(64)
    );
    assert.deepStrictEqual(
        result.orderedTargetPlacementIds,
        ['pl-workbench-01']
    );
    assert.strictEqual(program.loopMode, 'task_cycle');
    assert.deepStrictEqual(program.manualPathConstraintIds, []);
    assert.strictEqual(JSON.stringify(result.semanticDiff).includes('"x"'), false);
    assert.strictEqual(JSON.stringify(result.semanticDiff).includes('"z"'), false);
});

process.stdout.write('Facility navigation authoring checks: '
    + checks + '/' + checks + ' passed\n');
