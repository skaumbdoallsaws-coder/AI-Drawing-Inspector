(function (root, factory) {
    'use strict';

    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityThree = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    const RESOLUTION_STAGES = Object.freeze([
        'manifest',
        'footprint',
        'proxy',
        'overview',
        'detail',
    ]);
    const DEFAULT_BOUNDS = Object.freeze({
        minimum: Object.freeze({ x: -0.5, y: 0, z: -0.5 }),
        maximum: Object.freeze({ x: 0.5, y: 1, z: 0.5 }),
    });
    const SELECTED_COLOR = 0x32a8ff;
    const NORMAL_INSTANCE_COLOR = 0xffffff;

    function noop() {}

    function finite(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function stringValue(value, fallback) {
        return typeof value === 'string' && value ? value : fallback;
    }

    function sortedUniqueStrings(values) {
        return Array.from(new Set((Array.isArray(values) ? values : [])
            .filter(function (value) {
                return typeof value === 'string' && value;
            }))).sort();
    }

    function copyPoint(value, fallback) {
        const source = value && typeof value === 'object' ? value : {};
        return {
            x: finite(source.x, fallback.x),
            y: finite(source.y, fallback.y),
            z: finite(source.z, fallback.z),
        };
    }

    function copyQuaternion(value) {
        const source = value && typeof value === 'object' ? value : {};
        return {
            x: finite(source.x, 0),
            y: finite(source.y, 0),
            z: finite(source.z, 0),
            w: finite(source.w, 1),
        };
    }

    function validBounds(value) {
        if (!value || typeof value !== 'object') return null;
        const minimum = value.minimum;
        const maximum = value.maximum;
        if (!minimum || !maximum) return null;
        const result = {
            minimum: copyPoint(minimum, DEFAULT_BOUNDS.minimum),
            maximum: copyPoint(maximum, DEFAULT_BOUNDS.maximum),
        };
        if (result.maximum.x <= result.minimum.x
            || result.maximum.y <= result.minimum.y
            || result.maximum.z <= result.minimum.z) {
            return null;
        }
        return result;
    }

    function boundsFromFootprint(geometry) {
        if (!geometry || typeof geometry !== 'object') return null;
        const polygons = geometry.footprintPolygons;
        if (!Array.isArray(polygons) || !polygons.length) return null;
        let minX = Infinity;
        let maxX = -Infinity;
        let minZ = Infinity;
        let maxZ = -Infinity;
        polygons.forEach(function (polygon) {
            if (!Array.isArray(polygon)) return;
            polygon.forEach(function (point) {
                const x = Number(point && point.x);
                const z = Number(point && point.z);
                if (!Number.isFinite(x) || !Number.isFinite(z)) return;
                minX = Math.min(minX, x);
                maxX = Math.max(maxX, x);
                minZ = Math.min(minZ, z);
                maxZ = Math.max(maxZ, z);
            });
        });
        if (!Number.isFinite(minX) || maxX <= minX || maxZ <= minZ) return null;
        const interval = geometry.heightInterval || {};
        const minY = finite(interval.minimumY, 0);
        const maxY = finite(interval.maximumY, minY + 1);
        return validBounds({
            minimum: { x: minX, y: minY, z: minZ },
            maximum: { x: maxX, y: maxY, z: maxZ },
        });
    }

    function extractBounds(value) {
        if (!value || typeof value !== 'object') return null;
        const candidates = [
            value.aabb,
            value.selectionBounds,
            value.geometry && value.geometry.aabb,
            value.geometry && value.geometry.selectionBounds,
            value.definition && value.definition.geometry
                && value.definition.geometry.aabb,
            value.assetDefinition && value.assetDefinition.geometry
                && value.assetDefinition.geometry.aabb,
            value.manifest && value.manifest.geometry
                && value.manifest.geometry.aabb,
        ];
        for (let index = 0; index < candidates.length; index += 1) {
            const normalized = validBounds(candidates[index]);
            if (normalized) return normalized;
        }
        const geometries = [
            value.geometry,
            value.definition && value.definition.geometry,
            value.assetDefinition && value.assetDefinition.geometry,
            value.manifest && value.manifest.geometry,
        ];
        for (let index = 0; index < geometries.length; index += 1) {
            const normalized = boundsFromFootprint(geometries[index]);
            if (normalized) return normalized;
        }
        return null;
    }

    function cloneBounds(value) {
        const bounds = validBounds(value) || DEFAULT_BOUNDS;
        return {
            minimum: copyPoint(bounds.minimum, DEFAULT_BOUNDS.minimum),
            maximum: copyPoint(bounds.maximum, DEFAULT_BOUNDS.maximum),
        };
    }

    function normalizePlacement(value, index) {
        const placement = value && typeof value === 'object' ? value : {};
        const transform = placement.transform && typeof placement.transform === 'object'
            ? placement.transform : {};
        return {
            placementId: stringValue(placement.placementId, 'placement-' + index),
            assetId: stringValue(placement.assetId, 'unknown-asset'),
            assetDefinitionRevision: stringValue(
                placement.assetDefinitionRevision,
                'unknown-revision'
            ),
            transform: {
                position: copyPoint(
                    transform.position,
                    { x: 0, y: 0, z: 0 }
                ),
                quaternion: copyQuaternion(transform.quaternion),
                scale: finite(transform.scale, 1),
            },
            source: placement,
        };
    }

    function catalogRecords(catalog) {
        if (Array.isArray(catalog)) return catalog.slice();
        if (!catalog || typeof catalog !== 'object') return [];
        if (Array.isArray(catalog.entries)) return catalog.entries.slice();
        if (Array.isArray(catalog.assets)) return catalog.assets.slice();
        return Object.keys(catalog).sort().map(function (key) {
            const value = catalog[key];
            if (!value || typeof value !== 'object') return null;
            if (value.assetId) return value;
            return Object.assign({ assetId: key }, value);
        }).filter(Boolean);
    }

    function catalogRevision(record) {
        return stringValue(
            record && (
                record.assetDefinitionRevision
                || record.publishedAssetDefinitionRevision
                || record.definitionRevision
                || (record.definition && record.definition.assetDefinitionRevision)
            ),
            ''
        );
    }

    function buildCatalogIndex(catalog) {
        const exact = new Map();
        const byAsset = new Map();
        catalogRecords(catalog).forEach(function (record) {
            const assetId = stringValue(record && record.assetId, '');
            if (!assetId) return;
            const revision = catalogRevision(record);
            if (revision) exact.set(assetId + '|' + revision, record);
            if (!byAsset.has(assetId)) byAsset.set(assetId, record);
        });
        return { exact: exact, byAsset: byAsset };
    }

    function representationDescriptor(source, stage) {
        if (!source || typeof source !== 'object') return null;
        const directNames = {
            footprint: ['footprint', 'footprintGeometry'],
            proxy: ['proxy', 'proxyGeometry', 'collisionProxy'],
            overview: ['overview', 'overviewGeometry'],
            detail: ['detail', 'detailGeometry'],
        };
        const names = directNames[stage] || [];
        for (let index = 0; index < names.length; index += 1) {
            if (source[names[index]] !== undefined) return source[names[index]];
        }
        const representations = source.representations;
        if (representations && representations[stage] !== undefined) {
            return representations[stage];
        }
        const renderBundle = source.renderBundle || source.manifest;
        if (renderBundle && renderBundle !== source) {
            return representationDescriptor(renderBundle, stage);
        }
        if (stage === 'overview' && Array.isArray(source.lodArtifacts)) {
            const overview = source.overviewGeometry || {};
            const match = source.lodArtifacts.find(function (item) {
                return String(item && item.lodId) === String(overview.lodId);
            });
            return match || null;
        }
        if (stage === 'detail' && Array.isArray(source.lodArtifacts)) {
            return source.lodArtifacts[0] || null;
        }
        return null;
    }

    function createThreeAdapter(inputOptions) {
        const options = inputOptions || {};
        const THREE = options.THREE || (root && root.THREE);
        const OrbitControls = options.OrbitControls
            || (THREE && THREE.OrbitControls)
            || (root && root.OrbitControls);
        const GLTFLoader = options.GLTFLoader
            || (THREE && THREE.GLTFLoader)
            || (root && root.GLTFLoader);
        const assetResolver = options.assetResolver || null;
        const ResizeObserverType = options.ResizeObserver
            || (root && root.ResizeObserver);
        const requestFrame = options.requestAnimationFrame
            || (root && root.requestAnimationFrame
                ? root.requestAnimationFrame.bind(root) : null);
        const cancelFrame = options.cancelAnimationFrame
            || (root && root.cancelAnimationFrame
                ? root.cancelAnimationFrame.bind(root) : null);
        const AbortControllerType = options.AbortController
            || (root && root.AbortController);
        const logger = options.logger || (root && root.console) || {};

        const state = {
            host: null,
            mounted: false,
            disposed: false,
            degraded: false,
            contextLost: false,
            status: 'unmounted',
            statusReason: null,
            renderer: null,
            scene: null,
            modelRoot: null,
            camera: null,
            controls: null,
            raycaster: null,
            canvas: null,
            resizeObserver: null,
            resizeHandler: null,
            contextLostHandler: null,
            contextRestoredHandler: null,
            controlChangeHandler: null,
            pointerHandler: null,
            selectionHandler: null,
            frameId: null,
            needsRender: false,
            mountGeneration: 0,
            sceneGeneration: 0,
            abortController: null,
            currentInput: null,
            ghostInput: null,
            ghostObject: null,
            placements: [],
            baseGroups: new Map(),
            renderGroups: new Map(),
            pickObjects: [],
            instanceLookup: new Map(),
            selectedIds: new Set(),
            loadTrace: [],
            warnings: [],
            pendingLoads: 0,
            renderRequests: 0,
            renderedFrames: 0,
            mountCount: 0,
            teardownCount: 0,
            listenerCount: 0,
            lastFit: null,
            worldBounds: null,
        };

        function notifyStatus(status, reason) {
            state.status = status;
            state.statusReason = reason || null;
            if (typeof options.onStatusChange === 'function') {
                options.onStatusChange({
                    status: state.status,
                    reason: state.statusReason,
                    degraded: state.degraded,
                    contextLost: state.contextLost,
                });
            }
        }

        function warning(code, message, detail) {
            state.warnings.push({
                code: String(code),
                message: String(message),
                detail: detail === undefined ? null : String(detail),
            });
        }

        function reportError(code, error) {
            warning(code, error && error.message ? error.message : String(error));
            if (logger && typeof logger.warn === 'function') {
                logger.warn('InspectorPro facility renderer: ' + code, error);
            }
        }

        function enterDegraded(reason, contextLost) {
            state.degraded = true;
            state.contextLost = Boolean(contextLost);
            state.needsRender = false;
            if (state.frameId !== null && cancelFrame) {
                cancelFrame(state.frameId);
            }
            state.frameId = null;
            notifyStatus('degraded', reason);
            if (typeof options.onDegraded === 'function') {
                options.onDegraded({
                    reason: reason,
                    contextLost: state.contextLost,
                });
            }
        }

        function objectTransform(object) {
            if (!object) return null;
            const position = object.position || {};
            const quaternion = object.quaternion || {};
            const scale = object.scale || {};
            return {
                position: {
                    x: finite(position.x, 0),
                    y: finite(position.y, 0),
                    z: finite(position.z, 0),
                },
                quaternion: {
                    x: finite(quaternion.x, 0),
                    y: finite(quaternion.y, 0),
                    z: finite(quaternion.z, 0),
                    w: finite(quaternion.w, 1),
                },
                scale: {
                    x: finite(scale.x, 1),
                    y: finite(scale.y, 1),
                    z: finite(scale.z, 1),
                },
            };
        }

        function appendCanvas(host, canvas) {
            if (!host || !canvas || typeof host.appendChild !== 'function') return;
            if (canvas.parentNode !== host) host.appendChild(canvas);
            if (canvas.style) {
                canvas.style.display = 'block';
                canvas.style.width = '100%';
                canvas.style.height = '100%';
            }
            if (typeof canvas.setAttribute === 'function') {
                canvas.setAttribute('aria-label', 'Facility layout 3D view');
            }
        }

        function removeCanvas() {
            const canvas = state.canvas;
            if (!canvas) return;
            if (canvas.parentNode && typeof canvas.parentNode.removeChild === 'function') {
                canvas.parentNode.removeChild(canvas);
            } else if (typeof canvas.remove === 'function') {
                canvas.remove();
            }
        }

        function addListener(target, type, handler, listenerOptions) {
            if (!target || typeof target.addEventListener !== 'function') return;
            target.addEventListener(type, handler, listenerOptions);
            state.listenerCount += 1;
        }

        function removeListener(target, type, handler, listenerOptions) {
            if (!target || !handler || typeof target.removeEventListener !== 'function') return;
            target.removeEventListener(type, handler, listenerOptions);
            state.listenerCount = Math.max(0, state.listenerCount - 1);
        }

        function resize() {
            if (!state.mounted || !state.renderer || !state.camera || !state.host) {
                return false;
            }
            let width = finite(state.host.clientWidth, 0);
            let height = finite(state.host.clientHeight, 0);
            if ((!width || !height)
                && typeof state.host.getBoundingClientRect === 'function') {
                const rect = state.host.getBoundingClientRect();
                width = finite(rect && rect.width, width);
                height = finite(rect && rect.height, height);
            }
            width = Math.max(1, width || 1);
            height = Math.max(1, height || 1);
            if (typeof state.renderer.setSize === 'function') {
                state.renderer.setSize(width, height, false);
            }
            if (state.camera.isOrthographicCamera) {
                const halfHeight = Math.max(1, finite(state.camera.top, 1));
                const halfWidth = halfHeight * width / height;
                state.camera.left = -halfWidth;
                state.camera.right = halfWidth;
            } else {
                state.camera.aspect = width / height;
            }
            if (typeof state.camera.updateProjectionMatrix === 'function') {
                state.camera.updateProjectionMatrix();
            }
            invalidate();
            return true;
        }

        function renderNow() {
            if (!state.mounted || state.degraded
                || !state.renderer || !state.scene || !state.camera) {
                return false;
            }
            try {
                state.renderer.render(state.scene, state.camera);
                state.renderedFrames += 1;
                return true;
            } catch (error) {
                reportError('render_failed', error);
                enterDegraded('render_failed', false);
                return false;
            }
        }

        function onAnimationFrame(generation) {
            state.frameId = null;
            if (!state.mounted || generation !== state.mountGeneration) return;
            if (!state.needsRender) return;
            state.needsRender = false;
            renderNow();
        }

        function invalidate() {
            state.renderRequests += 1;
            if (!state.mounted || state.degraded || !state.renderer) return false;
            state.needsRender = true;
            if (state.frameId !== null) return true;
            if (!requestFrame) {
                state.needsRender = false;
                return renderNow();
            }
            const generation = state.mountGeneration;
            state.frameId = requestFrame(function () {
                onAnimationFrame(generation);
            });
            return true;
        }

        function makeSceneGraph() {
            state.scene = new THREE.Scene();
            const RootType = THREE.Group || THREE.Object3D;
            state.modelRoot = new RootType();
            state.modelRoot.name = 'InspectorProFacilityModelRoot';
            state.scene.add(state.modelRoot);
            state.camera = options.camera || new THREE.PerspectiveCamera(
                finite(options.fov, 40),
                1,
                0.01,
                10000
            );
            if (state.camera.position && typeof state.camera.position.set === 'function') {
                state.camera.position.set(8, 8, 8);
            }
            if (typeof THREE.HemisphereLight === 'function') {
                state.scene.add(new THREE.HemisphereLight(0xffffff, 0x334155, 1.7));
            }
            if (typeof THREE.DirectionalLight === 'function') {
                const light = new THREE.DirectionalLight(0xffffff, 1.35);
                if (light.position && typeof light.position.set === 'function') {
                    light.position.set(8, 16, 10);
                }
                state.scene.add(light);
            }
            if (typeof THREE.Raycaster === 'function') {
                state.raycaster = new THREE.Raycaster();
            }
        }

        function attachRuntime() {
            state.contextLostHandler = function (event) {
                if (event && typeof event.preventDefault === 'function') {
                    event.preventDefault();
                }
                enterDegraded('webgl_context_lost', true);
            };
            state.contextRestoredHandler = function () {
                state.contextLost = false;
                state.degraded = false;
                notifyStatus('ready', null);
                invalidate();
            };
            addListener(
                state.canvas,
                'webglcontextlost',
                state.contextLostHandler,
                false
            );
            addListener(
                state.canvas,
                'webglcontextrestored',
                state.contextRestoredHandler,
                false
            );
            state.pointerHandler = function (event) {
                const result = pick(event);
                if (result && state.selectionHandler) {
                    state.selectionHandler(result.placementId, api);
                }
            };
            addListener(
                state.canvas,
                'pointerup',
                state.pointerHandler,
                false
            );

            if (typeof OrbitControls === 'function') {
                state.controls = new OrbitControls(state.camera, state.canvas);
                state.controls.minPolarAngle = 0.03;
                state.controls.maxPolarAngle = Math.PI / 2 - 0.03;
                state.controlChangeHandler = invalidate;
                addListener(state.controls, 'change', state.controlChangeHandler);
            }

            if (typeof ResizeObserverType === 'function') {
                state.resizeHandler = resize;
                state.resizeObserver = new ResizeObserverType(state.resizeHandler);
                state.resizeObserver.observe(state.host);
            }
        }

        function disposeMaterial(material, seenMaterials, seenTextures) {
            if (!material || seenMaterials.has(material)) return;
            seenMaterials.add(material);
            Object.keys(material).forEach(function (key) {
                const candidate = material[key];
                if (candidate && candidate.isTexture && !seenTextures.has(candidate)) {
                    seenTextures.add(candidate);
                    if (typeof candidate.dispose === 'function') candidate.dispose();
                }
            });
            if (typeof material.dispose === 'function') material.dispose();
        }

        function disposeObjectGraphs(objects) {
            const seenObjects = new Set();
            const seenGeometries = new Set();
            const seenMaterials = new Set();
            const seenTextures = new Set();
            (objects || []).filter(Boolean).forEach(function (rootObject) {
                const visit = function (object) {
                    if (!object || seenObjects.has(object)) return;
                    seenObjects.add(object);
                    if (object.geometry && !seenGeometries.has(object.geometry)) {
                        seenGeometries.add(object.geometry);
                        if (typeof object.geometry.dispose === 'function') {
                            object.geometry.dispose();
                        }
                    }
                    const materials = Array.isArray(object.material)
                        ? object.material : [object.material];
                    materials.filter(Boolean).forEach(function (material) {
                        disposeMaterial(material, seenMaterials, seenTextures);
                    });
                };
                if (typeof rootObject.traverse === 'function') {
                    rootObject.traverse(visit);
                } else {
                    visit(rootObject);
                }
            });
        }

        function disposeRenderGroup(record) {
            if (!record) return;
            if (record.container && record.container.parent
                && typeof record.container.parent.remove === 'function') {
                record.container.parent.remove(record.container);
            } else if (record.container && state.modelRoot
                && typeof state.modelRoot.remove === 'function') {
                state.modelRoot.remove(record.container);
            }
            disposeObjectGraphs([record.container, record.prototypeObject]);
            record.pickObjects.forEach(function (object) {
                state.instanceLookup.delete(object);
                if (object && object.uuid) state.instanceLookup.delete(object.uuid);
            });
            const removed = new Set(record.pickObjects);
            state.pickObjects = state.pickObjects.filter(function (object) {
                return !removed.has(object);
            });
        }

        function clearModel() {
            disposeGhostObject();
            state.renderGroups.forEach(disposeRenderGroup);
            state.renderGroups.clear();
            state.pickObjects = [];
            state.instanceLookup.clear();
            if (state.modelRoot && Array.isArray(state.modelRoot.children)) {
                while (state.modelRoot.children.length) {
                    const child = state.modelRoot.children[0];
                    if (typeof state.modelRoot.remove === 'function') {
                        state.modelRoot.remove(child);
                    } else {
                        state.modelRoot.children.shift();
                    }
                }
            }
        }

        function disposeGhostObject() {
            if (!state.ghostObject) return;
            if (state.ghostObject.parent
                && typeof state.ghostObject.parent.remove === 'function') {
                state.ghostObject.parent.remove(state.ghostObject);
            }
            disposeObjectGraphs([state.ghostObject]);
            state.ghostObject = null;
        }

        function ghostBounds(ghost) {
            const catalog = state.currentInput && state.currentInput.assetCatalog;
            const index = buildCatalogIndex(catalog);
            const key = String(ghost.assetId || '') + '|'
                + String(ghost.assetDefinitionRevision || '');
            return extractBounds(index.exact.get(key))
                || extractBounds(index.byAsset.get(ghost.assetId))
                || cloneBounds(DEFAULT_BOUNDS);
        }

        function renderGhostObject() {
            disposeGhostObject();
            const ghost = state.ghostInput;
            if (!ghost || !state.mounted || !state.modelRoot || state.degraded) {
                invalidate();
                return false;
            }
            const position = ghost.worldPosition || ghost.position;
            if (!position) return false;
            const prototype = makeFallbackPrototype(ghostBounds(ghost));
            const object = prototype.object;
            const visit = function (candidate) {
                const materials = Array.isArray(candidate && candidate.material)
                    ? candidate.material : [candidate && candidate.material];
                materials.filter(Boolean).forEach(function (material) {
                    material.transparent = true;
                    material.opacity = ghost.valid === false ? 0.28 : 0.34;
                    material.depthWrite = false;
                    if (material.color && typeof material.color.setHex === 'function') {
                        material.color.setHex(
                            ghost.valid === false ? 0xef4444 : 0x8b5cf6
                        );
                    }
                    material.needsUpdate = true;
                });
            };
            if (typeof object.traverse === 'function') object.traverse(visit);
            else visit(object);
            applyPlacementTransform(object, {
                placementId: '__facility_ghost__',
                transform: {
                    position: {
                        x: finite(position.x, 0),
                        y: finite(position.y, 0),
                        z: finite(position.z, 0),
                    },
                    quaternion: ghost.quaternion
                        || { x: 0, y: 0, z: 0, w: 1 },
                    scale: finite(ghost.scale, 1),
                },
            });
            object.name = 'FacilityPlacementGhost';
            object.userData = object.userData || {};
            object.userData.facilityGhost = true;
            state.modelRoot.add(object);
            state.ghostObject = object;
            invalidate();
            return true;
        }

        function abortLoading() {
            state.sceneGeneration += 1;
            if (state.abortController
                && typeof state.abortController.abort === 'function') {
                state.abortController.abort();
            }
            state.abortController = null;
            state.pendingLoads = 0;
        }

        function teardownMount(finalDispose) {
            abortLoading();
            if (state.frameId !== null && cancelFrame) cancelFrame(state.frameId);
            state.frameId = null;
            state.needsRender = false;

            if (state.resizeObserver) {
                state.resizeObserver.disconnect();
                state.resizeObserver = null;
            }
            removeListener(
                state.canvas,
                'webglcontextlost',
                state.contextLostHandler,
                false
            );
            removeListener(
                state.canvas,
                'webglcontextrestored',
                state.contextRestoredHandler,
                false
            );
            removeListener(
                state.canvas,
                'pointerup',
                state.pointerHandler,
                false
            );
            removeListener(
                state.controls,
                'change',
                state.controlChangeHandler
            );
            state.contextLostHandler = null;
            state.contextRestoredHandler = null;
            state.controlChangeHandler = null;
            state.pointerHandler = null;
            state.resizeHandler = null;

            clearModel();
            if (state.controls && typeof state.controls.dispose === 'function') {
                state.controls.dispose();
            }
            if (state.renderer) {
                if (state.renderer.renderLists
                    && typeof state.renderer.renderLists.dispose === 'function') {
                    state.renderer.renderLists.dispose();
                }
                if (typeof state.renderer.dispose === 'function') {
                    state.renderer.dispose();
                }
                if (typeof state.renderer.forceContextLoss === 'function'
                    && !state.contextLost) {
                    state.renderer.forceContextLoss();
                }
            }
            removeCanvas();

            state.renderer = null;
            state.scene = null;
            state.modelRoot = null;
            state.camera = null;
            state.controls = null;
            state.raycaster = null;
            state.canvas = null;
            state.host = null;
            state.mounted = false;
            state.degraded = false;
            state.contextLost = false;
            state.listenerCount = 0;
            state.teardownCount += 1;
            state.disposed = Boolean(finalDispose);
            if (finalDispose) state.ghostInput = null;
            notifyStatus(finalDispose ? 'disposed' : 'unmounted', null);
        }

        function mount(host) {
            if (!host || typeof host.appendChild !== 'function') {
                throw new TypeError('A DOM-like facility renderer host is required.');
            }
            if (state.mounted && state.host === host) return api;
            const replayInput = state.currentInput ? {
                layout: state.currentInput.layout,
                assetCatalog: state.currentInput.assetCatalog,
            } : null;
            const replayGhost = state.ghostInput;
            if (state.mounted || state.renderer || state.canvas) teardownMount(false);

            state.disposed = false;
            state.host = host;
            state.mounted = true;
            state.mountGeneration += 1;
            state.mountCount += 1;
            notifyStatus('mounting', null);

            const webglAllowed = typeof options.webglAvailable === 'function'
                ? options.webglAvailable()
                : options.webglAvailable !== false;
            if (!webglAllowed || !THREE
                || typeof THREE.WebGLRenderer !== 'function'
                || typeof THREE.Scene !== 'function'
                || (typeof THREE.Group !== 'function'
                    && typeof THREE.Object3D !== 'function')
                || typeof THREE.PerspectiveCamera !== 'function') {
                enterDegraded('webgl_unavailable', false);
                return api;
            }

            try {
                state.renderer = typeof options.rendererFactory === 'function'
                    ? options.rendererFactory({ THREE: THREE, host: host })
                    : new THREE.WebGLRenderer({
                        antialias: true,
                        alpha: true,
                        powerPreference: 'high-performance',
                    });
                state.canvas = state.renderer.domElement;
                appendCanvas(host, state.canvas);
                if (typeof state.renderer.setPixelRatio === 'function') {
                    const ratio = finite(
                        options.pixelRatio,
                        finite(root && root.devicePixelRatio, 1)
                    );
                    state.renderer.setPixelRatio(Math.max(1, Math.min(ratio, 2)));
                }
                if (THREE.SRGBColorSpace !== undefined) {
                    state.renderer.outputColorSpace = THREE.SRGBColorSpace;
                }
                makeSceneGraph();
                attachRuntime();
                state.degraded = false;
                state.contextLost = false;
                notifyStatus('ready', null);
                resize();
                if (replayInput) {
                    setScene(replayInput).then(function () {
                        if (replayGhost) setGhostPlacement(replayGhost);
                    }).catch(function (error) {
                        reportError('scene_remount_failed', error);
                    });
                } else if (replayGhost) {
                    setGhostPlacement(replayGhost);
                }
            } catch (error) {
                reportError('webgl_initialization_failed', error);
                if (state.renderer && typeof state.renderer.dispose === 'function') {
                    state.renderer.dispose();
                }
                removeCanvas();
                state.renderer = null;
                state.canvas = null;
                state.scene = null;
                state.modelRoot = null;
                state.camera = null;
                state.controls = null;
                state.raycaster = null;
                enterDegraded('webgl_initialization_failed', false);
            }
            return api;
        }

        function initialize(host) {
            return mount(host);
        }

        function makeFallbackPrototype(bounds) {
            const normalized = cloneBounds(bounds);
            const width = normalized.maximum.x - normalized.minimum.x;
            const height = normalized.maximum.y - normalized.minimum.y;
            const depth = normalized.maximum.z - normalized.minimum.z;
            let geometry = null;
            let material = null;
            let object = null;
            if (typeof THREE.BoxGeometry === 'function') {
                geometry = new THREE.BoxGeometry(width, height, depth);
            }
            const MaterialType = THREE.MeshStandardMaterial
                || THREE.MeshBasicMaterial;
            if (typeof MaterialType === 'function') {
                material = new MaterialType({
                    color: 0x7692a8,
                    transparent: true,
                    opacity: 0.78,
                });
            }
            if (geometry && material && typeof THREE.Mesh === 'function') {
                object = new THREE.Mesh(geometry, material);
            } else {
                const ObjectType = THREE.Object3D || THREE.Group;
                object = new ObjectType();
                object.geometry = geometry;
                object.material = material;
                object.isMesh = Boolean(geometry && material);
            }
            if (object.position && typeof object.position.set === 'function') {
                object.position.set(
                    (normalized.minimum.x + normalized.maximum.x) / 2,
                    (normalized.minimum.y + normalized.maximum.y) / 2,
                    (normalized.minimum.z + normalized.maximum.z) / 2
                );
            }
            object.name = 'FacilityFootprintFallback';
            object.userData = object.userData || {};
            object.userData.facilityRepresentation = 'footprint';
            return {
                object: object,
                instancingEligible: true,
                bounds: normalized,
            };
        }

        function placementMatrix(placement) {
            if (typeof THREE.Matrix4 !== 'function') return placement.transform;
            const matrix = new THREE.Matrix4();
            if (typeof matrix.compose !== 'function'
                || typeof THREE.Vector3 !== 'function'
                || typeof THREE.Quaternion !== 'function') {
                matrix.facilityTransform = placement.transform;
                return matrix;
            }
            const position = placement.transform.position;
            const quaternion = placement.transform.quaternion;
            const scaleValue = placement.transform.scale;
            matrix.compose(
                new THREE.Vector3(position.x, position.y, position.z),
                new THREE.Quaternion(
                    quaternion.x,
                    quaternion.y,
                    quaternion.z,
                    quaternion.w
                ),
                new THREE.Vector3(scaleValue, scaleValue, scaleValue)
            );
            return matrix;
        }

        function collectPrototypeMeshes(object) {
            if (!object) return [];
            if (typeof object.updateMatrixWorld === 'function') {
                object.updateMatrixWorld(true);
            }
            const meshes = [];
            const visit = function (candidate) {
                if (!candidate || !candidate.isMesh
                    || !candidate.geometry || !candidate.material) return;
                let matrix = candidate.matrixWorld;
                if (matrix && typeof matrix.clone === 'function') {
                    matrix = matrix.clone();
                }
                meshes.push({
                    source: candidate,
                    geometry: candidate.geometry,
                    material: candidate.material,
                    matrix: matrix,
                    instancingEligible: !candidate.isSkinnedMesh
                        && !candidate.morphTargetInfluences,
                });
            };
            if (typeof object.traverse === 'function') object.traverse(visit);
            else visit(object);
            return meshes;
        }

        function multiplyPlacementAndPrototype(placement, prototypeMatrix) {
            const placementValue = placementMatrix(placement);
            if (typeof THREE.Matrix4 !== 'function'
                || !prototypeMatrix
                || typeof placementValue.multiplyMatrices !== 'function') {
                return placementValue;
            }
            const result = new THREE.Matrix4();
            result.multiplyMatrices(placementValue, prototypeMatrix);
            return result;
        }

        function applyPlacementTransform(object, placement) {
            const transform = placement.transform;
            if (object.position && typeof object.position.set === 'function') {
                object.position.set(
                    transform.position.x,
                    transform.position.y,
                    transform.position.z
                );
            }
            if (object.quaternion && typeof object.quaternion.set === 'function') {
                object.quaternion.set(
                    transform.quaternion.x,
                    transform.quaternion.y,
                    transform.quaternion.z,
                    transform.quaternion.w
                );
            }
            if (object.scale && typeof object.scale.set === 'function') {
                object.scale.set(
                    transform.scale,
                    transform.scale,
                    transform.scale
                );
            }
            object.userData = object.userData || {};
            object.userData.placementId = placement.placementId;
        }

        function cloneRenderable(prototype) {
            if (prototype && typeof prototype.clone === 'function') {
                const clone = prototype.clone(true);
                if (typeof clone.traverse === 'function') {
                    clone.traverse(function (object) {
                        if (!object || !object.isMesh || !object.material) return;
                        if (Array.isArray(object.material)) {
                            object.material = object.material.map(function (material) {
                                return material && typeof material.clone === 'function'
                                    ? material.clone() : material;
                            });
                        } else if (typeof object.material.clone === 'function') {
                            object.material = object.material.clone();
                        }
                    });
                }
                return clone;
            }
            return prototype;
        }

        function createContainer() {
            const Type = THREE.Group || THREE.Object3D;
            return new Type();
        }

        function baseGroupKey(group) {
            return group.assetId + '|' + group.assetDefinitionRevision;
        }

        function removeExistingGroup(group) {
            const existing = state.renderGroups.get(baseGroupKey(group));
            if (!existing) return;
            disposeRenderGroup(existing);
            state.renderGroups.delete(baseGroupKey(group));
        }

        function buildRenderedGroup(group, prototype, representation) {
            removeExistingGroup(group);
            const container = createContainer();
            container.name = 'FacilityAssetGroup:' + baseGroupKey(group);
            container.userData = container.userData || {};
            container.userData.assetId = group.assetId;
            container.userData.assetDefinitionRevision =
                group.assetDefinitionRevision;
            container.userData.representation = representation;

            const prototypeMeshes = collectPrototypeMeshes(prototype.object);
            const repeated = group.placements.length > 1;
            const eligible = prototype.instancingEligible !== false
                && prototypeMeshes.length > 0
                && prototypeMeshes.every(function (item) {
                    return item.instancingEligible;
                })
                && typeof THREE.InstancedMesh === 'function';
            const useInstancing = repeated && eligible;
            const pickObjects = [];
            const mappings = [];

            if (useInstancing) {
                prototypeMeshes.forEach(function (mesh, meshIndex) {
                    const instances = new THREE.InstancedMesh(
                        mesh.geometry,
                        mesh.material,
                        group.placements.length
                    );
                    const placementIds = [];
                    group.placements.forEach(function (placement, instanceId) {
                        instances.setMatrixAt(
                            instanceId,
                            multiplyPlacementAndPrototype(
                                placement,
                                mesh.matrix
                            )
                        );
                        placementIds.push(placement.placementId);
                    });
                    if (instances.instanceMatrix) {
                        instances.instanceMatrix.needsUpdate = true;
                    }
                    if (typeof instances.computeBoundingBox === 'function') {
                        instances.computeBoundingBox();
                    }
                    if (typeof instances.computeBoundingSphere === 'function') {
                        instances.computeBoundingSphere();
                    }
                    instances.name = 'FacilityInstances:' + baseGroupKey(group)
                        + ':' + meshIndex;
                    instances.userData = instances.userData || {};
                    instances.userData.facilityInstancePlacementIds =
                        placementIds.slice();
                    container.add(instances);
                    pickObjects.push(instances);
                    state.instanceLookup.set(instances, placementIds);
                    if (instances.uuid) {
                        state.instanceLookup.set(instances.uuid, placementIds);
                    }
                    mappings.push({
                        meshIndex: meshIndex,
                        placementIds: placementIds.slice(),
                    });
                });
            } else {
                group.placements.forEach(function (placement) {
                    const object = cloneRenderable(prototype.object);
                    applyPlacementTransform(object, placement);
                    container.add(object);
                    pickObjects.push(object);
                    mappings.push({
                        placementId: placement.placementId,
                    });
                });
            }

            state.modelRoot.add(container);
            const record = {
                baseKey: baseGroupKey(group),
                representationKey: baseGroupKey(group) + '|' + representation,
                assetId: group.assetId,
                assetDefinitionRevision: group.assetDefinitionRevision,
                representation: representation,
                placementIds: group.placements.map(function (placement) {
                    return placement.placementId;
                }),
                instanced: useInstancing,
                meshCount: useInstancing
                    ? prototypeMeshes.length : pickObjects.length,
                mappings: mappings,
                container: container,
                prototypeObject: prototype.object,
                pickObjects: pickObjects,
            };
            state.renderGroups.set(record.baseKey, record);
            state.pickObjects = state.pickObjects.concat(pickObjects);
            applySelection();
            invalidate();
            return record;
        }

        function makeLoader() {
            if (!GLTFLoader) return null;
            if (typeof GLTFLoader === 'function') return new GLTFLoader();
            if (typeof GLTFLoader === 'object') return GLTFLoader;
            return null;
        }

        function loadUrl(url) {
            const loader = makeLoader();
            if (!loader) {
                return Promise.reject(new Error('GLTFLoader is unavailable.'));
            }
            if (typeof loader.loadAsync === 'function') {
                return loader.loadAsync(url);
            }
            if (typeof loader.load === 'function') {
                return new Promise(function (resolve, reject) {
                    loader.load(url, resolve, undefined, reject);
                });
            }
            return Promise.reject(new Error('GLTFLoader has no load method.'));
        }

        function objectFromResult(result) {
            if (!result) return null;
            if (result.isObject3D) return result;
            if (result.scene && result.scene.isObject3D) return result.scene;
            if (result.object3D && result.object3D.isObject3D) {
                return result.object3D;
            }
            if (result.object && result.object.isObject3D) return result.object;
            if (result.geometry && result.material
                && typeof THREE.Mesh === 'function') {
                return new THREE.Mesh(result.geometry, result.material);
            }
            return null;
        }

        function disposeUnadoptedVisual(result) {
            const object = objectFromResult(result);
            if (object) disposeObjectGraphs([object]);
        }

        async function normalizeVisualResult(result, stage, group) {
            if (stage === 'footprint' && (!result || typeof result !== 'object')) {
                return makeFallbackPrototype(group.bounds);
            }
            let resolved = result;
            const url = typeof result === 'string'
                ? result
                : (result && (result.url || result.href || result.path));
            if (url) resolved = await loadUrl(String(url));
            const object = objectFromResult(resolved);
            if (!object) {
                if (stage === 'footprint') {
                    return makeFallbackPrototype(
                        extractBounds(resolved) || group.bounds
                    );
                }
                return null;
            }
            return {
                object: object,
                instancingEligible: !resolved
                    || resolved.instancingEligible !== false,
                bounds: extractBounds(resolved) || group.bounds,
            };
        }

        function resolverMethodName(stage) {
            return stage.charAt(0).toUpperCase() + stage.slice(1);
        }

        async function callResolver(group, stage, manifest, signal) {
            const request = {
                assetId: group.assetId,
                assetDefinitionRevision: group.assetDefinitionRevision,
                placementIds: group.placements.map(function (placement) {
                    return placement.placementId;
                }),
                stage: stage,
                asset: group.catalog,
                manifest: manifest,
                signal: signal || null,
            };
            let result;
            if (typeof assetResolver === 'function') {
                result = await assetResolver(request);
            } else if (assetResolver && typeof assetResolver === 'object') {
                const suffix = resolverMethodName(stage);
                const method = assetResolver['load' + suffix]
                    || assetResolver['resolve' + suffix]
                    || assetResolver.resolveStage
                    || assetResolver.resolve;
                if (typeof method === 'function') {
                    result = await method.call(assetResolver, request);
                }
            }
            if (result !== undefined && result !== null) return result;
            if (stage === 'manifest') {
                return group.catalog && (
                    group.catalog.manifest
                    || group.catalog.renderBundle
                    || group.catalog
                );
            }
            return representationDescriptor(manifest, stage)
                || representationDescriptor(group.catalog, stage);
        }

        function traceLoad(group, stage, status, detail) {
            state.loadTrace.push({
                assetId: group.assetId,
                assetDefinitionRevision: group.assetDefinitionRevision,
                stage: stage,
                status: status,
                detail: detail || null,
            });
        }

        async function resolveGroup(group, generation, signal) {
            let manifest = null;
            for (let index = 0; index < RESOLUTION_STAGES.length; index += 1) {
                const stage = RESOLUTION_STAGES[index];
                if (generation !== state.sceneGeneration || !state.mounted) {
                    return false;
                }
                state.pendingLoads += 1;
                traceLoad(group, stage, 'started', null);
                try {
                    const result = await callResolver(
                        group,
                        stage,
                        manifest,
                        signal
                    );
                    if (generation !== state.sceneGeneration || !state.mounted) {
                        if (stage !== 'manifest') {
                            disposeUnadoptedVisual(result);
                        }
                        return false;
                    }
                    if (stage === 'manifest') {
                        manifest = result || group.catalog || {};
                        const bounds = extractBounds(manifest);
                        if (bounds) {
                            group.bounds = bounds;
                            buildRenderedGroup(
                                group,
                                makeFallbackPrototype(bounds),
                                'footprint'
                            );
                        }
                        traceLoad(group, stage, result ? 'resolved' : 'skipped', null);
                    } else {
                        const prototype = await normalizeVisualResult(
                            result,
                            stage,
                            group
                        );
                        if (generation !== state.sceneGeneration || !state.mounted) {
                            disposeUnadoptedVisual(prototype);
                            return false;
                        }
                        if (prototype) {
                            group.bounds = prototype.bounds || group.bounds;
                            buildRenderedGroup(group, prototype, stage);
                            traceLoad(group, stage, 'resolved', null);
                        } else {
                            traceLoad(group, stage, 'skipped', null);
                        }
                    }
                } catch (error) {
                    const aborted = signal && signal.aborted;
                    traceLoad(
                        group,
                        stage,
                        aborted ? 'cancelled' : 'failed',
                        error && error.message ? error.message : String(error)
                    );
                    if (!aborted) {
                        warning(
                            'asset_stage_failed',
                            'Asset stage failed; the last deterministic representation remains.',
                            group.assetId + ':' + stage
                        );
                    }
                } finally {
                    state.pendingLoads = Math.max(0, state.pendingLoads - 1);
                }
            }
            return true;
        }

        function createBaseGroups(layout, catalog) {
            const catalogIndex = buildCatalogIndex(catalog);
            const placements = Array.isArray(layout && layout.placements)
                ? layout.placements.map(normalizePlacement) : [];
            placements.sort(function (left, right) {
                return left.placementId.localeCompare(right.placementId);
            });
            const groups = new Map();
            placements.forEach(function (placement) {
                const key = placement.assetId + '|'
                    + placement.assetDefinitionRevision;
                if (!groups.has(key)) {
                    const catalogEntry = catalogIndex.exact.get(key)
                        || catalogIndex.byAsset.get(placement.assetId)
                        || {};
                    if (!catalogIndex.exact.has(key) && catalogRevision(catalogEntry)
                        && catalogRevision(catalogEntry)
                            !== placement.assetDefinitionRevision) {
                        warning(
                            'asset_revision_mismatch',
                            'Catalog definition does not match the placement revision.',
                            key
                        );
                    }
                    groups.set(key, {
                        assetId: placement.assetId,
                        assetDefinitionRevision:
                            placement.assetDefinitionRevision,
                        placements: [],
                        catalog: catalogEntry,
                        bounds: extractBounds(catalogEntry)
                            || cloneBounds(DEFAULT_BOUNDS),
                    });
                }
                groups.get(key).placements.push(placement);
            });
            return { placements: placements, groups: groups };
        }

        async function setScene(input) {
            const value = input && typeof input === 'object' ? input : {};
            state.currentInput = {
                layout: value.layout || {},
                assetCatalog: value.assetCatalog || [],
            };
            abortLoading();
            const generation = state.sceneGeneration;
            if (typeof AbortControllerType === 'function') {
                state.abortController = new AbortControllerType();
            }
            const signal = state.abortController
                ? state.abortController.signal : null;

            state.loadTrace = [];
            state.warnings = [];
            state.lastFit = null;
            const built = createBaseGroups(
                state.currentInput.layout,
                state.currentInput.assetCatalog
            );
            state.placements = built.placements;
            state.baseGroups = built.groups;
            state.worldBounds = computeWorldBounds();

            if (!state.mounted || !state.modelRoot || state.degraded) {
                if (!state.mounted) notifyStatus('unmounted', null);
                return getDiagnostics();
            }

            clearModel();
            Array.from(state.baseGroups.keys()).sort().forEach(function (key) {
                const group = state.baseGroups.get(key);
                buildRenderedGroup(
                    group,
                    makeFallbackPrototype(group.bounds),
                    'footprint'
                );
            });
            renderGhostObject();
            state.worldBounds = computeWorldBounds();
            notifyStatus('loading', null);

            const keys = Array.from(state.baseGroups.keys()).sort();
            for (let index = 0; index < keys.length; index += 1) {
                if (generation !== state.sceneGeneration || !state.mounted) {
                    break;
                }
                await resolveGroup(
                    state.baseGroups.get(keys[index]),
                    generation,
                    signal
                );
            }
            if (generation === state.sceneGeneration && state.mounted
                && !state.degraded) {
                notifyStatus('ready', null);
                state.worldBounds = computeWorldBounds();
                invalidate();
            }
            return getDiagnostics();
        }

        function setGhostPlacement(ghost) {
            if (!ghost) {
                state.ghostInput = null;
                disposeGhostObject();
                invalidate();
                return true;
            }
            const position = ghost.worldPosition || ghost.position;
            if (!position
                || !Number.isFinite(Number(position.x))
                || !Number.isFinite(Number(position.z))) {
                return false;
            }
            state.ghostInput = {
                assetId: String(ghost.assetId || ''),
                assetDefinitionRevision: String(
                    ghost.assetDefinitionRevision || ''
                ),
                worldPosition: {
                    x: Number(position.x),
                    y: finite(Number(position.y), 0),
                    z: Number(position.z),
                },
                quaternion: ghost.quaternion
                    ? {
                        x: finite(Number(ghost.quaternion.x), 0),
                        y: finite(Number(ghost.quaternion.y), 0),
                        z: finite(Number(ghost.quaternion.z), 0),
                        w: finite(Number(ghost.quaternion.w), 1),
                    }
                    : { x: 0, y: 0, z: 0, w: 1 },
                scale: finite(Number(ghost.scale), 1),
                valid: ghost.valid !== false,
            };
            return renderGhostObject();
        }

        function rotatePoint(point, quaternion) {
            const x = point.x;
            const y = point.y;
            const z = point.z;
            const qx = quaternion.x;
            const qy = quaternion.y;
            const qz = quaternion.z;
            const qw = quaternion.w;
            const ix = qw * x + qy * z - qz * y;
            const iy = qw * y + qz * x - qx * z;
            const iz = qw * z + qx * y - qy * x;
            const iw = -qx * x - qy * y - qz * z;
            return {
                x: ix * qw + iw * -qx + iy * -qz - iz * -qy,
                y: iy * qw + iw * -qy + iz * -qx - ix * -qz,
                z: iz * qw + iw * -qz + ix * -qy - iy * -qx,
            };
        }

        function transformedBounds(localBounds, placement) {
            const bounds = cloneBounds(localBounds);
            const corners = [];
            [bounds.minimum.x, bounds.maximum.x].forEach(function (x) {
                [bounds.minimum.y, bounds.maximum.y].forEach(function (y) {
                    [bounds.minimum.z, bounds.maximum.z].forEach(function (z) {
                        corners.push({ x: x, y: y, z: z });
                    });
                });
            });
            const output = {
                minimum: { x: Infinity, y: Infinity, z: Infinity },
                maximum: { x: -Infinity, y: -Infinity, z: -Infinity },
            };
            corners.forEach(function (corner) {
                const scaled = {
                    x: corner.x * placement.transform.scale,
                    y: corner.y * placement.transform.scale,
                    z: corner.z * placement.transform.scale,
                };
                const rotated = rotatePoint(
                    scaled,
                    placement.transform.quaternion
                );
                const point = {
                    x: rotated.x + placement.transform.position.x,
                    y: rotated.y + placement.transform.position.y,
                    z: rotated.z + placement.transform.position.z,
                };
                output.minimum.x = Math.min(output.minimum.x, point.x);
                output.minimum.y = Math.min(output.minimum.y, point.y);
                output.minimum.z = Math.min(output.minimum.z, point.z);
                output.maximum.x = Math.max(output.maximum.x, point.x);
                output.maximum.y = Math.max(output.maximum.y, point.y);
                output.maximum.z = Math.max(output.maximum.z, point.z);
            });
            return output;
        }

        function computeWorldBounds() {
            const configured = options.worldBounds;
            const hasConfigured = configured
                && Number.isFinite(Number(configured.minX))
                && Number.isFinite(Number(configured.minZ))
                && Number.isFinite(Number(configured.maxX))
                && Number.isFinite(Number(configured.maxZ))
                && Number(configured.maxX) > Number(configured.minX)
                && Number(configured.maxZ) > Number(configured.minZ);
            const floorY = Number.isFinite(Number(configured && configured.floorY))
                ? Number(configured.floorY) : 0;
            const output = hasConfigured ? {
                minimum: {
                    x: Number(configured.minX),
                    y: floorY,
                    z: Number(configured.minZ),
                },
                maximum: {
                    x: Number(configured.maxX),
                    y: floorY + 0.01,
                    z: Number(configured.maxZ),
                },
            } : {
                minimum: { x: Infinity, y: Infinity, z: Infinity },
                maximum: { x: -Infinity, y: -Infinity, z: -Infinity },
            };
            if (!state.placements.length) return hasConfigured ? output : null;
            state.placements.forEach(function (placement) {
                const group = state.baseGroups.get(
                    placement.assetId + '|' + placement.assetDefinitionRevision
                );
                const bounds = transformedBounds(
                    group ? group.bounds : DEFAULT_BOUNDS,
                    placement
                );
                ['x', 'y', 'z'].forEach(function (axis) {
                    output.minimum[axis] = Math.min(
                        output.minimum[axis],
                        bounds.minimum[axis]
                    );
                    output.maximum[axis] = Math.max(
                        output.maximum[axis],
                        bounds.maximum[axis]
                    );
                });
            });
            return output;
        }

        function setVector(target, value) {
            if (!target) return;
            if (typeof target.set === 'function') {
                target.set(value.x, value.y, value.z);
                return;
            }
            target.x = value.x;
            target.y = value.y;
            target.z = value.z;
        }

        function fit() {
            if (!state.camera || !state.modelRoot || !state.worldBounds
                || state.degraded) return false;
            const beforeRoot = objectTransform(state.modelRoot);
            const bounds = state.worldBounds;
            const center = {
                x: (bounds.minimum.x + bounds.maximum.x) / 2,
                y: (bounds.minimum.y + bounds.maximum.y) / 2,
                z: (bounds.minimum.z + bounds.maximum.z) / 2,
            };
            const fitTarget = options.worldBounds
                && Number.isFinite(Number(options.worldBounds.floorY))
                ? {
                    x: center.x,
                    y: Number(options.worldBounds.floorY),
                    z: center.z,
                }
                : center;
            const size = {
                x: Math.max(0.01, bounds.maximum.x - bounds.minimum.x),
                y: Math.max(0.01, bounds.maximum.y - bounds.minimum.y),
                z: Math.max(0.01, bounds.maximum.z - bounds.minimum.z),
            };
            const span = Math.max(size.x, size.y, size.z, 1);
            const currentTarget = state.controls && state.controls.target
                ? state.controls.target : center;
            const cameraPosition = state.camera.position || {
                x: center.x + 1,
                y: center.y + 1,
                z: center.z + 1,
            };
            let direction = {
                x: finite(cameraPosition.x, center.x + 1)
                    - finite(currentTarget.x, center.x),
                y: finite(cameraPosition.y, center.y + 1)
                    - finite(currentTarget.y, center.y),
                z: finite(cameraPosition.z, center.z + 1)
                    - finite(currentTarget.z, center.z),
            };
            let length = Math.sqrt(
                direction.x * direction.x
                + direction.y * direction.y
                + direction.z * direction.z
            );
            if (!Number.isFinite(length) || length < 0.0001) {
                direction = { x: 1, y: 1, z: 1 };
                length = Math.sqrt(3);
            }
            direction = {
                x: direction.x / length,
                y: direction.y / length,
                z: direction.z / length,
            };

            if (state.camera.isOrthographicCamera) {
                const half = span * 0.65;
                state.camera.top = half;
                state.camera.bottom = -half;
                const aspect = Math.max(0.01, finite(state.camera.aspect, 1));
                state.camera.left = -half * aspect;
                state.camera.right = half * aspect;
            } else {
                const verticalFov = finite(state.camera.fov, 40) * Math.PI / 180;
                const aspect = Math.max(0.01, finite(state.camera.aspect, 1));
                const horizontalFov = 2 * Math.atan(
                    Math.tan(verticalFov / 2) * aspect
                );
                const limitingFov = Math.max(
                    0.01,
                    Math.min(verticalFov, horizontalFov)
                );
                const radius = Math.max(
                    0.5,
                    Math.sqrt(
                        size.x * size.x
                        + size.y * size.y
                        + size.z * size.z
                    ) / 2
                );
                const distance = (
                    radius / Math.sin(limitingFov / 2)
                ) * 1.12;
                setVector(state.camera.position, {
                    x: center.x + direction.x * distance,
                    y: center.y + direction.y * distance,
                    z: center.z + direction.z * distance,
                });
                state.camera.near = Math.max(0.001, distance / 1000);
                state.camera.far = Math.max(100, distance + span * 20);
            }
            if (state.controls && state.controls.target) {
                setVector(state.controls.target, fitTarget);
                if (typeof state.controls.update === 'function') {
                    state.controls.update();
                }
            } else if (typeof state.camera.lookAt === 'function') {
                state.camera.lookAt(
                    fitTarget.x,
                    fitTarget.y,
                    fitTarget.z
                );
            }
            if (typeof state.camera.updateProjectionMatrix === 'function') {
                state.camera.updateProjectionMatrix();
            }
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld(true);
            }
            const afterRoot = objectTransform(state.modelRoot);
            state.lastFit = {
                center: center,
                size: size,
                rootUnchanged: JSON.stringify(beforeRoot)
                    === JSON.stringify(afterRoot),
            };
            invalidate();
            return state.lastFit.rootUnchanged;
        }

        function applyMaterialSelection(material, selected) {
            if (!material) return;
            material.userData = material.userData || {};
            if (!material.userData.facilitySelectionOriginal) {
                material.userData.facilitySelectionOriginal = {
                    emissive: material.emissive
                        && typeof material.emissive.getHex === 'function'
                        ? material.emissive.getHex() : null,
                    emissiveIntensity: finite(material.emissiveIntensity, 0),
                };
            }
            const original = material.userData.facilitySelectionOriginal;
            if (material.emissive && typeof material.emissive.setHex === 'function') {
                material.emissive.setHex(
                    selected ? SELECTED_COLOR : finite(original.emissive, 0)
                );
            }
            if ('emissiveIntensity' in material) {
                material.emissiveIntensity = selected
                    ? 0.75 : original.emissiveIntensity;
            }
            material.needsUpdate = true;
        }

        function applySelection() {
            state.renderGroups.forEach(function (record) {
                if (record.instanced) {
                    record.pickObjects.forEach(function (object) {
                        const placementIds = state.instanceLookup.get(object) || [];
                        if (typeof object.setColorAt === 'function'
                            && typeof THREE.Color === 'function') {
                            placementIds.forEach(function (placementId, instanceId) {
                                object.setColorAt(
                                    instanceId,
                                    new THREE.Color(
                                        state.selectedIds.has(placementId)
                                            ? SELECTED_COLOR
                                            : NORMAL_INSTANCE_COLOR
                                    )
                                );
                            });
                            if (object.instanceColor) {
                                object.instanceColor.needsUpdate = true;
                            }
                        }
                        object.userData = object.userData || {};
                        object.userData.selectedPlacementIds = placementIds.filter(
                            function (placementId) {
                                return state.selectedIds.has(placementId);
                            }
                        );
                    });
                    return;
                }
                record.pickObjects.forEach(function (object) {
                    const placementId = object.userData
                        && object.userData.placementId;
                    const selected = state.selectedIds.has(placementId);
                    const visit = function (candidate) {
                        const materials = Array.isArray(candidate && candidate.material)
                            ? candidate.material : [candidate && candidate.material];
                        materials.filter(Boolean).forEach(function (material) {
                            applyMaterialSelection(material, selected);
                        });
                    };
                    if (typeof object.traverse === 'function') object.traverse(visit);
                    else visit(object);
                });
            });
            invalidate();
        }

        function setSelection(placementIds) {
            const values = typeof placementIds === 'string'
                ? [placementIds]
                : placementIds;
            state.selectedIds = new Set(sortedUniqueStrings(values));
            applySelection();
            return Array.from(state.selectedIds).sort();
        }

        function setSelectionHandler(handler) {
            state.selectionHandler = typeof handler === 'function'
                ? handler
                : null;
        }

        function normalizedPointer(input) {
            const source = input && typeof input === 'object' ? input : {};
            if (source.ndc && Number.isFinite(Number(source.ndc.x))
                && Number.isFinite(Number(source.ndc.y))) {
                return {
                    x: Number(source.ndc.x),
                    y: Number(source.ndc.y),
                };
            }
            if (source.normalized === true
                && Number.isFinite(Number(source.x))
                && Number.isFinite(Number(source.y))) {
                return { x: Number(source.x), y: Number(source.y) };
            }
            if (!state.canvas
                || typeof state.canvas.getBoundingClientRect !== 'function') {
                return null;
            }
            const rect = state.canvas.getBoundingClientRect();
            const width = Math.max(1, finite(rect.width, 1));
            const height = Math.max(1, finite(rect.height, 1));
            const clientX = finite(source.clientX, finite(source.x, rect.left));
            const clientY = finite(source.clientY, finite(source.y, rect.top));
            return {
                x: ((clientX - finite(rect.left, 0)) / width) * 2 - 1,
                y: -((clientY - finite(rect.top, 0)) / height) * 2 + 1,
            };
        }

        function placementIdFromObject(object) {
            let cursor = object;
            while (cursor) {
                if (cursor.userData && cursor.userData.placementId) {
                    return cursor.userData.placementId;
                }
                cursor = cursor.parent;
            }
            return null;
        }

        function pick(input) {
            if (state.degraded || !state.raycaster || !state.camera) return null;
            const pointer = normalizedPointer(input);
            if (!pointer) return null;
            const vector = typeof THREE.Vector2 === 'function'
                ? new THREE.Vector2(pointer.x, pointer.y) : pointer;
            state.raycaster.setFromCamera(vector, state.camera);
            const hits = state.raycaster.intersectObjects(
                state.pickObjects,
                true
            ) || [];
            for (let index = 0; index < hits.length; index += 1) {
                const hit = hits[index];
                let placementId = null;
                const instanceId = Number.isInteger(hit.instanceId)
                    ? hit.instanceId : null;
                if (instanceId !== null) {
                    const mapping = state.instanceLookup.get(hit.object)
                        || state.instanceLookup.get(hit.object && hit.object.uuid)
                        || [];
                    placementId = mapping[instanceId] || null;
                }
                if (!placementId) placementId = placementIdFromObject(hit.object);
                if (!placementId) continue;
                return {
                    placementId: placementId,
                    instanceId: instanceId,
                    point: hit.point ? {
                        x: finite(hit.point.x, 0),
                        y: finite(hit.point.y, 0),
                        z: finite(hit.point.z, 0),
                    } : null,
                };
            }
            return null;
        }

        function worldPointOnFloor(input, floorY) {
            if (state.degraded || !state.raycaster || !state.camera) return null;
            const pointer = normalizedPointer(input);
            if (!pointer) return null;
            const elevation = finite(Number(floorY), 0);
            const vector = typeof THREE.Vector2 === 'function'
                ? new THREE.Vector2(pointer.x, pointer.y) : pointer;
            state.raycaster.setFromCamera(vector, state.camera);
            if (typeof options.floorProjector === 'function') {
                const projected = options.floorProjector({
                    pointer: pointer,
                    floorY: elevation,
                    camera: state.camera,
                    raycaster: state.raycaster,
                });
                return projected ? {
                    x: finite(Number(projected.x), 0),
                    y: elevation,
                    z: finite(Number(projected.z), 0),
                } : null;
            }
            const ray = state.raycaster.ray;
            if (!ray) return null;
            if (typeof ray.intersectPlane === 'function'
                && typeof THREE.Plane === 'function'
                && typeof THREE.Vector3 === 'function') {
                const plane = new THREE.Plane(
                    new THREE.Vector3(0, 1, 0),
                    -elevation
                );
                const target = new THREE.Vector3();
                const hit = ray.intersectPlane(plane, target);
                return hit ? { x: hit.x, y: elevation, z: hit.z } : null;
            }
            const origin = ray.origin;
            const direction = ray.direction;
            if (!origin || !direction || Math.abs(finite(direction.y, 0)) < 1e-12) {
                return null;
            }
            const distance = (elevation - finite(origin.y, 0)) / direction.y;
            if (!Number.isFinite(distance) || distance < 0) return null;
            return {
                x: finite(origin.x, 0) + finite(direction.x, 0) * distance,
                y: elevation,
                z: finite(origin.z, 0) + finite(direction.z, 0) * distance,
            };
        }

        function worldToClient(input) {
            if (state.degraded || !state.camera || !state.canvas
                    || !input || typeof THREE.Vector3 !== 'function') {
                return null;
            }
            const point = new THREE.Vector3(
                finite(Number(input.x), 0),
                finite(Number(input.y), 0),
                finite(Number(input.z), 0)
            );
            if (typeof point.project !== 'function') return null;
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld();
            }
            point.project(state.camera);
            const rect = typeof state.canvas.getBoundingClientRect === 'function'
                ? state.canvas.getBoundingClientRect() : null;
            if (!rect) return null;
            const width = Math.max(1, finite(rect.width, 1));
            const height = Math.max(1, finite(rect.height, 1));
            const clientX = finite(rect.left, 0) + (point.x + 1) * width / 2;
            const clientY = finite(rect.top, 0) + (1 - point.y) * height / 2;
            return {
                x: clientX,
                y: clientY,
                clientX: clientX,
                clientY: clientY,
                ndc: { x: point.x, y: point.y, z: point.z },
                visible: point.z >= -1 && point.z <= 1,
            };
        }

        function copyDiagnosticsGroup(record) {
            return {
                key: record.representationKey,
                assetId: record.assetId,
                assetDefinitionRevision: record.assetDefinitionRevision,
                representation: record.representation,
                placementIds: record.placementIds.slice(),
                instanced: record.instanced,
                meshCount: record.meshCount,
                instanceMappings: record.mappings.map(function (item) {
                    return item.placementIds
                        ? {
                            meshIndex: item.meshIndex,
                            placementIds: item.placementIds.slice(),
                        }
                        : { placementId: item.placementId };
                }),
            };
        }

        function getDiagnostics() {
            const groups = Array.from(state.renderGroups.values())
                .sort(function (left, right) {
                    return left.representationKey.localeCompare(
                        right.representationKey
                    );
                })
                .map(copyDiagnosticsGroup);
            return {
                status: state.status,
                statusReason: state.statusReason,
                mounted: state.mounted,
                disposed: state.disposed,
                degraded: state.degraded,
                contextLost: state.contextLost,
                placementCount: state.placements.length,
                assetGroupCount: state.baseGroups.size,
                representationGroups: groups,
                selectedPlacementIds: Array.from(state.selectedIds).sort(),
                ghostActive: Boolean(state.ghostInput),
                loadTrace: state.loadTrace.map(function (item) {
                    return Object.assign({}, item);
                }),
                warnings: state.warnings.map(function (item) {
                    return Object.assign({}, item);
                }),
                pendingLoads: state.pendingLoads,
                demandRendering: {
                    pendingFrame: state.frameId !== null,
                    renderRequests: state.renderRequests,
                    renderedFrames: state.renderedFrames,
                },
                lifecycle: {
                    mountCount: state.mountCount,
                    teardownCount: state.teardownCount,
                    observerActive: Boolean(state.resizeObserver),
                    listenerCount: state.listenerCount,
                    canvasCount: state.canvas && state.canvas.parentNode ? 1 : 0,
                },
                controlsActive: Boolean(state.controls),
                camera: state.camera ? {
                    position: state.camera.position ? {
                        x: finite(state.camera.position.x, 0),
                        y: finite(state.camera.position.y, 0),
                        z: finite(state.camera.position.z, 0),
                    } : null,
                    target: state.controls && state.controls.target ? {
                        x: finite(state.controls.target.x, 0),
                        y: finite(state.controls.target.y, 0),
                        z: finite(state.controls.target.z, 0),
                    } : null,
                } : null,
                modelRootTransform: objectTransform(state.modelRoot),
                worldBounds: state.worldBounds
                    ? cloneBounds(state.worldBounds) : null,
                lastFit: state.lastFit ? {
                    center: Object.assign({}, state.lastFit.center),
                    size: Object.assign({}, state.lastFit.size),
                    rootUnchanged: state.lastFit.rootUnchanged,
                } : null,
            };
        }

        function dispose() {
            if (!state.mounted && !state.renderer && !state.canvas) {
                state.disposed = true;
                notifyStatus('disposed', null);
                return false;
            }
            teardownMount(true);
            return true;
        }

        const api = {
            mount: mount,
            initialize: initialize,
            setScene: setScene,
            setSelection: setSelection,
            setSelectionHandler: setSelectionHandler,
            setGhostPlacement: setGhostPlacement,
            worldPointOnFloor: worldPointOnFloor,
            worldToClient: worldToClient,
            fit: fit,
            invalidate: invalidate,
            pick: pick,
            getDiagnostics: getDiagnostics,
            dispose: dispose,
        };
        return api;
    }

    return Object.freeze({
        RESOLUTION_STAGES: RESOLUTION_STAGES,
        createThreeAdapter: createThreeAdapter,
    });
}));
