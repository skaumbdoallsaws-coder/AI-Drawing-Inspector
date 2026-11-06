'use strict';
// The Columns dialog (static/facility_layout_columns.js) on a small stand-in DOM: what it saves through the session.
const test = require('node:test');
const assert = require('node:assert/strict');
const columns = require('../static/facility_layout_columns.js');

class Node {
    constructor(doc, tag) {
        this.ownerDocument = doc; this.tagName = tag.toUpperCase(); this.attributes = {}; this.children = [];
        this.parentElement = null; this.listeners = {}; this.hidden = false; this.disabled = false; this.text = '';
        this.ownValue = '';
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; }
    append(...nodes) { nodes.forEach(node => { node.parentElement = this; this.children.push(node); }); }
    appendChild(node) { this.append(node); return node; }
    replaceChildren() { this.children = []; }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(n => n !== this); }
    get isConnected() { return true; }
    set textContent(value) { this.text = String(value); }
    get textContent() { return this.text; }
    get options() { return this.children.filter(node => node.tagName === 'OPTION'); }
    get value() { return this.tagName === 'OPTION' ? this.getAttribute('value') : this.ownValue; }
    set value(value) { this.ownValue = String(value); }
    addEventListener(type, listener) { (this.listeners[type] = this.listeners[type] || []).push(listener); }
    dispatch(type) { const event = { type, preventDefault() {} }; (this.listeners[type] || []).forEach(fn => fn(event)); }
    showModal() {}
    focus() {}
    find(predicate) {
        if (predicate(this)) return this;
        for (const child of this.children) { const hit = child.find(predicate); if (hit) return hit; }
        return null;
    }
}

function setup(saved, selection) {
    const doc = { createElement: tag => new Node(doc, tag), activeElement: null,
        defaultView: { crypto: { randomUUID: () => '00000000-0000-4000-8000-000000000001' } } };
    const layout = { layoutId: 'fl-test', coordinateFrame: { floorElevation: 0 },
        extensions: { facilityPlan: { widthMeters: 40, depthMeters: 30 } } };
    if (saved) layout.extensions.facilityColumns = { version: 1, columns: saved };
    const calls = [];
    const state = { loaded: true, layout, selection: selection || [], draftRevision: 3 };
    const library = { appearances: new Map([['concrete-smooth', { appearanceId: 'concrete-smooth', label: 'Concrete' }],
        ['steel-brushed', { appearanceId: 'steel-brushed', label: 'Brushed steel' }]]) };
    const workspace = { document: doc, root: new Node(doc, 'div'), capabilities: { manualAuthoring: true },
        options: { threeOptions: { facilityLibrary: { get: () => library } } },
        session: { getState: () => state, subscribe: () => () => {},
            setColumns: async value => { calls.push(value); } } };
    const ui = columns.open(workspace);
    const field = label => ui.dialog.find(node => node.getAttribute('aria-label') === label);
    const form = ui.dialog.children[0];
    const apply = async () => { form.dispatch('submit'); await new Promise(resolve => setImmediate(resolve)); };
    return { ui, field, apply, calls };
}

const DXF = { columnId: 'col-fp-0123456789abcdef', label: 'C-12', shape: 'rectangle', center: { x: 10, z: 5 },
    widthMeters: 0.4, depthMeters: 0.6, rotationDegrees: 30, heightMeters: 8, baseElevation: 0,
    appearance: { appearanceId: 'concrete-smooth', overrides: { color: '#aabbcc' } },
    source: { referenceId: 'fp-main', importId: 'fpi-' + 'a'.repeat(32), entityId: '2F/1A' },
    footprint: [{ x: 1, z: 1 }] };
const OTHER = { columnId: 'col-b', label: 'B', shape: 'circle', center: { x: 20, z: 5 }, diameterMeters: 0.5,
    heightMeters: 8, baseElevation: 0, appearance: { color: '#8f969c' } };

test('a new column is saved with every setting the server checks, its outline left to the server', async () => {
    const { field, apply, calls } = setup(null);
    assert.equal(field('Column').value, '');
    field('Column name').value = 'C-1';
    field('Center X (m)').value = '12.5';
    field('Center Z (m)').value = '7';
    field('Rotation (degrees)').value = '15';
    field('Height (m)').value = '7.5';
    field('Color').value = '#336699';
    await apply();
    assert.deepEqual(calls, [{ version: 1, columns: [{ columnId: 'col-00000000-0000-4000-8000-000000000001',
        label: 'C-1', shape: 'rectangle', center: { x: 12.5, z: 7 }, widthMeters: 0.4, depthMeters: 0.4,
        rotationDegrees: 15, heightMeters: 7.5, baseElevation: 0, appearance: { color: '#336699' } }] }]);
});

test('a column selected in the plan opens for editing; its drawing source and finish are kept, its place too',
    async () => {
        const { ui, field, apply, calls } = setup([DXF, OTHER], [DXF.columnId]);
        assert.equal(field('Column').value, DXF.columnId);
        assert.equal(field('Finish').value, 'concrete-smooth');
        assert.equal(field('Color').parentElement.hidden, true);  // a library finish, not a plain color
        assert.equal(field('Diameter (m)').parentElement.hidden, true);
        assert.match(ui.dialog.find(node => node.getAttribute('data-column-source') !== null).textContent,
            /fp-main, entity 2F\/1A/);
        field('Center X (m)').value = '11';
        field('Height (m)').value = '9';
        await apply();
        const [saved, other] = calls[0].columns;
        assert.deepEqual(saved, { columnId: DXF.columnId, label: 'C-12', shape: 'rectangle', center: { x: 11, z: 5 },
            widthMeters: 0.4, depthMeters: 0.6, rotationDegrees: 30, heightMeters: 9, baseElevation: 0,
            appearance: DXF.appearance, source: DXF.source });
        assert.deepEqual(other, OTHER);  // unchanged, and still second
    });

test('round columns take a diameter; another finish replaces the old one; delete removes only that column',
    async () => {
        let run = setup([DXF, OTHER]);
        run.field('Column').value = DXF.columnId;
        run.field('Column').dispatch('change');
        run.field('Shape').value = 'circle';
        run.field('Shape').dispatch('change');
        assert.equal(run.field('Width along X (m)').parentElement.hidden, true);
        assert.equal(run.field('Diameter (m)').parentElement.hidden, false);
        run.field('Diameter (m)').value = '0.45';
        run.field('Finish').value = 'steel-brushed';
        await run.apply();
        const saved = run.calls[0].columns[0];
        assert.deepEqual([saved.shape, saved.diameterMeters, saved.widthMeters, saved.appearance],
            ['circle', 0.45, undefined, { appearanceId: 'steel-brushed' }]);
        assert.deepEqual(saved.source, DXF.source);

        run = setup([DXF, OTHER], ['col-b']);
        const remove = run.ui.dialog.find(node => node.getAttribute('aria-label') === 'Delete column');
        assert.equal(remove.disabled, false);
        remove.dispatch('click');
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(run.calls, [{ version: 1, columns: [DXF].map(row => {
            const value = JSON.parse(JSON.stringify(row)); delete value.footprint; return value; }) }]);
    });
