'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const MODULE_PATH = path.join(ROOT, 'static', 'facility_layout_editor.js');
const facility = require(MODULE_PATH);

let checks = 0;
const pendingChecks = [];
function check(name, fn) {
    const result = fn();
    if (result && typeof result.then === 'function') {
        pendingChecks.push(Promise.resolve(result).then(() => {
            checks += 1;
            process.stdout.write(`PASS ${name}\n`);
        }));
        return;
    }
    checks += 1;
    process.stdout.write(`PASS ${name}\n`);
}

class FakeElement {
    constructor(documentRef, name) {
        this.ownerDocument = documentRef;
        this.nodeName = name;
        this.parentNode = null;
        this.children = [];
        this.attributes = {};
        this.listeners = new Map();
        this.clientWidth = 640;
        this.clientHeight = 360;
        this.textContent = '';
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
    }

    getAttribute(name) {
        return Object.prototype.hasOwnProperty.call(this.attributes, name)
            ? this.attributes[name]
            : null;
    }

    addEventListener(type, handler) {
        if (!this.listeners.has(type)) this.listeners.set(type, new Set());
        this.listeners.get(type).add(handler);
    }

    removeEventListener(type, handler) {
        const handlers = this.listeners.get(type);
        if (handlers) handlers.delete(handler);
    }

    dispatch(type, input) {
        const event = input && input.target
            ? input
            : { target: input || this };
        event.type = type;
        event.target = event.target || this;
        if (typeof event.preventDefault !== 'function') {
            event.defaultPrevented = false;
            event.preventDefault = function () {
                this.defaultPrevented = true;
            };
        }
        const handlers = this.listeners.get(type);
        if (handlers) {
            Array.from(handlers).forEach(handler => handler(event));
        }
        return event;
    }

    descendants() {
        const result = [];
        this.children.forEach((child) => {
            result.push(child);
            result.push(...child.descendants());
        });
        return result;
    }

    findByAttribute(name, value) {
        return this.descendants().filter(
            element => element.getAttribute(name) === String(value)
        );
    }
}

class FakeDocument {
    createElementNS(namespace, name) {
        assert.strictEqual(namespace, 'http://www.w3.org/2000/svg');
        return new FakeElement(this, name);
    }
}

class FakeResizeObserver {
    constructor(callback) {
        this.callback = callback;
        this.targets = new Set();
        this.disconnected = false;
        FakeResizeObserver.instances.add(this);
    }

    observe(target) {
        if (!this.targets.has(target)) {
            this.targets.add(target);
            FakeResizeObserver.activeObservations += 1;
        }
        this.disconnected = false;
    }

    disconnect() {
        FakeResizeObserver.activeObservations -= this.targets.size;
        this.targets.clear();
        this.disconnected = true;
    }

    trigger() {
        this.callback(Array.from(this.targets).map(target => ({ target })));
    }

    static reset() {
        FakeResizeObserver.instances = new Set();
        FakeResizeObserver.activeObservations = 0;
    }
}
FakeResizeObserver.reset();

function layout(placements) {
    return {
        schemaVersion: 1,
        layoutId: 'fl-editor-test',
        displayName: 'Editor Test',
        status: 'draft',
        association: { siteId: 'site-a' },
        coordinateFrame: {
            units: 'm',
            handedness: 'right',
            upAxis: '+Y',
            floorAxes: ['+X', '+Z'],
            datumId: 'site-origin',
            floorElevation: 0,
        },
        sourceShellRef: {
            shellId: 'shell-a',
            shellRevision: 'a'.repeat(64),
            coordinateFrameFingerprint: 'b'.repeat(64),
        },
        policySetRef: {
            policySetId: 'policy-a',
            policySetRevision: 'c'.repeat(64),
        },
        zones: [{
            zoneId: 'zn-cell',
            zoneType: 'workcell',
            label: 'Cell',
            boundary: [
                { x: 0, z: 0 },
                { x: 12, z: 0 },
                { x: 12, z: 8 },
                { x: 0, z: 8 },
            ],
            floorElevation: 0,
            anchors: [],
            evidence: [],
        }],
        placements: placements || [
            placement('pl-machine', 'asset-machine', 3, 2),
            placement('pl-rack', 'asset-rack', 9, 6),
        ],
        routes: [{
            routeId: 'rt-material',
            routeKind: 'material',
            sourceEndpoint: {
                kind: 'placement_connector',
                placementId: 'pl-machine',
                connectorId: 'out',
            },
            targetEndpoint: {
                kind: 'placement_connector',
                placementId: 'pl-rack',
                connectorId: 'in',
            },
            routingMode: 'orthogonal',
            centerline: [
                { x: 3, y: 0, z: 2 },
                { x: 9, y: 0, z: 2 },
                { x: 9, y: 0, z: 6 },
            ],
            corridorWidth: 0.8,
            routeFingerprint: 'd'.repeat(64),
            sourceRevisions: { layout: 'e'.repeat(64) },
            requirements: [],
            evidence: [],
        }],
        utilityNetworks: [],
        processBindings: [],
        dismissedSuggestions: [],
        createdAt: '2026-07-29T00:00:00Z',
        updatedAt: '2026-07-29T00:00:00Z',
        futureField: { preserved: true },
    };
}

function placement(placementId, assetId, x, z) {
    return {
        placementId,
        assetId,
        assetDefinitionRevision: 'f'.repeat(64),
        transform: {
            position: { x, y: 0, z },
            quaternion: { x: 0, y: 0, z: 0, w: 1 },
            scale: 1,
        },
        positionMode: 'auto',
        snapRelationship: null,
        metadata: { instanceLabel: placementId },
    };
}

function makeHost() {
    const documentRef = new FakeDocument();
    const host = new FakeElement(documentRef, 'host');
    return { documentRef, host };
}

function mockAdapter(id) {
    return {
        id,
        type: 'mock',
        layouts: [],
        selections: [],
        fitCount: 0,
        fitFacilityCount: 0,
        fitLayoutCount: 0,
        topViewCount: 0,
        disposed: false,
        suspended: false,
        handler: null,
        setSelectionHandler(handler) { this.handler = handler; },
        setLayout(value) { this.layouts.push(value); },
        setSelection(value) { this.selections.push(value); },
        fit() { this.fitCount += 1; return { id: this.id }; },
        fitFacility() {
            this.fitCount += 1;
            this.fitFacilityCount += 1;
            return { id: this.id, mode: 'facility' };
        },
        fitLayout() {
            this.fitLayoutCount += 1;
            return { id: this.id, mode: 'layout' };
        },
        topView() {
            this.topViewCount += 1;
            return { id: this.id, mode: 'top' };
        },
        suspend() { this.suspended = true; return true; },
        resume() { this.suspended = false; return true; },
        dispose() { this.disposed = true; },
        getDiagnostics() {
            return {
                id: this.id,
                type: this.type,
                mounted: !this.disposed && !this.suspended,
                suspended: this.suspended,
                observerCount: 0,
                renderCount: this.layouts.length + this.selections.length,
                selection: this.selections[this.selections.length - 1] || null,
            };
        },
    };
}

check('module exports CommonJS and classic global API', () => {
    assert.strictEqual(facility.API_VERSION, 1);
    assert.strictEqual(typeof facility.createEditor, 'function');
    const source = fs.readFileSync(MODULE_PATH, 'ascii');
    const self = {};
    vm.runInNewContext(source, { self });
    assert.strictEqual(typeof self.InspectorProFacilityLayout.createEditor, 'function');
    assert.strictEqual(
        typeof self.InspectorProFacilityLayout.createTopPlanAdapter,
        'function'
    );
});

check('X/Z projection and inverse are deterministic', () => {
    const bounds = { minX: 0, minZ: 0, maxX: 10, maxZ: 5 };
    const first = facility.createTopPlanProjection(
        bounds,
        { width: 220, height: 120 },
        10
    );
    const second = facility.createTopPlanProjection(
        bounds,
        { width: 220, height: 120 },
        10
    );
    assert.deepStrictEqual(first, second);
    assert.deepStrictEqual(
        facility.projectTopPlanPoint({ x: 0, z: 5 }, first),
        { x: 10, y: 10 }
    );
    assert.deepStrictEqual(
        facility.projectTopPlanPoint({ x: 10, z: 0 }, first),
        { x: 210, y: 110 }
    );
    const point = { x: 7.25, z: 1.5 };
    const projected = facility.projectTopPlanPoint(point, first);
    assert.deepStrictEqual(facility.unprojectTopPlanPoint(projected, first), point);
});

check('unknown asset bounds use one deterministic fallback footprint', () => {
    const source = placement('pl-unknown', 'asset-unknown', 4, 7);
    const first = facility.placementFootprint(source, {});
    const second = facility.placementFootprint(source, {});
    assert.deepStrictEqual(first, second);
    assert.deepStrictEqual(first, [
        { x: 3.4, z: 6.6 },
        { x: 4.6, z: 6.6 },
        { x: 4.6, z: 7.4 },
        { x: 3.4, z: 7.4 },
    ]);
});

check('plan geometry leaves overhead structure to 3D', () => {
    const beam = placement('pl-beam', 'asset-unknown', 4, 7);
    beam.transform.position.y = 10;
    const low = placement('pl-shelf', 'asset-unknown', 8, 7);
    low.transform.position.y = 4;
    const stacked = placement('pl-stacked', 'asset-unknown', 12, 7);
    stacked.transform.position.y = 6;
    stacked.snapRelationship = { family: 'vertical_stack', stackId: 'st-1', level: 3 };
    const ids = facility.collectTopPlanGeometry(layout([beam, low, stacked]), {})
        .placements.map((item) => item.placementId);
    assert.deepStrictEqual(ids, ['pl-shelf', 'pl-stacked']);
});

check('authored shell bounds keep sparse layouts in a stable world frame', () => {
    const sparse = layout([placement('pl-machine', 'asset-machine', 0, 0)]);
    assert.deepStrictEqual(
        facility.collectTopPlanBounds(sparse, {
            worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
        }),
        { minX: -0.6, minZ: -0.4, maxX: 40, maxZ: 30 }
    );
});

