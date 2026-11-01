'use strict';

// Appearances, Scenes and Decals panel: browsing, search, live preview, apply,
// part finishes, scenes, decals and custom finishes, against a tiny DOM and
// fakes for the workspace session and 3D adapter.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const libraryApi = require('../static/facility_layout_library.js');
const panelApi = require('../static/facility_layout_library_panel.js');

// ------------------------------------------------------------ tiny DOM --
function makeDocument() {
    const doc = { listeners: Object.create(null), activeElement: null };
    function matches(node, selector) {
        const match = /^\.([\w-]+)(?:\[([\w-]+)="([^"]*)"\])?$/.exec(selector);
        if (!match) throw new Error('Unsupported selector ' + selector);
        if (!(' ' + node.className + ' ').includes(' ' + match[1] + ' ')) return false;
        return !match[2] || node.getAttribute(match[2]) === match[3];
    }
    function walk(node, visit) {
        node.children.forEach(function (child) { visit(child); walk(child, visit); });
    }
    function element(tag) {
        const node = {
            tagName: String(tag).toUpperCase(), children: [], attributes: Object.create(null), parentNode: null,
            className: '', listeners: Object.create(null), hidden: false, value: '', checked: false, disabled: false,
            style: { values: {}, setProperty(key, value) { this.values[key] = value; } },
            ownerDocument: doc,
            get textContent() { return this._text || this.children.map(child => child.textContent).join(''); },
            set textContent(value) { this.children.forEach(child => { child.parentNode = null; }); this.children = []; this._text = String(value); },
            classList: {
                add(name) { if (!this.contains(name)) node.className = (node.className + ' ' + name).trim(); },
                remove(name) { node.className = node.className.split(' ').filter(item => item !== name).join(' '); },
                contains(name) { return node.className.split(' ').includes(name); },
            },
            append(...items) { items.forEach(item => this.appendChild(item)); },
            appendChild(child) {
                if (child.parentNode) child.parentNode.removeChild(child);
                child.parentNode = this; this.children.push(child); this._text = ''; return child;
            },
            removeChild(child) {
                const index = this.children.indexOf(child);
                if (index >= 0) this.children.splice(index, 1);
                child.parentNode = null; return child;
            },
            setAttribute(key, value) {
                this.attributes[key] = String(value);
                if (key === 'value') this.value = String(value);
                if (key === 'disabled') this.disabled = true;
                if (key === 'selected' && this.parentNode) this.parentNode.value = this.attributes.value;
            },
            getAttribute(key) { return key in this.attributes ? this.attributes[key] : null; },
            addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
            removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter(item => item !== fn); },
            dispatch(type, extra) {
                const event = Object.assign({ type, target: this, defaultPrevented: false,
                    preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} }, extra || {});
                (this.listeners[type] || []).slice().forEach(fn => fn(event));
                return event;
            },
            querySelectorAll(selector) { const found = []; walk(this, child => { if (matches(child, selector)) found.push(child); }); return found; },
            querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
            focus() { doc.activeElement = this; },
            select() {},
            getContext() { return { drawImage() {} }; },
            toBlob(callback, type) { callback({ size: 2048, type }); },
        };
        return node;
    }
    doc.createElement = element;
    doc.addEventListener = function (type, fn) { (doc.listeners[type] = doc.listeners[type] || []).push(fn); };
    doc.removeEventListener = function (type, fn) { doc.listeners[type] = (doc.listeners[type] || []).filter(item => item !== fn); };
    doc.defaultView = {
        crypto: { randomUUID: () => 'abc123de-f456-7890' },
        Image: class { set src(value) { this._src = value; Promise.resolve().then(() => this.onload && this.onload()); } get src() { return this._src; } },
    };
    return doc;
}

function find(root, predicate) {
    let found = null;
    (function visit(node) { node.children.forEach(child => { if (!found && predicate(child)) found = child; visit(child); }); }(root));
    return found;
}
function findAll(root, predicate) {
    const found = [];
    (function visit(node) { node.children.forEach(child => { if (predicate(child)) found.push(child); visit(child); }); }(root));
    return found;
}
function buttonNamed(root, text) {
    return find(root, node => node.tagName === 'BUTTON' && node.textContent === text);
}

