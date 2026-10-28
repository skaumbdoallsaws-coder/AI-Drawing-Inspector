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
globalThis.InspectorProFacilityNavigationAuthoring = require(
    '../static/facility_layout_navigation_authoring.js'
);

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

    makeScale(x, y, z) {
        this.composed = {
            position: { x: 0, y: 0, z: 0 },
            quaternion: { x: 0, y: 0, z: 0, w: 1 },
            scale: { x, y, z },
        };
        this.elements = null;
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
        this.rotation = { x: 0, y: 0, z: 0 };
        this.visible = true;
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

    removeFromParent() {
        if (this.parent) this.parent.remove(this);
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
        this.attributes = { position: { count: 0 } };
    }

    setAttribute(name, attribute) { this.attributes[name] = attribute; return this; }

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

class FakeExtrudeGeometry extends FakeShapeGeometry {
    constructor(shape, options) { super(shape); this.options = options; }
    rotateX(angle) { this.rotationX = angle; }
}

class FakePlaneGeometry extends FakeGeometry {
    constructor(width, height) { super(width, height); this.isPlaneGeometry = true; }
    rotateX(angle) { this.rotationX = angle; return this; }
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

    computeVertexNormals() {
        this.normalsComputed = true;
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
        clone.roughness = this.roughness;
        clone.metalness = this.metalness;
        clone.map = this.map;
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
        const copy = new FakeMatrix4();
        copy.composed = matrix.composed
            ? JSON.parse(JSON.stringify(matrix.composed)) : null;
        copy.multiplied = matrix.multiplied;
        copy.elements = matrix.elements ? matrix.elements.slice() : null;
        this.matrices[index] = copy;
    }

    getMatrixAt(index, target) {
        const matrix = this.matrices[index];
        target.composed = matrix && matrix.composed
            ? JSON.parse(JSON.stringify(matrix.composed)) : null;
        target.multiplied = matrix ? matrix.multiplied : null;
        target.elements = matrix && matrix.elements
            ? matrix.elements.slice() : null;
        return target;
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
        flush(timestamp) {
            const current = Array.from(callbacks.entries());
            callbacks.clear();
            current.forEach(([, callback]) => callback(
                timestamp === undefined ? 16 : timestamp
            ));
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
        ExtrudeGeometry: FakeExtrudeGeometry,
        BoxGeometry: FakeGeometry,
        PlaneGeometry: FakePlaneGeometry,
        SphereGeometry: FakeGeometry,
        CylinderGeometry: FakeGeometry,
        LatheGeometry: FakeGeometry,
        Bone: FakeObject3D,
        Skeleton: class { dispose() {} },
        SkinnedMesh: class extends FakeMesh { bind() {} },
        Uint16BufferAttribute: FakeFloat32BufferAttribute,
        SplineCurve: class { constructor(points) { this.points = points; } getPoints() { return this.points; } },
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
const REV_C = 'c'.repeat(64);

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

function motionPayload(options) {
    const value = options || {};
    const layoutRevision = value.layoutRevision || REV_B;
    const movement = {
        outcome: value.outcome || 'accepted',
        movementId: value.movementId || 'movement-one',
        routeId: value.routeId || 'route-one',
        vehicleProfileRef: {
            vehicleProfileId: 'vehicle-profile-one',
            vehicleProfileRevision: REV_A,
        },
        routeFingerprint: 'route-fingerprint-one',
        plannerDurationEstimateSeconds: value.duration || 5,
        distanceMeters: 10,
        poses: [
            { x: 1, z: 2, heading: Math.PI - 0.1, gear: 'reverse' },
            { x: 11, z: 2, heading: -Math.PI + 0.1, gear: 'forward' },
        ],
        cumulativeDistance: [0, 10],
        carriedPlacementIds: value.carriedPlacementIds || [],
        sweptEnvelope: {
            valid: true,
            sampledPoseCount: 6,
            projectedSampleCount: 6,
            sampleSpacingMeters: 2,
            effectiveWidthMeters: 1,
            effectiveLengthMeters: 2,
            sweptEnvelopeRevision: 'facility-swept-envelope-v1',
            sweptBounds: {
                minimum: { x: 0, z: 1.5 },
                maximum: { x: 12, z: 2.5 },
            },
            geometry: {
                polygons: [{
                    exterior: [
                        { x: 0, z: 1.5 },
                        { x: 12, z: 1.5 },
                        { x: 12, z: 2.5 },
                        { x: 0, z: 2.5 },
                    ],
                    holes: [],
                }],
                ringOrientation: {
                    exterior: 'counterclockwise',
                    holes: 'clockwise',
                },
                startVertexRule: 'lowest_x_then_z_lexicographic',
                precisionDecimals: 6,
                polygonSortKey: 'first_vertex_then_area',
            },
            findings: [],
        },
        clearance: {
            sampleSpacingMeters: 2,
            samples: [0, 2, 4, 6, 8, 10].map(distance => ({
                distanceMeters: distance,
                nearestObstacleIds: ['obstacle-one'],
                clearanceMeters: 3 + distance / 10,
            })),
        },
    };
    if (value.vehiclePlacementId) {
        movement.vehiclePlacementId = value.vehiclePlacementId;
    }
    if (value.laneBinding) movement.laneBinding = value.laneBinding;
    if (value.poses) {
        movement.poses = value.poses;
        movement.cumulativeDistance = value.cumulativeDistance;
        movement.distanceMeters = value.cumulativeDistance.at(-1);
    }
    return {
        package: {
            schemaVersion: 'facility-motion-package-v1',
            packageId: value.packageId || 'fmp-one',
            plannerVersions: {
                routingEngineVersion: 'facility-routing-v1',
                routerVersion: 'heading-lattice-v1',
            },
            layoutRevision,
            obstacleContextRevision: 'obstacles-one',
            qualification: (
                'Replays one deterministically planned traversal against '
                + 'nominal geometry at an exact vehicle revision. It does not '
                + 'establish throughput, congestion, traffic safety, or '
                + 'regulatory compliance.'
            ),
            movement,
        },
        vehicleProfile: {
            vehicleProfileId: 'vehicle-profile-one',
            vehicleProfileRevision: REV_A,
            displayName: 'Fixture forklift',
            overallDimensions: { length: 2, width: 1, height: 2 },
            footprint: [
                { x: -1, z: -0.5 },
                { x: 1, z: -0.5 },
                { x: 1, z: 0.5 },
                { x: -1, z: 0.5 },
            ],
        },
    };
}

function motionPayloadV2(options) {
    const value = options || {};
    const payload = motionPayload(value);
    const packageValue = payload.package;
    packageValue.schemaVersion = 'facility-motion-package-v2';
    packageValue.generationLayoutRevision = packageValue.layoutRevision;
    delete packageValue.layoutRevision;
    packageValue.validationContextFingerprint = value.validationFingerprint || REV_A;
    packageValue.validationContextSpec = {
        schemaVersion: 'facility-motion-validation-context-spec-v1',
    };
    if (value.includeActiveFingerprint !== false) {
        payload.activeValidationContextFingerprint = value.activeFingerprint || REV_A;
    }
    return payload;
}

function navigationMotionPayload(options) {
    const value = options || {};
    const placementId = value.placementId || 'actor-placement';
    const packageId = value.packageId || 'fmp-navigation-one';
    return {
        package: {
            schemaVersion: 'facility-motion-package-v3',
            packageId,
            plannerVersions: {
                pedestrian: 'facility-pedestrian-journey-v1',
                motion_serializer: 'facility-motion-package-v3',
            },
            generationLayoutRevision: REV_B,
            validationContextFingerprint: REV_A,
            navigationSnapshotId: 'nss-navigation-one',
            qualification: (
                'Replays one accepted revision-bound navigation journey for an existing '
                + 'placed actor on a shared display clock. Presentation timing is not process '
                + 'timing and does not establish throughput, congestion, staffing, traffic '
                + 'safety, or regulatory compliance.'
            ),
            movement: {
                outcome: 'accepted',
                movementId: 'fmm-navigation-one',
                movementProgramId: 'nmp-navigation-one',
                journeySolutionId: 'njs-navigation-one',
                navigationSnapshotId: 'nss-navigation-one',
                actorClass: 'pedestrian',
                actorPlacementId: placementId,
                actorProfileRef: {
                    profileKind: 'pedestrian',
                    profileId: 'operator-profile-one',
                    profileRevision: REV_A,
                },
                presentationDurationSeconds: 8,
                presentationTimingAuthority: 'derived_display_only',
                distanceMeters: 16,
                poses: value.poses || [
                    { x: 1, z: 2, heading: 0, gear: 'forward' },
                    { x: 9, z: 2, heading: 0, gear: 'forward' },
                    { x: 1, z: 2, heading: Math.PI, gear: 'forward' },
                ],
                cumulativeDistance: value.cumulativeDistance || [0, 8, 16],
                validation: {
                    identity: 'pass',
                    topology: 'pass',
                    direction: 'pass',
                    physical: 'pass',
                    authority: 'pass',
                    stale: 'pass',
                },
                sourceRevisions: { layout: REV_B },
            },
        },
        actorProfile: {
            profileKind: 'pedestrian',
            profileId: 'operator-profile-one',
            profileRevision: REV_A,
            footprint: [
                { x: -0.3, z: -0.3 },
                { x: 0.3, z: -0.3 },
                { x: 0.3, z: 0.3 },
                { x: -0.3, z: 0.3 },
            ],
            overallDimensions: { length: 0.6, width: 0.6, height: 1.8 },
        },
        activeValidationContextFingerprint: REV_A,
    };
}

function navigationActivityPayload() {
    const motion = navigationMotionPayload({ placementId: 'actor-placement' });
    const actor = {
        actorId: 'actor-navigation-one',
        actorType: 'operator',
        label: 'Existing operator',
        motionPackageId: motion.package.packageId,
        returnMotionPackageId: null,
        endTransferMotionPackageId: null,
        startTransferMotionPackageId: null,
        cycleMotionPackageIds: [],
        placementId: 'actor-placement',
        assetDefinitionRef: {
            assetId: 'activity-asset',
            assetDefinitionRevision: REV_A,
        },
        routeId: 'nmp-navigation-one',
        departmentZoneIds: ['zone-one'],
        startOffsetSeconds: 0,
        repeat: true,
        loopMode: 'journey_cycle',
        endpointTurnSeconds: 0,
        visualAlignment: {
            forwardAxis: '+Z',
            authority: 'curated_revision_bound_visual_review',
            evidenceArtifact: 'fixture.glb',
        },
    };
    return {
        scenario: {
            schemaVersion: 'facility-activity-scenario-v7',
            scenarioId: 'fas-navigation-one',
            layoutRevision: REV_B,
            label: 'Navigation activity',
            qualification: (
                'Prototype navigation playback presents accepted revision-bound actor '
                + 'journeys on one shared display clock. Path intersections and sampled '
                + 'center proximity are presentation diagnostics, not safety, capacity, '
                + 'staffing, timing, or regulatory findings.'
            ),
            prototypeMode: true,
            repeat: true,
            cycleDurationSeconds: 8,
            actors: [actor],
            leanMotion: activityPayload().scenario.leanMotion,
            navigationPresentation: {
                schemaVersion: 'facility-navigation-presentation-v1',
                qualification: (
                    'Derived display diagnostics preserve accepted journey geometry and do not '
                    + 'reschedule actors or alter paths to conceal visual overlap.'
                ),
                sharedClock: true,
                processTimingClaimed: false,
                generatedCollisionAvoidanceOffsets: false,
                phaseOffsets: [{
                    actorId: actor.actorId,
                    offsetSeconds: 0,
                    authority: 'none',
                }],
                pathBindings: [{
                    pathBindingId: 'npb-navigation-one',
                    actorId: actor.actorId,
                    actorClass: 'pedestrian',
                    journeySolutionId: 'njs-navigation-one',
                    motionPackageId: motion.package.packageId,
                    closed: true,
                }],
                pathIntersections: [],
                sampledProximity: {
                    sampleCount: 21,
                    pairMinimums: [],
                    qualification: (
                        'Center-distance samples on the shared display clock; '
                        + 'not a collision or safety assessment.'
                    ),
                },
                handoffResultIds: [],
            },
            stationaryEvidence: {
                placementCount: 1,
                assetTypeCount: 1,
                reason: 'Fixed machinery has no revision-bound track.',
                evidenceStatus: 'unknown',
            },
            unavailableActivity: [],
        },
        actorPayloads: { [motion.package.packageId]: motion },
    };
}

function reviewedCycleNavigationActivityPayload(options) {
    const inspection = options && options.inspection === true;
    const segmentSpecs = inspection ? [
        {
            phase: 'inspection_pick',
            poses: [
                { x: 0, z: 0, heading: 0, gear: 'forward' },
                { x: 2, z: 0, heading: 0, gear: 'forward' },
            ],
            distance: 2,
        },
        {
            phase: 'inspection_place',
            poses: [
                { x: 2, z: 0, heading: 0, gear: 'forward' },
                { x: 4, z: 0, heading: 0, gear: 'forward' },
            ],
            distance: 2,
        },
        {
            phase: 'return_empty',
            poses: [
                { x: 4, z: 0, heading: Math.PI / 2, gear: 'forward' },
                { x: 4, z: 2, heading: Math.PI, gear: 'forward' },
                { x: 0, z: 2, heading: -Math.PI / 2, gear: 'forward' },
                { x: 0, z: 0, heading: -Math.PI / 2, gear: 'forward' },
            ],
            distance: 8,
            cumulativeDistance: [0, 2, 6, 8],
        },
    ] : [
        {
            phase: 'carry_in',
            poses: [
                { x: 0, z: 0, heading: 0, gear: 'forward' },
                { x: 2, z: 0, heading: 0, gear: 'forward' },
            ],
            distance: 2,
        },
        {
            phase: 'carry_out',
            poses: [
                { x: 2, z: 0, heading: Math.PI / 2, gear: 'forward' },
                { x: 2, z: 2, heading: Math.PI / 2, gear: 'forward' },
            ],
            distance: 2,
        },
        {
            phase: 'return_empty',
            poses: [
                { x: 2, z: 2, heading: -3 * Math.PI / 4, gear: 'forward' },
                { x: 0, z: 0, heading: -3 * Math.PI / 4, gear: 'forward' },
            ],
            distance: Math.sqrt(8),
        },
    ];
    const segments = segmentSpecs.map(function (spec) {
        const family = inspection ? 'inspection' : 'packaging';
        const packageId = 'fmp-' + family + '-' + spec.phase;
        const payload = navigationMotionPayload({
            placementId: 'actor-placement',
            packageId,
            poses: spec.poses,
            cumulativeDistance: spec.cumulativeDistance
                || [0, spec.distance],
        });
        Object.assign(payload.package.movement, {
            movementId: 'fmm-' + family + '-' + spec.phase,
            movementProgramId: 'nmp-' + family + '-' + spec.phase,
            journeySolutionId: 'njs-' + family + '-' + spec.phase,
            presentationDurationSeconds: 2,
            distanceMeters: spec.distance,
        });
        return { spec, payload };
    });
    const result = navigationActivityPayload();
    const actor = result.scenario.actors[0];
    actor.motionPackageId = segments[0].payload.package.packageId;
    actor.cycleMotionPackageIds = segments.map(function (segment) {
        return segment.payload.package.packageId;
    });
    actor.routeId = segments[0].payload.package.movement.movementProgramId;
    actor.loopMode = 'closed_path';
    actor.endpointTurnSeconds = 1;
    result.scenario.cycleDurationSeconds = 9;
    result.scenario.navigationPresentation.pathBindings[0].journeySolutionId =
        segments[0].payload.package.movement.journeySolutionId;
    result.scenario.navigationPresentation.pathBindings[0].motionPackageId =
        segments[0].payload.package.packageId;
    result.actorPayloads = Object.fromEntries(segments.map(function (segment) {
        return [segment.payload.package.packageId, segment.payload];
    }));
    result.candidatePresentation = {
        schemaVersion: 'facility-reference-movement-candidates-v1',
        sourceLayoutId: 'fl-reference-manual-20260812',
        sourceLayoutRevision: REV_A,
        authority: 'inferred_candidate',
        reviewStatus: 'pending',
        productionEligible: false,
        candidateCounts: {
            operators: 1,
            vehicles: 0,
            handoffs: 0,
            displayedActors: 1,
            displayedHandoffs: 0,
            unavailableActors: 0,
            partialPrograms: 0,
            suppressedStationaryOperators: 0,
        },
        suppressedOperatorPlacementIds: [],
        handoffs: [],
        [inspection ? 'inspectionPathLegend' : 'packagingPathLegend']:
            inspection ? [
                {
                    phase: 'inspection_pick',
                    label: 'Pick to inspect',
                    lineStyle: 'solid',
                },
                {
                    phase: 'inspection_place',
                    label: 'Inspect to place',
                    lineStyle: 'solid',
                },
                {
                    phase: 'return_empty',
                    label: 'Return empty',
                    lineStyle: 'dashed',
                },
            ] : [
                { phase: 'carry_in', label: 'Carry in', lineStyle: 'solid' },
                { phase: 'carry_out', label: 'Carry out', lineStyle: 'solid' },
                {
                    phase: 'return_empty',
                    label: 'Return empty',
                    lineStyle: 'dashed',
                },
            ],
        programEvidence: [{
            actorPlacementId: actor.placementId,
            pathSegments: segments.map(function (segment) {
                return {
                    phase: segment.spec.phase,
                    movementProgramId:
                        segment.payload.package.movement.movementProgramId,
                    motionPackageId: segment.payload.package.packageId,
                    distanceMeters: segment.spec.distance,
                    turnCount: 0,
                };
            }),
            interactionPauseSeconds: 1,
            timingAuthority: 'derived_display_only',
        }],
        qualification: inspection
            ? 'Reviewed Inspection sequence; prototype timing only.'
            : 'Reviewed Packaging sequence; prototype timing only.',
        presentationFingerprint: REV_B,
    };
    return result;
}

function packagingNavigationActivityPayload() {
    return reviewedCycleNavigationActivityPayload({ inspection: false });
}

function inspectionNavigationActivityPayload() {
    return reviewedCycleNavigationActivityPayload({ inspection: true });
}

function activityPayload(options) {
    const value = options || {};
    const actorPlacementId = value.placementId || 'actor-placement';
    const payload = motionPayload({
        layoutRevision: REV_B,
        vehiclePlacementId: actorPlacementId,
    });
    payload.package.movement.poses = [
        { x: 1, z: 2, heading: 0, gear: 'forward' },
        { x: 11, z: 2, heading: 0, gear: 'forward' },
    ];
    payload.package.movement.cumulativeDistance = [0, 10];
    payload.package.movement.plannerDurationEstimateSeconds = 5;
    return {
        scenario: {
            schemaVersion: 'facility-activity-scenario-v6',
            scenarioId: 'fas-fixture',
            layoutRevision: REV_B,
            label: 'Fixture activity',
            qualification: (
                'Prototype activity playback presents independently revision-bound '
                + 'route results on one shared display clock. It is not a discrete-event '
                + 'simulation and does not establish traffic safety, throughput, '
                + 'utilization, staffing, machine cycles, or regulatory compliance.'
            ),
            prototypeMode: true,
            repeat: true,
            cycleDurationSeconds: 12,
            actors: [{
                actorId: 'actor-fixture',
                actorType: value.actorType || 'operator',
                label: 'Fixture actor',
                motionPackageId: payload.package.packageId,
                returnMotionPackageId: null,
                endTransferMotionPackageId: null,
                startTransferMotionPackageId: null,
                cycleMotionPackageIds: [],
                placementId: actorPlacementId,
                assetDefinitionRef: {
                    assetId: value.assetId || 'activity-asset',
                    assetDefinitionRevision: REV_A,
                },
                routeId: payload.package.movement.routeId,
                departmentZoneIds: ['zone-one'],
                startOffsetSeconds: 0,
                repeat: true,
                loopMode: 'ping_pong',
                endpointTurnSeconds: 1,
                visualAlignment: {
                    forwardAxis: value.forwardAxis || '+Z',
                    authority: 'curated_revision_bound_visual_review',
                    evidenceArtifact: 'fixture.glb',
                },
            }],
            leanMotion: value.leanMotion || {
                schemaVersion: 'facility-lean-motion-v3',
                qualification: (
                    'Derived prototype motion borrows existing placed operator identities, '
                    + 'assigns them to nearby placed stations, and routes the responsible '
                    + 'endpoint operators to derived FIFO handoff points. Material handoff '
                    + 'lines show workpiece transfer relationships, not operator walking. '
                    + 'The routes are geometrically feasible paths, not time-optimal standard '
                    + 'work, and do not establish staffing, task frequency, synchronized '
                    + 'transfer timing, capacity, traffic safety, or compliance.'
                ),
                evidenceStatus: 'derived',
                operatorPaths: [],
                pedestrianConnections: [],
                assistanceGates: [],
                materialHandoffs: [],
                fifoPoints: [],
            },
            stationaryEvidence: {
                placementCount: 0,
                assetTypeCount: 0,
                reason: 'No stationary fixture assets.',
                evidenceStatus: 'unknown',
            },
            unavailableActivity: [],
        },
        actorPayloads: {
            [payload.package.packageId]: payload,
        },
    };
}

function pairedLaneActivityPayload() {
    const actorPlacementId = 'actor-placement';
    const routeId = 'route-one';
    const lane = (travelDirection, z, markingId) => ({
        schemaVersion: 1,
        bindingVersion: 'facility-motion-lane-binding-v1',
        status: 'direction_markings',
        travelDirection,
        routeId,
        sourceMarkingIds: [markingId],
        lateralOffsetMeters: travelDirection === 'forward' ? -2 : 2,
        laneCenterline: travelDirection === 'forward'
            ? [{ x: 1, y: 0, z }, { x: 11, y: 0, z }]
            : [{ x: 11, y: 0, z }, { x: 1, y: 0, z }],
        evidenceStatus: 'derived',
        qualification: 'Fixture direction-marking lane.',
    });
    const create = (packageId, poses, cumulativeDistance, duration, laneBinding) => (
        motionPayload({
            packageId,
            movementId: packageId + '-movement',
            routeId,
            layoutRevision: REV_B,
            vehiclePlacementId: actorPlacementId,
            poses,
            cumulativeDistance,
            duration,
            laneBinding,
        })
    );
    const outbound = create(
        'fmp-outbound',
        [
            { x: 1, z: 2, heading: 0, gear: 'forward' },
            { x: 11, z: 2, heading: 0, gear: 'forward' },
        ],
        [0, 10],
        5,
        lane('forward', 2, 'marking-forward')
    );
    const endTransfer = create(
        'fmp-end-transfer',
        [
            { x: 11, z: 2, heading: 0, gear: 'forward' },
            { x: 12, z: 3, heading: Math.PI / 2, gear: 'forward' },
            { x: 11, z: 4, heading: Math.PI, gear: 'forward' },
        ],
        [0, Math.SQRT2, 2 * Math.SQRT2],
        1
    );
    const returnLane = create(
        'fmp-return',
        [
            { x: 11, z: 4, heading: Math.PI, gear: 'forward' },
            { x: 1, z: 4, heading: Math.PI, gear: 'forward' },
        ],
        [0, 10],
        5,
        lane('reverse', 4, 'marking-reverse')
    );
    const startTransfer = create(
        'fmp-start-transfer',
        [
            { x: 1, z: 4, heading: Math.PI, gear: 'forward' },
            { x: 0, z: 3, heading: -Math.PI / 2, gear: 'forward' },
            { x: 1, z: 2, heading: 0, gear: 'forward' },
        ],
        [0, Math.SQRT2, 2 * Math.SQRT2],
        1
    );
    const payload = activityPayload({ actorType: 'vehicle' });
    const actor = payload.scenario.actors[0];
    actor.motionPackageId = outbound.package.packageId;
    actor.returnMotionPackageId = returnLane.package.packageId;
    actor.endTransferMotionPackageId = endTransfer.package.packageId;
    actor.startTransferMotionPackageId = startTransfer.package.packageId;
    actor.loopMode = 'paired_lanes';
    actor.endpointTurnSeconds = 0;
    actor.routeId = routeId;
    payload.scenario.cycleDurationSeconds = 12;
    payload.actorPayloads = {
        [outbound.package.packageId]: outbound,
        [returnLane.package.packageId]: returnLane,
        [endTransfer.package.packageId]: endTransfer,
        [startTransfer.package.packageId]: startTransfer,
    };
    return payload;
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
    const THREE = options && options.THREE || createThree();
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
    // An unturned three.js camera looks along -Z, which is south on the plan.
    // (Before 2026-10-21 the report gave the bottom of the view instead.)
    assert.ok(Math.abs(reports[0].headingDegrees - 180) < 0.001);
    assert.deepStrictEqual(reports[0].screenTop, { x: 0, z: -1 });

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
    // A quarter turn left about +Y points the camera along -X, west.
    assert.ok(Math.abs(reports[1].headingDegrees - 270) < 0.001);
    assert.ok(Math.abs(reports[1].screenTop.x + 1) < 0.001);
    assert.ok(Math.abs(reports[1].screenTop.z) < 0.001);
    assert.ok(Math.abs(
        data.adapter.getDiagnostics().cameraOrientation.headingDegrees - 270
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

test('short walks route on large sites without allocating a whole-site grid', () => {
    const input = {
        start: {x: 340, z: 35}, goal: {x: 325, z: 20}, radius: .3,
        bounds: {minimum: {x: -82, z: 0}, maximum: {x: 376, z: 200}},
        obstacles: [[{x:330,z:25},{x:334,z:25},{x:334,z:40},{x:330,z:40}]],
    };
    const result = runtime.planWalkthroughRoute(input);
    assert.equal(result.ok, true);
    assert.equal(result.reason, 'routed');
    assert(result.visitedNodeCount <= 20000);
    result.points.slice(1).forEach((p, i) => assert(runtime.walkthroughSegmentValid(result.points[i], p, input)));
});

test('walk search exhaustion is not reported as proof of no path', () => {
    const result = runtime.planWalkthroughRoute({
        start: {x: 10, z: 10}, goal: {x: 30, z: 10}, radius: .3, maximumNodes: 100,
        bounds: {minimum: {x: 0, z: 0}, maximum: {x: 400, z: 200}},
        obstacles: [[{x:20,z:0},{x:21,z:0},{x:21,z:150},{x:20,z:150}]],
    });
    assert.equal(result.ok, false);
    assert.equal(result.reason, 'search_budget_exhausted');
    assert.equal(result.visitedNodeCount, 100);
    assert.deepEqual(result.points, []);
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

test('parked sheets share one renderer and restore camera, geometry and selection', async () => {
    const pool = runtime.createRendererPool({ maximumSize: 1 });
    const first = fixture({ rendererPool: pool });
    first.adapter.mount(first.host);
    await first.adapter.setScene({
        layout: { placements: [placement('pl-a', 'asset-machine', REV_A, 1, 0, 2)] },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    first.adapter.setSelection(['pl-a']);
    const camera = first.adapter.getCameraView();
    camera.position = { x: 12, y: 18, z: 24 };
    first.adapter.applyCameraView(camera);
    const expectedCamera = first.adapter.getCameraView();
    const controls = FakeControls.instances.at(-1);
    assert.strictEqual(first.adapter.park(), true);
    assert.strictEqual(first.adapter.park(), false);
    assert.strictEqual(first.adapter.getDiagnostics().lifecycle.listenerCount, 0);
    assert.strictEqual(pool.getDiagnostics().leasedCount, 0);

    const second = fixture({ rendererPool: pool });
    second.adapter.mount(second.host);
    assert.strictEqual(second.adapter.getDiagnostics().degraded, false);
    assert.strictEqual(second.adapter.park(), true);
    assert.strictEqual(first.adapter.resume(), true);
    await settleAsync();
    assert.strictEqual(FakeRenderer.instances.length, 1);
    assert.notStrictEqual(FakeControls.instances.at(-1), controls);
    assert.deepStrictEqual(first.adapter.getCameraView(), expectedCamera);
    assert.deepStrictEqual(first.adapter.getDiagnostics().selectedPlacementIds, ['pl-a']);
    assert.deepStrictEqual(first.adapter.getDiagnostics().representationGroups
        .flatMap(group => group.placementIds), ['pl-a']);
    assert.strictEqual(pool.getDiagnostics().leasedCount, 1);
    first.adapter.park();
    first.adapter.dispose();
    assert.strictEqual(first.adapter.resume(), false);
    second.adapter.dispose();
    pool.dispose();
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

for (const navigation of ['camera-view', 'toolbar-zoom']) {
    test(navigation + ' loads visible deferred meshes without selecting equipment', async () => {
        const data = fixture({
            largeLayoutDetailThreshold: 2,
            largeLayoutHeavyVisualBytes: 100,
            assetResolver: request => {
                if (request.stage === 'manifest') return asset(request.assetId, request.assetDefinitionRevision);
                if (request.stage === 'footprint') return prototype(data.THREE, request.stage);
                if (request.stage === 'overview') {
                    const visual = prototype(data.THREE, request.stage);
                    visual.byteSize = 101;
                    return visual;
                }
                return null;
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: { placements: [placement('pl-a', 'asset-heavy', REV_A, 1, 0, 2),
                placement('pl-b', 'asset-heavy', REV_A, 4, 0, 2)] },
            assetCatalog: [asset('asset-heavy', REV_A)],
        });
        const view = data.adapter.getCameraView();
        view.position = { x: 2, y: 2, z: 100000 };
        view.target = { x: 2, y: 0, z: 2 };
        data.adapter.applyCameraView(view);
        await settleAsync(20);
        assert.strictEqual(data.adapter.getDiagnostics().rendering.deferredGroupCount, 1);
        if (navigation === 'camera-view') {
            view.position = { x: 2, y: 2, z: 8 };
            data.adapter.applyCameraView(view);
        } else {
            data.adapter.zoomBy(10000);
        }
        await settleAsync(20);
        const diagnostics = data.adapter.getDiagnostics();
        assert.strictEqual(diagnostics.rendering.deferredGroupCount, 0);
        assert.strictEqual(diagnostics.representationGroups[0].representation, 'overview');
        assert.deepStrictEqual(diagnostics.selectedPlacementIds, []);
        data.adapter.dispose();
    });
}

test('manual preview waits for an in-flight deferred exact visual', async () => {
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
                const overview = prototype(data.THREE, request.stage);
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
            routes: [],
            floorMarkings: [],
        },
        assetCatalog: [asset('asset-heavy', REV_A)],
    });

    data.adapter.setSelection(['pl-a']);
    await Promise.resolve();
    const loaded = await data.adapter.navigationPreview.load({
        previewId: 'nav-preview-deferred-one',
        layoutRevision: REV_B,
        actorPlacementId: 'pl-a',
        actorClass: 'pedestrian',
        points: [{ x: 1, z: 2 }, { x: 3, z: 2 }],
        loopMode: 'one_way',
        direction: 'forward',
        visualForwardAxis: '+X',
        validationStatus: 'validated',
        pathsVisible: true,
    }, REV_B);
    assert.strictEqual(loaded.exactCatalogVisual, true);
    assert.strictEqual(loaded.sourcePlacementSuppressed, true);
    assert.strictEqual(loaded.duplicateVisiblePlacementCount, 0);
    assert.strictEqual(
        data.adapter.getDiagnostics().representationGroups[0].representation,
        'overview'
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

function deferredWallArtworkFixture(target) {
    const THREE = createThree(), loads = [];
    THREE.BufferGeometry = class extends FakeBufferGeometry { computeVertexNormals() {} };
    THREE.Mesh = class extends FakeMesh {
        updateWorldMatrix() {}
        getWorldPosition(vector) { return vector.set(this.position.x, this.position.y, this.position.z); }
        getWorldScale(vector) { return vector.set(this.scale.x, this.scale.y, this.scale.z); }
    };
    THREE.TextureLoader = class {
        load(url, ready, progress, failed) {
            const texture = {isTexture:true, image:{width:400,height:300}, dispose() {},
                offset:{set() {}}, repeat:{set() {}}};
            loads.push({ready:()=>ready(texture), failed});
            return texture;
        }
    };
    const data = fixture({THREE, assetResolver:()=>null});
    const wall = asset('asset-wall', REV_A);
    wall.definition.structureKind = 'wall';
    const layout = {placements:[placement('wall', 'asset-wall', REV_A, 0, 0, 0)],
        extensions:{facilityPerimeterWalls:{version:1, panels:[], settings:{
            boundarySource:'polygon', boundary:[{x:0,z:0},{x:10,z:0},{x:10,z:10},{x:0,z:10}],
            thicknessMeters:.2, heightMeters:3, openings:[],
            exteriorFinish:{color:'#222222',jointColor:'#111111',jointWidthMeters:.01,
                panelWidthMeters:10,panelHeightMeters:3,
                fittedArtworks:[{artworkId:'deferred-art',imagePath:'/test.png',target,
                    region:[0,0,1,1],coverage:1,uv:[0,0,1,1]}]}
        }}}};
    return Object.assign(data, {loads, input:{layout,assetCatalog:[wall]}});
}

for (const target of [{placementId:'wall',face:'positive_z'}, {edge:0,side:'interior'}]) {
    test(`deferred fitted artwork survives layer refresh for ${JSON.stringify(target)}`, async () => {
        const data = deferredWallArtworkFixture(target);
        data.adapter.mount(data.host);
        await data.adapter.setScene(data.input);
        data.adapter.setLayerVisibility({zones:false,cells:false});
        data.loads[0].ready();
        let art = data.adapter.getDiagnostics().exteriorArtwork[0];
        assert.equal(art.status, 'ready');
        assert.equal(art.visible, true, 'Ready artwork must unhide its parent as well as its mesh');
        data.adapter.setLayerVisibility({walls:false});
        assert.equal(data.adapter.getDiagnostics().exteriorArtwork[0].visible, false);
        data.adapter.setLayerVisibility({walls:true});
        assert.equal(data.adapter.getDiagnostics().exteriorArtwork[0].visible, true);
        data.adapter.dispose();
    });

    test(`deferred fitted artwork respects walls hidden during load for ${JSON.stringify(target)}`, async () => {
        const data = deferredWallArtworkFixture(target);
        data.adapter.mount(data.host);
        await data.adapter.setScene(data.input);
        data.adapter.setLayerVisibility({walls:false});
        data.loads[0].ready();
        assert.equal(data.adapter.getDiagnostics().exteriorArtwork[0].visible, false);
        data.adapter.setLayerVisibility({walls:true});
        assert.equal(data.adapter.getDiagnostics().exteriorArtwork[0].visible, true);
        data.adapter.dispose();
    });
}

test('failed fitted artwork stays hidden when walls are toggled', async () => {
    const data = deferredWallArtworkFixture({placementId:'wall',face:'positive_z'});
    data.adapter.mount(data.host);
    await data.adapter.setScene(data.input);
    data.loads[0].failed();
    data.adapter.setLayerVisibility({walls:false});
    data.adapter.setLayerVisibility({walls:true});
    const art = data.adapter.getDiagnostics().exteriorArtwork[0];
    assert.equal(art.status, 'failed');
    assert.equal(art.visible, false);
    data.adapter.dispose();
});

for (const count of [1, 2]) {
    test(`authored artwork retains its texture and colors on ${count} tinted wall placements`, async () => {
        const texture = {isTexture:true, disposeCount:0, dispose(){this.disposeCount++;}};
        const data = fixture({assetResolver:request => {
            if (request.stage === 'manifest') return asset(request.assetId, request.assetDefinitionRevision);
            if (request.stage !== 'detail') return null;
            const visual = prototype(data.THREE, 'sign-wall');
            const print = visual.children[0].material;
            print.name = 'printed-logo';
            print.color.setHex(0xffffff);
            print.userData.facilityArtwork = true;
            print.map = texture;
            const backing = prototype(data.THREE, 'backing').children[0];
            backing.material.map = texture;
            visual.add(backing);
            return visual;
        }});
        data.adapter.mount(data.host);
        await data.adapter.setScene({layout:{placements:Array.from({length:count}, (_, i) =>
            Object.assign(placement('pl-sign-'+i, 'asset-sign', REV_A, i*8, 0, 2), {appearance:{color:'#ff0000'}}))},
            assetCatalog:[asset('asset-sign', REV_A)]});
        data.scheduler.flush();
        const prints = [], backings = [];
        FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => {
            if (!object.isMesh || !object.material) return;
            if (object.material.name === 'printed-logo') prints.push(object);
            else if (object.material.userData.facilityNeutralAssetMaterial) backings.push(object);
        });
        assert.ok(prints.length && backings.length);
        for (const object of prints) {
            assert.strictEqual(object.material.map, texture);
            assert.strictEqual(object.material.color.getHex(), 0xffffff);
            if (object.isInstancedMesh) assert.strictEqual(object.colors[0], 0xffffff);
        }
        assert.strictEqual(texture.disposeCount, 0, 'A shared artwork texture must remain live');
        data.adapter.setSelection('pl-sign-0');
        data.adapter.setSelection([]);
        for (const object of prints) assert.strictEqual(object.material.color.getHex(), 0xffffff);
        data.adapter.dispose();
        assert.ok(texture.disposeCount > 0, 'Artwork texture must be released at teardown');
    });
}

for (const count of [1, 2]) {
    test(`authored metallic finishes survive tint and display settings on ${count} placements`, async () => {
        const data = fixture({assetResolver: request => {
            if (request.stage === 'manifest') return asset(request.assetId, request.assetDefinitionRevision);
            if (request.stage !== 'detail') return null;
            const visual = prototype(data.THREE, 'gold-trim');
            const finish = visual.children[0].material;
            finish.name = 'authored-gold';
            finish.color.setHex(0xc99b39);
            finish.metalness = 0.65;
            finish.roughness = 0.38;
            finish.userData.facilityAuthoredFinish = true;
            visual.add(prototype(data.THREE, 'ordinary-wall').children[0]);
            return visual;
        }});
        data.adapter.mount(data.host);
        await data.adapter.setScene({layout:{placements:Array.from({length:count}, (_, i) =>
            Object.assign(placement('pl-trim-'+i, 'asset-trim', REV_A, i*8, 0, 2), {appearance:{color:'#292d32'}}))},
            assetCatalog:[asset('asset-trim', REV_A)]});
        data.adapter.setVisualSettings({metalness:0.1, roughness:0.9});
        data.adapter.setSelection('pl-trim-0');
        data.adapter.setSelection([]);
        data.scheduler.flush();
        const trims = [];
        FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => {
            if (object.material?.name === 'authored-gold') trims.push(object);
        });
        assert.ok(trims.length);
        for (const object of trims) {
            assert.strictEqual(object.material.metalness, 0.65);
            assert.strictEqual(object.material.roughness, 0.38);
            assert.strictEqual(object.isInstancedMesh ? object.colors[0] : object.material.color.getHex(), 0xc99b39);
        }
        data.adapter.dispose();
    });
}

test('repeated illuminated assets retain their light children instead of mesh-only instancing', async () => {
    class AuthoredLight extends FakeObject3D {
        constructor() { super(); this.isLight = true; this.name = 'authored-wall-light'; }
        clone(deep) { const light = super.clone(deep); light.isLight = true; return light; }
    }
    const data = fixture({assetResolver: request => {
        if (request.stage === 'manifest') return asset(request.assetId, request.assetDefinitionRevision);
        if (request.stage !== 'detail') return null;
        const visual = prototype(data.THREE, 'illuminated-wall');
        visual.add(new AuthoredLight());
        return visual;
    }});
    data.adapter.mount(data.host);
    await data.adapter.setScene({layout:{placements:[
        placement('pl-light-a', 'asset-light', REV_A, 0, 0, 0),
        placement('pl-light-b', 'asset-light', REV_A, 8, 0, 0)]},assetCatalog:[asset('asset-light', REV_A)]});
    data.scheduler.flush();
    const groups = data.adapter.getDiagnostics().representationGroups;
    assert.ok(groups.some(g => g.assetId === 'asset-light' && !g.instanced && g.renderedLightCount === 2));
    let lights = 0;
    FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => { if (object.name === 'authored-wall-light') lights++; });
    assert.strictEqual(lights, 2);
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
    data.host.clientWidth = 1200;
    data.host.clientHeight = 500;
    assert.strictEqual(data.adapter.fit(), true);
    data.scheduler.flush();
    const after = data.adapter.getDiagnostics();
    assert.strictEqual(renderer.lastRender.camera.aspect, 2.4);
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

        assert.strictEqual(data.adapter.topView({
            minimum: { x: 5, y: 0, z: 10 },
            maximum: { x: 15, y: 3, z: 20 },
        }), true);
        diagnostics = data.adapter.getDiagnostics();
        assert.deepStrictEqual(diagnostics.camera.target, {
            x: 10,
            y: 0,
            z: 15,
        });
        assert.deepStrictEqual(diagnostics.lastFit.size, {
            x: 10,
            y: 3,
            z: 10,
        });
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
    assert(marking.children.length > 0);
    marking.children.forEach(mesh => {
        assert.strictEqual(mesh.geometry.isPlaneGeometry, true);
        assert.strictEqual(mesh.geometry.rotationX, -Math.PI / 2);
    });
    data.adapter.dispose();
});

function styledZone(zoneId, boundary, fillColor, parentZoneId) {
    return {
        zoneId,
        zoneType: 'workcell',
        label: zoneId,
        boundary,
        floorElevation: 0,
        extensions: Object.assign(
            { style: { fillColor } },
            parentZoneId ? { knowledgeFoundation: { parentZoneId } } : {}
        ),
    };
}

function sceneObjects(predicate) {
    const found = [];
    FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => {
        if (predicate(object)) found.push(object);
    });
    return found;
}

test('3D floor outlines zone limits and hides them with their layer', async () => {
    const data = fixture();
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [],
            zones: [
                styledZone('zn-cnc', [
                    { x: 0, z: 0 }, { x: 20, z: 0 }, { x: 20, z: 10 }, { x: 0, z: 10 },
                ], '#5b8def'),
                styledZone('zn-cell', [
                    { x: 2, z: 2 }, { x: 6, z: 2 }, { x: 6, z: 5 }, { x: 2, z: 5 },
                ], '#58b6a6', 'zn-cnc'),
            ],
        },
        assetCatalog: [],
    });
    data.scheduler.flush();
    assert.strictEqual(data.adapter.getDiagnostics().zoneMarkingCount, 2);
    const zones = {};
    sceneObjects(object => object.userData.facilityZone === true)
        .forEach(object => { zones[object.userData.zoneId] = object; });
    const cnc = zones['zn-cnc'];
    // Only the limits: one line per edge, no fill or lettering, in the plan's
    // zone outline color rather than the zone's own color.
    assert.strictEqual(cnc.children.length, 4);
    cnc.children.forEach(mesh => {
        assert.strictEqual(mesh.geometry.isPlaneGeometry, true);
        assert.strictEqual(mesh.material.options.color, 0x4d7c8a);
    });
    // Each line is centred on its edge, so neighbouring zones share one line.
    assert.deepStrictEqual(
        cnc.children.map(mesh => [mesh.position.x, mesh.position.z])
            .sort((left, right) => left[0] - right[0] || left[1] - right[1]),
        [[0, 5], [10, 0], [10, 10], [20, 5]]
    );
    // Departments follow the zones layer; child areas follow the cells layer.
    data.adapter.setLayerVisibility({ zones: false });
    assert.strictEqual(cnc.visible, false);
    assert.strictEqual(zones['zn-cell'].visible, true);
    data.adapter.setLayerVisibility({ zones: true, cells: false });
    assert.strictEqual(cnc.visible, true);
    assert.strictEqual(zones['zn-cell'].visible, false);
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

test('3D layer visibility hides presentation objects without changing scene data', async () => {
    const data = fixture();
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [
                placement('pl-layer', 'asset-machine', REV_A, 2, 0, 2),
            ],
            routes: [{
                routeId: 'rt-layer',
                routeKind: 'material',
                centerline: [
                    { x: 0, y: 0, z: 0 },
                    { x: 8, y: 0, z: 0 },
                ],
                corridorWidth: 2,
                extensions: {
                    facilityAisle: {
                        schemaVersion: 1,
                        aisleKind: 'material',
                        direction: 'two_way',
                    },
                },
            }],
            floorMarkings: [{
                markingId: 'fm-layer',
                markingType: 'parking_box',
                label: 'Layer marking',
                semanticRole: 'parking',
                transform: { position: { x: 4, y: 0, z: 4 } },
                width: 2,
                depth: 3,
            }],
        },
        assetCatalog: [asset('asset-machine', REV_A)],
    });
    data.scheduler.flush();
    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    let aisle = null;
    let marking = null;
    scene.traverse(object => {
        if (object.userData.facilityAisle === true) aisle = object;
        if (object.userData.facilityFloorMarking === true) marking = object;
    });
    assert(aisle);
    assert(marking);
    const before = data.adapter.getDiagnostics();
    assert.strictEqual(before.placementCount, 1);
    assert.strictEqual(before.routeCount, 1);
    assert.strictEqual(before.floorMarkingCount, 1);
    data.adapter.setLayerVisibility({
        assets: false,
        routes: false,
        markings: false,
    });
    assert.strictEqual(aisle.visible, false);
    assert.strictEqual(marking.visible, false);
    assert.deepStrictEqual(data.adapter.getLayerVisibility(), {
        zones: true,
        cells: true,
        routes: false,
        markings: false,
        assets: false,
        walls: true,
        ground: true,
        surfaces: true,
        site: true,
    });
    const after = data.adapter.getDiagnostics();
    assert.strictEqual(after.placementCount, 1);
    assert.strictEqual(after.routeCount, 1);
    assert.strictEqual(after.floorMarkingCount, 1);
    data.adapter.setLayerVisibility({
        assets: true,
        routes: true,
        markings: true,
    });
    assert.strictEqual(aisle.visible, true);
    assert.strictEqual(marking.visible, true);
    data.adapter.dispose();
});

test('perimeter walls and tagged wall assets have an independent presentation layer', async () => {
    const data = fixture();
    data.adapter.mount(data.host);
    const wall = asset('asset-wall', REV_A); wall.tags = ['wall'];
    const layout = { placements: [placement('pl-wall', 'asset-wall', REV_A, 2, 0, 2)],
        extensions: { facilityPerimeterWalls: { version: 1, settings: { heightMeters: 3 },
            panels: [[{x:0,z:0},{x:0,z:4},{x:0.2,z:4}]] } } };
    const before = JSON.stringify(layout);
    await data.adapter.setScene({ layout, assetCatalog: [wall] });
    assert.equal(data.adapter.getDiagnostics().perimeterWallCount, 1);
    assert.equal(data.adapter.getDiagnostics().visibleLegacyWallPlacementCount, 1);
    data.adapter.setLayerVisibility({ assets: false });
    assert.equal(data.adapter.getDiagnostics().visiblePerimeterWallCount, 1);
    assert.equal(data.adapter.getDiagnostics().visibleLegacyWallPlacementCount, 1);
    data.adapter.setLayerVisibility({ walls: false });
    assert.equal(data.adapter.getDiagnostics().visiblePerimeterWallCount, 0);
    assert.equal(data.adapter.getDiagnostics().visibleLegacyWallPlacementCount, 0);
    assert.equal(data.adapter.getDiagnostics().placementCount, 1);
    assert.equal(JSON.stringify(layout), before);
    data.adapter.setLayerVisibility({ walls: true });
    assert.equal(data.adapter.getDiagnostics().visiblePerimeterWallCount, 1);
    await data.adapter.setScene({ layout: {placements:[]}, assetCatalog: [] });
    assert.equal(data.adapter.getDiagnostics().perimeterWallCount, 0);
    data.adapter.dispose();
});

test('interior-only perimeter paint renders without an exterior finish', async () => {
    const data=fixture();data.adapter.mount(data.host);
    const layout={placements:[],extensions:{facilityPlan:{widthMeters:10,depthMeters:8},
        facilityPerimeterWalls:{version:1,settings:{boundarySource:'plan',heightMeters:3,thicknessMeters:.2,
            openings:[],interiorColor:'#3b4147'},panels:[]}}};
    const before=JSON.stringify(layout);
    await data.adapter.setScene({layout,assetCatalog:[]});
    assert.equal(data.adapter.getDiagnostics().exteriorFinishObjectCount,1);
    assert.equal(JSON.stringify(layout),before);
    await data.adapter.setScene({layout:{placements:[]},assetCatalog:[]});
    assert.equal(data.adapter.getDiagnostics().exteriorFinishObjectCount,0);
    data.adapter.dispose();
});

test('motion sampler follows arc length and takes the shortest heading arc', () => {
    const movement = motionPayload().package.movement;
    const midpoint = runtime.sampleFacilityMotionAtDistance(movement, 5);
    assert.strictEqual(midpoint.x, 6);
    assert.strictEqual(midpoint.z, 2);
    assert.strictEqual(midpoint.gear, 'reverse');
    assert.ok(Math.abs(Math.abs(midpoint.heading) - Math.PI) < 1e-9);
    assert.deepStrictEqual(
        runtime.sampleFacilityMotionAtDistance(movement, 0),
        runtime.sampleFacilityMotionAtDistance(movement, 0)
    );
});

test('manual navigation preview moves the exact existing GLB and restores it',
    async () => {
        const data = fixture({
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(
                        request.assetId,
                        request.assetDefinitionRevision
                    );
                }
                if (request.stage === 'overview') {
                    return prototype(data.THREE, request.assetId);
                }
                return null;
            },
        });
        const actor = placement(
            'operator-nav-one',
            'asset-operator',
            REV_A,
            2,
            0,
            2
        );
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [actor],
                routes: [],
                floorMarkings: [],
            },
            assetCatalog: [asset('asset-operator', REV_A)],
        });
        while (data.scheduler.pendingCount) data.scheduler.flush();

        const scene = FakeRenderer.instances.at(-1).lastRender.scene;
        let source = null;
        scene.traverse(object => {
            if (object.userData
                    && object.userData.placementId === 'operator-nav-one') {
                source = object;
            }
        });
        assert(source);
        assert.notStrictEqual(source.visible, false);

        const loaded = await data.adapter.navigationPreview.load({
            previewId: 'nav-preview-operator-one',
            layoutRevision: REV_B,
            actorPlacementId: 'operator-nav-one',
            actorClass: 'pedestrian',
            points: [{ x: 2, z: 2 }, { x: 10, z: 2 }],
            loopMode: 'closed_loop',
            direction: 'forward',
            visualForwardAxis: '+X',
            validationStatus: 'validated',
            pathsVisible: true,
        }, REV_B);
        assert.strictEqual(loaded.exactCatalogVisual, true);
        assert.strictEqual(loaded.sourcePlacementSuppressed, true);
        assert.strictEqual(loaded.duplicateVisiblePlacementCount, 0);
        assert.strictEqual(source.visible, false);

        data.adapter.navigationPreview.seek(0.5);
        data.scheduler.flush(1000);
        let state = data.adapter.navigationPreview.getState();
        assert.strictEqual(state.pose.x, 6);
        assert.strictEqual(state.pose.z, 2);
        assert.strictEqual(state.pose.heading, 0);
        assert.strictEqual(state.visualYawRadians, 0);
        assert.strictEqual(
            data.adapter.navigationPreview.setPathsVisible(false),
            false
        );
        state = data.adapter.navigationPreview.getState();
        assert.strictEqual(state.pathsVisible, false);
        assert.strictEqual(state.exactCatalogVisual, true);

        assert.strictEqual(
            data.adapter.navigationPreview.dispose('test_dispose'),
            true
        );
        assert.notStrictEqual(source.visible, false);
        assert.strictEqual(
            data.adapter.navigationPreview.getState().loaded,
            false
        );
        data.adapter.dispose();
    });

test('motion playback refuses stale revisions and uses the one owned frame loop', async () => {
    const data = fixture({ prefersReducedMotion: true });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: { placements: [], routes: [], floorMarkings: [] },
        assetCatalog: [],
    });
    while (data.scheduler.pendingCount) data.scheduler.flush();
    assert.throws(
        () => data.adapter.motion.load(motionPayload(), REV_A),
        error => error && error.code === 'facility_motion_package_stale'
    );

    const loaded = data.adapter.motion.load(motionPayload(), REV_B);
    assert.strictEqual(loaded.status, 'ready');
    assert.strictEqual(loaded.playing, false);
    assert.strictEqual(loaded.prefersReducedMotion, true);
    assert.strictEqual(data.scheduler.pendingCount, 1);
    data.scheduler.flush(1000);
    let state = data.adapter.motion.getState();
    assert.strictEqual(state.pose.x, 1);
    assert.strictEqual(state.clearanceAtValidatedSample.distanceMeters, 0);
    assert.strictEqual(data.scheduler.pendingCount, 0);

    assert.strictEqual(data.adapter.motion.play(), true);
    assert.strictEqual(data.scheduler.pendingCount, 1);
    data.scheduler.flush(2000);
    assert.strictEqual(data.scheduler.pendingCount, 1);
    data.scheduler.flush(3000);
    state = data.adapter.motion.getState();
    assert.strictEqual(state.elapsedSeconds, 1);
    assert.strictEqual(state.distanceMeters, 2);
    assert.strictEqual(state.clearanceAtValidatedSample.distanceMeters, 2);
    assert.strictEqual(data.scheduler.pendingCount, 1);

    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    let footprint = null;
    let ribbon = null;
    scene.traverse(object => {
        if (object.userData.facilityMotionVehicleFootprint) footprint = object;
        if (object.userData.facilityMotionRibbon) ribbon = object;
    });
    assert(footprint);
    assert(ribbon);
    assert.strictEqual(data.adapter.motion.pause(), true);
    data.adapter.motion.seek(2.6);
    data.scheduler.flush(4000);
    state = data.adapter.motion.getState();
    assert.strictEqual(state.playing, false);
    assert.ok([4, 6].includes(
        state.clearanceAtValidatedSample.distanceMeters
    ));
    assert.strictEqual(
        state.distanceMeters,
        state.clearanceAtValidatedSample.distanceMeters
    );
    data.adapter.dispose();
    assert.strictEqual(data.scheduler.pendingCount, 0);
});

