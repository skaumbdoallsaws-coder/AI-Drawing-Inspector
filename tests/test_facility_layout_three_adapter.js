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
        this.elements = null;
    }

    fromArray(values) {
        this.elements = values.slice();
        return this;
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
        clone.elements = this.elements ? this.elements.slice() : null;
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

    applyMatrix4(matrix) {
        const values = matrix && matrix.elements;
        if (Array.isArray(values) && values.length === 16) {
            this.position.set(values[12], values[13], values[14]);
        }
        return this;
    }

    clone(deep) {
        const clone = new FakeObject3D();
        clone.name = this.name;
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

class FakeShape {
    constructor() {
        this.commands = [];
    }

    moveTo(x, y) {
        this.commands.push(['moveTo', x, y]);
    }

    lineTo(x, y) {
        this.commands.push(['lineTo', x, y]);
    }

    closePath() {
        this.commands.push(['closePath']);
    }
}

class FakeShapeGeometry extends FakeGeometry {
    constructor(shape) {
        super();
        this.shape = shape;
        this.isShapeGeometry = true;
    }
}

class FakeBufferGeometry extends FakeGeometry {
    constructor() {
        super();
        this.attributes = {};
    }

    setAttribute(name, attribute) {
        this.attributes[name] = attribute;
        return this;
    }
}

class FakeFloat32BufferAttribute {
    constructor(values, itemSize) {
        this.array = Array.from(values);
        this.itemSize = itemSize;
        this.count = this.array.length / itemSize;
    }
}

class FakeMaterial {
    constructor(options) {
        this.options = Object.assign({}, options);
        this.userData = {};
        this.name = '';
        this.color = new FakeColor(this.options.color || 0);
        this.emissive = new FakeColor(0);
        this.emissiveIntensity = 0;
        this.roughness = this.options.roughness;
        this.metalness = this.options.metalness;
        this.transparent = Boolean(this.options.transparent);
        this.opacity = this.options.opacity === undefined
            ? 1 : this.options.opacity;
        this.depthWrite = this.options.depthWrite !== false;
        this.depthTest = this.options.depthTest !== false;
        this.side = this.options.side;
        this.flatShading = Boolean(this.options.flatShading);
        this.vertexColors = Boolean(this.options.vertexColors);
        this.disposeCount = 0;
        this.needsUpdate = false;
    }

    clone() {
        const clone = new FakeMaterial(this.options);
        clone.name = this.name;
        clone.userData = Object.assign({}, this.userData);
        clone.color.setHex(this.color.getHex());
        clone.emissive.setHex(this.emissive.getHex());
        clone.emissiveIntensity = this.emissiveIntensity;
        return clone;
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

class FakeLineSegments extends FakeObject3D {
    constructor(geometry, material) {
        super();
        this.isLineSegments = true;
        this.geometry = geometry;
        this.material = material;
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
        this.info = {
            reset: () => {
                this.infoResetCount = (this.infoResetCount || 0) + 1;
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

    setAnimationLoop(value) {
        this.animationLoop = value;
    }

    setRenderTarget(value) {
        this.renderTarget = value;
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

class FakePointerLockControls extends FakeEventTarget {
    constructor(camera, canvas) {
        super();
        this.camera = camera;
        this.canvas = canvas;
        this.enabled = false;
        this.isLocked = false;
        this.disposeCount = 0;
        FakePointerLockControls.instances.push(this);
    }

    getDirection(target) {
        return target.set(0, 0, -1);
    }

    lock() {
        this.isLocked = true;
        this.dispatch('lock');
    }

    unlock() {
        if (!this.isLocked) return;
        this.isLocked = false;
        this.dispatch('unlock');
    }

    dispose() {
        this.disposeCount += 1;
    }
}
FakePointerLockControls.instances = [];

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
        Shape: FakeShape,
        ShapeGeometry: FakeShapeGeometry,
        BoxGeometry: FakeGeometry,
        BufferGeometry: FakeBufferGeometry,
        Float32BufferAttribute: FakeFloat32BufferAttribute,
        MeshStandardMaterial: FakeMaterial,
        MeshBasicMaterial: FakeMaterial,
        LineBasicMaterial: FakeMaterial,
        Mesh: FakeMesh,
        LineSegments: FakeLineSegments,
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
    const documentObject = new FakeEventTarget();
    documentObject.hidden = false;
    const windowObject = new FakeEventTarget();
    const adapter = runtime.createThreeAdapter(Object.assign({
        THREE,
        OrbitControls: FakeControls,
        PointerLockControls: FakePointerLockControls,
        ResizeObserver: FakeResizeObserver,
        requestAnimationFrame: callback => scheduler.request(callback),
        cancelAnimationFrame: id => scheduler.cancel(id),
        document: documentObject,
        window: windowObject,
        logger: { warn() {} },
    }, options || {}));
    return {
        THREE,
        host,
        adapter,
        scheduler,
        documentObject,
        windowObject,
    };
}

function resetFakes() {
    FakeRenderer.instances.length = 0;
    FakeControls.instances.length = 0;
    FakePointerLockControls.instances.length = 0;
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
    assert.strictEqual(typeof runtime.createRendererPool, 'function');
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
        'suspend',
        'resume',
        'setScene',
        'setSelection',
        'setSelectionHandler',
        'setGhostPlacement',
        'setProposalPreview',
        'fit',
        'fitFacility',
        'fitLayout',
        'frontView',
        'topView',
        'rightView',
        'isometricView',
        'setNavigationMode',
        'enterWalkthrough',
        'exitWalkthrough',
        'switchImmersiveMode',
        'getWalkthroughState',
        'setWalkthroughStateHandler',
        'enterDrone',
        'exitDrone',
        'getDroneState',
        'setDroneStateHandler',
        'getWalkthroughContextFocus',
        'setWalkthroughContextHandler',
        'setCameraOrientationHandler',
        'getRecordingCanvas',
        'renderRecordingFrame',
        'navigateWalkthroughToPlacement',
        'navigateWalkthroughToPoint',
        'cancelWalkthroughNavigation',
        'getCameraView',
        'applyCameraView',
        'zoomBy',
        'setGridVisible',
        'setVisualSettings',
        'getVisualSettings',
        'invalidate',
        'pick',
        'worldPointOnFloor',
        'getDiagnostics',
        'dispose',
    ].forEach(method => {
        assert.strictEqual(typeof adapter[method], 'function', method);
    });
    assert.strictEqual(adapter.getRecordingCanvas(), null);
});

test('camera orientation reports the facility direction at the top of the view', () => {
    const data = fixture();
    data.adapter.mount(data.host);
    data.scheduler.flush();
    const reports = [];
    assert.strictEqual(data.adapter.setCameraOrientationHandler(value => {
        reports.push(value);
    }), true);
    assert.strictEqual(reports.length, 1);
    assert.ok(Math.abs(reports[0].headingDegrees) < 0.001);
    assert.deepStrictEqual(reports[0].screenTop, { x: 0, z: 1 });

    const halfTurn = Math.sqrt(0.5);
    assert.strictEqual(data.adapter.applyCameraView({
        position: { x: 8, y: 7, z: 6 },
        quaternion: { x: 0, y: halfTurn, z: 0, w: halfTurn },
        up: { x: 0, y: 1, z: 0 },
        target: { x: 2, y: 0, z: 3 },
        navigationMode: 'orbit',
    }), true);
    data.scheduler.flush();
    assert.strictEqual(reports.length, 2);
    assert.ok(Math.abs(reports[1].headingDegrees - 90) < 0.001);
    assert.ok(Math.abs(reports[1].screenTop.x - 1) < 0.001);
    assert.ok(Math.abs(reports[1].screenTop.z) < 0.001);
    assert.ok(Math.abs(
        data.adapter.getDiagnostics().cameraOrientation.headingDegrees - 90
    ) < 0.001);

    data.adapter.invalidate();
    data.scheduler.flush();
    assert.strictEqual(reports.length, 2);
    assert.strictEqual(data.adapter.setCameraOrientationHandler(null), false);
    data.adapter.dispose();
});

test('recording refresh renders synchronously before canvas capture', () => {
    const data = fixture();
    data.adapter.mount(data.host);
    data.scheduler.flush();
    const canvas = data.adapter.getRecordingCanvas();
    const before = data.adapter.getDiagnostics()
        .demandRendering.renderedFrames;
    assert.strictEqual(data.adapter.renderRecordingFrame(), canvas);
    assert.strictEqual(
        data.adapter.getDiagnostics().demandRendering.renderedFrames,
        before + 1
    );
    data.adapter.dispose();
});

test('walkthrough geometry prevents tunneling and finds a valid spawn', () => {
    const bounds = {
        minimum: { x: 0, y: 0, z: 0 },
        maximum: { x: 12, y: 0, z: 12 },
    };
    const obstacle = [
        { x: 4, z: 4 },
        { x: 6, z: 4 },
        { x: 6, z: 6 },
        { x: 4, z: 6 },
    ];
    assert.strictEqual(
        runtime.circleIntersectsPolygon({ x: 3.8, z: 5 }, 0.3, obstacle),
        true
    );
    assert.strictEqual(
        runtime.walkthroughPointValid(
            { x: 0.1, z: 5 }, 0.3, bounds, [obstacle]
        ),
        false
    );
    const movement = runtime.resolveWalkthroughMovement({
        start: { x: 2, z: 5 },
        delta: { x: 8, z: 0 },
        radius: 0.3,
        bounds,
        obstacles: [obstacle],
    });
    assert.strictEqual(movement.collided, true);
    assert(movement.position.x < 3.71);
    assert.strictEqual(movement.position.z, 5);
    const spawn = runtime.findWalkthroughSpawn({
        desired: { x: 5, z: 5 },
        radius: 0.3,
        bounds,
        obstacles: [obstacle],
    });
    assert(spawn);
    assert.strictEqual(
        runtime.walkthroughPointValid(spawn, 0.3, bounds, [obstacle]),
        true
    );
});

test('drone geometry preserves altitude clearance and slides along obstacles', () => {
    const bounds = {
        minimum: { x: 0, y: 0, z: 0 },
        maximum: { x: 20, y: 15, z: 20 },
    };
    const volume = {
        id: 'rack-a',
        placementId: 'rack-a',
        polygon: [
            { x: 8, z: 6 },
            { x: 10, z: 6 },
            { x: 10, z: 14 },
            { x: 8, z: 14 },
        ],
        minimumY: 0,
        maximumY: 6,
    };
    assert.strictEqual(runtime.sphereIntersectsDroneVolume(
        { x: 7.8, y: 3, z: 10 }, 0.35, volume
    ), true);
    assert.strictEqual(runtime.sphereIntersectsDroneVolume(
        { x: 9, y: 6.5, z: 10 }, 0.35, volume
    ), false);
    const blocked = runtime.resolveDroneMovement({
        start: { x: 7, y: 3, z: 8 },
        delta: { x: 3, y: 0, z: 3 },
        radius: 0.35,
        bounds,
        volumes: [volume],
    });
    assert.strictEqual(blocked.collided, true);
    assert.ok(blocked.collisionIds.includes('rack-a'));
    assert.ok(blocked.position.z > 8);
    assert.ok(blocked.position.x < 8);
    const over = runtime.resolveDroneMovement({
        start: { x: 7, y: 7, z: 10 },
        delta: { x: 4, y: 0, z: 0 },
        radius: 0.35,
        bounds,
        volumes: [volume],
    });
    assert.strictEqual(over.collided, false);
    assert.ok(over.position.x > 10);
});

test('assisted drone probe reports an approaching obstacle and finds a safe spawn', () => {
    const bounds = {
        minimum: { x: 0, y: 0, z: 0 },
        maximum: { x: 20, y: 15, z: 20 },
    };
    const volume = {
        id: 'machine-a',
        polygon: [
            { x: 8, z: 8 },
            { x: 12, z: 8 },
            { x: 12, z: 12 },
            { x: 8, z: 12 },
        ],
        minimumY: 0,
        maximumY: 5,
    };
    const probe = runtime.probeDroneClearance({
        start: { x: 5, y: 2, z: 10 },
        direction: { x: 1, y: 0, z: 0 },
        maximumDistance: 5,
        radius: 0.35,
        bounds,
        volumes: [volume],
        steps: 20,
    });
    assert.strictEqual(probe.bounded, true);
    assert.strictEqual(probe.obstacleId, 'machine-a');
    assert.ok(probe.distance > 2 && probe.distance < 3.5);
    const index = runtime.buildDroneSpatialIndex([volume], 2);
    const indexedProbe = runtime.probeDroneClearance({
        start: { x: 5, y: 2, z: 10 },
        direction: { x: 1, y: 0, z: 0 },
        maximumDistance: 5,
        radius: 0.35,
        bounds,
        volumes: index,
        steps: 20,
    });
    assert.deepStrictEqual(indexedProbe, probe);
    assert.ok(index.cells.size > 0);
    const spawn = runtime.findDroneSpawn({
        desired: { x: 10, y: 2, z: 10 },
        radius: 0.35,
        bounds,
        volumes: index,
    });
    assert.ok(spawn);
    assert.strictEqual(runtime.dronePointValid(
        spawn, 0.35, bounds, [volume]
    ), true);
});

test('Drone visibility expands with altitude and remains bounded', () => {
    assert.strictEqual(runtime.droneViewDistanceForAltitude(
        0, 60, 4, 500
    ), 60);
    assert.strictEqual(runtime.droneViewDistanceForAltitude(
        29.2, 60, 4, 500
    ), 176.8);
    assert.strictEqual(runtime.droneViewDistanceForAltitude(
        200, 60, 4, 500
    ), 500);
});

test('multi-level walkthrough climbs bounded steps and rejects unsafe drops', () => {
    const bounds = {
        minimum: { x: 0, y: 0, z: 0 },
        maximum: { x: 12, y: 2, z: 4 },
    };
    const rectangle = (id, x1, x2, elevation, kind) => ({
        id,
        kind,
        elevation,
        polygon: [
            { x: x1, z: 0 }, { x: x2, z: 0 },
            { x: x2, z: 4 }, { x: x1, z: 4 },
        ],
    });
    const volume = (x1, x2, maximumY) => ({
        minimumY: 0,
        maximumY,
        walkableElevation: maximumY,
        polygon: [
            { x: x1, z: 0 }, { x: x2, z: 0 },
            { x: x2, z: 4 }, { x: x1, z: 4 },
        ],
    });
    const surfaces = [
        rectangle('ground', 0, 12, 0, 'ground'),
        rectangle('step-1', 2, 3, 0.2, 'stair'),
        rectangle('step-2', 3, 4, 0.4, 'stair'),
        rectangle('platform', 4, 8, 0.4, 'platform'),
    ];
    const climbed = runtime.resolveMultiLevelWalkthroughMovement({
        start: { x: 1, z: 2, elevation: 0 },
        delta: { x: 4.5, z: 0 },
        radius: 0.2,
        maximumStepUp: 0.24,
        maximumStepDown: 0.32,
        bodyHeight: 1.9,
        supportClearance: 0.075,
        bounds,
        surfaces,
        obstacleVolumes: [volume(2, 3, 0.2), volume(3, 4, 0.4), volume(4, 8, 0.4)],
    });
    assert(climbed.position.x > 5);
    assert.strictEqual(climbed.elevation, 0.4);
    assert.strictEqual(climbed.surfaceKind, 'platform');
    assert.strictEqual(climbed.changedLevel, true);

    const unsafeDrop = runtime.resolveMultiLevelWalkthroughMovement({
        start: { x: 6, z: 2, elevation: 0.4 },
        delta: { x: 4, z: 0 },
        radius: 0.2,
        maximumStepUp: 0.24,
        maximumStepDown: 0.32,
        bounds,
        surfaces,
        obstacleVolumes: [],
    });
    assert(unsafeDrop.position.x < 8.21);
    assert.strictEqual(unsafeDrop.elevation, 0.4);
    assert.strictEqual(unsafeDrop.collided, true);
});

test('multi-level walkthrough treats an unsupported high riser as a wall', () => {
    const bounds = {
        minimum: { x: 0, y: 0, z: 0 },
        maximum: { x: 8, y: 2, z: 4 },
    };
    const ground = {
        id: 'ground', kind: 'ground', elevation: 0,
        polygon: [
            { x: 0, z: 0 }, { x: 8, z: 0 },
            { x: 8, z: 4 }, { x: 0, z: 4 },
        ],
    };
    const highSurface = {
        id: 'high', kind: 'platform', elevation: 0.55,
        polygon: [
            { x: 3, z: 0 }, { x: 5, z: 0 },
            { x: 5, z: 4 }, { x: 3, z: 4 },
        ],
    };
    const result = runtime.resolveMultiLevelWalkthroughMovement({
        start: { x: 1, z: 2, elevation: 0 },
        delta: { x: 4, z: 0 },
        radius: 0.2,
        maximumStepUp: 0.24,
        maximumStepDown: 0.32,
        bounds,
        surfaces: [ground, highSurface],
        obstacleVolumes: [{
            minimumY: 0,
            maximumY: 0.55,
            walkableElevation: 0.55,
            polygon: highSurface.polygon,
        }],
    });
    assert(result.position.x < 2.81);
    assert.strictEqual(result.elevation, 0);
    assert.strictEqual(result.collided, true);
});

test('multi-level walkthrough climbs narrow verified treads without capsule snagging', () => {
    const bounds = {
        minimum: { x: -1, y: 0, z: -1 },
        maximum: { x: 4, y: 2, z: 1 },
    };
    const surfaces = [{
        id: 'ground', kind: 'ground', elevation: 0,
        polygon: [
            { x: -1, z: -1 }, { x: 4, z: -1 },
            { x: 4, z: 1 }, { x: -1, z: 1 },
        ],
    }];
    const obstacleVolumes = [];
    for (let index = 0; index < 8; index += 1) {
        const minimumX = 2 - (index + 1) * 0.2;
        const maximumX = minimumX + 0.266;
        const elevation = 0.15 * (index + 1);
        const polygon = [
            { x: minimumX, z: -0.4 }, { x: maximumX, z: -0.4 },
            { x: maximumX, z: 0.4 }, { x: minimumX, z: 0.4 },
        ];
        surfaces.push({ id: `step-${index + 1}`, kind: 'stair', elevation, polygon });
        obstacleVolumes.push({
            id: `step-${index + 1}`,
            minimumY: elevation - 0.03,
            maximumY: elevation,
            walkableElevation: elevation,
            walkableKind: 'stair',
            polygon,
        });
    }
    surfaces.push({
        id: 'platform', kind: 'platform', elevation: 1.2,
        polygon: [
            { x: -1, z: -1 }, { x: 0.45, z: -1 },
            { x: 0.45, z: 1 }, { x: -1, z: 1 },
        ],
    });
    const result = runtime.resolveMultiLevelWalkthroughMovement({
        start: { x: 2.4, z: 0, elevation: 0 },
        delta: { x: -3, z: 0 },
        radius: 0.3,
        maximumStepUp: 0.24,
        maximumStepDown: 0.34,
        bodyHeight: 1.95,
        supportClearance: 0.075,
        bounds,
        surfaces,
        obstacleVolumes,
    });
    assert(result.position.x < 0);
    assert.strictEqual(result.elevation, 1.2);
    assert.strictEqual(result.surfaceKind, 'platform');
    assert.strictEqual(result.changedLevel, true);
});

test('walkthrough posture profiles preserve the standing human envelope and scale together', () => {
    const profiles = runtime.walkthroughPostureProfiles(2);
    assert.strictEqual(profiles.standing.eyeHeight, 3.4);
    assert.strictEqual(profiles.standing.bodyHeight, 3.9);
    assert.strictEqual(profiles.standing.radius, 0.6);
    assert.strictEqual(profiles.crouching.bodyHeight, 2.4);
    assert.strictEqual(profiles.crawling.bodyHeight, 1.3);
    assert(profiles.standing.walkSpeed > profiles.crouching.walkSpeed);
    assert(profiles.crouching.walkSpeed > profiles.crawling.walkSpeed);
    assert(Object.isFrozen(profiles));
});

test('walkthrough can crawl under low geometry but refuses to stand without clearance', () => {
    const bounds = {
        minimum: { x: 0, y: 0, z: 0 },
        maximum: { x: 10, y: 3, z: 10 },
    };
    const overhead = {
        id: 'service-platform-underside',
        minimumY: 0.82,
        maximumY: 1.05,
        polygon: [
            { x: 3, z: 3 }, { x: 7, z: 3 },
            { x: 7, z: 7 }, { x: 3, z: 7 },
        ],
    };
    const postures = runtime.walkthroughPostureProfiles(1);
    const shared = {
        postures,
        point: { x: 5, z: 5 },
        elevation: 0,
        supportClearance: 0.075,
        bounds,
        obstacleVolumes: [overhead],
    };
    const crawl = runtime.resolveWalkthroughPostureChange(Object.assign({
        posture: 'crawling',
    }, shared));
    const crouch = runtime.resolveWalkthroughPostureChange(Object.assign({
        posture: 'crouching',
    }, shared));
    const stand = runtime.resolveWalkthroughPostureChange(Object.assign({
        posture: 'standing',
    }, shared));
    assert.strictEqual(crawl.ok, true);
    assert.strictEqual(crawl.availableHeight, 0.82);
    assert.strictEqual(crouch.ok, false);
    assert.strictEqual(crouch.reason, 'insufficient_clearance');
    assert.strictEqual(stand.ok, false);
    assert.strictEqual(stand.reason, 'insufficient_clearance');
    assert.strictEqual(stand.obstacleId, 'service-platform-underside');
});

test('walkthrough returns to standing in open geometry', () => {
    const postures = runtime.walkthroughPostureProfiles(1);
    const result = runtime.resolveWalkthroughPostureChange({
        posture: 'standing',
        postures,
        point: { x: 1, z: 1 },
        elevation: 0,
        bounds: {
            minimum: { x: 0, y: 0, z: 0 },
            maximum: { x: 10, y: 3, z: 10 },
        },
        obstacleVolumes: [],
    });
    assert.strictEqual(result.ok, true);
    assert.strictEqual(result.availableHeight, null);
    assert.strictEqual(result.reason, 'clear');
});

test('walkthrough route planning is deterministic and clears obstacles', () => {
    const bounds = {
        minimum: { x: 0, y: 0, z: 0 },
        maximum: { x: 12, y: 0, z: 12 },
    };
    const obstacle = [
        { x: 5, z: 0 },
        { x: 7, z: 0 },
        { x: 7, z: 8 },
        { x: 5, z: 8 },
    ];
    const input = {
        start: { x: 2, z: 2 },
        goal: { x: 10, z: 2 },
        radius: 0.3,
        gridSpacing: 0.5,
        bounds,
        obstacles: [obstacle],
    };
    const first = runtime.planWalkthroughRoute(input);
    const second = runtime.planWalkthroughRoute(input);
    assert.deepStrictEqual(second, first);
    assert.strictEqual(first.ok, true);
    assert.strictEqual(first.reason, 'routed');
    assert(first.points.length >= 3);
    assert(first.points.some(point => point.z >= 8.3));
    first.points.forEach(point => assert.strictEqual(
        runtime.walkthroughPointValid(point, 0.3, bounds, [obstacle]),
        true
    ));
    first.points.slice(1).forEach((point, index) => assert.strictEqual(
        runtime.walkthroughSegmentValid(first.points[index], point, input),
        true
    ));
});

test('bounded renderer pool reuses one WebGL renderer across adapter remounts', () => {
    const pool = runtime.createRendererPool({ maximumSize: 1 });
    const first = fixture({ rendererPool: pool });
    first.adapter.mount(first.host);
    const renderer = FakeRenderer.instances.at(-1);
    assert.strictEqual(first.adapter.dispose(), true);
    assert.strictEqual(renderer.disposeCount, 0);
    assert.strictEqual(renderer.forceContextLossCount, 0);
    assert.strictEqual(pool.getDiagnostics().availableCount, 1);

    const second = fixture({ rendererPool: pool });
    second.adapter.mount(second.host);
    assert.strictEqual(FakeRenderer.instances.length, 1);
    assert.strictEqual(second.host.children[0], renderer.domElement);
    assert.strictEqual(pool.getDiagnostics().reusedCount, 1);
    assert.strictEqual(second.adapter.dispose(), true);
    assert.strictEqual(pool.getDiagnostics().availableCount, 1);
    assert.strictEqual(pool.dispose(), true);
    assert.strictEqual(pool.dispose(), false);
    assert.strictEqual(renderer.disposeCount, 1);
    assert.strictEqual(renderer.forceContextLossCount, 1);
});

test('renderer pool capacity limits concurrent leases and factory calls', () => {
    const pool = runtime.createRendererPool({ maximumSize: 1 });
    let factoryCalls = 0;
    const factory = () => {
        factoryCalls += 1;
        return new FakeRenderer();
    };
    const first = pool.acquire(factory);
    assert.throws(
        () => pool.acquire(factory),
        /capacity is exhausted/
    );
    assert.strictEqual(factoryCalls, 1);
    assert.deepStrictEqual(pool.getDiagnostics(), {
        disposed: false,
        maximumSize: 1,
        availableCount: 0,
        leasedCount: 1,
        createdCount: 1,
        reusedCount: 0,
    });
    assert.strictEqual(pool.release(first), true);
    assert.strictEqual(pool.dispose(), true);
});

test('suspend and resume preserve one scene while pausing observers and frames', async () => {
    const pool = runtime.createRendererPool({ maximumSize: 1 });
    const data = fixture({ rendererPool: pool });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, 0, 0, 0),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    const renderer = FakeRenderer.instances.at(-1);
    const controls = FakeControls.instances.at(-1);
    const observer = FakeResizeObserver.instances.at(-1);
    const disposedGeometry = FakeGeometry.totalDisposed;
    const disposedMaterial = FakeMaterial.totalDisposed;

    assert.strictEqual(data.adapter.suspend(), true);
    assert.strictEqual(data.adapter.suspend(), false);
    let diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.suspended, true);
    assert.strictEqual(diagnostics.lifecycle.observerActive, false);
    assert.strictEqual(diagnostics.demandRendering.pendingFrame, false);
    assert.strictEqual(observer.active, false);
    assert.strictEqual(FakeGeometry.totalDisposed, disposedGeometry);
    assert.strictEqual(FakeMaterial.totalDisposed, disposedMaterial);
    assert.strictEqual(pool.getDiagnostics().leasedCount, 1);

    assert.strictEqual(data.adapter.resume(), true);
    assert.strictEqual(data.adapter.resume(), false);
    diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.suspended, false);
    assert.strictEqual(diagnostics.lifecycle.observerActive, true);
    assert.strictEqual(FakeRenderer.instances.length, 1);
    assert.strictEqual(FakeControls.instances.at(-1), controls);
    assert.strictEqual(FakeResizeObserver.instances.length, 1);
    assert.strictEqual(renderer.disposeCount, 0);
    data.adapter.dispose();
    pool.dispose();
});

test('resume rebuilds a scene changed while the adapter was suspended', async () => {
    const data = fixture();
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-before', 'asset-machine', REV_A, 0, 0, 0),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });

    assert.strictEqual(data.adapter.suspend(), true);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-after', 'asset-machine', REV_A, 12, 0, 4),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    let diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.suspended, true);
    assert.strictEqual(diagnostics.placementCount, 1);

    assert.strictEqual(data.adapter.resume(), true);
    await settleAsync();
    diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.suspended, false);
    assert.deepStrictEqual(
        diagnostics.representationGroups.flatMap(group => group.placementIds),
        ['pl-after']
    );
    assert.strictEqual(diagnostics.pendingLoads, 0);
    data.adapter.dispose();
});

test('uses cursor-centered navigation and adaptive resolution while moving', () => {
    const data = fixture({
        pixelRatio: 2,
        interactivePixelRatio: 1,
        navigationResolutionRestoreDelayMs: 0,
    });
    data.adapter.mount(data.host);

    const controls = FakeControls.instances.at(-1);
    const renderer = FakeRenderer.instances.at(-1);
    assert.strictEqual(controls.zoomToCursor, true);
    assert.strictEqual(controls.zoomSpeed, 1.8);
    assert.strictEqual(controls.panSpeed, 1.25);
    assert.strictEqual(controls.rotateSpeed, 1);
    assert.strictEqual(controls.screenSpacePanning, true);
    assert.strictEqual(controls.enableDamping, false);
    assert.strictEqual(renderer.pixelRatio, 2);

    controls.dispatch('start');
    let diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(renderer.pixelRatio, 1);
    assert.strictEqual(diagnostics.rendering.navigationInteracting, true);
    assert.strictEqual(diagnostics.rendering.currentPixelRatio, 1);

    controls.dispatch('end');
    diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(renderer.pixelRatio, 2);
    assert.strictEqual(diagnostics.rendering.navigationInteracting, false);
    assert.strictEqual(diagnostics.rendering.currentPixelRatio, 2);
    assert.deepStrictEqual(diagnostics.navigation.controls, {
        zoomToCursor: true,
        zoomSpeed: 1.8,
        panSpeed: 1.25,
        rotateSpeed: 1,
        screenSpacePanning: true,
        enableDamping: false,
    });
    data.adapter.dispose();
});

test('large layouts retain a resolved overview instead of loading detail', async () => {
    const calls = [];
    const data = fixture({
        largeLayoutDetailThreshold: 2,
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
                placement('pl-b', 'asset-machine', REV_A, 4, 0, 2),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });

    assert.deepStrictEqual(
        calls,
        ['manifest', 'footprint', 'proxy', 'overview']
    );
    const diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.rendering.largeLayoutMode, true);
    assert.strictEqual(
        diagnostics.representationGroups[0].representation,
        'overview'
    );
    assert.deepStrictEqual(
        diagnostics.loadTrace.find(item => item.stage === 'detail'),
        {
            assetId: 'asset-machine',
            assetDefinitionRevision: REV_A,
            stage: 'detail',
            status: 'skipped',
            detail: 'large_layout_overview_lod',
        }
    );
    data.adapter.dispose();
});

test('large layouts still load detail when no overview is available', async () => {
    const calls = [];
    const data = fixture({
        largeLayoutDetailThreshold: 2,
        assetResolver: request => {
            calls.push(request.stage);
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage === 'overview') return null;
            return prototype(data.THREE, request.stage);
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, 1, 0, 2),
                placement('pl-b', 'asset-machine', REV_A, 4, 0, 2),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });

    assert.deepStrictEqual(
        calls,
        ['manifest', 'footprint', 'proxy', 'overview', 'detail']
    );
    assert.strictEqual(
        data.adapter.getDiagnostics().representationGroups[0].representation,
        'detail'
    );
    data.adapter.dispose();
});

