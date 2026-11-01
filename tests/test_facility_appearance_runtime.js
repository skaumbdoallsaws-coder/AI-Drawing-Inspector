'use strict';

// Appearance library runtime: catalog resolution, preferences, projected UVs
// and finish materials, exercised against the vendored three.js r184.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const ROOT = path.resolve(__dirname, '..');
const libraryApi = require('../static/facility_layout_library.js');
const finishes = require('../static/facility_layout_finishes.js');

function manifests() {
    const read = name => JSON.parse(fs.readFileSync(path.join(ROOT, 'static/facility_library', name + '.json'), 'utf8'));
    return { appearances: read('appearances'), scenes: read('scenes'), decals: read('decals') };
}

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('library resolves presets, custom finishes and per-use overrides in precedence order', () => {
    const library = libraryApi.indexLibrary(manifests());
    const layout = { placements: [], extensions: { facilityAppearances: { version: 1, custom: [
        { appearanceId: 'custom-smoked-oak', label: 'Smoked oak', baseAppearanceId: 'wood-oak', color: '#8a7b6a', sizeMeters: 0.6 },
    ] } } };
    const oak = libraryApi.resolveAppearance(library, { appearanceId: 'wood-oak' }, layout);
    assert.strictEqual(oak.texture.mapping, 'box');
    assert.strictEqual(oak.texture.grain, 'part', 'wood follows each part: legs vertical, tops lengthwise');
    assert.ok(oak.texture.maps.color.endsWith('/static/facility_library/textures/wood-oak/color.jpg'));
    const smoked = libraryApi.resolveAppearance(library, { appearanceId: 'custom-smoked-oak', sizeMeters: 0.5 }, layout);
    assert.strictEqual(smoked.label, 'Smoked oak');
    assert.strictEqual(smoked.color, '#8a7b6a');
    assert.strictEqual(smoked.texture.sizeMeters, 0.5, 'the placement override beats the custom finish');
    assert.strictEqual(smoked.baseAppearanceId, 'wood-oak');
    assert.strictEqual(libraryApi.resolveAppearance(library, { color: '#ff0000' }, layout), null);
    assert.strictEqual(libraryApi.resolveAppearance(library, { appearanceId: 'custom-gone' }, layout).missing, true);
    const kraft = libraryApi.resolveAppearance(library, { appearanceId: 'cardboard-kraft' }, layout);
    assert.strictEqual(kraft.color, '#b58f60');
    assert.ok(kraft.texture.maps.detail && !kraft.texture.maps.color, 'tintable sets use a neutral detail map');
});

test('finish signatures group identical finishes and separate any difference', () => {
    const library = libraryApi.indexLibrary(manifests());
    const sign = (value, scale) => libraryApi.finishSignature(libraryApi.resolveAppearance(library, value, {}), scale);
    assert.strictEqual(sign({ appearanceId: 'wood-oak' }), sign({ appearanceId: 'wood-oak' }));
    assert.notStrictEqual(sign({ appearanceId: 'wood-oak' }), sign({ appearanceId: 'wood-oak', rotationDegrees: 90 }));
    assert.notStrictEqual(sign({ appearanceId: 'wood-oak' }, 1), sign({ appearanceId: 'wood-oak' }, 2));
    assert.strictEqual(sign({ appearanceId: 'steel-polished' }, 1), sign({ appearanceId: 'steel-polished' }, 2),
        'untextured finishes do not depend on placement scale');
});

