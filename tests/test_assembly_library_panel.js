'use strict';

// The Assembly tab's Appearances, Scenes and Signs panel (docs/assembly-signs-scenes-plan.md, AD5): browsing,
// finishes on the machine or selected parts, scenes, signs placed by side or dropped on the 3D view, logos and
// removal, against a tiny DOM and a fake viewer that records what the panel writes.

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const libraryApi = require('../static/facility_layout_library.js');
const panelApi = require('../static/assembly_library_panel.js');

// ------------------------------------------------------------ tiny DOM --
function makeDocument() {
    const doc = { listeners: Object.create(null) };
    function element(tag) {
        const node = {
            tagName: String(tag).toUpperCase(), children: [], attributes: Object.create(null), parentNode: null,
            className: '', listeners: Object.create(null), hidden: false, value: '', disabled: false, files: null,
            style: { values: {}, setProperty(key, value) { this.values[key] = value; } },
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
            contains(other) { for (let at = other; at; at = at.parentNode) if (at === this) return true; return false; },
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
            click() { this.clicked = (this.clicked || 0) + 1; this.dispatch('click'); },
        };
        return node;
    }
    doc.createElement = element;
    doc.addEventListener = function (type, fn) { (doc.listeners[type] = doc.listeners[type] || []).push(fn); };
    doc.removeEventListener = function (type, fn) { doc.listeners[type] = (doc.listeners[type] || []).filter(item => item !== fn); };
    doc.dispatch = function (type, event) { (doc.listeners[type] || []).slice().forEach(fn => fn(event)); };
    return doc;
}

function find(root, predicate) {
    let found = null;
    (function visit(node) { node.children.forEach(child => { if (!found && predicate(child)) found = child; visit(child); }); }(root));
    return found;
}
const buttonNamed = (root, text) => find(root, node => node.tagName === 'BUTTON' && node.textContent === text);
const nodeNamed = (root, label) => find(root, node => node.className === 'ip-flib-node' && node.textContent.includes(label));
const tileFor = (root, kind, id) => find(root, node => node.className === 'ip-flib-item'
    && node.getAttribute('data-kind') === kind && node.getAttribute('data-id') === id);
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

function library() {
    const read = name => JSON.parse(fs.readFileSync(path.join(ROOT, 'static/facility_library', name + '.json'), 'utf8'));
    return libraryApi.indexLibrary({ appearances: read('appearances'), scenes: read('scenes'), decals: read('decals') });
}

function harness(options) {
    const doc = makeDocument();
    const host = doc.createElement('div');
    const lib = library();
    const store = { get: () => lib, load: () => Promise.resolve(lib), error: () => null, subscribe: () => () => {} };
    const calls = [];
    const view = { 0: doc.createElement('div') };
    const canvas = doc.createElement('canvas');
    view[0].append(canvas);
    let appearance = { assemblyNumber: 'asset-robot', revision: '', assigned: { whole: null, parts: {} }, scene: null,
        signs: [], images: [], signStatus: {} };
    const settings = { selection: ['wrist'], hit: { part: 'base', side: 'front',
        anchor: { mesh: 0, point: [0, 0.4, 0.3], normal: [0, 0, 1] } } };
    const viewer = {
        assemblyNumber: () => 'asset-robot',
        selectedParts: () => settings.selection,
        partName: part => ({ wrist: 'Wrist', base: 'Base' })[part] || part,
        load: async () => JSON.parse(JSON.stringify(appearance)),
        async saveFinishes(number, value) { calls.push(['finishes', number, value]); appearance.assigned = value; return appearance; },
        async saveScene(number, sceneId) {
            calls.push(['scene', number, sceneId]);
            appearance.scene = sceneId ? { sceneId } : null;
            return appearance;
        },
        async saveSigns(number, signs) {
            calls.push(['signs', number, signs]);
            appearance.signs = signs.map((row, index) => Object.assign({ signId: row.signId || 'sg-new' + index, url: '/x.svg' }, row));
            return appearance;
        },
        async importImage(number, file) {
            calls.push(['image', number, file.name]);
            appearance.images = [{ imageId: 'd'.repeat(64), label: 'Acme', aspect: 2, url: '/api/assembly-appearance-images/'
                + 'd'.repeat(64) + '.png' }];
            return { image: appearance.images[0] };
        },
        async redraw() { calls.push(['redraw']); },
        pickSurfaceAt: (x, y) => { calls.push(['pick', x, y]); return settings.hit; },
        dropTarget: () => view[0],
    };
    if (options && options.faces) {
        // Faces (docs/assembly-face-selection-plan.md): the view says which face is under the pointer and keeps
        // the selection (a click on the machine selects).
        settings.face = FACE_TOP;
        settings.faces = [];
        Object.assign(viewer, {
            faceAt: (x, y) => { calls.push(['faceAt', x, y]); return settings.face; },
            selectedFaces: () => settings.faces.slice(),
            setSelectedFaces: list => { settings.faces = list.slice(); calls.push(['select', list.map(ref => ref.face)]); },
        });
    }
    const panel = panelApi.createAssemblyLibraryPanel({ document: doc, host, store, viewer });
    return { doc, host, panel, calls, settings, canvas, set appearance(value) { appearance = value; },
        get appearance() { return appearance; } };
}

