'use strict';

// General lights by area (docs/facility-lighting-plan.md, L7): resolving the areas, testing points against them, the
// on/off table size and the shader hook, exercised against the vendored three.js r184.

const assert = require('assert');
const path = require('path');
const { pathToFileURL } = require('url');

const ROOT = path.resolve(__dirname, '..');
const areas = require('../static/facility_layout_light_areas.js');

const tests = [];
function test(name, callback) { tests.push({ name, callback }); }

let threeModule = null;
async function three() {
    if (!threeModule) {
        threeModule = await import(pathToFileURL(path.join(ROOT, 'static/vendor/three/0.184.0/build/three.module.min.js')).href);
    }
    return threeModule;
}

const floor = (surfaceId, label, points) => ({ surfaceId, label, elevation: 0, material: 'concrete', color: '#8a8f94',
    roughness: 0.8, boundary: points.map(([x, z]) => ({ x, z })) });
const LAYOUT = { extensions: { facilityFloorSurfaces: { version: 1, surfaces: [
    floor('fs-receiving', '01 Receiving', [[0, 0], [10, 0], [10, 10], [0, 10]]),
    // An L: the notch at x 25-30, z 5-10 is outside.
    floor('fs-dispatch', '06 Dispatch', [[20, 0], [30, 0], [30, 5], [25, 5], [25, 10], [20, 10]]),
] } } };

test('areas resolve against the layout: floor areas by id, plan rectangles, and floor areas that are gone', () => {
    const resolved = areas.resolveAreas({ mode: 'only', areas: [{ surfaceId: 'fs-receiving' }, { surfaceId: 'fs-gone' },
        { rectangle: { minX: 40, minZ: 0, maxX: 50, maxZ: 2 } }, { surfaceId: 'fs-dispatch' }] }, LAYOUT);
    assert.strictEqual(resolved.mode, 'only');
    assert.deepStrictEqual(resolved.shapes.map(shape => [shape.kind, shape.surfaceId || null, shape.label || null]),
        [['floor', 'fs-receiving', '01 Receiving'], ['rectangle', null, null], ['floor', 'fs-dispatch', '06 Dispatch']]);
    assert.deepStrictEqual(resolved.missing, ['fs-gone'], 'a floor area deleted later lights nothing');
    assert.deepStrictEqual(resolved.shapes[2].bounds, { minX: 20, minZ: 0, maxX: 30, maxZ: 10 });
    assert.strictEqual(areas.resolveAreas(null, LAYOUT), null, 'no areas: general lights on everywhere');
    assert.strictEqual(areas.resolveAreas({ mode: 'on', areas: [] }, LAYOUT), null, 'an unknown mode is ignored');
    assert.deepStrictEqual(areas.resolveAreas({ mode: 'except', areas: [{ rectangle: { minX: 5, minZ: 0, maxX: 5, maxZ: 9 } }] },
        null), { mode: 'except', shapes: [], missing: [] }, 'an empty rectangle is no area; a layout without floors is fine');
    const many = areas.resolveAreas({ mode: 'only', areas: Array.from({ length: 70 }, (_, i) => ({
        rectangle: { minX: i, minZ: 0, maxX: i + 1, maxZ: 1 } })) }, LAYOUT);
    assert.strictEqual(many.shapes.length, areas.MAX_AREAS, 'at most 64 areas are read');
});

test('a point is lit inside the areas (edges count) with mode only, and outside them with mode except', () => {
    const only = areas.resolveAreas({ mode: 'only', areas: [{ surfaceId: 'fs-receiving' }, { surfaceId: 'fs-dispatch' },
        { rectangle: { minX: 40, minZ: 0, maxX: 50, maxZ: 2 } }] }, LAYOUT);
    const except = Object.assign({}, only, { mode: 'except' });
    const points = { centre: [5, 5], edge: [10, 5], corner: [0, 0], beside: [11, 5], notch: [27, 7], foot: [27, 2],
        stem: [22, 7], box: [45, 1], aboveBox: [45, 3] };
    const seen = mode => Object.fromEntries(Object.entries(points).map(([name, [x, z]]) => [name, areas.lit(mode, x, z)]));
    assert.deepStrictEqual(seen(only), { centre: true, edge: true, corner: true, beside: false, notch: false, foot: true,
        stem: true, box: true, aboveBox: false });
    assert.deepStrictEqual(seen(except), { centre: false, edge: false, corner: false, beside: true, notch: true, foot: false,
        stem: false, box: false, aboveBox: true });
    assert.strictEqual(areas.lit(null, 5, 5), true);
    const nothing = areas.resolveAreas({ mode: 'only', areas: [] }, LAYOUT);
    assert.strictEqual(areas.lit(nothing, 5, 5), false, 'only, with no areas: general lights off everywhere');
    assert.strictEqual(areas.insidePolygon([[0, 0], [4, 0], [0, 4]], 2, 2), true, 'on the slanted edge');
    assert.strictEqual(areas.insidePolygon([[0, 0], [4, 0], [0, 4]], 2.01, 2.01), false);
});

