'use strict';

// The Site tab's globe flight: camera arithmetic, and the turn-dive-hold-settle-fade sequence
// against a fake MapLibre (the real one needs WebGL).
const assert = require('assert');
const path = require('path');
const test = require('node:test');

const globe = require(path.join(__dirname, '..', 'static', 'facility_layout_site_globe.js'));
const site = require(path.join(__dirname, '..', 'static', 'facility_layout_site.js'));

function close(actual, expected, tolerance) {
    assert.ok(Math.abs(actual - expected) <= (tolerance || 1e-9), actual + ' != ' + expected);
}

class FakeElement {
    constructor(tag) {
        this.tagName = tag; this.children = []; this.parentNode = null; this.listeners = {};
        this.className = ''; this.textContent = ''; this.clientWidth = 1200; this.clientHeight = 800;
        const names = new Set();
        this.classList = { add: n => names.add(n), remove: n => names.delete(n), contains: n => names.has(n) };
    }
    appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
    removeChild(child) { this.children = this.children.filter(c => c !== child); child.parentNode = null; return child; }
    addEventListener(type, listener) { this.listeners[type] = listener; }
}

function fakeDocument() {
    return { createElement: tag => new FakeElement(tag), head: new FakeElement('head'),
        defaultView: { matchMedia: () => ({ matches: false }) } };
}

function fakeLibrary(calls, options) {
    class Map {
        constructor(settings) {
            if (options && options.noWebGL) throw new Error('Failed to initialize WebGL');
            calls.push(['create', settings]); this.handlers = {};
            setTimeout(() => this.fire('load'), 0);
        }
        on(type, handler) { calls.push(['on', type]); }
        once(type, handler) { (this.handlers[type] = this.handlers[type] || []).push(handler); }
        fire(type) { const handlers = this.handlers[type] || []; this.handlers[type] = []; handlers.forEach(h => h()); }
        setPadding(padding) { calls.push(['padding', padding]); }
        easeTo(camera) { calls.push(['easeTo', camera]); setTimeout(() => this.fire('moveend'), 0); }
        flyTo(camera) { calls.push(['flyTo', camera]); setTimeout(() => this.fire('moveend'), 0); }
        remove() { calls.push(['remove']); }
    }
    return { Map };
}

const until = async (check, what) => {
    for (let i = 0; i < 200 && !check(); i += 1) await new Promise(resolve => setTimeout(resolve, 5));
    assert.ok(check(), 'timed out waiting for ' + what);
};

function flight(calls, extra) {
    const documentRef = fakeDocument();
    const host = new FakeElement('div');
    const ended = [];
    const result = globe.createFlight(Object.assign({ document: documentRef, host: host,
        tileUrl: '/api/facility-site-globe/site-a/{z}/{x}/{y}.jpg',
        loadLibrary: () => Promise.resolve(fakeLibrary(calls)), onEnd: () => ended.push(true) }, extra));
    return { flight: result, host: host, ended: ended };
}

const target = { latitude: 45.0207, longitude: -92.7756, padLeft: 290, zoom: 17.5, previous: null, ready: null };

test('ground resolution, whole-globe framing and turn length are plain arithmetic', () => {
    close(globe.zoomForMetersPerPixel(40075016.686 / 512, 0), 0);
    close(globe.zoomForMetersPerPixel(40075016.686 * 0.5 / (512 * 1024), 60), 10);
    const zoom = globe.globeZoom(910, 800);
    close(512 * Math.pow(2, zoom) / Math.PI, 0.75 * 800, 1e-6);  // the globe spans 3/4 of the shorter side
    close(globe.arcDegrees({ latitude: 0, longitude: 0 }, { latitude: 0, longitude: 90 }), 90);
    close(globe.arcDegrees({ latitude: 45, longitude: -93 }, { latitude: -45, longitude: 87 }), 180, 1e-6);
    const start = globe.startPoint(target, null);
    assert.strictEqual(start.latitude, 20);
    close(start.longitude, -12.7756, 1e-9);
    assert.deepStrictEqual(globe.startPoint({ latitude: 0, longitude: 150 }, null), { latitude: 20, longitude: -130 });
    assert.deepStrictEqual(globe.startPoint(target, { latitude: 44.9, longitude: -93.2 }), { latitude: 44.9, longitude: -93.2 });
    assert.deepStrictEqual([0, 90, 180, 360].map(globe.spinMilliseconds), [900, 1550, 2200, 2200]);
    const style = globe.globeStyle('/tiles/{z}/{x}/{y}.jpg');
    assert.deepStrictEqual([style.projection.type, style.sources.earth.tiles[0], style.sources.earth.maxzoom,
        style.sources.earth.tileSize], ['globe', '/tiles/{z}/{x}/{y}.jpg', 16, 512]);
});

test('a placement lands on the photo box centre beside the panel, and framing extends past the photo', () => {
    const view = site.viewForBox({ minX: -250, maxX: 250, minZ: -250, maxZ: 250 }, { width: 1200, height: 800 });
    close(view.mpp, 0.65);
    close(view.cx + 290 * view.mpp / 2, 0);  // the target sits in the middle of the area beside the panel
    const image = { corners: [{ x: -200, z: -150 }, { x: 200, z: -150 }, { x: 200, z: 150 }, { x: -200, z: 150 }],
        geoBounds: { south: 44.0, west: -93.2, north: 44.1, east: -93.0 } };
    assert.strictEqual(site.latLonAt(image, -300, 0), null);
    const outside = site.geoPoint(image, -300, 0);
    close(outside.longitude, -93.25, 1e-12);
    close(outside.latitude, 44.05, 1e-12);
});