function dragEvent(payload, target) {
    const data = { [panelApi.DRAG_TYPE]: JSON.stringify(payload) };
    return { target, clientX: 120, clientY: 80, defaultPrevented: false,
        preventDefault() { this.defaultPrevented = true; },
        dataTransfer: { types: Object.keys(data), getData: key => data[key] || '', setData(key, value) { data[key] = value; } } };
}

const FACE_TOP = { part: 'base', mesh: 0, face: 3, kind: 'plane', side: 'top', areaM2: 0.12, center: [0, 0.5, 0],
    fingerprint: { area: 0.12, center: [0, 0.5, 0], normal: [0, 1, 0] } };
const FACE_ROUND = { part: 'wrist', mesh: 1, face: 7, kind: 'cylinder', side: 'front', areaM2: 0.04,
    center: [0.2, 1.4, 0.1], fingerprint: { area: 0.04, center: [0, 0.1, 0], normal: [0, 0, 0.62] } };
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const pointer = (x, y, extra) => Object.assign({ clientX: x, clientY: y, button: 0, buttons: 0 }, extra || {});

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('the tree has the machine, the three libraries and logos, and the new machine-safety signs', async () => {
    const { host } = harness();
    await settle();
    ['On this machine', 'Appearances', 'Scenes', 'Safety signs', 'Logos'].forEach(label => assert(nodeNamed(host, label), label));
    nodeNamed(host, 'Safety signs').click();
    ['iso7010-w021', 'iso7010-w018', 'iso7010-w024', 'iso7010-p010', 'iso7010-p015']
        .forEach(id => assert(tileFor(host, 'decal', id), id));
    assert(find(host, node => node.className === 'ip-flib-empty') === null);
});

test('Lights finishes glow only in the Facility 3D view, so the machine pane leaves them out', async () => {
    const { host } = harness();
    await settle();
    nodeNamed(host, 'Appearances').click();
    await settle();
    assert(nodeNamed(host, 'Paint & Coatings') && nodeNamed(host, 'Metals'), 'the finish groups are listed');
    assert.strictEqual(nodeNamed(host, 'Lights'), null, 'no Lights group');
    assert(tileFor(host, 'appearance', 'paint-safety-orange'));
    assert.strictEqual(tileFor(host, 'appearance', 'light-stack-red'), null, 'no glow finish under Appearances');
    const search = find(host, node => node.className === 'ip-flib-search');
    search.value = 'light';
    search.dispatch('input');
    await settle();
    assert(tileFor(host, 'appearance', 'wood-maple'), 'search still finds the other finishes ("light" maple)');
    assert.strictEqual(tileFor(host, 'appearance', 'light-cool-white-led'), null, 'nor in search');
});

