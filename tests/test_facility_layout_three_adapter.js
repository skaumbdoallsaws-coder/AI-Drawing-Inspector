'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const MODULE_PATH = path.join(
    ROOT,
    'static',
    'facility_layout_three_adapter.js'
);
const runtime = require(MODULE_PATH);

let nextUuid = 1;

class FakeEventTarget {
    constructor() {
        this.listeners = new Map();
    }

    addEventListener(type, handler) {
        if (!this.listeners.has(type)) this.listeners.set(type, new Set());
        this.listeners.get(type).add(handler);
    }

    removeEventListener(type, handler) {
        const handlers = this.listeners.get(type);
        if (handlers) handlers.delete(handler);
    }

    dispatch(type, fields) {
        const event = Object.assign({
            type,
            target: this,
            prevented: false,
            preventDefault() {
                this.prevented = true;
            },
        }, fields || {});
        const handlers = this.listeners.get(type);
        if (handlers) Array.from(handlers).forEach(handler => handler(event));
        return event;
    }

    listenerCount() {
        let count = 0;
        this.listeners.forEach(handlers => {
            count += handlers.size;
        });
        return count;
    }
}

class FakeElement extends FakeEventTarget {
    constructor(name) {
        super();
        this.name = name || 'element';
        this.parentNode = null;
        this.children = [];
        this.style = {};
        this.attributes = {};
        this.clientWidth = 800;
        this.clientHeight = 600;
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

    remove() {
        if (this.parentNode) this.parentNode.removeChild(this);
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }

    getBoundingClientRect() {
        return {
            left: 0,
            top: 0,
            width: this.clientWidth,
            height: this.clientHeight,
            right: this.clientWidth,
            bottom: this.clientHeight,
        };
    }
}

class FakeVector2 {
    constructor(x, y) {
        this.x = x || 0;
        this.y = y || 0;
    }
}

class FakeVector3 {
    constructor(x, y, z) {
        this.set(x || 0, y || 0, z || 0);
    }

    set(x, y, z) {
        this.x = x;
        this.y = y;
        this.z = z;
        return this;
    }

    clone() {
        return new FakeVector3(this.x, this.y, this.z);
    }
}

class FakeQuaternion {
    constructor(x, y, z, w) {
        this.set(x || 0, y || 0, z || 0, w === undefined ? 1 : w);
    }

    set(x, y, z, w) {
        this.x = x;
        this.y = y;
        this.z = z;
        this.w = w;
        return this;
    }

    clone() {
        return new FakeQuaternion(this.x, this.y, this.z, this.w);
    }
}

class FakeMatrix4 {
    constructor() {
        this.composed = null;
        this.multiplied = null;
    }

    compose(position, quaternion, scale) {
        this.composed = {
            position: { x: position.x, y: position.y, z: position.z },
            quaternion: {
                x: quaternion.x,
                y: quaternion.y,
                z: quaternion.z,
                w: quaternion.w,
            },
            scale: { x: scale.x, y: scale.y, z: scale.z },
        };
        return this;
    }

    multiplyMatrices(left, right) {
        this.multiplied = { left, right };
        this.composed = left.composed;
        return this;
    }

    clone() {
        const clone = new FakeMatrix4();
        clone.composed = this.composed
            ? JSON.parse(JSON.stringify(this.composed)) : null;
        clone.multiplied = this.multiplied;
        return clone;
    }
}

class FakeObject3D extends FakeEventTarget {
    constructor() {
        super();
        this.uuid = 'uuid-' + nextUuid;
        nextUuid += 1;
        this.isObject3D = true;
        this.children = [];
        this.parent = null;
        this.position = new FakeVector3();
        this.quaternion = new FakeQuaternion();
        this.scale = new FakeVector3(1, 1, 1);
        this.userData = {};
        this.matrixWorld = new FakeMatrix4();
        this.name = '';
    }

    add(child) {
        if (!child) return;
        if (child.parent) child.parent.remove(child);
        child.parent = this;
        this.children.push(child);
    }

    remove(child) {
        const index = this.children.indexOf(child);
        if (index >= 0) this.children.splice(index, 1);
        child.parent = null;
    }

    traverse(visitor) {
        visitor(this);
        this.children.slice().forEach(child => child.traverse(visitor));
    }