function library() {
    const read = name => JSON.parse(fs.readFileSync(path.join(ROOT, 'static/facility_library', name + '.json'), 'utf8'));
    return libraryApi.indexLibrary({ appearances: read('appearances'), scenes: read('scenes'), decals: read('decals') });
}

function harness(options) {
    const settings = options || {};
    const doc = makeDocument();
    const host = doc.createElement('div');
    const lib = library();
    const store = { get: () => lib, load: () => Promise.resolve(lib), error: () => null, subscribe: () => () => {} };
    const memory = new Map();
    const preferences = libraryApi.createPreferences({ getItem: key => memory.get(key) || null, setItem: (key, value) => memory.set(key, value) });
    const calls = [];
    const layout = settings.layout || { layoutId: 'fl-test', placements: [
        { placementId: 'pl-a', assetId: 'asset-rack', metadata: { instanceLabel: 'Rack A' } },
        { placementId: 'pl-b', assetId: 'asset-rack', metadata: { instanceLabel: 'Rack B' },
            componentMaterials: { representation: 'detail', overrides: [
                { key: 'm0-s0', color: '#000000', roughness: 1, metalness: 0 },
                { key: 'p:Frame#0', color: '#111111', roughness: 1, metalness: 0 }] } },
        { placementId: 'pl-wall', assetId: 'asset-wall', metadata: {} },
    ], extensions: {} };
    const state = { selection: settings.selection || ['pl-a', 'pl-b'], canEdit: settings.canEdit !== false, layout };
    const listeners = new Set();
    const session = {
        subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
        async setPlacementsAppearance(ids, value) { calls.push(['setPlacementsAppearance', ids, value]); },
        async setComponentMaterials(id, value) { calls.push(['setComponentMaterials', id, value]); },
        async setViewportScene(value) { calls.push(['setViewportScene', value]); },
        async setCustomAppearances(value) { calls.push(['setCustomAppearances', value]); },
        async setEquipmentDecals(value) { calls.push(['setEquipmentDecals', value]); },
        async importDecalImage(blob) { calls.push(['importDecalImage', blob.type]); return { imagePath: '/api/facility-decal-images/site-a/' + 'c'.repeat(64) + '.png', uv: [0, 0, 1, 1] }; },
    };
    const dropTarget = doc.createElement('div');
    const adapter = {
        previewFinish(spec) { calls.push(['previewFinish', spec]); return true; },
        clearFinishPreview() { calls.push(['clearFinishPreview']); return true; },
        previewViewportScene(value) { calls.push(['previewViewportScene', value]); return true; },
        clearViewportScenePreview() { calls.push(['clearViewportScenePreview']); return true; },
        highlightComponent(id, key) { calls.push(['highlightComponent', id, key]); },
        async getComponentMaterials(id) {
            calls.push(['getComponentMaterials', id]);
            return { representation: 'detail', slots: [
                { key: 'p:Frame#0', legacyKey: 'm0-s0', label: 'Frame / Steel' },
                { key: 'p:Frame/Seat#0', legacyKey: 'm1-s0', label: 'Seat / Fabric' }] };
        },
        pick() { return settings.hit || null; },
        decalAnchorAt(input, rotation) {
            return settings.hit ? { placementId: settings.hit.placementId,
                anchor: { position: { x: 0, y: 1, z: 0.3 }, normal: { x: 0, y: 0, z: 1 }, rotationDegrees: rotation } } : null;
        },
    };
    const wallOpens = [];
    const draws = [];
    const workspace = {
        session,
        subscribeStructure(fn) { listeners.add(fn); return () => listeners.delete(fn); },
        appearanceLibraryContext() {
            return { session, threeAdapter: adapter, document: doc, assetCatalog: settings.assetCatalog || [], layout: state.layout,
                selection: state.selection.slice(), canEdit: state.canEdit, viewMode: '3d', dropTarget,
                show3d() {}, openWallDecals(prefill) { wallOpens.push(prefill); },
                drawLightArea(done) { draws.push(done); return true; },
                isWallAsset: id => id === 'pl-wall', ...(settings.context ? settings.context() : {}) };
        },
    };
    const panel = panelApi.createLibraryPanel({ document: doc, host, store, preferences });
    panel.bind(workspace);
    return { doc, host, panel, calls, state, preferences, dropTarget, wallOpens, draws, notify() { listeners.forEach(fn => fn()); } };
}