check('top plan renders the measured facility floor grid axes and origin', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout();
    const before = JSON.stringify(source);
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
        floorGridSpacing: 1,
        floorMajorGridSpacing: 5,
        units: 'm',
        originMode: 'corner',
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(source);
    assert.strictEqual(
        host.findByAttribute('data-layer', 'environment').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-facility-floor', 'true').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-facility-origin', 'true').length,
        1
    );
    assert.deepStrictEqual(adapter.getDiagnostics().environment, {
        bounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
        spacing: 1,
        majorSpacing: 5,
        minorLineCount: 56,
        majorLineCount: 16,
        origin: { x: 0, z: 0 },
        center: { x: 20, z: 15 },
    });
    const facilityProjection = adapter.fitFacility();
    const layoutProjection = adapter.fitLayout();
    assert(layoutProjection.scale > facilityProjection.scale);
    assert.strictEqual(JSON.stringify(source), before);
    adapter.dispose();
});

check('top plan fits the building alone, large in the view, whatever lies past its walls', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout([
        placement('pl-machine', 'asset-machine', 3, 2),
        placement('pl-far', 'asset-rack', 120, 70),  // e.g. a car out in the car park
    ]);
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
        units: 'm',
        originMode: 'corner',
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(source);
    const facilityProjection = adapter.fitFacility();
    const building = adapter.fitBuilding();
    assert(building.scale > 2 * facilityProjection.scale);
    // The 40 x 30 m building fills the height bar the margin and fits the width.
    assert(building.scale * 30 >= 0.8 * 650 && building.scale * 30 <= 650);
    assert(building.scale * 40 <= 900);
    adapter.dispose();
});

check('top plan updates dimensions grid rulers and view-only scale together', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout();
    const before = JSON.stringify(source);
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
        floorGridSpacing: 1,
        floorMajorGridSpacing: 5,
        units: 'm',
        originMode: 'corner',
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(source);
    adapter.setEnvironmentSettings({
        worldBounds: { minX: 0, minZ: 0, maxX: 55, maxZ: 36 },
        floorGridSpacing: 2,
        floorMajorGridSpacing: 10,
    });
    const environment = adapter.getDiagnostics().environment;
    assert.deepStrictEqual(environment.bounds, {
        minX: 0, minZ: 0, maxX: 55, maxZ: 36,
    });
    assert.strictEqual(environment.spacing, 2);
    assert.strictEqual(environment.majorSpacing, 10);
    const caption = host.findByAttribute(
        'data-plan-settings-trigger',
        'dimensions'
    )[0];
    assert.strictEqual(caption.textContent, '55 x 36 m | Grid 2 m');
    const originalScale = adapter.getViewportState().projection.scale;
    assert.strictEqual(
        adapter.setScaleAt({ clientX: 450, clientY: 325 }, originalScale * 1.5),
        true
    );
    assert.ok(Math.abs(
        adapter.getViewportState().projection.scale - originalScale * 1.5
    ) < 1e-6);
    assert.strictEqual(JSON.stringify(source), before);
    adapter.dispose();
});

check('top plan publishes projection changes and applies view-only preferences', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout();
    const before = JSON.stringify(source);
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
        floorGridSpacing: 1,
        floorMajorGridSpacing: 5,
        getSize: () => ({ width: 900, height: 650 }),
    });
    const snapshots = [];
    adapter.setViewportChangeHandler(value => snapshots.push(value));
    adapter.setLayout(source);
    const countAfterLayout = snapshots.length;
    adapter.panByPixels(12, -7);
    adapter.zoomAt({ clientX: 450, clientY: 325 }, 1.25);
    assert.ok(snapshots.length >= countAfterLayout + 2);
    adapter.setViewPreferences({ displayUnit: 'ft', showGrid: false });
    const state = adapter.getViewportState();
    assert.strictEqual(state.displayUnit, 'ft');
    assert.strictEqual(state.showGrid, false);
    assert.strictEqual(adapter.getDiagnostics().environment.minorLineCount, 0);
    assert.strictEqual(adapter.getDiagnostics().environment.majorLineCount, 0);
    const card = host.findByAttribute('data-placement-id', 'pl-machine')[0];
    assert.ok(card.getAttribute('aria-label').includes('feet'));
    assert.strictEqual(JSON.stringify(source), before);
    adapter.dispose();
});

check('top plan renders and clears transient zone drawing previews', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(layout());
    adapter.setTransientZonePreview([
        { x: 2, z: 3 },
        { x: 8, z: 3 },
        { x: 8, z: 7 },
        { x: 2, z: 7 },
    ], { kind: 'rectangle', closed: true });
    assert.strictEqual(
        host.findByAttribute('data-layer', 'transient-zone-preview').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute(
            'data-facility-zone-preview',
            'rectangle'
        )[0].nodeName,
        'polygon'
    );
    assert.strictEqual(
        host.findByAttribute('data-zone-preview-vertex', '0').length,
        1
    );
    assert.strictEqual(
        adapter.getDiagnostics().transientZonePreview.closed,
        true
    );

    adapter.setTransientZonePreview([
        { x: 1, z: 1 },
        { x: 4, z: 1 },
    ], { kind: 'polygon', closed: false });
    assert.strictEqual(
        host.findByAttribute(
            'data-facility-zone-preview',
            'polygon'
        )[0].nodeName,
        'polyline'
    );
    adapter.setTransientZonePreview([], {});
    assert.strictEqual(
        host.findByAttribute('data-layer', 'transient-zone-preview').length,
        0
    );
    assert.strictEqual(adapter.getDiagnostics().transientZonePreview, null);
    adapter.dispose();
});

check('top plan renders mixed pattern ghosts and deterministic guides', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout();
    source.floorMarkings = [{
        markingId: 'fm-flow',
        markingType: 'direction_arrow',
        label: 'Material flow',
        semanticRole: 'material_flow',
        transform: {
            position: { x: 4, y: 0, z: 4 },
            rotationDegrees: 0,
        },
        width: 1.5,
        depth: 0.75,
        fillColor: '#facc15',
        strokeColor: '#111827',
        opacity: 1,
        positionMode: 'manual',
    }];
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        assetBounds: {
            'asset-machine': { width: 2, depth: 1 },
            'asset-rack': { width: 3, depth: 1.2 },
        },
        worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(source);
    adapter.setTransientPatternPreview({
        mode: 'linear',
        copies: [
            {
                sourceId: 'pl-machine',
                kind: 'placement',
                position: { x: 12, y: 0, z: 4 },
                rotationDegrees: 0,
            },
            {
                sourceId: 'fm-flow',
                kind: 'floor-marking',
                position: { x: 14, y: 0, z: 4 },
                rotationDegrees: 90,
            },
            {
                sourceId: 'zn-cell',
                kind: 'zone',
                position: { x: 16, y: 0, z: 4 },
                rotationDegrees: 0,
                boundary: [
                    { x: 15, z: 3 },
                    { x: 17, z: 3 },
                    { x: 17, z: 5 },
                    { x: 15, z: 5 },
                ],
            },
        ],
        moves: [],
        guide: {
            kind: 'linear',
            start: { x: 4, z: 4 },
            end: { x: 16, z: 4 },
        },
    });
    assert.strictEqual(
        host.findByAttribute('data-layer', 'pattern-preview').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-pattern-preview-source', 'pl-machine').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-pattern-preview-source', 'fm-flow').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-pattern-preview-source', 'zn-cell').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-pattern-guide', 'linear').length,
        1
    );
    assert.strictEqual(
        adapter.getDiagnostics().transientPatternPreview.mode,
        'linear'
    );
    adapter.setTransientPatternPreview({
        mode: 'mirror',
        copies: [{
            sourceId: 'pl-machine',
            kind: 'placement',
            position: { x: 20, y: 0, z: 4 },
            rotationDegrees: 180,
        }],
        moves: [],
        guide: {
            kind: 'mirror',
            start: { x: 12, z: 0 },
            end: { x: 12, z: 30 },
        },
    });
    assert.strictEqual(
        host.findByAttribute('data-pattern-guide', 'mirror').length,
        1
    );
    assert.strictEqual(
        adapter.getDiagnostics().transientPatternPreview.mode,
        'mirror'
    );
    adapter.setTransientPatternPreview(null);
    assert.strictEqual(
        host.findByAttribute('data-layer', 'pattern-preview').length,
        0
    );
    adapter.dispose();
});