    updateMatrixWorld() {
        this.matrixWorld = new FakeMatrix4().compose(
            this.position,
            this.quaternion,
            this.scale
        );
        this.children.forEach(child => child.updateMatrixWorld(true));
    }

    clone(deep) {
        const clone = new FakeObject3D();
        clone.position = this.position.clone();
        clone.quaternion = this.quaternion.clone();
        clone.scale = this.scale.clone();
        clone.userData = Object.assign({}, this.userData);
        if (deep) this.children.forEach(child => clone.add(child.clone(true)));
        return clone;
    }
}

class FakeGroup extends FakeObject3D {}
class FakeScene extends FakeGroup {}

class FakeColor {
    constructor(value) {
        this.value = value === undefined ? 0 : value;
    }

    setHex(value) {
        this.value = value;
        return this;
    }

    getHex() {
        return this.value;
    }
}

class FakeGeometry {
    constructor(width, height, depth) {
        this.width = width;
        this.height = height;
        this.depth = depth;
        this.disposeCount = 0;
    }

    dispose() {
        this.disposeCount += 1;
        FakeGeometry.totalDisposed += 1;
    }
}
FakeGeometry.totalDisposed = 0;

class FakeMaterial {
    constructor(options) {
        this.options = Object.assign({}, options);
        this.userData = {};
        this.emissive = new FakeColor(0);
        this.emissiveIntensity = 0;
        this.disposeCount = 0;
        this.needsUpdate = false;
    }

    clone() {
        return new FakeMaterial(this.options);
    }

    dispose() {
        this.disposeCount += 1;
        FakeMaterial.totalDisposed += 1;
    }
}
FakeMaterial.totalDisposed = 0;

class FakeMesh extends FakeObject3D {
    constructor(geometry, material) {
        super();
        this.isMesh = true;
        this.geometry = geometry;
        this.material = material;
    }

    clone(deep) {
        const clone = new FakeMesh(this.geometry, this.material);
        clone.position = this.position.clone();
        clone.quaternion = this.quaternion.clone();
        clone.scale = this.scale.clone();
        clone.userData = Object.assign({}, this.userData);
        if (deep) this.children.forEach(child => clone.add(child.clone(true)));
        return clone;
    }
}

class FakeInstancedMesh extends FakeMesh {
    constructor(geometry, material, count) {
        super(geometry, material);
        this.isInstancedMesh = true;
        this.count = count;
        this.matrices = new Array(count);
        this.colors = new Array(count);
        this.instanceMatrix = { needsUpdate: false };
        this.instanceColor = { needsUpdate: false };
    }

    setMatrixAt(index, matrix) {
        this.matrices[index] = matrix;
    }

    setColorAt(index, color) {
        this.colors[index] = color.value;
    }

    computeBoundingBox() {}
    computeBoundingSphere() {}
}

class FakePerspectiveCamera extends FakeObject3D {
    constructor(fov, aspect, near, far) {
        super();
        this.isPerspectiveCamera = true;
        this.fov = fov;
        this.aspect = aspect;
        this.near = near;
        this.far = far;
        this.projectionUpdates = 0;
    }

    lookAt(x, y, z) {
        this.lookTarget = { x, y, z };
    }

    updateProjectionMatrix() {
        this.projectionUpdates += 1;
    }
}

class FakeLight extends FakeObject3D {}

class FakeRaycaster {
    setFromCamera(pointer, camera) {
        this.pointer = pointer;
        this.camera = camera;
        this.ray = {
            origin: { x: pointer.x * 10, y: 10, z: pointer.y * 10 },
            direction: { x: 0, y: -1, z: 0 },
        };
    }

    intersectObjects() {
        return FakeRaycaster.nextHits.slice();
    }
}
FakeRaycaster.nextHits = [];

class FakeRenderer {
    constructor() {
        this.domElement = new FakeElement('canvas');
        this.renderCount = 0;
        this.disposeCount = 0;
        this.forceContextLossCount = 0;
        this.renderLists = {
            dispose: () => {
                this.renderListsDisposed = true;
            },
        };
        FakeRenderer.instances.push(this);
    }

    setPixelRatio(value) {
        this.pixelRatio = value;
    }

    setSize(width, height) {
        this.size = { width, height };
        this.domElement.clientWidth = width;
        this.domElement.clientHeight = height;
    }

    render(scene, camera) {
        this.renderCount += 1;
        this.lastRender = { scene, camera };
    }