test('heavy large-layout visuals defer until their placement is selected', async () => {
    let overview = null;
    const data = fixture({
        largeLayoutDetailThreshold: 2,
        largeLayoutHeavyVisualBytes: 100,
        assetResolver: request => {
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage === 'footprint') {
                return prototype(data.THREE, request.stage);
            }
            if (request.stage === 'overview') {
                overview = prototype(data.THREE, request.stage);
                overview.byteSize = 101;
                return overview;
            }
            return null;
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-a', 'asset-heavy', REV_A, 1, 0, 2),
                placement('pl-b', 'asset-heavy', REV_A, 4, 0, 2),
            ],
        },
        assetCatalog: [asset('asset-heavy', REV_A)],
    });

    let diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.rendering.deferredGroupCount, 1);
    assert.strictEqual(
        diagnostics.representationGroups[0].representation,
        'footprint'
    );
    assert.strictEqual(
        diagnostics.loadTrace.find(item => (
            item.stage === 'overview' && item.status === 'skipped'
        )).detail,
        'large_layout_heavy_visual_deferred'
    );

    data.adapter.setSelection(['pl-a']);
    await settleAsync(20);
    diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.rendering.deferredGroupCount, 0);
    assert.strictEqual(
        diagnostics.representationGroups[0].representation,
        'overview'
    );
    assert.strictEqual(
        diagnostics.loadTrace.filter(item => (
            item.stage === 'overview'
            && item.detail === 'deferred_selected_asset'
            && item.status === 'resolved'
        )).length,
        1
    );
    data.adapter.dispose();
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

