'use strict';

/**
 * FT1 acceptance for the structure derivation.
 * Every rule in section 3.2a of docs/facility-layout-structure-tree-plan.md has
 * a case here, plus the grouping identity rules from section 3a.
 */

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const structure = require(path.join(ROOT, 'static', 'facility_layout_structure.js'));
const { deriveStructure, UNZONED_SCOPE } = structure;

let passed = 0;
function check(name, run) {
    run();
    passed += 1;
    console.log('PASS ' + name);
}

function rect(x0, z0, x1, z1) {
    return [
        { x: x0, z: z0 }, { x: x1, z: z0 }, { x: x1, z: z1 }, { x: x0, z: z1 },
    ];
}

function zone(zoneId, label, boundary) {
    return { zoneId: zoneId, label: label, zoneType: 'workcell', boundary: boundary };
}

function place(placementId, assetId, x, z, revision) {
    return {
        placementId: placementId,
        assetId: assetId,
        assetDefinitionRevision: revision || 'r1',
        transform: { position: { x: x, y: 0, z: z } },
    };
}

// ---------------------------------------------------------------- rule 1 --
check('rule 1: parenting is whole-polygon and strictly larger', function () {
    const model = deriveStructure({
        zones: [
            zone('outer', 'Outer', rect(0, 0, 100, 100)),
            zone('inner', 'Inner', rect(10, 10, 40, 40)),
            // Overlaps outer but is not covered by it: not a child.
            zone('straddle', 'Straddle', rect(90, 90, 140, 140)),
        ],
        placements: [],
    });
    assert.strictEqual(model.zones.inner.parentZoneId, 'outer');
    assert.strictEqual(model.zones.straddle.parentZoneId, null);
    assert.deepStrictEqual(model.roots, ['outer', 'straddle'],
        'roots are label-ordered: Outer, Straddle');
});

check('rule 1: equal-area zones never parent each other', function () {
    const model = deriveStructure({
        zones: [
            zone('a', 'A', rect(0, 0, 10, 10)),
            zone('b', 'B', rect(0, 0, 10, 10)),
        ],
        placements: [],
    });
    assert.strictEqual(model.zones.a.parentZoneId, null);
    assert.strictEqual(model.zones.b.parentZoneId, null);
});

// ---------------------------------------------------------------- rule 2 --
check('rule 2: a placement exactly on the boundary is inside, not unzoned', function () {
    const model = deriveStructure({
        zones: [zone('z', 'Z', rect(0, 0, 10, 10))],
        placements: [
            place('edge', 'asset-a', 10, 5),      // on the right edge
            place('corner', 'asset-a', 0, 0),     // on a vertex
            place('outside', 'asset-a', 10.5, 5),
        ],
    });
    assert.strictEqual(model.counts.unzoned, 1);
    assert.strictEqual(model.zones.z.directCount, 2);
    assert.deepStrictEqual(
        model.unzoned.groups[0].placementIds, ['outside']
    );
});

// ---------------------------------------------------------------- rule 3 --
check('rule 3: smallest containing zone wins', function () {
    const model = deriveStructure({
        zones: [
            zone('big', 'Big', rect(0, 0, 100, 100)),
            zone('small', 'Small', rect(0, 0, 20, 20)),
        ],
        placements: [place('p', 'asset-a', 5, 5)],
    });
    assert.strictEqual(model.zones.small.directCount, 1);
    assert.strictEqual(model.zones.big.directCount, 0);
    assert.strictEqual(model.zones.big.totalCount, 1, 'parent total includes the child');
});

