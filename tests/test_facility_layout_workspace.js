'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const MODULE_PATH = path.join(ROOT, 'static', 'facility_layout_workspace.js');
const workspaceModule = require(MODULE_PATH);

let checks = 0;
async function check(name, fn) {
    await fn();
    checks += 1;
    process.stdout.write(`PASS ${name}\n`);
}

function clone(value) {
    if (value === undefined) return undefined;
    return JSON.parse(JSON.stringify(value));
}

function selectorMatcher(selector) {
    const attribute = selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
    if (attribute) {
        return element => {
            const value = element.getAttribute(attribute[1]);
            return value !== null && (
                attribute[2] === undefined || value === attribute[2]
            );
        };
    }
    const className = selector.match(/^\.([A-Za-z0-9_-]+)$/);
    if (className) {
        return element => String(element.className || '')
            .split(/\s+/).includes(className[1]);
    }
    return element => String(element.nodeName || '').toLowerCase()
        === selector.toLowerCase();
}

class FakeElement {
    constructor(documentRef, name) {
        this.ownerDocument = documentRef;
        this.nodeName = String(name).toUpperCase();
        this.parentNode = null;
        this.children = [];
        this.attributes = {};
        this.listeners = new Map();
        this.className = '';
        this.textContent = '';
        this.hidden = false;
        this.disabled = false;
        this.value = '';
        this.clientWidth = 900;
        this.clientHeight = 600;
        this.isContentEditable = false;
        this.capturedPointers = new Set();
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
        const text = String(value);
        this.attributes[name] = text;
        if (name === 'class') this.className = text;
        if (name === 'value') this.value = text;
        if (name === 'disabled') this.disabled = true;
        if (name === 'hidden') this.hidden = true;
        if (name === 'draggable') this.draggable = text === 'true';
    }

    getAttribute(name) {
        if (name === 'class' && this.className) return this.className;
        return Object.prototype.hasOwnProperty.call(this.attributes, name)
            ? this.attributes[name]
            : null;
    }

    removeAttribute(name) {
        delete this.attributes[name];
        if (name === 'disabled') this.disabled = false;
        if (name === 'hidden') this.hidden = false;
    }

    addEventListener(type, handler) {
        if (!this.listeners.has(type)) this.listeners.set(type, new Set());
        this.listeners.get(type).add(handler);
        FakeElement.listenerCount += 1;
    }

    removeEventListener(type, handler) {
        const handlers = this.listeners.get(type);
        if (handlers && handlers.delete(handler)) FakeElement.listenerCount -= 1;
    }

    contains(node) {
        let current = node;
        while (current) {
            if (current === this) return true;
            current = current.parentNode;
        }
        return false;
    }

    setPointerCapture(pointerId) {
        this.capturedPointers.add(Number(pointerId));
    }

    hasPointerCapture(pointerId) {
        return this.capturedPointers.has(Number(pointerId));
    }

    releasePointerCapture(pointerId) {
        this.capturedPointers.delete(Number(pointerId));
    }

    getBoundingClientRect() {
        return {
            left: 0,
            top: 0,
            width: this.clientWidth,
            height: this.clientHeight,
        };
    }

    descendants() {
        const result = [];
        this.children.forEach(child => {
            result.push(child);
            result.push(...child.descendants());
        });
        return result;
    }

    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }

    querySelectorAll(selector) {
        const match = selectorMatcher(selector);
        return this.descendants().filter(match);
    }

    dispatch(type, input) {
        const source = input || {};
        const event = Object.assign({
            type,
            target: this,
            currentTarget: this,
            relatedTarget: null,
            ctrlKey: false,
            metaKey: false,
            shiftKey: false,
            defaultPrevented: false,
            propagationStopped: false,
            preventDefault() { this.defaultPrevented = true; },
            stopPropagation() { this.propagationStopped = true; },
        }, source);
        if (!event.target) event.target = this;
        let current = this;
        while (current) {
            event.currentTarget = current;
            const handlers = current.listeners.get(type);
            if (handlers) Array.from(handlers).forEach(handler => handler(event));
            if (event.propagationStopped) break;
            current = current.parentNode;
        }
        return event;
    }
}
FakeElement.listenerCount = 0;

class FakeDocument {
    createElement(name) {
        return new FakeElement(this, name);
    }
}

class FakeDataTransfer {
    constructor() {
        this.data = {};
        this.effectAllowed = '';
        this.dropEffect = '';
    }

    setData(type, value) {
        this.data[type] = String(value);
    }

    getData(type) {
        return this.data[type] || '';
    }
}

function placement(id, assetId, x, z, mode) {
    return {
        placementId: id,
        assetId,
        assetDefinitionRevision: `revision-${assetId}`,
        transform: {
            position: { x, y: 0, z },
            quaternion: { x: 0, y: 0, z: 0, w: 1 },
            scale: 1,
        },
        positionMode: mode || 'auto',
        snapRelationship: null,
        metadata: { instanceLabel: id },
    };
}