async function settle(ms) {
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
    if (ms) await new Promise(resolve => setTimeout(resolve, ms));
}

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('the tree arranges favorites, recents, layout use and the three libraries like a task pane', async () => {
    const h = harness();
    const labels = findAll(h.host, node => node.className === 'ip-flib-node-label').map(node => node.textContent);
    assert.deepStrictEqual(labels.slice(0, 4), ['Favorites', 'Recent', 'In this layout', 'Appearances']);
    ['Metals', 'Plastics', 'Wood', 'Rubber', 'Glass', 'Fabric', 'Paper & Cardboard', 'Paint & Coatings', 'Concrete & Stone',
        'Lights'].forEach(label => assert.ok(labels.includes(label), label));
    assert.ok(labels.includes('Scenes') && labels.includes('Decals'));
    const names = findAll(h.host, node => node.className === 'ip-flib-name').map(node => node.textContent);
    assert.ok(names.includes('Brushed steel') && names.every(name => !/Oak/.test(name)), 'Metals is the first folder');
    const search = find(h.host, node => node.className === 'ip-flib-search');
    search.value = 'machine';
    search.dispatch('input');
    const results = findAll(h.host, node => node.className === 'ip-flib-name').map(node => node.textContent);
    assert.ok(results.includes('Machine shop') && results.includes('Machine gray enamel'), 'search spans finishes and scenes');
});

test('selecting a finish previews it on the selection and Apply saves only the changes made', async () => {
    const h = harness();
    assert.ok(h.panel.select('appearance', 'wood-oak'));
    await settle(120);
    const preview = h.calls.filter(call => call[0] === 'previewFinish').at(-1);
    assert.deepStrictEqual(preview[1], { placementIds: ['pl-a', 'pl-b'], appearance: { appearanceId: 'wood-oak' } });
    assert.ok(find(h.host, node => node.tagName === 'BUTTON' && node.textContent === 'Selected objects (2)'));
    const partButton = buttonNamed(h.host, 'One part');
    assert.ok(partButton.disabled, 'part scope needs exactly one object');
    h.panel.setDraft({ sizeMeters: 0.5, grain: 'width' });
    buttonNamed(h.host, 'Apply').dispatch('click');
    await settle();
    const saved = h.calls.find(call => call[0] === 'setPlacementsAppearance');
    assert.deepStrictEqual(saved.slice(1), [['pl-a', 'pl-b'], { appearanceId: 'wood-oak', sizeMeters: 0.5, grain: 'width' }]);
    assert.deepStrictEqual(h.preferences.recents()[0], { kind: 'appearance', id: 'wood-oak' });
    buttonNamed(h.host, 'Reset').dispatch('click');
    await settle();
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'setPlacementsAppearance').at(-1).slice(1), [['pl-a', 'pl-b'], null]);
});

test('a light shows its glow color, and changing it previews and saves as the color override', async () => {
    const h = harness({ selection: ['pl-a'] });
    assert.ok(h.panel.select('appearance', 'light-exit-green'));
    await settle(120);
    const labels = findAll(h.host, node => node.className === 'ip-flib-field-label').map(node => node.textContent);
    assert.ok(labels.includes('Glow color') && !labels.includes('Color') && !labels.includes('Tint'), labels.join());
    const glow = find(h.host, node => node.tagName === 'INPUT' && node.getAttribute('aria-label') === 'Glow color');
    assert.strictEqual(glow.value, '#2bea74', 'the field starts at the glow, not the switched-off plastic');
    assert.ok(findAll(h.host, node => node.className === 'ip-flib-source')
        .some(node => /lights no other surface/.test(node.textContent)));
    glow.value = '#33FF88';
    glow.dispatch('input');
    await settle(120);
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'previewFinish').at(-1)[1],
        { placementIds: ['pl-a'], appearance: { appearanceId: 'light-exit-green', color: '#33ff88' } });
    buttonNamed(h.host, 'Apply').dispatch('click');
    await settle();
    assert.deepStrictEqual(h.calls.find(call => call[0] === 'setPlacementsAppearance').slice(1),
        [['pl-a'], { appearanceId: 'light-exit-green', color: '#33ff88' }]);
    assert.ok(h.panel.select('appearance', 'paint-machine-gray'));
    await settle(120);
    assert.ok(find(h.host, node => node.tagName === 'INPUT' && node.getAttribute('aria-label') === 'Color'),
        'other finishes keep their plain color field');
});