check('top plan renders zones routes and placements with stable IDs', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        assetBounds: {
            'asset-machine': { width: 2, depth: 1 },
            'asset-rack': { width: 3, depth: 1.2 },
        },
    });
    const markedLayout = layout();
    markedLayout.floorMarkings = [{
        markingId: 'fm-keep-clear',
        markingType: 'keep_clear',
        label: 'CNC keep clear',
        semanticRole: 'keep_clear',
        transform: {
            position: { x: 6, y: 0, z: 4 },
            rotationDegrees: 15,
        },
        width: 3,
        depth: 2,
        fillColor: '#facc15',
        strokeColor: '#111827',
        opacity: 0.9,
        text: 'KEEP CLEAR',
        positionMode: 'manual',
        metadata: {},
        evidence: [],
    }];
    adapter.setLayout(markedLayout);
    assert.strictEqual(host.children.length, 1);
    assert.strictEqual(host.findByAttribute('data-zone-id', 'zn-cell').length, 1);
    const zoneLabel = host.findByAttribute(
        'data-zone-label-for',
        'zn-cell'
    );
    assert.strictEqual(zoneLabel.length, 1);
    assert.strictEqual(zoneLabel[0].nodeName, 'g');
    assert.strictEqual(zoneLabel[0].children[1].textContent, 'Cell');
    const quiet = JSON.parse(JSON.stringify(markedLayout));
    const strip = quiet.zones.find((zone) => zone.zoneId === 'zn-cell');
    strip.extensions = Object.assign({}, strip.extensions, { style: { labelHidden: true } });
    adapter.setLayout(quiet);
    assert.strictEqual(host.findByAttribute('data-zone-id', 'zn-cell').length, 1);
    assert.strictEqual(host.findByAttribute('data-zone-label-for', 'zn-cell').length, 0);
    adapter.setLayout(markedLayout);
    assert.strictEqual(host.findByAttribute('data-route-id', 'rt-material').length, 1);
    const floorMarking = host.findByAttribute(
        'data-floor-marking-id',
        'fm-keep-clear'
    );
    assert.strictEqual(floorMarking.length, 1);
    assert.strictEqual(
        floorMarking[0].getAttribute('data-floor-marking-type'),
        'keep_clear'
    );
    assert.ok(floorMarking[0].getAttribute('aria-label').includes(
        'CNC keep clear'
    ));
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-machine').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-rack').length,
        1
    );
    const machineCard = host.findByAttribute(
        'data-placement-id',
        'pl-machine'
    )[0];
    assert.strictEqual(machineCard.nodeName, 'g');
    assert.strictEqual(machineCard.getAttribute('class'), 'ip-flw-plan-card');
    assert.strictEqual(machineCard.getAttribute('data-card-world-width'), '2');
    assert.strictEqual(machineCard.getAttribute('data-card-world-depth'), '1');
    assert(machineCard.getAttribute('aria-label').includes('2 by 1 metres'));
    assert.strictEqual(
        machineCard.findByAttribute('class', 'ip-flw-plan-card-body').length,
        1
    );
    assert.strictEqual(
        machineCard.findByAttribute('data-card-content', 'compact').length,
        1
    );
    assert.strictEqual(
        machineCard.findByAttribute('data-card-content', 'full').length,
        1
    );
    const detailLevel = machineCard.getAttribute('data-card-detail-level');
    const compactContent = machineCard.findByAttribute(
        'data-card-content', 'compact'
    )[0];
    const fullContent = machineCard.findByAttribute(
        'data-card-content', 'full'
    )[0];
    assert.strictEqual(
        compactContent.getAttribute('display'),
        detailLevel === 'compact' ? 'inline' : 'none'
    );
    assert.strictEqual(
        fullContent.getAttribute('display'),
        detailLevel === 'full' ? 'inline' : 'none'
    );
    assert.strictEqual(
        compactContent.findByAttribute(
            'class', 'ip-flw-plan-card-symbol'
        )[0].getAttribute('fill'),
        '#dceeff'
    );
    adapter.setSelection('fm-keep-clear');
    assert.strictEqual(
        host.findByAttribute(
            'class', 'ip-flw-floor-marking-resize-handle'
        ).length,
        4
    );
    [0, 1, 2, 3].forEach(index => {
        assert.strictEqual(
            host.findByAttribute(
                'data-floor-marking-resize-handle',
                String(index)
            ).length,
            1
        );
    });
    assert.ok(adapter.getDiagnostics().renderCount >= 1);
    adapter.dispose();
});

check('top plan layer visibility is presentation-only and hierarchy-aware', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
    });
    const input = layout();
    input.zones[0].extensions = {
        knowledgeFoundation: { entityKind: 'department' },
    };
    input.zones.push({
        zoneId: 'zn-child-cell',
        zoneType: 'workcell',
        label: 'Child Cell',
        boundary: [
            { x: 1, z: 1 },
            { x: 5, z: 1 },
            { x: 5, z: 4 },
            { x: 1, z: 4 },
        ],
        floorElevation: 0,
        anchors: [],
        evidence: [],
        extensions: {
            knowledgeFoundation: {
                entityKind: 'cell',
                parentZoneId: 'zn-cell',
            },
        },
    });
    input.floorMarkings = [{
        markingId: 'fm-layer-test',
        markingType: 'parking_box',
        label: 'Parking',
        semanticRole: 'parking',
        transform: { position: { x: 2, y: 0, z: 6 } },
        width: 1,
        depth: 2,
        fillColor: '#2563eb',
        strokeColor: '#ffffff',
        opacity: 1,
    }];
    const authoritative = JSON.stringify(input);
    adapter.setLayout(input);
    adapter.setLayerVisibility({
        zones: false,
        cells: true,
        routes: false,
        markings: false,
        assets: false,
    });
    assert.strictEqual(
        host.findByAttribute('data-zone-id', 'zn-cell').length,
        0
    );
    assert.strictEqual(
        host.findByAttribute('data-zone-id', 'zn-child-cell').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-route-id', 'rt-material').length,
        0
    );
    assert.strictEqual(
        host.findByAttribute('data-floor-marking-id', 'fm-layer-test').length,
        0
    );
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-machine').length,
        0
    );
    assert.deepStrictEqual(adapter.getLayerVisibility(), {
        zones: false,
        cells: true,
        routes: false,
        markings: false,
        assets: false,
        walls: true,
    });
    assert.strictEqual(JSON.stringify(input), authoritative);
    adapter.dispose();
});

check('Plan walls hide independently of assets and preserve the document', () => {
    const { documentRef, host } = makeHost();
    const input = layout([placement('pl-wall', 'asset-wall', 2, 2)]);
    input.extensions = { facilityPerimeterWalls: { version: 1, settings: { heightMeters: 6 },
        panels: [[{x:0,z:0},{x:0,z:10},{x:.2,z:10}]] } };
    const adapter = facility.createTopPlanAdapter(host, { document: documentRef,
        assetCatalog: [{assetId:'asset-wall', assetDefinitionRevision:input.placements[0].assetDefinitionRevision,tags:['wall']}] });
    const before = JSON.stringify(input);
    adapter.setLayout(input); adapter.setLayerVisibility({assets:false});
    assert.equal(host.findByAttribute('data-placement-id','pl-wall').length,1);
    assert.equal(host.findByAttribute('data-layer','walls')[0].children.length,1);
    adapter.setLayerVisibility({walls:false});
    assert.equal(host.findByAttribute('data-placement-id','pl-wall').length,0);
    assert.equal(host.findByAttribute('data-layer','walls')[0].children.length,0);
    assert.equal(JSON.stringify(input),before); adapter.dispose();
});

check('top plan collapses a vertical stack into one counted footprint', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const members = [0, 1, 2].map(level => {
        const item = placement(
            `pl-stack-${level}`,
            'asset-machine',
            4,
            4
        );
        item.transform.position.y = level * 0.2;
        item.snapRelationship = {
            family: 'vertical_stack',
            stackId: 'stack-editor-a',
            level,
            count: 3,
            gapMeters: 0,
            itemHeightMeters: 0.2,
            evidenceStatus: 'unverified',
        };
        return item;
    });
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        assetBounds: { 'asset-machine': { width: 2, depth: 1 } },
    });
    adapter.setLayout(layout(members));
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-stack-0').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-stack-1').length,
        0
    );
    const badge = host.findByAttribute('data-stack-badge', 'stack-editor-a');
    assert.strictEqual(badge.length, 1);
    const card = host.findByAttribute('data-stack-id', 'stack-editor-a')[0];
    assert.strictEqual(card.getAttribute('data-stack-count'), '3');
    assert.ok(card.getAttribute('aria-label').includes('stack of 3 items'));
    adapter.dispose();
});

check('zone header tabs avoid equipment occupying the upper-left corner', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout([
        placement('pl-machine', 'asset-machine', 1, 7.5),
    ]);
    source.routes = [];
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        assetBounds: {
            'asset-machine': { width: 2, depth: 1 },
        },
    });
    adapter.setLayout(source);
    const label = host.findByAttribute(
        'data-zone-label-box-for',
        'zn-cell'
    )[0];
    const card = host.findByAttribute(
        'class',
        'ip-flw-plan-card-body'
    )[0];
    const labelBounds = {
        minX: Number(label.getAttribute('x')),
        minY: Number(label.getAttribute('y')),
        maxX: Number(label.getAttribute('x'))
            + Number(label.getAttribute('width')),
        maxY: Number(label.getAttribute('y'))
            + Number(label.getAttribute('height')),
    };
    const points = card.getAttribute('points').split(' ').map(value => {
        const pair = value.split(',').map(Number);
        return { x: pair[0], y: pair[1] };
    });
    const cardBounds = {
        minX: Math.min(...points.map(point => point.x)),
        minY: Math.min(...points.map(point => point.y)),
        maxX: Math.max(...points.map(point => point.x)),
        maxY: Math.max(...points.map(point => point.y)),
    };
    const overlapWidth = Math.max(
        0,
        Math.min(labelBounds.maxX, cardBounds.maxX)
            - Math.max(labelBounds.minX, cardBounds.minX)
    );
    const overlapHeight = Math.max(
        0,
        Math.min(labelBounds.maxY, cardBounds.maxY)
            - Math.max(labelBounds.minY, cardBounds.minY)
    );
    assert.strictEqual(overlapWidth * overlapHeight, 0);
    assert.strictEqual(
        host.findByAttribute('data-zone-label-for', 'zn-cell')[0]
            .getAttribute('data-zone-label-edge'),
        'top-inside'
    );
    adapter.dispose();
});

check('a zone inside the building keeps its label inside the walls', () => {
    // Live 2026-10-24: "Forklift charging", a 1 m strip along the east wall, hung its label past the wall.
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout([]);
    source.routes = [];
    source.zones.push(Object.assign({}, source.zones[0], {
        zoneId: 'zn-charging',
        zoneType: 'charging',
        label: 'Forklift charging',
        boundary: [{ x: 11, z: 2 }, { x: 12, z: 2 }, { x: 12, z: 6 }, { x: 11, z: 6 }],
    }));
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: { minX: 0, minZ: 0, maxX: 12, maxZ: 8 },
    });
    adapter.setLayout(source);
    const walls = host.findByAttribute('data-zone-id', 'zn-cell')[0].getAttribute('points')
        .split(' ').map(pair => pair.split(',').map(Number));
    const label = zoneLabelBox(host, 'zn-charging');
    assert.ok(label.minX >= Math.min(...walls.map(p => p[0])) && label.maxX <= Math.max(...walls.map(p => p[0]))
        && label.minY >= Math.min(...walls.map(p => p[1])) && label.maxY <= Math.max(...walls.map(p => p[1])),
    JSON.stringify({ label, walls }));
    adapter.dispose();
});