test('renders loaded facility assets in neutral CAD gray without losing selection feedback', async () => {
    let sourceMaterial = null;
    const data = fixture({
        assetResolver: request => {
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage !== 'detail') return null;
            const visual = prototype(data.THREE, 'colored-detail');
            sourceMaterial = visual.children[0].material;
            sourceMaterial.color.setHex(0xff00cc);
            sourceMaterial.options.color = 0xff00cc;
            return visual;
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-gray', 'asset-machine', REV_A, 1, 0, 2),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    data.scheduler.flush();

    assert(sourceMaterial);
    assert.strictEqual(sourceMaterial.disposeCount, 1);
    assert.deepStrictEqual(data.adapter.getDiagnostics().assetMaterial, {
        mode: 'neutral',
        color: 0x9aa2a9,
    });

    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    let placementRoot = null;
    let renderedMaterial = null;
    scene.traverse(object => {
        if (object.userData && object.userData.placementId === 'pl-gray') {
            placementRoot = object;
        }
    });
    assert(placementRoot);
    placementRoot.traverse(object => {
        if (object.isMesh && object.material) {
            renderedMaterial = object.material;
        }
    });
    assert(renderedMaterial);
    assert.strictEqual(renderedMaterial.color.getHex(), 0x9aa2a9);
    assert.strictEqual(renderedMaterial.transparent, false);
    assert.strictEqual(renderedMaterial.opacity, 1);
    assert.strictEqual(
        renderedMaterial.userData.facilityNeutralAssetMaterial,
        true
    );

    data.adapter.setSelection('pl-gray');
    assert.strictEqual(renderedMaterial.emissive.getHex(), 0x32a8ff);
    assert.strictEqual(renderedMaterial.emissiveIntensity, 0.75);
    data.adapter.dispose();
});

test('display settings update real materials and sustain bounded auto rotation', async () => {
    const data = fixture({
        assetResolver: request => {
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage === 'detail') {
                return prototype(data.THREE, 'display-settings-detail');
            }
            return null;
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-display', 'asset-machine', REV_A, 1, 0, 2),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    data.scheduler.flush();

    assert.deepStrictEqual(data.adapter.getVisualSettings(), {
        ambient: 1.55,
        directional: 2,
        exposure: 1.22,
        contrast: 1.02,
        metalness: 0.04,
        roughness: 0.7,
        autoRotate: false,
        wireframe: false,
        background: 'auto',
    });

    const settings = data.adapter.setVisualSettings({
        ambient: 0.9,
        directional: 2.2,
        exposure: 1.35,
        contrast: 1.2,
        metalness: 0.44,
        roughness: 0.31,
        autoRotate: true,
        wireframe: true,
        background: '#223344',
    });
    assert.deepStrictEqual(settings, data.adapter.getVisualSettings());
    assert.strictEqual(FakeRenderer.instances.at(-1).toneMappingExposure, 1.35);
    assert.strictEqual(
        FakeRenderer.instances.at(-1).domElement.style.filter,
        'contrast(1.20)'
    );
    const controls = FakeControls.instances.at(-1);
    assert.strictEqual(controls.autoRotate, true);
    assert.strictEqual(controls.autoRotateSpeed, 1.2);
    assert(data.scheduler.pendingCount > 0);

    let material = null;
    FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => {
        if (object.userData && object.userData.placementId === 'pl-display') {
            object.traverse(candidate => {
                if (candidate.isMesh && candidate.material) {
                    material = candidate.material;
                }
            });
        }
    });
    assert(material);
    assert.strictEqual(material.metalness, 0.44);
    assert.strictEqual(material.roughness, 0.31);
    assert.strictEqual(material.wireframe, true);

    const updatesBefore = controls.updateCount || 0;
    data.scheduler.flush();
    assert((controls.updateCount || 0) > updatesBefore);
    assert(data.scheduler.pendingCount > 0);
    data.adapter.setVisualSettings({ autoRotate: false, wireframe: false });
    data.scheduler.flush();
    assert.strictEqual(data.scheduler.pendingCount, 0);
    assert.strictEqual(material.wireframe, false);
    data.adapter.dispose();
});

test('keeps CAD normalization below the placement transform', async () => {
    let visual = null;
    const sourceToCanonical = [
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0.85, -0.52, 1,
    ];
    const data = fixture({
        assetResolver: request => {
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage === 'overview') {
                visual = prototype(data.THREE, 'private-cad-model');
                return {
                    object: visual,
                    sourceToCanonical,
                };
            }
            return null;
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-private', 'asset-private', REV_A, 8, 0, 6),
            ],
        },
        assetCatalog: [asset('asset-private', REV_A)],
    });
    data.scheduler.flush();

    assert(visual);
    assert.deepStrictEqual(
        { x: visual.position.x, y: visual.position.y, z: visual.position.z },
        { x: 0, y: 0.85, z: -0.52 }
    );
    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    let placementRoot = null;
    scene.traverse(object => {
        if (object.userData
                && object.userData.placementId === 'pl-private') {
            placementRoot = object;
        }
    });
    assert(placementRoot);
    assert.deepStrictEqual(
        {
            x: placementRoot.position.x,
            y: placementRoot.position.y,
            z: placementRoot.position.z,
        },
        { x: 8, y: 0, z: 6 }
    );
    assert.deepStrictEqual(
        placementRoot.userData.sourceToCanonical,
        sourceToCanonical
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

test('Fit Facility Fit Layout and Top View frame shared world data without moving it',
    async () => {
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
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement('pl-a', 'asset-machine', REV_A, 4, 0, 4),
                    placement('pl-b', 'asset-machine', REV_A, 7, 0, 6),
                ],
            },
            assetCatalog: [asset('asset-machine', REV_A)],
        });
        const before = data.adapter.getDiagnostics().modelRootTransform;
        assert.strictEqual(data.adapter.fitFacility(), true);
        let diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.lastFit.mode, 'facility');
        assert.strictEqual(diagnostics.lastFit.size.x, 40);
        assert.strictEqual(diagnostics.lastFit.size.z, 30);

        assert.strictEqual(data.adapter.fitLayout(), true);
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.lastFit.mode, 'layout');
        assert(diagnostics.lastFit.size.x < 40);
        assert(diagnostics.lastFit.size.z < 30);

        assert.strictEqual(data.adapter.topView(), true);
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.lastFit.mode, 'top');
        assert.deepStrictEqual(diagnostics.camera.target, {
            x: 20,
            y: 0,
            z: 15,
        });
        assert.strictEqual(diagnostics.camera.position.x, 20);
        assert.strictEqual(diagnostics.camera.position.z, 15);
        assert(diagnostics.camera.position.y > 0);
        assert.deepStrictEqual(diagnostics.modelRootTransform, before);
        data.adapter.dispose();
    });