test('motion v2 uses the recomputed context gate instead of full layout equality', async () => {
    const data = fixture({ prefersReducedMotion: true });
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: { placements: [], routes: [], floorMarkings: [] },
        assetCatalog: [],
    });
    while (data.scheduler.pendingCount) data.scheduler.flush();

    const unrelatedRevision = motionPayloadV2();
    const loaded = data.adapter.motion.load(unrelatedRevision, REV_C);
    assert.strictEqual(loaded.status, 'ready');
    data.adapter.motion.dispose();

    assert.throws(
        () => data.adapter.motion.load(motionPayloadV2({
            includeActiveFingerprint: false,
        }), REV_B),
        error => error
            && error.code === 'facility_motion_validation_context_unavailable'
    );
    assert.throws(
        () => data.adapter.motion.load(motionPayloadV2({
            activeFingerprint: REV_C,
        }), REV_B),
        error => error && error.code === 'facility_motion_package_stale'
    );
    data.adapter.dispose();
});

test('motion disposal restores reparented vehicle and carried placement state', async () => {
    const data = fixture({
        assetResolver: request => {
            if (request.stage === 'manifest') {
                return asset(request.assetId, request.assetDefinitionRevision);
            }
            if (request.stage === 'overview') {
                return prototype(data.THREE, request.assetId);
            }
            return null;
        },
    });
    const vehicle = placement('vehicle-one', 'forklift', REV_A, 4, 0, 5);
    const carried = placement('load-one', 'pallet', REV_A, 5, 1, 5);
    carried.snapRelationship = { supportPlacementId: 'vehicle-one' };
    data.adapter.mount(data.host);
    await data.adapter.setScene({
        layout: {
            placements: [vehicle, carried],
            routes: [],
            floorMarkings: [],
        },
        assetCatalog: [asset('forklift', REV_A), asset('pallet', REV_A)],
    });
    while (data.scheduler.pendingCount) data.scheduler.flush();
    assert.strictEqual(
        data.adapter.getDiagnostics().representationGroups[0]
            .prototypeMeshCount,
        1
    );
    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    const byId = {};
    scene.traverse(object => {
        const id = object.userData && object.userData.placementId;
        if (id) byId[id] = object;
    });
    const before = {};
    ['vehicle-one', 'load-one'].forEach(id => {
        before[id] = {
            parent: byId[id].parent,
            index: byId[id].parent.children.indexOf(byId[id]),
            position: Object.assign({}, byId[id].position),
            quaternion: Object.assign({}, byId[id].quaternion),
            scale: Object.assign({}, byId[id].scale),
            visible: byId[id].visible !== false,
        };
    });
    data.adapter.setSelection(['vehicle-one']);
    data.adapter.motion.load(motionPayload({
        vehiclePlacementId: 'vehicle-one',
        carriedPlacementIds: ['load-one'],
    }), REV_B);
    data.scheduler.flush(1000);
    let motionState = data.adapter.motion.getState();
    assert.strictEqual(motionState.vehiclePresentation, 'placed_asset');
    assert.strictEqual(motionState.following, true);
    assert.strictEqual(data.adapter.motion.setFollow(false), false);
    assert.strictEqual(data.adapter.motion.getState().following, false);
    assert.strictEqual(data.adapter.motion.setFollow(true), true);
    assert.notStrictEqual(byId['vehicle-one'].parent, before['vehicle-one'].parent);
    assert.strictEqual(byId['vehicle-one'].parent, byId['load-one'].parent);

    assert.strictEqual(data.adapter.motion.dispose('test_dispose'), true);
    ['vehicle-one', 'load-one'].forEach(id => {
        assert.strictEqual(byId[id].parent, before[id].parent);
        assert.strictEqual(byId[id].parent.children.indexOf(byId[id]), before[id].index);
        assert.deepStrictEqual(Object.assign({}, byId[id].position), before[id].position);
        assert.deepStrictEqual(
            Object.assign({}, byId[id].quaternion),
            before[id].quaternion
        );
        assert.deepStrictEqual(Object.assign({}, byId[id].scale), before[id].scale);
        assert.strictEqual(byId[id].visible !== false, before[id].visible);
    });
    assert.deepStrictEqual(
        data.adapter.getDiagnostics().selectedPlacementIds,
        ['vehicle-one']
    );
    data.adapter.dispose();
});