test('a finish goes on the selected parts or the whole machine, with a colour, and comes off again', async () => {
    const { host, calls, settings } = harness();
    await settle();
    nodeNamed(host, 'Appearances').click();
    tileFor(host, 'appearance', 'paint-safety-orange').click();
    assert(buttonNamed(host, 'Selected parts (1)').getAttribute('aria-checked') === 'true');
    await buttonNamed(host, 'Apply').dispatch('click');
    await settle(); await settle();
    assert.deepStrictEqual(calls[0], ['finishes', 'asset-robot', { whole: null,
        parts: { wrist: { appearanceId: 'paint-safety-orange' } } }]);
    assert.deepStrictEqual(calls[1], ['redraw']);
    settings.selection = [];
    tileFor(host, 'appearance', 'paint-safety-orange').click();
    find(host, node => node.tagName === 'INPUT' && node.attributes.type === 'color').value = '#123456';
    find(host, node => node.tagName === 'INPUT' && node.attributes.type === 'color').dispatch('input');
    buttonNamed(host, 'Apply').dispatch('click');
    await settle(); await settle();
    assert.deepStrictEqual(calls[2][2].whole, { appearanceId: 'paint-safety-orange', color: '#123456' });
    assert.deepStrictEqual(calls[2][2].parts, { wrist: { appearanceId: 'paint-safety-orange' } }, 'parts kept');
    buttonNamed(host, 'Remove whole-machine finish').dispatch('click');
    await settle(); await settle();
    assert.strictEqual(calls[4][2].whole, null);
});

test('a scene is applied, and Classic takes the view back to its own light', async () => {
    const { host, calls } = harness();
    await settle();
    nodeNamed(host, 'Scenes').click();
    tileFor(host, 'scene', 'machine-shop').click();
    buttonNamed(host, 'Use this scene').dispatch('click');
    await settle(); await settle();
    assert.deepStrictEqual(calls[0], ['scene', 'asset-robot', 'machine-shop']);
    buttonNamed(host, 'Back to Classic').dispatch('click');
    await settle(); await settle();
    assert.deepStrictEqual(calls[2], ['scene', 'asset-robot', null]);
});

test('a sign is placed on the selected part by side, width and turn, keeping the signs already there', async () => {
    const h = harness();
    h.appearance.signs = [{ signId: 'sg-aaaaaa', decalId: 'iso7010-p010', label: 'Do not touch', part: 'base',
        side: 'left', across: 0.5, up: 0.5, widthMeters: 0.3, rotationDegrees: 0, url: '/p010.svg', code: 'ISO 7010 P010' }];
    await h.panel.refresh();
    nodeNamed(h.host, 'Safety signs').click();
    tileFor(h.host, 'decal', 'iso7010-w024').click();
    const side = find(h.host, node => node.tagName === 'SELECT' && node.attributes['aria-label'] === 'Side');
    side.value = 'left'; side.dispatch('change');
    const width = find(h.host, node => node.tagName === 'INPUT' && node.attributes.type === 'number');
    width.value = '0.12'; width.dispatch('input');
    const turn = find(h.host, node => node.tagName === 'SELECT' && node.attributes['aria-label'] === 'Turn');
    turn.value = '90'; turn.dispatch('change');
    buttonNamed(h.host, 'Place on part').dispatch('click');
    await settle(); await settle();
    const [kind, number, rows] = h.calls[0];
    assert.strictEqual(kind, 'signs');
    assert.strictEqual(number, 'asset-robot');
    assert.deepStrictEqual(rows[0], { signId: 'sg-aaaaaa', decalId: 'iso7010-p010', label: 'Do not touch', part: 'base',
        side: 'left', across: 0.5, up: 0.5, widthMeters: 0.3, rotationDegrees: 0 }, 'resolved fields are not sent back');
    assert.deepStrictEqual(rows[1], { label: 'Crushing of hands', part: 'wrist', side: 'left', widthMeters: 0.12,
        rotationDegrees: 90, decalId: 'iso7010-w024' });
    // Without a selection the panel asks for one rather than guessing a part.
    h.settings.selection = [];
    tileFor(h.host, 'decal', 'iso7010-w017').click();
    assert(buttonNamed(h.host, 'Place on part').disabled);
});

