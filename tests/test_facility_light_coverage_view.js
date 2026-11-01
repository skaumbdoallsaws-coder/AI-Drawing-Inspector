'use strict';

// Lighting coverage overlay (docs/facility-lighting-plan.md, CC3): the server's grid read back, the lux bands, the
// floor the 3D quads lie on, the plan picture and the 3D objects.

const assert = require('assert');
const path = require('path');
const { pathToFileURL } = require('url');

const ROOT = path.resolve(__dirname, '..');
const coverage = require('../static/facility_layout_light_coverage.js');
const groundRuntime = require('../static/facility_layout_ground.js');

function payload(cols, rows, values, extra) {
    const buffer = Buffer.alloc(cols * rows * 2);
    values.forEach((value, index) => buffer.writeUInt16LE(value === null ? 65535 : Math.round(value * 10), index * 2));
    return Object.assign({
        summary: { label: coverage.CAPTION, area: { label: 'the car parks and truck yards' }, darkSpots: { listed: [] } },
        grid: { originX: 10, originZ: -5, cellMeters: 1, cols, rows, encoding: 'uint16le-tenths',
            values: buffer.toString('base64') },
        spots: [],
    }, extra || {});
}

function luminance(color) {
    const channel = value => {
        const c = parseInt(value, 16) / 255;
        return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(color.slice(1, 3)) + 0.7152 * channel(color.slice(3, 5)) + 0.0722 * channel(color.slice(5, 7));
}

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('the bands run from dark to light by estimated lux, the dark end for the dark spots', () => {
    assert.deepStrictEqual(coverage.BANDS.map(band => band.from), [0, 1, 5, 10, 20, 50, 100, 200]);
    const light = coverage.BANDS.map(band => luminance(band.color));
    light.slice(1).forEach((value, index) => assert.ok(value > light[index], 'band ' + (index + 1) + ' is lighter'));
    assert.deepStrictEqual([0, 0.9, 1, 4.9, 5, 19.9, 20, 199.9, 200, 5000].map(coverage.bandOf),
        [0, 0, 1, 1, 2, 3, 4, 6, 7, 7]);
    assert.strictEqual(coverage.CAPTION, 'Estimate, not a lighting design. No code-compliance claims.');
});

test('the grid reads back row by row from the south-west cell, cells outside the area left out', () => {
    const grid = coverage.decode(payload(3, 2, [0, 0.5, null, 1, 250, 19.9]));
    assert.deepStrictEqual(Array.from(grid.bands), [0, 0, -1, 1, 7, 3]);
    assert.deepStrictEqual(Array.from(grid.lux).map(value => Number.isNaN(value) ? null : Math.round(value * 10) / 10),
        [0, 0.5, null, 1, 250, 19.9]);
    assert.deepStrictEqual([grid.originX, grid.originZ, grid.cell, grid.cols, grid.rows, grid.inside], [10, -5, 1, 3, 2, 5]);
    const broken = payload(3, 2, [0, 0, 0, 0, 0, 0]);
    broken.grid.values = broken.grid.values.slice(0, 8);
    assert.throws(() => coverage.decode(broken), /incomplete/);
    assert.throws(() => coverage.decode({ grid: Object.assign({}, payload(1, 1, [0]).grid, { encoding: 'float32' }) }),
        /cannot draw/);
});

test('the 3D quads lie flat just above the highest floor drawn under each cell centre', () => {
    const layout = {
        coordinateFrame: { floorElevation: 0 },
        extensions: {
            facilityGround: { schemaVersion: 1, surfaces: [
                { surfaceId: 'yard', minX: 10, maxX: 12, minZ: -5, maxZ: -3, startElevation: -1.35, endElevation: -1.35,
                    slopeAxis: 'x', color: '#3d4247' },
                { surfaceId: 'ramp', minX: 11, maxX: 12, minZ: -5, maxZ: -3, startElevation: -1.35, endElevation: -0.35,
                    slopeAxis: 'x', color: '#3d4247' }] },
            facilityFloorSurfaces: { version: 1, surfaces: [{ surfaceId: 'fs-dock', label: 'Dock', elevation: 0.2,
                boundary: [{ x: 12, z: -5 }, { x: 13, z: -5 }, { x: 13, z: -3 }, { x: 12, z: -3 }] }] },
        },
    };
    const heightAt = coverage.floorHeight(layout, groundRuntime);
    assert.strictEqual(heightAt(10.5, -4.5), -1.35, 'the yard');
    assert.ok(Math.abs(heightAt(11.5, -4.5) + 0.85) < 1e-9, 'the ramp, higher than the yard there');
    assert.strictEqual(heightAt(12.5, -4.5), 0.2, 'the floor area');
    assert.strictEqual(heightAt(20, 20), 0, 'elsewhere the floor');
    const grid = coverage.decode(payload(3, 2, [0.5, 30, 250, null, 30, 0.5]));
    const spots = coverage.spotsOf({ spots: [{ number: 1, centre: { x: 10.5, z: -4.5 },
        outline: [[10, -5, 11, -5, 11, -4, 10, -4]] }] });
    const view = coverage.sceneView(grid, spots, heightAt);
    assert.deepStrictEqual(view.parts.map(part => [part.band, part.color, part.indices.length / 6]),
        [[0, '#1c1202', 2], [4, '#af8008', 2], [7, '#fff0d6', 1]]);
    const yard = view.parts[0].positions;
    assert.deepStrictEqual(Array.from(yard.slice(0, 12)).map(value => Math.round(value * 100) / 100),
        [10, -1.3, -5, 11, -1.3, -5, 11, -1.3, -4, 10, -1.3, -4], 'the south-west cell, 5 cm over the yard');
    const at = (part, vertex) => Array.from(part.positions.slice(vertex * 3, vertex * 3 + 3));
    const [a, b, c] = Array.from(view.parts[0].indices.slice(0, 3)).map(vertex => at(view.parts[0], vertex));
    const normalY = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]);
    assert.ok(normalY > 0, 'faces up');
    assert.ok(Math.abs(view.parts[2].positions[1] - 0.25) < 1e-6, 'the floor area cell sits over the floor area');
    assert.strictEqual(view.outline.length, 4 * 2 * 3, 'four 1 m edges, each a segment');
    assert.ok(Math.abs(view.outline[1] - (-1.35 + 0.08)) < 1e-6, 'outlines a little above the quads');
});