test('on a light the color override is its glow, the unlit color stays, and the glow is in the signature', () => {
    const library = libraryApi.indexLibrary(manifests());
    const layout = { placements: [], extensions: { facilityAppearances: { version: 1, custom: [
        { appearanceId: 'custom-daylight', label: 'Daylight', baseAppearanceId: 'light-cool-white-led', color: '#f4f8ff' },
    ] } } };
    const plain = libraryApi.resolveAppearance(library, { appearanceId: 'light-warm-white' }, {});
    assert.deepStrictEqual(plain.emission, { color: '#ffd29a', intensity: 1 });
    const tinted = libraryApi.resolveAppearance(library, { appearanceId: 'light-warm-white', color: '#ffb070' }, {});
    assert.deepStrictEqual(tinted.emission, { color: '#ffb070', intensity: 1 });
    assert.strictEqual(tinted.color, '#805838', 'switched off, the lens shows the same color at half brightness');
    assert.strictEqual(library.appearances.get('light-warm-white').emission.color, '#ffd29a', 'the library row is untouched');
    const custom = libraryApi.resolveAppearance(library, { appearanceId: 'custom-daylight' }, layout);
    assert.strictEqual(custom.emission.color, '#f4f8ff', 'a custom finish on a light carries its own glow');
    assert.strictEqual(libraryApi.resolveAppearance(library, { appearanceId: 'paint-machine-gray', color: '#123456' }, {}).color,
        '#123456', 'other finishes still take the color as their color');
    const sign = value => libraryApi.finishSignature(libraryApi.resolveAppearance(library, value, layout), 1);
    assert.notStrictEqual(sign({ appearanceId: 'light-warm-white' }), sign({ appearanceId: 'light-warm-white', color: '#ffb070' }));
    assert.strictEqual(sign({ appearanceId: 'light-stack-red' }), sign({ appearanceId: 'light-stack-red' }));
    assert.deepStrictEqual(libraryApi.search(library, { kind: 'appearance', category: 'lights' }).map(row => row.id), [
        'light-cool-white-led', 'light-warm-white', 'light-exit-green', 'light-beacon-amber', 'light-alarm-red',
        'light-signal-blue', 'light-stack-red', 'light-stack-amber', 'light-stack-green',
        'light-pole-led', 'light-wall-led', 'light-dock-led']);
    // An outdoor light's beam angle (L8) comes with it and makes its own material.
    assert.strictEqual(libraryApi.resolveAppearance(library, { appearanceId: 'light-pole-led' }, {}).emission.beamAngleDegrees, 110);
    const pole = libraryApi.resolveAppearance(library, { appearanceId: 'light-pole-led' }, {});
    const narrower = JSON.parse(JSON.stringify(pole));
    narrower.emission.beamAngleDegrees = 60;
    assert.notStrictEqual(libraryApi.finishSignature(pole, 1), libraryApi.finishSignature(narrower, 1));
});

test('a use of a light chooses its own pattern, and a color recolors it lit and unlit (the R03 case)', () => {
    const library = libraryApi.indexLibrary(manifests());
    const resolve = value => libraryApi.resolveAppearance(library, value, {});
    // A stack light's red lamp that blinks: red when lit, dark red between, never blue.
    const red = resolve({ appearanceId: 'light-stack-red', pattern: 'blink', periodSeconds: 1 });
    assert.deepStrictEqual(red.emission, { color: '#ff3a24', intensity: 1, pattern: 'blink', periodSeconds: 1 });
    assert.strictEqual(red.color, library.appearances.get('light-stack-red').color, 'its own unlit red');
    // Sage's first try borrowed the blinking blue finish and recolored it: now that is red lit and unlit too.
    const borrowed = resolve({ appearanceId: 'light-signal-blue', color: '#ff3a24' });
    assert.deepStrictEqual(borrowed.emission, { color: '#ff3a24', intensity: 1, pattern: 'blink', periodSeconds: 1 });
    assert.strictEqual(borrowed.color, '#801d12', 'unlit: the same red at half brightness, not the blue plastic');
    // steady stops a blinking finish; a pattern and period change it.
    assert.deepStrictEqual(resolve({ appearanceId: 'light-signal-blue', pattern: 'steady' }).emission,
        { color: '#3a86ff', intensity: 1 });
    assert.deepStrictEqual(resolve({ appearanceId: 'light-beacon-amber', pattern: 'strobe', periodSeconds: 2 }).emission,
        { color: '#ffab1f', intensity: 1, pattern: 'strobe', periodSeconds: 2 });
    assert.ok(!resolve({ appearanceId: 'paint-machine-gray', pattern: 'blink', periodSeconds: 1 }).emission,
        'a pattern means nothing on a finish that does not glow');
    const sign = value => libraryApi.finishSignature(resolve(value), 1);
    assert.notStrictEqual(sign({ appearanceId: 'light-stack-red' }),
        sign({ appearanceId: 'light-stack-red', pattern: 'blink', periodSeconds: 1 }), 'a blinking copy has its own material');
    assert.ok(libraryApi.OVERRIDE_FIELDS.includes('pattern') && libraryApi.OVERRIDE_FIELDS.includes('periodSeconds'),
        'the Appearances pane keeps them in a draft');
});