test('dropping a sign or a finish on the 3D view lands it on the part under the pointer', async () => {
    const h = harness();
    await settle();
    nodeNamed(h.host, 'Safety signs').click();
    h.doc.dispatch('dragover', dragEvent({ kind: 'decal', id: 'iso7010-w017' }, h.canvas));
    assert(h.settings && h.canvas.parentNode.classList.contains('ip-flib-drop-active'));
    const drop = dragEvent({ kind: 'decal', id: 'iso7010-w017' }, h.canvas);
    h.doc.dispatch('drop', drop);
    await settle(); await settle();
    assert(drop.defaultPrevented && !h.canvas.parentNode.classList.contains('ip-flib-drop-active'));
    assert.deepStrictEqual(h.calls[0], ['pick', 120, 80]);
    assert.deepStrictEqual(h.calls[1][2][0], { label: 'Hot surface', part: 'base', side: 'front', widthMeters: 0.3,
        rotationDegrees: 0, decalId: 'iso7010-w017', anchor: { mesh: 0, point: [0, 0.4, 0.3], normal: [0, 0, 1] } });
    h.doc.dispatch('drop', dragEvent({ kind: 'appearance', id: 'steel-brushed' }, h.canvas));
    await settle(); await settle();
    assert.deepStrictEqual(h.calls[4], ['finishes', 'asset-robot', { whole: null,
        parts: { base: { appearanceId: 'steel-brushed' } } }]);
    // Off the view, or on empty space, nothing is written.
    const before = h.calls.length;
    h.doc.dispatch('drop', dragEvent({ kind: 'decal', id: 'iso7010-w017' }, h.doc.createElement('div')));
    h.settings.hit = null;
    h.doc.dispatch('drop', dragEvent({ kind: 'decal', id: 'iso7010-w017' }, h.canvas));
    await settle();
    assert.strictEqual(h.calls.filter(call => call[0] === 'signs').length, 1);
    assert(h.calls.length === before + 1 && h.calls[before][0] === 'pick');
    assert(find(h.host, node => node.className === 'ip-flib-status').textContent.includes('Drop it on a part'));
});