    dispose() {
        this.disposeCount += 1;
    }

    forceContextLoss() {
        this.forceContextLossCount += 1;
    }
}
FakeRenderer.instances = [];

class FakeControls extends FakeEventTarget {
    constructor(camera, canvas) {
        super();
        this.camera = camera;
        this.canvas = canvas;
        this.target = new FakeVector3();
        this.disposeCount = 0;
        FakeControls.instances.push(this);
    }

    update() {
        this.updateCount = (this.updateCount || 0) + 1;
    }

    dispose() {
        this.disposeCount += 1;
    }
}
FakeControls.instances = [];

class FakeResizeObserver {
    constructor(callback) {
        this.callback = callback;
        this.active = false;
        FakeResizeObserver.instances.push(this);
    }

    observe(host) {
        this.host = host;
        if (!this.active) {
            this.active = true;
            FakeResizeObserver.activeCount += 1;
        }
    }

    disconnect() {
        if (this.active) {
            this.active = false;
            FakeResizeObserver.activeCount -= 1;
        }
    }
}
FakeResizeObserver.instances = [];
FakeResizeObserver.activeCount = 0;

function createFrameScheduler() {
    let nextId = 1;
    const callbacks = new Map();
    return {
        request(callback) {
            const id = nextId;
            nextId += 1;
            callbacks.set(id, callback);
            return id;
        },
        cancel(id) {
            callbacks.delete(id);
        },
        flush() {
            const current = Array.from(callbacks.entries());
            callbacks.clear();
            current.forEach(([, callback]) => callback(16));
        },
        get pendingCount() {
            return callbacks.size;
        },
    };
}

function createThree() {
    return {
        Scene: FakeScene,
        Group: FakeGroup,
        Object3D: FakeObject3D,
        WebGLRenderer: FakeRenderer,
        PerspectiveCamera: FakePerspectiveCamera,
        HemisphereLight: FakeLight,
        DirectionalLight: FakeLight,
        Raycaster: FakeRaycaster,
        Vector2: FakeVector2,
        Vector3: FakeVector3,
        Quaternion: FakeQuaternion,
        Matrix4: FakeMatrix4,
        BoxGeometry: FakeGeometry,
        MeshStandardMaterial: FakeMaterial,
        MeshBasicMaterial: FakeMaterial,
        Mesh: FakeMesh,
        InstancedMesh: FakeInstancedMesh,
        Color: FakeColor,
        SRGBColorSpace: 'srgb',
    };
}

const REV_A = 'a'.repeat(64);
const REV_B = 'b'.repeat(64);

function transform(x, y, z, quaternion) {
    return {
        position: { x, y, z },
        quaternion: quaternion || { x: 0, y: 0, z: 0, w: 1 },
        scale: 1,
    };
}

function placement(id, assetId, revision, x, y, z, quaternion) {
    return {
        placementId: id,
        assetId,
        assetDefinitionRevision: revision,
        transform: transform(x, y, z, quaternion),
        positionMode: 'auto',
        snapRelationship: null,
        metadata: {},
    };
}

function asset(assetId, revision, bounds) {
    return {
        assetId,
        publishedAssetDefinitionRevision: revision,
        definition: {
            geometry: {
                aabb: bounds || {
                    minimum: { x: -1, y: 0, z: -0.5 },
                    maximum: { x: 1, y: 2, z: 0.5 },
                },
            },
        },
    };
}

function prototype(THREE, name) {
    const rootObject = new THREE.Group();
    rootObject.name = name;
    rootObject.add(new THREE.Mesh(
        new THREE.BoxGeometry(1, 1, 1),
        new THREE.MeshStandardMaterial({ color: 0x8899aa })
    ));
    return rootObject;
}

function fixture(options) {
    const scheduler = createFrameScheduler();
    const THREE = createThree();
    const host = new FakeElement('host');
    const adapter = runtime.createThreeAdapter(Object.assign({
        THREE,
        OrbitControls: FakeControls,
        ResizeObserver: FakeResizeObserver,
        requestAnimationFrame: callback => scheduler.request(callback),
        cancelAnimationFrame: id => scheduler.cancel(id),
        logger: { warn() {} },
    }, options || {}));
    return { THREE, host, adapter, scheduler };
}

function resetFakes() {
    FakeRenderer.instances.length = 0;
    FakeControls.instances.length = 0;
    FakeResizeObserver.instances.length = 0;
    FakeResizeObserver.activeCount = 0;
    FakeRaycaster.nextHits = [];
    FakeGeometry.totalDisposed = 0;
    FakeMaterial.totalDisposed = 0;
}

const tests = [];

function test(name, callback) {
    tests.push({ name, callback });
}

async function settleAsync(turns) {
    const count = Number.isInteger(turns) ? turns : 12;
    for (let index = 0; index < count; index += 1) {
        await Promise.resolve();
    }
}

test('exports the classic UMD global, CommonJS API, and complete adapter contract', () => {
    assert.strictEqual(typeof runtime.createThreeAdapter, 'function');
    assert.deepStrictEqual(
        Array.from(runtime.RESOLUTION_STAGES),
        ['manifest', 'footprint', 'proxy', 'overview', 'detail']
    );
    const source = fs.readFileSync(MODULE_PATH, 'ascii');
    const context = {
        globalThis: {},
        console: { warn() {} },
    };
    context.globalThis.globalThis = context.globalThis;
    vm.runInNewContext(source, context);
    assert.strictEqual(
        typeof context.globalThis.InspectorProFacilityThree.createThreeAdapter,
        'function'
    );

    const { adapter } = fixture();
    [
        'mount',
        'initialize',
        'setScene',
        'setSelection',
        'setSelectionHandler',
        'setGhostPlacement',
        'fit',
        'invalidate',
        'pick',
        'worldPointOnFloor',
        'getDiagnostics',
        'dispose',
    ].forEach(method => {
        assert.strictEqual(typeof adapter[method], 'function', method);
    });
});

test('resolves every asset progressively in the required deterministic order', async () => {
    const calls = [];
    const data = fixture({
        assetResolver: request => {
            calls.push(request.stage);
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            return prototype(data.THREE, request.stage);
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, 1, 0, 2),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    assert.deepStrictEqual(
        calls,
        ['manifest', 'footprint', 'proxy', 'overview', 'detail']
    );
    const diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.status, 'ready');
    assert.strictEqual(diagnostics.controlsActive, true);
    assert.ok(diagnostics.camera);
    assert.ok(diagnostics.camera.position);
    assert.strictEqual(diagnostics.representationGroups.length, 1);
    assert.strictEqual(
        diagnostics.representationGroups[0].representation,
        'detail'
    );
    assert.deepStrictEqual(
        diagnostics.loadTrace.filter(item => item.status === 'started')
            .map(item => item.stage),
        calls
    );
    data.adapter.dispose();
});

test('instances repeated exact revisions with stable placement identity and xyzw transforms', async () => {
    const data = fixture({
        assetResolver: request => {
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage === 'detail') {
                return prototype(data.THREE, 'detail');
            }
            return null;
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement(
                    'pl-z',
                    'asset-rack',
                    REV_A,
                    6,
                    0,
                    2,
                    { x: 0, y: 0.707106, z: 0, w: 0.707106 }
                ),
                placement('pl-a', 'asset-rack', REV_A, 2, 0, 2),
            ],
        },
        assetCatalog: [asset('asset-rack', REV_A)],
    });
    const diagnostics = data.adapter.getDiagnostics();
    const group = diagnostics.representationGroups[0];
    assert.strictEqual(group.instanced, true);
    assert.strictEqual(
        group.key,
        'asset-rack|' + REV_A + '|detail'
    );
    assert.deepStrictEqual(group.placementIds, ['pl-a', 'pl-z']);
    assert.deepStrictEqual(
        group.instanceMappings[0].placementIds,
        ['pl-a', 'pl-z']
    );

    const rootObject = FakeRenderer.instances.at(-1).lastRender
        ? FakeRenderer.instances.at(-1).lastRender.scene : null;
    data.scheduler.flush();
    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    let instances = null;
    scene.traverse(object => {
        if (object.isInstancedMesh) instances = object;
    });
    assert(instances);
    assert.strictEqual(instances.matrices[0].composed.position.x, 2);
    assert.strictEqual(instances.matrices[1].composed.position.x, 6);
    assert.strictEqual(
        instances.matrices[1].composed.quaternion.w,
        0.707106
    );
    assert.strictEqual(rootObject, null);

    data.adapter.setSelection('pl-z');
    assert.deepStrictEqual(instances.userData.selectedPlacementIds, ['pl-z']);
    FakeRaycaster.nextHits = [{
        object: instances,
        instanceId: 1,
        point: new FakeVector3(6, 1, 2),
    }];
    assert.deepStrictEqual(
        data.adapter.pick({ normalized: true, x: 0, y: 0 }),
        {
            placementId: 'pl-z',
            instanceId: 1,
            point: { x: 6, y: 1, z: 2 },
        }
    );
    let selectedFromPointer = null;
    data.adapter.setSelectionHandler(placementId => {
        selectedFromPointer = placementId;
    });
    FakeRenderer.instances.at(-1).domElement.dispatch(
        'pointerup',
        { clientX: 400, clientY: 300 }
    );
    assert.strictEqual(selectedFromPointer, 'pl-z');
    data.adapter.dispose();
});

