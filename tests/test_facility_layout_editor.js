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

    dispatch(type, target) {
        const handlers = this.listeners.get(type);
        if (handlers) {
            Array.from(handlers).forEach(handler => handler({
                type,
                target: target || this,
            }));
        }
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
        this.targets.add(target);
        FakeResizeObserver.activeObservations += 1;
    }

    disconnect() {
        if (this.disconnected) return;
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
        disposed: false,
        handler: null,
        setSelectionHandler(handler) { this.handler = handler; },
        setLayout(value) { this.layouts.push(value); },
        setSelection(value) { this.selections.push(value); },
        fit() { this.fitCount += 1; return { id: this.id }; },
        dispose() { this.disposed = true; },
        getDiagnostics() {
            return {
                id: this.id,
                type: this.type,
                mounted: !this.disposed,
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
    adapter.setLayout(layout());
    assert.strictEqual(host.children.length, 1);
    assert.strictEqual(host.findByAttribute('data-zone-id', 'zn-cell').length, 1);
    assert.strictEqual(host.findByAttribute('data-route-id', 'rt-material').length, 1);
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-machine').length,
        1
    );
    assert.strictEqual(
        host.findByAttribute('data-placement-id', 'pl-rack').length,
        1
    );
    assert.ok(adapter.getDiagnostics().renderCount >= 1);
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

Promise.all(pendingChecks).then(() => {
    process.stdout.write(
        `${checks}/${checks} facility layout editor checks passed\n`
    );
}).catch((error) => {
    console.error(error && error.stack ? error.stack : error);
    process.exitCode = 1;
});
