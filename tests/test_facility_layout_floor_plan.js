'use strict';

// Floor-plan import, the Plan view side (docs/facility-floor-plan-import-plan.md, sections 5 and 6):
// static/facility_layout_floor_plan.js. Run with: node tests/test_facility_layout_floor_plan.js

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const floorPlan = require(path.join(ROOT, 'static', 'facility_layout_floor_plan.js'));
const CASES = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'tests', 'fixtures', 'facility_layout', 'floor_plan', 'alignment_cases.json'), 'utf8'));

let checks = 0;
const pending = [];
function check(name, fn) {
    const result = fn();
    const done = () => {
        checks += 1;
        process.stdout.write(`PASS ${name}\n`);
    };
    if (result && typeof result.then === 'function') pending.push(result.then(done));
    else done();
}

// A small DOM: enough for the panel (HTML) and the drawing (SVG).
class Node {
    constructor(documentRef, name) {
        this.ownerDocument = documentRef;
        this.nodeName = String(name).toUpperCase();
        this.parentNode = null;
        this.children = [];
        this.attributes = {};
        this.listeners = {};
        this.className = '';
        this.textContent = '';
        this.hidden = false;
        this.disabled = false;
        this.checked = false;
        this.value = '';
        this.clicks = 0;
    }

    appendChild(child) {
        if (child.parentNode) child.parentNode.removeChild(child);
        child.parentNode = this;
        this.children.push(child);
        return child;
    }

    removeChild(child) {
        const index = this.children.indexOf(child);
        if (index >= 0) this.children.splice(index, 1);
        child.parentNode = null;
        return child;
    }

    get firstChild() {
        return this.children[0] || null;
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
        if (name === 'hidden') this.hidden = true;
        if (name === 'disabled') this.disabled = true;
    }

    getAttribute(name) {
        return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
    }

    hasAttribute(name) {
        return Object.prototype.hasOwnProperty.call(this.attributes, name);
    }

    addEventListener(type, handler) {
        (this.listeners[type] = this.listeners[type] || []).push(handler);
    }

    matches(selector) {
        const match = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(selector);
        if (!match) throw new Error('unsupported selector ' + selector);
        return this.hasAttribute(match[1]) && (match[2] === undefined || this.getAttribute(match[1]) === match[2]);
    }

    closest(selector) {
        for (let node = this; node; node = node.parentNode) if (node.matches(selector)) return node;
        return null;
    }

    all() {
        const out = [];
        this.children.forEach(child => out.push(child, ...child.all()));
        return out;
    }

    querySelector(selector) {
        return this.all().find(node => node.matches(selector)) || null;
    }

    click() {
        this.clicks += 1;
    }

    text() {
        return [this.textContent].concat(this.children.map(child => child.text())).join(' ').replace(/\s+/g, ' ');
    }
}

class FakeDocument {
    createElement(name) { return new Node(this, name); }
    createElementNS(namespace, name) {
        assert.strictEqual(namespace, 'http://www.w3.org/2000/svg');
        return new Node(this, name);
    }
}

function fire(target, type) {
    const event = { type, target, preventDefault() {} };
    for (let node = target; node; node = node.parentNode) (node.listeners[type] || []).forEach(fn => fn(event));
    return event;
}

function flush() {
    return new Promise(resolve => setImmediate(resolve));
}

