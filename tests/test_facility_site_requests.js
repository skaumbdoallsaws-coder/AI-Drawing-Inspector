'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const Site = require('../static/facility_layout_site.js');
const Transport = require('../static/facility_layout_transport.js');

class Element {
    constructor(tag) {
        this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {};
        this.style = {}; this.clientWidth = 900; this.clientHeight = 600;
        this.classList = { toggle() {} };
    }
    set textContent(value) { this.text = value; this.children = []; }
    get textContent() { return this.text || ''; }
    setAttribute(key, value) { this.attrs[key] = value; }
    appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
    removeChild(child) { this.children = this.children.filter(item => item !== child); }
    addEventListener(key, fn) { (this.listeners[key] ||= []).push(fn); }
    emit(key, event = {}) { return Promise.all((this.listeners[key] || []).map(fn => fn(event))); }
    contains(child) { return this === child || this.children.some(item => item.contains(child)); }
}
function find(element, predicate) {
    if (predicate(element)) return element;
    for (const child of element.children) { const found = find(child, predicate); if (found) return found; }
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const match = { latitude: 45, longitude: -93, label: 'New place' };
const photo = { imageId: 'b'.repeat(64), imagePath: '/new.jpg', source: 'usgs_naip',
    geoBounds: { south: 44.9, west: -93.1, north: 45.1, east: -92.9 }, widthPixels: 500, heightPixels: 500 };
function harness(overrides = {}) {
    const calls = [];
    const layout = { layoutId: 'layout-a', extensions: { facilitySiteContext: {
        version: 1, georeference: { originLatitude: 44, originLongitude: -92, label: 'Old place' },
        buildingPose: { x: -20, z: -15, bearingDegrees: 0 }, imagery: [],
    } } };
    const session = Object.assign({
        geocodeAddress: async () => ({ matches: [match] }),
        fetchSiteImagery: async () => photo,
        setSiteContext: async value => { calls.push(value); },
    }, overrides);
    const view = Site.create({ document: { createElement: tag => new Element(tag),
        createElementNS: (_, tag) => new Element(tag) }, session });
    view.render(layout); view.show();
    const button = label => find(view.element, item => item.tagName === 'button' && item.text === label);
    const input = label => find(view.element, item => item.attrs['aria-label'] === label);
    button('Site').emit('click');  // a placed site's pane starts folded away
    button('Change location').emit('click');
    input('Street address').value = 'New address';
    input('Street address').emit('input');
    return { view, calls, layout, button, input };
}
test('the settings pane folds away once a site is placed and opens and closes on request', async () => {
    const h = harness();  // opened with 'Site', then 'Change location'
    assert.ok(h.input('Street address'));
    await h.button('Find').emit('click'); await settle();
    assert.equal(h.calls.length, 1);
    assert.equal(h.button('Change location'), undefined);  // placed: folded to its Site button
    await h.button('Site').emit('click');
    assert.ok(h.button('Change location') && h.button('Hide'));
    await h.button('Hide').emit('click');
    assert.equal(h.button('Change location'), undefined);
    assert.ok(h.button('Site'));
});
test('Find places a single match and Enter follows the same path', async () => {
    for (const enter of [false, true]) {
        const h = harness();
        if (enter) await h.input('Street address').emit('keydown', { key: 'Enter' });
        else await h.button('Find').emit('click');
        await settle();
        assert.equal(h.calls.length, 1);
        assert.equal(h.calls[0].georeference.label, 'New place');
        assert.equal(h.calls[0].imagery[0].imageId, photo.imageId);
    }
});
test('multiple matches require selection; no matches preserve the old site', async () => {
    const h = harness({ geocodeAddress: async () => ({ matches: [match, { ...match, label: 'Another' }] }) });
    await h.button('Find').emit('click'); await settle();
    assert.equal(h.calls.length, 0);
    await h.button('Another').emit('click'); await settle();
    assert.equal(h.calls[0].georeference.label, 'Another');
    const empty = harness({ geocodeAddress: async () => ({ matches: [] }) });
    await empty.button('Find').emit('click'); await settle();
    assert.equal(empty.calls.length, 0);
});
test('failed imagery preserves the old context and reports the error over the map', async () => {
    const h = harness({ fetchSiteImagery: async () => { throw new Error('Imagery unavailable'); } });
    await h.button('Find').emit('click'); await settle();
    assert.equal(h.calls.length, 0);
    const status = find(h.view.element, item => item.className === 'ip-flw-site-progress');
    assert.equal(status.hidden, false); assert.equal(status.textContent, 'Imagery unavailable');
    assert.equal(h.layout.extensions.facilitySiteContext.georeference.label, 'Old place');
});
test('pending imagery is visible and repeated Enter does not start a second request', async () => {
    let resolvePhoto, fetches = 0;
    const h = harness({ fetchSiteImagery: () => { fetches++; return new Promise(resolve => { resolvePhoto = resolve; }); } });
    await h.button('Find').emit('click'); await settle();
    const status = find(h.view.element, item => item.className === 'ip-flw-site-progress');
    assert.equal(status.textContent, 'Fetching the aerial photo...');
    await h.input('Street address').emit('keydown', { key: 'Enter' });
    assert.equal(fetches, 1); assert.equal(h.calls.length, 0);
    resolvePhoto(photo); await settle(); assert.equal(h.calls.length, 1);
});
test('late imagery cannot write after a layout switch or view destruction', async () => {
    for (const destroy of [false, true]) {
        let resolvePhoto;
        const h = harness({ fetchSiteImagery: () => new Promise(resolve => { resolvePhoto = resolve; }) });
        await h.button('Find').emit('click'); await settle();
        if (destroy) h.view.destroy();
        else h.view.render({ ...h.layout, layoutId: 'layout-b' });
        resolvePhoto(photo); await settle(); assert.equal(h.calls.length, 0);
    }
});
test('site requests have a deadline and forward caller cancellation', async t => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const transport = Transport.createHttpTransport({ siteId: 'site-a', layoutId: 'layout-a',
        fetch: (_, init) => new Promise((resolve, reject) => {
            const abort = () => reject(new Error('Aborted'));
            if (init.signal.aborted) abort(); else init.signal.addEventListener('abort', abort, { once: true });
        }) });
    const timed = transport.fetchSiteImagery({ latitude: 45, longitude: -93, halfSizeMeters: 250 });
    const check = assert.rejects(timed, /took too long.*unchanged/);
    t.mock.timers.tick(180001); await check;
    const controller = new AbortController();
    const cancelled = transport.geocodeAddress('Test address', { signal: controller.signal });
    const cancelledCheck = assert.rejects(cancelled, /Aborted/);
    controller.abort(); await cancelledCheck;
});
test('a site proposal inspects candidate geometry, disables edits and cancels old image work', async () => {
    let resolvePhoto, analyzed;
    const h=harness({fetchSiteImagery:()=>new Promise(resolve=>{resolvePhoto=resolve;}),
        analyzeSiteContext:async (options,layout)=>{analyzed=layout;return {metrics:null,findings:[]};}});
    await h.button('Find').emit('click');await settle();
    const candidate=JSON.parse(JSON.stringify(h.layout));
    candidate.extensions.facilitySiteContext.buildingPose.x=25;
    h.view.render(candidate,{readOnly:true});await settle();
    assert.equal(analyzed.extensions.facilitySiteContext.buildingPose.x,25);
    assert.ok(find(h.view.element,e=>e.text==='Site proposal'));
    assert.equal(h.button('Change location'),undefined);
    resolvePhoto(photo);await settle();assert.equal(h.calls.length,0);
    h.view.render(h.layout);await settle();assert.ok(h.button('Change location'));
    h.view.destroy();
});
test('the chosen photo source reaches the server, and the standard photo sends none', async () => {
    const bodies = [];
    const transport = Transport.createHttpTransport({ siteId: 'site-a', layoutId: 'layout-a',
        fetch: async (_, init) => { bodies.push(JSON.parse(init.body)); return { ok: true, status: 200,
            headers: { get: () => 'application/json' }, json: async () => photo, text: async () => JSON.stringify(photo) }; } });
    await transport.fetchSiteImagery({ latitude: 45, longitude: -93, halfSizeMeters: 150, source: 'mngeo_metro' });
    await transport.fetchSiteImagery({ latitude: 45, longitude: -93, halfSizeMeters: 150 });
    assert.equal(bodies[0].source, 'mngeo_metro');
    assert.equal('source' in bodies[1], false);
});
test('parcel, layer and check requests carry exactly what the server needs', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({ siteId: 'site-a', layoutId: 'layout-a',
        fetch: async (url, init) => { calls.push([url, JSON.parse(init.body)]); return { ok: true, status: 200,
            headers: { get: () => 'application/json' }, json: async () => ({}), text: async () => '{}' }; } });
    const box = { south: 45.01, west: -92.79, north: 45.03, east: -92.77 };
    await transport.fetchSiteParcel({ latitude: 45.02, longitude: -92.776, originLatitude: 45.021, originLongitude: -92.7776 });
    await transport.fetchSiteOverlay({ layer: 'flood', geoBounds: box, widthPixels: 1000, heightPixels: 1000 });
    await transport.checkSiteLayers({ layout: { layoutId: 'layout-a' } });
    assert.match(calls[0][0], /\/site-parcel$/);
    assert.deepEqual(calls[0][1], { latitude: 45.02, longitude: -92.776, originLatitude: 45.021, originLongitude: -92.7776 });
    assert.match(calls[1][0], /\/site-overlay$/);
    assert.deepEqual(calls[1][1], { layer: 'flood', geoBounds: box, widthPixels: 1000, heightPixels: 1000 });
    assert.match(calls[2][0], /\/site-layer-checks$/);
    assert.deepEqual(calls[2][1], { layout: { layoutId: 'layout-a' } });
    await transport.fetchSiteRoads({ geoBounds: box });
    assert.match(calls[3][0], /\/site-roads$/);
    assert.deepEqual(calls[3][1], { geoBounds: box });
    calls.splice(3, 1);
    await transport.prefetchSiteGlobe({ latitude: 45.02, longitude: -92.776 });
    assert.match(calls[3][0], /\/api\/facility-site-globe\/site-a\/prefetch$/);
    assert.deepEqual(calls[3][1], { latitude: 45.02, longitude: -92.776 });
});
test('a placement asks for the globe tiles, and a globe that cannot start never blocks the photo', async () => {
    const prefetched = [];
    const h = harness({ prefetchSiteGlobe: async value => { prefetched.push(value); return { tiles: 140 }; } });
    h.layout.association = { siteId: 'site-a' };
    const flying = [];
    h.view.element.classList = { toggle() {}, add: name => flying.push(name), remove() {} };
    h.view.render(JSON.parse(JSON.stringify(h.layout)));
    await h.button('Find').emit('click');
    for (let i = 0; i < 20 && !h.calls.length; i += 1) await new Promise(resolve => setTimeout(resolve, 5));
    assert.deepEqual(prefetched, [{ latitude: 45, longitude: -93 }]);
    assert.deepEqual(flying, ['ip-flw-site-flying']);
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].imagery[0].imageId, photo.imageId);
    // No WebGL library in this test: the flight ended and took its overlay with it.
    for (let i = 0; i < 20 && find(h.view.element, e => e.className === 'ip-flw-site-globe'); i += 1) {
        await new Promise(resolve => setTimeout(resolve, 5));
    }
    assert.equal(find(h.view.element, e => e.className === 'ip-flw-site-globe'), undefined);
});
test('a placement brings the roads in the same edit, and a road failure never stops the photo', async () => {
    const roads = { source: 'census_tiger', fetched: '2026-10-23', geoBounds: photo.geoBounds, items: [] };
    const asked = [];
    const h = harness({ fetchSiteRoads: async (value) => { asked.push(value); return roads; } });
    await h.button('Find').emit('click'); await settle(); await settle();
    assert.deepEqual(asked, [{ geoBounds: photo.geoBounds }]);
    assert.equal(h.calls.length, 1);
    assert.deepEqual(h.calls[0].roads, roads);
    const failing = harness({ fetchSiteRoads: async () => { throw new Error('Census map down'); } });
    await failing.button('Find').emit('click'); await settle(); await settle();
    assert.equal(failing.calls.length, 1);
    assert.equal('roads' in failing.calls[0], false);
    assert.equal(failing.calls[0].imagery[0].imageId, photo.imageId);
});
test('trace requests send the draft with a point or a box', async () => {
    const calls = [];
    const transport = Transport.createHttpTransport({ siteId: 'site-a', layoutId: 'layout-a',
        fetch: async (url, init) => { calls.push([url, JSON.parse(init.body)]); return { ok: true, status: 200,
            headers: { get: () => 'application/json' }, json: async () => ({}), text: async () => '{}' }; } });
    await transport.traceSitePhoto({ layout: { layoutId: 'layout-a' }, x: 1.5, z: -2 });
    await transport.traceSitePhoto({ layout: { layoutId: 'layout-a' }, box: { minX: -70, maxX: 25, minZ: -30, maxZ: 35 } });
    assert.match(calls[0][0], /\/site-trace$/);
    assert.deepEqual(calls[0][1], { layout: { layoutId: 'layout-a' }, x: 1.5, z: -2 });
    assert.deepEqual(calls[1][1], { layout: { layoutId: 'layout-a' }, box: { minX: -70, maxX: 25, minZ: -30, maxZ: 35 } });
});
test('clicking the photo in trace mode makes an existing-pavement area to check and apply', async () => {
    const traced = { outline: [{ x: -60, z: -30 }, { x: 20, z: -30 }, { x: 20, z: 30 }, { x: -60, z: 30 }],
        areaAcres: 1.19, areaSquareMeters: 4800, lengthMeters: 80, widthMeters: 60, longAxisBearingDegrees: 90,
        perimeterMeters: 280, accuracyMeters: 1.5, touchesPhotoEdge: false,
        photo: { source: 'usgs_naip', captured: '2021-06-18' } };
    const asked = [];
    const session = { traceSitePhoto: async request => { asked.push(request); return traced; },
        setSiteContext: async () => {}, upsertSiteArea: async () => {} };
    const image = Object.assign({}, photo, { corners: [{ x: -100, z: -100 }, { x: 100, z: -100 }, { x: 100, z: 100 },
        { x: -100, z: 100 }] });
    const layout = { layoutId: 'layout-a', association: { siteId: 'site-a' }, extensions: { facilitySiteContext: {
        version: 1, georeference: { originLatitude: 45, originLongitude: -93 },
        buildingPose: { x: -20, z: -15, bearingDegrees: 0 }, imagery: [image] } } };
    const view = Site.create({ document: { createElement: tag => new Element(tag),
        createElementNS: (_, tag) => new Element(tag) }, session });
    view.element.getBoundingClientRect = () => ({ left: 0, top: 0 });
    view.element.classList = { toggle() {}, add() {}, remove() {} };
    view.render(layout); view.show();
    const button = label => find(view.element, item => item.tagName === 'button' && item.text === label);
    await button('Site').emit('click');  // a placed site's pane starts folded away
    await button('Areas').emit('click');
    await button('Trace pavement on the photo').emit('click');
    const svg = find(view.element, item => item.tagName === 'svg');
    await svg.emit('pointerdown', { button: 0, clientX: 450, clientY: 300, pointerId: 1, target: svg });
    await svg.emit('pointerup', { clientX: 450, clientY: 300, pointerId: 1, target: svg });
    await settle(); await settle();
    assert.equal(asked.length, 1);
    assert.ok(Number.isFinite(asked[0].x) && Number.isFinite(asked[0].z) && !asked[0].box);
    const kind = find(view.element, item => item.attrs['aria-label'] === 'Area kind');
    const vertices = find(view.element, item => item.attrs['aria-label'] === 'Area vertices X, Z (m)');
    assert.equal(kind.value, 'existing_pavement');
    assert.equal(vertices.value.split('\n').length, 4);
    assert.ok(find(view.element, item => /^Traced 1\.19 ac/.test(item.text || '')));
    view.destroy();
});
test('short property edges carry no length label and a traced area shows its name without its photo', () => {
    const image = Object.assign({}, photo, { corners: [{ x: -100, z: -100 }, { x: 100, z: -100 }, { x: 100, z: 100 },
        { x: -100, z: 100 }] });
    const layout = { layoutId: 'layout-a', association: { siteId: 'site-a' }, extensions: { facilitySiteContext: {
        version: 1, georeference: { originLatitude: 45, originLongitude: -93 },
        buildingPose: { x: -20, z: -15, bearingDegrees: 0 }, imagery: [image],
        property: { boundary: [{ x: -80, z: -60 }, { x: 80, z: -60 }, { x: 80, z: 60 }, { x: 79, z: 61 },
            { x: -80, z: 60 }] },
        areas: [{ areaId: 'area-lot', kind: 'existing_pavement', surface: 'asphalt',
            label: 'Parking lot south of 4th Ave N \u2014 USGS NAIP photo 2021-06-18',
            boundary: [{ x: -50, z: -40 }, { x: 50, z: -40 }, { x: 50, z: 40 }, { x: -50, z: 40 }] }] } } };
    const view = Site.create({ document: { createElement: tag => new Element(tag),
        createElementNS: (_, tag) => new Element(tag) }, session: {} });
    view.render(layout); view.show();
    const texts = [];
    (function walk(item) { if (item.tagName === 'text') texts.push(item.text); item.children.forEach(walk); })(view.element);
    assert.ok(texts.includes('E1  160.0 m') && texts.includes('E5  120.0 m'));
    assert.ok(!texts.some(text => /^E3 /.test(text || '')));  // the 1.4 m edge
    assert.ok(texts.includes('Parking lot south of 4th Ave N'));
    view.destroy();
});