test('one-part scope lists real parts and replaces only that part, including its legacy key', async () => {
    const h = harness({ selection: ['pl-b'] });
    h.panel.open({ node: 'appearances', scope: 'part' });
    await settle();
    h.panel.select('appearance', 'fabric-woven-navy');
    await settle(120);
    assert.strictEqual(h.panel.state().scope, 'part');
    assert.strictEqual(h.panel.state().partKey, 'p:Frame#0');
    const partSelect = find(h.host, node => node.tagName === 'SELECT' && node.getAttribute('aria-label') === 'Part');
    partSelect.value = 'p:Frame/Seat#0';
    partSelect.dispatch('change');
    await settle(120);
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'previewFinish').at(-1)[1],
        { placementIds: ['pl-b'], partKey: 'p:Frame/Seat#0', appearance: { appearanceId: 'fabric-woven-navy' } });
    h.panel.state();
    partSelect.value = 'p:Frame#0';
    partSelect.dispatch('change');
    buttonNamed(h.host, 'Apply').dispatch('click');
    await settle();
    const saved = h.calls.find(call => call[0] === 'setComponentMaterials');
    assert.strictEqual(saved[1], 'pl-b');
    assert.deepStrictEqual(saved[2], { representation: 'detail', overrides: [
        { key: 'p:Frame#0', appearanceId: 'fabric-woven-navy' }] }, 'the legacy m0-s0 and stable key for the same part are replaced');
});

test('the part outline goes when part scope ends, and messages name objects by their catalog name', async () => {
    const h = harness({ selection: ['pl-c'], assetCatalog: [{ assetId: 'asset-mill', label: 'Haas VF-4' }],
        layout: { layoutId: 'fl-test', placements: [{ placementId: 'pl-c', assetId: 'asset-mill', metadata: {} }], extensions: {} } });
    h.panel.open({ node: 'appearances', scope: 'part' });
    await settle();
    h.panel.select('appearance', 'paint-safety-yellow');
    await settle(120);
    const outlines = () => h.calls.filter(call => call[0] === 'highlightComponent');
    assert.deepStrictEqual(outlines().at(-1), ['highlightComponent', 'pl-c', 'p:Frame#0']);
    buttonNamed(h.host, 'Apply').dispatch('click');
    await settle();
    const status = h.panel.state().status;
    assert.ok(status.includes('Haas VF-4') && !status.includes('pl-c'), status);
    buttonNamed(h.host, 'Selected object').dispatch('click');
    await settle();
    assert.deepStrictEqual(outlines().at(-1), ['highlightComponent', null, undefined], 'leaving part scope clears the outline');
});

test('scenes preview in the viewport and save with the layout; Reset returns to Classic', async () => {
    const h = harness({ layout: { layoutId: 'fl', placements: [], extensions: { facilityScene: { version: 1, sceneId: 'warehouse' } } },
        selection: [] });
    h.panel.select('scene', 'machine-shop');
    await settle(120);
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'previewViewportScene').at(-1)[1], { version: 1, sceneId: 'machine-shop' });
    h.panel.setDraft({ shadows: true });
    buttonNamed(h.host, 'Apply').dispatch('click');
    await settle();
    assert.deepStrictEqual(h.calls.find(call => call[0] === 'setViewportScene')[1],
        { version: 1, sceneId: 'machine-shop', adjustments: { shadows: true } });
    buttonNamed(h.host, 'Reset to Classic').dispatch('click');
    await settle();
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'setViewportScene').at(-1), ['setViewportScene', null]);
});