test('with no part ticked, "Pick on the machine" puts a sign or a finish where the machine is clicked', async () => {
    const h = harness();
    h.settings.selection = [];
    await settle();
    nodeNamed(h.host, 'Safety signs').click();
    tileFor(h.host, 'decal', 'iso7010-w017').click();
    assert(buttonNamed(h.host, 'Place on part').disabled, 'nothing ticked to place on');
    buttonNamed(h.host, 'Pick on the machine').click();
    const view = h.canvas.parentNode;
    const status = () => find(h.host, node => node.className === 'ip-flib-status').textContent;
    assert(view.classList.contains('ip-flib-drop-active') && status().includes('Click the machine where Hot surface'));
    assert(buttonNamed(h.host, 'Cancel pick'));
    // Dragging orbits the view; it is not a pick.
    view.dispatch('pointerdown', { button: 0, clientX: 10, clientY: 10 });
    view.dispatch('pointerup', { button: 0, clientX: 40, clientY: 40 });
    assert(!h.calls.length);
    view.dispatch('pointerdown', { button: 0, clientX: 50, clientY: 60 });
    view.dispatch('pointerup', { button: 0, clientX: 51, clientY: 60 });
    await settle(); await settle();
    assert.deepStrictEqual(h.calls[0], ['pick', 51, 60]);
    assert.deepStrictEqual(h.calls[1][2][0], { label: 'Hot surface', part: 'base', side: 'front', widthMeters: 0.3,
        rotationDegrees: 0, decalId: 'iso7010-w017', anchor: { mesh: 0, point: [0, 0.4, 0.3], normal: [0, 0, 1] } });
    assert(!view.classList.contains('ip-flib-drop-active'), 'one pick, then the view is itself again');
    const after = h.calls.length;
    view.dispatch('pointerdown', { button: 0, clientX: 50, clientY: 60 });
    view.dispatch('pointerup', { button: 0, clientX: 50, clientY: 60 });
    assert.strictEqual(h.calls.length, after);
    // A finish: Esc cancels a pick; the next one lands on the clicked part.
    nodeNamed(h.host, 'Appearances').click();
    tileFor(h.host, 'appearance', 'steel-brushed').click();
    buttonNamed(h.host, 'Pick on the machine').click();
    h.doc.dispatch('keydown', { key: 'Escape' });
    assert(status().includes('Pick cancelled') && !view.classList.contains('ip-flib-drop-active'));
    buttonNamed(h.host, 'Pick on the machine').click();
    view.dispatch('pointerdown', { button: 0, clientX: 70, clientY: 20 });
    view.dispatch('pointerup', { button: 0, clientX: 70, clientY: 20 });
    await settle(); await settle();
    const finishes = h.calls.filter(call => call[0] === 'finishes');
    assert.deepStrictEqual(finishes[0], ['finishes', 'asset-robot', { whole: null,
        parts: { base: { appearanceId: 'steel-brushed' } } }]);
});

test('the machine lists its finishes, scene and signs, says which were not drawn, and removes a sign', async () => {
    const h = harness();
    h.appearance.assigned = { whole: { appearanceId: 'paint-machine-gray' }, parts: { wrist: { appearanceId: 'steel-brushed' } } };
    h.appearance.scene = { sceneId: 'machine-shop' };
    h.appearance.signs = [{ signId: 'sg-bbbbbb', decalId: 'iso7010-w024', label: 'Crushing of hands', part: 'wrist',
        side: 'top', across: 0.5, up: 0.5, widthMeters: 0.1, rotationDegrees: 0, url: '/w024.svg' }];
    h.appearance.signStatus = { 'sg-bbbbbb': 'no_surface' };
    await h.panel.refresh();
    const names = ['paint-machine-gray', 'steel-brushed', 'machine-shop'];
    names.forEach(id => assert(find(h.host, node => node.getAttribute && node.getAttribute('data-id') === id), id));
    const sign = tileFor(h.host, 'placed-sign', 'sg-bbbbbb');
    assert(sign.textContent.includes('On Wrist, top - not drawn: no surface faces that way there'));
    assert(find(h.host, node => node.className === 'ip-flib-count' && node.textContent === '3'));
    sign.click();
    buttonNamed(h.host, 'Remove sign').dispatch('click');
    await settle(); await settle();
    assert.deepStrictEqual(h.calls[0], ['signs', 'asset-robot', []]);
});

test('a logo is imported for the machine and placed like a sign', async () => {
    const h = harness();
    await settle();
    nodeNamed(h.host, 'Logos').click();
    const picker = find(h.host, node => node.tagName === 'INPUT' && node.attributes.type === 'file');
    buttonNamed(h.host, 'Import logo...').dispatch('click');
    assert.strictEqual(picker.clicked, 1);
    picker.files = [{ name: 'acme.png', type: 'image/png' }];
    picker.dispatch('change');
    await settle(); await settle(); await settle();
    assert.deepStrictEqual(h.calls[0], ['image', 'asset-robot', 'acme.png']);
    const logo = tileFor(h.host, 'logo', 'd'.repeat(64));
    assert(logo, 'the imported logo is listed');
    logo.click();
    buttonNamed(h.host, 'Place on part').dispatch('click');
    await settle(); await settle();
    assert.deepStrictEqual(h.calls[2][2][0], { label: 'Acme', part: 'wrist', side: 'front', widthMeters: 0.3,
        rotationDegrees: 0, imageId: 'd'.repeat(64) });
});

