'use strict';

const assert = require('assert');
const fs = require('fs');
const adapter = require('../static/facility_layout_command_adapter.js');
const patterns = require('../static/facility_layout_patterns.js');
const contract = require('../static/contracts/facility-construction-commands-v1.json');

// Python feeds schema probes to this mode to check cross-language acceptance.
if (process.argv.includes('--validate')) {
    const requests = JSON.parse(fs.readFileSync(0, 'utf8'));
    process.stdout.write(JSON.stringify(requests.map(request => {
        try { adapter.normalize(contract, request.commandId, request.arguments); return true; }
        catch (_) { return false; }
    })));
} else {
    let checks = 0;
    function check(name, fn) { fn(); checks++; process.stdout.write('PASS ' + name + '\n'); }
    const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`);
    function fixture() {
        const placements = ['bench', 'tool'].map((id, i) => ({
            placementId: id, assetId: 'asset-' + id, assetDefinitionRevision: 'revision-' + id,
            positionMode: 'manual', transform: { position: { x: 10 + i * 5, y: 0, z: 10 },
                quaternion: { x: 0, y: 0, z: 0, w: 1 }, scale: 1 },
        }));
        const catalog = placements.map(p => ({ assetId: p.assetId,
            assetDefinitionRevision: p.assetDefinitionRevision,
            width: p.placementId === 'bench' ? 3 : 0.3, depth: 2, height: 1 }));
        catalog[0].supportSurfaces = [{ surfaceId: 'worktop',
            localFrame: { origin: { x: 0, y: 1, z: 0 }, xAxis: { x: 1, y: 0, z: 0 },
                zAxis: { x: 0, y: 0, z: 1 }, normal: { x: 0, y: 1, z: 0 } },
            bounds: { minimumX: -1.5, maximumX: 1.5, minimumZ: -1, maximumZ: 1 },
            allowedSides: ['above', 'below'] }];
        return { layout: { placements, zones: [], floorMarkings: [], routes: [] }, catalog };
    }
    const linear = { seedIds: ['bench'], count: 4, direction: 'vertical', spacing: 5, sourceUnit: 'm' };
    function prepare(commandId, args, data) {
        data = data || fixture();
        return adapter.prepare(contract, patterns, data.layout, data.catalog, commandId, args, 'test');
    }
    check('vertical 5 m request matches manual geometry and preserves orientation', () => {
        const data = fixture();
        const result = prepare('linear-pattern', linear, data).pattern;
        const manual = patterns.buildLinearPattern(patterns.collectSelection(data.layout,
            data.catalog, ['bench']), { count: 4, pitch: 5, angleDegrees: 90 });
        assert.deepStrictEqual(result, manual);
        result.copies.forEach((copy, i) => { near(copy.position.x, 10); near(copy.position.z, 5 - i * 5); });
    });
    check('all cardinal directions and unit conversions are explicit', () => {
        for (const [direction, dx, dz] of [['east', 1, 0], ['west', -1, 0], ['north', 0, 1], ['south', 0, -1]]) {
            const result = prepare('linear-pattern', { ...linear, direction, sourceUnit: 'mm', spacing: 5000 }).pattern;
            near(result.copies[0].position.x, 10 + dx * 5);
            near(result.copies[0].position.z, 10 + dz * 5);
        }
        near(prepare('linear-pattern', { ...linear, sourceUnit: 'ft', spacing: 10 }).pattern.guide.pitch, 3.048);
        near(prepare('linear-pattern', { ...linear, sourceUnit: 'in', spacing: 12 }).pattern.guide.pitch, 0.3048);
    });
    check('invalid count spacing types fields and absent direction cannot default', () => {
        for (const patch of [{ count: 1 }, { count: 51 }, { count: 2.5 }, { spacing: 0 },
            { spacing: NaN }, { spacing: Infinity }, { spacing: '5' }, { direction: 'up' },
            { pitch: 5 }, { seedIds: ['bench', 'bench'] }, { sourceUnit: 'feet' }]) {
            assert.throws(() => prepare('linear-pattern', { ...linear, ...patch }));
        }
        const missing = { ...linear }; delete missing.direction;
        assert.throws(() => prepare('linear-pattern', missing));
        assert.strictEqual(prepare('linear-pattern', { ...linear, count: 50 }).pattern.copies.length, 49);
    });
    check('locked unknown route and missing or stale catalog records fail closed', () => {
        assert.throws(() => prepare('linear-pattern', { ...linear, seedIds: ['missing'] }));
        for (const change of [data => { data.layout.placements[0].positionMode = 'locked'; },
            data => { data.catalog = []; }, data => { data.catalog[0].assetDefinitionRevision = 'stale'; },
            data => { delete data.catalog[0].width; }]) {
            const data = fixture(); change(data); assert.throws(() => prepare('linear-pattern', linear, data));
        }
        const data = fixture(); data.layout.routes.push({ routeId: 'route' });
        assert.throws(() => prepare('linear-pattern', { ...linear, seedIds: ['route'] }, data));
    });
    check('cell layout parameters match manual builder and reject world coordinates', () => {
        const data = fixture();
        const args = { selectionIds: ['bench', 'tool'], strategyId: 'line', targetBounds: { width: 15, depth: 8 },
            gap: 0.5, rows: 1, orientation: 'preserve', angleDegrees: 0, invertU: false, sourceUnit: 'm' };
        assert.deepStrictEqual(prepare('cell-layout', args, data).pattern,
            patterns.buildCellLayout(patterns.collectSelection(data.layout, data.catalog, args.selectionIds),
                { shape: 'line', width: 15, depth: 8, gap: 0.5, rows: 1, orientation: 'preserve', angleDegrees: 0, invertU: false }));
        assert.throws(() => prepare('cell-layout', { ...args, targetBounds: { ...args.targetBounds, x: 20 } }));
        assert.throws(() => prepare('cell-layout', { ...args, targetBounds: { width: 0.1, depth: 0.1 } }));
    });
    check('surface side and unit conversion match manual builder, unknown surface rejects', () => {
        const data = fixture();
        data.catalog[1].depth = 0.3;
        const args = { supportId: 'bench', childIds: ['tool'], surfaceId: 'worktop', side: 'bottom',
            gap: 50, itemGap: 0, inset: 50, sourceUnit: 'mm' };
        assert.deepStrictEqual(prepare('surface-stack', args, data).pattern,
            patterns.buildSurfaceStack(patterns.collectSelection(data.layout, data.catalog, ['bench', 'tool']),
                { supportPlacementId: 'bench', surfaceId: 'worktop', side: 'below', gap: 0.05, itemGap: 0, inset: 0.05 }));
        assert.throws(() => prepare('surface-stack', { ...args, surfaceId: 'missing' }, data));
        assert.throws(() => prepare('surface-stack', { ...args, childIds: ['bench'] }, data));
    });
    check('create cell derives bounds with numeric padding and rejects accidental membership', () => {
        const data = fixture();
        const args = { selectionIds: ['bench'], label: 'Cell', envelopePadding: 100, sourceUnit: 'mm' };
        const result = prepare('create-cell-group', args, data).cell;
        near(result.minX, 8.4); near(result.width, 3.2);
        data.layout.placements[1].transform.position.x = 10;
        assert.throws(() => prepare('create-cell-group', args, data));
        assert.throws(() => prepare('create-cell-group', { ...args, envelopePadding: {} }));
    });
    check('nested zones cannot silently lose their child group on repetition', () => {
        const data = fixture();
        data.layout.zones = [{ zoneId: 'parent', boundary: [
            { x: 5, z: 5 }, { x: 20, z: 5 }, { x: 20, z: 20 }, { x: 5, z: 20 },
        ] }, { zoneId: 'child', parentZoneId: 'parent', boundary: [
            { x: 8, z: 8 }, { x: 12, z: 8 }, { x: 12, z: 12 }, { x: 8, z: 12 },
        ] }];
        assert.throws(() => prepare('linear-pattern', { ...linear, seedIds: ['parent'] }, data));
        delete data.layout.zones[1].parentZoneId;
        assert.throws(() => prepare('linear-pattern', { ...linear, seedIds: ['parent'] }, data));
    });
    process.stdout.write(`${checks}/${checks} construction adapter checks passed\n`);
}