test('the Lights on switch previews and saves with the scene, and re-editing the saved scene starts from it', async () => {
    const saved = { version: 1, sceneId: 'machine-shop', adjustments: { lights: false, ambient: 0.4 } };
    const h = harness({ layout: { layoutId: 'fl', placements: [], extensions: { facilityScene: saved } }, selection: [] });
    h.panel.select('scene', 'warehouse');
    await settle(120);
    const lightsBox = () => find(h.host, node => node.tagName === 'INPUT' && node.getAttribute('aria-label') === 'Lights on');
    assert.strictEqual(lightsBox().checked, true, 'another scene starts with the lights on');
    lightsBox().checked = false;
    lightsBox().dispatch('change');
    await settle(120);
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'previewViewportScene').at(-1)[1],
        { version: 1, sceneId: 'warehouse', adjustments: { lights: false } });
    buttonNamed(h.host, 'Apply').dispatch('click');
    await settle();
    assert.deepStrictEqual(h.calls.find(call => call[0] === 'setViewportScene')[1],
        { version: 1, sceneId: 'warehouse', adjustments: { lights: false } });
    // The scene the layout already uses opens with its own settings, so Apply keeps them.
    h.panel.select('scene', 'machine-shop');
    await settle(120);
    assert.strictEqual(lightsBox().checked, false, 'the saved switch shows');
    h.panel.setDraft({ exposure: 1.1 });
    buttonNamed(h.host, 'Apply').dispatch('click');
    await settle();
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'setViewportScene').at(-1)[1],
        { version: 1, sceneId: 'machine-shop', adjustments: { exposure: 1.1, ambient: 0.4, lights: false } });
});

test('the Glow halo box shows for Evening only, previews and saves with the scene, and reopens as saved', async () => {
    const h = harness({ layout: { layoutId: 'fl', placements: [], extensions: { facilityScene: { version: 1, sceneId: 'warehouse' } } },
        selection: [] });
    const haloBox = () => find(h.host, node => node.tagName === 'INPUT' && node.getAttribute('aria-label') === 'Glow halo');
    h.panel.select('scene', 'machine-shop');
    await settle(120);
    assert.strictEqual(haloBox(), null, 'not for a scene without floor light pools');
    h.panel.select('scene', 'evening');
    await settle(120);
    assert.strictEqual(haloBox().checked, false, 'off by default');
    haloBox().checked = true;
    haloBox().dispatch('change');
    await settle(120);
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'previewViewportScene').at(-1)[1],
        { version: 1, sceneId: 'evening', adjustments: { glowHalo: true } });
    buttonNamed(h.host, 'Apply').dispatch('click');
    await settle();
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'setViewportScene').at(-1)[1],
        { version: 1, sceneId: 'evening', adjustments: { glowHalo: true } });
    const reopened = harness({ layout: { layoutId: 'fl', placements: [], extensions: { facilityScene:
        { version: 1, sceneId: 'evening', adjustments: { glowHalo: true } } } }, selection: [] });
    reopened.panel.select('scene', 'evening');
    await settle(120);
    assert.strictEqual(find(reopened.host, node => node.tagName === 'INPUT'
        && node.getAttribute('aria-label') === 'Glow halo').checked, true, 'the saved halo shows');
});