function zone(id) {
    return {
        zoneId: id,
        zoneType: 'workcell',
        label: 'Assembly cell',
        boundary: [
            { x: 0, z: 0 },
            { x: 4, z: 0 },
            { x: 4, z: 3 },
            { x: 0, z: 3 },
        ],
        floorElevation: 0,
        anchors: [],
        evidence: [],
    };
}

function layout() {
    return {
        schemaVersion: 1,
        layoutId: 'fl-workspace',
        displayName: 'Workspace test',
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
        zones: [zone('zn-a')],
        placements: [
            placement('pl-a', 'asset-rack', 1, 1, 'auto'),
            placement('pl-b', 'asset-forklift', 5, 2, 'manual'),
        ],
        routes: [],
        utilityNetworks: [],
        processBindings: [],
        dismissedSuggestions: [],
        createdAt: '2026-07-29T00:00:00Z',
        updatedAt: '2026-07-29T00:00:00Z',
    };
}

function selectedRecord(document, id) {
    return document.placements.find(item => item.placementId === id)
        || document.zones.find(item => item.zoneId === id);
}

class FakeSession {
    constructor() {
        this.listeners = new Set();
        this.calls = [];
        this.idSequence = 0;
        this.state = {
            apiVersion: 1,
            loaded: true,
            baseRevision: 'rev-1',
            baseLayout: layout(),
            layout: layout(),
            operations: [],
            history: [],
            historyCursor: 0,
            canUndo: false,
            canRedo: false,
            dirty: false,
            busy: false,
            conflict: null,
            selection: [],
            camera: null,
            ghostPlacement: null,
            lastError: null,
        };
    }

    _notify() {
        const snapshot = this.getState();
        this.listeners.forEach(listener => listener(snapshot));
    }

    _gesture(name) {
        this.state.dirty = true;
        this.state.history.push({ label: name, operationCount: 1, applied: true });
        this.state.historyCursor = this.state.history.length;
        this.state.canUndo = true;
        this.state.canRedo = false;
        this._notify();
        return Promise.resolve(this.getState());
    }

    getState() {
        return clone(this.state);
    }

    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    select(id, options) {
        this.calls.push(['select', id, clone(options || {})]);
        if (!selectedRecord(this.state.layout, id)) return this.getState();
        if (options && options.toggle) {
            this.state.selection = this.state.selection.includes(id)
                ? this.state.selection.filter(item => item !== id)
                : this.state.selection.concat([id]);
        } else if (options && options.additive) {
            if (!this.state.selection.includes(id)) this.state.selection.push(id);
        } else {
            this.state.selection = [id];
        }
        this._notify();
        return this.getState();
    }

    selectMany(ids, options) {
        this.calls.push(['selectMany', clone(ids), clone(options || {})]);
        const valid = ids.filter(id => selectedRecord(this.state.layout, id));
        this.state.selection = options && options.additive
            ? Array.from(new Set(this.state.selection.concat(valid)))
            : Array.from(new Set(valid));
        this._notify();
        return this.getState();
    }

    clearSelection() {
        this.calls.push(['clearSelection']);
        this.state.selection = [];
        this._notify();
        return this.getState();
    }

    beginGhostPlacement(asset) {
        this.calls.push(['beginGhostPlacement', clone(asset)]);
        this.state.ghostPlacement = {
            assetId: asset.assetId,
            assetDefinitionRevision: asset.assetDefinitionRevision,
            worldPosition: null,
            valid: true,
            metadata: clone(asset.metadata || {}),
        };
        this._notify();
        return clone(this.state.ghostPlacement);
    }

    updateGhostPlacement(worldPosition, valid) {
        this.calls.push(['updateGhostPlacement', clone(worldPosition), valid]);
        this.state.ghostPlacement.worldPosition = clone(worldPosition);
        this.state.ghostPlacement.valid = valid !== false;
        this._notify();
        return clone(this.state.ghostPlacement);
    }

    cancelGhostPlacement() {
        this.calls.push(['cancelGhostPlacement']);
        this.state.ghostPlacement = null;
        this._notify();
        return this.getState();
    }

    commitGhostPlacement() {
        this.calls.push(['commitGhostPlacement']);
        const ghost = clone(this.state.ghostPlacement);
        this.idSequence += 1;
        const id = `pl-new-${this.idSequence}`;
        this.state.layout.placements.push(placement(
            id,
            ghost.assetId,
            ghost.worldPosition.x,
            ghost.worldPosition.z,
            'manual'
        ));
        this.state.layout.placements[
            this.state.layout.placements.length - 1
        ].assetDefinitionRevision = ghost.assetDefinitionRevision;
        this.state.selection = [id];
        this.state.ghostPlacement = null;
        return this._gesture('Place asset');
    }