check('zone labels at the plan boundary avoid a clamped top-outside slot', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout([]);
    source.routes = [];
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: { minX: 0, minZ: 0, maxX: 12, maxZ: 8 },
    });
    adapter.setLayout(source);
    const label = host.findByAttribute(
        'data-zone-label-for',
        'zn-cell'
    )[0];
    assert.notStrictEqual(
        label.getAttribute('data-zone-label-edge'),
        'top-outside'
    );
    adapter.dispose();
});

function zoneLabelBox(host, zoneId) {
    const box = host.findByAttribute('data-zone-label-box-for', zoneId)[0];
    const minX = Number(box.getAttribute('x'));
    const minY = Number(box.getAttribute('y'));
    return {
        minX, minY,
        maxX: minX + Number(box.getAttribute('width')),
        maxY: minY + Number(box.getAttribute('height')),
    };
}

function roomyZoneLabelPlan(label, worldBounds) {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout([]);
    source.routes = [];
    if (label) source.zones[0].label = label;
    // By default there is free space all round the zone, so an outside slot is
    // open and unclamped.
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: worldBounds || { minX: -10, minZ: -10, maxX: 22, maxZ: 18 },
    });
    adapter.setLayout(source);
    return { documentRef, host, source, adapter };
}

function boxesOverlap(left, right) {
    return Math.min(left.maxX, right.maxX) > Math.max(left.minX, right.minX)
        && Math.min(left.maxY, right.maxY) > Math.max(left.minY, right.minY);
}

check('a zone name too wide for one line wraps to stay inside its zone', () => {
    // The 12 m zone is about 145 px wide; "Raw Material Storage" needs 152 px on one line.
    const { host, adapter } = roomyZoneLabelPlan('Raw Material Storage');
    const label = host.findByAttribute('data-zone-label-for', 'zn-cell')[0];
    assert.strictEqual(label.getAttribute('data-zone-label-lines'), '2');
    assert.match(label.getAttribute('data-zone-label-edge'), /-inside$/);
    const spans = label.descendants().filter(element => element.nodeName === 'tspan');
    assert.deepStrictEqual(spans.map(span => span.textContent.trim()), ['Raw Material', 'Storage']);
    assert.strictEqual(spans.map(span => span.textContent).join(''), 'Raw Material Storage');
    const box = zoneLabelBox(host, 'zn-cell');
    assert.strictEqual(box.maxY - box.minY, 36);
    adapter.dispose();
});

check('zone labels keep clear of the plan size readout', () => {
    // The zone shares the plan's top-left corner, where the readout is drawn.
    const { host, adapter } = roomyZoneLabelPlan(
        null, { minX: 0, minZ: -10, maxX: 30, maxZ: 8 });
    const caption = host.findByAttribute('class', 'ip-flw-plan-grid-caption')[0];
    const x = Number(caption.getAttribute('x'));
    const y = Number(caption.getAttribute('y'));
    // A browser draws the 11 px readout about 5 px a character and 14 px tall.
    const readout = { minX: x, minY: y - 12, maxX: x + caption.textContent.length * 5, maxY: y + 2 };
    assert.ok(!boxesOverlap(zoneLabelBox(host, 'zn-cell'), readout));
    assert.match(
        host.findByAttribute('data-zone-label-for', 'zn-cell')[0]
            .getAttribute('data-zone-label-edge'),
        /-inside$/
    );
    adapter.dispose();
});

check('zone labels sit inside a zone that has room for them', () => {
    const { host, adapter } = roomyZoneLabelPlan();
    assert.strictEqual(
        host.findByAttribute('data-zone-label-for', 'zn-cell')[0]
            .getAttribute('data-zone-label-edge'),
        'top-inside'
    );
    adapter.dispose();
});

check('zone labels move out from under controls floating over the plan', () => {
    const { documentRef, host, source, adapter } = roomyZoneLabelPlan();
    const covered = zoneLabelBox(host, 'zn-cell');
    // A toolbar over the label's first-choice slot, as the plan navigation can be.
    const svg = host.children.find(child => child.nodeName === 'svg');
    svg.getBoundingClientRect = () => ({
        left: 0, top: 0, right: 640, bottom: 360, width: 640, height: 360,
    });
    const toolbar = {
        getBoundingClientRect: () => ({
            left: covered.minX, top: covered.minY,
            right: covered.maxX, bottom: covered.maxY,
            width: covered.maxX - covered.minX, height: covered.maxY - covered.minY,
        }),
    };
    documentRef.querySelectorAll = selector => (
        selector === '[data-plan-overlay]' ? [toolbar] : []);
    adapter.setLayout(source);
    const moved = zoneLabelBox(host, 'zn-cell');
    const overlapWidth = Math.min(moved.maxX, covered.maxX) - Math.max(moved.minX, covered.minX);
    const overlapHeight = Math.min(moved.maxY, covered.maxY) - Math.max(moved.minY, covered.minY);
    assert.ok(overlapWidth <= -4 || overlapHeight <= -4, JSON.stringify({ covered, moved }));
    assert.match(
        host.findByAttribute('data-zone-label-for', 'zn-cell')[0]
            .getAttribute('data-zone-label-edge'),
        /-inside$/
    );
    adapter.dispose();
});

check('zone labels use hierarchy-aware semantic zoom without overlap', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout([]);
    source.routes = [];
    source.zones = [
        {
            zoneId: 'zn-parent',
            zoneType: 'workcell',
            label: 'Assembly Department',
            boundary: [
                { x: 0, z: 0 }, { x: 40, z: 0 },
                { x: 40, z: 20 }, { x: 0, z: 20 },
            ],
            floorElevation: 0,
            anchors: [],
            evidence: [],
            extensions: { knowledgeFoundation: { entityKind: 'department' } },
        },
        ...[0, 1, 2, 3].map(index => ({
            zoneId: `zn-child-${index + 1}`,
            zoneType: 'workcell',
            label: `Assembly Cell ${index + 1}`,
            boundary: [
                { x: index * 10, z: 0 },
                { x: (index + 1) * 10, z: 0 },
                { x: (index + 1) * 10, z: 20 },
                { x: index * 10, z: 20 },
            ],
            floorElevation: 0,
            anchors: [],
            evidence: [],
            extensions: {
                knowledgeFoundation: {
                    entityKind: 'subzone',
                    parentZoneId: 'zn-parent',
                },
            },
        })),
    ];
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 20 },
        getSize: () => ({ width: 900, height: 600 }),
    });
    adapter.setLayout(source);
    assert.strictEqual(
        host.findByAttribute('data-zone-label-for', 'zn-parent').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-zone-label-for', 'zn-child-1').length,
        0
    );
    assert.strictEqual(adapter.getDiagnostics().zoneLabels.semanticLevel,
        'overview');

    adapter.zoomAt({ clientX: 450, clientY: 300 }, 2);
    assert.strictEqual(
        host.findByAttribute('data-zone-label-for', 'zn-parent').length,
        0
    );
    assert.strictEqual(
        host.findByAttribute('data-zone-label-for', 'zn-child-1').length,
        1
    );
    assert.strictEqual(adapter.getDiagnostics().zoneLabels.semanticLevel,
        'detail');
    assert.strictEqual(adapter.getDiagnostics().zoneLabels.labelOverlapArea, 0);
    adapter.dispose();
});

check('plan picking synchronizes one stable selection to every view', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const top = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
    });
    const peer = mockAdapter('three-view');
    const controller = facility.createEditor({
        layout: layout(),
        adapters: [top, peer],
    });
    assert.strictEqual(top.pick('pl-rack'), true);
    assert.strictEqual(controller.getState().selectedPlacementId, 'pl-rack');
    assert.strictEqual(top.getDiagnostics().selection, 'pl-rack');
    assert.strictEqual(peer.selections[peer.selections.length - 1], 'pl-rack');
    assert.strictEqual(top.pick('pl-missing'), false);
    assert.strictEqual(controller.getState().selectedPlacementId, 'pl-rack');
    controller.clearSelection();
    assert.strictEqual(top.getDiagnostics().selection, null);
    controller.dispose();
});

check('plan placement drag preview moves cards transiently without mutating layout',
    () => {
        FakeResizeObserver.reset();
        const { documentRef, host } = makeHost();
        const source = layout();
        const before = JSON.stringify(source);
        const adapter = facility.createTopPlanAdapter(host, {
            document: documentRef,
            ResizeObserver: FakeResizeObserver,
            assetBounds: {
                'asset-machine': { width: 2, depth: 1 },
                'asset-rack': { width: 3, depth: 1.2 },
            },
        });
        adapter.setLayout(source);
        const card = host.findByAttribute(
            'data-placement-id',
            'pl-machine'
        )[0];
        assert.strictEqual(adapter.setTransientPlacementMove(
            ['pl-machine'],
            { x: 2, y: 0, z: -1 }
        ), true);
        assert(card.getAttribute('transform').startsWith('translate('));
        assert.strictEqual(card.getAttribute('data-drag-preview'), 'true');
        assert.strictEqual(JSON.stringify(source), before);
        assert.strictEqual(adapter.setTransientPlacementMove([], null), true);
        assert.strictEqual(card.getAttribute('transform'), '');
        assert.strictEqual(card.getAttribute('data-drag-preview'), 'false');
        assert.strictEqual(JSON.stringify(source), before);
        adapter.dispose();
    });

check('plan duplicate drag previews a copy while the source remains fixed', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout();
    const before = JSON.stringify(source);
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        assetBounds: {
            'asset-machine': { width: 2, depth: 1 },
            'asset-rack': { width: 3, depth: 1.2 },
        },
    });
    adapter.setLayout(source);
    const card = host.findByAttribute('data-placement-id', 'pl-machine')[0];
    assert.strictEqual(adapter.setTransientPlacementDuplicate(
        ['pl-machine'],
        { x: 2, y: 0, z: -1 }
    ), true);
    assert.strictEqual(card.getAttribute('transform'), '');
    assert.strictEqual(card.getAttribute('data-drag-preview'), 'false');
    const previews = host.findByAttribute(
        'data-duplicate-preview-id',
        'pl-machine'
    );
    assert.strictEqual(previews.length, 1);
    assert.ok(previews[0].getAttribute('transform').startsWith('translate('));
    assert.deepStrictEqual(adapter.getDiagnostics().transientPlacementDuplicate, {
        placementIds: ['pl-machine'],
        delta: { x: 2, y: 0, z: -1 },
    });
    assert.strictEqual(JSON.stringify(source), before);
    assert.strictEqual(adapter.setTransientPlacementDuplicate([], null), true);
    assert.strictEqual(
        host.findByAttribute('data-layer', 'placement-duplicate-preview').length,
        0
    );
    assert.strictEqual(JSON.stringify(source), before);
    adapter.dispose();
});