test('activity actors face travel, turn at endpoints, and ping-pong without teleporting',
    async () => {
        const data = fixture({
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(
                        request.assetId,
                        request.assetDefinitionRevision
                    );
                }
                if (request.stage === 'overview') {
                    return prototype(data.THREE, request.assetId);
                }
                return null;
            },
        });
        const parkedQuaternion = {
            x: 0,
            y: Math.sin(Math.PI / 4),
            z: 0,
            w: Math.cos(Math.PI / 4),
        };
        const actorPlacement = placement(
            'actor-placement',
            'activity-asset',
            REV_A,
            40,
            0,
            40,
            parkedQuaternion
        );
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [actorPlacement],
                routes: [],
                floorMarkings: [],
            },
            assetCatalog: [asset('activity-asset', REV_A)],
        });
        while (data.scheduler.pendingCount) data.scheduler.flush();
        const zeroTurnPayload = activityPayload();
        zeroTurnPayload.scenario.actors[0].endpointTurnSeconds = 0;
        await assert.rejects(
            data.adapter.activity.load(zeroTurnPayload, REV_B),
            error => error && error.code === 'facility_activity_visual_alignment_invalid'
        );
        await data.adapter.activity.load(activityPayload(), REV_B);
        data.scheduler.flush(1000);

        const scene = FakeRenderer.instances.at(-1).lastRender.scene;
        let rootObject = null;
        scene.traverse(object => {
            if (object.userData.facilityActivityActorId === 'actor-fixture') {
                rootObject = object;
            }
        });
        assert(rootObject);
        const rootYaw = () => 2 * Math.atan2(
            rootObject.quaternion.y,
            rootObject.quaternion.w
        );
        let state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'outbound');
        assert.ok(Math.abs(state.actors[0].pose.heading) < 1e-9);
        assert.ok(Math.abs(rootYaw() - Math.PI / 2) < 1e-9);
        assert.deepStrictEqual(
            Object.assign({}, rootObject.children[0].quaternion),
            { x: 0, y: 0, z: 0, w: 1 }
        );

        data.adapter.activity.seek(5.5);
        data.scheduler.flush(2000);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'turn_at_end');
        assert.strictEqual(state.actors[0].travelDirection, 'turning');
        assert.ok(Math.abs(state.actors[0].pose.heading - Math.PI / 2) < 1e-9);
        assert.ok(Math.abs(rootYaw()) < 1e-9);

        data.adapter.activity.seek(7);
        data.scheduler.flush(3000);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'return');
        assert.strictEqual(state.actors[0].travelDirection, 'return');
        assert.ok(Math.abs(Math.abs(state.actors[0].pose.heading) - Math.PI) < 1e-9);
        assert.ok(Math.abs(rootYaw() + Math.PI / 2) < 1e-9);
        assert.ok(state.actors[0].pose.x < 11);

        data.adapter.activity.seek(11.5);
        data.scheduler.flush(4000);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'turn_at_start');
        assert.ok(Math.abs(state.actors[0].pose.x - 1) < 1e-9);
        assert.ok(Math.abs(state.actors[0].pose.heading - Math.PI / 2) < 1e-9);

        data.adapter.activity.play();
        data.scheduler.flush(5000);
        data.scheduler.flush(6000);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.elapsedSeconds, 0.5);
        assert.strictEqual(state.actors[0].playbackPhase, 'outbound');
        assert.ok(state.actors[0].pose.x > 1);
        assert.ok(Math.abs(state.actors[0].pose.heading) < 1e-9);
        data.adapter.dispose();
    });

