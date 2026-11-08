'use strict';

// Placing the footprint by hand on the Site tab, PowerPoint-style: click to select, drag to move, turn by the
// round handle. It never resizes, the map stays still while it moves, and the typed fields keep working.
const assert = require('node:assert/strict');
const test = require('node:test');
const Site = require('../static/facility_layout_site.js');

const DEGREE = String.fromCharCode(176);
const WIDTH = 900;
const HEIGHT = 600;

class Element {
    constructor(tag) {
        this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {}; this.style = {};
        this.clientWidth = WIDTH; this.clientHeight = HEIGHT;
        const classes = this.classes = new Set();
        this.classList = {
            toggle(name, on) { if (on === undefined ? !classes.has(name) : on) classes.add(name); else classes.delete(name); },
            add(name) { classes.add(name); },
            remove(name) { classes.delete(name); },
            contains(name) { return classes.has(name); },
        };
    }
    set textContent(value) { this.text = value; this.children = []; }
    get textContent() { return this.text || ''; }
    setAttribute(key, value) { this.attrs[key] = String(value); }
    getAttribute(key) { return Object.prototype.hasOwnProperty.call(this.attrs, key) ? this.attrs[key] : null; }
    appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
    removeChild(child) { this.children = this.children.filter(item => item !== child); }
    addEventListener(key, fn) { (this.listeners[key] ||= []).push(fn); }
    emit(key, event = {}) { return Promise.all((this.listeners[key] || []).map(fn => fn(event))); }
    contains(child) { return this === child || this.children.some(item => item.contains(child)); }
    focus() {}
    getBoundingClientRect() { return { left: 0, top: 0, width: this.clientWidth, height: this.clientHeight }; }
}