check('rule 3: equal areas resolve by zoneId, not input order', function () {
    const zoneA = zone('aaa', 'A', rect(0, 0, 10, 10));
    const zoneB = zone('bbb', 'B', rect(0, 0, 10, 10));
    const placements = [place('p', 'asset-a', 5, 5)];
    const forward = deriveStructure({ zones: [zoneA, zoneB], placements: placements });
    const reversed = deriveStructure({ zones: [zoneB, zoneA], placements: placements });
    assert.strictEqual(forward.zones.aaa.directCount, 1);
    assert.strictEqual(reversed.zones.aaa.directCount, 1,
        'reordering the zones array must not move the placement');
    assert.strictEqual(forward.zones.bbb.directCount, 0);
    assert.strictEqual(reversed.zones.bbb.directCount, 0);
});

check('rule 3: a reordered zones array produces identical output', function () {
    const zones = [
        zone('z1', 'One', rect(0, 0, 100, 100)),
        zone('z2', 'Two', rect(10, 10, 50, 50)),
        zone('z3', 'Three', rect(20, 20, 30, 30)),
    ];
    const placements = [
        place('p1', 'asset-a', 25, 25),
        place('p2', 'asset-b', 40, 40),
        place('p3', 'asset-a', 90, 90),
    ];
    const forward = deriveStructure({ zones: zones, placements: placements });
    const shuffled = deriveStructure({
        zones: [zones[2], zones[0], zones[1]],
        placements: placements,
    });
    assert.deepStrictEqual(forward.roots, shuffled.roots);
    assert.deepStrictEqual(
        Object.keys(forward.zones).sort().map(function (id) {
            return [id, forward.zones[id].parentZoneId, forward.zones[id].directCount];
        }),
        Object.keys(shuffled.zones).sort().map(function (id) {
            return [id, shuffled.zones[id].parentZoneId, shuffled.zones[id].directCount];
        })
    );
});

// ---------------------------------------------------------------- rule 4 --
check('rule 4: overlapping non-nesting zones list a placement once', function () {
    const model = deriveStructure({
        zones: [
            zone('left', 'Left', rect(0, 0, 60, 40)),      // area 2400
            zone('right', 'Right', rect(40, 0, 100, 40)),  // area 2400, overlaps
        ],
        placements: [place('p', 'asset-a', 50, 20)],       // inside both
    });
    const total = model.zones.left.directCount + model.zones.right.directCount;
    assert.strictEqual(total, 1, 'appears exactly once');
    assert.strictEqual(model.zones.left.directCount, 1, 'zoneId ascending breaks the tie');
    assert.strictEqual(model.counts.unzoned, 0);
});

// ---------------------------------------------------------------- rule 5 --
check('rule 5: invalid geometry is reported, not thrown, and holds nothing', function () {
    const model = deriveStructure({
        zones: [
            zone('good', 'Good', rect(0, 0, 100, 100)),
            zone('broken', 'Broken', [{ x: 0, z: 0 }, { x: 1, z: 1 }]),
            { zoneId: 'degenerate', label: 'Degenerate', boundary: rect(5, 5, 5, 5) },
        ],
        placements: [place('p', 'asset-a', 50, 50)],
    });
    assert.deepStrictEqual(model.invalidZoneIds.sort(), ['broken', 'degenerate']);
    assert.strictEqual(model.zones.broken.geometryValid, false);
    assert.strictEqual(model.zones.broken.directCount, 0);
    assert.strictEqual(model.zones.good.directCount, 1,
        'an invalid zone does not steal a placement');
});

// -------------------------------------------------------- concave polygon --
check('concave polygon: the bbox prefilter does not admit a point outside it', function () {
    // An L shape. (90, 90) is inside the bounding box but outside the polygon.
    const ell = [
        { x: 0, z: 0 }, { x: 100, z: 0 }, { x: 100, z: 40 },
        { x: 40, z: 40 }, { x: 40, z: 100 }, { x: 0, z: 100 },
    ];
    const model = deriveStructure({
        zones: [zone('ell', 'L', ell)],
        placements: [
            place('inside', 'asset-a', 20, 20),
            place('notch', 'asset-a', 90, 90),
        ],
    });
    assert.strictEqual(model.zones.ell.directCount, 1);
    assert.deepStrictEqual(model.unzoned.groups[0].placementIds, ['notch']);
});