    moveSelected(delta) {
        this.calls.push(['moveSelected', clone(delta)]);
        this.state.selection.forEach(id => {
            const value = this.state.layout.placements.find(
                item => item.placementId === id
            );
            if (!value) return;
            value.transform.position.x += delta.x || 0;
            value.transform.position.y += delta.y || 0;
            value.transform.position.z += delta.z || 0;
            if (value.positionMode === 'auto') value.positionMode = 'manual';
        });
        return this._gesture('Move selection');
    }

    rotateSelected90(turns) {
        this.calls.push(['rotateSelected90', turns]);
        const q = workspaceModule.quarterTurnQuaternion(
            turns === undefined ? 1 : turns
        );
        this.state.selection.forEach(id => {
            const value = this.state.layout.placements.find(
                item => item.placementId === id
            );
            if (value) value.transform.quaternion = clone(q);
        });
        return this._gesture('Rotate selection');
    }

    duplicateSelected(offset) {
        this.calls.push(['duplicateSelected', clone(offset)]);
        const source = this.state.layout.placements.find(
            item => item.placementId === this.state.selection[0]
        );
        if (source) {
            this.idSequence += 1;
            const duplicate = clone(source);
            duplicate.placementId = `pl-copy-${this.idSequence}`;
            duplicate.transform.position.x += offset.x;
            duplicate.transform.position.z += offset.z;
            duplicate.positionMode = 'manual';
            this.state.layout.placements.push(duplicate);
            this.state.selection = [duplicate.placementId];
        }
        return this._gesture('Duplicate selection');
    }

    deleteSelected() {
        this.calls.push(['deleteSelected']);
        const selected = new Set(this.state.selection);
        this.state.layout.placements = this.state.layout.placements.filter(
            item => !selected.has(item.placementId)
        );
        this.state.layout.zones = this.state.layout.zones.filter(
            item => !selected.has(item.zoneId)
        );
        this.state.selection = [];
        return this._gesture('Delete selection');
    }

    lockSelected() {
        this.calls.push(['lockSelected']);
        this.state.selection.forEach(id => {
            const value = this.state.layout.placements.find(
                item => item.placementId === id
            );
            if (value) value.positionMode = 'locked';
        });
        return this._gesture('Lock selection');
    }

    unlockSelected() {
        this.calls.push(['unlockSelected']);
        this.state.selection.forEach(id => {
            const value = this.state.layout.placements.find(
                item => item.placementId === id
            );
            if (value) value.positionMode = 'manual';
        });
        return this._gesture('Unlock selection');
    }

    createRectangleZone(start, end, options) {
        this.calls.push(['createRectangleZone', clone(start), clone(end), clone(options)]);
        this.idSequence += 1;
        const id = `zn-new-${this.idSequence}`;
        this.state.layout.zones.push({
            zoneId: id,
            zoneType: options.zoneType,
            label: options.label,
            boundary: [
                { x: Math.min(start.x, end.x), z: Math.min(start.z, end.z) },
                { x: Math.max(start.x, end.x), z: Math.min(start.z, end.z) },
                { x: Math.max(start.x, end.x), z: Math.max(start.z, end.z) },
                { x: Math.min(start.x, end.x), z: Math.max(start.z, end.z) },
            ],
            floorElevation: 0,
            anchors: [],
            evidence: [],
        });
        this.state.selection = [id];
        return this._gesture('Create rectangle zone');
    }

    createPolygonZone(points, options) {
        this.calls.push(['createPolygonZone', clone(points), clone(options)]);
        this.idSequence += 1;
        const id = `zn-poly-${this.idSequence}`;
        this.state.layout.zones.push({
            zoneId: id,
            zoneType: options.zoneType,
            label: options.label,
            boundary: clone(points),
            floorElevation: 0,
            anchors: [],
            evidence: [],
        });
        this.state.selection = [id];
        return this._gesture('Create polygon zone');
    }

    editZoneDimensions(id, dimensions) {
        this.calls.push(['editZoneDimensions', id, clone(dimensions)]);
        const value = this.state.layout.zones.find(item => item.zoneId === id);
        const center = workspaceModule.zoneDimensions(value).center;
        const halfWidth = dimensions.width / 2;
        const halfDepth = dimensions.depth / 2;
        value.boundary = [
            { x: center.x - halfWidth, z: center.z - halfDepth },
            { x: center.x + halfWidth, z: center.z - halfDepth },
            { x: center.x + halfWidth, z: center.z + halfDepth },
            { x: center.x - halfWidth, z: center.z + halfDepth },
        ];
        return this._gesture('Resize zone');
    }

    undo() {
        this.calls.push(['undo']);
        this.state.canUndo = false;
        this.state.canRedo = true;
        this._notify();
        return Promise.resolve(this.getState());
    }

    redo() {
        this.calls.push(['redo']);
        this.state.canUndo = true;
        this.state.canRedo = false;
        this._notify();
        return Promise.resolve(this.getState());
    }