function all(element, predicate, found = []) {
    if (predicate(element)) found.push(element);
    element.children.forEach(child => all(child, predicate, found));
    return found;
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const close = (actual, expected, tolerance = 0.002) =>
    assert.ok(Math.abs(actual - expected) <= tolerance, actual + ' != ' + expected);

const PLAN = { widthMeters: 48, depthMeters: 32 };
const SAVED_POSE = { x: -24, z: -16, bearingDegrees: 0 };  // centred on the site origin

function harness(settings) {
    const saved = [];
    let layout = { layoutId: 'layout-a', extensions: { facilityPlan: PLAN, facilitySiteContext: {
        version: 1, georeference: { originLatitude: 45, originLongitude: -93, label: 'Test lot' },
        buildingPose: SAVED_POSE, imagery: [] } } };
    const h = { saved };
    // Like the session: a saved pose comes back as a new layout.
    const session = {
        setSiteContext: async () => {},
        setBuildingPose: async pose => {
            saved.push(pose);
            layout = { ...layout, extensions: { ...layout.extensions, facilitySiteContext: {
                ...layout.extensions.facilitySiteContext, buildingPose: { ...pose } } } };
            h.view.render(layout, settings);
        },
    };
    h.view = Site.create({ document: { createElement: tag => new Element(tag),
        createElementNS: (_, tag) => new Element(tag) }, session });
    h.view.render(layout, settings); h.view.show();
    const element = h.view.element;
    const svg = all(element, item => item.tagName === 'svg')[0];
    Object.assign(h, {
        svg,
        find: predicate => all(element, predicate),
        byClass: name => all(element, item => String(item.attrs.class || '').split(' ').includes(name)),
        button: label => all(element, item => item.tagName === 'button' && item.text === label)[0],
        input: label => all(element, item => item.tagName === 'input' && item.attrs['aria-label'] === label)[0],
        building: () => h.byClass('ip-flw-site-building')[0],
        knob: () => all(element, item => item.attrs['data-site-pose'] === 'rotate')[0],
        selected: () => h.byClass('ip-flw-site-selection').length === 1,
        viewBox: () => svg.attrs.viewBox,
        // Screen position of a property point (+X east, +Z north), from the drawn view box.
        screen(x, z) {
            const [minX, minY, width] = svg.attrs.viewBox.split(' ').map(Number);
            const mpp = width / WIDTH;
            return { clientX: (x - minX) / mpp, clientY: (-z - minY) / mpp };
        },
        mpp: () => Number(svg.attrs.viewBox.split(' ')[2]) / WIDTH,
        outline() {
            return h.building().attrs.points.trim().split(/\s+/).map(pair => pair.split(',').map(Number))
                .map(([x, y]) => ({ x, z: -y }));
        },
        center() {
            const points = h.outline();
            return { x: (points[0].x + points[2].x) / 2, z: (points[0].z + points[2].z) / 2 };
        },
        async press(target, at, extra) {
            await svg.emit('pointerdown', { button: 0, pointerId: 1, target, ...at, ...(extra || {}) });
        },
        async move(at, extra) { await svg.emit('pointermove', { pointerId: 1, target: svg, ...at, ...(extra || {}) }); },
        async release(at) { await svg.emit('pointerup', { pointerId: 1, target: svg, ...at }); await settle(); await settle(); },
        async click(target, at) { await h.press(target, at); await h.release(at); },
        async clickBuilding() { const at = h.screen(h.center().x, h.center().z); await h.click(h.building(), at); },
        async clickEmptyMap() { const at = h.screen(55, 45); await h.click(svg, at); },
        escape: () => element.emit('keydown', { key: 'Escape', target: element }),
    });
    return h;
}

function sides(points) {
    return points.map((p, i) => Math.hypot(points[(i + 1) % 4].x - p.x, points[(i + 1) % 4].z - p.z));
}

test('a click selects the footprint: an outline and a rotation handle, no resize handles, and its typed fields', async () => {
    const h = harness();
    assert.equal(h.selected(), false);
    assert.ok(h.button('Site'), 'a placed site starts with its pane folded');
    assert.match(h.building().attrs.class, /ip-flw-site-building-editable/);
    await h.clickBuilding();
    assert.equal(h.selected(), true);
    assert.match(h.building().attrs.class, /ip-flw-site-building-selected/);
    assert.ok(h.knob(), 'a rotation handle');
    assert.equal(h.byClass('ip-flw-site-rotate-glyph').length, 1);
    // Only the footprint itself and the turn handle respond: no corner, edge or centre handles.
    assert.deepEqual(h.find(item => item.attrs['data-site-pose'] !== undefined).map(item => item.attrs['data-site-pose']),
        ['move', 'rotate']);
    assert.equal(h.byClass('ip-flw-site-handle').length, 0);
    // The handle sits above the far (north) edge, beyond the outline, on the centre line.
    const knob = { x: Number(h.knob().attrs.cx), z: -Number(h.knob().attrs.cy) };
    close(knob.x, 0); assert.ok(knob.z > 16);
    // The Building settings open on their own, with the saved values.
    assert.ok(h.button('Hide'), 'the pane opened');
    assert.equal(h.button('Building').attrs['aria-pressed'], 'true');
    assert.equal(h.input('Building X (m)').value, '-24');
    assert.equal(h.input('True bearing (degrees)').value, '0');
    assert.equal(h.saved.length, 0, 'selecting saves nothing');
});

test('a click on empty map or Esc deselects and folds the pane back as it was', async () => {
    const h = harness();
    await h.clickBuilding();
    await h.clickEmptyMap();
    assert.equal(h.selected(), false);
    assert.equal(h.knob(), undefined);
    assert.ok(h.button('Site') && !h.button('Hide'), 'folded again');
    await h.clickBuilding();
    assert.equal(h.selected(), true);
    await h.escape();
    assert.equal(h.selected(), false);
    assert.ok(h.button('Site'));
    // From an open pane in another section, deselecting goes back to that section.
    await h.button('Site').emit('click');
    await h.button('Layers').emit('click');
    await h.clickBuilding();
    assert.equal(h.button('Building').attrs['aria-pressed'], 'true');
    await h.clickEmptyMap();
    assert.equal(h.button('Layers').attrs['aria-pressed'], 'true');
    assert.equal(h.saved.length, 0);
});

test('dragging the footprint before it is selected still pans the map and changes nothing', async () => {
    const h = harness();
    const before = h.viewBox(), outline = JSON.stringify(h.outline());
    const at = h.screen(0, 0);
    await h.press(h.building(), at);
    await h.move({ clientX: at.clientX + 80, clientY: at.clientY + 20 });
    await h.release({ clientX: at.clientX + 80, clientY: at.clientY + 20 });
    assert.notEqual(h.viewBox(), before, 'the map panned');
    assert.equal(JSON.stringify(h.outline()), outline);
    assert.equal(h.selected(), false, 'a drag is not a click');
    assert.equal(h.saved.length, 0);
});

test('the selected footprint drags as one rigid piece while the map stays still, and saves once on release', async () => {
    const h = harness();
    await h.clickBuilding();
    const box = h.viewBox(), mpp = h.mpp();
    const at = h.screen(5, -3);  // grabbed off-centre
    await h.press(h.building(), at);
    await h.move({ clientX: at.clientX + 30, clientY: at.clientY - 10 });
    await h.move({ clientX: at.clientX + 60, clientY: at.clientY - 30 });
    // Live: the outline and the typed fields follow, nothing is saved yet, the map has not moved.
    close(h.outline()[0].x, -24 + 60 * mpp);
    close(h.outline()[0].z, -16 + 30 * mpp);
    close(Number(h.input('Building X (m)').value), -24 + 60 * mpp);
    close(Number(h.input('Building Z (m)').value), -16 + 30 * mpp);
    assert.equal(h.saved.length, 0);
    assert.equal(h.viewBox(), box);
    await h.release({ clientX: at.clientX + 60, clientY: at.clientY - 30 });
    assert.equal(h.saved.length, 1, 'one undoable edit');
    close(h.saved[0].x, -24 + 60 * mpp);
    close(h.saved[0].z, -16 + 30 * mpp);
    assert.equal(h.saved[0].bearingDegrees, 0);
    assert.equal(h.viewBox(), box, 'the map never moved');
    sides(h.outline()).forEach((length, i) => close(length, i % 2 ? 32 : 48, 1e-6));
    assert.equal(h.selected(), true, 'still selected after the move');
});

test('the round handle turns the footprint about its centre, shows the angle, and Shift snaps to 15 degrees', async () => {
    const h = harness();
    await h.clickBuilding();
    const box = h.viewBox();
    const knob = { x: Number(h.knob().attrs.cx), z: -Number(h.knob().attrs.cy) };
    const reach = Math.hypot(knob.x, knob.z);
    const aim = degrees => h.screen(reach * Math.sin(degrees * Math.PI / 180), reach * Math.cos(degrees * Math.PI / 180));
    await h.press(h.knob(), h.screen(knob.x, knob.z));
    await h.move(aim(20));
    await h.move(aim(45));
    const label = h.byClass('ip-flw-site-angle');
    assert.equal(label.length, 1);
    assert.equal(label[0].text, '45.0' + DEGREE);
    assert.equal(h.input('True bearing (degrees)').value, '45');
    assert.equal(h.viewBox(), box, 'turning never pans');
    await h.release(aim(45));
    assert.equal(h.byClass('ip-flw-site-angle').length, 0, 'the angle shows only while turning');
    assert.equal(h.saved.length, 1);
    assert.equal(h.saved[0].bearingDegrees, 45);
    const centre = Site.buildingToProperty(h.saved[0], 24, 16);
    close(centre.x, 0); close(centre.z, 0);
    sides(h.outline()).forEach((length, i) => close(length, i % 2 ? 32 : 48, 1e-6));
    // Shift: 15 degree steps. 45 + 55 = 100 degrees snaps to 105.
    const turned = { x: Number(h.knob().attrs.cx), z: -Number(h.knob().attrs.cy) };
    await h.press(h.knob(), h.screen(turned.x, turned.z));
    await h.move(aim(100), { shiftKey: true });
    assert.equal(h.byClass('ip-flw-site-angle')[0].text, '105.0' + DEGREE);
    await h.release(aim(100));
    assert.equal(h.saved[1].bearingDegrees, 105);
    const after = Site.buildingToProperty(h.saved[1], 24, 16);
    close(after.x, 0); close(after.z, 0);
});

test('Esc during a drag puts the footprint back and saves nothing; a click on it never nudges it', async () => {
    const h = harness();
    await h.clickBuilding();
    const outline = JSON.stringify(h.outline());
    const at = h.screen(0, 0);
    await h.press(h.building(), at);
    await h.move({ clientX: at.clientX + 40, clientY: at.clientY });
    assert.notEqual(JSON.stringify(h.outline()), outline);
    await h.escape();
    assert.equal(JSON.stringify(h.outline()), outline);
    assert.equal(h.input('Building X (m)').value, '-24');
    await h.release({ clientX: at.clientX + 40, clientY: at.clientY });
    assert.equal(h.saved.length, 0);
    assert.equal(h.selected(), true);
    // A press and release within the 3 px threshold: no change, no save, still selected.
    await h.press(h.building(), at);
    await h.move({ clientX: at.clientX + 2, clientY: at.clientY });
    await h.release({ clientX: at.clientX + 2, clientY: at.clientY });
    assert.equal(JSON.stringify(h.outline()), outline);
    assert.equal(h.saved.length, 0);
    assert.equal(h.selected(), true);
});

test('the typed X, Z and bearing still apply, and unapplied typing keeps the pane open on deselect', async () => {
    const h = harness();
    await h.button('Site').emit('click');
    await h.button('Building').emit('click');
    assert.equal(h.selected(), true, 'opening the Building settings selects the footprint');
    const field = h.input('Building X (m)');
    field.value = '5'; await field.emit('input');
    await h.button('Apply building position').emit('click'); await settle();
    assert.equal(h.saved.length, 1);
    assert.deepEqual(h.saved[0], { x: 5, z: -16, bearingDegrees: 0 });
    // Selected from the map, then typed but not applied: deselecting keeps the Building settings on show.
    const g = harness();
    await g.clickBuilding();
    const typed = g.input('Building Z (m)');
    typed.value = '7'; await typed.emit('input');
    await g.clickEmptyMap();
    assert.equal(g.selected(), false);
    assert.equal(g.input('Building Z (m)').value, '7');
    assert.ok(g.button('Hide'), 'the pane stays open');
});

test('the pane choice made while selected wins over the restore', async () => {
    const h = harness();
    await h.button('Site').emit('click');  // open
    await h.clickBuilding();
    await h.button('Hide').emit('click');
    assert.equal(h.selected(), true, 'hiding the pane keeps the selection');
    assert.ok(h.knob());
    await h.clickEmptyMap();
    assert.equal(h.selected(), false);
    assert.ok(h.button('Site') && !h.button('Hide'), 'stays folded, as last chosen');
});

test('measuring and read-only proposals never select or move the footprint', async () => {
    const h = harness();
    await h.button('Measure').emit('click');
    await h.clickBuilding();
    assert.equal(h.selected(), false);
    assert.equal(h.byClass('ip-flw-site-measure-point').length, 1, 'the click measured instead');
    assert.doesNotMatch(h.building().attrs.class, /editable/);
    // Selected, then Measure: measuring deselects.
    await h.escape();
    await h.clickBuilding();
    assert.equal(h.selected(), true);
    await h.button('Measure').emit('click');
    assert.equal(h.selected(), false);
    const r = harness({ readOnly: true });
    await r.clickBuilding();
    assert.equal(r.selected(), false);
    assert.doesNotMatch(r.building().attrs.class, /editable/);
    assert.equal(r.saved.length, 0);
});

test('pose helpers: a move keeps the bearing and the server limit, a turn keeps the centre', () => {
    assert.deepEqual(Site.movedPose({ x: 1, z: 2, bearingDegrees: 30 }, 0.12345, -0.5), { x: 1.123, z: 1.5, bearingDegrees: 30 });
    assert.deepEqual(Site.movedPose({ x: 4990, z: -4990, bearingDegrees: 0 }, 50, -50), { x: 5000, z: -5000, bearingDegrees: 0 });
    const size = { width: 48, depth: 32 };
    const pose = { x: 10, z: 20, bearingDegrees: 350 };
    const centre = Site.buildingToProperty(pose, 24, 16);
    const from = { x: centre.x, z: centre.z + 40 };
    const to = { x: centre.x + 40, z: centre.z };  // a quarter turn clockwise
    const turned = Site.turnedPose(pose, size, from, to, false);
    assert.equal(turned.bearingDegrees, 80);
    const kept = Site.buildingToProperty(turned, 24, 16);
    close(kept.x, centre.x); close(kept.z, centre.z);
    assert.equal(Site.turnedPose(pose, size, from, { x: centre.x + 40, z: centre.z + 5 }, true).bearingDegrees, 75);
    assert.equal(Site.formatBearing(37.46), '37.5' + DEGREE);
});