test('3D heads-up navigation changes only camera controls and floor display',
    async () => {
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
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement('pl-a', 'asset-machine', REV_A, 4, 0, 4),
                ],
            },
            assetCatalog: [asset('asset-machine', REV_A)],
        });
        const rootBefore = data.adapter.getDiagnostics().modelRootTransform;
        assert.strictEqual(data.adapter.setNavigationMode('pan'), true);
        let diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.navigation.mode, 'pan');
        const controls = FakeControls.instances.at(-1);
        assert.strictEqual(controls.mouseButtons.LEFT, 2);
        assert.strictEqual(controls.mouseButtons.RIGHT, 0);

        const target = diagnostics.camera.target;
        const distance = position => Math.hypot(
            position.x - target.x,
            position.y - target.y,
            position.z - target.z
        );
        const distanceBefore = distance(diagnostics.camera.position);
        assert.strictEqual(data.adapter.zoomBy(1.25), true);
        diagnostics = data.adapter.getDiagnostics();
        assert(distance(diagnostics.camera.position) < distanceBefore);

        assert.strictEqual(data.adapter.isometricView(), true);
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.lastFit.mode, 'isometric');
        assert(diagnostics.camera.position.x > diagnostics.camera.target.x);
        assert(diagnostics.camera.position.y > diagnostics.camera.target.y);
        assert(diagnostics.camera.position.z > diagnostics.camera.target.z);

        assert.strictEqual(data.adapter.frontView(), true);
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.lastFit.mode, 'front');
        assert.strictEqual(diagnostics.camera.position.x, diagnostics.camera.target.x);
        assert.strictEqual(diagnostics.camera.position.y, diagnostics.camera.target.y);
        assert(diagnostics.camera.position.z > diagnostics.camera.target.z);

        assert.strictEqual(data.adapter.rightView(), true);
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.lastFit.mode, 'right');
        assert(diagnostics.camera.position.x > diagnostics.camera.target.x);
        assert.strictEqual(diagnostics.camera.position.y, diagnostics.camera.target.y);
        assert.strictEqual(diagnostics.camera.position.z, diagnostics.camera.target.z);

        assert.strictEqual(data.adapter.setGridVisible(false), true);
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.navigation.gridVisible, false);
        assert.strictEqual(diagnostics.environment.gridVisible, false);
        assert.strictEqual(data.adapter.setGridVisible(true), true);
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.environment.gridVisible, true);
        assert.deepStrictEqual(diagnostics.modelRootTransform, rootBefore);
        data.adapter.dispose();
    });