    save() {
        this.calls.push(['save']);
        this.state.dirty = false;
        this.state.history = [];
        this.state.historyCursor = 0;
        this.state.canUndo = false;
        this._notify();
        return Promise.resolve({ state: this.getState(), receipt: { revision: 'rev-2' } });
    }
}

class FakeAdapter {
    constructor(type) {
        this.type = type;
        this.selectionHandler = null;
        this.selections = [];
        this.layouts = [];
        this.mounted = false;
        this.disposed = false;
        this.invalidations = 0;
        this.camera = null;
        this.ghost = null;
    }

    mount(host) {
        this.host = host;
        this.mounted = true;
    }

    setSelectionHandler(handler) {
        this.selectionHandler = handler;
    }

    setSelection(value) {
        this.selections.push(clone(value));
    }

    setSelections(value) {
        this.selections.push(clone(value));
    }

    setLayout(value) {
        this.layouts.push(clone(value));
    }

    setGhostPlacement(value) {
        this.ghost = clone(value);
        return true;
    }

    clientToWorld(event) {
        return event && event.world || { x: 0, y: 0, z: 0 };
    }

    worldPointOnFloor(event) {
        return event && event.world || null;
    }

    panByPixels(x, y) {
        this.lastPan = { x, y };
        return true;
    }

    zoomAt(event, factor) {
        this.lastZoom = { event, factor };
        return true;
    }

    resolveMarquee() {
        return ['pl-a'];
    }

    setScene(input) {
        this.layouts.push(clone(input.layout));
        return Promise.resolve();
    }

    fit() {
        this.fitCount = (this.fitCount || 0) + 1;
        return { fitted: true };
    }

    invalidate() {
        this.invalidations += 1;
    }

    getDiagnostics() {
        return { mounted: this.mounted };
    }

    emitSelection(id) {
        if (this.selectionHandler) this.selectionHandler(id);
    }

    dispose() {
        this.disposed = true;
    }
}

class FakeController {
    constructor(adapters, initialCatalog) {
        this.adapters = adapters;
        this.layouts = [];
        this.catalogs = [clone(initialCatalog || [])];
        this.selections = [];
        this.fitCount = 0;
        this.disposeCount = 0;
    }

    setAssetCatalog(value) {
        this.catalogs.push(clone(value));
    }

    setLayout(value) {
        this.layouts.push(clone(value));
        this.adapters.forEach(adapter => {
            if (adapter.setLayout) adapter.setLayout(value);
            else if (adapter.setScene) adapter.setScene({ layout: value });
        });
    }

    select(id) {
        this.selections.push(id);
        this.adapters.forEach(adapter => adapter.setSelection(id));
        return true;
    }

    clearSelection() {
        this.selections.push(null);
        this.adapters.forEach(adapter => adapter.setSelection(null));
    }

    fit() {
        this.fitCount += 1;
        this.adapters.forEach(adapter => adapter.fit());
    }

    dispose() {
        this.disposeCount += 1;
        this.adapters.forEach(adapter => adapter.dispose());
    }
}

function catalog() {
    return [
        {
            assetId: 'asset-rack',
            assetDefinitionRevision: 'revision-asset-rack',
            displayName: 'Pallet Rack',
            category: 'Storage',
        },
        {
            assetId: 'asset-forklift',
            assetDefinitionRevision: 'revision-asset-forklift',
            displayName: 'Electric Forklift',
            category: 'Material Handling',
        },
        {
            assetId: 'asset-machine',
            assetDefinitionRevision: 'revision-asset-machine',
            displayName: 'CNC Mill',
            category: 'Machines',
        },
    ];
}

function fixture(options) {
    const documentRef = new FakeDocument();
    const root = documentRef.createElement('div');
    const session = new FakeSession();
    const top = new FakeAdapter('top-plan');
    top.mounted = true;
    const three = options && options.noThree ? null : new FakeAdapter('three');
    let controller = null;
    const layoutRuntime = {
        createTopPlanAdapter(host) {
            top.host = host;
            return top;
        },
        createEditor(config) {
            controller = new FakeController(config.adapters, config.assetCatalog);
            return controller;
        },
    };
    let projectedPoint = { x: 12.24, y: 0, z: -3.26 };
    const workspace = workspaceModule.createWorkspace({
        root,
        session,
        layoutRuntime,
        threeAdapter: three,
        assetCatalog: catalog(),
        gridSize: 0.5,
        eventToWorld(event) {
            return event && event.world
                ? event.world
                : projectedPoint;
        },
        marqueeResolver: options && options.marqueeResolver,
        keyboardPlacementPoint: options && options.keyboardPlacementPoint,
        createDragSessionId: () => 'drag-stable-001',
    });
    return {
        documentRef,
        root,
        session,
        top,
        three,
        get controller() { return controller; },
        workspace,
        setProjectedPoint(value) { projectedPoint = value; },
    };
}

