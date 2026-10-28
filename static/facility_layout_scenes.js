(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityScenes = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    // Viewport scenes: image-based lighting and the helpers that place a sun
    // shadow over the facility. A scene changes how the viewport looks, never
    // the layout. Environments load from bundled files only.

    function createEnvironmentLoader(options) {
        const settings = options || {};
        const THREE = settings.THREE;
        let pmrem = null;
        let room = null;
        const hdr = new Map();
        function generator() {
            if (!pmrem && settings.renderer && typeof THREE.PMREMGenerator === 'function') {
                pmrem = new THREE.PMREMGenerator(settings.renderer);
            }
            return pmrem;
        }
        // A neutral studio room built in code: reflections for metals and glass
        // with nothing to download. Used by the Classic scene for library finishes.
        function roomEnvironment() {
            if (room) return room;
            const Room = settings.RoomEnvironment;
            const pmremGenerator = generator();
            if (!Room || !pmremGenerator) return null;
            const scene = new Room();
            room = pmremGenerator.fromScene(scene, 0.04).texture;
            room.userData = Object.assign({}, room.userData, { facilityEnvironment: 'room' });
            if (typeof scene.dispose === 'function') scene.dispose();
            return room;
        }
        function load(url) {
            if (!url) return Promise.resolve(null);
            if (hdr.has(url)) return hdr.get(url);
            const promise = new Promise(function (resolve, reject) {
                const Loader = settings.HDRLoader;
                const pmremGenerator = generator();
                if (!Loader || !pmremGenerator) {
                    reject(new Error('HDR environments are unavailable in this renderer.'));
                    return;
                }
                new Loader().load(url, function (texture) {
                    texture.mapping = THREE.EquirectangularReflectionMapping;
                    const environment = pmremGenerator.fromEquirectangular(texture).texture;
                    environment.userData = Object.assign({}, environment.userData, { facilityEnvironment: url });
                    resolve({ environment: environment, equirect: texture });
                }, undefined, function (error) {
                    reject(error instanceof Error ? error : new Error('The scene environment could not be loaded.'));
                });
            });
            hdr.set(url, promise);
            promise.catch(function () { hdr.delete(url); });
            return promise;
        }
        function dispose() {
            if (room) room.dispose();
            room = null;
            hdr.forEach(function (promise) {
                promise.then(function (value) {
                    if (value && value.environment) value.environment.dispose();
                    if (value && value.equirect) value.equirect.dispose();
                }).catch(function () {});
            });
            hdr.clear();
            if (pmrem) pmrem.dispose();
            pmrem = null;
        }
        return { room: roomEnvironment, load: load, dispose: dispose };
    }

    // Fit a directional light's orthographic shadow camera around the facility
    // so the shadow map covers the floor plan without wasting resolution.
    function fitSunShadow(THREE, light, bounds) {
        if (!light || !light.shadow || !bounds) return false;
        const min = bounds.minimum || bounds.min, max = bounds.maximum || bounds.max;
        if (!min || !max) return false;
        const center = new THREE.Vector3((min.x + max.x) / 2, (min.y + max.y) / 2, (min.z + max.z) / 2);
        const span = Math.max(4, max.x - min.x, max.z - min.z, max.y - min.y);
        const direction = new THREE.Vector3(0.45, 1, 0.55).normalize();
        light.position.copy(center).addScaledVector(direction, span * 1.5);
        if (light.target) {
            light.target.position.copy(center);
            light.target.updateMatrixWorld();
        }
        const camera = light.shadow.camera;
        const half = span * 0.75;
        camera.left = -half; camera.right = half; camera.top = half; camera.bottom = -half;
        camera.near = 0.5; camera.far = span * 4;
        camera.updateProjectionMatrix();
        const size = span > 120 ? 4096 : 2048;
        light.shadow.mapSize.set(size, size);
        light.shadow.bias = -0.0004;
        light.shadow.normalBias = 0.02;
        if (light.shadow.map) {
            light.shadow.map.dispose();
            light.shadow.map = null;
        }
        return true;
    }

    return { createEnvironmentLoader: createEnvironmentLoader, fitSunShadow: fitSunShadow };
}));