test('a failed write says why and leaves the panel usable', async () => {
    const doc = makeDocument();
    const lib = library();
    const redraws = [];
    const failing = panelApi.createAssemblyLibraryPanel({ document: doc, host: doc.createElement('div'),
        store: { get: () => lib, load: () => Promise.resolve(lib), error: () => null },
        viewer: { assemblyNumber: () => 'asset-robot', selectedParts: () => [], load: async () => null,
            saveScene: async () => { throw new Error('"moon" is not a scene'); }, redraw: async () => redraws.push(1),
            pickSurfaceAt: () => null, dropTarget: () => null } });
    await settle();
    const root = failing.element;
    nodeNamed(root, 'Scenes').click();
    tileFor(root, 'scene', 'warehouse').click();
    buttonNamed(root, 'Use this scene').dispatch('click');
    await settle(); await settle();
    const status = find(root, node => node.className === 'ip-flib-status');
    assert(status.textContent.includes('is not a scene') && status.getAttribute('data-tone') === 'error');
    assert(!buttonNamed(root, 'Use this scene').disabled && redraws.length === 0);
});

test('faces are selected in the view: the pane says how, follows the selection and can clear it', async () => {
    const h = harness({ faces: true });
    await settle();
    assert(!buttonNamed(h.host, 'Pick faces'), 'no picking mode to start');
    assert(find(h.host, node => node.textContent === 'Click a face on the machine to select it; Ctrl-click adds one.'));
    nodeNamed(h.host, 'Appearances').click();
    tileFor(h.host, 'appearance', 'paint-safety-orange').click();
    assert(buttonNamed(h.host, 'Selected faces').disabled, 'nothing selected yet');
    // A click on the machine selected a face: the view tells the pane.
    h.settings.faces = [FACE_TOP];
    h.panel.selectionChanged();
    assert(find(h.host, node => node.textContent === 'Flat face of Base selected.'));
    assert(buttonNamed(h.host, 'Selected faces (1)').getAttribute('aria-checked') === 'true', 'a finish goes on it');
    h.settings.faces = [FACE_TOP, FACE_ROUND];
    h.panel.selectionChanged();
    assert(find(h.host, node => node.textContent === '2 faces selected.'));
    buttonNamed(h.host, 'Clear faces').dispatch('click');
    assert.deepStrictEqual(h.settings.faces, []);
    assert(buttonNamed(h.host, 'Selected faces').disabled
        && buttonNamed(h.host, 'Selected faces').getAttribute('aria-checked') === 'false');
    const target = h.canvas.parentNode;
    assert(!target.listeners || !(target.listeners.pointermove || []).length, 'the pane does not listen to the view');
});

test('while "Pick on the machine" waits for a click the view does not select', async () => {
    const h = harness({ faces: true });
    await settle();
    assert.strictEqual(h.panel.isPicking(), false);
    nodeNamed(h.host, 'Safety signs').click();
    tileFor(h.host, 'decal', 'iso7010-w024').click();
    buttonNamed(h.host, 'Pick on the machine').dispatch('click');
    assert.strictEqual(h.panel.isPicking(), true);
    h.doc.dispatch('keydown', { key: 'Escape' });
    assert.strictEqual(h.panel.isPicking(), false);
});