check('Plan uses saved appearance and restores it after deselection', () => {
    const {documentRef, host} = makeHost();
    const top = facility.createTopPlanAdapter(host, {document:documentRef, ResizeObserver:FakeResizeObserver});
    const doc = layout();
    doc.placements.find(p => p.placementId === 'pl-machine').appearance = {color:'#2478bc'};
    top.setLayout(doc);
    const color = () => host.findByAttribute('data-placement-id','pl-machine')[0]
        .findByAttribute('class','ip-flw-plan-card-body')[0].getAttribute('fill');
    assert.equal(color(), '#2478bc');
    top.setSelection('pl-machine'); assert.equal(color(), '#bfe3ff');
    top.setSelection(null); assert.equal(color(), '#2478bc');
    top.dispose();
});

check('zones and placements are mouse and keyboard selectable', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const top = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
    });
    top.setLayout(layout());
    const zone = host.findByAttribute('data-zone-id', 'zn-cell')[0];
    const placementNode = host.findByAttribute(
        'data-placement-id',
        'pl-machine'
    )[0];
    assert.strictEqual(zone.getAttribute('role'), 'button');
    assert.strictEqual(zone.getAttribute('tabindex'), '0');
    assert.strictEqual(top.pick('zn-cell'), true);
    assert.strictEqual(top.getDiagnostics().selection, 'zn-cell');
    const keyboard = top.svg.dispatch('keydown', {
        target: placementNode,
        key: ' ',
    });
    assert.strictEqual(keyboard.defaultPrevented, true);
    assert.strictEqual(top.getDiagnostics().selection, 'pl-machine');
    top.dispose();
});

check('top plan draws columns over the walls; they are picked like zones and hide with the walls', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const top = facility.createTopPlanAdapter(host, { document: documentRef, ResizeObserver: FakeResizeObserver });
    const source = layout();
    source.extensions = Object.assign({}, source.extensions, { facilityColumns: { version: 1, columns: [{
        columnId: 'col-a', label: 'Column A', shape: 'rectangle', center: { x: 5, z: 5 }, widthMeters: 0.4,
        depthMeters: 0.4, rotationDegrees: 0, heightMeters: 6, baseElevation: 0, appearance: { color: '#336699' },
        footprint: [{ x: 4.8, z: 4.8 }, { x: 5.2, z: 4.8 }, { x: 5.2, z: 5.2 }, { x: 4.8, z: 5.2 }] }] } });
    top.setLayout(source);
    const node = () => host.findByAttribute('data-column-id', 'col-a')[0];
    assert.strictEqual(node().getAttribute('role'), 'button');
    assert.strictEqual(node().getAttribute('fill'), '#336699');
    assert.strictEqual(node().getAttribute('aria-label'), 'Column A');
    assert.strictEqual(node().getAttribute('aria-selected'), 'false');
    const order = node().parentNode.parentNode.children.map(child => child.getAttribute('data-layer'));
    assert.strictEqual(order.indexOf('columns'), order.indexOf('walls') + 1, order.join());
    assert.strictEqual(top.pick('col-a'), true);
    assert.strictEqual(top.getDiagnostics().selection, 'col-a');
    assert.strictEqual(node().getAttribute('aria-selected'), 'true');
    top.setSelection(null);
    const keyboard = top.svg.dispatch('keydown', { target: node(), key: 'Enter' });
    assert.strictEqual(keyboard.defaultPrevented, true);
    assert.strictEqual(top.getDiagnostics().selection, 'col-a');
    top.setLayout(source);  // still there: still selected
    assert.strictEqual(top.getDiagnostics().selection, 'col-a');
    top.setLayerVisibility({ walls: false });
    assert.strictEqual(host.findByAttribute('data-layer', 'columns').length, 0);
    top.setLayerVisibility({ walls: true });
    top.setLayout(layout());  // gone: no longer selected, and no empty layer
    assert.strictEqual(top.getDiagnostics().selection, null);
    assert.strictEqual(host.findByAttribute('data-layer', 'columns').length, 0);
    assert.strictEqual(top.pick('col-a'), false);
    top.dispose();
});

check('fit delegates to views and leaves authoritative layout byte-identical', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const source = layout();
    const before = JSON.stringify(source);
    const top = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
    });
    const peer = mockAdapter('peer');
    const controller = facility.createEditor(source, { adapters: [top, peer] });
    const results = controller.fit();
    assert.strictEqual(results.length, 2);
    assert.strictEqual(peer.fitCount, 1);
    assert.strictEqual(peer.fitFacilityCount, 1);
    assert.strictEqual(controller.fitLayout().length, 2);
    assert.strictEqual(peer.fitLayoutCount, 1);
    assert.strictEqual(controller.topView().length, 1);
    assert.strictEqual(peer.topViewCount, 1);
    assert.strictEqual(JSON.stringify(source), before);
    assert.strictEqual(JSON.stringify(controller.getState().layout), before);
    controller.dispose();
});

check('selection survives compatible layout replacement and clears when absent', () => {
    const peer = mockAdapter('peer');
    const controller = facility.createEditor(layout(), { adapters: [peer] });
    assert.strictEqual(controller.select('pl-machine'), true);
    const compatible = layout();
    compatible.displayName = 'Updated label';
    controller.setLayout(compatible);
    assert.strictEqual(controller.getState().selectedPlacementId, 'pl-machine');
    controller.setLayout(layout([placement('pl-rack', 'asset-rack', 9, 6)]));
    assert.strictEqual(controller.getState().selectedPlacementId, null);
    assert.strictEqual(controller.select('pl-missing'), false);
    controller.dispose();
});

check('twenty mount and dispose cycles leave no observers or DOM residue', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    for (let index = 0; index < 20; index += 1) {
        const adapter = facility.createTopPlanAdapter(host, {
            id: 'top-' + index,
            document: documentRef,
            ResizeObserver: FakeResizeObserver,
        });
        const controller = facility.createEditor(layout(), { adapters: [adapter] });
        assert.strictEqual(host.children.length, 1);
        assert.strictEqual(FakeResizeObserver.activeObservations, 1);
        controller.dispose();
        controller.dispose();
        assert.strictEqual(host.children.length, 0);
        assert.strictEqual(FakeResizeObserver.activeObservations, 0);
    }
    assert.strictEqual(FakeResizeObserver.instances.size, 20);
});

check('twenty suspend and resume cycles reuse one plan observer', () => {
    FakeResizeObserver.reset();
    const { host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        ResizeObserver: FakeResizeObserver,
    });
    adapter.setLayout(layout());
    for (let index = 0; index < 20; index += 1) {
        assert.strictEqual(adapter.suspend(), true);
        assert.strictEqual(adapter.getDiagnostics().suspended, true);
        assert.strictEqual(FakeResizeObserver.activeObservations, 0);
        assert.strictEqual(adapter.resume(), true);
        assert.strictEqual(adapter.getDiagnostics().suspended, false);
        assert.strictEqual(FakeResizeObserver.activeObservations, 1);
    }
    assert.strictEqual(FakeResizeObserver.instances.size, 1);
    adapter.dispose();
    assert.strictEqual(FakeResizeObserver.activeObservations, 0);
});

check('degraded 2D-only mode operates without Three or WebGL', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const top = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
    });
    const controller = facility.createEditor({ layout: layout(), adapters: [top] });
    assert.strictEqual(controller.select('pl-machine'), true);
    assert.strictEqual(controller.fit().length, 1);
    const state = controller.getState();
    assert.strictEqual(state.diagnostics.mountedViews, 1);
    assert.strictEqual(state.diagnostics.views[0].type, 'top-plan');
    assert.deepStrictEqual(
        state.diagnostics.views[0].placementIds,
        ['pl-machine', 'pl-rack']
    );
    controller.dispose();
});

check('rendering is demand-driven and resize performs one bounded render', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
    });
    adapter.setLayout(layout());
    const idleCount = adapter.getDiagnostics().renderCount;
    assert.strictEqual(adapter.getDiagnostics().renderCount, idleCount);
    host.clientWidth = 800;
    Array.from(FakeResizeObserver.instances)[0].trigger();
    assert.strictEqual(adapter.getDiagnostics().renderCount, idleCount + 1);
    assert.strictEqual(
        fs.readFileSync(MODULE_PATH, 'ascii').includes('requestAnimationFrame'),
        false
    );
    adapter.dispose();
});

check('controller diagnostics report mounted views observers renders and selection', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const top = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
    });
    const controller = facility.createEditor(layout(), { adapters: [top] });
    controller.select('pl-rack');
    const state = controller.getState();
    assert.strictEqual(state.selection.kind, 'placement');
    assert.strictEqual(state.selection.placementId, 'pl-rack');
    assert.strictEqual(state.diagnostics.mountedViews, 1);
    assert.strictEqual(state.diagnostics.observerCount, 1);
    assert.ok(state.diagnostics.renderCount >= 2);
    assert.strictEqual(state.diagnostics.selection, 'pl-rack');
    controller.dispose();
    const disposed = controller.getState();
    assert.strictEqual(disposed.disposed, true);
    assert.strictEqual(disposed.diagnostics.mountedViews, 0);
    assert.strictEqual(disposed.diagnostics.observerCount, 0);
});

check('controller suspension pauses every view and resumes without reconstruction', () => {
    const first = mockAdapter('first');
    const second = mockAdapter('second');
    const controller = facility.createEditor({
        layout: layout(),
        adapters: [first, second],
    });
    assert.strictEqual(controller.suspend(), true);
    assert.strictEqual(controller.suspend(), false);
    assert.strictEqual(controller.getState().suspended, true);
    assert.strictEqual(controller.getState().diagnostics.mountedViews, 0);
    assert.deepStrictEqual(controller.fit(), []);
    assert.strictEqual(controller.resume(), true);
    assert.strictEqual(controller.resume(), false);
    assert.strictEqual(controller.getState().suspended, false);
    assert.strictEqual(controller.getState().diagnostics.mountedViews, 2);
    controller.dispose();
});