test('repeating activity wraps the authoritative shared clock for unequal actor cycles',
    async () => {
        const data = fixture({
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(
                        request.assetId,
                        request.assetDefinitionRevision
                    );
                }
                if (request.stage === 'overview') {
                    return prototype(data.THREE, request.assetId);
                }
                return null;
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement('actor-placement', 'activity-asset', REV_A, 1, 0, 2),
                    placement('actor-placement-two', 'activity-asset', REV_A, 20, 0, 2),
                ],
                routes: [],
                floorMarkings: [],
            },
            assetCatalog: [asset('activity-asset', REV_A)],
        });
        while (data.scheduler.pendingCount) data.scheduler.flush();

        const payload = activityPayload();
        const shorter = motionPayload({
            packageId: 'fmp-shorter-cycle',
            movementId: 'movement-shorter-cycle',
            routeId: 'route-shorter-cycle',
            layoutRevision: REV_B,
            vehiclePlacementId: 'actor-placement-two',
            duration: 3,
        });
        shorter.package.movement.poses = [
            { x: 20, z: 2, heading: 0, gear: 'forward' },
            { x: 26, z: 2, heading: 0, gear: 'forward' },
        ];
        shorter.package.movement.cumulativeDistance = [0, 6];
        shorter.package.movement.distanceMeters = 6;
        payload.actorPayloads[shorter.package.packageId] = shorter;
        payload.scenario.actors.push(Object.assign({}, payload.scenario.actors[0], {
            actorId: 'actor-shorter-cycle',
            label: 'Shorter-cycle actor',
            motionPackageId: shorter.package.packageId,
            placementId: 'actor-placement-two',
            routeId: 'route-shorter-cycle',
        }));

        await data.adapter.activity.load(payload, REV_B);
        data.scheduler.flush(1000);
        data.adapter.activity.seek(11.5);
        data.scheduler.flush(2000);
        data.adapter.activity.play();
        data.scheduler.flush(5000);
        data.scheduler.flush(6000);

        const state = data.adapter.activity.getState();
        assert.strictEqual(state.elapsedSeconds, 0.5);
        assert.strictEqual(state.actors[0].playbackPhase, 'outbound');
        assert.strictEqual(state.actors[1].playbackPhase, 'outbound');
        assert.ok(state.actors[1].pose.x > 20);
        data.adapter.dispose();
    });

test('activity lean-motion paths toggle independently from moving actors',
    async () => {
        const data = fixture({
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(
                        request.assetId,
                        request.assetDefinitionRevision
                    );
                }
                if (request.stage === 'overview') {
                    return prototype(data.THREE, request.assetId);
                }
                return null;
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement(
                        'actor-placement',
                        'activity-asset',
                        REV_A,
                        40,
                        0,
                        40
                    ),
                    placement(
                        'actor-placement-two',
                        'activity-asset',
                        REV_A,
                        50,
                        0,
                        40
                    ),
                ],
                routes: [],
                floorMarkings: [],
            },
            assetCatalog: [asset('activity-asset', REV_A)],
        });
        while (data.scheduler.pendingCount) data.scheduler.flush();
        const payload = activityPayload();
        const createOperatorLeg = (
            packageId,
            placementId,
            routeId,
            poses
        ) => motionPayload({
            packageId,
            movementId: `${packageId}-movement`,
            routeId,
            layoutRevision: REV_B,
            vehiclePlacementId: placementId,
            poses,
            cumulativeDistance: [0, Math.hypot(
                poses[1].x - poses[0].x,
                poses[1].z - poses[0].z
            )],
            duration: 2,
        });
        const operatorOneLocal = createOperatorLeg(
            'fmp-operator-one-local',
            'actor-placement',
            'operator-one-route',
            [
                { x: 1, z: 2, heading: 0, gear: 'forward' },
                { x: 2, z: 2, heading: 0, gear: 'forward' },
            ]
        );
        const operatorOneOut = createOperatorLeg(
            'fmp-operator-one-out',
            'actor-placement',
            'connection-one:outbound',
            [
                { x: 2, z: 2, heading: 0, gear: 'forward' },
                { x: 4, z: 1, heading: 0, gear: 'forward' },
            ]
        );
        const operatorOneReturn = createOperatorLeg(
            'fmp-operator-one-return',
            'actor-placement',
            'connection-one:return',
            [
                { x: 4, z: 1, heading: Math.PI, gear: 'forward' },
                { x: 1, z: 2, heading: Math.PI, gear: 'forward' },
            ]
        );
        const operatorTwoLocal = createOperatorLeg(
            'fmp-operator-two-local',
            'actor-placement-two',
            'operator-two-route',
            [
                { x: 11, z: 2, heading: Math.PI, gear: 'forward' },
                { x: 10, z: 2, heading: Math.PI, gear: 'forward' },
            ]
        );
        const operatorTwoOut = createOperatorLeg(
            'fmp-operator-two-out',
            'actor-placement-two',
            'connection-two:outbound',
            [
                { x: 10, z: 2, heading: Math.PI, gear: 'forward' },
                { x: 8, z: 1, heading: Math.PI, gear: 'forward' },
            ]
        );
        const operatorTwoReturn = createOperatorLeg(
            'fmp-operator-two-return',
            'actor-placement-two',
            'connection-two:return',
            [
                { x: 8, z: 1, heading: 0, gear: 'forward' },
                { x: 11, z: 2, heading: 0, gear: 'forward' },
            ]
        );
        const firstActor = payload.scenario.actors[0];
        firstActor.motionPackageId = operatorOneLocal.package.packageId;
        firstActor.cycleMotionPackageIds = [
            operatorOneLocal.package.packageId,
            operatorOneOut.package.packageId,
            operatorOneReturn.package.packageId,
        ];
        firstActor.routeId = 'operator-one-route';
        firstActor.loopMode = 'closed_path';
        firstActor.endpointTurnSeconds = 0.45;
        const secondActor = Object.assign({}, firstActor, {
            actorId: 'actor-other',
            label: 'Fixture actor two',
            motionPackageId: operatorTwoLocal.package.packageId,
            cycleMotionPackageIds: [
                operatorTwoLocal.package.packageId,
                operatorTwoOut.package.packageId,
                operatorTwoReturn.package.packageId,
            ],
            placementId: 'actor-placement-two',
            routeId: 'operator-two-route',
            departmentZoneIds: ['zone-two'],
        });
        payload.scenario.actors = [firstActor, secondActor];
        payload.actorPayloads = {
            [operatorOneLocal.package.packageId]: operatorOneLocal,
            [operatorOneOut.package.packageId]: operatorOneOut,
            [operatorOneReturn.package.packageId]: operatorOneReturn,
            [operatorTwoLocal.package.packageId]: operatorTwoLocal,
            [operatorTwoOut.package.packageId]: operatorTwoOut,
            [operatorTwoReturn.package.packageId]: operatorTwoReturn,
        };
        payload.scenario.leanMotion = {
                schemaVersion: 'facility-lean-motion-v3',
                qualification: (
                    'Derived prototype motion borrows existing placed operator identities, '
                    + 'assigns them to nearby placed stations, and routes the responsible '
                    + 'endpoint operators to derived FIFO handoff points. Material handoff '
                    + 'lines show workpiece transfer relationships, not operator walking. '
                    + 'The routes are geometrically feasible paths, not time-optimal standard '
                    + 'work, and do not establish staffing, task frequency, synchronized '
                    + 'transfer timing, capacity, traffic safety, or compliance.'
                ),
                evidenceStatus: 'derived',
                operatorPaths: [
                    {
                        pathId: 'operator-path-one',
                        actorId: 'actor-fixture',
                        zoneId: 'zone-one',
                        pathKind: 'cell_work_loop',
                        segmentIndex: 0,
                        segmentCount: 1,
                        assignedPlacementIds: ['bench-one'],
                        centerline: [
                            { x: 1, z: 2 },
                            { x: 4, z: 2 },
                            { x: 4, z: 5 },
                            { x: 1, z: 5 },
                            { x: 1, z: 2 },
                        ],
                        closed: true,
                        evidenceStatus: 'derived',
                    },
                    {
                        pathId: 'operator-path-two',
                        actorId: 'actor-other',
                        zoneId: 'zone-two',
                        pathKind: 'cell_work_loop',
                        segmentIndex: 0,
                        segmentCount: 1,
                        assignedPlacementIds: ['bench-two'],
                        centerline: [
                            { x: 8, z: 2 },
                            { x: 11, z: 2 },
                            { x: 11, z: 5 },
                            { x: 8, z: 5 },
                            { x: 8, z: 2 },
                        ],
                        closed: true,
                        evidenceStatus: 'derived',
                    },
                ],
                pedestrianConnections: [
                    {
                        connectionId: 'connection-one',
                        actorId: 'actor-fixture',
                        pathId: 'operator-path-one',
                        zoneId: 'zone-one',
                        fifoPointId: 'fifo-one',
                        handoffIds: ['handoff-one'],
                        role: 'output',
                        motionPackageIds: [
                            operatorOneOut.package.packageId,
                            operatorOneReturn.package.packageId,
                        ],
                        centerline: [
                            { x: 2, z: 2 },
                            { x: 4, z: 1 },
                            { x: 2, z: 2 },
                        ],
                        closed: true,
                        evidenceStatus: 'derived',
                    },
                    {
                        connectionId: 'connection-two',
                        actorId: 'actor-other',
                        pathId: 'operator-path-two',
                        zoneId: 'zone-two',
                        fifoPointId: 'fifo-two',
                        handoffIds: ['handoff-one'],
                        role: 'input',
                        motionPackageIds: [
                            operatorTwoOut.package.packageId,
                            operatorTwoReturn.package.packageId,
                        ],
                        centerline: [
                            { x: 10, z: 2 },
                            { x: 8, z: 1 },
                            { x: 10, z: 2 },
                        ],
                        closed: true,
                        evidenceStatus: 'derived',
                    },
                ],
                assistanceGates: [{
                    gateId: 'gate-one',
                    zoneId: 'zone-one',
                    participantPathIds: [
                        'operator-path-one',
                        'operator-path-two',
                    ],
                    participantActorIds: ['actor-fixture', 'actor-other'],
                    position: { x: 7, z: 2 },
                    evidenceStatus: 'derived',
                }],
                materialHandoffs: [{
                    handoffId: 'handoff-one',
                    fromZoneId: 'zone-one',
                    toZoneId: 'zone-two',
                    fromPointId: 'fifo-one',
                    toPointId: 'fifo-two',
                    fromPathId: 'operator-path-one',
                    toPathId: 'operator-path-two',
                    fromActorId: 'actor-fixture',
                    toActorId: 'actor-other',
                    fromConnectionId: 'connection-one',
                    toConnectionId: 'connection-two',
                    centerline: [
                        { x: 4, z: 1 },
                        { x: 8, z: 1 },
                    ],
                    evidenceStatus: 'derived',
                }],
                fifoPoints: [
                    {
                        pointId: 'fifo-one',
                        zoneId: 'zone-one',
                        role: 'output',
                        position: { x: 4, z: 1 },
                        evidenceStatus: 'derived',
                    },
                    {
                        pointId: 'fifo-two',
                        zoneId: 'zone-two',
                        role: 'input',
                        position: { x: 8, z: 1 },
                        evidenceStatus: 'derived',
                    },
                ],
            };

        await data.adapter.activity.load(payload, REV_B);
        data.scheduler.flush(1000);
        let state = data.adapter.activity.getState();
        assert.strictEqual(state.pathsVisible, true);
        assert.deepStrictEqual(state.leanMotionCounts, {
            operatorPaths: 2,
            pedestrianConnections: 2,
            assistanceGates: 1,
            materialHandoffs: 1,
            fifoPoints: 2,
            renderedObjects: 8,
        });
        assert.strictEqual(state.actors[0].visible, true);
        assert.strictEqual(state.borrowedPlacementCount, 2);
        assert.deepStrictEqual(state.duplicateVisiblePlacementIds, []);

        const scene = FakeRenderer.instances.at(-1).lastRender.scene;
        let pathRoot = null;
        const kinds = [];
        scene.traverse(object => {
            if (object.name === 'FacilityLeanMotionPaths') pathRoot = object;
            if (object.userData && object.userData.facilityLeanMotionKind) {
                kinds.push(object.userData.facilityLeanMotionKind);
            }
        });
        assert(pathRoot);
        assert.deepStrictEqual(kinds.sort(), [
            'assistance_gate',
            'fifo_point',
            'fifo_point',
            'material_handoff',
            'operator_path',
            'operator_path',
            'pedestrian_connection',
            'pedestrian_connection',
        ]);

        assert.strictEqual(data.adapter.activity.setPathsVisible(false), false);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.pathsVisible, false);
        assert.strictEqual(pathRoot.visible, false);
        assert.strictEqual(state.actors[0].visible, true);

        assert.strictEqual(data.adapter.activity.setPathsVisible(true), true);
        assert.strictEqual(pathRoot.visible, true);
        data.adapter.dispose();
    });