// ------------------------------------------------------------ empty cases --
check('an empty layout derives an empty structure', function () {
    const model = deriveStructure({});
    assert.deepStrictEqual(model.roots, []);
    assert.strictEqual(model.counts.zones, 0);
    assert.strictEqual(model.counts.placements, 0);
    assert.strictEqual(model.unzoned.directCount, 0);
});

check('zones with no placements derive zones and no groups', function () {
    const model = deriveStructure({
        zones: [zone('z', 'Z', rect(0, 0, 10, 10))],
        placements: [],
    });
    assert.strictEqual(model.counts.zones, 1);
    assert.deepStrictEqual(model.zones.z.groups, []);
    assert.strictEqual(model.zones.z.totalCount, 0);
});

check('placements with no zones all fall to unzoned', function () {
    const model = deriveStructure({
        zones: [],
        placements: [place('p1', 'asset-a', 1, 1), place('p2', 'asset-a', 2, 2)],
    });
    assert.strictEqual(model.unzoned.directCount, 2);
    assert.strictEqual(model.unzoned.groups.length, 1, 'same asset groups together');
    assert.strictEqual(model.unzoned.groups[0].scopeId, UNZONED_SCOPE);
});

// ------------------------------------------------- grouping identity (3a) --
check('groups retain their member placement IDs', function () {
    const model = deriveStructure({
        zones: [zone('z', 'Z', rect(0, 0, 10, 10))],
        placements: [
            place('p1', 'asset-a', 1, 1),
            place('p2', 'asset-a', 2, 2),
            place('p3', 'asset-b', 3, 3),
        ],
    });
    const groups = model.zones.z.groups;
    assert.strictEqual(groups.length, 2);
    assert.deepStrictEqual(groups[0].placementIds, ['p1', 'p2']);
    assert.deepStrictEqual(groups[1].placementIds, ['p3']);
});

check('two revisions of one asset are two groups', function () {
    const model = deriveStructure({
        zones: [zone('z', 'Z', rect(0, 0, 10, 10))],
        placements: [
            place('p1', 'asset-a', 1, 1, 'rev-1'),
            place('p2', 'asset-a', 2, 2, 'rev-2'),
        ],
    });
    assert.strictEqual(model.zones.z.groups.length, 2,
        'display name would have merged these; identity must not');
});

check('the same asset in two zones gets two distinct row IDs', function () {
    const model = deriveStructure({
        zones: [
            zone('cellA', 'Cell A', rect(0, 0, 10, 10)),
            zone('cellB', 'Cell B', rect(20, 0, 30, 10)),
        ],
        placements: [
            place('a1', 'asset-guard', 5, 5),
            place('b1', 'asset-guard', 25, 5),
        ],
    });
    const rowA = model.zones.cellA.groups[0].rowId;
    const rowB = model.zones.cellB.groups[0].rowId;
    assert.notStrictEqual(rowA, rowB,
        'expanding Cell A must not expand the identical group in Cell B');
    assert.ok(rowA.indexOf('cellA') === 0);
    assert.ok(rowB.indexOf('cellB') === 0);
});

check('unzoned groups cannot collide with a zone scope', function () {
    const model = deriveStructure({
        zones: [zone('z', 'Z', rect(0, 0, 10, 10))],
        placements: [
            place('inside', 'asset-a', 5, 5),
            place('outside', 'asset-a', 50, 50),
        ],
    });
    assert.notStrictEqual(
        model.zones.z.groups[0].rowId,
        model.unzoned.groups[0].rowId
    );
});