check('controller drives Three-style scene and selection contracts by stable ID', () => {
    const scenes = [];
    const selections = [];
    const three = {
        id: 'three-view',
        type: 'three',
        selectionHandler: null,
        setSelectionHandler(handler) { this.selectionHandler = handler; },
        setScene(value) {
            scenes.push(value);
            return Promise.resolve({ status: 'ready' });
        },
        setSelection(value) { selections.push(value); },
        getDiagnostics() {
            return {
                id: this.id,
                type: this.type,
                mounted: true,
                observerCount: 0,
                renderCount: scenes.length,
                selection: selections[selections.length - 1] || null,
            };
        },
        dispose() {},
    };
    const catalog = [{ assetId: 'asset-machine', marker: 'catalog' }];
    const controller = facility.createEditor({
        layout: layout(),
        assetCatalog: catalog,
        adapters: [three],
    });
    assert.strictEqual(scenes.length, 1);
    assert.deepStrictEqual(scenes[0].assetCatalog, catalog);
    assert.strictEqual(
        controller.getState().diagnostics.pendingViewUpdates,
        1
    );
    three.selectionHandler('pl-machine');
    assert.strictEqual(controller.getState().selectedPlacementId, 'pl-machine');
    assert.strictEqual(selections[selections.length - 1], 'pl-machine');
    controller.dispose();
});

check('ready clears resolved asynchronous view updates', async () => {
    let resolveScene;
    const three = {
        setSelectionHandler() {},
        setScene() {
            return new Promise((resolve) => {
                resolveScene = resolve;
            });
        },
        setSelection() {},
        getDiagnostics() {
            return { mounted: true };
        },
        dispose() {},
    };
    const controller = facility.createEditor({
        layout: layout(),
        adapters: [three],
    });
    assert.strictEqual(
        controller.getState().diagnostics.pendingViewUpdates,
        1
    );
    resolveScene({ status: 'ready' });
    const state = await controller.ready();
    assert.strictEqual(state.diagnostics.pendingViewUpdates, 0);
    controller.dispose();
});

check('plan authoring projection preserves world intent through pan zoom and layout updates',
    () => {
        const { host } = makeHost();
        const adapter = facility.createTopPlanAdapter(host, {
            ResizeObserver: FakeResizeObserver,
            getSize: () => ({ width: 640, height: 360 }),
        });
        adapter.setLayout(layout());
        adapter.fit();

        const intended = { x: 3, y: 0, z: 2 };
        const machineElement = host.findByAttribute(
            'data-placement-id',
            'pl-machine'
        )[0];
        const initialDetailLevel = machineElement.getAttribute(
            'data-card-detail-level'
        );
        const firstClient = adapter.worldToClient(intended);
        const firstRoundTrip = adapter.clientToWorld({
            clientX: firstClient.x,
            clientY: firstClient.y,
        });
        assert(Math.abs(firstRoundTrip.x - intended.x) < 1e-9);
        assert(Math.abs(firstRoundTrip.z - intended.z) < 1e-9);

        adapter.panByPixels(87, -41);
        assert.strictEqual(
            host.findByAttribute('data-placement-id', 'pl-machine')[0],
            machineElement
        );
        assert.ok(machineElement.parentNode.getAttribute('transform'));
        const pannedClient = adapter.worldToClient(intended);
        assert.notDeepStrictEqual(pannedClient, firstClient);
        adapter.zoomAt({
            clientX: pannedClient.x,
            clientY: pannedClient.y,
        }, 1.75);
        assert.strictEqual(
            host.findByAttribute('data-placement-id', 'pl-machine')[0],
            machineElement
        );
        assert.notStrictEqual(
            machineElement.getAttribute('data-card-detail-level'),
            'body'
        );
        assert.notStrictEqual(
            machineElement.getAttribute('data-card-detail-level'),
            initialDetailLevel
        );
        const zoomedDetailLevel = machineElement.getAttribute(
            'data-card-detail-level'
        );
        assert.strictEqual(
            machineElement.findByAttribute(
                'data-card-content', 'compact'
            )[0].getAttribute('display'),
            zoomedDetailLevel === 'compact' ? 'inline' : 'none'
        );
        assert.strictEqual(
            machineElement.findByAttribute(
                'data-card-content', 'full'
            )[0].getAttribute('display'),
            zoomedDetailLevel === 'full' ? 'inline' : 'none'
        );
        const zoomRoundTrip = adapter.clientToWorld({
            clientX: pannedClient.x,
            clientY: pannedClient.y,
        });
        assert(Math.abs(zoomRoundTrip.x - intended.x) < 1e-9);
        assert(Math.abs(zoomRoundTrip.z - intended.z) < 1e-9);

        const projectionBefore = adapter.getDiagnostics().projection;
        adapter.setLayout(layout([
            placement('pl-machine', 'asset-machine', 4, 2),
            placement('pl-rack', 'asset-rack', 10, 6),
        ]));
        assert.deepStrictEqual(adapter.getDiagnostics().projection, projectionBefore);

        const hits = adapter.resolveMarquee({
            start: { x: 2, z: 1 },
            end: { x: 4, z: 3 },
        });
        assert(hits.includes('pl-machine'));
        adapter.setGhostPlacement({
            assetId: 'asset-machine',
            assetDefinitionRevision: 'f'.repeat(64),
            worldPosition: { x: 5, y: 0, z: 4 },
            valid: true,
        });
        assert.strictEqual(adapter.getDiagnostics().ghostActive, true);
        assert.strictEqual(
            host.findByAttribute('data-facility-ghost', 'asset-machine').length,
            1
        );
        adapter.setGhostPlacement(null);
        assert.strictEqual(adapter.getDiagnostics().ghostActive, false);
        adapter.dispose();
    });

check('top plan shows proposal footprints and original positions without picking them',
    () => {
        FakeResizeObserver.reset();
        const { documentRef, host } = makeHost();
        const adapter = facility.createTopPlanAdapter(host, {
            document: documentRef,
            ResizeObserver: FakeResizeObserver,
            assetBounds: {
                'asset-machine': { width: 2, depth: 1 },
                'asset-rack': { width: 3, depth: 1.2 },
            },
        });
        const saved = layout();
        const proposed = layout([
            placement('pl-machine', 'asset-machine', 20, 2),
            placement('pl-new', 'asset-rack', 15, 6),
        ]);
        proposed.routes[0].centerline[1] = { x: 12, y: 0, z: 4 };
        const savedBefore = JSON.stringify(saved);
        const proposedBefore = JSON.stringify(proposed);
        adapter.setLayout(proposed);
        assert.strictEqual(adapter.setProposalPreview({
            active: true,
            newPlacementIds: ['pl-new'],
            movedPlacementIds: ['pl-machine'],
            removedPlacementIds: ['pl-rack'],
            changedRouteIds: ['rt-material'],
            beforeRoutes: [saved.routes[0]],
            proposedRoutes: [proposed.routes[0]],
            beforePlacements: [
                saved.placements[0],
                saved.placements[1],
            ],
            proposedPlacements: [
                proposed.placements[0],
                proposed.placements[1],
            ],
        }), true);
        const moved = host.findByAttribute(
            'data-proposal-state',
            'moved'
        )[0];
        const added = host.findByAttribute(
            'data-proposal-state',
            'new'
        )[0];
        assert.ok(moved);
        assert.ok(added);
        assert.strictEqual(moved.getAttribute('pointer-events'), 'none');
        assert.strictEqual(added.getAttribute('role'), 'img');
        assert.strictEqual(
            host.findByAttribute(
                'data-proposal-before-id',
                'pl-machine'
            ).length,
            1
        );
        assert.strictEqual(
            host.findByAttribute(
                'data-proposal-before-state',
                'removed'
            ).length,
            1
        );
        assert.strictEqual(
            host.findByAttribute(
                'data-proposal-move-id',
                'pl-machine'
            ).length,
            1
        );
        assert.strictEqual(
            host.findByAttribute(
                'data-proposal-route-state',
                'changed'
            ).length,
            1
        );
        assert.strictEqual(
            host.findByAttribute(
                'data-proposal-route-state',
                'proposed'
            ).length,
            1
        );
        const diagnostics = adapter.getDiagnostics();
        assert.strictEqual(diagnostics.proposalPreviewActive, true);
        assert.strictEqual(diagnostics.proposalBeforeCount, 2);
        assert.strictEqual(diagnostics.proposalNewCount, 1);
        assert.strictEqual(diagnostics.proposalMovedCount, 1);
        assert.ok(diagnostics.projection.minX <= 2);
        assert.ok(diagnostics.projection.maxX >= 21);
        assert.strictEqual(JSON.stringify(saved), savedBefore);
        assert.strictEqual(JSON.stringify(proposed), proposedBefore);

        assert.strictEqual(adapter.setProposalPreview(null), true);
        assert.strictEqual(
            host.findByAttribute('data-proposal-state', 'moved').length,
            0
        );
        assert.strictEqual(
            host.findByAttribute(
                'data-proposal-before-id',
                'pl-machine'
            ).length,
            0
        );
        assert.strictEqual(
            adapter.getDiagnostics().proposalPreviewActive,
            false
        );
        adapter.dispose();
    });