test('general lights per area: floor areas to tick, rectangles drawn on the plan, removed areas dropped on Apply', async () => {
    const floor = (surfaceId, label) => ({ surfaceId, label, boundary: [], elevation: 0, material: 'concrete',
        color: '#8a8f94', roughness: 0.8 });
    const saved = { version: 1, sceneId: 'evening', adjustments: { lightAreas: { mode: 'only', areas: [
        { surfaceId: 'fs-receiving' }, { surfaceId: 'fs-gone' }, { rectangle: { minX: 0, minZ: 0, maxX: 10, maxZ: 4 } }] } } };
    const h = harness({ layout: { layoutId: 'fl', placements: [], extensions: { facilityScene: saved,
        facilityFloorSurfaces: { version: 1, surfaces: [floor('fs-receiving', '01 Receiving'), floor('fs-dispatch', '06 Dispatch')] } } },
        selection: [] });
    h.panel.select('scene', 'evening');
    await settle(120);
    const general = () => find(h.host, node => node.tagName === 'SELECT' && node.getAttribute('aria-label') === 'General lights');
    const shown = () => find(general(), node => node.tagName === 'OPTION' && node.getAttribute('selected') !== null).getAttribute('value');
    const tick = label => find(h.host, node => node.tagName === 'INPUT' && node.getAttribute('aria-label') === label);
    const preview = () => h.calls.filter(call => call[0] === 'previewViewportScene').at(-1)[1];
    const choose = async value => { general().value = value; general().dispatch('change'); await settle(120); };
    assert.strictEqual(shown(), 'only', 'the saved areas show');
    assert.strictEqual(tick('01 Receiving').checked, true);
    assert.strictEqual(tick('06 Dispatch').checked, false);
    assert.ok(h.host.textContent.includes('fs-gone was removed from the layout: it lights nothing and is dropped on Apply.'));
    assert.ok(h.host.textContent.includes('Drawn 10 x 4 m at 5, 2'));
    tick('06 Dispatch').checked = true;
    tick('06 Dispatch').dispatch('change');
    await settle(120);
    assert.deepStrictEqual(preview().adjustments.lightAreas, { mode: 'only', areas: [{ surfaceId: 'fs-receiving' },
        { rectangle: { minX: 0, minZ: 0, maxX: 10, maxZ: 4 } }, { surfaceId: 'fs-dispatch' }] }, 'previewed, the removed area left out');
    // Draw an area on the plan: the workspace hands back one rectangle.
    buttonNamed(h.host, 'Draw an area on the plan').dispatch('click');
    assert.strictEqual(h.draws.length, 1);
    h.draws[0]({ minX: 20, minZ: 1, maxX: 26, maxZ: 3 });
    await settle(120);
    assert.deepStrictEqual(preview().adjustments.lightAreas.areas.at(-1), { rectangle: { minX: 20, minZ: 1, maxX: 26, maxZ: 3 } });
    assert.ok(h.host.textContent.includes('Drawn 6 x 2 m at 23, 2'));
    buttonNamed(h.host, 'Remove').dispatch('click');
    await settle(120);
    assert.ok(!h.host.textContent.includes('Drawn 10 x 4 m'), 'the first drawn area is removed');
    buttonNamed(h.host, 'Draw an area on the plan').dispatch('click');
    h.draws[1](null);
    await settle(120);
    assert.strictEqual(preview().adjustments.lightAreas.areas.length, 3, 'Esc on the plan adds nothing');
    await choose('except');
    buttonNamed(h.host, 'Apply').dispatch('click');
    await settle();
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'setViewportScene').at(-1)[1], { version: 1, sceneId: 'evening',
        adjustments: { lightAreas: { mode: 'except', areas: [{ surfaceId: 'fs-receiving' }, { surfaceId: 'fs-dispatch' },
            { rectangle: { minX: 20, minZ: 1, maxX: 26, maxZ: 3 } }] } } });
    // Everywhere saves no areas; picking "Only in" again brings them back.
    await choose('everywhere');
    assert.strictEqual(preview().adjustments, undefined);
    assert.strictEqual(tick('01 Receiving'), null, 'no area list');
    await choose('only');
    assert.strictEqual(preview().adjustments.lightAreas.areas.length, 3);
    assert.strictEqual(tick('06 Dispatch').checked, true);
});

test('dropping a sign on equipment saves an equipment decal; on a wall it opens wall decals', async () => {
    const h = harness({ hit: { placementId: 'pl-a', point: { x: 0, y: 1, z: 0 }, normal: { x: 0, y: 0, z: 1 } } });
    const drag = { types: [panelApi.DRAG_TYPE], getData: () => JSON.stringify({ kind: 'decal', id: 'iso7010-w014' }) };
    h.dropTarget.dispatch('dragover', { dataTransfer: drag });
    h.dropTarget.dispatch('drop', { dataTransfer: drag, clientX: 10, clientY: 10 });
    await settle(20);
    const saved = h.calls.find(call => call[0] === 'setEquipmentDecals');
    assert.ok(saved, 'equipment decal saved');
    const row = saved[1].decals[0];
    assert.strictEqual(row.placementId, 'pl-a');
    assert.strictEqual(row.libraryDecalId, 'iso7010-w014');
    assert.ok(/^edecal-[a-z0-9]+$/.test(row.decalId));
    assert.ok(Math.abs(row.widthMeters / row.heightMeters - 1.145) < 0.01, 'height follows the sign artwork');
    assert.deepStrictEqual(h.calls.find(call => call[0] === 'importDecalImage'), ['importDecalImage', 'image/png'],
        'the sign is imported, so the layout keeps its own copy');

    const wall = harness({ hit: { placementId: 'pl-wall', point: { x: 0, y: 1, z: 0 }, normal: { x: 0, y: 0, z: 1 } } });
    wall.dropTarget.dispatch('drop', { dataTransfer: drag, clientX: 10, clientY: 10 });
    await settle(20);
    assert.strictEqual(wall.wallOpens.length, 1);
    assert.strictEqual(wall.wallOpens[0].label, 'Forklift trucks');
    assert.ok(!wall.calls.some(call => call[0] === 'setEquipmentDecals'));
});