test('walkthrough starts near selection, moves on demand, and restores overview',
    async () => {
        const data = fixture({
            worldBounds: {
                minX: 0,
                minZ: 0,
                maxX: 20,
                maxZ: 16,
                floorY: 0,
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement('pl-a', 'asset-machine', REV_A, 5, 0, 5),
                ],
            },
            assetCatalog: [asset('asset-machine', REV_A)],
        });
        data.scheduler.flush();
        data.adapter.setSelection(['pl-a']);
        const overview = data.adapter.getDiagnostics().camera;
        const states = [];
        data.adapter.setWalkthroughStateHandler(value => states.push(value));
        const entered = data.adapter.enterWalkthrough({ placementId: 'pl-a' });
        assert.strictEqual(entered.supported, true);
        assert.strictEqual(entered.active, true);
        assert.strictEqual(entered.locked, true);
        assert.strictEqual(entered.targetPlacementId, 'pl-a');
        assert.strictEqual(entered.obstacleCount, 1);
        assert.strictEqual(FakeControls.instances.at(-1).enabled, false);
        let diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.camera.position.y, 1.7);
        assert.strictEqual(diagnostics.navigation.walkthrough.active, true);

        const beforeMove = diagnostics.camera.position.z;
        data.documentObject.dispatch('keydown', { code: 'KeyW' });
        data.scheduler.flush();
        diagnostics = data.adapter.getDiagnostics();
        assert(diagnostics.camera.position.z < beforeMove);
        data.documentObject.dispatch('keyup', { code: 'KeyW' });
        data.scheduler.flush();
        assert.strictEqual(data.scheduler.pendingCount, 0);

        FakePointerLockControls.instances.at(-1).unlock();
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.navigation.walkthrough.active, false);
        assert.deepStrictEqual(diagnostics.camera, overview);
        assert.strictEqual(FakeControls.instances.at(-1).enabled, true);
        assert(states.some(value => value.active && value.locked));
        assert.strictEqual(states.at(-1).reason, 'pointer_lock_released');
        data.adapter.dispose();
        assert.strictEqual(data.documentObject.listenerCount(), 0);
        assert.strictEqual(data.windowObject.listenerCount(), 0);
        assert.strictEqual(
            FakePointerLockControls.instances.at(-1).disposeCount,
            1
        );
    });