test('keeps different definition revisions in separate render groups', async () => {
    const data = fixture({
        assetResolver: request => {
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage === 'overview') {
                return prototype(data.THREE, request.assetDefinitionRevision);
            }
            return null;
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-rack', REV_A, 0, 0, 0),
                placement('pl-b', 'asset-rack', REV_B, 3, 0, 0),
            ],
        },
        assetCatalog: [
            asset('asset-rack', REV_A),
            asset('asset-rack', REV_B),
        ],
    });
    const groups = data.adapter.getDiagnostics().representationGroups;
    assert.strictEqual(groups.length, 2);
    assert(groups.every(group => group.instanced === false));
    assert.deepStrictEqual(
        groups.map(group => group.assetDefinitionRevision).sort(),
        [REV_A, REV_B]
    );
    data.adapter.dispose();
});

test('Fit mutates only camera and controls while model and scene roots stay fixed', async () => {
    const data = fixture();
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, -4, 0, -2),
                placement('pl-b', 'asset-machine', REV_A, 8, 0, 6),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    const before = data.adapter.getDiagnostics().modelRootTransform;
    const renderer = FakeRenderer.instances.at(-1);
    data.scheduler.flush();
    const cameraBefore = Object.assign({}, renderer.lastRender.camera.position);
    assert.strictEqual(data.adapter.fit(), true);
    data.scheduler.flush();
    const after = data.adapter.getDiagnostics();
    assert.deepStrictEqual(after.modelRootTransform, before);
    assert.strictEqual(after.lastFit.rootUnchanged, true);
    assert.notDeepStrictEqual(
        Object.assign({}, renderer.lastRender.camera.position),
        cameraBefore
    );
    data.adapter.dispose();
});

