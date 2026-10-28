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
    const workspace = {
        session,
        subscribeStructure(fn) { listeners.add(fn); return () => listeners.delete(fn); },
        appearanceLibraryContext() {
            return { session, threeAdapter: adapter, document: doc, assetCatalog: settings.assetCatalog || [], layout: state.layout,
                selection: state.selection.slice(), canEdit: state.canEdit, viewMode: '3d', dropTarget,
                show3d() {}, openWallDecals(prefill) { wallOpens.push(prefill); },
                isWallAsset: id => id === 'pl-wall' };
        },
    };
    const panel = panelApi.createLibraryPanel({ document: doc, host, store, preferences });
    panel.bind(workspace);
    return { doc, host, panel, calls, state, preferences, dropTarget, wallOpens, notify() { listeners.forEach(fn => fn()); } };
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
    ['Metals', 'Plastics', 'Wood', 'Rubber', 'Glass', 'Fabric', 'Paper & Cardboard', 'Paint & Coatings', 'Concrete & Stone']
        .forEach(label => assert.ok(labels.includes(label), label));
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

(async () => {
    let failed = 0;
    for (const [name, fn] of tests) {
        try { await fn(); console.log('ok -', name); } catch (error) { failed += 1; console.error('FAIL -', name, '\n', error); }
    }
    console.log(failed ? failed + ' failed' : tests.length + '/' + tests.length + ' passed');
    process.exitCode = failed ? 1 : 0;
})();