test('Drone mode flies vertically, reports metrics, and restores overview',
    async () => {
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
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement('pl-a', 'asset-machine', REV_A, 8, 0, 8),
                ],
            },
            assetCatalog: [asset('asset-machine', REV_A)],
        });
        data.scheduler.flush();
        data.adapter.setSelection(['pl-a']);
        const before = data.adapter.getDiagnostics();
        assert.strictEqual(before.camera.fov, 45);
        const states = [];
        data.adapter.setDroneStateHandler(value => states.push(value));
        const entered = data.adapter.enterDrone({ placementId: 'pl-a' });
        assert.strictEqual(entered.supported, true);
        assert.strictEqual(entered.active, true);
        assert.strictEqual(entered.locked, true);
        assert.strictEqual(entered.assistedFlight, true);
        assert.strictEqual(entered.obstacleCount, 1);
        assert.ok(entered.bounds.maximum.y >= 30);
        assert.strictEqual(FakeControls.instances.at(-1).enabled, false);
        let diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.camera.fov, 60);
        assert.strictEqual(
            diagnostics.navigation.drone.fieldOfView,
            60
        );
        const altitudeBefore = diagnostics.navigation.drone.altitude;

        data.documentObject.dispatch('keydown', { code: 'Space' });
        data.scheduler.flush();
        diagnostics = data.adapter.getDiagnostics();
        assert.ok(diagnostics.navigation.drone.altitude > altitudeBefore);
        assert.ok(diagnostics.navigation.drone.currentSpeed > 0);
        assert.strictEqual(diagnostics.placementCount, before.placementCount);
        assert.deepStrictEqual(
            diagnostics.modelRootTransform,
            before.modelRootTransform
        );
        data.documentObject.dispatch('keyup', { code: 'Space' });
        data.scheduler.flush();

        FakePointerLockControls.instances.at(-1).unlock();
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.navigation.drone.active, false);
        assert.strictEqual(diagnostics.camera.fov, 45);
        assert.deepStrictEqual(diagnostics.camera, before.camera);
        assert.strictEqual(FakeControls.instances.at(-1).enabled, true);
        assert.ok(states.some(value => value.active && value.locked));
        assert.strictEqual(states.at(-1).reason, 'pointer_lock_released');
        data.adapter.dispose();
    });

test('Drone mode starts from an in-bounds camera without a selected asset',
    async () => {
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
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement('pl-a', 'asset-machine', REV_A, 8, 0, 8),
                ],
            },
            assetCatalog: [asset('asset-machine', REV_A)],
        });
        data.scheduler.flush();
        assert.strictEqual(data.adapter.applyCameraView({
            position: { x: 20, y: 8, z: 15 },
            quaternion: { x: 0, y: 0, z: 0, w: 1 },
            up: { x: 0, y: 1, z: 0 },
            target: { x: 20, y: 8, z: 10 },
            fov: 52,
        }), true);
        assert.strictEqual(data.adapter.getCameraView().fov, 52);

        const entered = data.adapter.enterDrone({ ignoreSelection: true });
        assert.strictEqual(entered.active, true);
        assert.strictEqual(entered.locked, true);
        assert.deepStrictEqual(entered.spawn, { x: 20, y: 8, z: 15 });

        data.adapter.exitDrone('test_complete');
        assert.strictEqual(data.adapter.getCameraView().fov, 52);
        data.adapter.dispose();
    });

test('G hands camera position and heading between Drone and Walkthrough',
    async () => {
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
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement('pl-a', 'asset-machine', REV_A, 8, 0, 8),
                ],
            },
            assetCatalog: [asset('asset-machine', REV_A)],
        });
        data.scheduler.flush();
        const overview = data.adapter.getDiagnostics().camera;
        const heading = { x: 0, y: 0.382683, z: 0, w: 0.92388 };
        assert.strictEqual(data.adapter.applyCameraView({
            position: { x: 20, y: 12, z: 15 },
            quaternion: heading,
            up: { x: 0, y: 1, z: 0 },
            target: { x: 21, y: 12, z: 14 },
            fov: 45,
        }), true);
        const handoffOverview = data.adapter.getDiagnostics().camera;
        data.adapter.enterDrone({ ignoreSelection: true });
        let diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.navigation.drone.active, true);
        assert.strictEqual(diagnostics.camera.position.x, 20);
        assert.strictEqual(diagnostics.camera.position.z, 15);

        data.documentObject.dispatch('keydown', { code: 'KeyG' });
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.navigation.drone.active, false);
        assert.strictEqual(diagnostics.navigation.walkthrough.active, true);
        assert.strictEqual(diagnostics.navigation.walkthrough.locked, true);
        assert.strictEqual(diagnostics.camera.position.x, 20);
        assert.strictEqual(diagnostics.camera.position.y, 1.7);
        assert.strictEqual(diagnostics.camera.position.z, 15);
        assert.deepStrictEqual(diagnostics.camera.quaternion, heading);
        assert.strictEqual(diagnostics.camera.fov, 45);

        data.documentObject.dispatch('keyup', { code: 'KeyG' });
        data.documentObject.dispatch('keydown', { code: 'KeyG' });
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.navigation.walkthrough.active, false);
        assert.strictEqual(diagnostics.navigation.drone.active, true);
        assert.strictEqual(diagnostics.navigation.drone.locked, true);
        assert.strictEqual(diagnostics.camera.position.x, 20);
        assert.strictEqual(diagnostics.camera.position.z, 15);
        assert.deepStrictEqual(diagnostics.camera.quaternion, heading);
        assert.strictEqual(diagnostics.camera.fov, 60);

        data.documentObject.dispatch('keyup', { code: 'KeyG' });
        data.documentObject.dispatch('keydown', { code: 'Escape' });
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.navigation.drone.active, false);
        assert.deepStrictEqual(diagnostics.camera, handoffOverview);
        assert.notDeepStrictEqual(diagnostics.camera, overview);
        data.adapter.dispose();
    });