test('Fit uses authoritative facility bounds even when the layout is empty', async () => {
    const data = fixture({
        worldBounds: {
            minX: 0,
            minZ: 0,
            maxX: 40,
            maxZ: 30,
            floorY: 0,
        },
    });
    data.adapter.mount(data.host);
    const controls = FakeControls.instances.at(-1);
    assert.strictEqual(controls.minPolarAngle, 0.03);
    assert.strictEqual(controls.maxPolarAngle, Math.PI / 2 - 0.03);
    await data.adapter.setScene({
        layout: { placements: [] },
        assetCatalog: [],
    });
    assert.strictEqual(data.adapter.fit(), true);
    data.scheduler.flush();
    const diagnostics = data.adapter.getDiagnostics();
    assert.deepStrictEqual(diagnostics.worldBounds, {
        minimum: { x: 0, y: 0, z: 0 },
        maximum: { x: 40, y: 0.01, z: 30 },
    });
    assert.deepStrictEqual(diagnostics.camera.target, {
        x: 20,
        y: 0,
        z: 15,
    });
    data.adapter.dispose();
});

test('facility-floor projection and transient ghost remain outside picking state', async () => {
    const data = fixture();
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, 0, 0, 0),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    assert.deepStrictEqual(
        data.adapter.worldPointOnFloor(
            { normalized: true, x: 0.2, y: -0.3 },
            0
        ),
        { x: 2, y: 0, z: -3 }
    );
    assert.strictEqual(data.adapter.setGhostPlacement({
        assetId: 'asset-machine',
        assetDefinitionRevision: REV_A,
        worldPosition: { x: 4, y: 0, z: 5 },
        valid: true,
    }), true);
    let diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.ghostActive, true);
    assert.strictEqual(diagnostics.placementCount, 1);
    data.scheduler.flush();
    let ghostCount = 0;
    FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => {
        if (object.userData && object.userData.facilityGhost) ghostCount += 1;
    });
    assert.strictEqual(ghostCount, 1);
    assert.strictEqual(data.adapter.setGhostPlacement(null), true);
    diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.ghostActive, false);
    data.adapter.dispose();
});