test('the flight turns, dives, holds until the photo is ready, settles on its framing and fades away', async () => {
    const calls = [];
    const { flight: trip, host, ended } = flight(calls);
    trip.fly(target);
    await until(() => calls.some(c => c[0] === 'flyTo'), 'the dive');
    await new Promise(resolve => setTimeout(resolve, 20));
    const create = calls.find(c => c[0] === 'create')[1];
    assert.strictEqual(create.interactive, false);
    assert.strictEqual(create.style.projection.type, 'globe');
    close(create.center[0], -12.7756, 1e-9);
    assert.strictEqual(create.center[1], 20);
    assert.deepStrictEqual(calls.find(c => c[0] === 'padding')[1], { left: 290, right: 0, top: 0, bottom: 0 });
    const moves = calls.filter(c => c[0] === 'easeTo' || c[0] === 'flyTo');
    assert.deepStrictEqual(moves.map(c => c[0]), ['easeTo', 'flyTo']);
    assert.deepStrictEqual(moves[0][1].center, [-92.7756, 45.0207]);
    close(moves[1][1].zoom, 17.15);
    assert.strictEqual(moves[1][1].duration, 5000);
    // Nothing more happens while the photo is still loading: the globe holds over the place.
    assert.strictEqual(host.children.length, 1);
    assert.ok(!calls.some(c => c[0] === 'remove'));
    const landing = trip.land({ latitude: 45.0208, longitude: -92.7757, metersPerPixel: 0.65 });
    await until(() => host.children.length === 1 && host.children[0].classList.contains('ip-flw-site-globe-leaving'), 'the fade');
    const settle = calls.filter(c => c[0] === 'easeTo')[1][1];
    assert.deepStrictEqual(settle.center, [-92.7757, 45.0208]);
    close(settle.zoom, globe.zoomForMetersPerPixel(0.65, 45.0208));
    await landing;
    assert.deepStrictEqual([host.children.length, ended.length, calls.filter(c => c[0] === 'remove').length], [0, 1, 1]);
});

test('the globe hovers over the place until the server has the tiles, then dives', async () => {
    const calls = [];
    const { flight: trip } = flight(calls);
    let tilesReady;
    trip.fly(Object.assign({}, target, { ready: new Promise(resolve => { tilesReady = resolve; }) }));
    await until(() => calls.filter(c => c[0] === 'easeTo').length === 1, 'the turn');
    await new Promise(resolve => setTimeout(resolve, 40));
    assert.ok(!calls.some(c => c[0] === 'flyTo'), 'no dive before the tiles are ready');
    tilesReady({ tiles: 140, ready: 140 });
    await until(() => calls.some(c => c[0] === 'flyTo'), 'the dive');
    assert.strictEqual(calls.find(c => c[0] === 'create')[1].cancelPendingTileRequestsWhileZooming, false);
    trip.cancel();
});

test('a photo that arrives early waits for the dive to finish before the fade', async () => {
    const calls = [];
    const { flight: trip, host } = flight(calls);
    trip.fly(target);
    const landing = trip.land({ latitude: 45.0207, longitude: -92.7756, metersPerPixel: 0.65 });
    await landing;
    assert.deepStrictEqual(calls.filter(c => c[0] === 'easeTo' || c[0] === 'flyTo').map(c => c[0]), ['easeTo', 'flyTo', 'easeTo']);
    assert.strictEqual(host.children.length, 0);
});

test('skip, a failed photo, a missing library or no WebGL end the flight without waiting', async () => {
    let calls = [];
    let trip = flight(calls);
    trip.flight.fly(target);
    await until(() => calls.some(c => c[0] === 'create'), 'the globe');
    trip.flight.cancel();
    assert.deepStrictEqual([trip.host.children.length, trip.ended.length], [0, 1]);
    await trip.flight.land({ latitude: 45, longitude: -93, metersPerPixel: 1 });  // never waits on a skipped flight
    trip.flight.cancel();
    assert.strictEqual(trip.ended.length, 1);

    calls = [];
    trip = flight(calls);
    trip.flight.fly(target);
    await trip.flight.land(null);  // the photo failed: fade straight out
    assert.deepStrictEqual([trip.host.children.length, trip.ended.length], [0, 1]);

    for (const extra of [{ loadLibrary: () => Promise.reject(new Error('offline')) },
        { loadLibrary: () => Promise.resolve(fakeLibrary([], { noWebGL: true })) }]) {
        trip = flight([], extra);
        await trip.flight.fly(target);
        assert.deepStrictEqual([trip.host.children.length, trip.ended.length], [0, 1]);
    }
});

test('reduced motion turns the flight off', () => {
    const documentRef = fakeDocument();
    assert.strictEqual(globe.wanted(documentRef), true);
    documentRef.defaultView.matchMedia = query => ({ matches: query === '(prefers-reduced-motion: reduce)' });
    assert.strictEqual(globe.wanted(documentRef), false);
});