test('navigation activity replays a v3 journey with exact visual and class path controls',
    async () => {
        const data = fixture({
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(
                        request.assetId,
                        request.assetDefinitionRevision
                    );
                }
                if (request.stage === 'overview') {
                    return prototype(data.THREE, request.assetId);
                }
                return null;
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [placement(
                    'actor-placement',
                    'activity-asset',
                    REV_A,
                    1,
                    0,
                    2
                )],
                routes: [],
                floorMarkings: [],
            },
            assetCatalog: [asset('activity-asset', REV_A)],
        });
        while (data.scheduler.pendingCount) data.scheduler.flush();
        const payload = navigationActivityPayload();
        await data.adapter.activity.load(payload, REV_B);
        data.adapter.activity.play();
        data.scheduler.flush(0);
        data.scheduler.flush(4000);
        let state = data.adapter.activity.getState();

        assert.strictEqual(state.borrowedPlacementCount, 1);
        assert.deepStrictEqual(state.duplicateVisiblePlacementIds, []);
        assert.strictEqual(state.actors[0].exactCatalogVisual, true);
        assert.strictEqual(state.actors[0].sourcePlacementSuppressed, true);
        assert.strictEqual(state.actors[0].visible, true);
        assert(state.actors[0].pose.x > 1);
        assert(Math.abs(state.actors[0].pose.heading) < 1e-6);
        let navigationPath = null;
        FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => {
            if (object.userData
                    && object.userData.facilityActivityPathActorType
                        === 'operator') {
                navigationPath = object;
            }
        });
        assert(navigationPath);
        assert.strictEqual(navigationPath.visible, true);

        assert.strictEqual(
            data.adapter.activity.setPathTypeVisible('operator', false),
            false
        );
        state = data.adapter.activity.getState();
        assert.strictEqual(state.visiblePathTypes.operator, false);
        assert.strictEqual(navigationPath.visible, false);
        assert.strictEqual(state.actors[0].visible, true);
        assert.strictEqual(data.adapter.activity.setPathsVisible(false), false);
        assert.strictEqual(state.actors[0].visible, true);
        data.adapter.dispose();
    });

test('packaging activity uses three semantic path legs and loops the existing operator',
    async () => {
        const data = fixture({
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(
                        request.assetId,
                        request.assetDefinitionRevision
                    );
                }
                if (request.stage === 'overview') {
                    return prototype(data.THREE, request.assetId);
                }
                return null;
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [placement(
                    'actor-placement',
                    'activity-asset',
                    REV_A,
                    1,
                    0,
                    2
                )],
                routes: [],
                floorMarkings: [],
            },
            assetCatalog: [asset('activity-asset', REV_A)],
        });
        while (data.scheduler.pendingCount) data.scheduler.flush();
        const payload = packagingNavigationActivityPayload();
        await data.adapter.activity.load(payload, REV_B);

        const paths = new Map();
        FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => {
            const phase = object.userData
                && object.userData.facilityActivityPathPhase;
            if (phase) paths.set(phase, object);
        });
        assert.deepStrictEqual(Array.from(paths.keys()).sort(), [
            'carry_in',
            'carry_out',
            'return_empty',
        ]);
        assert.strictEqual(paths.get('carry_in').material.color.getHex(), '#2563eb');
        assert.strictEqual(paths.get('carry_out').material.color.getHex(), '#d97706');
        assert.strictEqual(paths.get('return_empty').material.color.getHex(), '#059669');
        assert(
            paths.get('return_empty').geometry.attributes.position.count
                > paths.get('carry_in').geometry.attributes.position.count
        );

        data.adapter.activity.seek(2.5);
        data.scheduler.flush(1000);
        let state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'local_turn_1');
        assert.strictEqual(
            state.actors[0].currentMotionPackageId,
            'fmp-packaging-carry_in'
        );
        assert.deepStrictEqual(state.duplicateVisiblePlacementIds, []);
        assert.deepStrictEqual(state.visibleSourcePlacementIds, []);
        assert.deepStrictEqual(
            state.candidatePresentation.packagingPathLegend.map(
                item => item.phase
            ),
            ['carry_in', 'carry_out', 'return_empty']
        );

        data.adapter.activity.seek(3.5);
        data.scheduler.flush(2000);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'local_path_2');
        assert.strictEqual(
            state.actors[0].currentMotionPackageId,
            'fmp-packaging-carry_out'
        );

        data.adapter.activity.seek(6.5);
        data.scheduler.flush(3000);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'local_path_3');
        assert.strictEqual(
            state.actors[0].currentMotionPackageId,
            'fmp-packaging-return_empty'
        );

        data.adapter.activity.seek(9.25);
        data.scheduler.flush(4000);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'local_path_1');
        assert.strictEqual(
            state.actors[0].currentMotionPackageId,
            'fmp-packaging-carry_in'
        );
        data.adapter.dispose();
    });

test('inspection activity uses A-B-C paths and a perimeter empty return',
    async () => {
        const data = fixture({
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(
                        request.assetId,
                        request.assetDefinitionRevision
                    );
                }
                if (request.stage === 'overview') {
                    return prototype(data.THREE, request.assetId);
                }
                return null;
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [placement(
                    'actor-placement',
                    'activity-asset',
                    REV_A,
                    1,
                    0,
                    2
                )],
                routes: [],
                floorMarkings: [],
            },
            assetCatalog: [asset('activity-asset', REV_A)],
        });
        while (data.scheduler.pendingCount) data.scheduler.flush();
        await data.adapter.activity.load(
            inspectionNavigationActivityPayload(),
            REV_B
        );

        const paths = new Map();
        FakeRenderer.instances.at(-1).lastRender.scene.traverse(object => {
            const phase = object.userData
                && object.userData.facilityActivityPathPhase;
            if (phase) paths.set(phase, object);
        });
        assert.deepStrictEqual(Array.from(paths.keys()).sort(), [
            'inspection_pick',
            'inspection_place',
            'return_empty',
        ]);
        assert.strictEqual(
            paths.get('inspection_pick').material.color.getHex(),
            '#2563eb'
        );
        assert.strictEqual(
            paths.get('inspection_place').material.color.getHex(),
            '#2563eb'
        );
        assert.strictEqual(
            paths.get('return_empty').material.color.getHex(),
            '#059669'
        );
        assert(
            paths.get('return_empty').geometry.attributes.position.count
                > paths.get('inspection_place').geometry.attributes.position.count
        );

        data.adapter.activity.seek(2.5);
        data.scheduler.flush(1000);
        let state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'local_turn_1');
        assert.strictEqual(
            state.actors[0].currentMotionPackageId,
            'fmp-inspection-inspection_pick'
        );
        assert.deepStrictEqual(state.duplicateVisiblePlacementIds, []);
        assert.deepStrictEqual(state.visibleSourcePlacementIds, []);
        assert.deepStrictEqual(
            state.candidatePresentation.inspectionPathLegend.map(
                item => item.phase
            ),
            ['inspection_pick', 'inspection_place', 'return_empty']
        );

        data.adapter.activity.seek(3.5);
        data.scheduler.flush(2000);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'local_path_2');
        assert.strictEqual(
            state.actors[0].currentMotionPackageId,
            'fmp-inspection-inspection_place'
        );

        data.adapter.activity.seek(6.5);
        data.scheduler.flush(3000);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'local_path_3');
        assert.strictEqual(
            state.actors[0].currentMotionPackageId,
            'fmp-inspection-return_empty'
        );

        data.adapter.activity.seek(9.25);
        data.scheduler.flush(4000);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.actors[0].playbackPhase, 'local_path_1');
        data.adapter.dispose();
    });

test('reference activity suppresses non-animated operator placements and restores them',
    async () => {
        const data = fixture({
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(
                        request.assetId,
                        request.assetDefinitionRevision
                    );
                }
                if (request.stage === 'overview') {
                    return prototype(data.THREE, request.assetId);
                }
                return null;
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement(
                        'actor-placement',
                        'activity-asset',
                        REV_A,
                        1,
                        0,
                        2
                    ),
                    placement(
                        'stationary-operator',
                        'asset-operator',
                        REV_A,
                        3,
                        0,
                        2
                    ),
                ],
                routes: [],
                floorMarkings: [],
            },
            assetCatalog: [
                asset('activity-asset', REV_A),
                asset('asset-operator', REV_A),
            ],
        });
        while (data.scheduler.pendingCount) data.scheduler.flush();
        const payload = navigationActivityPayload();
        payload.candidatePresentation = {
            schemaVersion: 'facility-reference-movement-candidates-v1',
            sourceLayoutId: 'fl-reference-manual-20260812',
            sourceLayoutRevision: 'a'.repeat(64),
            authority: 'inferred_candidate',
            reviewStatus: 'pending',
            productionEligible: false,
            candidateCounts: {
                operators: 1,
                vehicles: 0,
                handoffs: 0,
                displayedActors: 1,
                displayedHandoffs: 0,
                unavailableActors: 0,
                partialPrograms: 0,
                suppressedStationaryOperators: 1,
            },
            suppressedOperatorPlacementIds: ['stationary-operator'],
            handoffs: [],
            qualification: 'Candidate presentation only.',
            presentationFingerprint: 'b'.repeat(64),
        };
        await data.adapter.activity.load(payload, REV_B);
        let state = data.adapter.activity.getState();
        assert.strictEqual(state.borrowedPlacementCount, 1);
        assert.strictEqual(state.suppressedStationaryOperatorCount, 1);
        assert.deepStrictEqual(state.duplicateVisiblePlacementIds, []);
        assert.deepStrictEqual(state.visibleSourcePlacementIds, []);
        assert.strictEqual(
            state.candidatePresentation.candidateCounts
                .suppressedStationaryOperators,
            1
        );

        const enteredDrone = data.adapter.enterDrone({ ignoreSelection: true });
        assert.strictEqual(enteredDrone.active, true);
        state = data.adapter.activity.getState();
        assert.deepStrictEqual(state.visibleSourcePlacementIds, []);

        assert.strictEqual(data.adapter.exitDrone('test_complete'), true);
        state = data.adapter.activity.getState();
        assert.deepStrictEqual(state.visibleSourcePlacementIds, []);

        assert.strictEqual(data.adapter.activity.dispose('test'), true);
        state = data.adapter.activity.getState();
        assert.strictEqual(state.loaded, false);
        assert.strictEqual(state.suppressedStationaryOperatorCount, 0);
        data.adapter.dispose();
    });

test('Drone culling preserves activity ownership of repeated operator instances',
    async () => {
        const data = fixture({
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(
                        request.assetId,
                        request.assetDefinitionRevision
                    );
                }
                if (request.stage === 'overview') {
                    return prototype(data.THREE, request.assetId);
                }
                return null;
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [
                    placement(
                        'actor-placement',
                        'asset-operator',
                        REV_A,
                        1,
                        0,
                        2
                    ),
                    placement(
                        'stationary-operator',
                        'asset-operator',
                        REV_A,
                        3,
                        0,
                        2
                    ),
                ],
                routes: [],
                floorMarkings: [],
            },
            assetCatalog: [asset('asset-operator', REV_A)],
        });
        while (data.scheduler.pendingCount) data.scheduler.flush();
        const payload = navigationActivityPayload();
        payload.scenario.actors[0].assetDefinitionRef.assetId =
            'asset-operator';
        payload.candidatePresentation = {
            schemaVersion: 'facility-reference-movement-candidates-v1',
            sourceLayoutId: 'fl-reference-manual-20260812',
            sourceLayoutRevision: REV_A,
            authority: 'inferred_candidate',
            reviewStatus: 'pending',
            productionEligible: false,
            candidateCounts: {
                operators: 1,
                vehicles: 0,
                handoffs: 0,
                displayedActors: 1,
                displayedHandoffs: 0,
                unavailableActors: 0,
                partialPrograms: 0,
                suppressedStationaryOperators: 1,
            },
            suppressedOperatorPlacementIds: ['stationary-operator'],
            handoffs: [],
            qualification: 'Candidate presentation only.',
            presentationFingerprint: REV_B,
        };

        await data.adapter.activity.load(payload, REV_B);
        const scene = FakeRenderer.instances.at(-1).lastRender.scene;
        let baseInstances = null;
        scene.traverse(object => {
            if (object.isInstancedMesh
                    && object.userData
                    && Array.isArray(
                        object.userData.facilityInstancePlacementIds
                    )) {
                baseInstances = object;
            }
        });
        assert(baseInstances);

        data.adapter.enterDrone({ ignoreSelection: true });
        assert.strictEqual(baseInstances.count, 0);
        assert.deepStrictEqual(
            data.adapter.activity.getState().visibleSourcePlacementIds,
            []
        );

        data.adapter.exitDrone('test_complete');
        assert.strictEqual(baseInstances.count, 0);
        assert.deepStrictEqual(
            data.adapter.activity.getState().visibleSourcePlacementIds,
            []
        );

        data.adapter.activity.dispose('test');
        assert.strictEqual(baseInstances.count, 2);
        assert.deepStrictEqual(
            baseInstances.userData.facilityInstancePlacementIds,
            ['actor-placement', 'stationary-operator']
        );
        data.adapter.dispose();
    });