test('keeps failed assets as deterministic footprint boxes without blocking peers', async () => {
    const data = fixture({
        assetResolver: request => {
            if (request.assetId === 'asset-failed') {
                throw new Error('fixture load failure');
            }
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage === 'detail') {
                return prototype(data.THREE, 'detail-ok');
            }
            return null;
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-failed', 'asset-failed', REV_A, 0, 0, 0),
                placement('pl-ok', 'asset-ok', REV_A, 4, 0, 0),
            ],
        },
        assetCatalog: [
            asset('asset-failed', REV_A),
            asset('asset-ok', REV_A),
        ],
    });
    const diagnostics = data.adapter.getDiagnostics();
    const failed = diagnostics.representationGroups.find(
        group => group.assetId === 'asset-failed'
    );
    const okay = diagnostics.representationGroups.find(
        group => group.assetId === 'asset-ok'
    );
    assert.strictEqual(failed.representation, 'footprint');
    assert.strictEqual(okay.representation, 'detail');
    assert.strictEqual(
        diagnostics.loadTrace.filter(item => (
            item.assetId === 'asset-failed' && item.status === 'failed'
        )).length,
        5
    );
    assert(diagnostics.warnings.length >= 5);
    data.adapter.dispose();
});

test('context loss degrades 3D without throwing and context restoration resumes it', async () => {
    const statuses = [];
    const data = fixture({
        onStatusChange: status => statuses.push(status.status),
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, 0, 0, 0),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    const canvas = FakeRenderer.instances.at(-1).domElement;
    const event = canvas.dispatch('webglcontextlost');
    assert.strictEqual(event.prevented, true);
    let diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.status, 'degraded');
    assert.strictEqual(diagnostics.contextLost, true);
    assert.strictEqual(diagnostics.degraded, true);
    assert.doesNotThrow(() => data.adapter.setSelection(['pl-a']));

    canvas.dispatch('webglcontextrestored');
    diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.status, 'ready');
    assert.strictEqual(diagnostics.contextLost, false);
    assert.strictEqual(diagnostics.degraded, false);
    assert(statuses.includes('degraded'));
    data.adapter.dispose();
});

test('WebGL-unavailable mode retains scene identity for the independent 2D controller', async () => {
    const data = fixture({ webglAvailable: false });
    data.adapter.mount(data.host);
    const diagnostics = await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, 0, 0, 0),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    assert.strictEqual(diagnostics.degraded, true);
    assert.strictEqual(diagnostics.statusReason, 'webgl_unavailable');
    assert.strictEqual(diagnostics.placementCount, 1);
    assert.strictEqual(data.host.children.length, 0);
    assert.strictEqual(data.adapter.pick({ normalized: true, x: 0, y: 0 }), null);
    data.adapter.dispose();
});

test('coalesces invalidations into a demand-driven frame with no idle loop', () => {
    const data = fixture();
    data.adapter.mount(data.host);
    assert.strictEqual(data.scheduler.pendingCount, 1);
    data.adapter.invalidate();
    data.adapter.invalidate();
    data.adapter.invalidate();
    assert.strictEqual(data.scheduler.pendingCount, 1);
    data.scheduler.flush();
    assert.strictEqual(data.scheduler.pendingCount, 0);
    const diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.demandRendering.renderedFrames, 1);
    assert.strictEqual(diagnostics.demandRendering.pendingFrame, false);
    data.adapter.dispose();
});

test('twenty remounts leave exactly one canvas, observer, and render request', () => {
    const data = fixture();
    const hosts = [];
    for (let index = 0; index < 20; index += 1) {
        const host = new FakeElement('host-' + index);
        hosts.push(host);
        data.adapter.mount(host);
        assert.strictEqual(host.children.length, 1);
        assert.strictEqual(FakeResizeObserver.activeCount, 1);
        assert.strictEqual(data.scheduler.pendingCount, 1);
        hosts.slice(0, -1).forEach(previous => {
            assert.strictEqual(previous.children.length, 0);
        });
    }
    const diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.lifecycle.mountCount, 20);
    assert.strictEqual(diagnostics.lifecycle.teardownCount, 19);
    assert.strictEqual(diagnostics.lifecycle.canvasCount, 1);
    assert.strictEqual(diagnostics.lifecycle.observerActive, true);
    assert.strictEqual(diagnostics.lifecycle.listenerCount, 4);
    data.adapter.dispose();
    assert.strictEqual(FakeResizeObserver.activeCount, 0);
    assert.strictEqual(data.scheduler.pendingCount, 0);
    assert(hosts.every(host => host.children.length === 0));
});