test('dropping a finish targets the object under the cursor, or the whole selection when it is part of it', async () => {
    const h = harness({ hit: { placementId: 'pl-b', partKey: 'p:Frame#0' } });
    const drag = { types: [panelApi.DRAG_TYPE], getData: () => JSON.stringify({ kind: 'appearance', id: 'paint-safety-yellow' }) };
    h.dropTarget.dispatch('drop', { dataTransfer: drag });
    await settle();
    assert.deepStrictEqual(h.calls.find(call => call[0] === 'setPlacementsAppearance').slice(1),
        [['pl-a', 'pl-b'], { appearanceId: 'paint-safety-yellow' }]);
    const single = harness({ hit: { placementId: 'pl-b', partKey: 'p:Frame#0' }, selection: [] });
    single.dropTarget.dispatch('drop', { dataTransfer: drag, shiftKey: true });
    await settle();
    assert.strictEqual(single.calls.find(call => call[0] === 'setComponentMaterials')[1], 'pl-b', 'Shift finishes one part');
});

test('favorites, custom finishes and read-only states behave as described', async () => {
    const h = harness();
    const star = find(h.host, node => node.className === 'ip-flib-fav');
    star.dispatch('click');
    assert.strictEqual(h.preferences.favorites().length, 1);
    h.panel.select('appearance', 'wood-walnut');
    buttonNamed(h.host, 'Save as custom').dispatch('click');
    const name = find(h.host, node => node.tagName === 'INPUT' && node.getAttribute('aria-label') === 'Custom finish name');
    name.value = 'Smoked walnut';
    h.panel.setDraft({ color: '#7a6a5a' });
    buttonNamed(h.host, 'Save').dispatch('click');
    await settle();
    const saved = h.calls.find(call => call[0] === 'setCustomAppearances')[1];
    assert.strictEqual(saved.custom[0].label, 'Smoked walnut');
    assert.strictEqual(saved.custom[0].baseAppearanceId, 'wood-walnut');
    assert.strictEqual(saved.custom[0].color, '#7a6a5a');
    assert.ok(/^custom-smoked-walnut-[a-z0-9]{1,6}$/.test(saved.custom[0].appearanceId));
    const locked = harness({ canEdit: false });
    locked.panel.select('appearance', 'wood-oak');
    assert.ok(buttonNamed(locked.host, 'Apply').disabled, 'Apply waits for an editable draft');
});