// ------------------------------------------------------- reference layout --
const REFERENCE = path.join(
    ROOT, '.runtime', 'facility-layout', 'layouts', 'local', 'site-local',
    'layouts', 'fl-reference-manual-20260812.json'
);
if (fs.existsSync(REFERENCE)) {
    const layout = JSON.parse(fs.readFileSync(REFERENCE, 'utf8'));

    check('reference layout: matches the figures the plan was written against', function () {
        const model = deriveStructure(layout);
        assert.strictEqual(model.counts.zones, 45);
        assert.strictEqual(model.counts.placements, 827);
        assert.strictEqual(model.counts.unzoned, 0, 'every placement lands in a zone');
        assert.strictEqual(model.roots.length, 6);
        assert.strictEqual(model.counts.invalidZones, 0);
    });

    check('reference layout: nesting is three deep, 6 / 27 / 12', function () {
        const model = deriveStructure(layout);
        const depths = {};
        model.zoneOrder.forEach(function (zoneId) {
            let depth = 0;
            let cursor = model.zones[zoneId].parentZoneId;
            while (cursor) { depth += 1; cursor = model.zones[cursor].parentZoneId; }
            depths[depth] = (depths[depth] || 0) + 1;
        });
        assert.deepStrictEqual(depths, { 0: 6, 1: 27, 2: 12 });
    });

    check('reference layout: group row IDs are unique across the whole tree', function () {
        const model = deriveStructure(layout);
        const seen = Object.create(null);
        let groups = 0;
        model.zoneOrder.forEach(function (zoneId) {
            model.zones[zoneId].groups.forEach(function (group) {
                assert.ok(!seen[group.rowId], 'duplicate group row ID: ' + group.rowId);
                seen[group.rowId] = true;
                groups += 1;
            });
        });
        assert.ok(groups > 0);
    });

    check('reference layout: derivation is order independent', function () {
        const shuffled = {
            zones: layout.zones.slice().reverse(),
            placements: layout.placements.slice().reverse(),
        };
        const a = deriveStructure(layout);
        const b = deriveStructure(shuffled);
        assert.deepStrictEqual(a.roots, b.roots);
        a.zoneOrder.forEach(function (zoneId) {
            assert.strictEqual(
                a.zones[zoneId].directCount, b.zones[zoneId].directCount,
                'counts differ for ' + zoneId
            );
            assert.strictEqual(
                a.zones[zoneId].parentZoneId, b.zones[zoneId].parentZoneId
            );
        });
    });

    // Section 5: the hierarchy and grouping halves of the benchmark. Rendering
    // belongs to FT2, integrated responsiveness to FT5.
    check('benchmark: hierarchy and grouping, reported separately', function () {
        const runs = 50;
        let start = process.hrtime.bigint();
        for (let i = 0; i < runs; i += 1) deriveStructure(layout);
        const full = Number(process.hrtime.bigint() - start) / 1e6 / runs;

        const zonesOnly = { zones: layout.zones, placements: [] };
        start = process.hrtime.bigint();
        for (let i = 0; i < runs; i += 1) deriveStructure(zonesOnly);
        const hierarchy = Number(process.hrtime.bigint() - start) / 1e6 / runs;

        console.log('     hierarchy only        %s ms', hierarchy.toFixed(2));
        console.log('     hierarchy + grouping  %s ms', full.toFixed(2));
        console.log('     grouping share        %s ms', (full - hierarchy).toFixed(2));
        assert.ok(full < 50, 'a full derivation should stay well inside a frame');
    });
} else {
    console.log('SKIP reference layout cases (fixture not present)');
}

// ------------------------------------------------------ FT4: reparenting --
// Deleting a zone is not modelled here - the derivation only sees the layout
// that remains. These checks pin the consequence the plan calls out, because
// an earlier draft got it backwards and said contents fall to Unzoned.

const NESTED = {
    zones: [
        { zoneId: 'outer', label: 'Automation', boundary: rect(0, 0, 100, 100) },
        { zoneId: 'mid', label: 'Cell A01', boundary: rect(10, 10, 60, 60) },
        { zoneId: 'inner', label: 'Station 1', boundary: rect(20, 20, 40, 40) },
    ],
    placements: [place('p1', 'asset-robot', 30, 30)],
};