check('top plan paths toggle without removing the activity presentation', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(layout());
    adapter.setActivityPresentation({
        scenario: {
            scenarioId: 'fas-lean-motion',
            actors: [],
            leanMotion: {
                operatorPaths: [{
                    pathId: 'operator-one',
                    centerline: [
                        { x: 2, z: 2 },
                        { x: 8, z: 2 },
                        { x: 8, z: 6 },
                        { x: 2, z: 2 },
                    ],
                }],
                pedestrianConnections: [{
                    connectionId: 'connection-one',
                    centerline: [
                        { x: 5, z: 1 },
                        { x: 8, z: 2 },
                    ],
                }],
                assistanceGates: [{
                    gateId: 'gate-one',
                    position: { x: 8, z: 2 },
                }],
                materialHandoffs: [{
                    handoffId: 'handoff-one',
                    centerline: [
                        { x: 1, z: 1 },
                        { x: 5, z: 1 },
                    ],
                }],
                fifoPoints: [{
                    pointId: 'fifo-one',
                    position: { x: 1, z: 1 },
                }],
            },
        },
        actorPayloads: {},
    });
    assert.strictEqual(
        host.findByAttribute('data-lean-motion-kind', 'operator_path').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute(
            'data-lean-motion-kind',
            'pedestrian_connection'
        ).length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-lean-motion-kind', 'assistance_gate').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-lean-motion-kind', 'material_handoff').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-lean-motion-kind', 'fifo_point').length,
        1
    );

    assert.strictEqual(adapter.setActivityPathsVisible(false), false);
    assert.strictEqual(
        host.findByAttribute('data-lean-motion-kind', 'operator_path').length,
        0
    );
    assert.strictEqual(
        host.findByAttribute(
            'data-lean-motion-kind',
            'pedestrian_connection'
        ).length,
        0
    );
    assert.strictEqual(
        host.findByAttribute('data-lean-motion-kind', 'assistance_gate').length,
        0
    );
    assert.strictEqual(
        host.findByAttribute('data-lean-motion-kind', 'material_handoff').length,
        0
    );
    assert.strictEqual(
        host.findByAttribute('data-lean-motion-kind', 'fifo_point').length,
        0
    );
    assert.strictEqual(
        host.findByAttribute('data-layer', 'activity-playback').length,
        1
    );

    assert.strictEqual(adapter.setActivityPathsVisible(true), true);
    assert.strictEqual(
        host.findByAttribute('data-lean-motion-kind', 'operator_path').length,
        1
    );
    adapter.dispose();
});

check('top plan renders v3 navigation paths from motion packages by actor class', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(layout());
    adapter.setActivityPresentation({
        scenario: {
            schemaVersion: 'facility-activity-scenario-v7',
            scenarioId: 'fas-navigation-plan',
            actors: [{
                actorId: 'actor-navigation-plan',
                actorType: 'operator',
                placementId: 'pl-machine',
                motionPackageId: 'fmp-navigation-plan',
            }],
            leanMotion: {
                operatorPaths: [],
                pedestrianConnections: [],
                assistanceGates: [],
                materialHandoffs: [],
                fifoPoints: [],
            },
        },
        actorPayloads: {
            'fmp-navigation-plan': {
                package: {
                    movement: {
                        journeySolutionId: 'njs-navigation-plan',
                        poses: [
                            { x: 2, z: 2 },
                            { x: 8, z: 2 },
                            { x: 2, z: 2 },
                        ],
                    },
                },
                actorProfile: {
                    footprint: [
                        { x: -0.3, z: -0.25 },
                        { x: 0.3, z: -0.25 },
                        { x: 0.3, z: 0.25 },
                        { x: -0.3, z: 0.25 },
                    ],
                },
            },
        },
    });
    assert.strictEqual(
        host.findByAttribute(
            'data-navigation-activity-actor-type',
            'operator'
        ).length,
        1
    );
    adapter.updateActivitySnapshot({
        scenarioId: 'fas-navigation-plan',
        actors: [{
            actorId: 'actor-navigation-plan',
            visible: true,
            pose: { x: 5, z: 2, heading: 0, distanceMeters: 3 },
        }],
    });
    const marker = host.findByAttribute(
        'data-activity-actor-id',
        'actor-navigation-plan'
    )[0];
    assert.strictEqual(marker.getAttribute('data-activity-distance-meters'), '3');
    assert.strictEqual(
        adapter.setActivityPathTypeVisible('operator', false),
        false
    );
    assert.strictEqual(
        host.findByAttribute(
            'data-navigation-activity-actor-type',
            'operator'
        ).length,
        0
    );
    assert.strictEqual(
        host.findByAttribute(
            'data-activity-actor-id',
            'actor-navigation-plan'
        ).length,
        1
    );
    adapter.dispose();
});

check('top plan renders all Packaging cycle legs with semantic path styles', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(layout());
    const phases = [
        ['carry_in', 'fmp-carry-in', '#2563eb', null],
        ['carry_out', 'fmp-carry-out', '#d97706', null],
        ['return_empty', 'fmp-return-empty', '#059669', '9 6'],
    ];
    const actorPayloads = {};
    phases.forEach(function (entry, index) {
        actorPayloads[entry[1]] = {
            package: {
                movement: {
                    journeySolutionId: 'njs-' + entry[0],
                    poses: [
                        { x: 2 + index, z: 2 + index },
                        { x: 4 + index, z: 2 + index },
                    ],
                },
            },
            actorProfile: { footprint: [] },
        };
    });
    adapter.setActivityPresentation({
        scenario: {
            schemaVersion: 'facility-activity-scenario-v7',
            scenarioId: 'fas-packaging-plan',
            actors: [{
                actorId: 'actor-packaging-plan',
                actorType: 'operator',
                placementId: 'pl-machine',
                motionPackageId: 'fmp-carry-in',
                cycleMotionPackageIds: phases.map(item => item[1]),
                loopMode: 'closed_path',
            }],
            leanMotion: {
                operatorPaths: [],
                pedestrianConnections: [],
                assistanceGates: [],
                materialHandoffs: [],
                fifoPoints: [],
            },
        },
        actorPayloads,
        candidatePresentation: {
            handoffs: [],
            programEvidence: [{
                actorPlacementId: 'pl-machine',
                pathSegments: phases.map(item => ({
                    phase: item[0],
                    motionPackageId: item[1],
                })),
            }],
        },
    });

    phases.forEach(function (entry) {
        const line = host.findByAttribute(
            'data-navigation-activity-path-phase',
            entry[0]
        )[0];
        assert(line);
        assert.strictEqual(line.getAttribute('stroke'), entry[2]);
        assert.strictEqual(line.getAttribute('stroke-dasharray'), entry[3]);
    });
    assert.strictEqual(
        host.findByAttribute(
            'data-navigation-activity-actor-id',
            'actor-packaging-plan'
        ).length,
        3
    );
    adapter.dispose();
});

check('top plan renders Inspection A-B-C and dashed return paths', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(layout());
    const phases = [
        ['inspection_pick', 'fmp-inspection-pick', '#2563eb', null],
        ['inspection_place', 'fmp-inspection-place', '#2563eb', null],
        ['return_empty', 'fmp-inspection-return', '#059669', '9 6'],
    ];
    const actorPayloads = {};
    phases.forEach(function (entry, index) {
        actorPayloads[entry[1]] = {
            package: {
                movement: {
                    journeySolutionId: 'njs-' + entry[0],
                    poses: [
                        { x: 2 + index, z: 2 + index },
                        { x: 4 + index, z: 2 + index },
                    ],
                },
            },
            actorProfile: { footprint: [] },
        };
    });
    adapter.setActivityPresentation({
        scenario: {
            schemaVersion: 'facility-activity-scenario-v7',
            scenarioId: 'fas-inspection-plan',
            actors: [{
                actorId: 'actor-inspection-plan',
                actorType: 'operator',
                placementId: 'pl-machine',
                motionPackageId: 'fmp-inspection-pick',
                cycleMotionPackageIds: phases.map(item => item[1]),
                loopMode: 'closed_path',
            }],
            leanMotion: {
                operatorPaths: [],
                pedestrianConnections: [],
                assistanceGates: [],
                materialHandoffs: [],
                fifoPoints: [],
            },
        },
        actorPayloads,
        candidatePresentation: {
            handoffs: [],
            programEvidence: [{
                actorPlacementId: 'pl-machine',
                pathSegments: phases.map(item => ({
                    phase: item[0],
                    motionPackageId: item[1],
                })),
            }],
        },
    });

    phases.forEach(function (entry) {
        const line = host.findByAttribute(
            'data-navigation-activity-path-phase',
            entry[0]
        )[0];
        assert(line);
        assert.strictEqual(line.getAttribute('stroke'), entry[2]);
        assert.strictEqual(line.getAttribute('stroke-dasharray'), entry[3]);
    });
    assert.strictEqual(
        host.findByAttribute(
            'data-navigation-activity-actor-id',
            'actor-inspection-plan'
        ).length,
        3
    );
    adapter.dispose();
});

check('top plan borrows an existing operator without rendering a duplicate', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(layout([
        placement('pl-existing-operator', 'asset-operator', 4, 3),
    ]));
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-existing-operator').length,
        1
    );

    adapter.setActivityPresentation({
        scenario: {
            scenarioId: 'fas-existing-operator',
            actors: [{
                actorId: 'actor-existing-operator',
                actorType: 'operator',
                placementId: 'pl-existing-operator',
                motionPackageId: 'fmp-existing-operator',
            }],
            leanMotion: {
                operatorPaths: [],
                pedestrianConnections: [],
                assistanceGates: [],
                materialHandoffs: [],
                fifoPoints: [],
            },
        },
        actorPayloads: {
            'fmp-existing-operator': {
                vehicleProfile: {
                    footprint: [
                        { x: -0.3, z: -0.25 },
                        { x: 0.3, z: -0.25 },
                        { x: 0.3, z: 0.25 },
                        { x: -0.3, z: 0.25 },
                    ],
                },
            },
        },
    });
    adapter.updateActivitySnapshot({
        scenarioId: 'fas-existing-operator',
        actors: [{
            actorId: 'actor-existing-operator',
            visible: true,
            pose: { x: 6, z: 3, heading: 0, distanceMeters: 2 },
        }],
    });
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-existing-operator').length,
        0
    );
    assert.strictEqual(
        host.findByAttribute(
            'data-activity-placement-id',
            'pl-existing-operator'
        ).length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-activity-borrowed-placement', 'true').length,
        1
    );

    adapter.clearActivityPresentation();
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-existing-operator').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute(
            'data-activity-placement-id',
            'pl-existing-operator'
        ).length,
        0
    );
    adapter.dispose();
});