test('activity vehicles transfer between marked lanes for a closed two-way loop',
    async () => {
        const data = fixture({
            assetResolver: request => {
                if (request.stage === 'manifest') {
                    return asset(
                        request.assetId,
                        request.assetDefinitionRevision
                    );
                }
                if (request.stage === 'overview') {
                    return prototype(data.THREE, request.assetId);
                }
                return null;
            },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({
            layout: {
                placements: [placement(
                    'actor-placement',
                    'activity-asset',
                    REV_A,
                    40,
                    0,
                    40
                )],
                routes: [],
                floorMarkings: [],
            },
            assetCatalog: [asset('activity-asset', REV_A)],
        });
        while (data.scheduler.pendingCount) data.scheduler.flush();
        await data.adapter.activity.load(pairedLaneActivityPayload(), REV_B);

        data.adapter.activity.seek(5.5);
        data.scheduler.flush(1000);
        let actor = data.adapter.activity.getState().actors[0];
        assert.strictEqual(actor.playbackPhase, 'lane_change_at_end');
        assert.strictEqual(actor.currentMotionPackageId, 'fmp-end-transfer');
        assert.ok(Math.abs(actor.pose.x - 12) < 1e-9);
        assert.ok(Math.abs(actor.pose.z - 3) < 1e-9);

        data.adapter.activity.seek(6.5);
        data.scheduler.flush(2000);
        actor = data.adapter.activity.getState().actors[0];
        assert.strictEqual(actor.playbackPhase, 'return');
        assert.strictEqual(actor.currentMotionPackageId, 'fmp-return');
        assert.ok(actor.pose.x < 11);
        assert.ok(Math.abs(actor.pose.z - 4) < 1e-9);
        assert.ok(Math.abs(Math.abs(actor.pose.heading) - Math.PI) < 1e-9);
        assert.ok(Math.sin(actor.visualYawRadians) < -0.999999);
        assert.ok(Math.abs(Math.cos(actor.visualYawRadians)) < 1e-9);

        data.adapter.activity.seek(11.5);
        data.scheduler.flush(3000);
        actor = data.adapter.activity.getState().actors[0];
        assert.strictEqual(actor.playbackPhase, 'lane_change_at_start');
        assert.ok(Math.abs(actor.pose.x) < 1e-9);
        assert.ok(Math.abs(actor.pose.z - 3) < 1e-9);

        data.adapter.activity.seek(0.5);
        data.scheduler.flush(4000);
        actor = data.adapter.activity.getState().actors[0];
        assert.strictEqual(actor.playbackPhase, 'outbound');
        assert.strictEqual(actor.currentMotionPackageId, 'fmp-outbound');
        assert.ok(actor.pose.x > 1);
        assert.ok(Math.abs(actor.pose.z - 2) < 1e-9);
        assert.ok(Math.sin(actor.visualYawRadians) > 0.999999);
        assert.ok(Math.abs(Math.cos(actor.visualYawRadians)) < 1e-9);
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
            routes: [{
                routeId: 'rt-proposal',
                centerline: [
                    { x: 0, y: 0, z: 2 },
                    { x: 20, y: 0, z: 2 },
                ],
                corridorWidth: 2,
            }],
        };
        const proposal = {
            active: true,
            newPlacementIds: ['pl-new'],
            movedPlacementIds: ['pl-a'],
            removedPlacementIds: ['pl-removed'],
            changedRouteIds: ['rt-proposal'],
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
            beforeRoutes: [{
                routeId: 'rt-proposal',
                centerline: [
                    { x: 0, y: 0, z: 4 },
                    { x: 20, y: 0, z: 4 },
                ],
                corridorWidth: 2,
            }],
            proposedRoutes: proposedLayout.routes,
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
        assert.deepStrictEqual(roles, [
            'before', 'before', 'moved', 'new', 'proposed', 'removed',
        ]);
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
    assert.strictEqual(diagnostics.lifecycle.listenerCount, 16);
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
    await settleAsync(32);

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

test('avatar camera retracts at thin obstacles, floor and facility boundary', () => {
    const bounds = { minimum: { x: 0, y: 0, z: 0 }, maximum: { x: 20, y: 5, z: 20 } };
    const anchor = { x: 10, y: 1.3, z: 10 };
    const wall = [{ x: 8, z: 12 }, { x: 12, z: 12 }, { x: 12, z: 12.02 }, { x: 8, z: 12.02 }];
    const input = { anchor, desired: { x: 10, y: 1.45, z: 14 }, floorY: 0, bounds };
    assert.strictEqual(runtime.resolveWalkthroughCamera(input).obstructed, false);
    const blocked = runtime.resolveWalkthroughCamera({ ...input, obstacles: [wall] });
    assert(blocked.obstructed && blocked.position.z < 11.85 && blocked.position.z > 11.7);
    const floor = runtime.resolveWalkthroughCamera({ ...input, desired: { x: 10, y: -2, z: 14 } });
    assert(floor.obstructed && floor.position.y >= 0.15);
    const edge = runtime.resolveWalkthroughCamera({ ...input, anchor: { x: 10, y: 1.3, z: 19 } });
    assert.strictEqual(edge.obstructed, false);
    const beyond = runtime.resolveWalkthroughCamera({ ...input, desired: { x: 10, y: 1.3, z: 22 } });
    assert(beyond.obstructed && beyond.position.z <= 19.85);
});

test('third-person movement, camera switch, routing and Drone use the walker position', async () => {
    const data = fixture({ worldBounds: { minX: 0, minZ: 0, maxX: 20, maxZ: 20, floorY: 0 } });
    data.adapter.mount(data.host);
    await data.adapter.setScene({ layout: { placements: [] }, assetCatalog: [] });
    data.scheduler.flush();
    const overview = data.adapter.getDiagnostics().camera;
    assert.strictEqual(data.adapter.setWalkthroughCameraMode('invalid'), false);
    data.adapter.setWalkthroughCameraMode('third-person');
    data.adapter.enterWalkthrough({ worldPoint: { x: 10, y: 0, z: 10 }, ignoreSelection: true });
    const start = data.adapter.getWalkthroughState();
    assert(start.avatar.visible);
    assert(start.cameraDistance > 3.9);
    assert.strictEqual(start.position.z, 10);
    assert.strictEqual(data.adapter.getDiagnostics().camera.position.z, 15);
    data.documentObject.dispatch('keydown', { code: 'KeyW' });
    for (let i = 1; i <= 20; i++) data.scheduler.flush(i * 16);
    const moved = data.adapter.getWalkthroughState();
    assert(moved.position.z < 9.6);
    assert(moved.avatar.distanceMeters > 0.4 && moved.avatar.blend > 0.9);
    assert(moved.avatar.leftHip !== 0);
    data.documentObject.dispatch('keyup', { code: 'KeyW' });
    for (let i = 21; i <= 70; i++) data.scheduler.flush(i * 16);
    assert.strictEqual(data.adapter.getWalkthroughState().avatar.animation, 'idle');
    assert.strictEqual(data.scheduler.pendingCount, 0);
    const body = data.adapter.getWalkthroughState().position;
    data.documentObject.dispatch('keydown', { code: 'KeyC' });
    assert.deepStrictEqual(data.adapter.getWalkthroughState().position, body);
    assert.strictEqual(data.adapter.getWalkthroughState().avatar.visible, false);
    assert.strictEqual(data.adapter.getDiagnostics().camera.position.z, body.z);
    data.documentObject.dispatch('keydown', { code: 'KeyC', repeat: true });
    assert.strictEqual(data.adapter.getWalkthroughState().cameraMode, 'first-person');
    data.documentObject.dispatch('keydown', { code: 'KeyC' });
    const route = data.adapter.navigateWalkthroughToPoint({ x: body.x + 1, z: body.z });
    assert(route.ok && Math.abs(route.distance - 1) < 1e-6);
    assert(data.adapter.getDiagnostics().camera.position.z > body.z + 3);
    data.adapter.cancelWalkthroughNavigation('test');
    data.documentObject.dispatch('keydown', { code: 'KeyG' });
    assert.strictEqual(data.adapter.getWalkthroughState().avatar, null);
    assert.strictEqual(data.adapter.getDiagnostics().camera.position.z, body.z);
    data.adapter.exitDrone('test');
    assert.deepStrictEqual(data.adapter.getDiagnostics().camera, overview);
    data.adapter.dispose();
});

test('scripted walk gaze changes only camera and remains valid across camera modes', async () => {
    const data = fixture({worldBounds: {minX: 0, minZ: 0, maxX: 20, maxZ: 20, floorY: 0}});
    data.adapter.mount(data.host);
    const layout = {placements: []};
    await data.adapter.setScene({layout, assetCatalog: []});
    assert.equal(data.adapter.lookWalkthroughAt({x: 5, y: 1, z: 5}), false);
    data.adapter.enterWalkthrough({worldPoint: {x: 10, z: 10}, ignoreSelection: true});
    const before = data.adapter.getWalkthroughState().position;
    for (const mode of ['first-person', 'third-person']) {
        data.adapter.setWalkthroughCameraMode(mode);
        assert.equal(data.adapter.lookWalkthroughAt({x: 5, y: 1, z: 5}), true);
        assert.deepEqual(data.adapter.getWalkthroughState().position, before);
        assert.equal(data.adapter.getWalkthroughState().active, true);
        assert.equal(data.adapter.lookWalkthroughAt({x: NaN, y: 1, z: 5}), false);
    }
    assert.deepEqual(layout, {placements: []});
    data.adapter.dispose();
});

test('navigation retains the lookAt quaternion instead of restoring the previous heading', async () => {
    const THREE = createThree();
    THREE.PerspectiveCamera = class extends FakePerspectiveCamera {
        lookAt(x, y, z) {
            super.lookAt(x, y, z);
            const heading = Math.atan2(-(x - this.position.x), -(z - this.position.z));
            this.quaternion.set(0, Math.sin(heading / 2), 0, Math.cos(heading / 2));
        }
    };
    const data = fixture({THREE, worldBounds: {minX: 0, minZ: 0, maxX: 20, maxZ: 20, floorY: 0}});
    data.adapter.mount(data.host);
    await data.adapter.setScene({layout: {placements: []}, assetCatalog: []});
    data.adapter.enterWalkthrough({worldPoint: {x: 10, z: 10}, ignoreSelection: true});
    data.adapter.setWalkthroughCameraMode('first-person');
    assert(data.adapter.navigateWalkthroughToPoint({x: 12, z: 10}).ok);
    const facing = data.adapter.getCameraView().quaternion;
    assert(Math.abs(facing.y + Math.SQRT1_2) < 1e-6);
    assert(Math.abs(facing.w - Math.SQRT1_2) < 1e-6);
    data.scheduler.flush(16);
    assert.deepEqual(data.adapter.getCameraView().quaternion, facing);
    data.adapter.dispose();
});

test('avatar resources and frame work are released on suspend, park, context loss and dispose', async () => {
    for (const action of ['suspend', 'park', 'context-loss', 'dispose']) {
        const data = fixture({ worldBounds: { minX: 0, minZ: 0, maxX: 20, maxZ: 20, floorY: 0 } });
        data.adapter.mount(data.host);
        await data.adapter.setScene({ layout: { placements: [] }, assetCatalog: [] });
        data.adapter.setWalkthroughCameraMode('third-person');
        data.adapter.enterWalkthrough({ worldPoint: { x: 10, y: 0, z: 10 } });
        const geometryBefore = FakeGeometry.totalDisposed;
        if (action === 'context-loss') FakeRenderer.instances.at(-1).domElement.dispatch('webglcontextlost');
        else data.adapter[action]();
        assert.strictEqual(data.adapter.getWalkthroughState().avatar, null, action);
        assert.strictEqual(data.adapter.getWalkthroughState().active, false, action);
        assert(FakeGeometry.totalDisposed >= geometryBefore + 5, action);
        data.adapter.dispose();
        assert.strictEqual(data.scheduler.pendingCount, 0, action);
    }
});

test('blocked walking stops gait; mouse-look retracts camera without moving the walker', async () => {
    const data = fixture({ worldBounds: { minX: 0, minZ: 0, maxX: 20, maxZ: 20, floorY: 0 } });
    data.adapter.mount(data.host);
    await data.adapter.setScene({ layout: { placements: [] }, assetCatalog: [] });
    data.adapter.setWalkthroughCameraMode('third-person');
    data.adapter.enterWalkthrough({ worldPoint: { x: 10, y: 0, z: 0.3 } });
    data.documentObject.dispatch('keydown', { code: 'KeyW' });
    for (let i = 0; i < 50; i++) data.scheduler.flush(i * 16);
    const walk = data.adapter.getWalkthroughState();
    assert.strictEqual(walk.position.z, 0.3);
    assert(walk.collisionCount > 0);
    assert.strictEqual(walk.avatar.animation, 'idle');
    const controls = FakePointerLockControls.instances.at(-1);
    controls.getDirection = target => target.set(0, 0, 1);
    controls.dispatch('change');
    const looked = data.adapter.getWalkthroughState();
    assert.deepStrictEqual(looked.position, walk.position);
    assert(looked.cameraObstructed && !looked.avatar.visible);
    data.adapter.dispose();
});

test('route arrival settles on slow frames and repeated views never duplicate the avatar', async () => {
    const data = fixture({ worldBounds: { minX: 0, minZ: 0, maxX: 20, maxZ: 20, floorY: 0 } });
    data.adapter.mount(data.host);
    await data.adapter.setScene({ layout: { placements: [] }, assetCatalog: [] });
    data.adapter.setWalkthroughCameraMode('third-person');
    data.adapter.enterWalkthrough({ worldPoint: { x: 10, y: 0, z: 10 } });
    data.adapter.navigateWalkthroughToPoint({ x: 11, z: 10 });
    for (let i = 0; i < 20; i++) data.scheduler.flush(i * 300);
    const arrived = data.adapter.getWalkthroughState();
    assert.strictEqual(arrived.route.reason, 'arrived');
    assert.strictEqual(arrived.avatar.animation, 'idle');
    assert.deepStrictEqual(arrived.position, { x: 11, y: 0, z: 10 });
    assert.strictEqual(data.scheduler.pendingCount, 0);
    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    for (let i = 0; i < 10; i++) {
        data.adapter.setWalkthroughCameraMode('first-person');
        data.adapter.setWalkthroughCameraMode('third-person');
        assert.strictEqual(scene.children.filter(x => x.name === 'facility-walkthrough-avatar').length, 1);
    }
    data.adapter.exitWalkthrough();
    assert.strictEqual(scene.children.filter(x => x.name === 'facility-walkthrough-avatar').length, 0);
    data.adapter.dispose();
});

test('camera preferences persist; wheel changes only the third-person camera and cleans up', async () => {
    const prefs = require('../static/walkthrough_camera_settings.js');
    prefs.save(prefs.PRESETS.standard);
    const data = fixture({worldBounds:{minX:0,minZ:0,maxX:50,maxZ:50,floorY:0}});
    data.adapter.mount(data.host);
    await data.adapter.setScene({layout:{placements:[]},assetCatalog:[]});
    data.adapter.setWalkthroughCameraMode('third-person');
    data.adapter.enterWalkthrough({worldPoint:{x:25,y:0,z:25}});
    const body = data.adapter.getWalkthroughState().position;
    data.adapter.setWalkthroughCameraSettings(prefs.PRESETS.wide);
    assert.deepStrictEqual(data.adapter.getWalkthroughState().position, body);
    assert(data.adapter.getWalkthroughState().cameraDistance > 9);
    const canvas = FakeRenderer.instances.at(-1).domElement;
    assert(canvas.dispatch('wheel',{deltaY:-100}).prevented);
    assert.strictEqual(data.adapter.getWalkthroughState().cameraSettings.distance, 8.5);
    assert(!canvas.dispatch('wheel',{deltaY:100,ctrlKey:true}).prevented);
    data.adapter.setWalkthroughCameraMode('first-person');
    assert(!canvas.dispatch('wheel',{deltaY:100}).prevented);
    assert.strictEqual(data.adapter.getWalkthroughState().cameraSettings.distance,8.5);
    data.adapter.exitWalkthrough();
    data.adapter.enterWalkthrough({worldPoint:body});
    assert.strictEqual(data.adapter.getWalkthroughState().cameraSettings.distance,8.5);
    data.adapter.dispose();
    assert.strictEqual(canvas.listenerCount(),0);
    prefs.save(prefs.PRESETS.standard);
});

test('wide camera tests obstacles beyond the former five-metre search radius', async () => {
    const prefs = require('../static/walkthrough_camera_settings.js');
    const data=fixture({worldBounds:{minX:0,minZ:0,maxX:40,maxZ:40,floorY:0}});
    data.adapter.mount(data.host);
    await data.adapter.setScene({layout:{placements:[placement('wall','machine',REV_A,20,0,27)]},assetCatalog:[asset('machine',REV_A)]});
    data.adapter.setWalkthroughCameraSettings(prefs.PRESETS.wide);
    data.adapter.setWalkthroughCameraMode('third-person');
    data.adapter.enterWalkthrough({worldPoint:{x:20,y:0,z:20},ignoreSelection:true});
    const result=data.adapter.getWalkthroughState();
    assert(result.cameraObstructed);
    assert(result.cameraDistance < 7);
    assert.strictEqual(result.cameraSettings.distance,9);
    data.adapter.dispose();
    prefs.save(prefs.PRESETS.standard);
});

test('real operator avatars stay instanced at rest and animate independently in both motion modes', async () => {
    const { pathToFileURL } = require('node:url');
    const real = await import(pathToFileURL(path.join(ROOT, 'static/vendor/three/0.184.0/build/three.module.min.js')).href);
    const THREE = Object.assign({}, real, { WebGLRenderer: FakeRenderer });
    const revision = '773d3761fb0796587de7a21ccb8b368f4334c71f73c06682b84472d69d4b5757';
    const data = fixture({ THREE, assetResolver: request => request.stage === 'manifest'
        ? asset(request.assetId, request.assetDefinitionRevision) : null });
    data.adapter.mount(data.host);
    await data.adapter.setScene({ layout: {
        placements: [placement('actor-placement', 'asset-operator', revision, 1, 0, 2),
            placement('idle-operator', 'asset-operator', revision, 3, 0, 2)], routes: [], floorMarkings: [],
    }, assetCatalog: [asset('asset-operator', revision)] });
    while (data.scheduler.pendingCount) data.scheduler.flush();
    const diagnostics = data.adapter.getDiagnostics();
    const group = diagnostics.representationGroups.find(g => g.assetId === 'asset-operator');
    assert.equal(group.representation, 'operator-avatar');
    assert.equal(group.instanced, true);
    assert.equal(group.prototypeMeshCount, 34);
    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    const instances = [];
    scene.traverse(o => { if (o.isInstancedMesh) instances.push(o); });
    assert(instances.length > 0);
    const before = instances.map(o => Array.from(o.instanceMatrix.array));
    const payload = activityPayload();
    payload.scenario.actors[0].assetDefinitionRef = { assetId: 'asset-operator', assetDefinitionRevision: revision };
    await data.adapter.activity.load(payload, REV_B);
    data.adapter.activity.seek(1.17); data.scheduler.flush(100);
    const a = data.adapter.activity.getState().actors[0];
    assert.equal(a.visualSource, 'animated-operator-avatar');
    assert.equal(a.exactCatalogVisual, false);
    assert.equal(a.visualForwardAxis, '-Z');
    assert.equal(a.avatar.animation, 'walk');
    assert.notEqual(a.avatar.leftHip, 0);
    assert(a.sourcePlacementSuppressed);
    assert.deepEqual(data.adapter.activity.getState().duplicateVisiblePlacementIds, []);
    data.adapter.activity.seek(3.21); data.scheduler.flush(200);
    const b = data.adapter.activity.getState().actors[0];
    assert.notEqual(b.avatar.leftHip, a.avatar.leftHip);
    data.adapter.activity.seek(1.17); data.scheduler.flush(300);
    assert.deepEqual(data.adapter.activity.getState().actors[0].avatar, a.avatar);
    data.adapter.activity.pause(); data.scheduler.flush(3000);
    assert.deepEqual(data.adapter.activity.getState().actors[0].avatar, a.avatar);
    let rig;
    scene.traverse(o => { if (o.facilityOperatorAvatar) rig = o.facilityOperatorAvatar; });
    assert(rig);
    const cycleDuration = a.cycleDurationSeconds;
    data.adapter.activity.seek(cycleDuration + .2); data.scheduler.flush(4000);
    assert.equal(data.adapter.activity.getState().actors[0].avatar.animation, 'idle');
    data.adapter.activity.seek(cycleDuration + 1 + 1.17); data.scheduler.flush(4100);
    const reverse = data.adapter.activity.getState().actors[0];
    assert.equal(reverse.travelDirection, 'return');
    assert.equal(reverse.avatar.animation, 'walk');
    data.adapter.activity.dispose('test');
    assert.equal(rig.snapshot().disposed, true);
    assert.deepEqual(instances.map(o => Array.from(o.instanceMatrix.array)), before);
    await data.adapter.navigationPreview.load({ previewId: 'avatar-preview', layoutRevision: REV_B,
        actorPlacementId: 'actor-placement', actorClass: 'pedestrian',
        points: [{ x: 1, z: 2 }, { x: 11, z: 2 }], loopMode: 'one_way',
        direction: 'forward', visualForwardAxis: '+Z', validationStatus: 'validated', pathsVisible: true,
    }, REV_B);
    data.adapter.navigationPreview.seek(.17); data.scheduler.flush(5000);
    const nav = data.adapter.navigationPreview.getState();
    assert.equal(nav.avatar.animation, 'walk');
    assert.equal(nav.visualYawRadians, -Math.PI / 2);
    assert.equal(nav.visualSource, 'animated-operator-avatar');
    data.adapter.navigationPreview.seek(1); data.scheduler.flush(5100);
    assert.equal(data.adapter.navigationPreview.getState().avatar.animation, 'idle');
    data.adapter.navigationPreview.dispose('test');
    assert.deepEqual(instances.map(o => Array.from(o.instanceMatrix.array)), before);
    data.adapter.dispose();
});

for (const fps of [5, 10, 20, 30, 60, 144]) {
    test('walking retains its specified speed at ' + fps + ' FPS', async () => {
        const data = fixture({ worldBounds: { minX: 0, minZ: 0, maxX: 100, maxZ: 100 } });
        data.adapter.mount(data.host);
        await data.adapter.setScene({ layout: { placements: [] } });
        data.adapter.enterWalkthrough({ worldPoint: { x: 50, z: 50 } });
        data.documentObject.dispatch('keydown', { code: 'KeyW' });
        data.scheduler.flush(0);
        const start = data.adapter.getWalkthroughState().position.z;
        for (let frame = 1; frame <= fps * 2; frame++) data.scheduler.flush(frame * 1000 / fps);
        const end = data.adapter.getWalkthroughState();
        assert(Math.abs(start - end.position.z - end.walkSpeed * 2) < 1e-8);
        assert.equal(end.performance.droppedSeconds, 0);
        data.adapter.dispose();
    });
}

test('long stalls have bounded travel, no catch-up debt, and blur releases movement', async () => {
    const data = fixture({ worldBounds: { minX: 0, minZ: 0, maxX: 100, maxZ: 100 } });
    data.adapter.mount(data.host);
    await data.adapter.setScene({ layout: { placements: [] } });
    data.adapter.enterWalkthrough({ worldPoint: { x: 50, z: 50 } });
    data.documentObject.dispatch('keydown', { code: 'KeyW' });data.scheduler.flush(0);
    const start = data.adapter.getWalkthroughState().position.z;
    data.scheduler.flush(10000);
    const end = data.adapter.getWalkthroughState();
    assert(Math.abs(start - end.position.z - 1.4 * 0.25) < 1e-8);
    assert.equal(end.performance.droppedSeconds, 9.75);
    data.scheduler.flush(10000);
    assert.deepEqual(data.adapter.getWalkthroughState().position, end.position);
    data.scheduler.flush(10100);
    assert(Math.abs(end.position.z - data.adapter.getWalkthroughState().position.z - 0.14) < 1e-8);
    data.windowObject.dispatch('blur');
    const stopped = data.adapter.getWalkthroughState().position;
    data.scheduler.flush(20000);
    assert.deepEqual(data.adapter.getWalkthroughState().position, stopped);
    data.adapter.dispose();
});

test('indexed collision candidates preserve full-scan results, corners, slides and overflow walls', () => {
    const rectangle = (x, z, w, d) => [{x,z},{x:x+w,z},{x:x+w,z:z+d},{x,z:z+d}];
    const polygons = Array.from({length:836}, (_,i) => rectangle((i%30)*5-70, Math.floor(i/30)*5-60, 2, 1));
    polygons.push(rectangle(-20000, -20, 40000, 0.03));
    const index = runtime.buildDroneSpatialIndex(polygons.map((polygon,i) => ({id:String(i),polygon,minimumY:0,maximumY:1})));
    assert.equal(index.overflow.length, 1);
    const bounds = {minimum:{x:-30000,z:-100},maximum:{x:30000,z:100}};
    let seed=7181, largestCandidateCount=0;
    const random=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
    for(let i=0;i<600;i++) {
        const start={x:random()*140-70,z:random()*120-60};
        const delta={x:random()*8-4,z:random()*8-4},radius=0.3;
        const nearby=runtime.walkthroughSweptObstacles(index,start,delta,radius);
        largestCandidateCount=Math.max(largestCandidateCount,nearby.length);
        const input={start,delta,radius,bounds};
        assert.deepEqual(runtime.resolveWalkthroughMovement({...input,obstacles:nearby}),
            runtime.resolveWalkthroughMovement({...input,obstacles:polygons}));
    }
    assert(largestCandidateCount<10);
    const start={x:0,z:-19},delta={x:2,z:-3};
    assert(runtime.walkthroughSweptObstacles(index,start,delta,0.3).some(p=>p[0].x===-20000));
});

test('slow-frame sprint cannot tunnel through a thin wall', async () => {
    const data=fixture({walkthroughFastSpeed:15,worldBounds:{minX:0,minZ:0,maxX:100,maxZ:100}});
    data.adapter.mount(data.host);
    await data.adapter.setScene({layout:{placements:[placement('wall','wall',REV_A,50,0,50)]},
        assetCatalog:[asset('wall',REV_A,{minimum:{x:-8,y:0,z:-0.02},maximum:{x:8,y:6,z:0.02}})]});
    data.adapter.enterWalkthrough({worldPoint:{x:50,z:51.5}});
    data.documentObject.dispatch('keydown',{code:'ShiftLeft'});
    data.documentObject.dispatch('keydown',{code:'KeyW'});
    data.scheduler.flush(0);data.scheduler.flush(200);
    const state=data.adapter.getWalkthroughState();
    assert(state.position.z>50.3);
    assert(state.collisionCount>0);
    assert.equal(state.performance.collisionCandidates,1);
    data.adapter.dispose();
});

test('walk and route use interactive resolution and restore it at rest and on exit', async () => {
    const data=fixture({pixelRatio:2,navigationResolutionRestoreDelayMs:0,
        worldBounds:{minX:0,minZ:0,maxX:100,maxZ:100}});
    data.adapter.mount(data.host);await data.adapter.setScene({layout:{placements:[]}});
    data.adapter.enterWalkthrough({worldPoint:{x:50,z:50}});
    const renderer=FakeRenderer.instances.at(-1);
    data.documentObject.dispatch('keydown',{code:'KeyW'});data.scheduler.flush(0);
    assert.equal(renderer.pixelRatio,1);
    data.documentObject.dispatch('keyup',{code:'KeyW'});data.scheduler.flush(100);
    assert.equal(renderer.pixelRatio,2);
    data.adapter.navigateWalkthroughToPoint({x:51,z:50});
    assert.equal(renderer.pixelRatio,1);
    data.adapter.cancelWalkthroughNavigation('test');data.scheduler.flush(200);
    assert.equal(renderer.pixelRatio,2);
    data.documentObject.dispatch('keydown',{code:'KeyW'});
    data.adapter.exitWalkthrough();
    assert.equal(renderer.pixelRatio,2);
    data.adapter.dispose();
});

test('moving context queries are bounded in rate and range, with fresh explicit reads', async () => {
    const queries=[];
    class RecordingRaycaster extends FakeRaycaster {
        constructor(){super();this.far=Infinity;}
        intersectObjects(){queries.push(this.far);return super.intersectObjects();}
    }
    const THREE=createThree();THREE.Raycaster=RecordingRaycaster;
    const data=fixture({THREE,worldBounds:{minX:0,minZ:0,maxX:100,maxZ:100}});
    data.adapter.mount(data.host);await data.adapter.setScene({layout:{placements:[]}});
    data.adapter.enterWalkthrough({worldPoint:{x:50,z:50}});
    data.scheduler.flush();queries.length=0;
    data.documentObject.dispatch('keydown',{code:'KeyW'});
    for(let i=0;i<6;i++)data.scheduler.flush(i*16);
    assert.deepEqual(queries,[5]);
    data.adapter.getWalkthroughContextFocus();
    assert.deepEqual(queries,[5,5]);
    data.adapter.pick({normalized:true,x:0,y:0});
    assert.equal(queries.at(-1),Infinity);
    data.documentObject.dispatch('keyup',{code:'KeyW'});data.scheduler.flush(101);
    assert.equal(queries.at(-1),5);
    data.adapter.dispose();
});

test('appearance survives instancing selection reset and scene updates without reloading geometry', async () => {
    const data = fixture(); data.adapter.mount(data.host);
    const layout = {placements: [placement('pl-one','one',REV_A,1,0,1),
        placement('pl-a','repeat',REV_A,3,0,1), placement('pl-b','repeat',REV_A,5,0,1)]};
    const catalog = [asset('one',REV_A), asset('repeat',REV_A)];
    await data.adapter.setScene({layout, assetCatalog: catalog}); data.scheduler.flush();
    const scene = FakeRenderer.instances.at(-1).lastRender.scene;
    let instances, single;
    scene.traverse(o => {
        if (o.isInstancedMesh && o.userData.facilityInstancePlacementIds?.includes('pl-a')) instances = o;
        if (o.userData?.placementId === 'pl-one') single = o;
    });
    assert(instances && single);
    const originalColors = instances.colors.slice();
    const meshes=[]; single.traverse(o => {if(o.material) meshes.push(o);});
    const originalSingle = meshes[0].material.color.getHex();
    const changed = JSON.parse(JSON.stringify(layout));
    changed.placements[0].appearance={color:'#28866b'};
    changed.placements[1].appearance={color:'#2478bc'};
    await data.adapter.setScene({layout:changed, assetCatalog:catalog});
    assert.equal(instances.colors[0], 0x2478bc);
    assert.equal(instances.colors[1], originalColors[1]);
    assert.equal(meshes[0].material.color.getHex(), 0x28866b);
    data.adapter.setSelection(['pl-a', 'pl-one']);
    assert.equal(instances.colors[0], 0x32a8ff);
    data.adapter.setSelection([]);
    assert.equal(instances.colors[0], 0x2478bc);
    assert.equal(meshes[0].material.color.getHex(), 0x28866b);
    await data.adapter.setScene({layout, assetCatalog:catalog});
    assert.deepEqual(instances.colors, originalColors);
    assert.equal(meshes[0].material.color.getHex(), originalSingle);
    assert.equal(meshes[0].material.disposeCount, 0);
    data.adapter.dispose();
});

test('late detail load takes the current appearance rather than the original request', async () => {
    let finish, started;
    const waiting = new Promise(r => { started = r; });
    const data = fixture({assetResolver: request => {
        if (request.stage === 'manifest') return asset(request.assetId, request.assetDefinitionRevision);
        if (request.stage !== 'detail') return null;
        started();
        return new Promise(resolve => { finish = () => resolve(prototype(data.THREE, 'late-detail')); });
    }});
    data.adapter.mount(data.host);
    const input = {layout:{placements:[placement('pl-late','one',REV_A,1,0,1)]}, assetCatalog:[asset('one',REV_A)]};
    const pending = data.adapter.setScene(input);
    await waiting;
    const colored = JSON.parse(JSON.stringify(input));
    colored.layout.placements[0].appearance={color:'#bb4040'};
    await data.adapter.setScene(colored);
    finish(); await pending; data.scheduler.flush();
    let material;
    FakeRenderer.instances.at(-1).lastRender.scene.traverse(o => {
        if (o.userData?.placementId === 'pl-late') o.traverse(c => {if(c.material) material=c.material;});
    });
    assert.equal(material.color.getHex(), 0xbb4040);
    data.adapter.dispose();
});

test('selection changes uniforms without invalidating shaders or redundant instance colors', async () => {
    const data=fixture();data.adapter.mount(data.host);
    await data.adapter.setScene({layout:{placements:[placement('single','one',REV_A,1,0,1),
        placement('first','repeat',REV_A,3,0,1),placement('second','repeat',REV_A,5,0,1)]},
        assetCatalog:[asset('one',REV_A),asset('repeat',REV_A)]});
    data.scheduler.flush();const scene=FakeRenderer.instances.at(-1).lastRender.scene;
    let writes=0;const materials=[];
    scene.traverse(o=>{
        if(o.material){materials.push(o.material);o.material.needsUpdate=false;}
        if(o.isInstancedMesh){const original=o.setColorAt.bind(o);o.setColorAt=(...args)=>{writes++;original(...args);};}
    });
    data.adapter.setSelection([]);assert.equal(writes,0);
    data.adapter.setSelection(['first','single']);assert(writes>0);
    const previous=writes;data.adapter.setSelection(['first','single']);assert.equal(writes,previous);
    assert(materials.every(m=>m.needsUpdate===false));
    data.adapter.dispose();
});

for (const distanceCulling of [false, true]) {
    test('Drone ' + (distanceCulling ? 'opt-in culling uses wall extents' : 'defaults to the complete factory'), async () => {
        const data = fixture({
            ...(distanceCulling ? { droneDistanceCulling: true } : {}),
            worldBounds: { minX: 0, minZ: 0, maxX: 300, maxZ: 200, floorY: 0 },
        });
        data.adapter.mount(data.host);
        await data.adapter.setScene({ layout: { placements: [
            placement('operator-near', 'operator', REV_A, 20, 0, 40),
            placement('operator-far', 'operator', REV_A, 280, 0, 160),
            placement('long-wall', 'wall', REV_A, 150, 0, 20),
        ] }, assetCatalog: [asset('operator', REV_A), asset('wall', REV_A, {
            minimum: {x:-140,y:0,z:-.125}, maximum:{x:140,y:6,z:.125},
        })] });
        data.scheduler.flush();
        const scene = FakeRenderer.instances.at(-1).lastRender.scene;
        let operators, wall;
        scene.traverse(object => {
            if (object.userData?.facilityInstancePlacementIds?.includes('operator-near')) operators = object;
            if (object.userData?.placementId === 'long-wall') wall = object;
        });
        assert(operators && wall);
        const entered = data.adapter.enterDrone({ignoreSelection:true,worldPoint:{x:15,y:2,z:35}});
        assert(entered.active);
        assert.equal(operators.count, distanceCulling ? 1 : 2);
        assert.equal(wall.visible, true, 'Nearby wall must not disappear because its center is distant');
        assert.equal(data.adapter.getDroneState().distanceCulling, distanceCulling);
        if (!distanceCulling) {
            const camera = data.adapter.getCameraView();
            assert(camera.far > Math.hypot(300-camera.position.x,200-camera.position.z,6-camera.position.y));
        }
        data.adapter.switchImmersiveMode('walkthrough');
        assert.equal(operators.count,2);assert.equal(wall.visible,true);
        data.adapter.exitWalkthrough();
        data.adapter.enterDrone({ignoreSelection:true,worldPoint:{x:15,y:2,z:35}});
        data.adapter.exitDrone();
        assert.equal(operators.count,2);assert.equal(wall.visible,true);
        data.adapter.dispose();
    });
}

test('ground surfaces render and walkthrough follows the ramp without changing the layout', async () => {
    const THREE=createThree();
    THREE.BufferGeometry=class extends FakeBufferGeometry {
        setIndex(value){this.index=value;return this;}
        computeVertexNormals(){this.normalsComputed=true;}
    };
    const data=fixture({THREE,worldBounds:{minX:0,minZ:0,maxX:40,maxZ:10,floorY:0}});
    const surface=(id,a,b,y,end=y)=>({surfaceId:id,minX:a,maxX:b,minZ:0,maxZ:10,startElevation:y,endElevation:end,slopeAxis:'x',color:'#888888'});
    const layout={placements:[],extensions:{facilityGround:{schemaVersion:1,surfaces:[surface('yard',-30,-20,-1.35),surface('ramp',-20,0,-1.35,0),surface('factory',0,40,0)]}}};
    const before=JSON.stringify(layout);data.adapter.mount(data.host);
    await data.adapter.setScene({layout});data.scheduler.flush();
    assert.equal(data.adapter.getDiagnostics().environment.groundSurfaceCount,3);
    const entered=data.adapter.enterWalkthrough({worldPoint:{x:-25,z:5},ignoreSelection:true});assert.equal(entered.position.y,-1.35);
    assert(data.adapter.navigateWalkthroughToPoint({x:2,z:5}).ok);
    for(let i=0;i<1800&&data.adapter.getWalkthroughState().route.active;i++)data.scheduler.flush(i*33);
    const end=data.adapter.getWalkthroughState();assert(Math.abs(end.position.x-2)<.01);assert.equal(end.position.y,0);
    assert.equal(JSON.stringify(layout),before);data.adapter.dispose();
});

// ---- Appearance library: finishes, scenes and equipment decals --------------
// These run against the real three.js r184 math, materials and geometry, with
// the harness renderer and raycaster standing in for WebGL.

let realThreeModule = null;
async function libraryThree() {
    if (!realThreeModule) {
        const { pathToFileURL } = require('url');
        realThreeModule = await import(pathToFileURL(path.join(ROOT,
            'static/vendor/three/0.184.0/build/three.module.min.js')).href);
    }
    const THREE = Object.assign({}, realThreeModule);
    THREE.WebGLRenderer = FakeRenderer;
    THREE.Raycaster = FakeRaycaster;
    delete THREE.PMREMGenerator;
    THREE.TextureLoader = class {
        load(url, onLoad) {
            const texture = new realThreeModule.Texture();
            texture.userData.url = url;
            libraryThree.loads.push(url);
            Promise.resolve().then(() => onLoad && onLoad(texture));
            return texture;
        }
    };
    return THREE;
}
libraryThree.loads = [];

function libraryStore() {
    const read = name => JSON.parse(fs.readFileSync(path.join(ROOT, 'static/facility_library', name + '.json'), 'utf8'));
    const libraryApi = require('../static/facility_layout_library.js');
    const library = libraryApi.indexLibrary({ appearances: read('appearances'), scenes: read('scenes'), decals: read('decals') });
    return { get: () => library, load: () => Promise.resolve(library) };
}

async function libraryFixture(extra) {
    const THREE = await libraryThree();
    let resolverCalls = 0;
    const data = fixture(Object.assign({
        THREE,
        facilityLibrary: libraryStore(),
        assetResolver: request => {
            resolverCalls += 1;
            if (request.stage === 'manifest') return asset(request.assetId, request.assetDefinitionRevision);
            if (request.stage === 'overview') {
                const object = new THREE.Group();
                const mesh = new THREE.Mesh(new THREE.BoxGeometry(2, 1, 0.5), new THREE.MeshStandardMaterial({ color: 0x8899aa }));
                mesh.userData.facilityPartKey = 'p:Body#0';
                object.add(mesh);
                return object;
            }
            return null;
        },
    }, extra || {}));
    data.resolverCalls = () => resolverCalls;
    data.adapter.mount(data.host);
    return data;
}

function finishPlacement(id, assetId, x, appearance) {
    const value = placement(id, assetId, REV_A, x, 0, 1);
    if (appearance) value.appearance = appearance;
    return value;
}

function renderedScene() {
    return FakeRenderer.instances.at(-1).lastRender.scene;
}

test('library finishes group identical finishes into one instanced batch and leave plain colors alone', async () => {
    const data = await libraryFixture();
    await data.adapter.setScene({ layout: { placements: [
        finishPlacement('oak-1', 'rack', 0, { appearanceId: 'wood-oak', grain: 'length' }),
        finishPlacement('oak-2', 'rack', 3, { appearanceId: 'wood-oak', grain: 'length' }),
        finishPlacement('plain', 'rack', 6, { color: '#bb4040' }),
        finishPlacement('steel', 'bench', 9, { appearanceId: 'steel-polished' }),
    ] }, assetCatalog: [asset('rack', REV_A), asset('bench', REV_A)] });
    await settleAsync();
    data.scheduler.flush();
    const batches = [];
    let plainMaterial = null, steelMaterial = null;
    renderedScene().traverse(object => {
        if (object.isInstancedMesh && object.material.userData.facilityAppearanceFinish) batches.push(object);
        if (object.userData && object.userData.placementId === 'plain') object.traverse(c => { if (c.isMesh) plainMaterial = c.material; });
        if (object.userData && object.userData.placementId === 'steel') object.traverse(c => { if (c.isMesh) steelMaterial = c.material; });
    });
    assert.strictEqual(batches.length, 1, 'both oak racks share one instanced batch');
    assert.strictEqual(batches[0].count, 2);
    assert.ok(batches[0].geometry.attributes.uv, 'textured finishes carry projected UVs');
    assert.ok(batches[0].material.map && batches[0].material.map.userData.url.endsWith('wood-oak/color.jpg'));
    assert.strictEqual(plainMaterial.color.getHex(), 0xbb4040, 'plain colors keep the original tint path');
    assert.ok(steelMaterial.userData.facilityAppearanceFinish && steelMaterial.metalness === 1);
    data.adapter.setSelection(['oak-1', 'steel']);
    assert.strictEqual(steelMaterial.color.getHexString(), 'c6c9cb', 'selection never overwrites a finish color');
    assert.ok(batches[0].material.color.getHex() === 0xffffff, 'the shared finish material is never tinted');
    const diagnostics = data.adapter.getDiagnostics().appearanceLibrary;
    assert.strictEqual(diagnostics.finishGroups, 2);
    assert.ok(diagnostics.projectedGeometries >= 1);
    data.adapter.dispose();
});

test('colors, scenes and library finishes update without reloading models; geometry edits still rebuild', async () => {
    const data = await libraryFixture();
    const layout = { placements: [finishPlacement('one', 'rack', 0, null), finishPlacement('two', 'rack', 3, null)] };
    const input = { layout, assetCatalog: [asset('rack', REV_A)] };
    await data.adapter.setScene(input);
    await settleAsync();
    const afterFirstBuild = data.resolverCalls();
    const colored = JSON.parse(JSON.stringify(input));
    colored.layout.placements[0].appearance = { color: '#2478bc' };
    await data.adapter.setScene(colored);
    const scened = JSON.parse(JSON.stringify(colored));
    scened.layout.extensions = { facilityScene: { version: 1, sceneId: 'presentation-light' } };
    await data.adapter.setScene(scened);
    assert.strictEqual(data.resolverCalls(), afterFirstBuild, 'no model reload for colors or scenes');
    assert.strictEqual(data.adapter.getViewportScene().sceneId, 'presentation-light');
    const finished = JSON.parse(JSON.stringify(scened));
    finished.layout.placements[1].appearance = { appearanceId: 'brass-brushed' };
    await data.adapter.setScene(finished);
    await settleAsync();
    data.scheduler.flush();
    assert.strictEqual(data.resolverCalls(), afterFirstBuild, 'a finish-only edit reuses the models on screen');
    const materialOf = id => {
        let found = null;
        renderedScene().traverse(o => { if (o.userData && o.userData.placementId === id) o.traverse(c => { if (c.isMesh) found = c.material; }); });
        return found;
    };
    assert.ok(materialOf('two').userData.facilityAppearanceFinish && /brass-brushed/.test(materialOf('two').name));
    assert.ok(!materialOf('one').userData.facilityAppearanceFinish, 'the other copy keeps its own finish');
    assert.strictEqual(data.adapter.getDiagnostics().appearanceLibrary.finishGroups, 1);
    await data.adapter.setScene(scened);
    await settleAsync();
    data.scheduler.flush();
    assert.strictEqual(data.resolverCalls(), afterFirstBuild, 'removing the finish regroups without a reload too');
    let batches = 0;
    renderedScene().traverse(o => { if (o.isInstancedMesh && o.count === 2) batches += 1; });
    assert.ok(batches >= 1, 'both copies share an instanced batch again');
    const moved = JSON.parse(JSON.stringify(scened));
    moved.layout.placements[0].transform.position.x = 1.5;
    await data.adapter.setScene(moved);
    await settleAsync();
    assert.ok(data.resolverCalls() > afterFirstBuild, 'geometry edits still rebuild the scene');
    data.adapter.dispose();
});

test('the saved scene sets base lighting and the viewer settings scale it; Classic keeps the original look', async () => {
    const data = await libraryFixture();
    const scene = sceneId => ({ layout: { placements: [], extensions: sceneId ? { facilityScene: { version: 1, sceneId,
        adjustments: { exposure: 0.9 } } } : {} }, assetCatalog: [] });
    await data.adapter.setScene(scene(null));
    data.scheduler.flush();
    const sceneObject = renderedScene();
    const renderer = FakeRenderer.instances.at(-1);
    let hemisphere = null;
    sceneObject.traverse(object => { if (object.isHemisphereLight) hemisphere = object; });
    assert.strictEqual(hemisphere.intensity, 1.55, 'Classic equals the original defaults');
    assert.strictEqual(renderer.toneMappingExposure, 1.22);
    await data.adapter.setScene(scene('machine-shop'));
    const shopAmbient = sceneManifest('machine-shop').ambient;
    assert.ok(Math.abs(hemisphere.intensity - shopAmbient) < 1e-9);
    assert.ok(Math.abs(renderer.toneMappingExposure - 0.9) < 1e-9, 'scene adjustments apply');
    data.adapter.setVisualSettings({ ambient: 1.55 * 1.5 });
    assert.ok(Math.abs(hemisphere.intensity - shopAmbient * 1.5) < 1e-9, 'Display settings scale the scene');
    await data.adapter.setScene(scene('presentation-dark'));
    assert.strictEqual(sceneObject.background.getHexString(), '1c2026', 'the scene backdrop shows when the viewer has none');
    data.adapter.setVisualSettings({ background: '#112233' });
    assert.strictEqual(sceneObject.background.getHexString(), '112233', 'a viewer background color wins');
    data.adapter.dispose();
});

function sceneManifest(sceneId) {
    const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, 'static/facility_library/scenes.json'), 'utf8'));
    return manifest.scenes.find(scene => scene.sceneId === sceneId);
}

test('under a scene environment finishes keep their own reflections while plain models take the gentler fill', async () => {
    const THREE = await libraryThree();
    THREE.PMREMGenerator = class {
        fromScene() { return { texture: new realThreeModule.Texture() }; }
        fromEquirectangular() { return { texture: new realThreeModule.Texture() }; }
        dispose() {}
    };
    const data = await libraryFixture({ THREE, RoomEnvironment: class { dispose() {} } });
    const placements = [finishPlacement('shiny', 'rack', 0, { appearanceId: 'steel-polished' }), finishPlacement('plain', 'bench', 3, null)];
    const input = extensions => ({ layout: { placements, extensions }, assetCatalog: [asset('rack', REV_A), asset('bench', REV_A)] });
    await data.adapter.setScene(input({}));
    await settleAsync();
    data.scheduler.flush();
    const finishMaterial = () => {
        let found = null;
        renderedScene().traverse(o => { if (o.isMesh && o.material && o.material.userData.facilityAppearanceFinish) found = o.material; });
        return found;
    };
    const classic = finishMaterial();
    assert.strictEqual(classic.envMap.userData.facilityEnvironment, 'room', 'Classic gives finishes a room to reflect');
    assert.strictEqual(classic.envMapIntensity, 0.7);
    assert.strictEqual(renderedScene().environment, null, 'Classic adds no environment light to plain models');

    const preset = sceneManifest('presentation-light');
    await data.adapter.setScene(input({ facilityScene: { version: 1, sceneId: 'presentation-light' } }));
    data.scheduler.flush();
    const lit = finishMaterial();
    assert.strictEqual(renderedScene().environment, lit.envMap, 'finishes reflect the scene environment themselves');
    assert.strictEqual(renderedScene().environmentIntensity, preset.environmentIntensity, 'plain models take the scene fill');
    assert.ok(Math.abs(lit.envMapIntensity - Math.min(2, 2 * preset.environmentIntensity)) < 1e-9);

    await data.adapter.setScene(input({ facilityScene: { version: 1, sceneId: 'presentation-light',
        adjustments: { environmentIntensity: 0.25, environmentRotationDegrees: 90 } } }));
    data.scheduler.flush();
    const turned = finishMaterial();
    assert.ok(Math.abs(turned.envMapIntensity - 0.5) < 1e-9, 'the Reflections setting still scales finishes');
    assert.ok(Math.abs(turned.envMapRotation.y - Math.PI / 2) < 1e-9, 'finish reflections turn with the scene');

    await data.adapter.setScene(input({}));
    data.scheduler.flush();
    const back = finishMaterial();
    assert.strictEqual(back.envMap.userData.facilityEnvironment, 'room');
    assert.strictEqual(back.envMapIntensity, 0.7);
    assert.strictEqual(back.envMapRotation.y, 0, 'back in Classic the room is unturned');
    data.adapter.dispose();
});

test('equipment decals project onto their placement and go away with the saved row', async () => {
    const THREE = await libraryThree();
    class FakeDecalGeometry extends THREE.BufferGeometry {
        constructor(mesh, position, orientation, size) {
            super();
            FakeDecalGeometry.calls.push({ mesh, position: position.clone(), size: size.clone() });
            this.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0], 3));
            this.setAttribute('normal', new THREE.Float32BufferAttribute([0, 0, 1, 0, 0, 1, 0, 0, 1], 3));
            this.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 0, 1], 2));
        }
    }
    FakeDecalGeometry.calls = [];
    const data = await libraryFixture({ DecalGeometry: FakeDecalGeometry });
    const row = { decalId: 'edecal-1', label: 'Forklift warning', imagePath: '/api/facility-decal-images/site-a/' + 'b'.repeat(64) + '.png',
        placementId: 'one', anchor: { position: { x: 0, y: 0.5, z: 0.25 }, normal: { x: 0, y: 0, z: 1 }, rotationDegrees: 0 },
        widthMeters: 0.3, heightMeters: 0.26 };
    const input = { layout: { placements: [finishPlacement('one', 'rack', 4, null)],
        extensions: { facilityEquipmentDecals: { version: 1, decals: [row] } } }, assetCatalog: [asset('rack', REV_A)] };
    await data.adapter.setScene(input);
    await settleAsync();
    data.scheduler.flush();
    assert.strictEqual(data.adapter.getDiagnostics().appearanceLibrary.equipmentDecals, 1);
    const call = FakeDecalGeometry.calls.at(-1);
    assert.ok(Math.abs(call.position.x - 4) < 1e-9 && Math.abs(call.position.z - 1.25) < 1e-9,
        'the anchor follows the placement transform into world space');
    let decalMeshes = 0;
    renderedScene().traverse(object => { if (object.userData && object.userData.facilityEquipmentDecal) decalMeshes += 1; });
    assert.ok(decalMeshes >= 1);
    const without = JSON.parse(JSON.stringify(input));
    without.layout.extensions.facilityEquipmentDecals.decals = [];
    await data.adapter.setScene(without);
    assert.strictEqual(data.adapter.getDiagnostics().appearanceLibrary.equipmentDecals, 0);
    data.adapter.dispose();
});