function withoutZone(layout, zoneId) {
    return {
        zones: layout.zones.filter(function (zone) { return zone.zoneId !== zoneId; }),
        placements: layout.placements,
    };
}

function parentOf(model, placementId) {
    let found = null;
    model.zoneOrder.forEach(function (zoneId) {
        model.zones[zoneId].groups.forEach(function (group) {
            if (group.placementIds.indexOf(placementId) >= 0) found = zoneId;
        });
    });
    if (found) return found;
    const unzoned = model.unzoned;
    if (unzoned) {
        for (let index = 0; index < unzoned.groups.length; index += 1) {
            if (unzoned.groups[index].placementIds.indexOf(placementId) >= 0) {
                return UNZONED_SCOPE;
            }
        }
    }
    return null;
}

check('deleting a nested zone reparents to the next containing zone', function () {
    assert.strictEqual(parentOf(deriveStructure(NESTED), 'p1'), 'inner');

    // Delete the innermost zone: the robot is still inside Cell A01.
    const afterInner = deriveStructure(withoutZone(NESTED, 'inner'));
    assert.strictEqual(parentOf(afterInner, 'p1'), 'mid', 'falls to the next parent');

    // Delete that too: still inside Automation, still not unzoned.
    const afterMid = deriveStructure(
        withoutZone(withoutZone(NESTED, 'inner'), 'mid')
    );
    assert.strictEqual(parentOf(afterMid, 'p1'), 'outer');
    assert.strictEqual(afterMid.unzoned.directCount, 0, 'nothing fell to Unzoned');
});

check('only a placement with no containing zone left becomes unzoned', function () {
    const bare = deriveStructure({ zones: [], placements: NESTED.placements });
    assert.strictEqual(parentOf(bare, 'p1'), UNZONED_SCOPE);
    assert.strictEqual(bare.unzoned.directCount, 1);
});

check('deleting a middle zone reparents its child zone, not just its assets', function () {
    const afterMid = deriveStructure(withoutZone(NESTED, 'mid'));
    assert.deepStrictEqual(afterMid.roots, ['outer']);
    assert.deepStrictEqual(afterMid.zones.outer.childZoneIds, ['inner'],
        'the grandchild becomes a direct child of the surviving ancestor');
    assert.strictEqual(parentOf(afterMid, 'p1'), 'inner');
});

check('deleting a top-level zone drops its whole subtree to unzoned', function () {
    const afterOuter = deriveStructure({
        zones: [],
        placements: NESTED.placements,
    });
    assert.deepStrictEqual(afterOuter.roots, []);
    assert.strictEqual(afterOuter.unzoned.directCount, 1);
});

check('moving a placement across a boundary moves it between zones', function () {
    const moved = {
        zones: NESTED.zones,
        placements: [place('p1', 'asset-robot', 70, 70)],   // outside mid, inside outer
    };
    assert.strictEqual(parentOf(deriveStructure(moved), 'p1'), 'outer');

    const outside = {
        zones: NESTED.zones,
        placements: [place('p1', 'asset-robot', 500, 500)],
    };
    assert.strictEqual(parentOf(deriveStructure(outside), 'p1'), UNZONED_SCOPE);
});

check('counts roll up through the surviving chain after a deletion', function () {
    const before = deriveStructure(NESTED);
    assert.strictEqual(before.zones.outer.totalCount, 1);
    assert.strictEqual(before.zones.outer.directCount, 0, 'held by the innermost zone');

    const after = deriveStructure(withoutZone(NESTED, 'inner'));
    assert.strictEqual(after.zones.outer.totalCount, 1);
    assert.strictEqual(after.zones.mid.directCount, 1);
});

console.log('\n' + passed + '/' + passed + ' facility layout structure checks passed');