function toolbarButton(data, command) {
    return data.root.querySelector(`[data-command="${command}"]`);
}

function assetRow(data, assetId) {
    return data.root.querySelector(`[data-asset-id="${assetId}"]`);
}

async function main() {
    await check('exports UMD and CommonJS API with pure helpers', async () => {
        assert.strictEqual(workspaceModule.API_VERSION, 1);
        assert.strictEqual(typeof workspaceModule.createWorkspace, 'function');
        const source = fs.readFileSync(MODULE_PATH, 'utf8');
        const browser = {};
        vm.runInNewContext(source, { globalThis: browser });
        assert.strictEqual(browser.InspectorProFacilityWorkspace.API_VERSION, 1);
        assert.strictEqual(
            typeof browser.InspectorProFacilityWorkspace.createWorkspace,
            'function'
        );
    });

    await check('drag payload is stable, minimal, and strictly parseable', async () => {
        const text = workspaceModule.createAssetDragPayload({
            assetId: 'asset-rack',
            assetDefinitionRevision: 'revision-rack',
            ignored: 'not serialized',
        }, 'drag-17');
        assert.deepStrictEqual(JSON.parse(text), {
            assetId: 'asset-rack',
            assetDefinitionRevision: 'revision-rack',
            dragSessionId: 'drag-17',
        });
        assert.deepStrictEqual(workspaceModule.parseAssetDragPayload(text), {
            assetId: 'asset-rack',
            assetDefinitionRevision: 'revision-rack',
            dragSessionId: 'drag-17',
        });
        assert.strictEqual(workspaceModule.parseAssetDragPayload('{bad'), null);
        assert.strictEqual(workspaceModule.parseAssetDragPayload(
            JSON.stringify({ assetId: 'x' })
        ), null);
    });

    await check('grid snap and quarter-turn quaternion are deterministic', async () => {
        assert.deepStrictEqual(
            workspaceModule.snapWorldPoint({ x: 1.24, y: 4, z: -1.26 }, 0.5),
            { x: 1, y: 4, z: -1.5 }
        );
        const q = workspaceModule.quarterTurnQuaternion(1);
        assert.ok(Math.abs(q.y - Math.SQRT1_2) < 1e-12);
        assert.ok(Math.abs(q.w - Math.SQRT1_2) < 1e-12);
        assert.deepStrictEqual(
            workspaceModule.quarterTurnQuaternion(4),
            { x: 0, y: 0, z: 0, w: 1 }
        );
    });

    await check('builds accessible CAD workspace, categorized tree, and P6 warning',
        async () => {
            const data = fixture();
            assert.strictEqual(
                data.root.getAttribute('aria-label'),
                'Facility layout workspace'
            );
            assert.strictEqual(
                data.root.querySelector('[role="toolbar"]').getAttribute('aria-label'),
                'Facility layout tools'
            );
            assert.ok(data.root.textContent === '' || data.root.children.length > 0);
            assert.strictEqual(data.root.querySelectorAll('.ip-flw-asset-group').length, 3);
            assert.ok(data.root.querySelector('.ip-flw-validation-notice')
                .textContent.includes('arrives in P6'));
            assert.strictEqual(
                data.root.querySelector('[data-view="plan"]').getAttribute('aria-selected'),
                'true'
            );
            assert.strictEqual(
                toolbarButton(data, 'delete').getAttribute('aria-label'),
                'Delete'
            );
            assert.strictEqual(data.workspace.threeTab.disabled, false);
            assert.strictEqual(
                toolbarButton(data, 'select').getAttribute('aria-pressed'),
                'true'
            );
            assert.strictEqual(
                toolbarButton(data, 'delete').getAttribute('aria-pressed'),
                null
            );
            data.workspace.destroy();
        });

    await check('asset search filters categorized rows without changing catalog',
        async () => {
            const data = fixture();
            const search = data.root.querySelector('input');
            search.value = 'forklift';
            search.dispatch('input');
            assert.strictEqual(data.root.querySelectorAll('.ip-flw-asset-row').length, 1);
            assert.strictEqual(
                data.root.querySelector('.ip-flw-asset-row').getAttribute('data-asset-id'),
                'asset-forklift'
            );
            assert.strictEqual(data.workspace.assetCatalog.length, 3);
            data.workspace.destroy();
        });

    await check('drop remains world-stable after arbitrary camera changes and delegates once',
        async () => {
            const data = fixture();
            const row = assetRow(data, 'asset-rack');
            const transfer = new FakeDataTransfer();
            row.dispatch('dragstart', { dataTransfer: transfer });
            const payload = JSON.parse(transfer.getData(workspaceModule.ASSET_MIME));
            assert.deepStrictEqual(payload, {
                assetId: 'asset-rack',
                assetDefinitionRevision: 'revision-asset-rack',
                dragSessionId: 'drag-stable-001',
            });
            data.top.camera = { panX: 700, panY: -420, zoom: 0.18 };
            data.three.camera = { x: 80, y: 60, z: -120, zoom: 2.6 };
            data.workspace.viewportStack.dispatch('dragover', {
                dataTransfer: transfer,
                world: { x: 12.24, y: 0, z: -3.26 },
            });
            assert.deepStrictEqual(
                data.session.getState().ghostPlacement.worldPosition,
                { x: 12, y: 0, z: -3.5 }
            );
            data.workspace.viewportStack.dispatch('drop', {
                dataTransfer: transfer,
                world: { x: 12.24, y: 0, z: -3.26 },
            });
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'commitGhostPlacement').length,
                1
            );
            const created = data.session.getState().layout.placements.find(
                item => item.placementId === 'pl-new-1'
            );
            assert.deepStrictEqual(created.transform.position, { x: 12, y: 0, z: -3.5 });
            assert.strictEqual(data.session.getState().ghostPlacement, null);
            assert.strictEqual(data.workspace.ghostOverlay.hidden, true);
            data.workspace.destroy();
        });

    await check('ghost cancel is transient and never commits layout', async () => {
        const data = fixture();
        const transfer = new FakeDataTransfer();
        assetRow(data, 'asset-machine').dispatch('dragstart', { dataTransfer: transfer });
        data.workspace.viewportStack.dispatch('dragover', {
            dataTransfer: transfer,
            world: { x: 8, y: 0, z: 7 },
        });
        const before = data.session.getState().layout.placements.length;
        data.workspace.viewportStack.dispatch('dragleave', {
            dataTransfer: transfer,
            relatedTarget: null,
        });
        assert.strictEqual(data.session.getState().ghostPlacement, null);
        assert.strictEqual(data.session.getState().layout.placements.length, before);
        assert.strictEqual(
            data.session.calls.filter(call => call[0] === 'commitGhostPlacement').length,
            0
        );
        data.workspace.destroy();
    });

    await check('Ctrl selection is additive and propagates across controller views',
        async () => {
            const data = fixture();
            data.workspace.handleViewSelection('pl-a');
            data.workspace.handleViewSelection('pl-b', { ctrlKey: true });
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a', 'pl-b']);
            assert.deepStrictEqual(
                data.three.selections[data.three.selections.length - 1],
                ['pl-a', 'pl-b']
            );
            assert.strictEqual(
                data.controller.selections[data.controller.selections.length - 1],
                'pl-a'
            );
            data.workspace.handleViewSelection('pl-a', { ctrlKey: true });
            assert.deepStrictEqual(data.session.getState().selection, ['pl-b']);
            data.workspace.destroy();
        });

    await check('zones select directly without starting a marquee', async () => {
        const data = fixture();
        const target = data.documentRef.createElement('polygon');
        target.setAttribute('data-zone-id', 'zn-a');
        data.workspace.planView.appendChild(target);
        target.dispatch('pointerdown', {
            pointerId: 31,
            world: { x: 2, y: 0, z: 2 },
        });
        target.dispatch('pointerup', {
            pointerId: 31,
            world: { x: 2, y: 0, z: 2 },
        });
        assert.deepStrictEqual(data.session.getState().selection, ['zn-a']);
        assert.strictEqual(data.workspace.getState().session.history.length, 0);
        assert.strictEqual(
            data.session.calls.filter(call => call[0] === 'selectMany').length,
            0
        );
        data.workspace.destroy();
    });

    await check('plan marquee hook selects resolved IDs once with additive behavior',
        async () => {
            let resolverCalls = 0;
            const data = fixture({
                marqueeResolver(input) {
                    resolverCalls += 1;
                    assert.deepStrictEqual(input.start, { x: 0, y: 0, z: 0 });
                    assert.deepStrictEqual(input.end, { x: 6, y: 0, z: 4 });
                    return ['pl-a', 'pl-b'];
                },
            });
            data.workspace.planView.dispatch('pointerdown', {
                world: { x: 0, y: 0, z: 0 },
            });
            data.workspace.planView.dispatch('pointerup', {
                world: { x: 6, y: 0, z: 4 },
                ctrlKey: true,
            });
            assert.strictEqual(resolverCalls, 1);
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'selectMany').length,
                1
            );
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a', 'pl-b']);
            data.workspace.destroy();
        });

    await check('placement pointer move is one delegated gesture and marks auto manual',
        async () => {
            const data = fixture();
            const target = data.documentRef.createElement('polygon');
            target.setAttribute('data-placement-id', 'pl-a');
            data.workspace.planView.appendChild(target);
            target.dispatch('pointerdown', {
                world: { x: 1, y: 0, z: 1 },
            });
            target.dispatch('pointermove', {
                world: { x: 3.2, y: 0, z: 0.2 },
            });
            target.dispatch('pointerup', {
                world: { x: 3.2, y: 0, z: 0.2 },
            });
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(call => call[0] === 'moveSelected');
            assert.strictEqual(calls.length, 1);
            assert.deepStrictEqual(calls[0][1], { x: 2, y: 0, z: -1 });
            const moved = data.session.getState().layout.placements.find(
                item => item.placementId === 'pl-a'
            );
            assert.strictEqual(moved.positionMode, 'manual');
            data.workspace.destroy();
        });

    await check('pointer capture keeps a move gesture owned by the plan view',
        async () => {
            const data = fixture();
            const target = data.documentRef.createElement('polygon');
            target.setAttribute('data-placement-id', 'pl-a');
            data.workspace.planView.appendChild(target);
            target.dispatch('pointerdown', {
                pointerId: 42,
                world: { x: 1, y: 0, z: 1 },
            });
            assert.strictEqual(
                data.workspace.planView.hasPointerCapture(42),
                true
            );
            data.workspace.planView.dispatch('pointerup', {
                pointerId: 42,
                world: { x: 2, y: 0, z: 2 },
            });
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.workspace.planView.hasPointerCapture(42),
                false
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'moveSelected').length,
                1
            );
            data.workspace.destroy();
        });

    await check('dragging one member of a multi-selection moves the full selection once',
        async () => {
            const data = fixture();
            data.session.selectMany(['pl-a', 'pl-b']);
            const target = data.documentRef.createElement('polygon');
            target.setAttribute('data-placement-id', 'pl-a');
            data.workspace.planView.appendChild(target);
            target.dispatch('pointerdown', {
                world: { x: 1, y: 0, z: 1 },
            });
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a', 'pl-b']);
            target.dispatch('pointerup', {
                world: { x: 2, y: 0, z: 2 },
            });
            await data.workspace.whenIdle();
            const calls = data.session.calls.filter(call => call[0] === 'moveSelected');
            assert.strictEqual(calls.length, 1);
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a', 'pl-b']);
            assert.deepStrictEqual(data.top.selections[data.top.selections.length - 1],
                ['pl-a', 'pl-b']);
            data.workspace.destroy();
        });

    await check('toolbar commands delegate exactly once and Fit changes only view',
        async () => {
            const data = fixture();
            data.session.select('pl-a');
            const layoutBeforeFit = clone(data.session.getState().layout);
            await data.workspace.executeCommand('fit');
            assert.strictEqual(data.controller.fitCount, 1);
            assert.deepStrictEqual(data.session.getState().layout, layoutBeforeFit);
            for (const command of ['rotate', 'duplicate', 'lock', 'undo', 'redo', 'save']) {
                await data.workspace.executeCommand(command);
                await data.workspace.whenIdle();
            }
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'rotateSelected90').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'duplicateSelected').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'lockSelected').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'undo').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'redo').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'save').length,
                1
            );
            data.workspace.destroy();
        });

    await check('rectangle and polygon zone tools commit one gesture each', async () => {
        const data = fixture();
        await data.workspace.executeCommand('rectangle-zone');
        data.workspace.planView.dispatch('pointerdown', {
            world: { x: 1, y: 0, z: 1 },
        });
        data.workspace.planView.dispatch('pointerup', {
            world: { x: 5, y: 0, z: 4 },
        });
        await data.workspace.whenIdle();
        assert.strictEqual(
            data.session.calls.filter(call => call[0] === 'createRectangleZone').length,
            1
        );
        await data.workspace.executeCommand('polygon-zone');
        [
            { x: 0, y: 0, z: 0 },
            { x: 3, y: 0, z: 0 },
            { x: 2, y: 0, z: 2 },
        ].forEach(world => data.workspace.planView.dispatch('click', { world }));
        data.root.dispatch('keydown', {
            key: 'Enter',
            target: data.root,
        });
        await data.workspace.whenIdle();
        assert.strictEqual(
            data.session.calls.filter(call => call[0] === 'createPolygonZone').length,
            1
        );
        data.workspace.destroy();
    });

    await check('session updates controller and adapter selections return to session',
        async () => {
            const data = fixture();
            const initialLayoutCount = data.controller.layouts.length;
            data.session.select('pl-b');
            assert.strictEqual(data.controller.layouts.length, initialLayoutCount);
            assert.strictEqual(
                data.controller.selections[data.controller.selections.length - 1],
                'pl-b'
            );
            data.three.emitSelection('pl-a');
            assert.deepStrictEqual(data.session.getState().selection, ['pl-a']);
            assert.ok(data.controller.catalogs.length > 0);
            data.workspace.destroy();
        });

    await check('Plan and 3D segmented modes switch without framing scene state',
        async () => {
            const data = fixture();
            assert.strictEqual(data.workspace.getState().viewMode, 'plan');
            data.workspace.threeTab.dispatch('click');
            assert.strictEqual(data.workspace.getState().viewMode, '3d');
            assert.strictEqual(data.workspace.planView.hidden, true);
            assert.strictEqual(data.workspace.threeView.hidden, false);
            assert.strictEqual(data.three.invalidations, 1);
            data.workspace.planTab.dispatch('click');
            assert.strictEqual(data.workspace.getState().viewMode, 'plan');
            const noThree = fixture({ noThree: true });
            noThree.workspace.threeTab.dispatch('click');
            assert.strictEqual(noThree.workspace.getState().viewMode, 'plan');
            assert.strictEqual(noThree.workspace.threeTab.disabled, true);
            data.workspace.destroy();
            noThree.workspace.destroy();
        });

    await check('placement transform fields and zone dimensions delegate authoritative edits',
        async () => {
            const data = fixture();
            data.session.select('pl-a');
            const xInput = data.workspace.propertiesBody.querySelector(
                '[data-property="x"]'
            );
            xInput.value = '3.5';
            xInput.dispatch('change');
            await data.workspace.whenIdle();
            assert.deepStrictEqual(
                data.session.calls.filter(call => call[0] === 'moveSelected').pop()[1],
                { x: 2.5, y: 0, z: 0 }
            );
            const rotation = data.workspace.propertiesBody.querySelector(
                '[data-property="rotation"]'
            );
            rotation.value = '90';
            rotation.dispatch('change');
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'rotateSelected90').pop()[1],
                1
            );
            data.session.select('zn-a');
            const width = data.workspace.propertiesBody.querySelector(
                '[data-property="width"]'
            );
            const depth = data.workspace.propertiesBody.querySelector(
                '[data-property="depth"]'
            );
            width.value = '8';
            depth.value = '6';
            width.dispatch('change');
            await data.workspace.whenIdle();
            const zoneCall = data.session.calls.filter(
                call => call[0] === 'editZoneDimensions'
            ).pop();
            assert.deepStrictEqual(zoneCall.slice(1), ['zn-a', { width: 8, depth: 6 }]);
            data.workspace.destroy();
        });

    await check('keyboard shortcuts are accessible and ignore active form fields',
        async () => {
            const data = fixture();
            data.session.select('pl-a');
            data.root.dispatch('keydown', { key: 'r', target: data.root });
            data.root.dispatch('keydown', { key: 'l', target: data.root });
            data.root.dispatch('keydown', {
                key: 'z',
                ctrlKey: true,
                target: data.root,
            });
            data.root.dispatch('keydown', {
                key: 'y',
                ctrlKey: true,
                target: data.root,
            });
            data.root.dispatch('keydown', { key: 'f', target: data.root });
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'rotateSelected90').length,
                1
            );
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'lockSelected').length,
                1
            );
            assert.strictEqual(data.controller.fitCount, 1);
            const input = data.documentRef.createElement('input');
            data.root.dispatch('keydown', { key: 'Delete', target: input });
            await data.workspace.whenIdle();
            assert.strictEqual(
                data.session.calls.filter(call => call[0] === 'deleteSelected').length,
                0
            );
            data.workspace.destroy();
        });

    await check('Enter places the focused catalog asset at the plan center',
        async () => {
            const data = fixture({
                keyboardPlacementPoint: { x: 7.24, y: 0, z: -2.76 },
            });
            const row = assetRow(data, 'asset-machine');
            const event = row.dispatch('keydown', {
                key: 'Enter',
                target: row,
            });
            await data.workspace.whenIdle();
            assert.strictEqual(event.defaultPrevented, true);
            const commit = data.session.calls.filter(
                call => call[0] === 'commitGhostPlacement'
            );
            assert.strictEqual(commit.length, 1);
            const created = data.session.getState().layout.placements.find(
                item => item.placementId.startsWith('pl-new-')
            );
            assert.deepStrictEqual(
                created.transform.position,
                { x: 7, y: 0, z: -3 }
            );
            assert.strictEqual(data.session.getState().ghostPlacement, null);
            data.workspace.destroy();
        });

    await check('destroy removes listeners, subscription, adapters, and DOM exactly once',
        async () => {
            const baseline = FakeElement.listenerCount;
            const data = fixture();
            assert.ok(FakeElement.listenerCount > baseline);
            const controller = data.controller;
            const subscriptionCount = data.session.listeners.size;
            assert.strictEqual(subscriptionCount, 1);
            assert.strictEqual(data.workspace.destroy(), true);
            assert.strictEqual(data.workspace.destroy(), false);
            assert.strictEqual(data.session.listeners.size, 0);
            assert.strictEqual(controller.disposeCount, 1);
            assert.strictEqual(data.root.children.length, 0);
            assert.strictEqual(FakeElement.listenerCount, baseline);
            data.session.select('pl-a');
            assert.strictEqual(controller.disposeCount, 1);
        });

    process.stdout.write(`${checks}/${checks} facility layout workspace checks passed\n`);
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