test('lighting coverage: pick an area and Show; the totals and dark spots list; Hide, a failure and a dropped estimate', async () => {
    const floor = (surfaceId, label) => ({ surfaceId, label, boundary: [], elevation: 0, material: 'concrete',
        color: '#8a8f94', roughness: 0.8 });
    let shown = null;
    let failure = null;
    const asked = [];
    const caption = 'Estimate, not a lighting design. No code-compliance claims.';
    const h = harness({ selection: [], layout: { layoutId: 'fl', placements: [],
        zones: [{ zoneId: 'zn-park', label: 'Visitor car park', boundary: [] }],
        extensions: { facilityFloorSurfaces: { version: 1, surfaces: [floor('fs-receiving', '01 Receiving')] } } },
        context: () => ({ lightCoverage: shown,
            async showLightCoverage(area, choice) {
                asked.push([area, choice]);
                if (failure) throw new Error(failure);
                shown = { token: asked.length, choice, caption, summary: {
                    area: { label: 'Visitor car park', sizeSquareMeters: 600.4 },
                    estimatedLux: { minimum: 0, mean: 29.7, maximum: 174.6 },
                    lamps: { on: 830, lightingThisArea: 12, offBySwitch: 0, offByArea: 0 },
                    darkSpots: { belowLux: 14.9, basis: "half the area's mean", count: 3 } },
                spots: [{ number: 1, centre: { x: 12.5, z: -40.5 }, sizeSquareMeters: 320, meanLux: 3.1, minimumLux: 0,
                    nearestLamps: [{ label: 'Pole 7', distanceMeters: 14.2 }, { label: 'Pole 8', distanceMeters: 19 }] },
                { number: 2, centre: { x: 3.5, z: 1.5 }, sizeSquareMeters: 12, meanLux: 9, minimumLux: 6.5, nearestLamps: [] }] };
                return shown;
            },
            hideLightCoverage() { shown = null; return true; } }) });
    h.panel.select('scene', 'evening');
    await settle(120);
    const area = () => find(h.host, node => node.tagName === 'SELECT' && node.getAttribute('aria-label') === 'Area to check');
    assert.deepStrictEqual(findAll(area(), node => node.tagName === 'OPTION').map(node => [node.getAttribute('value'),
        node.textContent]), [['lot', 'Car parks and truck yards'], ['floor:fs-receiving', 'Floor area: 01 Receiving'],
        ['zone:zn-park', 'Zone: Visitor car park']]);
    area().value = 'zone:zn-park';
    area().dispatch('change');
    buttonNamed(h.host, 'Show').dispatch('click');
    await settle();
    assert.deepStrictEqual(asked, [[{ zoneId: 'zn-park' }, 'zone:zn-park']]);
    const text = h.host.textContent;
    assert.ok(text.includes(caption));
    assert.ok(text.includes('Visitor car park, 600 sq m: estimated 0 to 174.6 lux, mean 29.7.'), text);
    assert.ok(text.includes('12 of 830 lamps that are on light it.'));
    assert.ok(text.includes("Dark spots, below 14.9 lux (half the area's mean): the 2 largest of 3, outlined and numbered on the floor."));
    assert.deepStrictEqual(findAll(h.host, node => node.tagName === 'LI').map(node => node.textContent), [
        '320 sq m around 12.5, -40.5: mean 3.1 lux, lowest 0. Nearest: Pole 7 (14.2 m), Pole 8 (19 m).',
        '12 sq m around 3.5, 1.5: mean 9 lux, lowest 6.5.']);
    buttonNamed(h.host, 'Hide').dispatch('click');
    await settle();
    assert.strictEqual(buttonNamed(h.host, 'Hide'), null);
    assert.strictEqual(findAll(h.host, node => node.tagName === 'LI').length, 0);
    // A failure says why; nothing is shown.
    failure = 'This layout has no car park or truck yard zone; check one zone, floor area or rectangle instead.';
    area().value = 'lot';
    area().dispatch('change');
    buttonNamed(h.host, 'Show').dispatch('click');
    await settle();
    assert.deepStrictEqual(asked.at(-1), [{ lot: true }, 'lot']);
    const said = find(h.host, node => node.className === 'ip-flib-coverage-error');
    assert.deepStrictEqual([said.textContent, said.getAttribute('role')], [failure, 'alert'], 'said in the block');
    assert.strictEqual(buttonNamed(h.host, 'Hide'), null);
    // Shown again, then dropped by the workspace (the layout changed): the block follows on the next refresh.
    failure = null;
    buttonNamed(h.host, 'Show').dispatch('click');
    await settle();
    assert.ok(buttonNamed(h.host, 'Hide'));
    assert.strictEqual(find(h.host, node => node.className === 'ip-flib-coverage-error'), null, 'the failure goes');
    shown = null;
    h.notify();
    await settle();
    assert.strictEqual(buttonNamed(h.host, 'Hide'), null, 'the block follows the workspace');
});

(async () => {
    let failed = 0;
    for (const [name, fn] of tests) {
        try { await fn(); console.log('ok -', name); } catch (error) { failed += 1; console.error('FAIL -', name, '\n', error); }
    }
    console.log(failed ? failed + ' failed' : tests.length + '/' + tests.length + ' passed');
    process.exitCode = failed ? 1 : 0;
})();