test('lights blink, strobe or turn on one shared clock and change only at fixed marks', () => {
    const library = libraryApi.indexLibrary(manifests());
    const emission = id => libraryApi.resolveAppearance(library, { appearanceId: id }, {}).emission;
    assert.deepStrictEqual(emission('light-beacon-amber'), { color: '#ffab1f', intensity: 1, pattern: 'rotate', periodSeconds: 1 });
    assert.deepStrictEqual(emission('light-alarm-red'), { color: '#ff2b1c', intensity: 1, pattern: 'strobe', periodSeconds: 1 });
    assert.deepStrictEqual(emission('light-signal-blue'), { color: '#3a86ff', intensity: 1, pattern: 'blink', periodSeconds: 1 });
    assert.deepStrictEqual(Array.from(library.appearances.values()).filter(row => row.emission && row.emission.pattern)
        .map(row => row.appearanceId), ['light-beacon-amber', 'light-alarm-red', 'light-signal-blue'], 'the rest are steady');
    // The pattern is part of the finish: a steady copy of the beacon does not share its material.
    const turning = libraryApi.resolveAppearance(library, { appearanceId: 'light-beacon-amber' }, {});
    const still = JSON.parse(JSON.stringify(turning));
    delete still.emission.pattern;
    delete still.emission.periodSeconds;
    assert.notStrictEqual(libraryApi.finishSignature(turning, 1), libraryApi.finishSignature(still, 1));
    const blink = emission('light-signal-blue');
    const strobe = emission('light-alarm-red');
    const rotate = emission('light-beacon-amber');
    const steady = emission('light-stack-green');
    const levels = (glow, times) => times.map(t => finishes.glowLevel(glow, t));
    assert.deepStrictEqual(levels(blink, [0, 0.25, 0.5, 0.99, 1, 7.3]), [1, 1, 0, 0, 1, 1]);
    assert.deepStrictEqual(levels(strobe, [0, 0.05, 0.1, 0.5, 1.02]), [1, 1, 0, 0, 1]);
    assert.deepStrictEqual(levels(rotate, [0, 0.13, 0.26, 0.5, 0.8, 0.9]), [1, 0.55, 0.2, 0.2, 0.2, 0.55]);
    assert.ok(finishes.glowMoves(blink) && !finishes.glowMoves(steady));
    assert.strictEqual(finishes.glowLevel(steady, 0.7), 1);
    assert.strictEqual(finishes.nextGlowChange(steady, 0.7), Infinity);
    const next = (glow, t) => Math.round(finishes.nextGlowChange(glow, t) * 1e6) / 1e6;
    assert.deepStrictEqual([0.1, 0.5, 0.7, 1.2].map(t => next(blink, t)), [0.5, 1, 1, 1.5]);
    assert.deepStrictEqual([0, 0.1, 0.95].map(t => next(strobe, t)), [0.1, 1, 1]);
    // A turning beacon changes only where its brightness steps: 4 times a turn, not 8.
    assert.deepStrictEqual([0, 0.125, 0.25, 0.9].map(t => next(rotate, t)), [0.125, 0.25, 0.875, 1]);
    assert.strictEqual(next(Object.assign({}, blink, { periodSeconds: 2 }), 3.1), 4);
    assert.deepStrictEqual(finishes.GLOW_PATTERNS, ['steady', 'blink', 'strobe', 'rotate']);
});

test('search and scenes follow the manifest; unknown scenes fall back to Classic', () => {
    const library = libraryApi.indexLibrary(manifests());
    assert.deepStrictEqual(libraryApi.search(library, { query: 'kraft' }).map(row => row.id), ['cardboard-kraft']);
    assert.ok(libraryApi.search(library, { category: 'metals' }).every(row => row.category === 'metals'));
    assert.ok(libraryApi.search(library, { kind: 'decal', group: 'warning' }).length >= 8);
    assert.ok(libraryApi.search(library, { kind: 'scene', query: 'machine' }).some(row => row.id === 'machine-shop'));
    const classic = libraryApi.resolveScene(library, null);
    assert.strictEqual(classic.sceneId, 'classic');
    assert.strictEqual(classic.environment, null);
    const shop = libraryApi.resolveScene(library, { version: 1, sceneId: 'machine-shop', adjustments: { shadows: true, exposure: 0.9 } });
    assert.strictEqual(shop.shadows, true);
    assert.strictEqual(shop.exposure, 0.9);
    assert.ok(shop.environmentUrl.endsWith('environments/machine_shop_02_1k.hdr'));
    assert.strictEqual(libraryApi.resolveScene(library, { version: 1, sceneId: 'moon' }).sceneId, 'classic');
    // The lights are on unless the scene switches them off.
    assert.strictEqual(classic.lights, true);
    assert.strictEqual(shop.lights, true);
    assert.strictEqual(libraryApi.resolveScene(library, { version: 1, sceneId: 'machine-shop', adjustments: { lights: false } }).lights,
        false);
    // Only Evening asks for floor light pools.
    assert.strictEqual(libraryApi.resolveScene(library, { version: 1, sceneId: 'evening' }).lightPools, true);
    assert.deepStrictEqual(Array.from(library.scenes.values()).filter(row => row.lightPools).map(row => row.sceneId), ['evening']);
    // The glow halo (L6) is off unless the scene turns it on.
    assert.strictEqual(classic.glowHalo, false);
    assert.strictEqual(libraryApi.resolveScene(library, { version: 1, sceneId: 'evening' }).glowHalo, false);
    assert.strictEqual(libraryApi.resolveScene(library, { version: 1, sceneId: 'evening', adjustments: { glowHalo: true } })
        .glowHalo, true);
});