function near(actual, expected, tolerance, label) {
    assert.ok(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} != ${expected}`);
}

// A stored drawing as the server returns it: millimeters, its lowest corner at (1000, 2000).
const ORIGIN = [1000, 2000];
const MANIFEST = {
    origin: ORIGIN,
    units: { name: 'millimeters', metersPerUnit: 0.001 },
    layers: [
        { layerId: 'L0', name: '0', on: true, frozen: false, entities: 1, texts: 0 },
        { layerId: 'L1', name: 'WALLS', on: true, frozen: false, entities: 2, texts: 0 },
        { layerId: 'L2', name: 'TEXT', on: true, frozen: false, entities: 0, texts: 2 },
        { layerId: 'L3', name: 'OFF', on: false, frozen: false, entities: 1, texts: 0 },
        { layerId: 'L4', name: 'Defpoints', on: true, frozen: false, entities: 0, texts: 0 },
    ],
    warnings: [{ code: 'proxy_entities', message: 'Two proxy objects were left out.' }],
};
const GEOMETRY = Object.assign({}, MANIFEST, {
    entities: [
        { id: 'e1', layer: 'L1', type: 'LWPOLYLINE', closed: true,
            points: [[0, 0], [10000, 0], [10000, 8000], [0, 8000]] },
        { id: 'e2', layer: 'L1', type: 'LINE', closed: false, points: [[5000, 0], [5000, 8000]] },
        { id: 'e3', layer: 'L0', type: 'LINE', closed: false, points: [[0, -500], [10000, -500]] },
        { id: 'e4', layer: 'L3', type: 'LINE', closed: false, points: [[0, 0], [1, 1]] },
        { id: 't1', layer: 'L2', type: 'TEXT', at: [2000, 3000], height: 250, rotation: 90, align: 'MIDDLE_CENTER',
            mirrored: false, text: 'OFFICE' },
        { id: 't2', layer: 'L2', type: 'MTEXT', at: [7000, 3000], height: 200, rotation: 0, align: 'TOP_LEFT',
            mirrored: false, text: 'STORE\nROOM' },
    ],
});
const RECORD = {
    importId: 'fpi-' + 'a'.repeat(32), sourceSha256: 'b'.repeat(64), geometrySha256: 'c'.repeat(64),
    parserVersion: 'ezdxf-1.4.5+a1', sourceName: 'Plant 2.dxf', bytes: 1234,
};

check('the browser transform matches every shared alignment case and inverts', () => {
    assert.ok(CASES.cases.length >= 5);
    CASES.cases.forEach(item => {
        item.points.forEach(point => {
            const layout = floorPlan.toLayout(item.alignment, point.drawing[0], point.drawing[1]);
            near(layout.x, point.layout[0], CASES.tolerance, item.name + ' x');
            near(layout.z, point.layout[1], CASES.tolerance, item.name + ' z');
            const drawing = floorPlan.toDrawing(item.alignment, point.layout[0], point.layout[1]);
            near(drawing.u, point.drawing[0], 1e-6, item.name + ' u');
            near(drawing.v, point.drawing[1], 1e-6, item.name + ' v');
        });
    });
});

check('the screen matrix puts each stored point where the plan projects its layout point', () => {
    const projection = { scale: 20, offsetX: 30, offsetY: 40, minX: -5, maxZ: 25 };
    const alignment = { sourceOrigin: { u: 900, v: 1500 }, metersPerDrawingUnit: 0.001, rotationDegrees: 30,
        translationMeters: { x: 2, z: 3 } };
    const m = floorPlan.screenMatrix(alignment, ORIGIN, projection);
    [[0, 0], [10000, 0], [10000, 8000], [-250, 4321]].forEach(([p, q]) => {
        const layout = floorPlan.toLayout(alignment, p + ORIGIN[0], q + ORIGIN[1]);
        near(m[0] * p + m[2] * q + m[4], projection.offsetX + (layout.x - projection.minX) * projection.scale, 1e-9,
            'X of ' + p + ',' + q);
        near(m[1] * p + m[3] * q + m[5], projection.offsetY + (projection.maxZ - layout.z) * projection.scale, 1e-9,
            'Y of ' + p + ',' + q);
    });
    assert.strictEqual(floorPlan.screenMatrix(alignment, ORIGIN, null), null);
    assert.strictEqual(floorPlan.screenMatrix(Object.assign({}, alignment, { metersPerDrawingUnit: NaN }), ORIGIN,
        projection), null);
});

check('the drawing is one path per visible layer and labels that read upright', () => {
    const reference = floorPlan.newReference(RECORD, MANIFEST);
    const group = floorPlan.buildUnderlayContent(new FakeDocument(), GEOMETRY, reference);
    const paths = group.all().filter(node => node.nodeName === 'PATH');
    assert.deepStrictEqual(paths.map(node => node.getAttribute('data-floor-plan-layer')), ['L1', 'L0'],
        'the layer the file turns off stays hidden');
    assert.strictEqual(paths[0].getAttribute('d'), 'M0 0 10000 0 10000 8000 0 8000Z M5000 0 5000 8000');
    assert.strictEqual(paths[0].getAttribute('vector-effect'), 'non-scaling-stroke');
    const labels = group.all().filter(node => node.nodeName === 'TEXT');
    assert.deepStrictEqual(labels.map(node => node.getAttribute('transform')),
        ['translate(2000 3000) rotate(90) scale(1 -1)', 'translate(7000 3000) rotate(0) scale(1 -1)']);
    assert.deepStrictEqual(labels.map(node => [node.getAttribute('text-anchor'),
        node.getAttribute('dominant-baseline'), node.getAttribute('font-size')]),
    [['middle', 'central', '250'], ['start', 'hanging', '200']]);
    assert.strictEqual(labels[0].textContent, 'OFFICE');
    assert.deepStrictEqual(labels[1].children.map(span => [span.textContent, span.getAttribute('dy')]),
        [['STORE', '0em'], ['ROOM', '1.25em']]);
    // Hiding a layer is a different drawing; moving or fading it is not.
    const hidden = JSON.parse(JSON.stringify(reference));
    hidden.layers[1].visible = false;
    assert.notStrictEqual(floorPlan.contentKey(hidden), floorPlan.contentKey(reference));
    const moved = JSON.parse(JSON.stringify(reference));
    moved.alignment.translationMeters.x = 9;
    moved.opacity = 0.2;
    assert.strictEqual(floorPlan.contentKey(moved), floorPlan.contentKey(reference));
    const shown = floorPlan.buildUnderlayContent(new FakeDocument(), GEOMETRY, hidden);
    assert.deepStrictEqual(shown.all().filter(node => node.nodeName === 'PATH')
        .map(node => node.getAttribute('data-floor-plan-layer')), ['L0']);
});

check('labels stop at the cap and say how many were left out', () => {
    const entities = [];
    for (let index = 0; index < floorPlan.MAX_LABELS + 5; index += 1) {
        entities.push({ id: 't' + index, layer: 'L2', type: 'TEXT', at: [index, 0], height: 1, rotation: 0,
            align: 'LEFT', mirrored: false, text: 'x' });
    }
    const group = floorPlan.buildUnderlayContent(new FakeDocument(), { origin: [0, 0], entities },
        { layers: [] });
    assert.strictEqual(group.getAttribute('data-floor-plan-labels'), String(floorPlan.MAX_LABELS));
    assert.strictEqual(group.getAttribute('data-floor-plan-labels-skipped'), '5');
});

check('a label draws a few lines at most, and the drawing a bounded number in all', () => {
    const long = Array.from({ length: 2048 }, (_, index) => 'line ' + index).join('\n');
    const entities = [];
    for (let index = 0; index < 1000; index += 1) {
        entities.push({ id: 't' + index, layer: 'L2', type: 'MTEXT', at: [index, 0], height: 1, rotation: 0,
            align: 'TOP_LEFT', mirrored: false, text: long });
    }
    const group = floorPlan.buildUnderlayContent(new FakeDocument(), { origin: [0, 0], entities }, { layers: [] });
    const each = floorPlan.MAX_LINES_PER_LABEL;
    const kept = Math.floor(floorPlan.MAX_LABEL_LINES / each);
    assert.ok(kept < 1000, 'the line budget binds before the label cap');
    assert.strictEqual(group.getAttribute('data-floor-plan-labels'), String(kept));
    assert.strictEqual(group.getAttribute('data-floor-plan-label-lines'), String(kept * each));
    assert.strictEqual(group.getAttribute('data-floor-plan-labels-skipped'), String(1000 - kept));
    const spans = group.all().filter(node => node.nodeName === 'TSPAN');
    assert.strictEqual(spans.length, kept * each);
    const first = group.all().find(node => node.nodeName === 'TEXT');
    assert.deepStrictEqual(first.children.map(span => span.textContent), ['line 0', 'line 1', 'line 2', 'line 3',
        'line 4', 'line 5', 'line 6', 'line 7 ...']);
    // A label exactly the per-label size keeps every line, with no mark.
    const exact = Array.from({ length: each }, (_, index) => 'row ' + index).join('\n');
    const one = floorPlan.buildUnderlayContent(new FakeDocument(), { origin: [0, 0], entities: [
        { id: 'x', layer: 'L2', type: 'MTEXT', at: [0, 0], height: 1, rotation: 0, align: 'TOP_LEFT', text: exact }] },
    { layers: [] });
    assert.deepStrictEqual(one.all().filter(node => node.nodeName === 'TSPAN').map(span => span.textContent),
        exact.split('\n'));
});

check('snapping finds the nearest vertex within the radius, like a full search', () => {
    let seed = 7;
    const random = () => {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        return seed / 2147483648;
    };
    const entities = [];
    for (let line = 0; line < 400; line += 1) {
        entities.push({ layer: 'L1', points: [[random() * 50000, random() * 30000], [random() * 50000,
            random() * 30000]] });
    }
    entities.push({ layer: 'L1', points: [[60000, -2000], [60000.5, -2000]] });  // two points almost together
    const index = floorPlan.createSnapIndex({ entities });
    const all = entities.flatMap(entity => entity.points);
    assert.strictEqual(index.count, all.length);
    for (let query = 0; query < 300; query += 1) {
        const u = random() * 64000 - 2000;
        const v = random() * 36000 - 4000;
        const radius = [50, 400, 2500][query % 3];
        let best = null;
        all.forEach(point => {
            const distance = Math.hypot(point[0] - u, point[1] - v);
            if (distance <= radius && (!best || distance < best.distance)) best = { distance };
        });
        const found = floorPlan.nearestVertex(index, u, v, radius);
        if (!best) assert.strictEqual(found, null, `no vertex within ${radius} of ${u},${v}`);
        else near(found.distance, best.distance, 1e-9, `nearest to ${u},${v}`);
    }
    const close = floorPlan.nearestVertex(index, 60000.4, -2000, 1);
    assert.deepStrictEqual([close.u, close.v], [60000.5, -2000]);
    near(close.distance, 0.1, 1e-9, 'the nearer of two points almost together');
    assert.strictEqual(floorPlan.nearestVertex(floorPlan.createSnapIndex({ entities: [] }), 0, 0, 10), null);
    // Hidden layers are not snapped to.
    const shown = floorPlan.createSnapIndex(GEOMETRY, new Set(['L3']));
    assert.strictEqual(shown.count, 8);
    assert.deepStrictEqual(floorPlan.nearestVertex(shown, 1.2, 1.1, 5), { u: 0, v: 0, distance: Math.hypot(1.2, 1.1) });
    assert.strictEqual(floorPlan.nearestVertex(index, NaN, 0, 10), null);
    // A long thin drawing far zoomed out: the radius spans hundreds of cells and the answer is still exact.
    const line = [];
    for (let k = 0; k < 10000; k += 1) line.push([k * 0.01, 0]);
    const thin = floorPlan.createSnapIndex({ entities: [{ layer: 'L1', points: line }] });
    const above = floorPlan.nearestVertex(thin, 50, 5, 12);
    near(above.u, 50, 1e-9, 'the vertex below');
    assert.strictEqual(above.v, 0);
    near(above.distance, 5, 1e-9, 'five meters above a vertex of a 100 m line');
    assert.strictEqual(floorPlan.nearestVertex(thin, 50, 13, 12), null);
    const beyond = floorPlan.nearestVertex(thin, 105, 3, 12);  // past the end and outside the grid
    assert.deepStrictEqual([beyond.u, beyond.v], line[9999]);
    for (let query = 0; query < 200; query += 1) {
        const u = random() * 140 - 20;
        const v = random() * 40 - 20;
        const radius = [0.05, 3, 12, 40][query % 4];
        let best = null;
        line.forEach(point => {
            const distance = Math.hypot(point[0] - u, point[1] - v);
            if (distance <= radius && (!best || distance < best.distance)) best = { distance };
        });
        const found = floorPlan.nearestVertex(thin, u, v, radius);
        if (!best) assert.strictEqual(found, null, `no vertex within ${radius} of ${u},${v}`);
        else near(found.distance, best.distance, 1e-9, `nearest to ${u},${v} on the thin drawing`);
    }
});

check('a new underlay keeps the declared unit, hides what the file hides and sits at the plan origin', () => {
    const reference = floorPlan.newReference(RECORD, MANIFEST);
    assert.deepStrictEqual(Object.keys(reference).sort(), ['alignment', 'geometrySha256', 'importId', 'label',
        'layers', 'opacity', 'parserVersion', 'referenceId', 'showIn3D', 'sourceName', 'sourceSha256']);
    assert.strictEqual(reference.label, 'Plant 2');
    assert.deepStrictEqual(reference.alignment, { sourceOrigin: { u: 1000, v: 2000 }, metersPerDrawingUnit: 0.001,
        rotationDegrees: 0, translationMeters: { x: 0, z: 0 }, unitSource: 'header', confirmed: true,
        controlPoints: [] });
    assert.deepStrictEqual(reference.layers.map(layer => [layer.layerId, layer.visible]),
        [['L0', true], ['L1', true], ['L2', true], ['L3', false], ['L4', true]]);
    const unitless = floorPlan.newReference(RECORD, Object.assign({}, MANIFEST, { units: { name: null,
        metersPerUnit: null } }));
    assert.deepStrictEqual([unitless.alignment.metersPerDrawingUnit, unitless.alignment.unitSource,
        unitless.alignment.confirmed], [1, 'chosen', false]);
});

// The controller with a stand-in workspace: a session that records calls and keeps the layout, and a plan
// adapter that records what it is asked to draw.
function harness(options) {
    const settings = options || {};
    const documentRef = new FakeDocument();
    const calls = [];
    const adapter = {
        underlays: [], hovers: [], opacities: [],
        setFloorPlanUnderlay(value) { this.underlays.push(value); },
        setFloorPlanHover(value) { this.hovers.push(value); },
        setFloorPlanOpacity(value) { this.opacities.push(value); },
        planPointAt(event) { return { x: event.worldX, z: event.worldZ }; },
        planScale() { return 20; },
    };
    const workspace = {
        document: documentRef,
        viewportStack: documentRef.createElement('div'),
        topAdapter: adapter,
        viewMode: 'plan',
        state: { layout: { extensions: {} } },
        _eventWorld(event) {
            return { x: Math.round(event.worldX), y: 0, z: Math.round(event.worldZ) };
        },
    };
    let controller = null;
    const keep = function (reference) {
        const layout = { extensions: {} };
        if (reference) layout.extensions[floorPlan.KEY] = { version: 1, references: [reference] };
        workspace.state = { layout };
        controller.sync(layout);
    };
    workspace.session = {
        async importFloorPlan(file) {
            calls.push(['import', file.name]);
            if (settings.importGate) await settings.importGate;
            return { import: RECORD, manifest: settings.manifest || MANIFEST, reused: false };
        },
        async floorPlanGeometry(importId) {
            calls.push(['geometry', importId]);
            if (settings.missing) throw new Error('not found');
            return settings.geometry || GEOMETRY;
        },
        async alignFloorPlan(importId, body) {
            calls.push(['align', importId, JSON.parse(JSON.stringify(body))]);
            if (settings.alignGate) await settings.alignGate;
            return settings.alignResponse(body);
        },
        async upsertFloorPlanReference(reference) {
            calls.push(['upsert', JSON.parse(JSON.stringify(reference))]);
            keep(JSON.parse(JSON.stringify(reference)));
        },
        async deleteFloorPlanReference(referenceId) {
            calls.push(['delete', referenceId]);
            keep(null);
        },
    };
    controller = floorPlan.attach(workspace);
    return { controller, workspace, adapter, calls, keep, panel: () => controller.panel, documentRef };
}

function button(h, action) {
    const node = h.panel().querySelector('[data-fp-action="' + action + '"]');
    assert.ok(node, 'no ' + action + ' button in: ' + h.panel().text());
    return node;
}

async function importDrawing(h) {
    h.controller.open();
    const input = h.panel().querySelector('[data-fp-file]');
    input.files = [{ name: 'Plant 2.dxf', size: 1234 }];
    fire(input, 'change');
    await flush();
    await flush();
}

check('importing shows the drawing as a draft; cancel changes nothing', async () => {
    const h = harness();
    h.controller.sync(h.workspace.state.layout);
    assert.deepStrictEqual(h.adapter.underlays, [], 'nothing to draw, nothing redrawn');
    h.controller.open();
    assert.ok(/Import DXF/.test(h.panel().text()));
    fire(button(h, 'choose'), 'click');
    assert.strictEqual(h.panel().querySelector('[data-fp-file]').clicks, 1);
    await importDrawing(h);
    assert.deepStrictEqual(h.calls.map(call => call[0]), ['import', 'geometry']);
    const shown = h.adapter.underlays[h.adapter.underlays.length - 1];
    assert.strictEqual(shown.reference.importId, RECORD.importId);
    assert.strictEqual(shown.geometry, GEOMETRY);
    assert.strictEqual(shown.key, floorPlan.contentKey(shown.reference));
    const text = h.panel().text();
    assert.ok(/Plant 2\.dxf/.test(text) && /millimeters \(from the file\)/.test(text), text);
    assert.ok(/Two proxy objects were left out/.test(text), text);
    assert.ok(/WALLS \(2\)/.test(text) && /OFF \(1\)/.test(text), text);
    fire(button(h, 'cancel-draft'), 'click');
    assert.strictEqual(h.adapter.underlays[h.adapter.underlays.length - 1], null);
    assert.strictEqual(h.panel().hidden, true);
    assert.ok(!h.calls.some(call => call[0] === 'upsert'), 'cancel saves nothing');
});

check('adding saves the reference once; layers, strength and removal are edits of it', async () => {
    const h = harness();
    await importDrawing(h);
    fire(button(h, 'add'), 'click');
    await flush();
    const upserts = h.calls.filter(call => call[0] === 'upsert');
    assert.strictEqual(upserts.length, 1);
    assert.deepStrictEqual(upserts[0][1], floorPlan.newReference(RECORD, MANIFEST));
    assert.ok(/Undo removes it again/.test(h.panel().text()));
    // A layer turned off. Layers that draw nothing are not listed.
    assert.strictEqual(h.panel().querySelector('[data-fp-layer="L4"]'), null);
    assert.ok(h.panel().querySelector('[data-fp-layer="L3"]'), 'a layer off in the file is listed, unticked');
    const walls = h.panel().querySelector('[data-fp-layer="L1"]');
    assert.strictEqual(walls.checked, true);
    walls.checked = false;
    fire(walls, 'change');
    await flush();
    const hidden = h.calls[h.calls.length - 1];
    assert.strictEqual(hidden[0], 'upsert');
    assert.deepStrictEqual(hidden[1].layers.map(layer => layer.visible), [true, false, true, false, true]);
    // Dragging the strength fades the drawing at once; letting go saves it.
    const slider = h.panel().querySelector('[data-fp-opacity]');
    slider.value = '35';
    fire(slider, 'input');
    assert.deepStrictEqual(h.adapter.opacities, [0.35]);
    fire(slider, 'change');
    await flush();
    assert.strictEqual(h.calls[h.calls.length - 1][1].opacity, 0.35);
    // Hidden for now: nothing drawn, nothing saved.
    const before = h.calls.length;
    const show = h.panel().querySelector('[data-fp-show]');
    show.checked = false;
    fire(show, 'change');
    assert.strictEqual(h.adapter.underlays[h.adapter.underlays.length - 1], null);
    const again = h.panel().querySelector('[data-fp-show]');
    assert.strictEqual(again.checked, false);
    again.checked = true;
    fire(again, 'change');
    assert.strictEqual(h.adapter.underlays[h.adapter.underlays.length - 1].reference.opacity, 0.35);
    assert.strictEqual(h.calls.length, before);
    fire(button(h, 'remove'), 'click');
    await flush();
    assert.deepStrictEqual(h.calls[h.calls.length - 1], ['delete', 'fp-main']);
    assert.strictEqual(h.adapter.underlays[h.adapter.underlays.length - 1], null);
});

check('two picks on the drawing and two on the plan align it, holding a confirmed unit', async () => {
    const response = { alignment: { sourceOrigin: { u: 1000, v: 2000 }, metersPerDrawingUnit: 0.001,
        rotationDegrees: 0, translationMeters: { x: 5, z: 6 } }, scale: 'held', residualsMeters: [0, 0],
    rmsMeters: 0, maxResidualMeters: 0, impliedMetersPerDrawingUnit: 0.001, scaleRatio: 1 };
    const h = harness({ alignResponse: () => response });
    await importDrawing(h);
    fire(button(h, 'add'), 'click');
    await flush();
    fire(button(h, 'align'), 'click');
    assert.ok(/Click point A on the drawing/.test(h.panel().text()));
    assert.strictEqual(h.controller.handlePointerDown({ button: 1, worldX: 0, worldZ: 0 }), false,
        'the middle button still pans');
    h.controller.handlePointerMove({ worldX: 0.1, worldZ: 0.05 });
    assert.deepStrictEqual(h.adapter.hovers[h.adapter.hovers.length - 1], { x: 0, z: 0, snapped: true });
    // 12 px at 20 px/m is 0.6 m: (0.1, 0.05) snaps to the corner at drawing (1000, 2000), plan (0, 0).
    assert.strictEqual(h.controller.handlePointerDown({ button: 0, worldX: 0.1, worldZ: 0.05 }), true);
    let drawn = h.adapter.underlays[h.adapter.underlays.length - 1];
    assert.deepStrictEqual(drawn.markers, [{ x: 0, z: 0, label: 'A', kind: 'drawing' }]);
    assert.strictEqual(drawn.picking, true);
    h.controller.handlePointerDown({ button: 0, worldX: 4.8, worldZ: 6.2 });  // the plan's own snap: (5, 6)
    h.controller.handlePointerDown({ button: 0, worldX: 10.2, worldZ: 0.1 });  // snaps to drawing (11000, 2000)
    h.controller.handlePointerDown({ button: 0, worldX: 15, worldZ: 6 });
    await flush();
    const align = h.calls.find(call => call[0] === 'align');
    assert.deepStrictEqual(align[2], { controlPoints: [
        { source: { u: 1000, v: 2000 }, target: { x: 5, z: 6 } },
        { source: { u: 11000, v: 2000 }, target: { x: 15, z: 6 } },
    ], metersPerDrawingUnit: 0.001 });
    drawn = h.adapter.underlays[h.adapter.underlays.length - 1];
    assert.deepStrictEqual(drawn.markers.map(marker => marker.label), ['A', 'A\'', 'B', 'B\'']);
    assert.ok(/Points off by up to 0 m/.test(h.panel().text()), h.panel().text());
    fire(button(h, 'apply-alignment'), 'click');
    await flush();
    const saved = h.calls[h.calls.length - 1];
    assert.strictEqual(saved[0], 'upsert');
    assert.deepStrictEqual(saved[1].alignment, { sourceOrigin: { u: 1000, v: 2000 }, metersPerDrawingUnit: 0.001,
        rotationDegrees: 0, translationMeters: { x: 5, z: 6 }, unitSource: 'header', confirmed: true,
        controlPoints: align[2].controlPoints });
    assert.deepStrictEqual(h.adapter.underlays[h.adapter.underlays.length - 1].markers, []);
});

check('a drawing without a unit is scaled from a known length, or by choosing the unit', async () => {
    const manifest = Object.assign({}, MANIFEST, { units: { name: null, metersPerUnit: null } });
    const geometry = Object.assign({}, GEOMETRY, { units: manifest.units });
    const h = harness({ manifest, geometry, alignResponse: body => ({ metersPerDrawingUnit:
        body.distance.meters / Math.hypot(body.distance.b.u - body.distance.a.u, body.distance.b.v - body.distance.a.v)
    }) });
    await importDrawing(h);
    assert.ok(/does not say what unit/.test(h.panel().text()));
    fire(button(h, 'measure'), 'click');
    // Unconfirmed, the drawing is shown at 1 m per unit: drawing (1000, 2000) and (11000, 2000) are at x 0 and
    // 10000. 12 px at 20 px/m is 0.6 m, so 0.6 units.
    h.controller.handlePointerDown({ button: 0, worldX: 0.1, worldZ: 0.05 });
    h.controller.handlePointerDown({ button: 0, worldX: 9999.8, worldZ: -0.3 });
    assert.deepStrictEqual(h.adapter.underlays[h.adapter.underlays.length - 1].markers.map(marker => marker.label),
        ['A', 'B']);
    assert.ok(/Drawing length: 10000 units/.test(h.panel().text()), h.panel().text());
    h.panel().querySelector('[data-fp-distance]').value = '12';
    fire(button(h, 'apply-distance'), 'click');
    await flush();
    await flush();
    assert.deepStrictEqual(h.calls.find(call => call[0] === 'align')[2], { distance: {
        a: { u: 1000, v: 2000 }, b: { u: 11000, v: 2000 }, meters: 12 } });
    let draft = h.controller.currentReference();
    assert.deepStrictEqual([draft.alignment.metersPerDrawingUnit, draft.alignment.unitSource,
        draft.alignment.confirmed], [0.0012, 'calibrated', true]);
    assert.ok(!h.calls.some(call => call[0] === 'upsert'), 'a draft is changed in place, not saved');
    // Choosing the unit instead.
    const h2 = harness({ manifest, geometry });
    await importDrawing(h2);
    const select = h2.panel().querySelector('[data-fp-unit]');
    select.value = 'feet';
    fire(select, 'change');
    draft = h2.controller.currentReference();
    assert.deepStrictEqual([draft.alignment.metersPerDrawingUnit, draft.alignment.unitSource,
        draft.alignment.confirmed], [0.3048, 'chosen', true]);
});

check('an underlay whose drawing is not stored says so and draws nothing', async () => {
    const h = harness({ missing: true });
    h.keep(floorPlan.newReference(RECORD, MANIFEST));
    await flush();
    await flush();
    assert.ok(!h.adapter.underlays.some(Boolean));
    h.controller.open();
    await flush();
    await flush();
    assert.ok(/not stored here/.test(h.panel().text()), h.panel().text());
    assert.strictEqual(button(h, 'align').disabled, true);
});

check('closing while a drawing is read drops it; a length being typed survives unrelated updates', async () => {
    let release;
    const h = harness({ importGate: new Promise(resolve => { release = resolve; }),
        alignResponse: () => ({ metersPerDrawingUnit: 0.001 }) });
    h.controller.open();
    const input = h.panel().querySelector('[data-fp-file]');
    input.files = [{ name: 'Plant 2.dxf', size: 1234 }];
    fire(input, 'change');
    assert.ok(/Reading Plant 2\.dxf/.test(h.panel().text()));
    fire(button(h, 'close'), 'click');  // allowed while busy
    release();
    await flush();
    await flush();
    assert.strictEqual(h.controller.draft, null);
    assert.ok(!h.adapter.underlays.some(Boolean), 'nothing is drawn');
    h.controller.open();
    assert.ok(/Import DXF/.test(h.panel().text()), 'the panel is ready for another file');
    assert.strictEqual(button(h, 'choose').disabled, false);
    // A saved underlay, a length measured, a value half typed, then an update that changes no underlay.
    h.keep(floorPlan.newReference(RECORD, MANIFEST));
    await flush();
    await flush();
    fire(button(h, 'measure'), 'click');
    h.controller.handlePointerDown({ button: 0, worldX: 0.01, worldZ: 0 });
    h.controller.handlePointerDown({ button: 0, worldX: 9.99, worldZ: 0 });
    const length = h.panel().querySelector('[data-fp-distance]');
    length.value = '1';
    fire(length, 'input');
    h.controller.sync(h.workspace.state.layout);
    assert.strictEqual(h.panel().querySelector('[data-fp-distance]'), length, 'not drawn again');
    h.controller.render();
    assert.strictEqual(h.panel().querySelector('[data-fp-distance]').value, '1', 'kept when it is');
});

check('a preview without an underlay hides the saved one; picks wait for the Plan view', async () => {
    const h = harness();
    h.keep(floorPlan.newReference(RECORD, MANIFEST));
    await flush();
    await flush();
    assert.ok(h.adapter.underlays[h.adapter.underlays.length - 1]);
    h.controller.sync({ extensions: {} });  // a candidate layout without the underlay
    assert.strictEqual(h.adapter.underlays[h.adapter.underlays.length - 1], null);
    h.controller.sync(h.workspace.state.layout);
    h.workspace.viewMode = '3d';
    h.controller.open();
    fire(button(h, 'align'), 'click');
    assert.ok(/Switch to the Plan view/.test(h.panel().text()));
    assert.strictEqual(h.controller.handlePointerDown({ button: 0, worldX: 0, worldZ: 0 }), false);
});

// A held alignment answer: the drawing moved 5 m along x and 6 m along z.
const HELD = { alignment: { sourceOrigin: { u: 1000, v: 2000 }, metersPerDrawingUnit: 0.001, rotationDegrees: 0,
    translationMeters: { x: 5, z: 6 } }, scale: 'held', residualsMeters: [0, 0], rmsMeters: 0, maxResidualMeters: 0,
impliedMetersPerDrawingUnit: 0.001, scaleRatio: 1 };

function pickAll(h, picks) {
    picks.forEach(([x, z, at]) => h.controller.handlePointerDown({ button: 0, worldX: x, worldZ: z,
        timeStamp: at }));
}

async function measured(h) {
    h.keep(floorPlan.newReference(RECORD, MANIFEST));
    await flush();
    await flush();
    h.controller.open();
    fire(button(h, 'measure'), 'click');
    pickAll(h, [[0.01, 0], [9.99, 0]]);
    h.panel().querySelector('[data-fp-distance]').value = '12';
    fire(button(h, 'apply-distance'), 'click');
}

check('an undo while the scale is worked out drops the answer: it never puts the underlay back', async () => {
    let release;
    const h = harness({ alignGate: new Promise(resolve => { release = resolve; }),
        alignResponse: () => ({ metersPerDrawingUnit: 0.0012 }) });
    await measured(h);
    assert.strictEqual(h.controller.busy, true);
    h.keep(null);  // Undo of adding the underlay, while the scale is worked out
    release();
    await flush();
    await flush();
    assert.ok(!h.calls.some(call => call[0] === 'upsert'), 'the answer does not put the underlay back');
    assert.strictEqual(h.controller.busy, false);
    assert.strictEqual(h.controller.result, null);
    assert.ok(/changed while the scale was worked out/.test(h.panel().text()), h.panel().text());
});

check('an alignment worked out for one drawing is dropped when an undo brings back another', async () => {
    const h = harness({ alignResponse: () => HELD });
    const first = floorPlan.newReference(RECORD, MANIFEST);
    const second = Object.assign(JSON.parse(JSON.stringify(first)), { importId: 'fpi-' + 'd'.repeat(32) });
    h.keep(second);
    await flush();
    await flush();
    h.controller.open();
    fire(button(h, 'align'), 'click');
    pickAll(h, [[0.1, 0.05], [5, 6], [10.2, 0.1], [15, 6]]);
    await flush();
    assert.ok(h.panel().querySelector('[data-fp-action="apply-alignment"]'));
    // Showing or hiding a layer keeps the result.
    const layerOff = JSON.parse(JSON.stringify(second));
    layerOff.layers[1].visible = false;
    h.keep(layerOff);
    assert.ok(h.panel().querySelector('[data-fp-action="apply-alignment"]'), 'kept over a layer change');
    h.keep(first);  // Undo of the replacement brings the first drawing back
    assert.strictEqual(h.panel().querySelector('[data-fp-action="apply-alignment"]'), null);
    assert.strictEqual(h.controller.result, null);
    assert.ok(/points picked on it were dropped/.test(h.panel().text()), h.panel().text());
    h.controller.applyAlignment();
    assert.ok(!h.calls.some(call => call[0] === 'upsert'), 'nothing is applied to the other drawing');
});

check('a workspace going away drops answers still on their way', async () => {
    let release;
    const h = harness({ alignGate: new Promise(resolve => { release = resolve; }),
        alignResponse: () => ({ metersPerDrawingUnit: 0.0012 }) });
    await measured(h);
    const drawn = h.adapter.underlays.length;
    h.controller.dispose();
    assert.strictEqual(h.controller.panel, null);
    release();
    await flush();
    await flush();
    assert.ok(!h.calls.some(call => call[0] === 'upsert'), 'nothing is saved after');
    assert.strictEqual(h.adapter.underlays.length, drawn, 'nothing is drawn after');
});

check('a preview shows its own underlay, never the draft, and holds the picks', async () => {
    const h = harness();
    await importDrawing(h);  // a draft, not yet added
    assert.strictEqual(h.adapter.underlays[h.adapter.underlays.length - 1].reference.importId, RECORD.importId);
    fire(button(h, 'align'), 'click');
    pickAll(h, [[0.1, 0.05]]);
    h.controller.sync({ extensions: {} }, { preview: true });  // a candidate without an underlay
    assert.strictEqual(h.adapter.underlays[h.adapter.underlays.length - 1], null, 'the draft is not drawn under it');
    assert.strictEqual(h.controller.picking, null);
    assert.ok(/A preview is showing/.test(h.panel().text()), h.panel().text());
    fire(button(h, 'align'), 'click');
    assert.ok(/Close it to pick points/.test(h.panel().text()), h.panel().text());
    assert.strictEqual(h.controller.picking, null);
    h.controller.sync(h.workspace.state.layout);  // the preview closed
    assert.strictEqual(h.adapter.underlays[h.adapter.underlays.length - 1].reference.importId, RECORD.importId,
        'the draft shows again');
    assert.ok(h.controller.draft, 'and is still there to add');
});

function toolHarness(options) {
    const h = harness(options);
    h.modes = [];
    h.toolOptions = [];
    h.workspace.toolMode = 'polygon-zone';
    h.workspace._setToolMode = function (mode, options) {
        h.modes.push(mode);
        h.toolOptions.push(options);
        this.toolMode = mode;
    };
    return h;
}

async function keptAndOpen(h) {
    h.keep(floorPlan.newReference(RECORD, MANIFEST));
    await flush();
    await flush();
    h.controller.open();
}

check('picks set the drawing tool aside and own the clicks of their presses, however long held', async () => {
    const h = toolHarness({ alignResponse: () => HELD });
    await keptAndOpen(h);
    fire(button(h, 'align'), 'click');
    assert.deepStrictEqual(h.modes, ['select']);
    assert.strictEqual(h.controller.ownsClick({ detail: 1 }), true, 'while picking');
    pickAll(h, [[0.1, 0.05], [5, 6], [10.2, 0.1], [15, 6]]);
    assert.deepStrictEqual(h.modes, ['select', 'polygon-zone'], 'given back after the last pick');
    assert.deepStrictEqual(h.toolOptions, [{ keepPicks: true }, { keepPicks: true }],
        'setting the tool aside and giving it back are the picks\' own switches, not a tool chosen');
    // The last press, held as long as you like: the click that ends it is the pick's.
    assert.strictEqual(h.controller.ownsClick({ detail: 1 }), true, 'the click that ends the last press');
    // A double click on the last point: its second press is the picks' too (the tool given back never sees it), and
    // so are its clicks. It picks nothing.
    h.controller.forgetPress();
    assert.strictEqual(h.controller.handlePointerDown({ button: 0, worldX: 15, worldZ: 6 }), true);
    assert.strictEqual(h.controller.picking, null, 'no new pick');
    assert.strictEqual(h.controller.ownsClick({ detail: 2 }), true, 'the second click of a double click on it');
    assert.strictEqual(h.controller.ownsDoubleClick({}), true, 'and the double click');
    // A new click straight after is the tool's.
    h.controller.forgetPress();
    h.controller.handlePointerDown({ button: 0, worldX: 3, worldZ: 3 });
    assert.strictEqual(h.controller.ownsClick({ detail: 1 }), false, 'a new click is the tool one');
    assert.strictEqual(h.controller.ownsDoubleClick({}), false);
    await flush();
    fire(button(h, 'cancel-pick'), 'click');  // the result discarded
    // A tool the user chose while picking is left alone.
    h.workspace.toolMode = 'polygon-zone';
    fire(button(h, 'align'), 'click');
    h.workspace.toolMode = 'aisle';
    fire(button(h, 'cancel-pick'), 'click');
    assert.deepStrictEqual(h.modes, ['select', 'polygon-zone', 'select']);
    assert.strictEqual(h.workspace.toolMode, 'aisle');
});

check('picks do not begin while a tool that runs its own panel, or a light area, is drawing', async () => {
    for (const [mode, name] of [['motion-path', 'Motion path'], ['aisle', 'Aisle'], ['floor-marking', 'Floor marking']]) {
        const h = toolHarness();
        h.workspace.toolMode = mode;
        await keptAndOpen(h);
        fire(button(h, 'measure'), 'click');
        assert.strictEqual(h.controller.picking, null, mode);
        assert.deepStrictEqual(h.modes, [], mode + ' is left as it is');
        assert.ok(h.panel().text().includes('Choose Select first. The ' + name + ' tool is using the clicks on the '
            + 'plan.'), h.panel().text());
    }
    const lit = toolHarness();
    lit.workspace.toolMode = 'select';
    lit.workspace.lightAreaDraw = { kind: 'light-area' };
    await keptAndOpen(lit);
    fire(button(lit, 'align'), 'click');
    assert.strictEqual(lit.controller.picking, null);
    assert.ok(/Finish drawing the light area first/.test(lit.panel().text()), lit.panel().text());
});

check('while picking, a press of another button picks nothing and reaches no tool; the middle one pans', async () => {
    const h = toolHarness();
    await keptAndOpen(h);
    fire(button(h, 'measure'), 'click');
    assert.strictEqual(h.controller.handlePointerDown({ button: 2, worldX: 1, worldZ: 1 }), true, 'right');
    assert.strictEqual(h.controller.ownsClick({ detail: 1 }), true, 'and whatever click it ends in');
    assert.strictEqual(h.controller.handlePointerDown({ button: 1, worldX: 1, worldZ: 1 }), false, 'middle pans');
    assert.strictEqual(h.controller.picking.points.length, 0);
    pickAll(h, [[0.01, 0]]);
    assert.strictEqual(h.controller.picking.points.length, 1);
    fire(button(h, 'cancel-pick'), 'click');
});

check('a tool chosen right after the last pick takes the next press there', async () => {
    const h = toolHarness({ alignResponse: () => HELD });
    await keptAndOpen(h);
    fire(button(h, 'align'), 'click');
    pickAll(h, [[0.1, 0.05], [5, 6], [10.2, 0.1]]);
    h.controller.handlePointerDown({ button: 0, worldX: 15, worldZ: 6, timeStamp: 1000, clientX: 100, clientY: 100 });
    assert.strictEqual(h.controller.picking, null, 'the picks ended');
    h.controller.forgetPress();
    h.controller.toolChosen();  // the user pressed H for the hand tool
    const press = { button: 0, worldX: 15, worldZ: 6, timeStamp: 1200, clientX: 100, clientY: 100 };
    assert.strictEqual(h.controller.handlePointerDown(press), false, 'the hand tool has it');
    assert.strictEqual(h.controller.ownsClick({ detail: 2 }), false);
    await flush();
    await flush();
});

check('only a double click on the last point is held back from the tool given back', async () => {
    const cases = [
        ['the second press there', { timeStamp: 1400, clientX: 102, clientY: 98 }, true],
        ['a press 600 ms after', { timeStamp: 1600, clientX: 100, clientY: 100 }, false],
        ['a press 10 px away', { timeStamp: 1200, clientX: 110, clientY: 100 }, false],
        ['a right press there', { timeStamp: 1200, clientX: 100, clientY: 100, button: 2 }, false],
    ];
    for (const [label, press, expected] of cases) {
        const h = toolHarness({ alignResponse: () => HELD });
        await keptAndOpen(h);
        fire(button(h, 'align'), 'click');
        pickAll(h, [[0.1, 0.05], [5, 6], [10.2, 0.1]]);
        h.controller.handlePointerDown({ button: 0, worldX: 15, worldZ: 6, timeStamp: 1000, clientX: 100,
            clientY: 100 });
        assert.strictEqual(h.controller.picking, null, label + ': the picks ended');
        h.controller.forgetPress();
        const next = Object.assign({ button: 0, worldX: 15, worldZ: 6 }, press);
        assert.strictEqual(h.controller.handlePointerDown(next), expected, label);
        assert.strictEqual(h.controller.ownsClick({ detail: 1 }), expected, label + ': its click');
        // Asked once: a third press there is the tool's.
        h.controller.forgetPress();
        assert.strictEqual(h.controller.handlePointerDown(Object.assign({}, next, { timeStamp: 1450 })), false,
            label + ': the press after');
        await flush();
        await flush();
    }
});

check('a pick press that ends off the plan leaves no claim on the next click', async () => {
    const h = toolHarness({ alignResponse: () => HELD });
    await keptAndOpen(h);
    fire(button(h, 'align'), 'click');
    pickAll(h, [[0.1, 0.05], [5, 6], [10.2, 0.1], [15, 6]]);  // the last press released over the panel: no click
    h.controller.forgetPress();  // the next press on the plan
    assert.strictEqual(h.controller.ownsClick({ detail: 1 }), false);
    assert.strictEqual(h.controller.ownsDoubleClick({}), false);
    await flush();
});

check('a tool chosen while picking ends the picks, and the tool set aside is not put back', async () => {
    const h = toolHarness();
    await keptAndOpen(h);
    fire(button(h, 'align'), 'click');
    pickAll(h, [[0.1, 0.05]]);
    assert.strictEqual(h.workspace.toolMode, 'select');
    h.controller.toolChosen();  // the user chose a tool (the workspace says so before setting it)
    assert.strictEqual(h.controller.picking, null, 'the picks end');
    assert.deepStrictEqual(h.modes, ['select'], 'Polygon zone is not put back');
    assert.strictEqual(h.workspace.toolMode, 'select');
    assert.deepStrictEqual(h.adapter.hovers[h.adapter.hovers.length - 1], null, 'the hover ring goes');
    assert.strictEqual(h.panel().querySelector('[data-fp-action="cancel-pick"]'), null);
});

check('removing or replacing the drawing while picking ends the picks and gives the tool back', async () => {
    const h = toolHarness();
    await keptAndOpen(h);
    fire(button(h, 'measure'), 'click');
    assert.strictEqual(h.workspace.toolMode, 'select');
    fire(button(h, 'remove'), 'click');
    assert.strictEqual(h.controller.picking, null);
    assert.strictEqual(h.workspace.toolMode, 'polygon-zone', 'given back when the drawing is removed');
    await flush();
    await keptAndOpen(h);
    fire(button(h, 'measure'), 'click');
    pickAll(h, [[0.01, 0]]);
    assert.strictEqual(h.workspace.toolMode, 'select');
    const input = h.panel().querySelector('[data-fp-file]');
    input.files = [{ name: 'Plant 3.dxf', size: 99 }];
    fire(input, 'change');
    assert.strictEqual(h.controller.picking, null);
    assert.strictEqual(h.workspace.toolMode, 'polygon-zone', 'given back when another drawing is chosen');
    assert.deepStrictEqual(h.adapter.hovers[h.adapter.hovers.length - 1], null, 'the hover ring goes');
    await flush();
    await flush();
});

check('an answer on its way is dropped after an undo and a redo, or a preview opened, even once it closed',
    async () => {
        // Set scale; Undo then Redo bring the same drawing back before the answer.
        let release;
        const h = harness({ alignGate: new Promise(resolve => { release = resolve; }),
            alignResponse: () => ({ metersPerDrawingUnit: 0.0012 }) });
        await measured(h);
        assert.strictEqual(h.controller.busy, true);
        const reference = JSON.parse(JSON.stringify(floorPlan.referenceOf(h.workspace.state.layout)));
        h.keep(null);
        h.keep(reference);
        release();
        await flush();
        await flush();
        assert.ok(!h.calls.some(call => call[0] === 'upsert'), 'the scale is not saved');
        assert.strictEqual(h.controller.busy, false);
        assert.ok(/changed while the scale was worked out/.test(h.panel().text()), h.panel().text());

        // Align; a preview opens and closes before the answer.
        let releaseAlign;
        const g = harness({ alignGate: new Promise(resolve => { releaseAlign = resolve; }),
            alignResponse: () => HELD });
        await keptAndOpen(g);
        fire(button(g, 'align'), 'click');
        pickAll(g, [[0.1, 0.05], [5, 6], [10.2, 0.1], [15, 6]]);
        assert.strictEqual(g.controller.busy, true);
        g.controller.sync({ extensions: {} }, { preview: true });
        g.controller.sync(g.workspace.state.layout);
        releaseAlign();
        await flush();
        await flush();
        assert.strictEqual(g.controller.result, null, 'no alignment comes back to apply');
        assert.strictEqual(g.panel().querySelector('[data-fp-action="apply-alignment"]'), null);

        // Set scale; a preview is still showing when the answer comes.
        let releaseScale;
        const k = harness({ alignGate: new Promise(resolve => { releaseScale = resolve; }),
            alignResponse: () => ({ metersPerDrawingUnit: 0.0012 }) });
        await measured(k);
        k.controller.sync({ extensions: {} }, { preview: true });
        releaseScale();
        await flush();
        await flush();
        assert.ok(!k.calls.some(call => call[0] === 'upsert'), 'nothing is saved under a preview');
        assert.ok(/A preview opened while the scale was worked out/.test(k.panel().text()), k.panel().text());
    });

check('a drawing imported as a draft keeps its first alignment answer through unrelated updates', async () => {
    let release;
    const h = harness({ alignGate: new Promise(resolve => { release = resolve; }), alignResponse: () => HELD });
    await importDrawing(h);  // a draft: the drawing the picks are on changed without an undo
    fire(button(h, 'align'), 'click');
    pickAll(h, [[0.1, 0.05], [5, 6], [10.2, 0.1], [15, 6]]);
    h.controller.sync(h.workspace.state.layout);  // an unrelated render while it is worked out
    release();
    await flush();
    await flush();
    assert.strictEqual(h.controller.result && h.controller.result.kind, 'align', h.panel().text());
});

// FP2: the Walls and rooms section. A saved underlay whose layers carry ROLES, on a layout saved at revision r1.
const WALL_A = 'iw-fp-' + '1'.repeat(16);
const WALL_B = 'iw-fp-' + '2'.repeat(16);
const OUTLINE_A = 'ol-fp-' + 'a'.repeat(16);
const OUTLINE_B = 'ol-fp-' + 'b'.repeat(16);
const ROOM = 'zn-fp-' + 'c'.repeat(16);
const DOOR_A = 'dr-fp-' + 'd'.repeat(16);
const DOOR_B = 'dr-fp-' + 'e'.repeat(16);

function wallsAnswer(settings) {
    const height = settings.walls && settings.walls.heightMeters;
    const left = (settings.excluded || []).includes(WALL_A);
    const first = { candidateId: WALL_A, label: 'Drawing wall 1', start: { x: 0, z: 0 }, end: { x: 10, z: 0 },
        thicknessMeters: 0.2, lengthMeters: 10, from: 'faces', layers: ['L1'], sources: ['e1'],
        heightMeters: height || null, state: left ? 'excluded' : height ? 'new' : 'waiting',
        reason: left || height ? null : 'wall_settings',
        message: left || height ? null : 'Give the wall height to add the walls.' };
    const second = { candidateId: WALL_B, label: 'Drawing wall 2', start: { x: 5, z: 0 }, end: { x: 5, z: 8 },
        thicknessMeters: 0.2, lengthMeters: 8, from: 'faces', layers: ['L1'], sources: ['e2'], heightMeters: null,
        state: 'refused', reason: 'wall_there', message: 'A wall is already on the plan here.' };
    const operations = first.state === 'new' ? 1 : 0;
    return { converterVersion: 'fp-convert-1', importId: RECORD.importId, referenceId: 'fp-main', settings,
        walls: [first, second], rooms: [], outlines: [],
        unconverted: [{ entityId: 'e9', layerId: 'L1', reason: 'curve', message: 'A curve: it stays as drawing.' }],
        unconvertedCounts: { curve: 3 }, layers: { L1: { name: 'WALLS', role: 'wall_faces' } },
        summary: { walls: first.state === 'waiting' ? { refused: 1, waiting: 1 } : { [first.state]: 1, refused: 1 },
            rooms: {}, outlines: {}, operations, wallsOnPlan: 1, wallLimit: 128,
            blocked: operations ? null : { code: 'nothing_to_add', message: 'Nothing new to add.' } } };
}

function outlinesAnswer(settings) {
    const loop = settings.outline && settings.outline.loop;
    const outline = (id, area) => ({ candidateId: id, boundary: [{ x: 0, z: 0 }, { x: 20, z: 0 }, { x: 20, z: 10 },
        { x: 0, z: 10 }], thicknessMeters: 0.3, from: 'line', areaSquareMeters: area, layers: ['L1'], sources: ['e1'],
        replaces: loop ? { boundarySource: 'plan', openings: 1, exteriorFinish: false } : null });
    const a = Object.assign(outline(OUTLINE_A, 200), loop === OUTLINE_A
        ? { state: settings.outline.replace ? 'new' : 'waiting', reason: settings.outline.replace ? null : 'replace_needed',
            message: settings.outline.replace ? null : 'The plan already has outer walls; choose Replace to swap them.' }
        : { state: loop ? 'refused' : 'waiting', reason: loop ? 'other_outline' : 'choose_outline',
            message: loop ? 'Another outline was chosen.' : 'Choose which outline is the building.' });
    const b = Object.assign(outline(OUTLINE_B, 50), loop === OUTLINE_B ? { state: 'new', reason: null, message: null }
        : { state: loop ? 'refused' : 'waiting', reason: loop ? 'other_outline' : 'choose_outline',
            message: loop ? 'Another outline was chosen.' : 'Choose which outline is the building.' });
    const kind = settings.rooms && (settings.rooms.types[ROOM] || settings.rooms.zoneType);
    const room = { candidateId: ROOM, boundary: [], areaSquareMeters: 20, label: 'Office', labelFrom: 'text',
        zoneType: kind || null, layers: ['L3'], sources: ['r1'], state: kind ? 'new' : 'waiting',
        reason: kind ? null : 'zone_type', message: kind ? null : 'Choose its zone type.' };
    return { converterVersion: 'fp-convert-1', importId: RECORD.importId, referenceId: 'fp-main', settings,
        walls: [], rooms: [room], outlines: [a, b], unconverted: [], unconvertedCounts: {}, layers: {},
        summary: { walls: {}, rooms: { [room.state]: 1 }, outlines: { waiting: 2 }, operations: 1, wallsOnPlan: 0,
            wallLimit: 128, blocked: null } };
}

// A wall with a door in it, and outer walls with a double door that waits for the doors' height.
function doorsAnswer(settings) {
    const height = settings.doors && settings.doors.heightMeters;
    const left = (settings.excluded || []).includes(DOOR_A);
    const wall = { candidateId: WALL_A, label: 'Drawing wall 1', start: { x: 0, z: 0 }, end: { x: 10, z: 0 },
        thicknessMeters: 0.2, lengthMeters: 10, openings: left ? [] : [{ startMeters: 4, endMeters: 5 }],
        from: 'centerline', layers: ['L1'], sources: ['e1', 'e2'], heightMeters: 3, state: 'new', reason: null,
        message: null };
    const outline = { candidateId: OUTLINE_A, boundary: [{ x: 0, z: 0 }, { x: 20, z: 0 }, { x: 20, z: 10 },
        { x: 0, z: 10 }], thicknessMeters: 0.3, from: 'line', areaSquareMeters: 200, layers: ['L3'], sources: ['o1'],
        replaces: null, state: height ? 'new' : 'waiting', reason: height ? null : 'door_settings',
        message: height ? null : "Give the outer doors' height to add the outer walls with their doors, or leave the "
            + 'doors out.' };
    const inner = { candidateId: DOOR_A, kind: 'single', widthMeters: 1, at: { x: 4.5, z: 0 }, layers: ['L2'],
        sources: ['d1'], wall: WALL_A, wallLabel: 'Drawing wall 1', outline: null, edge: null, label: 'Drawing door 1',
        state: left ? 'excluded' : 'new', reason: null, message: null };
    const outer = { candidateId: DOOR_B, kind: 'double', widthMeters: 2, at: { x: 20, z: 6 }, layers: ['L2'],
        sources: ['d2', 'd3', 'l2', 'l3'], wall: null, wallLabel: null, outline: OUTLINE_A, edge: 1,
        label: 'Drawing door 2', state: outline.state, reason: outline.reason, message: outline.message };
    const doors = {};
    [inner, outer].forEach(row => { doors[row.state] = (doors[row.state] || 0) + 1; });
    return { converterVersion: 'fp-convert-2', importId: RECORD.importId, referenceId: 'fp-main', settings,
        walls: [wall], rooms: [], outlines: [outline], doors: [inner, outer],
        unconverted: [{ entityId: 'd9', layerId: 'L2', reason: 'door_leaf_missing', message: 'A door swing on the '
            + 'outer walls without its door leaf: an arc alone is not enough to cut a door there; it stays drawing.' }],
        unconvertedCounts: { door_leaf_missing: 1 }, layers: {},
        summary: { walls: { new: 1 }, rooms: {}, outlines: { [outline.state]: 1 }, doors, operations: height ? 2 : 1,
            wallsOnPlan: 0, wallLimit: 128, blocked: null } };
}

function converting(options) {
    const settings = options || {};
    const h = harness();
    const reference = floorPlan.newReference(RECORD, MANIFEST);
    const roles = settings.roles || { L1: 'wall_faces', L2: 'text' };
    reference.layers.forEach(layer => { layer.role = roles[layer.layerId] || 'reference'; });
    if (settings.unitOpen) Object.assign(reference.alignment, { unitSource: 'chosen', confirmed: false });
    h.keep(reference);
    h.save = function (revision) {
        h.workspace.state = Object.assign({}, h.workspace.state, { baseRevision: revision, dirty: false });
    };
    h.workspace.state.layout.layoutId = 'fl-1';
    h.workspace.state.layout.association = { siteId: 'site-1' };
    h.save('r1');
    h.workspace.state.dirty = Boolean(settings.dirty);
    h.workspace.session.convertFloorPlan = async (importId, body) => {
        h.calls.push(['convert', importId, JSON.parse(JSON.stringify(body))]);
        if (settings.convertGate) await settings.convertGate;
        if (settings.convertError) throw settings.convertError;
        const answer = { baseRevision: body.baseRevision, stage: body.stage,
            conversion: (settings.answer || wallsAnswer)(body.settings) };
        if (body.stage === 'proposal') answer.proposal = { proposalId: 'flp-1', approvalRequired: true };
        return answer;
    };
    h.workspace.session.fetchAndInstallOperationProposal = async (reference, options) => {
        h.calls.push(['install', reference, options]);
        h.controller.sync(h.workspace.state.layout, { preview: true });  // the workspace shows the change
    };
    return h;
}

async function settle() {
    await flush();
    await flush();
}

function field(h, name) {
    const node = h.panel().querySelector('[data-fp-setting="' + name + '"]');
    assert.ok(node, 'no ' + name + ' field in: ' + h.panel().text());
    return node;
}

check('each layer says what it shows; a role is kept in a draft, else one undoable edit', async () => {
    const h = harness();
    await keptAndOpen(h);
    const select = h.panel().querySelector('[data-fp-role="L1"]');
    assert.ok(select, h.panel().text());
    assert.strictEqual(select.value, 'reference');
    assert.deepStrictEqual(select.children.map(option => option.getAttribute('value')),
        floorPlan.ROLE_OPTIONS.map(option => option[0]));
    select.value = 'wall_faces';
    fire(select, 'change');
    await settle();
    const upserts = h.calls.filter(call => call[0] === 'upsert');
    assert.strictEqual(upserts.length, 1);
    assert.deepStrictEqual(upserts[0][1].layers.find(layer => layer.layerId === 'L1'),
        { layerId: 'L1', visible: true, role: 'wall_faces' });
    assert.strictEqual(h.panel().querySelector('[data-fp-role="L1"]').value, 'wall_faces');
    const d = harness();
    await importDrawing(d);
    const draftRole = d.panel().querySelector('[data-fp-role="L2"]');
    draftRole.value = 'text';
    fire(draftRole, 'change');
    assert.ok(!d.calls.some(call => call[0] === 'upsert'), 'a draft saves nothing');
    assert.strictEqual(d.controller.draft.reference.layers.find(layer => layer.layerId === 'L2').role, 'text');
});

check('the panel offers exactly the roles and zone types the server takes, named as the zones name them', () => {
    const python = fs.readFileSync(path.join(ROOT, 'ai_inspector', 'facility_layout', 'floor_plan_references.py'),
        'utf8');
    const roles = /^ROLES = \(([^)]*)\)/m.exec(python)[1].match(/"([a-z_]+)"/g).map(item => item.slice(1, -1));
    // Listed in the panel's own order (room names beside room outlines); the same roles as the server's.
    assert.deepStrictEqual(floorPlan.ROLE_OPTIONS.map(option => option[0]).sort(), roles.slice().sort());
    const converter = fs.readFileSync(path.join(ROOT, 'ai_inspector', 'facility_layout', 'floor_plan_conversion.py'),
        'utf8');
    const zones = /^ZONE_TYPES = \(([^)]*)\)/m.exec(converter)[1].match(/"([a-z_]+)"/g).map(item => item.slice(1, -1));
    assert.deepStrictEqual(floorPlan.ZONE_TYPE_OPTIONS.map(option => option[0]).sort(), zones.slice().sort());
    const workspace = fs.readFileSync(path.join(ROOT, 'static', 'facility_layout_workspace.js'), 'utf8');
    const block = /const ZONE_PURPOSE_OPTIONS = Object\.freeze\(\[([\s\S]*?)\]\);/.exec(workspace)[1];
    const named = [...block.matchAll(/value: '([a-z_]+)', label: '([^']*)'/g)].map(match => [match[1], match[2]]);
    assert.deepStrictEqual(floorPlan.ZONE_TYPE_OPTIONS, named);
});

check('the settings sent are the fields the layers call for, heights optional', () => {
    const form = { wallHeight: ' 3 ', wallThickness: '0.25', maxThickness: '', outlineHeight: 'abc',
        outlineThickness: '0.3', zoneType: '', types: { [ROOM]: 'storage' }, loop: OUTLINE_B, replace: true,
        excluded: [WALL_B, WALL_A] };
    assert.deepStrictEqual(floorPlan.conversionSettings(form, new Set(['wall_centerline', 'perimeter',
        'room_boundary'])), {
        excluded: [WALL_A, WALL_B],
        walls: { heightMeters: 3, thicknessMeters: 0.25 },
        outline: { replace: true, thicknessMeters: 0.3, loop: OUTLINE_B },
        rooms: { zoneType: null, types: { [ROOM]: 'storage' } },
    });
    assert.deepStrictEqual(floorPlan.conversionSettings(Object.assign({}, form, { maxThickness: '0.8' }),
        new Set(['wall_faces', 'text'])), { excluded: [WALL_A, WALL_B], walls: { heightMeters: 3,
        maxThicknessMeters: 0.8 } });
    // Doors: those in the outer walls take a height; those in walls take nothing (they open the wall full height).
    assert.deepStrictEqual(floorPlan.conversionSettings(Object.assign({}, form, { doorHeight: '2.1' }),
        new Set(['wall_faces', 'perimeter', 'door'])), { excluded: [WALL_A, WALL_B], walls: { heightMeters: 3 },
        outline: { replace: true, thicknessMeters: 0.3, loop: OUTLINE_B }, doors: { heightMeters: 2.1 } });
    assert.deepStrictEqual(floorPlan.conversionSettings(form, new Set(['perimeter', 'door'])).doors, {});
    assert.ok(!('doors' in floorPlan.conversionSettings(Object.assign({}, form, { doorHeight: '2.1' }),
        new Set(['wall_centerline', 'door']))));
});

check('doors are listed with the wall they open; those in the outer walls wait for their height', async () => {
    const h = converting({ roles: { L1: 'wall_centerline', L2: 'door', L3: 'perimeter' }, answer: doorsAnswer });
    h.controller.open();
    assert.ok(/Outer door height \(m\)/.test(h.panel().text()), h.panel().text());
    fire(button(h, 'find'), 'click');
    await settle();
    let text = h.panel().text();
    assert.ok(/Doors: 1 to add, 1 waiting\./.test(text), text);
    assert.ok(/Drawing door 1: 1 m door in Drawing wall 1/.test(text), text);
    assert.ok(/Drawing door 2: 2 m double door in the outer walls/.test(text), text);
    assert.ok(/waiting: Give the outer doors' height/.test(text), text);
    assert.ok(/1 - A door swing on the outer walls without its door leaf/.test(text), text);
    // The door in the wall left out, and the outer doors' height given: both are sent with the next list.
    const keep = h.panel().querySelector('[data-fp-keep="' + DOOR_A + '"]');
    keep.checked = false;
    fire(keep, 'change');
    field(h, 'outlineHeight').value = '6';
    fire(field(h, 'outlineHeight'), 'input');
    field(h, 'doorHeight').value = '2.1';
    fire(field(h, 'doorHeight'), 'input');
    fire(button(h, 'find'), 'click');
    await settle();
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'convert').at(-1)[2].settings, {
        excluded: [DOOR_A], walls: { thicknessMeters: 0.2 },
        outline: { replace: false, heightMeters: 6, thicknessMeters: 0.3 }, doors: { heightMeters: 2.1 } });
    text = h.panel().text();
    assert.ok(/Doors: 1 left out, 1 to add\./.test(text), text);
    assert.strictEqual(h.panel().querySelector('[data-fp-keep="' + DOOR_A + '"]').checked, false);
    assert.strictEqual(button(h, 'review').disabled, false);
});

check('walls and rooms are found only for layers with a role, a known unit and a saved layout', async () => {
    const none = converting({ roles: {} });
    none.controller.open();
    assert.ok(/choose above what its layers show/.test(none.panel().text()), none.panel().text());
    assert.strictEqual(none.panel().querySelector('[data-fp-action="find"]'), null);
    const dirty = converting({ dirty: true });
    dirty.controller.open();
    assert.ok(/Save the layout first/.test(dirty.panel().text()), dirty.panel().text());
    assert.strictEqual(button(dirty, 'find').disabled, true);
    const unit = converting({ unitOpen: true });
    unit.controller.open();
    assert.ok(/Choose the drawing's unit/.test(unit.panel().text()), unit.panel().text());
    assert.strictEqual(button(unit, 'find').disabled, true);
    await unit.controller.convert('candidates');  // a click that got through anyway
    assert.ok(!unit.calls.some(call => call[0] === 'convert'), 'nothing is sent');
    assert.ok(/Choose the drawing's unit/.test(unit.panel().text()));
    // A draft has no Walls and rooms section: it is not on the plan yet.
    const d = harness();
    await importDrawing(d);
    assert.strictEqual(d.panel().querySelector('[data-fp-convert]'), null);
});

check('the list shows what the drawing converts to; the review is staged with the settings shown', async () => {
    const h = converting();
    h.controller.open();
    let text = h.panel().text();
    assert.ok(/Wall height \(m\)/.test(text) && /Thickest wall drawn as two faces \(m\)/.test(text), text);
    assert.ok(!/Wall thickness for center lines/.test(text) && !/Outer wall height/.test(text), text);
    fire(button(h, 'find'), 'click');
    await settle();
    assert.deepStrictEqual(h.calls.filter(call => call[0] === 'convert')[0], ['convert', RECORD.importId,
        { baseRevision: 'r1', settings: { excluded: [], walls: { maxThicknessMeters: 0.6 } }, stage: 'candidates' }]);
    text = h.panel().text();
    assert.ok(/Walls: 1 not added, 1 waiting\./.test(text), text);
    assert.ok(/Drawing wall 1: 10 m long, 0\.2 m thick/.test(text) && /waiting: Give the wall height/.test(text), text);
    assert.ok(/not added: A wall is already on the plan here\./.test(text), text);
    assert.ok(/Left as drawing:/.test(text) && /3 - A curve: it stays as drawing\./.test(text), text);
    assert.ok(/Nothing new to add\./.test(text), text);
    assert.ok(h.panel().querySelector('[data-fp-keep="' + WALL_A + '"]'), 'a waiting wall can be left out');
    assert.strictEqual(h.panel().querySelector('[data-fp-keep="' + WALL_B + '"]'), null, 'a refused one cannot');
    assert.strictEqual(button(h, 'review').disabled, true, 'nothing to add yet');
    assert.ok(!/Changed since this list was made/.test(text), text);
    // The height typed: the list is now older than the fields (marked in place: the field keeps its focus), and the
    // review, which stages the list on show, waits for the list to be updated.
    const height = field(h, 'wallHeight');
    height.value = '3';
    fire(height, 'input');
    assert.strictEqual(field(h, 'wallHeight'), height, 'the field is not rebuilt while typed in');
    assert.ok(/Changed since this list was made: Update the list/.test(h.panel().text()), h.panel().text());
    assert.strictEqual(button(h, 'review').disabled, true);
    assert.strictEqual(button(h, 'find').textContent, 'Update the list');
    fire(button(h, 'find'), 'click');
    await settle();
    text = h.panel().text();
    assert.ok(/Walls: 1 to add, 1 not added\./.test(text) && !/Changed since/.test(text), text);
    assert.strictEqual(field(h, 'wallHeight').value, '3', 'the field keeps what was typed');
    assert.strictEqual(button(h, 'review').disabled, false);
    // Leaving the wall out marks the list as outdated; putting it back makes it current again.
    const keep = h.panel().querySelector('[data-fp-keep="' + WALL_A + '"]');
    keep.checked = false;
    fire(keep, 'change');
    assert.strictEqual(h.panel().querySelector('[data-fp-keep="' + WALL_A + '"]'), keep, 'the box keeps its focus');
    assert.ok(/Changed since this list was made/.test(h.panel().text()), h.panel().text());
    assert.strictEqual(button(h, 'review').disabled, true);
    h.controller.render();
    const again = h.panel().querySelector('[data-fp-keep="' + WALL_A + '"]');
    assert.strictEqual(again.checked, false, 'the choice is kept through a render');
    assert.ok(/Changed since this list was made/.test(h.panel().text()), h.panel().text());
    again.checked = true;
    fire(again, 'change');
    assert.ok(!/Changed since this list was made/.test(h.panel().text()), h.panel().text());
    assert.strictEqual(button(h, 'review').disabled, false);
    fire(button(h, 'review'), 'click');
    await settle();
    const staged = h.calls.filter(call => call[0] === 'convert').at(-1);
    assert.deepStrictEqual(staged[2], { baseRevision: 'r1', stage: 'proposal',
        settings: { excluded: [], walls: { heightMeters: 3, maxThicknessMeters: 0.6 } } });
    const install = h.calls.filter(call => call[0] === 'install')[0];
    assert.deepStrictEqual(install[1], { siteId: 'site-1', layoutId: 'fl-1', revision: 'r1', proposalId: 'flp-1' });
    assert.deepStrictEqual(Object.keys(install[2]).sort(), ['applyDirectly', 'isCurrent']);
    assert.strictEqual(install[2].applyDirectly, false);
    assert.ok(/on the plan to review\. Approve adds them/.test(h.panel().text()), h.panel().text());
    // Approved: the layout moved on to a new revision; the list belonged to the old one.
    h.save('r2');
    h.controller.sync(h.workspace.state.layout, { preview: false });
    text = h.panel().text();
    assert.ok(/Approved: the walls and rooms from the drawing are in the layout\./.test(text), text);
    assert.strictEqual(button(h, 'find').textContent, 'Find walls and rooms', 'the old list is gone');
    assert.strictEqual(h.panel().querySelector('[data-fp-candidates]'), null);
});

check('a review dismissed leaves the layout as it was, and says so', async () => {
    const h = converting();
    h.controller.open();
    field(h, 'wallHeight').value = '3';
    fire(field(h, 'wallHeight'), 'input');
    fire(button(h, 'find'), 'click');
    await settle();
    fire(button(h, 'review'), 'click');
    await settle();
    assert.ok(/Approve or dismiss it first/.test(h.panel().text()), 'no second conversion under the preview');
    h.controller.sync(h.workspace.state.layout, { preview: false });
    assert.ok(/The review closed without a change: the layout is as it was\./.test(h.panel().text()),
        h.panel().text());
    assert.ok(h.panel().querySelector('[data-fp-candidates]'), 'the list still holds for the same layout');
});

check('among several outlines one is chosen; outer walls are replaced only when asked; rooms get zone types',
    async () => {
        const h = converting({ roles: { L1: 'perimeter', L3: 'room_boundary' }, answer: outlinesAnswer });
        h.controller.open();
        assert.ok(/Outer wall height \(m\)/.test(h.panel().text()) && /Rooms become zones of type/.test(
            h.panel().text()), h.panel().text());
        field(h, 'outlineHeight').value = '6';
        fire(field(h, 'outlineHeight'), 'input');
        fire(button(h, 'find'), 'click');
        await settle();
        assert.strictEqual(h.panel().querySelector('[data-fp-keep="' + OUTLINE_A + '"]'), null);
        const choice = h.panel().querySelector('[data-fp-outline="' + OUTLINE_A + '"]');
        assert.ok(choice && h.panel().querySelector('[data-fp-outline="' + OUTLINE_B + '"]'), h.panel().text());
        assert.ok(/Choose which outline is the building\./.test(h.panel().text()));
        choice.checked = true;
        fire(choice, 'change');
        const zone = field(h, 'zoneType');
        zone.value = 'workcell';
        fire(zone, 'change');
        const own = h.panel().querySelector('[data-fp-room-type="' + ROOM + '"]');
        assert.ok(own, 'a waiting room has its own zone type');
        own.value = 'storage';
        fire(own, 'change');
        fire(button(h, 'find'), 'click');
        await settle();
        assert.deepStrictEqual(h.calls.filter(call => call[0] === 'convert').at(-1)[2].settings, {
            excluded: [], outline: { replace: false, heightMeters: 6, thicknessMeters: 0.3, loop: OUTLINE_A },
            rooms: { zoneType: 'workcell', types: { [ROOM]: 'storage' } } });
        let text = h.panel().text();
        assert.ok(/The plan already has outer walls; choose Replace/.test(text), text);
        assert.strictEqual(h.panel().querySelector('[data-fp-outline="' + OUTLINE_A + '"]').checked, true);
        const replace = field(h, 'replace');
        assert.strictEqual(replace.checked, false);
        replace.checked = true;
        fire(replace, 'change');
        fire(button(h, 'review'), 'click');
        await settle();
        assert.strictEqual(h.calls.filter(call => call[0] === 'convert').at(-1)[2].settings.outline.replace, true);
        assert.strictEqual(h.calls.filter(call => call[0] === 'install').length, 1);
    });

check('an answer from the server is dropped when the panel closed meanwhile; a refusal is shown', async () => {
    let release;
    const h = converting({ convertGate: new Promise(resolve => { release = resolve; }) });
    h.controller.open();
    fire(button(h, 'find'), 'click');
    assert.strictEqual(button(h, 'find').disabled, true, 'busy');
    h.controller.close();
    release();
    await settle();
    h.controller.open();
    assert.strictEqual(h.panel().querySelector('[data-fp-candidates]'), null, 'nothing from before the close');
    const refused = new Error('The layout changed. Convert again from the saved layout.');
    const e = converting({ convertError: refused });
    e.controller.open();
    fire(button(e, 'find'), 'click');
    await settle();
    assert.ok(/The layout changed\. Convert again/.test(e.panel().text()), e.panel().text());
    assert.strictEqual(e.controller.busy, false);
    assert.ok(!e.calls.some(call => call[0] === 'install'));
});

check('closing the panel while its review is fetched stops the install: the session hears it is not current',
    async () => {
        let release;
        const gate = new Promise(resolve => { release = resolve; });
        const h = converting();
        const installed = [];
        h.workspace.session.fetchAndInstallOperationProposal = async (reference, options) => {
            h.calls.push(['install', reference, options]);
            await gate;
            // As the session does once its fetch returns: a caller that is no longer current gets nothing.
            if (options.isCurrent && !options.isCurrent()) {
                throw new Error('The operation preview no longer matches the active editor');
            }
            installed.push(reference.proposalId);
        };
        h.controller.open();
        field(h, 'wallHeight').value = '3';
        fire(field(h, 'wallHeight'), 'input');
        fire(button(h, 'find'), 'click');
        await settle();
        fire(button(h, 'review'), 'click');
        await settle();
        const call = h.calls.find(item => item[0] === 'install');
        assert.ok(call, 'the review was asked for');
        assert.strictEqual(call[2].applyDirectly, false);
        assert.strictEqual(typeof call[2].isCurrent, 'function');
        assert.strictEqual(call[2].isCurrent(), true, 'current while the panel is open');
        h.controller.close();
        assert.strictEqual(call[2].isCurrent(), false, 'closed: no longer current');
        release();
        await settle();
        assert.deepStrictEqual(installed, [], 'nothing installed after the close');
        h.controller.open();
        const text = h.panel().text();
        assert.ok(!/Approve or dismiss it first/.test(text) && !/no longer matches/.test(text), text);
        assert.strictEqual(h.controller.busy, false);
    });

check('a list on show keeps its scroll through a render', async () => {
    const h = converting();
    h.controller.open();
    fire(button(h, 'find'), 'click');
    await settle();
    h.panel().querySelector('[data-fp-candidates]').scrollTop = 120;
    h.panel().scrollTop = 40;
    h.controller.render();
    assert.strictEqual(h.panel().querySelector('[data-fp-candidates]').scrollTop, 120);
    assert.strictEqual(h.panel().scrollTop, 40);
});

Promise.all(pending).then(() => {
    process.stdout.write(`${checks}/${checks} floor plan checks passed\n`);
}).catch(error => {
    console.error(error && error.stack ? error.stack : error);
    process.exitCode = 1;
});