test('walkthrough context focus requires a nearby center-ray machine hit',
    async () => {
        const contextEvents = [];
        const data = fixture({
            worldBounds: {
                minX: 0,
                minZ: 0,
                maxX: 20,
                maxZ: 16,
                floorY: 0,
            },
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(request.assetId, request.assetDefinitionRevision);
                }
                if (request.stage === 'detail') {
                    return prototype(data.THREE, 'context-detail');
                }
                return null;
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement('pl-context', 'asset-machine', REV_A, 5, 0, 5),
                ],
            },
            assetCatalog: [asset('asset-machine', REV_A)],
        });
        await settleAsync(16);
        data.scheduler.flush();
        data.adapter.setWalkthroughContextHandler(value => {
            contextEvents.push(value);
        });
        const scene = FakeRenderer.instances.at(-1).lastRender.scene;
        let pickObject = null;
        scene.traverse(object => {
            if (object.userData.placementId === 'pl-context') pickObject = object;
        });
        assert(pickObject);
        data.adapter.setSelection('pl-context');
        const entered = data.adapter.enterWalkthrough({
            placementId: 'pl-context',
        });
        assert.strictEqual(entered.active, true);
        FakeRaycaster.nextHits = [{
            object: pickObject,
            point: { x: 5, y: 1, z: 5 },
        }];
        data.adapter.invalidate();
        data.scheduler.flush();
        const focused = data.adapter.getWalkthroughContextFocus();
        assert.strictEqual(focused.placementId, 'pl-context');
        assert.strictEqual(focused.lineOfSight, true);
        assert.strictEqual(focused.focusSource, 'center_ray');
        assert(focused.distanceMeters <= 5);
        assert.strictEqual(
            data.adapter.getDiagnostics().walkthroughContextFocus.placementId,
            'pl-context'
        );

        FakeRaycaster.nextHits = [];
        data.adapter.invalidate();
        data.scheduler.flush();
        assert.strictEqual(data.adapter.getWalkthroughContextFocus(), null);
        assert.strictEqual(contextEvents.at(-1), null);
        data.adapter.exitWalkthrough('test_complete');
        data.adapter.dispose();
        FakeRaycaster.nextHits = [];
    });

test('walkthrough click targets route deterministically and manual input cancels',
    async () => {
        const data = fixture({
            worldBounds: {
                minX: -10,
                minZ: -10,
                maxX: 10,
                maxZ: 10,
                floorY: 0,
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement('pl-a', 'asset-machine', REV_A, 5, 0, 5),
                ],
            },
            assetCatalog: [asset('asset-machine', REV_A)],
        });
        data.scheduler.flush();
        data.adapter.enterWalkthrough({
            worldPoint: { x: -8, y: 0, z: -8 },
            ignoreSelection: true,
        });
        const canvas = FakeRenderer.instances.at(-1).domElement;
        canvas.dispatch('pointerup', { button: 0 });
        let walkthrough = data.adapter.getWalkthroughState();
        assert.strictEqual(walkthrough.route.active, true);
        assert.deepStrictEqual(walkthrough.route.destination, { x: 0, z: 0 });
        assert(data.scheduler.pendingCount > 0);

        data.documentObject.dispatch('keydown', { code: 'KeyD' });
        walkthrough = data.adapter.getWalkthroughState();
        assert.strictEqual(walkthrough.route.active, false);
        assert.strictEqual(walkthrough.route.reason, 'manual_input');
        data.documentObject.dispatch('keyup', { code: 'KeyD' });
        data.adapter.exitWalkthrough('test_complete');
        data.adapter.dispose();
    });

test('named camera views round-trip without changing facility geometry',
    async () => {
        const data = fixture();
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement('pl-a', 'asset-machine', REV_A, 4, 0, 4),
                ],
            },
            assetCatalog: [asset('asset-machine', REV_A)],
        });
        const rootBefore = data.adapter.getDiagnostics().modelRootTransform;
        const saved = data.adapter.getCameraView();
        data.adapter.topView();
        assert.strictEqual(data.adapter.applyCameraView(saved), true);
        const diagnostics = data.adapter.getDiagnostics();
        assert.deepStrictEqual(diagnostics.camera.position, saved.position);
        assert.deepStrictEqual(diagnostics.camera.target, saved.target);
        assert.deepStrictEqual(diagnostics.modelRootTransform, rootBefore);
        data.adapter.dispose();
    });

test('3D viewport renders a bounded factory floor and metric grid outside placement state', async () => {
    let backgroundCalls = 0;
    let currentTheme = 'dark';
    let themeListener = null;
    let themeCleanupCalls = 0;
    const background = { kind: 'cad-studio-background' };
    const data = fixture({
        worldBounds: {
            minX: 0,
            minZ: 0,
            maxX: 40,
            maxZ: 30,
            floorY: 0,
        },
        document: {
            documentElement: {
                getAttribute() {
                    return currentTheme;
                },
            },
        },
        subscribeThemeChange(handler) {
            themeListener = handler;
            return () => {
                themeCleanupCalls += 1;
                themeListener = null;
            };
        },
        backgroundFactory(context) {
            backgroundCalls += 1;
            assert.strictEqual(context.theme, currentTheme);
            return background;
        },
    });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: { placements: [] },
        assetCatalog: [],
    });
    data.scheduler.flush();

    const diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(backgroundCalls, 1);
    assert.deepStrictEqual(diagnostics.environment, {
        floorVisible: true,
        gridVisible: true,
        axesVisible: true,
        floorY: 0,
        width: 40,
        depth: 30,
        spacing: 1,
        majorSpacing: 5,
        minorLineCount: 56,
        majorLineCount: 16,
        axisLength: 10,
        origin: { x: 0, y: 0, z: 0 },
    });
    assert.strictEqual(diagnostics.placementCount, 0);

    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    assert.strictEqual(scene.background, background);
    let floor = null;
    let gridCount = 0;
    let axisCount = 0;
    scene.traverse(object => {
        if (object.name === 'InspectorProFacilityFloor') floor = object;
        if (object.userData.facilityEnvironment === 'floor-grid') {
            gridCount += 1;
        }
        if (String(object.userData.facilityEnvironment || '')
                .startsWith('floor-axis-')) axisCount += 1;
    });
    assert(floor);
    assert.strictEqual(floor.position.x, 20);
    assert.strictEqual(floor.position.y, -0.01);
    assert.strictEqual(floor.position.z, 15);
    assert.strictEqual(gridCount, 2);
    assert.strictEqual(axisCount, 2);

    assert.strictEqual(data.adapter.setEnvironmentSettings({
        worldBounds: {
            minX: 0,
            minZ: 0,
            maxX: 55,
            maxZ: 36,
            floorY: 0,
        },
        floorGridSpacing: 2,
        floorMajorGridSpacing: 10,
    }), true);
    data.scheduler.flush();
    assert.deepStrictEqual(data.adapter.getDiagnostics().environment, {
        floorVisible: true,
        gridVisible: true,
        axesVisible: true,
        floorY: 0,
        width: 55,
        depth: 36,
        spacing: 2,
        majorSpacing: 10,
        minorLineCount: 37,
        majorLineCount: 10,
        axisLength: 20,
        origin: { x: 0, y: 0, z: 0 },
    });
    let resizedFloor = null;
    scene.traverse(object => {
        if (object.name === 'InspectorProFacilityFloor') resizedFloor = object;
    });
    assert(resizedFloor);
    assert.strictEqual(resizedFloor.position.x, 27.5);
    assert.strictEqual(resizedFloor.position.z, 18);

    currentTheme = 'light';
    themeListener();
    data.scheduler.flush();
    assert.strictEqual(backgroundCalls, 2);
    assert.strictEqual(data.adapter.getDiagnostics().environment.gridVisible, true);

    FakeRaycaster.nextHits = [{ object: floor, instanceId: null }];
    assert.strictEqual(
        data.adapter.pick({ clientX: 200, clientY: 200 }),
        null
    );
    data.adapter.dispose();
    assert.strictEqual(themeCleanupCalls, 1);
    assert.strictEqual(themeListener, null);
});