test('a finish goes on the selected faces with their fingerprints and comes off them; a sign goes on a face', async () => {
    const h = harness({ faces: true });
    await settle();
    h.settings.faces = [FACE_TOP];
    nodeNamed(h.host, 'Appearances').click();
    tileFor(h.host, 'appearance', 'paint-safety-orange').click();
    assert(buttonNamed(h.host, 'Selected faces (1)').getAttribute('aria-checked') === 'true');
    await buttonNamed(h.host, 'Apply').dispatch('click');
    await settle(); await settle();
    assert.deepStrictEqual(h.calls.find(call => call[0] === 'finishes'), ['finishes', 'asset-robot', {
        whole: null, parts: {}, faces: [{ part: 'base', mesh: 0, face: 3, fingerprint: FACE_TOP.fingerprint,
            finish: { appearanceId: 'paint-safety-orange' } }] }]);
    nodeNamed(h.host, 'On this machine').click();
    assert(find(h.host, node => node.className === 'ip-flib-note-line' && node.textContent === 'On a face of Base'));
    nodeNamed(h.host, 'Appearances').click();
    tileFor(h.host, 'appearance', 'paint-safety-orange').click();
    buttonNamed(h.host, 'Remove from selected faces').dispatch('click');
    await settle(); await settle();
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'finishes')[1][2].faces, []);
    h.settings.faces = [FACE_TOP, FACE_ROUND];
    nodeNamed(h.host, 'Safety signs').click();
    tileFor(h.host, 'decal', 'iso7010-w024').click();
    buttonNamed(h.host, 'Place on selected faces (2)').dispatch('click');
    await settle(); await settle();
    const rows = h.calls.find(call => call[0] === 'signs')[2];
    assert.deepStrictEqual(rows.map(row => [row.part, row.side, row.face]), [
        ['base', 'top', { mesh: 0, face: 3, fingerprint: FACE_TOP.fingerprint }],
        ['wrist', 'front', { mesh: 1, face: 7, fingerprint: FACE_ROUND.fingerprint }]]);
    assert.deepStrictEqual(panelApi.storedSign(Object.assign({ signId: 'sg-abcdef', decalId: 'iso7010-w024' }, rows[0])).face,
        rows[0].face, 'the face is kept when the list is written back');
});

test('dropped on a selected face, a finish goes on the selected faces and a sign on that face', async () => {
    const h = harness({ faces: true });
    await settle();
    h.settings.faces = [FACE_TOP, FACE_ROUND];
    h.doc.dispatch('drop', dragEvent({ kind: 'appearance', id: 'paint-safety-yellow' }, h.canvas));
    await settle(); await settle();
    const saved = h.calls.find(call => call[0] === 'finishes')[2];
    assert.deepStrictEqual(saved.faces.map(row => [row.part, row.face, row.finish.appearanceId]),
        [['base', 3, 'paint-safety-yellow'], ['wrist', 7, 'paint-safety-yellow']]);
    assert(!h.calls.some(call => call[0] === 'pick'), 'not the part under the pointer');
    h.doc.dispatch('drop', dragEvent({ kind: 'decal', id: 'iso7010-w024' }, h.canvas));
    await settle(); await settle();
    const signs = h.calls.find(call => call[0] === 'signs')[2];
    assert.deepStrictEqual(signs[0].face, { mesh: 0, face: 3, fingerprint: FACE_TOP.fingerprint });
});

test('dropped on a face that is not selected, it lands on the part as before', async () => {
    const h = harness({ faces: true });
    await settle();
    h.settings.faces = [FACE_ROUND];
    h.settings.hit = { part: 'base', side: 'top', anchor: { mesh: 0, point: [0, 0.5, 0], normal: [0, 1, 0] } };
    h.doc.dispatch('drop', dragEvent({ kind: 'appearance', id: 'paint-safety-yellow' }, h.canvas));
    await settle(); await settle();
    const saved = h.calls.find(call => call[0] === 'finishes')[2];
    assert.deepStrictEqual(saved.parts, { base: { appearanceId: 'paint-safety-yellow' } });
    assert(!saved.faces || !saved.faces.length);
});

(async () => {
    let failed = 0;
    for (const [name, fn] of tests) {
        try {
            await fn();
            console.log('ok - ' + name);
        } catch (error) {
            failed += 1;
            console.log('not ok - ' + name);
            console.log(error && error.stack || error);
        }
    }
    console.log(`${tests.length - failed}/${tests.length} passed`);
    if (failed) process.exitCode = 1;
})();