test('remounting a populated adapter replays its authoritative scene', async () => {
    const data = fixture({
        assetResolver: request => {
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage === 'detail') {
                return prototype(data.THREE, 'detail');
            }
            return null;
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, 0, 0, 0),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    assert.strictEqual(
        data.adapter.getDiagnostics().representationGroups.length,
        1
    );

    const secondHost = new FakeElement('second-host');
    data.adapter.mount(secondHost);
    await settleAsync(16);

    const diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.status, 'ready');
    assert.strictEqual(diagnostics.representationGroups.length, 1);
    assert.deepStrictEqual(
        diagnostics.representationGroups[0].placementIds,
        ['pl-a']
    );
    assert.strictEqual(data.host.children.length, 0);
    assert.strictEqual(secondHost.children.length, 1);
    data.adapter.dispose();
});

test('a visual resolving after disposal is released instead of leaked', async () => {
    let resolveDetail = null;
    let lateObject = null;
    const data = fixture({
        assetResolver: request => {
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage === 'detail') {
                lateObject = prototype(data.THREE, 'late-detail');
                return new Promise(resolve => {
                    resolveDetail = () => resolve(lateObject);
                });
            }
            return null;
        },
    });
    data.adapter.mount(data.host);
    const scenePromise = data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, 0, 0, 0),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    await settleAsync(12);
    assert.strictEqual(typeof resolveDetail, 'function');
    const lateMesh = lateObject.children[0];
    assert.strictEqual(lateMesh.geometry.disposeCount, 0);
    assert.strictEqual(lateMesh.material.disposeCount, 0);

    data.adapter.dispose();
    resolveDetail();
    await scenePromise;

    assert.strictEqual(lateMesh.geometry.disposeCount, 1);
    assert.strictEqual(lateMesh.material.disposeCount, 1);
    assert.strictEqual(data.adapter.getDiagnostics().status, 'disposed');
});

test('dispose is idempotent and releases canvas, listeners, controls, RAF, and GPU resources', async () => {
    const data = fixture({
        assetResolver: request => {
            if (request.stage === 'detail') {
                return prototype(data.THREE, 'detail');
            }
            return null;
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, 0, 0, 0),
                placement('pl-b', 'asset-machine', REV_A, 3, 0, 0),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    const renderer = FakeRenderer.instances.at(-1);
    const controls = FakeControls.instances.at(-1);
    const canvas = renderer.domElement;
    assert(canvas.listenerCount() >= 2);
    assert.strictEqual(data.adapter.dispose(), true);
    assert.strictEqual(data.adapter.dispose(), false);
    const diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.status, 'disposed');
    assert.strictEqual(diagnostics.mounted, false);
    assert.strictEqual(diagnostics.lifecycle.canvasCount, 0);
    assert.strictEqual(diagnostics.lifecycle.observerActive, false);
    assert.strictEqual(diagnostics.lifecycle.listenerCount, 0);
    assert.strictEqual(data.host.children.length, 0);
    assert.strictEqual(canvas.listenerCount(), 0);
    assert.strictEqual(renderer.disposeCount, 1);
    assert.strictEqual(renderer.renderListsDisposed, true);
    assert.strictEqual(controls.disposeCount, 1);
    assert.strictEqual(data.scheduler.pendingCount, 0);
    assert(FakeGeometry.totalDisposed > 0);
    assert(FakeMaterial.totalDisposed > 0);
});

async function run() {
    let passed = 0;
    for (const entry of tests) {
        resetFakes();
        try {
            await entry.callback();
            passed += 1;
            console.log('ok - ' + entry.name);
        } catch (error) {
            console.error('not ok - ' + entry.name);
            throw error;
        }
    }
    console.log(passed + '/' + tests.length + ' passed');
}

run().catch(error => {
    console.error(error && error.stack ? error.stack : error);
    process.exitCode = 1;
});