test('3D viewport projects semantic floor markings from shared world coordinates', async () => {
    const data = fixture();
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [],
            floorMarkings: [{
                markingId: 'fm-crosswalk',
                markingType: 'crosswalk',
                label: 'Main aisle crossing',
                semanticRole: 'pedestrian_lane',
                transform: {
                    position: { x: 7, y: 0, z: 5 },
                    rotationDegrees: 90,
                },
                width: 2.4,
                depth: 2,
                fillColor: '#ffffff',
                strokeColor: '#1f2937',
                opacity: 0.85,
                text: '',
                positionMode: 'manual',
                metadata: {},
                evidence: [],
            }],
        },
        assetCatalog: [],
    });
    data.scheduler.flush();
    const diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.floorMarkingCount, 1);
    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    let marking = null;
    let gridY = null;
    scene.traverse(object => {
        if (object.userData.facilityFloorMarking === true) marking = object;
        if (object.userData.facilityEnvironment === 'floor-grid'
                && object.geometry
                && object.geometry.attributes
                && object.geometry.attributes.position) {
            const values = object.geometry.attributes.position.array;
            if (values.length >= 2) gridY = values[1];
        }
    });
    assert(marking);
    assert(Number.isFinite(gridY));
    assert.strictEqual(marking.userData.markingId, 'fm-crosswalk');
    assert.strictEqual(marking.userData.semanticRole, 'pedestrian_lane');
    assert.strictEqual(marking.position.x, 7);
    assert.ok(Math.abs(marking.position.y - 0.003) < 0.00001);
    assert.ok(gridY < marking.position.y);
    assert.strictEqual(marking.position.z, 5);
    data.adapter.dispose();
});

test('3D viewport projects semantic aisles from native route coordinates', async () => {
    const data = fixture();
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [],
            routes: [{
                routeId: 'rt-main-forklift',
                label: 'Main Forklift Boulevard',
                routeKind: 'forklift',
                sourceEndpoint: {
                    kind: 'world_point',
                    position: { x: 2, y: 0, z: 3 },
                },
                targetEndpoint: {
                    kind: 'world_point',
                    position: { x: 12, y: 0, z: 3 },
                },
                routingMode: 'vehicle',
                centerline: [
                    { x: 2, y: 0, z: 3 },
                    { x: 7, y: 0, z: 3 },
                    { x: 12, y: 0, z: 3 },
                ],
                corridorWidth: 3.5,
                extensions: {
                    facilityAisle: {
                        schemaVersion: 1,
                        aisleKind: 'forklift',
                        direction: 'two_way',
                        color: '#d9a514',
                        clearanceEvidenceStatus: 'unverified',
                    },
                },
            }],
        },
        assetCatalog: [],
    });
    data.scheduler.flush();
    const diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.routeCount, 1);
    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    let aisle = null;
    scene.traverse(object => {
        if (object.userData.facilityAisle === true) aisle = object;
    });
    assert(aisle);
    assert.strictEqual(aisle.userData.routeId, 'rt-main-forklift');
    assert.strictEqual(aisle.userData.aisleKind, 'forklift');
    assert.strictEqual(aisle.children.length, 2);
    data.adapter.dispose();
});

test('3D direction arrows use procedural floor-paint geometry', async () => {
    const data = fixture();
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [],
            floorMarkings: [{
                markingId: 'fm-arrow',
                markingType: 'direction_arrow',
                label: 'Material flow',
                semanticRole: 'material_flow',
                transform: {
                    position: { x: 4, y: 0, z: 3 },
                    rotationDegrees: 0,
                },
                width: 1.2,
                depth: 2.4,
                fillColor: '#facc15',
                strokeColor: '#111827',
                opacity: 1,
                text: '',
                positionMode: 'manual',
                metadata: {},
                evidence: [],
            }],
        },
        assetCatalog: [],
    });
    data.scheduler.flush();
    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    let marking = null;
    scene.traverse(object => {
        if (object.userData.facilityFloorMarking === true) marking = object;
    });
    assert(marking);
    assert.strictEqual(marking.children.length, 1);
    assert.strictEqual(marking.children[0].geometry.isShapeGeometry, true);
    assert.strictEqual(marking.children[0].material.options.map, undefined);
    assert.strictEqual(marking.children[0].material.options.depthWrite, true);
    assert.strictEqual(marking.children[0].material.options.toneMapped, false);
    assert.ok(Math.abs(marking.position.y - 0.003) < 0.00001);
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

test('full-layout proposal overlays show before and proposed states outside picking',
    async () => {
        const data = fixture();
        data.adapter.mount(data.host);
        const proposedLayout = {
            placements: [
                placement('pl-a', 'asset-machine', REV_A, 10, 0, 0),
                placement('pl-new', 'asset-machine', REV_A, 20, 0, 0),
            ],
        };
        const proposal = {
            active: true,
            newPlacementIds: ['pl-new'],
            movedPlacementIds: ['pl-a'],
            removedPlacementIds: ['pl-removed'],
            beforePlacements: [
                placement('pl-a', 'asset-machine', REV_A, 0, 0, 0),
                placement(
                    'pl-removed',
                    'asset-machine',
                    REV_A,
                    -5,
                    0,
                    0
                ),
            ],
            proposedPlacements: proposedLayout.placements,
        };
        const proposedBefore = JSON.stringify(proposedLayout);
        const previewBefore = JSON.stringify(proposal);
        await data.adapter.setScene({
            layout: proposedLayout,
            assetCatalog: [asset('asset-machine', REV_A)],
        });
        assert.strictEqual(data.adapter.setProposalPreview(proposal), true);
        data.scheduler.flush();
        const roles = [];
        FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => {
            if (object.userData
                    && object.userData.facilityProposalPreview) {
                roles.push(object.userData.facilityProposalPreview);
            }
        });
        roles.sort();
        assert.deepStrictEqual(roles, ['before', 'moved', 'new', 'removed']);
        let diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.proposalPreviewActive, true);
        assert.strictEqual(diagnostics.proposalBeforeCount, 2);
        assert.strictEqual(diagnostics.proposalProposedCount, 2);
        assert.strictEqual(diagnostics.placementCount, 2);
        assert.ok(diagnostics.worldBounds.minimum.x < -5);
        assert.ok(diagnostics.worldBounds.maximum.x > 20);
        assert.strictEqual(JSON.stringify(proposedLayout), proposedBefore);
        assert.strictEqual(JSON.stringify(proposal), previewBefore);

        assert.strictEqual(data.adapter.setProposalPreview(null), true);
        data.scheduler.flush();
        diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.proposalPreviewActive, false);
        let proposalObjectCount = 0;
        FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => {
            if (object.userData
                    && object.userData.facilityProposalPreview) {
                proposalObjectCount += 1;
            }
        });
        assert.strictEqual(proposalObjectCount, 0);
        assert.strictEqual(diagnostics.placementCount, 2);
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
    await new Promise(resolve => setImmediate(resolve));
    diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.status, 'ready');
    assert.strictEqual(diagnostics.contextLost, false);
    assert.strictEqual(diagnostics.degraded, false);
    assert(statuses.includes('degraded'));
    data.adapter.dispose();
});

test('context restoration replays edits made while 3D was degraded and clears dismissed preview', async () => {
    const data = fixture();
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-before', 'asset-machine', REV_A, 0, 0, 0),
            ],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    const canvas = FakeRenderer.instances.at(-1).domElement;
    canvas.dispatch('webglcontextlost');

    const editedLayout = {
        placements: [
            placement('pl-after-a', 'asset-machine', REV_A, 4, 0, 0),
            placement('pl-after-b', 'asset-machine', REV_A, 8, 0, 0),
        ],
    };
    await data.adapter.setScene({
        layout: editedLayout,
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    assert.strictEqual(data.adapter.setProposalPreview({
        active: true,
        newPlacementIds: ['pl-after-b'],
        movedPlacementIds: [],
        removedPlacementIds: [],
        beforePlacements: [],
        proposedPlacements: editedLayout.placements,
    }), false);
    assert.strictEqual(data.adapter.setProposalPreview(null), true);
    let diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.contextLost, true);
    assert.strictEqual(diagnostics.placementCount, 2);
    assert.strictEqual(diagnostics.proposalPreviewActive, false);

    canvas.dispatch('webglcontextrestored');
    await new Promise(resolve => setImmediate(resolve));
    diagnostics = data.adapter.getDiagnostics();
    assert.strictEqual(diagnostics.status, 'ready');
    assert.strictEqual(diagnostics.contextLost, false);
    assert.strictEqual(diagnostics.placementCount, 2);
    assert.strictEqual(diagnostics.proposalPreviewActive, false);
    assert.deepStrictEqual(
        diagnostics.representationGroups.flatMap(
            group => group.placementIds
        ).sort(),
        ['pl-after-a', 'pl-after-b']
    );
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
    assert.strictEqual(diagnostics.lifecycle.listenerCount, 14);
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