check('top plan isolates invalid manual segments and keeps actor visibility independent', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(layout([
        placement('pl-navigation-operator', 'asset-operator', 4, 3),
    ]));
    adapter.setNavigationAuthoringPreview({
        actorPlacementId: 'pl-navigation-operator',
        actorClass: 'pedestrian',
        points: [
            { x: 4, z: 3 },
            { x: 8, z: 3 },
            { x: 12, z: 5 },
        ],
        selectedPointIndex: 1,
        validationStatus: 'invalid',
        validation: { invalidSegmentIndexes: [1] },
        pathsVisible: true,
        pose: { x: 6, z: 3, heading: 0, normalizedTime: 0.25 },
    });
    assert.strictEqual(
        host.findByAttribute('data-navigation-invalid-segment', '1').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute(
            'data-navigation-preview-actor',
            'pl-navigation-operator'
        ).length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-navigation-operator').length,
        1
    );
    adapter.setNavigationPathsVisible(false);
    assert.strictEqual(
        host.findByAttribute('data-navigation-invalid-segment', '1').length,
        0
    );
    assert.strictEqual(
        host.findByAttribute(
            'data-navigation-preview-actor',
            'pl-navigation-operator'
        ).length,
        1
    );
    adapter.setNavigationAuthoringPreview(null);
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-navigation-operator').length,
        1
    );
    adapter.dispose();
});

check('top plan draws the lighting coverage over the floor and its markings, under the equipment, its dark spots on top', () => {
    FakeResizeObserver.reset();
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(layout());
    assert.strictEqual(host.findByAttribute('data-layer', 'light-coverage').length, 0);
    assert.strictEqual(adapter.setLightCoverage({ image: 'data:image/png;base64,AAAA', opacity: 0.8,
        minX: 0, minZ: 0, maxX: 20, maxZ: 10, spots: [{ number: 1, x: 5.5, z: 4.5,
            rings: [[{ x: 2, z: 2 }, { x: 9, z: 2 }, { x: 9, z: 7 }, { x: 2, z: 7 }]] }] }), true);
    const svg = host.findByAttribute('data-layer', 'light-coverage')[0].parentNode;
    const order = svg.children.map(layer => layer.getAttribute('data-layer'));
    assert.ok(order.indexOf('zones') < order.indexOf('light-coverage'), order.join());
    assert.ok(order.indexOf('floor-markings') < order.indexOf('light-coverage'), order.join());
    assert.ok(order.indexOf('light-coverage') < order.indexOf('placements'), order.join());
    assert.strictEqual(order[order.length - 1], 'light-coverage-spots', 'the outlines over everything');
    assert.strictEqual(host.findByAttribute('data-layer', 'light-coverage')[0].getAttribute('pointer-events'), 'none');
    const image = host.findByAttribute('data-light-coverage', 'grid')[0];
    const projection = adapter.projection;
    assert.strictEqual(Number(image.getAttribute('x')), projection.offsetX + (0 - projection.minX) * projection.scale);
    assert.strictEqual(Number(image.getAttribute('y')), projection.offsetY + (projection.maxZ - 10) * projection.scale);
    assert.strictEqual(Number(image.getAttribute('width')), 20 * projection.scale);
    assert.strictEqual(Number(image.getAttribute('height')), 10 * projection.scale);
    assert.strictEqual(image.getAttribute('opacity'), '0.8');
    const outlines = host.findByAttribute('data-light-coverage-spot', '1');
    assert.deepStrictEqual(outlines.map(path => path.getAttribute('stroke')), ['#000000', '#ffffff']);
    assert.ok(/^M[0-9. ]+(L[0-9. ]+){3}Z$/.test(outlines[1].getAttribute('d')), outlines[1].getAttribute('d'));
    assert.strictEqual(host.findByAttribute('data-light-coverage-label', '1')[0].textContent, '1');
    adapter.setLightCoverage(null);
    assert.strictEqual(host.findByAttribute('data-layer', 'light-coverage').length, 0);
    assert.strictEqual(host.findByAttribute('data-layer', 'light-coverage-spots').length, 0);
    adapter.dispose();
});

check('top plan draws an imported floor plan above the floor and under the zones, its picks on top', () => {
    FakeResizeObserver.reset();
    const floorPlan = require(path.join(ROOT, 'static', 'facility_layout_floor_plan.js'));
    const { documentRef, host } = makeHost();
    const adapter = facility.createTopPlanAdapter(host, {
        document: documentRef,
        ResizeObserver: FakeResizeObserver,
        worldBounds: { minX: 0, minZ: 0, maxX: 40, maxZ: 30 },
        getSize: () => ({ width: 900, height: 650 }),
    });
    adapter.setLayout(layout());
    const geometry = { origin: [1000, 2000], entities: [
        { id: 'e1', layer: 'L1', type: 'LINE', closed: false, points: [[0, 0], [10000, 0]] }] };
    const reference = { importId: 'fpi-' + 'a'.repeat(32), geometrySha256: 'c'.repeat(64), opacity: 0.4,
        layers: [{ layerId: 'L1', visible: true, role: 'reference' }],
        alignment: { sourceOrigin: { u: 1000, v: 2000 }, metersPerDrawingUnit: 0.001, rotationDegrees: 0,
            translationMeters: { x: 2, z: 3 } } };
    const underlay = { key: floorPlan.contentKey(reference), reference, geometry, picking: true,
        markers: [{ x: 2, z: 3, label: 'A', kind: 'drawing' }] };
    assert.strictEqual(adapter.setFloorPlanUnderlay(underlay), true);
    const layer = host.findByAttribute('data-layer', 'floor-plan')[0];
    const order = layer.parentNode.children.map(child => child.getAttribute('data-layer'));
    assert.ok(order.indexOf('floor-surfaces') < order.indexOf('floor-plan'), order.join());
    assert.ok(order.indexOf('floor-plan') < order.indexOf('zones'), order.join());
    assert.strictEqual(order[order.length - 1], 'floor-plan-markers', order.join());
    assert.strictEqual(layer.getAttribute('pointer-events'), 'none');
    assert.strictEqual(layer.getAttribute('opacity'), '0.4');
    const content = layer.children[0];
    assert.strictEqual(content.getAttribute('transform'), 'matrix('
        + floorPlan.screenMatrix(reference.alignment, geometry.origin, adapter.projection).join(' ') + ')');
    const projection = adapter.projection;
    const at = { x: projection.offsetX + (2 - projection.minX) * projection.scale,
        y: projection.offsetY + (projection.maxZ - 3) * projection.scale };
    const marker = host.findByAttribute('data-floor-plan-marker', 'A')[0];
    assert.strictEqual(marker.getAttribute('transform'), 'translate(' + at.x + ' ' + at.y + ')');
    const hover = host.findByAttribute('data-floor-plan-hover', 'true')[0];
    assert.strictEqual(hover.getAttribute('visibility'), 'hidden');
    adapter.setFloorPlanHover({ x: 2, z: 3, snapped: true });
    assert.deepStrictEqual([hover.getAttribute('visibility'), hover.getAttribute('data-snapped'),
        hover.getAttribute('transform')], ['visible', 'true', 'translate(' + at.x + ' ' + at.y + ') scale(1)']);
    // Zooming keeps the picks the same size on screen until the plan is drawn again.
    assert.strictEqual(adapter.zoomAt({ clientX: at.x, clientY: at.y }, 2), true);
    assert.strictEqual(marker.getAttribute('transform'), 'translate(' + at.x + ' ' + at.y + ') scale(0.5)');
    assert.strictEqual(hover.getAttribute('transform'), 'translate(' + at.x + ' ' + at.y + ') scale(0.5)');
    const picked = adapter.planPointAt({ clientX: at.x, clientY: at.y });
    assert.ok(Math.abs(picked.x - 2) < 1e-9 && Math.abs(picked.z - 3) < 1e-9, JSON.stringify(picked));
    assert.strictEqual(adapter.planScale(), projection.scale * 2);
    adapter.setFloorPlanOpacity(0.8);
    assert.strictEqual(layer.getAttribute('opacity'), '0.8');
    // Drawn again (picks done): the drawing itself is not rebuilt.
    adapter.setFloorPlanUnderlay(Object.assign({}, underlay, { markers: [], picking: false }));
    assert.strictEqual(host.findByAttribute('data-layer', 'floor-plan')[0].children[0], content);
    assert.strictEqual(host.findByAttribute('data-layer', 'floor-plan-markers').length, 0);
    adapter.setFloorPlanUnderlay(null);
    assert.strictEqual(host.findByAttribute('data-layer', 'floor-plan').length, 0);
    adapter.dispose();
});

check('a new asset catalog reaches the plan through the controller, which draws the new asset at its size (BS2)',
    () => {
        FakeResizeObserver.reset();
        const { documentRef, host } = makeHost();
        const input = layout([placement('pl-new', 'asset-new', 4, 4)]);
        const plan = facility.createTopPlanAdapter(host, { document: documentRef, ResizeObserver: FakeResizeObserver });
        const scenes = [];
        const three = { id: 'three', type: 'three', mounted: true, setScene(scene) { scenes.push(scene); },
            setSelectionHandler() {}, setSelection() {}, getDiagnostics() { return {}; }, dispose() {} };
        const controller = facility.createEditor({ layout: input, assetCatalog: [], adapters: [plan, three] });
        const width = () => {
            const points = host.findByAttribute('class', 'ip-flw-plan-card-body')[0].getAttribute('points')
                .split(' ').map(value => Number(value.split(',')[0]));
            return Math.max(...points) - Math.min(...points);
        };
        const before = width();
        const entry = { assetId: 'asset-new', assetDefinitionRevision: input.placements[0].assetDefinitionRevision,
            width: 6, depth: 1 };
        controller.setAssetCatalog([entry]);
        assert.deepStrictEqual(plan.options.assetCatalog, [entry]);
        assert.deepStrictEqual(scenes[scenes.length - 1].assetCatalog, [entry]);
        assert.ok(width() > 2 * before, `${width()} vs ${before}`);
        controller.dispose();
    });

Promise.all(pendingChecks).then(() => {
    process.stdout.write(
        `${checks}/${checks} facility layout editor checks passed\n`
    );
}).catch((error) => {
    console.error(error && error.stack ? error.stack : error);
    process.exitCode = 1;
});