test('a live finish preview replaces the copy on screen and clearing restores it untouched', async () => {
    const data = await libraryFixture();
    await data.adapter.setScene({ layout: { placements: [finishPlacement('first', 'rack', 0, null),
        finishPlacement('second', 'rack', 3, null)] }, assetCatalog: [asset('rack', REV_A)] });
    await settleAsync();
    data.scheduler.flush();
    let batch = null;
    renderedScene().traverse(object => { if (object.isInstancedMesh) batch = object; });
    const before = new realThreeModule.Matrix4();
    batch.getMatrixAt(0, before);
    assert.ok(data.adapter.previewFinish({ placementIds: ['first'], appearance: { appearanceId: 'brass-polished' } }));
    const hidden = new realThreeModule.Matrix4();
    batch.getMatrixAt(0, hidden);
    assert.ok(hidden.elements.every(value => value === 0 || value === 1) && hidden.elements[0] === 0, 'the instance is hidden');
    let previews = 0;
    renderedScene().traverse(object => { if (object.userData && object.userData.facilityFinishPreview) previews += 1; });
    assert.strictEqual(previews, 1);
    assert.ok(data.adapter.clearFinishPreview());
    const restored = new realThreeModule.Matrix4();
    batch.getMatrixAt(0, restored);
    assert.deepStrictEqual(Array.from(restored.elements), Array.from(before.elements));
    previews = 0;
    renderedScene().traverse(object => { if (object.userData && object.userData.facilityFinishPreview) previews += 1; });
    assert.strictEqual(previews, 0);
    data.adapter.dispose();
});