test('an on/off table holds one texel per part per copy, wrapped onto rows of 2048', () => {
    assert.deepStrictEqual(areas.tableSize(50, 16), { width: 800, height: 1 });
    assert.deepStrictEqual(areas.tableSize(3000, 2), { width: 2048, height: 3 });
    assert.deepStrictEqual(areas.tableSize(0, 0), { width: 1, height: 1 });
});

test('the shader hook scales each part\'s glow by its texel and tone-maps the lamps it switches off', async () => {
    const THREE = await three();
    assert.strictEqual(areas.toneMappingName(THREE, THREE.ACESFilmicToneMapping), 'ACESFilmic');
    assert.strictEqual(areas.toneMappingName(THREE, THREE.AgXToneMapping), 'AgX');
    assert.strictEqual(areas.toneMappingName(THREE, THREE.NoToneMapping), null);
    const physical = () => ({ vertexShader: THREE.ShaderLib.physical.vertexShader,
        fragmentShader: THREE.ShaderLib.physical.fragmentShader, uniforms: {} });
    const shader = physical();
    assert.strictEqual(areas.patchGlowShader(shader, 'ACESFilmic'), true);
    const vertex = shader.vertexShader;
    const fragment = shader.fragmentShader;
    assert.ok(vertex.indexOf('attribute float facilityLamp;') < vertex.indexOf('void main() {'), 'declared before main');
    assert.ok(vertex.includes('gl_InstanceID * facilityLampParts + int( facilityLamp + 0.5 )'), 'copies of a batch by instance');
    assert.ok(vertex.includes('texelFetch( facilityLampTable, ivec2( facilityLampTexel % facilityLampWidth,'
        + ' facilityLampTexel / facilityLampWidth ), 0 ).r'));
    assert.ok(vertex.includes('facilityLampMaskOn > 0.5 ?'), 'unused when the scene has no areas');
    assert.ok(fragment.includes('#include <emissivemap_fragment>\n\ttotalEmissiveRadiance *= vFacilityLampLit;'),
        'the glow is scaled before lighting adds it in');
    assert.ok(fragment.includes('vec3 facilityLampOffToneMapping( vec3 color ) { return ACESFilmicToneMapping( color ); }'));
    assert.ok(fragment.indexOf('mix( facilityLampOffToneMapping( gl_FragColor.rgb ), gl_FragColor.rgb, vFacilityLampLit )')
        < fragment.indexOf('#include <tonemapping_fragment>'), 'before the renderer\'s own tone mapping step');
    assert.strictEqual((fragment.match(/#ifndef TONE_MAPPING/g) || []).length, 2,
        'both tone mapping additions only where the material is not tone-mapped already');
    const plain = physical();
    areas.patchGlowShader(plain, null);
    assert.ok(plain.fragmentShader.includes('{ return color; }'), 'no renderer tone mapping: off lamps unchanged');
    const odd = { vertexShader: 'void main() {}', fragmentShader: 'void main() {}', uniforms: {} };
    assert.strictEqual(areas.patchGlowShader(odd, 'ACESFilmic'), false, 'a shader of another shape is left alone');
    assert.strictEqual(odd.vertexShader, 'void main() {}');
});

(async () => {
    let passed = 0;
    for (const entry of tests) {
        try {
            await entry.callback();
            passed += 1;
            console.log('ok - ' + entry.name);
        } catch (error) {
            console.error('not ok - ' + entry.name);
            console.error(error && error.stack ? error.stack : error);
            process.exitCode = 1;
        }
    }
    console.log(passed + '/' + tests.length + ' passed');
})();