test('layout usage lists object and part finishes, the scene and both decal kinds', () => {
    const library = libraryApi.indexLibrary(manifests());
    const layout = {
        placements: [
            { placementId: 'pl-a', appearance: { appearanceId: 'wood-oak' } },
            { placementId: 'pl-b', appearance: { color: '#123456' }, componentMaterials: { representation: 'detail', overrides: [
                { key: 'p:Seat#0', appearanceId: 'fabric-woven-navy' }, { key: 'm1-s0', color: '#000000', roughness: 1, metalness: 0 }] } },
        ],
        extensions: { facilityScene: { version: 1, sceneId: 'warehouse' }, facilityDecals: { version: 1, artworks: [{}, {}] },
            facilityEquipmentDecals: { version: 1, decals: [{ decalId: 'edecal-1', placementId: 'pl-a' }] } },
    };
    const usage = libraryApi.layoutUsage(library, layout);
    assert.deepStrictEqual(usage.appearances.map(row => [row.appearanceId, row.placementIds, row.partCount]),
        [['wood-oak', ['pl-a'], 0], ['fabric-woven-navy', ['pl-b'], 1]]);
    assert.strictEqual(usage.plainColors, 1);
    assert.strictEqual(usage.sceneLabel, 'Warehouse');
    assert.strictEqual(usage.wallDecals, 2);
    assert.strictEqual(usage.equipmentDecals.length, 1);
});

test('favorites and recents survive storage that is empty, full or blocked', () => {
    const memory = new Map();
    const storage = { getItem: key => memory.get(key) || null, setItem: (key, value) => memory.set(key, value) };
    const prefs = libraryApi.createPreferences(storage);
    assert.strictEqual(prefs.toggleFavorite('appearance', 'wood-oak'), true);
    prefs.pushRecent('scene', 'warehouse');
    prefs.pushRecent('appearance', 'wood-oak');
    prefs.pushRecent('scene', 'warehouse');
    const reread = libraryApi.createPreferences(storage);
    assert.ok(reread.isFavorite('appearance', 'wood-oak'));
    assert.deepStrictEqual(reread.recents(), [{ kind: 'scene', id: 'warehouse' }, { kind: 'appearance', id: 'wood-oak' }]);
    const blocked = libraryApi.createPreferences({ getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } });
    assert.strictEqual(blocked.toggleFavorite('decal', 'iso7010-w001'), true);
    assert.deepStrictEqual(blocked.favorites(), [{ kind: 'decal', id: 'iso7010-w001' }]);
});

test('grain axis follows the long horizontal side, the short one, or height', () => {
    const rack = { min: { x: 0, y: 0, z: 0 }, max: { x: 0.6, y: 2, z: 3 } };
    assert.strictEqual(finishes.grainAxis(rack, 'length'), 'z');
    assert.strictEqual(finishes.grainAxis(rack, 'width'), 'x');
    assert.strictEqual(finishes.grainAxis(rack, 'height'), 'y');
});

test('box UVs are meters along the grain on every face, so scale is physical', () => {
    // Two triangles: one on a top face (normal +y) and one on a front face (normal +z).
    const top = [0, 1, 0, 0, 1, 1, 3, 1, 0];
    const front = [0, 0, 1, 3, 0, 1, 0, 2, 1];
    const uv = finishes.boxUVs(new Float32Array(top.concat(front)), 'x');
    assert.deepStrictEqual(Array.from(uv.slice(0, 6)), [0, 0, 0, 1, 3, 0], 'top face: U = x, V = z');
    assert.deepStrictEqual(Array.from(uv.slice(6, 12)), [0, 0, 3, 0, 0, 2], 'front face: U = x, V = y');
    // An end-grain face (normal along the grain axis) still gets a stable mapping.
    const end = finishes.boxUVs(new Float32Array([2, 0, 0, 2, 0, 1, 2, 1, 0]), 'x');
    assert.deepStrictEqual(Array.from(end), [0, 0, 1, 0, 0, 1]);
});

test('cylindrical UVs unwrap the seam instead of smearing a whole triangle', () => {
    const triangle = new Float32Array([0, -1, -0.01, 1, -1, 0.01, 0, -1, 0.01]);
    const uv = finishes.cylindricalUVs(triangle, 'x', [0, 0, 0], 1);
    const v = [uv[1], uv[3], uv[5]];
    assert.ok(Math.max(...v) - Math.min(...v) < 0.1, 'angles near +-pi stay together: ' + v.join(','));
});