test('picking reports the surface normal and the stable part key under the cursor', async () => {
    const data = await libraryFixture();
    await data.adapter.setScene({ layout: { placements: [finishPlacement('solo', 'bench', 2, null)] },
        assetCatalog: [asset('bench', REV_A)] });
    await settleAsync();
    data.scheduler.flush();
    let mesh = null;
    renderedScene().traverse(object => { if (object.isMesh && object.userData.facilityPartKey) mesh = object; });
    mesh.updateMatrixWorld(true);
    FakeRaycaster.nextHits = [{ object: mesh, point: { x: 2, y: 0.5, z: 1.25 },
        face: { normal: new realThreeModule.Vector3(0, 0, 1) } }];
    const hit = data.adapter.pick({ normalized: true, x: 0, y: 0 });
    assert.strictEqual(hit.placementId, 'solo');
    assert.strictEqual(hit.partKey, 'p:Body#0');
    assert.ok(Math.abs(hit.normal.z - 1) < 1e-9);
    const anchor = data.adapter.decalAnchorAt({ normalized: true, x: 0, y: 0 }, 15);
    assert.strictEqual(anchor.placementId, 'solo');
    assert.deepStrictEqual(anchor.anchor.position, { x: 0, y: 0.5, z: 0.25 }, 'anchors are saved in placement coordinates');
    assert.strictEqual(anchor.anchor.rotationDegrees, 15);
    data.adapter.dispose();
});

test('object finishes replace authored asset colors but keep printed artwork', async () => {
    const THREE = await libraryThree();
    const authored = () => {
        const material = new THREE.MeshStandardMaterial({ color: 0x17191c });
        material.name = 'APEX frame';
        material.userData = { facilityAuthoredFinish: true, facilityMaterialRole: 'frame' };
        return material;
    };
    const artwork = () => {
        const material = new THREE.MeshStandardMaterial({ map: new realThreeModule.Texture() });
        material.userData = { facilityArtwork: true };
        return material;
    };
    const data = await libraryFixture({
        assetResolver: request => {
            if (request.stage === 'manifest') return asset(request.assetId, request.assetDefinitionRevision);
            if (request.stage !== 'overview') return null;
            const object = new THREE.Group();
            const frame = new THREE.Mesh(new THREE.BoxGeometry(2, 1, 0.5), authored());
            const print = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.01), artwork());
            frame.userData.facilityPartKey = 'p:world/frame#0';
            object.add(frame, print);
            return object;
        },
    });
    const finishes = () => {
        const seen = { finish: 0, artwork: 0, authoredKept: 0 };
        renderedScene().traverse(o => {
            if (!o.isMesh || !o.material) return;
            const u = o.material.userData || {};
            if (u.facilityAppearanceFinish) seen.finish += 1;
            else if (u.facilityArtwork) seen.artwork += 1;
            else if (u.facilityAuthoredFinish) seen.authoredKept += 1;
        });
        return seen;
    };
    await data.adapter.setScene({ layout: { placements: [finishPlacement('solo', 'table', 0, { appearanceId: 'brass-polished' })] },
        assetCatalog: [asset('table', REV_A)] });
    await settleAsync();
    data.scheduler.flush();
    let seen = finishes();
    assert.ok(seen.finish >= 1 && seen.authoredKept === 0, 'a single copy takes the finish over its authored color');
    assert.ok(seen.artwork >= 1, 'printed artwork keeps its look');
    await data.adapter.setScene({ layout: { placements: [finishPlacement('one', 'table', 0, { appearanceId: 'brass-polished' }),
        finishPlacement('two', 'table', 3, { appearanceId: 'brass-polished' })] }, assetCatalog: [asset('table', REV_A)] });
    await settleAsync();
    data.scheduler.flush();
    seen = finishes();
    assert.ok(seen.finish >= 1 && seen.authoredKept === 0, 'instanced copies take the finish too');
    assert.ok(seen.artwork >= 1);
    data.adapter.dispose();
});

test('a previewed object stays pickable, and instanced copies report a part only when asked', async () => {
    const data = await libraryFixture();
    await data.adapter.setScene({ layout: { placements: [finishPlacement('first', 'rack', 0, null),
        finishPlacement('second', 'rack', 3, null)] }, assetCatalog: [asset('rack', REV_A)] });
    await settleAsync();
    data.scheduler.flush();
    let batch = null;
    renderedScene().traverse(object => { if (object.isInstancedMesh) batch = object; });
    const original = FakeRaycaster.prototype.intersectObjects;
    let targets = [];
    FakeRaycaster.prototype.intersectObjects = function (list) { targets = list; return original.call(this, list); };
    FakeRaycaster.prototype.intersectObject = function (object) {
        let mesh = null;
        object.traverse(item => { if (!mesh && item.isMesh && item.userData.facilityPartKey) mesh = item; });
        return mesh ? [{ object: mesh }] : [];
    };
    try {
        const face = { normal: new realThreeModule.Vector3(0, 1, 0) };
        FakeRaycaster.nextHits = [{ object: batch, instanceId: 1, point: { x: 3, y: 1, z: 0 }, face }];
        assert.strictEqual(data.adapter.pick({ normalized: true, x: 0, y: 0 }).partKey, undefined,
            'plain picks skip the part search');
        const asked = data.adapter.pick({ normalized: true, x: 0, y: 0, parts: true });
        assert.strictEqual(asked.placementId, 'second');
        assert.strictEqual(asked.partKey, 'p:Body#0', 'the part is found on a copy of the instanced model');

        assert.ok(data.adapter.previewFinish({ placementIds: ['first'], appearance: { appearanceId: 'brass-polished' } }));
        let previewMesh = null;
        renderedScene().traverse(object => {
            if (object.userData && object.userData.facilityFinishPreview) {
                object.traverse(item => { if (!previewMesh && item.isMesh) previewMesh = item; });
            }
        });
        previewMesh.updateMatrixWorld(true);
        FakeRaycaster.nextHits = [{ object: previewMesh, point: { x: 0, y: 1, z: 0 }, face }];
        const hit = data.adapter.pick({ normalized: true, x: 0, y: 0, parts: true });
        assert.ok(targets.some(item => item.userData && item.userData.facilityFinishPreview),
            'the preview is among the pick targets');
        assert.strictEqual(hit.placementId, 'first', 'the preview picks as the placement it stands in for');
        assert.strictEqual(hit.partKey, 'p:Body#0');
        data.adapter.clearFinishPreview();
    } finally {
        FakeRaycaster.prototype.intersectObjects = original;
        delete FakeRaycaster.prototype.intersectObject;
    }
    data.adapter.dispose();
});

test('the ground layer hides the paving and keeps it hidden when the paving is rebuilt', async () => {
    const THREE=createThree();
    THREE.BufferGeometry=class extends FakeBufferGeometry {
        setIndex(value){this.index=value;return this;}
        computeVertexNormals(){this.normalsComputed=true;}
    };
    const data=fixture({THREE,worldBounds:{minX:0,minZ:0,maxX:40,maxZ:10,floorY:0}});
    const surface=(id,a,b)=>({surfaceId:id,minX:a,maxX:b,minZ:0,maxZ:10,startElevation:0,endElevation:0,slopeAxis:'x',color:'#888888'});
    const layout=surfaces=>({placements:[],extensions:{facilityGround:{schemaVersion:1,surfaces:surfaces}}});
    const shown=name=>{
        let found=null;
        FakeRenderer.instances.at(-1).lastRender.scene.traverse(object=>{if(object.name===name)found=object;});
        if(!found)return null;
        for(let object=found;object;object=object.parent){if(!object.visible)return false;}
        return true;
    };
    const before=layout([surface('yard',-30,0),surface('factory',0,40)]);
    const authoritative=JSON.stringify(before);data.adapter.mount(data.host);
    await data.adapter.setScene({layout:before});data.scheduler.flush();
    assert.equal(shown('InspectorProGround-yard'),true);
    assert.equal(data.adapter.setLayerVisibility({ground:false}).ground,false);data.scheduler.flush();
    assert.equal(shown('InspectorProGround-yard'),false);
    await data.adapter.setScene({layout:layout([surface('yard',-35,0),surface('factory',0,40)])});data.scheduler.flush();
    assert.equal(shown('InspectorProGround-yard'),false);
    assert.equal(data.adapter.setLayerVisibility({ground:true}).ground,true);data.scheduler.flush();
    assert.equal(shown('InspectorProGround-yard'),true);
    assert.equal(JSON.stringify(before),authoritative);data.adapter.dispose();
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