test('the plan picture is one pixel per cell, north up, transparent outside the area', () => {
    let drawn = null;
    const canvas = {
        getContext: () => ({
            createImageData: (width, height) => ({ width, height, data: new Uint8ClampedArray(width * height * 4) }),
            putImageData: image => { drawn = image; },
        }),
        toDataURL: type => 'data:' + type + ';base64,AAAA',
    };
    const grid = coverage.decode(payload(2, 2, [0.5, null, 250, 30]));
    assert.strictEqual(coverage.planImage({ createElement: () => canvas }, grid), 'data:image/png;base64,AAAA');
    assert.deepStrictEqual([canvas.width, canvas.height], [2, 2]);
    const pixel = (x, y) => Array.from(drawn.data.slice((y * 2 + x) * 4, (y * 2 + x) * 4 + 4));
    assert.deepStrictEqual(pixel(0, 1), [0x1c, 0x12, 0x02, 255], 'the south-west cell is bottom left');
    assert.deepStrictEqual(pixel(1, 1), [0, 0, 0, 0], 'outside the area');
    assert.deepStrictEqual(pixel(0, 0), [0xff, 0xf0, 0xd6, 255], 'the north-west cell is top left');
    assert.strictEqual(coverage.planImage({ createElement: () => ({}) }, grid), null, 'no canvas, no picture');
});

test('the 3D objects are a mesh per band and the outlines, unlit, see-through and never picked', async () => {
    const THREE = await import(pathToFileURL(path.join(ROOT, 'static/vendor/three/0.184.0/build/three.module.min.js')).href);
    const grid = coverage.decode(payload(2, 1, [0.5, 30]));
    const spots = coverage.spotsOf({ spots: [{ number: 1, centre: { x: 10.5, z: -4.5 },
        outline: [[10, -5, 11, -5, 11, -4, 10, -4]] }] });
    const root = coverage.sceneObjects(THREE, coverage.sceneView(grid, spots, () => 0), new THREE.Group());
    assert.strictEqual(root.name, 'FacilityLightCoverage');
    assert.deepStrictEqual(root.children.map(child => child.name),
        ['FacilityLightCoverage:band-0', 'FacilityLightCoverage:band-4', 'FacilityLightCoverage:dark-spots']);
    const [dark, mid, outline] = root.children;
    assert.strictEqual(dark.material.color.getHexString(), '1c1202');
    assert.strictEqual(mid.material.color.getHexString(), 'af8008');
    [dark, mid].forEach(mesh => {
        assert.ok(mesh.material.transparent && mesh.material.opacity === coverage.OPACITY && !mesh.material.depthWrite);
        assert.ok(!mesh.material.toneMapped && !mesh.material.fog && mesh.material.polygonOffset);
        assert.strictEqual(mesh.geometry.index.count, 6);
    });
    assert.ok(outline.isLineSegments && outline.renderOrder > mid.renderOrder);
    const hits = [];
    root.children.forEach(child => child.raycast(new THREE.Raycaster(), hits));
    assert.strictEqual(hits.length, 0, 'not pickable');
});

test('prepare gives the plan, the 3D view and the Scenes pane what they draw from one reply', () => {
    const reply = payload(2, 1, [0.5, 30], {
        summary: { label: coverage.CAPTION, area: { label: 'Visitor car park' },
            darkSpots: { listed: [{ centre: { x: 10.5, z: -4.5 }, sizeSquareMeters: 1, minimumLux: 0.5, meanLux: 0.5,
                nearestLamps: [] }] } },
        spots: [{ number: 1, centre: { x: 10.5, z: -4.5 }, outline: [[10, -5, 11, -5, 11, -4, 10, -4]] }],
    });
    const prepared = coverage.prepare(reply, { document: null, layout: {}, groundRuntime });
    assert.strictEqual(prepared.caption, coverage.CAPTION);
    assert.deepStrictEqual([prepared.plan.minX, prepared.plan.minZ, prepared.plan.maxX, prepared.plan.maxZ], [10, -5, 12, -4]);
    assert.strictEqual(prepared.plan.image, null);
    assert.deepStrictEqual(prepared.plan.spots[0].rings[0][2], { x: 11, z: -4 });
    assert.strictEqual(prepared.spots[0].number, 1);
    assert.strictEqual(prepared.scene.parts.length, 2);
});

(async () => {
    let failed = 0;
    for (const [name, fn] of tests) {
        try { await fn(); console.log('ok -', name); } catch (error) { failed += 1; console.error('FAIL -', name, '\n', error); }
    }
    console.log(failed ? failed + ' failed' : tests.length + '/' + tests.length + ' passed');
    process.exitCode = failed ? 1 : 0;
})();