async function runThreeTests() {
    const THREE = await import(pathToFileURL(path.join(ROOT, 'static/vendor/three/0.184.0/build/three.module.min.js')).href);
    const library = libraryApi.indexLibrary(manifests());

    const box = new THREE.BoxGeometry(2, 1, 0.5);
    const projected = finishes.finishGeometry(THREE, box, null, { mapping: 'box', axis: 'x' });
    assert.strictEqual(projected.index, null, 'faces are split so each keeps its own projection');
    assert.strictEqual(projected.attributes.uv.count, projected.attributes.position.count);
    const us = Array.from(projected.attributes.uv.array).filter((_, i) => i % 2 === 0);
    assert.ok(Math.abs(Math.max(...us) - Math.min(...us) - 2) < 1e-6, 'a 2 m box spans 2 m of texture along the grain');
    const twice = finishes.finishGeometry(THREE, box, new THREE.Matrix4().makeScale(2, 2, 2), { mapping: 'box', axis: 'x' });
    const us2 = Array.from(twice.attributes.uv.array).filter((_, i) => i % 2 === 0);
    assert.ok(Math.abs(Math.max(...us2) - Math.min(...us2) - 4) < 1e-6, 'bigger objects show more of the texture, not a stretched copy');
    assert.strictEqual(box.attributes.uv.count, 24, 'the shared source geometry is untouched');

    // A bare bounds box (positions only, as some catalog overviews ship) gets
    // flat normals on its finish copy; without them a normal map renders black.
    const bare = new THREE.BufferGeometry();
    bare.setAttribute('position', new THREE.Float32BufferAttribute([-0.5, 0, -0.5, 0.5, 0, -0.5, 0.5, 0.7, -0.5, -0.5, 0.7, -0.5,
        -0.5, 0, 0.5, 0.5, 0, 0.5, 0.5, 0.7, 0.5, -0.5, 0.7, 0.5], 3));
    bare.setIndex([0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 3, 7, 6, 3, 6, 2, 0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5]);
    const lit = finishes.finishGeometry(THREE, bare, null, { mapping: 'box', axis: 'x' });
    assert.ok(lit.attributes.normal, 'the finish copy has normals');
    const normals = lit.attributes.normal.array;
    for (let i = 0; i < normals.length; i += 9) {
        const length = Math.hypot(normals[i], normals[i + 1], normals[i + 2]);
        assert.ok(Math.abs(length - 1) < 1e-6, 'unit normals');
        assert.deepStrictEqual(Array.from(normals.slice(i, i + 3)), Array.from(normals.slice(i + 6, i + 9)), 'flat per face');
    }
    assert.strictEqual(bare.attributes.normal, undefined, 'the shared bounds box itself is untouched');

    const requested = [];
    const fakeTextures = {
        instance(url, colorSpace, transform, onFailed) {
            const texture = new THREE.Texture();
            texture.userData.url = url;
            texture.colorSpace = colorSpace;
            texture.repeat.set(transform.repeat, transform.repeat);
            texture.rotation = transform.rotation;
            requested.push({ url, colorSpace, transform, onFailed, texture });
            return url.includes('missing') ? null : texture;
        },
    };
    const oak = libraryApi.resolveAppearance(library, { appearanceId: 'wood-oak', sizeMeters: 0.5, rotationDegrees: 90 }, {});
    const material = finishes.createFinishMaterial(THREE, oak, { textures: fakeTextures, scale: 1 });
    assert.ok(material.isMeshStandardMaterial && finishes.isFinishMaterial(material));
    assert.strictEqual(material.map.colorSpace, THREE.SRGBColorSpace, 'color maps are sRGB');
    assert.strictEqual(material.normalMap.colorSpace, THREE.NoColorSpace, 'normal maps are linear data');
    assert.strictEqual(material.roughnessMap.colorSpace, THREE.NoColorSpace);
    assert.strictEqual(material.map.repeat.x, 2, '0.5 m tiles repeat twice per meter');
    assert.ok(Math.abs(material.map.rotation - Math.PI / 2) < 1e-9);
    const mean = library.textureSets.get('wood-oak').roughnessMean;
    assert.ok(Math.abs(material.roughness * mean - oak.roughness) < 1e-6, 'roughness is the average after the map');

    const glass = finishes.createFinishMaterial(THREE, libraryApi.resolveAppearance(library, { appearanceId: 'glass-clear' }, {}), {});
    assert.ok(glass.isMeshPhysicalMaterial && glass.transmission === 1 && Math.abs(glass.ior - 1.5) < 1e-9);
    const missing = finishes.createFinishMaterial(THREE, { appearanceId: 'custom-x', missing: true }, {});
    assert.deepStrictEqual(missing.userData.fallback, ['appearance_missing']);

    // A light glows in its glow color, kept out of tone mapping so it reads as switched on in any scene; the
    // flag survives the copy the instanced path makes, and other finishes neither glow nor change tone mapping.
    const led = finishes.createFinishMaterial(THREE, libraryApi.resolveAppearance(library, { appearanceId: 'light-cool-white-led' }, {}), {});
    assert.strictEqual(led.emissive.getHexString(), 'eef4ff');
    assert.strictEqual(led.emissiveIntensity, 1);
    assert.strictEqual(led.toneMapped, false);
    assert.strictEqual(led.color.getHexString(), 'dfe4e8', 'the base color is the unlit lens');
    assert.ok(finishes.isGlowMaterial(led) && finishes.isFinishMaterial(led));
    assert.deepStrictEqual(led.userData.facilityGlow, { color: '#eef4ff', intensity: 1 });
    const copy = led.clone();
    assert.ok(finishes.isGlowMaterial(copy) && copy.toneMapped === false && copy.emissive.getHexString() === 'eef4ff');
    const amber = finishes.createFinishMaterial(THREE,
        libraryApi.resolveAppearance(library, { appearanceId: 'light-beacon-amber', color: '#ff9900' }, {}), {});
    assert.strictEqual(amber.emissive.getHexString(), 'ff9900');
    assert.deepStrictEqual(amber.userData.facilityGlow, { color: '#ff9900', intensity: 1, pattern: 'rotate', periodSeconds: 1 },
        'a light that turns keeps its pattern with the glow');
    assert.ok(finishes.glowMoves(amber.userData.facilityGlow) && !finishes.glowMoves(led.userData.facilityGlow));
    const paint = finishes.createFinishMaterial(THREE, libraryApi.resolveAppearance(library, { appearanceId: 'paint-machine-gray' }, {}), {});
    assert.ok(!finishes.isGlowMaterial(paint) && paint.toneMapped === true && paint.emissive.getHex() === 0);

    const broken = JSON.parse(JSON.stringify(oak));
    broken.texture.maps.color = '/static/facility_library/textures/missing/color.jpg';
    const fallback = finishes.createFinishMaterial(THREE, broken, { textures: fakeTextures });
    assert.strictEqual(fallback.map, null, 'a missing color map falls back to the tint');
    assert.ok(fallback.userData.fallback.includes('color_texture_missing'));

    const prototype = new THREE.Group();
    const part = new THREE.Mesh(new THREE.BoxGeometry(3, 1, 1), new THREE.MeshStandardMaterial());
    part.position.set(1, 0, 0);
    const art = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial());
    art.material.userData.facilityAuthoredFinish = true;
    prototype.add(part, art);
    const mapping = finishes.mappingFor(THREE, prototype, oak);
    assert.strictEqual(mapping.axis, 'x');
    const cache = new Map();
    const skip = item => item.userData && item.userData.facilityAuthoredFinish;
    const first = prototype.clone(true), second = prototype.clone(true);
    finishes.applyFinishToObject(THREE, first, material, mapping, { geometryCache: cache, skip });
    finishes.applyFinishToObject(THREE, second, material, mapping, { geometryCache: cache, skip });
    assert.strictEqual(first.children[0].material, material);
    assert.ok(first.children[0].geometry.attributes.uv && first.children[0].geometry.userData.facilityFinishGeometry);
    assert.notStrictEqual(first.children[1].material, material, 'authored artwork keeps its own material');
    assert.strictEqual(part.material.isMeshStandardMaterial && part.material !== material, true, 'the prototype is untouched');
    assert.strictEqual(cache.size, 1, 'clones of one prototype reuse the projected geometry');
    assert.strictEqual(first.children[0].geometry, second.children[0].geometry);

    // Per-part grain: a vertical post and a horizontal beam each run along their own length.
    const table = new THREE.Group();
    const post = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.9, 0.06), new THREE.MeshStandardMaterial());
    const beam = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.05, 1.6), new THREE.MeshStandardMaterial());
    beam.position.set(0, 0.9, 0.8);
    table.add(post, beam);
    const partGrain = finishes.mappingFor(THREE, table, oak);
    assert.strictEqual(partGrain.perPart, true);
    finishes.applyFinishToObject(THREE, table, material, partGrain, { geometryCache: new Map() });
    const spanOf = (mesh, component) => {
        const values = Array.from(mesh.geometry.attributes.uv.array).filter((_, i) => i % 2 === component);
        return Math.max(...values) - Math.min(...values);
    };
    assert.ok(Math.abs(spanOf(post, 0) - 0.9) < 1e-6, 'the post grain (U) runs up the post');
    // The beam runs from z 0 to 1.6 in the table's space; its end faces are end grain.
    const beamU = Array.from(beam.geometry.attributes.uv.array).filter((_, i) => i % 2 === 0);
    assert.ok(Math.abs(Math.max(...beamU) - 1.6) < 1e-6, 'the beam grain (U) runs along the beam');
    assert.strictEqual(finishes.partAxis(THREE, beam.geometry, beam.matrixWorld), 'z');

    // Part keys: the browser tags meshes exactly as the server's component
    // inventory names them (tests/test_codex_component_inventory.py uses this glTF).
    const components = require('../static/facility_layout_component_materials.js');
    const json = { scene: 0, scenes: [{ nodes: [0, 2] }],
        nodes: [{ name: 'Frame', mesh: 1, children: [1] }, { name: 'Seat', mesh: 0 }, { name: 'Guide', mesh: 0 }],
        meshes: [{ primitives: [{}] }, { primitives: [{}, {}] }] };
    const associations = new Map();
    const meshPart = () => new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial());
    const frame = new THREE.Group(), primitiveA = meshPart(), primitiveB = meshPart(), seat = meshPart(), guide = meshPart();
    frame.add(primitiveA, primitiveB, seat);
    associations.set(frame, { meshes: 1, nodes: 0 });
    associations.set(primitiveA, { meshes: 1, primitives: 0 });
    associations.set(primitiveB, { meshes: 1, primitives: 1 });
    associations.set(seat, { meshes: 0, primitives: 0, nodes: 1 });
    associations.set(guide, { meshes: 0, primitives: 0, nodes: 2 });
    const gltfScene = new THREE.Group();
    gltfScene.add(frame, guide);
    assert.strictEqual(components.annotatePartKeys({ scene: gltfScene, parser: { json, associations } }), 4);
    assert.deepStrictEqual([primitiveA, primitiveB, seat, guide].map(mesh => mesh.userData.facilityPartKey),
        ['p:Frame#0', 'p:Frame#1', 'p:Frame/Seat#0', 'p:Guide#0']);
    assert.strictEqual(components.encodeName('Rack Bay~2/A'), 'Rack%20Bay%7E2%2FA');
    const repeated = components.nodePaths({ scene: 0, scenes: [{ nodes: [0] }],
        nodes: [{ name: 'Rack Bay', children: [1, 2, 3] }, { name: 'Shelf' }, { name: 'Shelf' }, {}] });
    assert.deepStrictEqual([1, 2, 3].map(index => repeated.get(index).path),
        ['Rack%20Bay/Shelf~0', 'Rack%20Bay/Shelf~1', 'Rack%20Bay/@3']);
    const tagged = gltfScene.clone(true);
    const slots = components.slots(tagged);
    assert.deepStrictEqual(slots.map(slot => slot.key), ['p:Frame#0', 'p:Frame#1', 'p:Frame/Seat#0', 'p:Guide#0'],
        'keys survive cloning');
    assert.deepStrictEqual(slots.map(slot => slot.legacyKey), ['m0-s0', 'm1-s0', 'm2-s0', 'm3-s0']);
    const applied = components.apply(tagged, { representation: 'overview', overrides: [
        { key: 'p:Frame/Seat#0', appearanceId: 'fabric-woven-navy' },
        { key: 'm3-s0', color: '#aabbcc', roughness: 0.4, metalness: 0 },
    ] }, 'detail', { materialFor: () => new THREE.MeshStandardMaterial({ color: 0x33415e }) });
    assert.deepStrictEqual(applied, ['p:Frame/Seat#0'],
        'stable keys apply on any representation; legacy keys only on the one they were made for');

    // A finished part keeps the depth offset of the material it replaces (authored surfaces draw pulled forward),
    // so a lens just under its housing stays visible; a part that had no offset gets none.
    const lamp = new THREE.Group(), lens = meshPart(), plate = meshPart();
    Object.assign(lens.material, { polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 });
    lens.userData.facilityPartKey = 'p:row/lens#0';
    plate.userData.facilityPartKey = 'p:row/plate#0';
    lamp.add(lens, plate);
    components.apply(lamp, { representation: 'detail', overrides: [
        { key: 'p:row/lens#0', appearanceId: 'light-cool-white-led' }, { key: 'p:row/plate#0', appearanceId: 'paint-machine-gray' },
    ] }, 'detail', { materialFor: () => new THREE.MeshStandardMaterial() });
    assert.ok(lens.material.userData.facilityComponentOverride && lens.material.polygonOffset
        && lens.material.polygonOffsetFactor === -1 && lens.material.polygonOffsetUnits === -1);
    assert.ok(plate.material.userData.facilityComponentOverride && plate.material.polygonOffset === false);

    // A model's default part finish (a light's lens that comes lit, glTF extras facilityDefaultFinish): recorded on
    // the freshly loaded model, kept by its copies, applied under the placement's own part finishes.
    const fitting = new THREE.Group(), ledLens = meshPart(), ledHead = meshPart();
    ledLens.material.userData = { facilityAuthoredFinish: true, facilityDefaultFinish: 'light-pole-led' };
    ledLens.userData.facilityPartKey = 'p:pole-light/led%20lens#0';
    ledHead.userData.facilityPartKey = 'p:pole-light/led%20head#0';
    fitting.add(ledLens, ledHead);
    assert.deepStrictEqual(components.recordDefaults(fitting), [{ key: 'p:pole-light/led%20lens#0', appearanceId: 'light-pole-led' }]);
    const finishedWithId = { materialFor: v => new THREE.MeshStandardMaterial({ name: v.appearanceId }) };
    const litCopy = fitting.clone(true);
    assert.deepStrictEqual(components.defaults(litCopy), components.defaults(fitting), 'copies keep the defaults');
    assert.deepStrictEqual(components.apply(litCopy, null, 'overview', finishedWithId), ['p:pole-light/led%20lens#0'],
        'no part finish of its own: the lens still gets its default');
    assert.strictEqual(litCopy.children[0].material.name, 'light-pole-led');
    assert.strictEqual(litCopy.children[1].material, ledHead.material, 'parts without a default keep their material');
    const ownCopy = fitting.clone(true);
    components.apply(ownCopy, { representation: 'overview', overrides: [{ key: 'p:pole-light/led%20lens#0', appearanceId: 'light-dock-led' }] },
        'overview', finishedWithId);
    assert.strictEqual(ownCopy.children[0].material.name, 'light-dock-led', "the placement's own part finish wins");
    const legacyCopy = fitting.clone(true);
    components.apply(legacyCopy, { representation: 'overview', overrides: [{ key: 'm0-s0', color: '#102030', roughness: 0.5, metalness: 0 }] },
        'overview', finishedWithId);
    assert.strictEqual(legacyCopy.children[0].material.color.getHexString(), '102030', 'so does a legacy key on its own representation');
    assert.deepStrictEqual(components.apply(new THREE.Group(), null, 'overview', finishedWithId), [], 'nothing to apply');

    // A stack light's three lamps are one finish group (extras facilityFinishGroup): the green lamp's default shows
    // only while none of them has a finish of its own, since one lamp shows the cell's state.
    const stack = new THREE.Group(), stackGreen = meshPart(), stackAmber = meshPart(), stackPole = meshPart();
    stackGreen.material.userData = { facilityAuthoredFinish: true, facilityDefaultFinish: 'light-stack-green', facilityFinishGroup: 'stack lamps' };
    stackAmber.material.userData = { facilityAuthoredFinish: true, facilityFinishGroup: 'stack lamps' };
    stackGreen.userData.facilityPartKey = 'p:stack-light/green%20lamp#0';
    stackAmber.userData.facilityPartKey = 'p:stack-light/amber%20lamp#0';
    stackPole.userData.facilityPartKey = 'p:stack-light/pole#0';
    stack.add(stackGreen, stackAmber, stackPole);
    assert.deepStrictEqual(components.recordDefaults(stack),
        [{ key: 'p:stack-light/green%20lamp#0', appearanceId: 'light-stack-green', group: 'stack lamps' }]);
    const newStack = stack.clone(true);
    assert.deepStrictEqual(components.apply(newStack, null, 'overview', finishedWithId), ['p:stack-light/green%20lamp#0'],
        'a new stack light comes green');
    assert.strictEqual(newStack.children[0].material.name, 'light-stack-green');
    const amberStack = stack.clone(true);
    assert.deepStrictEqual(components.apply(amberStack, { representation: 'overview', overrides: [
        { key: 'p:stack-light/amber%20lamp#0', appearanceId: 'light-stack-amber' }] }, 'overview', finishedWithId),
    ['p:stack-light/amber%20lamp#0'], 'set to amber: amber alone');
    assert.strictEqual(amberStack.children[0].material, stackGreen.material, 'its green lamp stays unlit');
    const legacyAmber = stack.clone(true);
    components.apply(legacyAmber, { representation: 'overview', overrides: [{ key: 'm1-s0', appearanceId: 'light-stack-amber' }] },
        'overview', finishedWithId);
    assert.strictEqual(legacyAmber.children[0].material, stackGreen.material, 'so does a legacy key on its own representation');
    const poleStack = stack.clone(true);
    components.apply(poleStack, { representation: 'overview', overrides: [{ key: 'p:stack-light/pole#0', appearanceId: 'paint-machine-gray' }] },
        'overview', finishedWithId);
    assert.strictEqual(poleStack.children[0].material.name, 'light-stack-green', 'a part outside the group leaves it on');
    const bothStack = stack.clone(true);
    components.apply(bothStack, { representation: 'overview', overrides: [
        { key: 'p:stack-light/green%20lamp#0', appearanceId: 'light-stack-green' },
        { key: 'p:stack-light/amber%20lamp#0', appearanceId: 'light-stack-amber' }] }, 'overview', finishedWithId);
    assert.strictEqual(bothStack.children[0].material.name, 'light-stack-green', 'green as its own finish stays on');
}

(async () => {
    let failed = 0;
    for (const [name, fn] of tests) {
        try { fn(); console.log('ok -', name); } catch (error) { failed += 1; console.error('FAIL -', name, '\n', error); }
    }
    try { await runThreeTests(); console.log('ok - three.js geometry and materials'); }
    catch (error) { failed += 1; console.error('FAIL - three.js geometry and materials\n', error); }
    console.log(failed ? failed + ' failed' : 'all passed');
    process.exitCode = failed ? 1 : 0;
})();
