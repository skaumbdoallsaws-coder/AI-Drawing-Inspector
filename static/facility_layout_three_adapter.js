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
    const CONTEXT_FOCUS_COLOR = 0xf4b740;
    const NORMAL_INSTANCE_COLOR = 0xffffff;
    const DEFAULT_ASSET_COLOR = 0x9aa2a9;
    const DEFAULT_ASSET_ROUGHNESS = 0.7;
    const DEFAULT_ASSET_METALNESS = 0.04;
    const DEFAULT_VISUAL_SETTINGS = Object.freeze({
        ambient: 1.55,
        directional: 2,
        exposure: 1.22,
        contrast: 1.02,
        metalness: DEFAULT_ASSET_METALNESS,
        roughness: DEFAULT_ASSET_ROUGHNESS,
        autoRotate: false,
        wireframe: false,
        background: 'auto',
    });
    const FLOOR_THICKNESS = 0.02;
    const DEFAULT_GRID_SPACING = 1;
    const DEFAULT_MAJOR_GRID_SPACING = 5;
    const DEFAULT_WALKTHROUGH_SETTINGS = Object.freeze({
        eyeHeight: 1.7,
        radius: 0.3,
        walkSpeed: 1.4,
        fastSpeed: 3,
        navigationSpeed: 2.2,
        spawnClearance: 0.6,
    });
    const DEFAULT_DRONE_SETTINGS = Object.freeze({
        radius: 0.35,
        cruiseSpeed: 5,
        boostSpeed: 15,
        slowdownDistance: 3,
        stopDistance: 0.45,
        minimumCeiling: 30,
        ceilingPadding: 10,
        maximumCeiling: 500,
        fieldOfView: 60,
        viewDistance: 60,
        altitudeViewMultiplier: 4,
        maximumViewDistance: 500,
        cullUpdateDistance: 5,
        motionPixelRatio: 0.5,
        assistedFlight: true,
    });
    const DEFAULT_WALKTHROUGH_POSTURES = Object.freeze({
        standing: Object.freeze({
            eyeHeight: 1.7,
            bodyHeight: 1.95,
            radius: 0.3,
            walkSpeed: 1.4,
            fastSpeed: 3.2,
        }),
        crouching: Object.freeze({
            eyeHeight: 1.05,
            bodyHeight: 1.2,
            radius: 0.3,
            walkSpeed: 0.8,
            fastSpeed: 1.2,
        }),
        crawling: Object.freeze({
            eyeHeight: 0.5,
            bodyHeight: 0.65,
            radius: 0.25,
            walkSpeed: 0.35,
            fastSpeed: 0.55,
        }),
    });

    function noop() {}

    function destroyRenderer(renderer) {
        if (!renderer) return;
        if (typeof renderer.setAnimationLoop === 'function') {
            renderer.setAnimationLoop(null);
        }
        if (renderer.renderLists
                && typeof renderer.renderLists.dispose === 'function') {
            renderer.renderLists.dispose();
        }
        if (typeof renderer.dispose === 'function') renderer.dispose();
        if (typeof renderer.forceContextLoss === 'function') {
            renderer.forceContextLoss();
        }
        const canvas = renderer.domElement;
        if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
    }

    function prepareRendererForPool(renderer) {
        if (!renderer) return;
        if (typeof renderer.setAnimationLoop === 'function') {
            renderer.setAnimationLoop(null);
        }
        if (typeof renderer.setRenderTarget === 'function') {
            renderer.setRenderTarget(null);
        }
        if (renderer.renderLists
                && typeof renderer.renderLists.dispose === 'function') {
            renderer.renderLists.dispose();
        }
        if (renderer.info && typeof renderer.info.reset === 'function') {
            renderer.info.reset();
        }
        const canvas = renderer.domElement;
        if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
    }

    function createRendererPool(inputOptions) {
        const poolOptions = inputOptions || {};
        const maximumSize = Math.max(
            1,
            Math.floor(finite(poolOptions.maximumSize, 1))
        );
        const available = [];
        const leased = new Set();
        let disposed = false;
        let createdCount = 0;
        let reusedCount = 0;

        function acquire(factory, context) {
            if (disposed) throw new Error('Facility renderer pool is disposed.');
            if (typeof factory !== 'function') {
                throw new TypeError('Facility renderer factory is required.');
            }
            let renderer = available.pop() || null;
            if (renderer) {
                reusedCount += 1;
            } else {
                if (leased.size >= maximumSize) {
                    throw new Error(
                        'Facility renderer pool capacity is exhausted.'
                    );
                }
                renderer = factory(context || {});
                createdCount += 1;
            }
            if (!renderer || !renderer.domElement) {
                throw new TypeError('Facility renderer factory returned no canvas.');
            }
            leased.add(renderer);
            return renderer;
        }

        function release(renderer, releaseOptions) {
            if (!leased.delete(renderer)) return false;
            const discard = disposed
                || Boolean(releaseOptions && releaseOptions.discard)
                || available.length >= maximumSize;
            if (discard) destroyRenderer(renderer);
            else {
                prepareRendererForPool(renderer);
                available.push(renderer);
            }
            return true;
        }

        function dispose() {
            if (disposed) return false;
            disposed = true;
            available.splice(0).forEach(destroyRenderer);
            return true;
        }

        function getDiagnostics() {
            return {
                disposed: disposed,
                maximumSize: maximumSize,
                availableCount: available.length,
                leasedCount: leased.size,
                createdCount: createdCount,
                reusedCount: reusedCount,
            };
        }

        return Object.freeze({
            acquire: acquire,
            release: release,
            dispose: dispose,
            getDiagnostics: getDiagnostics,
        });
    }

    function finite(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function clamp(value, minimum, maximum, fallback) {
        return Math.max(minimum, Math.min(maximum, finite(value, fallback)));
    }

    function cameraOrientationFromQuaternion(value) {
        const quaternion = value && typeof value === 'object' ? value : null;
        if (!quaternion) return null;
        const x = finite(quaternion.x, 0);
        const y = finite(quaternion.y, 0);
        const z = finite(quaternion.z, 0);
        const w = finite(quaternion.w, 1);

        // Project the camera's screen-right axis onto the facility floor. Its
        // perpendicular is the world direction shown at the top of the view.
        const rightX = 1 - 2 * (y * y + z * z);
        const rightZ = 2 * (x * z - w * y);
        const magnitude = Math.hypot(rightX, rightZ);
        if (magnitude < 1e-8) return null;
        const projectedTopX = -rightZ / magnitude;
        const projectedTopZ = rightX / magnitude;
        const topX = Math.abs(projectedTopX) < 1e-12 ? 0 : projectedTopX;
        const topZ = Math.abs(projectedTopZ) < 1e-12 ? 0 : projectedTopZ;
        const headingDegrees = (
            Math.atan2(topX, topZ) * 180 / Math.PI + 360
        ) % 360;
        return {
            headingDegrees: headingDegrees,
            screenTop: { x: topX, z: topZ },
            northAxis: '+Z',
            eastAxis: '+X',
        };
    }

    function normalizeVisualSettings(value, fallback) {
        const base = Object.assign(
            {},
            DEFAULT_VISUAL_SETTINGS,
            fallback && typeof fallback === 'object' ? fallback : {},
            value && typeof value === 'object' ? value : {}
        );
        const background = typeof base.background === 'string'
            && (/^#[0-9a-f]{6}$/i.test(base.background)
                || base.background === 'auto')
            ? base.background : 'auto';
        return {
            ambient: clamp(base.ambient, 0, 3,
                DEFAULT_VISUAL_SETTINGS.ambient),
            directional: clamp(base.directional, 0, 5,
                DEFAULT_VISUAL_SETTINGS.directional),
            exposure: clamp(base.exposure, 0, 3,
                DEFAULT_VISUAL_SETTINGS.exposure),
            contrast: clamp(base.contrast, 0.5, 1.5,
                DEFAULT_VISUAL_SETTINGS.contrast),
            metalness: clamp(base.metalness, 0, 1,
                DEFAULT_VISUAL_SETTINGS.metalness),
            roughness: clamp(base.roughness, 0, 1,
                DEFAULT_VISUAL_SETTINGS.roughness),
            autoRotate: base.autoRotate === true,
            wireframe: base.wireframe === true,
            background: background,
        };
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
        const defaultPoint = fallback && typeof fallback === 'object'
            ? fallback : { x: 0, y: 0, z: 0 };
        return {
            x: finite(source.x, defaultPoint.x),
            y: finite(source.y, defaultPoint.y),
            z: finite(source.z, defaultPoint.z),
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

    function normalizedPolygon(value) {
        if (!Array.isArray(value)) return [];
        return value.map(function (point) {
            return {
                x: finite(point && point.x, NaN),
                z: finite(point && point.z, NaN),
            };
        }).filter(function (point) {
            return Number.isFinite(point.x) && Number.isFinite(point.z);
        });
    }

    function pointInPolygon(point, polygon) {
        const points = normalizedPolygon(polygon);
        if (!point || points.length < 3) return false;
        const x = finite(point.x, NaN);
        const z = finite(point.z, NaN);
        if (!Number.isFinite(x) || !Number.isFinite(z)) return false;
        let inside = false;
        for (let index = 0, previous = points.length - 1;
                index < points.length; previous = index, index += 1) {
            const currentPoint = points[index];
            const previousPoint = points[previous];
            const crosses = (currentPoint.z > z) !== (previousPoint.z > z)
                && x < (previousPoint.x - currentPoint.x)
                    * (z - currentPoint.z)
                    / ((previousPoint.z - currentPoint.z) || Number.EPSILON)
                    + currentPoint.x;
            if (crosses) inside = !inside;
        }
        return inside;
    }

    function pointSegmentDistanceSquared(point, start, end) {
        const dx = end.x - start.x;
        const dz = end.z - start.z;
        const lengthSquared = dx * dx + dz * dz;
        if (lengthSquared <= Number.EPSILON) {
            const px = point.x - start.x;
            const pz = point.z - start.z;
            return px * px + pz * pz;
        }
        const projection = Math.max(0, Math.min(1,
            ((point.x - start.x) * dx + (point.z - start.z) * dz)
                / lengthSquared));
        const closestX = start.x + projection * dx;
        const closestZ = start.z + projection * dz;
        const px = point.x - closestX;
        const pz = point.z - closestZ;
        return px * px + pz * pz;
    }

    function circleIntersectsPolygon(point, radius, polygon) {
        const points = normalizedPolygon(polygon);
        const safeRadius = Math.max(0, finite(radius, 0));
        if (points.length < 3 || !point) return false;
        if (pointInPolygon(point, points)) return true;
        const radiusSquared = safeRadius * safeRadius;
        for (let index = 0; index < points.length; index += 1) {
            const next = points[(index + 1) % points.length];
            if (pointSegmentDistanceSquared(point, points[index], next)
                    <= radiusSquared) return true;
        }
        return false;
    }

    function validWalkthroughBounds(value) {
        if (!value || !value.minimum || !value.maximum) return null;
        const minimum = {
            x: finite(value.minimum.x, NaN),
            y: finite(value.minimum.y, 0),
            z: finite(value.minimum.z, NaN),
        };
        const maximum = {
            x: finite(value.maximum.x, NaN),
            y: finite(value.maximum.y, minimum.y),
            z: finite(value.maximum.z, NaN),
        };
        if (!Number.isFinite(minimum.x) || !Number.isFinite(minimum.z)
                || !Number.isFinite(maximum.x) || !Number.isFinite(maximum.z)
                || maximum.x <= minimum.x || maximum.z <= minimum.z) {
            return null;
        }
        return { minimum: minimum, maximum: maximum };
    }

    function walkthroughPointValid(point, radius, bounds, obstacles) {
        const area = validWalkthroughBounds(bounds);
        const safeRadius = Math.max(0, finite(radius, 0));
        if (!point || !area) return false;
        const x = finite(point.x, NaN);
        const z = finite(point.z, NaN);
        if (!Number.isFinite(x) || !Number.isFinite(z)
                || x < area.minimum.x + safeRadius
                || x > area.maximum.x - safeRadius
                || z < area.minimum.z + safeRadius
                || z > area.maximum.z - safeRadius) return false;
        return !(Array.isArray(obstacles) ? obstacles : []).some(
            function (polygon) {
                return circleIntersectsPolygon(
                    { x: x, z: z }, safeRadius, polygon
                );
            }
        );
    }

    function resolveWalkthroughMovement(input) {
        const value = input && typeof input === 'object' ? input : {};
        const start = {
            x: finite(value.start && value.start.x, 0),
            z: finite(value.start && value.start.z, 0),
        };
        const delta = {
            x: finite(value.delta && value.delta.x, 0),
            z: finite(value.delta && value.delta.z, 0),
        };
        const radius = Math.max(0.01, finite(value.radius, 0.3));
        const distance = Math.sqrt(delta.x * delta.x + delta.z * delta.z);
        const stepLimit = Math.max(0.02, radius * 0.35);
        const stepCount = Math.max(1, Math.ceil(distance / stepLimit));
        const increment = {
            x: delta.x / stepCount,
            z: delta.z / stepCount,
        };
        const position = { x: start.x, z: start.z };
        let collided = false;
        for (let step = 0; step < stepCount; step += 1) {
            const full = {
                x: position.x + increment.x,
                z: position.z + increment.z,
            };
            if (walkthroughPointValid(
                full, radius, value.bounds, value.obstacles
            )) {
                position.x = full.x;
                position.z = full.z;
                continue;
            }
            collided = true;
            const xOnly = {
                x: position.x + increment.x,
                z: position.z,
            };
            const zOnly = {
                x: position.x,
                z: position.z + increment.z,
            };
            const preferX = Math.abs(increment.x) >= Math.abs(increment.z);
            const candidates = preferX ? [xOnly, zOnly] : [zOnly, xOnly];
            const slide = candidates.find(function (candidate) {
                return walkthroughPointValid(
                    candidate, radius, value.bounds, value.obstacles
                );
            });
            if (slide) {
                position.x = slide.x;
                position.z = slide.z;
            }
        }
        return {
            position: position,
            collided: collided,
            stepCount: stepCount,
        };
    }

    function normalizedDroneVolume(value, index) {
        const source = value && typeof value === 'object' ? value : {};
        if (source._normalizedDroneVolume === true
                && Array.isArray(source.polygon)
                && source.planarBounds) {
            return source;
        }
        const polygon = normalizedPolygon(source.polygon);
        const minimumY = finite(source.minimumY, NaN);
        const maximumY = finite(source.maximumY, NaN);
        if (polygon.length < 3 || !Number.isFinite(minimumY)
                || !Number.isFinite(maximumY) || maximumY <= minimumY) {
            return null;
        }
        const planarBounds = polygon.reduce(function (bounds, point) {
            bounds.minimumX = Math.min(bounds.minimumX, point.x);
            bounds.maximumX = Math.max(bounds.maximumX, point.x);
            bounds.minimumZ = Math.min(bounds.minimumZ, point.z);
            bounds.maximumZ = Math.max(bounds.maximumZ, point.z);
            return bounds;
        }, {
            minimumX: Infinity,
            maximumX: -Infinity,
            minimumZ: Infinity,
            maximumZ: -Infinity,
        });
        return {
            id: String(source.id || source.placementId || ('volume-' + index)),
            placementId: String(source.placementId || source.id || ''),
            polygon: polygon,
            minimumY: minimumY,
            maximumY: maximumY,
            planarBounds: planarBounds,
            _normalizedDroneVolume: true,
        };
    }

    function buildDroneSpatialIndex(volumes, requestedCellSize) {
        const records = (Array.isArray(volumes) ? volumes : []).map(
            normalizedDroneVolume
        ).filter(Boolean);
        const cellSize = Math.max(1, finite(requestedCellSize, 10));
        const cells = new Map();
        const overflow = [];
        records.forEach(function (volume, recordIndex) {
            const bounds = volume.planarBounds;
            const minimumX = Math.floor(bounds.minimumX / cellSize);
            const maximumX = Math.floor(bounds.maximumX / cellSize);
            const minimumZ = Math.floor(bounds.minimumZ / cellSize);
            const maximumZ = Math.floor(bounds.maximumZ / cellSize);
            const cellCount = (maximumX - minimumX + 1)
                * (maximumZ - minimumZ + 1);
            if (cellCount > 1024) {
                overflow.push(recordIndex);
                return;
            }
            for (let cellX = minimumX; cellX <= maximumX; cellX += 1) {
                for (let cellZ = minimumZ; cellZ <= maximumZ; cellZ += 1) {
                    const key = cellX + ':' + cellZ;
                    const entries = cells.get(key) || [];
                    entries.push(recordIndex);
                    cells.set(key, entries);
                }
            }
        });
        return {
            _droneSpatialIndex: true,
            records: records,
            cellSize: cellSize,
            cells: cells,
            overflow: overflow,
        };
    }

    function droneCandidateVolumes(source, point, radius) {
        if (!source || source._droneSpatialIndex !== true) {
            return Array.isArray(source) ? source : [];
        }
        const safeRadius = Math.max(0, finite(radius, 0));
        const cellSize = source.cellSize;
        const minimumX = Math.floor(
            (finite(point && point.x, 0) - safeRadius) / cellSize
        );
        const maximumX = Math.floor(
            (finite(point && point.x, 0) + safeRadius) / cellSize
        );
        const minimumZ = Math.floor(
            (finite(point && point.z, 0) - safeRadius) / cellSize
        );
        const maximumZ = Math.floor(
            (finite(point && point.z, 0) + safeRadius) / cellSize
        );
        const indexes = new Set(source.overflow);
        for (let cellX = minimumX; cellX <= maximumX; cellX += 1) {
            for (let cellZ = minimumZ; cellZ <= maximumZ; cellZ += 1) {
                const entries = source.cells.get(cellX + ':' + cellZ) || [];
                entries.forEach(function (recordIndex) {
                    indexes.add(recordIndex);
                });
            }
        }
        return Array.from(indexes).sort(function (left, right) {
            return left - right;
        }).map(function (recordIndex) {
            return source.records[recordIndex];
        }).filter(Boolean);
    }

    function validDroneBounds(value) {
        const bounds = validWalkthroughBounds(value);
        if (!bounds) return null;
        const minimumY = finite(value.minimum.y, NaN);
        const maximumY = finite(value.maximum.y, NaN);
        if (!Number.isFinite(minimumY) || !Number.isFinite(maximumY)
                || maximumY <= minimumY) return null;
        bounds.minimum.y = minimumY;
        bounds.maximum.y = maximumY;
        return bounds;
    }

    function sphereIntersectsDroneVolume(point, radius, volume) {
        const normalized = normalizedDroneVolume(volume, 0);
        const safeRadius = Math.max(0, finite(radius, 0));
        if (!normalized || !point) return false;
        const y = finite(point.y, NaN);
        if (!Number.isFinite(y)) return false;
        let verticalDistance = 0;
        if (y < normalized.minimumY) {
            verticalDistance = normalized.minimumY - y;
        } else if (y > normalized.maximumY) {
            verticalDistance = y - normalized.maximumY;
        }
        if (verticalDistance > safeRadius) return false;
        const horizontalRadius = Math.sqrt(Math.max(
            0,
            safeRadius * safeRadius - verticalDistance * verticalDistance
        ));
        const planarBounds = normalized.planarBounds;
        if (point.x + horizontalRadius < planarBounds.minimumX
                || point.x - horizontalRadius > planarBounds.maximumX
                || point.z + horizontalRadius < planarBounds.minimumZ
                || point.z - horizontalRadius > planarBounds.maximumZ) {
            return false;
        }
        return circleIntersectsPolygon(
            { x: finite(point.x, NaN), z: finite(point.z, NaN) },
            horizontalRadius,
            normalized.polygon
        );
    }

    function droneCollisionAtPoint(point, radius, bounds, volumes) {
        const area = validDroneBounds(bounds);
        const safeRadius = Math.max(0.01, finite(radius, 0.35));
        if (!point || !area) return { kind: 'bounds', id: null };
        const position = {
            x: finite(point.x, NaN),
            y: finite(point.y, NaN),
            z: finite(point.z, NaN),
        };
        if (!Number.isFinite(position.x) || !Number.isFinite(position.y)
                || !Number.isFinite(position.z)
                || position.x < area.minimum.x + safeRadius
                || position.x > area.maximum.x - safeRadius
                || position.y < area.minimum.y + safeRadius
                || position.y > area.maximum.y - safeRadius
                || position.z < area.minimum.z + safeRadius
                || position.z > area.maximum.z - safeRadius) {
            return { kind: 'bounds', id: null };
        }
        const records = droneCandidateVolumes(
            volumes,
            position,
            safeRadius
        );
        for (let index = 0; index < records.length; index += 1) {
            const volume = normalizedDroneVolume(records[index], index);
            if (volume && sphereIntersectsDroneVolume(
                position,
                safeRadius,
                volume
            )) {
                return {
                    kind: 'obstacle',
                    id: volume.placementId || volume.id,
                };
            }
        }
        return null;
    }

    function dronePointValid(point, radius, bounds, volumes) {
        return !droneCollisionAtPoint(point, radius, bounds, volumes);
    }

    function rayDroneVolumeDistance(origin, direction, volume, maximumDistance) {
        const normalized = normalizedDroneVolume(volume, 0);
        if (!normalized) return null;
        const bounds = normalized.planarBounds;
        const limits = [
            [finite(origin && origin.x, NaN), finite(direction && direction.x, 0),
                bounds.minimumX, bounds.maximumX],
            [finite(origin && origin.y, NaN), finite(direction && direction.y, 0),
                normalized.minimumY, normalized.maximumY],
            [finite(origin && origin.z, NaN), finite(direction && direction.z, 0),
                bounds.minimumZ, bounds.maximumZ],
        ];
        let entry = 0;
        let exit = Math.max(0, finite(maximumDistance, Infinity));
        for (let index = 0; index < limits.length; index += 1) {
            const axis = limits[index];
            if (!Number.isFinite(axis[0])) return null;
            if (Math.abs(axis[1]) <= 1e-9) {
                if (axis[0] < axis[2] || axis[0] > axis[3]) return null;
                continue;
            }
            let near = (axis[2] - axis[0]) / axis[1];
            let far = (axis[3] - axis[0]) / axis[1];
            if (near > far) {
                const temporary = near;
                near = far;
                far = temporary;
            }
            entry = Math.max(entry, near);
            exit = Math.min(exit, far);
            if (entry > exit) return null;
        }
        return entry <= Math.max(0, finite(maximumDistance, Infinity))
            ? entry : null;
    }

    function droneViewDistanceForAltitude(
        altitude,
        baseDistance,
        altitudeMultiplier,
        maximumDistance
    ) {
        const base = Math.max(1, finite(baseDistance, 60));
        const multiplier = Math.max(0, finite(altitudeMultiplier, 4));
        const maximum = Math.max(base, finite(maximumDistance, 500));
        return Math.min(
            maximum,
            base + Math.max(0, finite(altitude, 0)) * multiplier
        );
    }

    function resolveDroneMovement(input) {
        const value = input && typeof input === 'object' ? input : {};
        const start = {
            x: finite(value.start && value.start.x, 0),
            y: finite(value.start && value.start.y, 0),
            z: finite(value.start && value.start.z, 0),
        };
        const delta = {
            x: finite(value.delta && value.delta.x, 0),
            y: finite(value.delta && value.delta.y, 0),
            z: finite(value.delta && value.delta.z, 0),
        };
        const radius = Math.max(0.01, finite(value.radius, 0.35));
        const distance = Math.hypot(delta.x, delta.y, delta.z);
        const stepLimit = Math.max(0.02, radius * 0.35);
        const stepCount = Math.max(1, Math.ceil(distance / stepLimit));
        const increment = {
            x: delta.x / stepCount,
            y: delta.y / stepCount,
            z: delta.z / stepCount,
        };
        const position = { x: start.x, y: start.y, z: start.z };
        const collisionIds = new Set();
        let collided = false;
        for (let step = 0; step < stepCount; step += 1) {
            const full = {
                x: position.x + increment.x,
                y: position.y + increment.y,
                z: position.z + increment.z,
            };
            const fullCollision = droneCollisionAtPoint(
                full,
                radius,
                value.bounds,
                value.volumes
            );
            if (!fullCollision) {
                Object.assign(position, full);
                continue;
            }
            collided = true;
            if (fullCollision.id) collisionIds.add(fullCollision.id);
            // Resolve the unblocked components independently. This preserves
            // tangential movement along a machine, rack, or facility boundary.
            ['x', 'y', 'z'].sort(function (left, right) {
                return Math.abs(increment[right]) - Math.abs(increment[left]);
            }).forEach(function (axis) {
                if (Math.abs(increment[axis]) <= Number.EPSILON) return;
                const candidate = {
                    x: position.x,
                    y: position.y,
                    z: position.z,
                };
                candidate[axis] += increment[axis];
                const collision = droneCollisionAtPoint(
                    candidate,
                    radius,
                    value.bounds,
                    value.volumes
                );
                if (!collision) position[axis] = candidate[axis];
                else if (collision.id) collisionIds.add(collision.id);
            });
        }
        return {
            position: position,
            collided: collided,
            collisionIds: Array.from(collisionIds).sort(),
            stepCount: stepCount,
        };
    }

    function probeDroneClearance(input) {
        const value = input && typeof input === 'object' ? input : {};
        const start = value.start || {};
        const direction = value.direction || {};
        const length = Math.hypot(
            finite(direction.x, 0),
            finite(direction.y, 0),
            finite(direction.z, 0)
        );
        const maximumDistance = Math.max(0, finite(value.maximumDistance, 3));
        if (length <= 1e-9 || maximumDistance <= 0) {
            return { distance: null, obstacleId: null, bounded: false };
        }
        const steps = Math.max(4, Math.floor(finite(value.steps, 12)));
        const unit = {
            x: finite(direction.x, 0) / length,
            y: finite(direction.y, 0) / length,
            z: finite(direction.z, 0) / length,
        };
        for (let index = 1; index <= steps; index += 1) {
            const distance = maximumDistance * index / steps;
            const point = {
                x: finite(start.x, 0) + unit.x * distance,
                y: finite(start.y, 0) + unit.y * distance,
                z: finite(start.z, 0) + unit.z * distance,
            };
            const collision = droneCollisionAtPoint(
                point,
                value.radius,
                value.bounds,
                value.volumes
            );
            if (collision) {
                return {
                    distance: distance,
                    obstacleId: collision.id,
                    bounded: true,
                };
            }
        }
        return {
            distance: maximumDistance,
            obstacleId: null,
            bounded: false,
        };
    }

    function findDroneSpawn(input) {
        const value = input && typeof input === 'object' ? input : {};
        const bounds = validDroneBounds(value.bounds);
        if (!bounds) return null;
        const radius = Math.max(0.01, finite(value.radius, 0.35));
        const desired = value.desired || {};
        const center = {
            x: (bounds.minimum.x + bounds.maximum.x) / 2,
            y: (bounds.minimum.y + bounds.maximum.y) / 2,
            z: (bounds.minimum.z + bounds.maximum.z) / 2,
        };
        const base = {
            x: Math.max(bounds.minimum.x + radius, Math.min(
                bounds.maximum.x - radius,
                finite(desired.x, center.x)
            )),
            y: Math.max(bounds.minimum.y + radius, Math.min(
                bounds.maximum.y - radius,
                finite(desired.y, bounds.minimum.y + 2)
            )),
            z: Math.max(bounds.minimum.z + radius, Math.min(
                bounds.maximum.z - radius,
                finite(desired.z, center.z)
            )),
        };
        const verticalCandidates = [
            base.y,
            bounds.minimum.y + Math.max(radius, 2),
            bounds.minimum.y + Math.max(radius, 5),
            bounds.minimum.y + Math.max(radius, 10),
            bounds.maximum.y - radius,
        ].map(function (valueY) {
            return Math.max(bounds.minimum.y + radius, Math.min(
                bounds.maximum.y - radius,
                valueY
            ));
        });
        const offsets = [
            [0, 0], [1, 0], [-1, 0], [0, 1], [0, -1],
            [2, 0], [-2, 0], [0, 2], [0, -2],
            [4, 0], [-4, 0], [0, 4], [0, -4],
            [8, 0], [-8, 0], [0, 8], [0, -8],
        ];
        for (let yIndex = 0; yIndex < verticalCandidates.length; yIndex += 1) {
            for (let index = 0; index < offsets.length; index += 1) {
                const candidate = {
                    x: Math.max(bounds.minimum.x + radius, Math.min(
                        bounds.maximum.x - radius,
                        base.x + offsets[index][0]
                    )),
                    y: verticalCandidates[yIndex],
                    z: Math.max(bounds.minimum.z + radius, Math.min(
                        bounds.maximum.z - radius,
                        base.z + offsets[index][1]
                    )),
                };
                if (dronePointValid(
                    candidate,
                    radius,
                    bounds,
                    value.volumes
                )) return candidate;
            }
        }
        return null;
    }

    function normalizedWalkSurface(value, index) {
        const surface = value && typeof value === 'object' ? value : {};
        const polygon = normalizedPolygon(surface.polygon);
        const elevation = finite(surface.elevation, NaN);
        if (polygon.length < 3 || !Number.isFinite(elevation)) return null;
        return {
            id: String(surface.id || ('surface-' + index)),
            kind: String(surface.kind || 'surface'),
            elevation: elevation,
            polygon: polygon,
        };
    }

    function walkthroughPostureProfiles(scale, overrides) {
        const factor = Math.max(0.001, finite(scale, 1));
        const supplied = overrides && typeof overrides === 'object' ? overrides : {};
        const result = {};
        Object.keys(DEFAULT_WALKTHROUGH_POSTURES).forEach(function (name) {
            const fallback = DEFAULT_WALKTHROUGH_POSTURES[name];
            const source = supplied[name] && typeof supplied[name] === 'object'
                ? supplied[name] : {};
            const bodyHeight = Math.max(0.1, finite(source.bodyHeight, fallback.bodyHeight));
            const walkSpeed = Math.max(0.05, finite(source.walkSpeed, fallback.walkSpeed));
            result[name] = Object.freeze({
                eyeHeight: Math.min(bodyHeight, Math.max(
                    0.05,
                    finite(source.eyeHeight, fallback.eyeHeight)
                )) * factor,
                bodyHeight: bodyHeight * factor,
                radius: Math.max(0.05, finite(source.radius, fallback.radius)) * factor,
                walkSpeed: walkSpeed * factor,
                fastSpeed: Math.max(
                    walkSpeed,
                    finite(source.fastSpeed, fallback.fastSpeed)
                ) * factor,
            });
        });
        return Object.freeze(result);
    }

    function walkthroughSurfaceAtPoint(input) {
        const value = input && typeof input === 'object' ? input : {};
        const point = {
            x: finite(value.point && value.point.x, NaN),
            z: finite(value.point && value.point.z, NaN),
        };
        const currentElevation = finite(value.currentElevation, NaN);
        const maximumStepUp = Math.max(0, finite(value.maximumStepUp, 0.24));
        const maximumStepDown = Math.max(0, finite(value.maximumStepDown, 0.32));
        if (!Number.isFinite(point.x) || !Number.isFinite(point.z)
                || !Number.isFinite(currentElevation)) return null;
        const candidates = (Array.isArray(value.surfaces) ? value.surfaces : [])
            .map(normalizedWalkSurface)
            .filter(function (surface) {
                return surface
                    && surface.elevation <= currentElevation + maximumStepUp + 1e-6
                    && surface.elevation >= currentElevation - maximumStepDown - 1e-6
                    && pointInPolygon(point, surface.polygon);
            })
            .sort(function (left, right) {
                if (right.elevation !== left.elevation) {
                    return right.elevation - left.elevation;
                }
                return left.id.localeCompare(right.id);
            });
        return candidates.length ? candidates[0] : null;
    }

    function walkthroughVolumeIgnoredAtElevation(
        volume,
        elevation,
        maximumClimbElevation,
        supportClearance
    ) {
        if (!volume || !Array.isArray(volume.polygon)) return true;
        const maximumY = finite(volume.maximumY, Infinity);
        const walkableElevation = finite(volume.walkableElevation, NaN);
        if (String(volume.walkableKind || '').toLowerCase() === 'stair') return true;
        if (Number.isFinite(walkableElevation)
                && walkableElevation <= maximumClimbElevation + supportClearance
                && walkableElevation >= elevation - supportClearance) return true;
        return maximumY <= elevation + supportClearance;
    }

    function walkthroughVerticalClearance(input) {
        const value = input && typeof input === 'object' ? input : {};
        const point = value.point || {};
        const elevation = finite(value.elevation, NaN);
        const radius = Math.max(0, finite(value.radius, 0.3));
        const supportClearance = Math.max(0, finite(value.supportClearance, 0.075));
        const maximumClimbElevation = finite(value.maximumClimbElevation, elevation);
        if (!Number.isFinite(elevation)
                || !Number.isFinite(Number(point.x))
                || !Number.isFinite(Number(point.z))) {
            return { availableHeight: null, obstacleId: null, bounded: false };
        }
        let availableHeight = Infinity;
        let obstacleId = null;
        (Array.isArray(value.obstacleVolumes) ? value.obstacleVolumes : [])
            .forEach(function (volume) {
                if (walkthroughVolumeIgnoredAtElevation(
                    volume,
                    elevation,
                    maximumClimbElevation,
                    supportClearance
                ) || !circleIntersectsPolygon(point, radius, volume.polygon)) return;
                const minimumY = finite(volume.minimumY, -Infinity);
                const clearance = minimumY <= elevation + supportClearance
                    ? 0 : minimumY - elevation;
                if (clearance < availableHeight) {
                    availableHeight = clearance;
                    obstacleId = String(volume.id || volume.sourceId || '') || null;
                }
            });
        return {
            availableHeight: Number.isFinite(availableHeight) ? availableHeight : null,
            obstacleId: obstacleId,
            bounded: Number.isFinite(availableHeight),
        };
    }

    function walkthroughPointValidAtElevation(input) {
        const value = input && typeof input === 'object' ? input : {};
        const point = value.point || {};
        const elevation = finite(value.elevation, NaN);
        const radius = Math.max(0, finite(value.radius, 0.3));
        const bodyHeight = Math.max(radius * 2, finite(value.bodyHeight, 1.95));
        const supportClearance = Math.max(0, finite(value.supportClearance, 0.075));
        const maximumClimbElevation = finite(value.maximumClimbElevation, elevation);
        if (!Number.isFinite(elevation)
                || !walkthroughPointValid(point, radius, value.bounds, [])) return false;
        return !(Array.isArray(value.obstacleVolumes) ? value.obstacleVolumes : [])
            .some(function (volume) {
                if (walkthroughVolumeIgnoredAtElevation(
                    volume,
                    elevation,
                    maximumClimbElevation,
                    supportClearance
                )) return false;
                const minimumY = finite(volume.minimumY, -Infinity);
                if (minimumY >= elevation + bodyHeight) return false;
                return circleIntersectsPolygon(point, radius, volume.polygon);
            });
    }

    function resolveWalkthroughPostureChange(input) {
        const value = input && typeof input === 'object' ? input : {};
        const posture = String(value.posture || '').toLowerCase();
        const profiles = value.postures && typeof value.postures === 'object'
            ? value.postures : walkthroughPostureProfiles(value.scale);
        const profile = profiles[posture];
        if (!profile) {
            return {
                ok: false,
                posture: posture,
                reason: 'unknown_posture',
                availableHeight: null,
                requiredHeight: null,
            };
        }
        const point = value.point || {};
        const elevation = finite(value.elevation, NaN);
        const maximumClimbElevation = finite(value.maximumClimbElevation, elevation);
        const clearance = walkthroughVerticalClearance({
            point: point,
            elevation: elevation,
            radius: profile.radius,
            supportClearance: value.supportClearance,
            maximumClimbElevation: maximumClimbElevation,
            obstacleVolumes: value.obstacleVolumes,
        });
        const insideBounds = Number.isFinite(elevation)
            && walkthroughPointValid(point, profile.radius, value.bounds, []);
        const valid = insideBounds && walkthroughPointValidAtElevation({
            point: point,
            elevation: elevation,
            radius: profile.radius,
            bodyHeight: profile.bodyHeight,
            supportClearance: value.supportClearance,
            maximumClimbElevation: maximumClimbElevation,
            bounds: value.bounds,
            obstacleVolumes: value.obstacleVolumes,
        });
        let reason = 'clear';
        if (!insideBounds) reason = 'outside_bounds';
        else if (!valid && clearance.bounded
                && clearance.availableHeight > Math.max(0, finite(value.supportClearance, 0.075))) {
            reason = 'insufficient_clearance';
        } else if (!valid) reason = 'collision';
        return {
            ok: valid,
            posture: posture,
            reason: reason,
            availableHeight: clearance.availableHeight,
            requiredHeight: profile.bodyHeight,
            obstacleId: clearance.obstacleId,
            profile: profile,
        };
    }

    function resolveMultiLevelWalkthroughMovement(input) {
        const value = input && typeof input === 'object' ? input : {};
        const radius = Math.max(0.01, finite(value.radius, 0.3));
        const maximumStepUp = Math.max(0, finite(value.maximumStepUp, 0.24));
        const maximumStepDown = Math.max(0, finite(value.maximumStepDown, 0.32));
        const start = {
            x: finite(value.start && value.start.x, 0),
            z: finite(value.start && value.start.z, 0),
            elevation: finite(
                value.start && (value.start.elevation !== undefined
                    ? value.start.elevation : value.start.y),
                0
            ),
        };
        const delta = {
            x: finite(value.delta && value.delta.x, 0),
            z: finite(value.delta && value.delta.z, 0),
        };
        const distance = Math.sqrt(delta.x * delta.x + delta.z * delta.z);
        const stepLimit = Math.max(0.02, Math.min(radius * 0.35, maximumStepUp * 0.55 || radius * 0.35));
        const stepCount = Math.max(1, Math.ceil(distance / stepLimit));
        const increment = { x: delta.x / stepCount, z: delta.z / stepCount };
        const position = { x: start.x, z: start.z };
        let elevation = start.elevation;
        let surface = walkthroughSurfaceAtPoint({
            point: position,
            currentElevation: elevation,
            maximumStepUp: maximumStepUp,
            maximumStepDown: maximumStepDown,
            surfaces: value.surfaces,
        });
        if (surface) elevation = surface.elevation;
        let collided = false;
        let changedLevel = false;

        function evaluate(candidate) {
            const nextSurface = walkthroughSurfaceAtPoint({
                point: candidate,
                currentElevation: elevation,
                maximumStepUp: maximumStepUp,
                maximumStepDown: maximumStepDown,
                surfaces: value.surfaces,
            });
            if (!nextSurface) return null;
            if (!walkthroughPointValidAtElevation({
                point: candidate,
                elevation: nextSurface.elevation,
                radius: radius,
                bodyHeight: value.bodyHeight,
                supportClearance: value.supportClearance,
                maximumClimbElevation: Math.max(elevation, nextSurface.elevation)
                    + maximumStepUp,
                bounds: value.bounds,
                obstacleVolumes: value.obstacleVolumes,
            })) return null;
            return nextSurface;
        }

        for (let step = 0; step < stepCount; step += 1) {
            const full = { x: position.x + increment.x, z: position.z + increment.z };
            let nextSurface = evaluate(full);
            let candidate = full;
            if (!nextSurface) {
                collided = true;
                const xOnly = { x: position.x + increment.x, z: position.z };
                const zOnly = { x: position.x, z: position.z + increment.z };
                const preferX = Math.abs(increment.x) >= Math.abs(increment.z);
                const alternatives = preferX ? [xOnly, zOnly] : [zOnly, xOnly];
                candidate = null;
                for (let index = 0; index < alternatives.length; index += 1) {
                    nextSurface = evaluate(alternatives[index]);
                    if (nextSurface) {
                        candidate = alternatives[index];
                        break;
                    }
                }
                if (!candidate) continue;
            }
            if (Math.abs(nextSurface.elevation - elevation) > 1e-6) changedLevel = true;
            position.x = candidate.x;
            position.z = candidate.z;
            elevation = nextSurface.elevation;
            surface = nextSurface;
        }
        return {
            position: position,
            elevation: elevation,
            surfaceId: surface ? surface.id : null,
            surfaceKind: surface ? surface.kind : null,
            collided: collided,
            changedLevel: changedLevel,
            stepCount: stepCount,
        };
    }

    function findWalkthroughSpawn(input) {
        const value = input && typeof input === 'object' ? input : {};
        const bounds = validWalkthroughBounds(value.bounds);
        const radius = Math.max(0.01, finite(value.radius, 0.3));
        if (!bounds) return null;
        const desired = value.desired || {
            x: (bounds.minimum.x + bounds.maximum.x) / 2,
            z: (bounds.minimum.z + bounds.maximum.z) / 2,
        };
        const clamped = {
            x: Math.max(bounds.minimum.x + radius, Math.min(
                bounds.maximum.x - radius, finite(desired.x, 0)
            )),
            z: Math.max(bounds.minimum.z + radius, Math.min(
                bounds.maximum.z - radius, finite(desired.z, 0)
            )),
        };
        if (walkthroughPointValid(
            clamped, radius, bounds, value.obstacles
        )) return clamped;
        const spacing = Math.max(radius * 2, 0.5);
        const maxSpan = Math.max(
            bounds.maximum.x - bounds.minimum.x,
            bounds.maximum.z - bounds.minimum.z
        );
        const maximumRing = Math.max(1, Math.ceil(maxSpan / spacing));
        for (let ring = 1; ring <= maximumRing; ring += 1) {
            for (let row = -ring; row <= ring; row += 1) {
                for (let column = -ring; column <= ring; column += 1) {
                    if (Math.max(Math.abs(column), Math.abs(row)) !== ring) {
                        continue;
                    }
                    const candidate = {
                        x: clamped.x + column * spacing,
                        z: clamped.z + row * spacing,
                    };
                    if (walkthroughPointValid(
                        candidate, radius, bounds, value.obstacles
                    )) return candidate;
                }
            }
        }
        return null;
    }

    function walkthroughSegmentValid(start, end, input) {
        const value = input && typeof input === 'object' ? input : {};
        const radius = Math.max(0.01, finite(value.radius, 0.3));
        const dx = finite(end && end.x, 0) - finite(start && start.x, 0);
        const dz = finite(end && end.z, 0) - finite(start && start.z, 0);
        const distance = Math.sqrt(dx * dx + dz * dz);
        const sampleSpacing = Math.max(
            0.05,
            Math.min(radius * 0.5, finite(value.sampleSpacing, 0.2))
        );
        const samples = Math.max(1, Math.ceil(distance / sampleSpacing));
        for (let index = 0; index <= samples; index += 1) {
            const ratio = index / samples;
            if (!walkthroughPointValid({
                x: finite(start && start.x, 0) + dx * ratio,
                z: finite(start && start.z, 0) + dz * ratio,
            }, radius, value.bounds, value.obstacles)) return false;
        }
        return true;
    }

    function routeDistance(points) {
        let total = 0;
        for (let index = 1; index < points.length; index += 1) {
            const dx = points[index].x - points[index - 1].x;
            const dz = points[index].z - points[index - 1].z;
            total += Math.sqrt(dx * dx + dz * dz);
        }
        return total;
    }

    function smoothWalkthroughRoute(points, input) {
        const source = Array.isArray(points) ? points : [];
        if (source.length <= 2) return source.map(function (point) {
            return { x: point.x, z: point.z };
        });
        const output = [{ x: source[0].x, z: source[0].z }];
        let anchor = 0;
        while (anchor < source.length - 1) {
            let next = source.length - 1;
            while (next > anchor + 1 && !walkthroughSegmentValid(
                source[anchor], source[next], input
            )) next -= 1;
            output.push({ x: source[next].x, z: source[next].z });
            anchor = next;
        }
        return output;
    }

    function planWalkthroughRoute(input) {
        const value = input && typeof input === 'object' ? input : {};
        const bounds = validWalkthroughBounds(value.bounds);
        const radius = Math.max(0.01, finite(value.radius, 0.3));
        const spacing = clamp(value.gridSpacing, 0.2, 2, 0.5);
        const obstacles = Array.isArray(value.obstacles) ? value.obstacles : [];
        const start = {
            x: finite(value.start && value.start.x, NaN),
            z: finite(value.start && value.start.z, NaN),
        };
        const goal = {
            x: finite(value.goal && value.goal.x, NaN),
            z: finite(value.goal && value.goal.z, NaN),
        };
        if (!bounds || !Number.isFinite(start.x) || !Number.isFinite(start.z)
                || !Number.isFinite(goal.x) || !Number.isFinite(goal.z)) {
            return { ok: false, reason: 'invalid_input', points: [] };
        }
        if (!walkthroughPointValid(start, radius, bounds, obstacles)) {
            return { ok: false, reason: 'invalid_start', points: [] };
        }
        if (!walkthroughPointValid(goal, radius, bounds, obstacles)) {
            return { ok: false, reason: 'invalid_goal', points: [] };
        }
        const segmentInput = {
            radius: radius,
            bounds: bounds,
            obstacles: obstacles,
            sampleSpacing: spacing * 0.4,
        };
        if (walkthroughSegmentValid(start, goal, segmentInput)) {
            const direct = [start, goal];
            return {
                ok: true,
                reason: 'direct',
                points: direct,
                rawPointCount: direct.length,
                visitedNodeCount: 0,
                distance: routeDistance(direct),
                gridSpacing: spacing,
            };
        }

        const minimumX = bounds.minimum.x + radius;
        const minimumZ = bounds.minimum.z + radius;
        const maximumX = bounds.maximum.x - radius;
        const maximumZ = bounds.maximum.z - radius;
        const columnCount = Math.max(
            1,
            Math.floor((maximumX - minimumX) / spacing) + 1
        );
        const rowCount = Math.max(
            1,
            Math.floor((maximumZ - minimumZ) / spacing) + 1
        );
        const maximumNodes = Math.max(
            100,
            Math.floor(finite(value.maximumNodes, 20000))
        );
        if (columnCount * rowCount > maximumNodes) {
            return { ok: false, reason: 'grid_too_large', points: [] };
        }
        const cellCache = new Map();
        const keyFor = function (column, row) {
            return column + ':' + row;
        };
        const pointFor = function (column, row) {
            return {
                x: minimumX + column * spacing,
                z: minimumZ + row * spacing,
            };
        };
        const validCell = function (column, row) {
            if (column < 0 || row < 0
                    || column >= columnCount || row >= rowCount) return false;
            const key = keyFor(column, row);
            if (!cellCache.has(key)) {
                cellCache.set(key, walkthroughPointValid(
                    pointFor(column, row), radius, bounds, obstacles
                ));
            }
            return cellCache.get(key);
        };
        const nearestCell = function (point) {
            const initialColumn = Math.max(0, Math.min(
                columnCount - 1,
                Math.round((point.x - minimumX) / spacing)
            ));
            const initialRow = Math.max(0, Math.min(
                rowCount - 1,
                Math.round((point.z - minimumZ) / spacing)
            ));
            const maximumRing = Math.max(columnCount, rowCount);
            for (let ring = 0; ring <= maximumRing; ring += 1) {
                const candidates = [];
                for (let row = initialRow - ring;
                        row <= initialRow + ring; row += 1) {
                    for (let column = initialColumn - ring;
                            column <= initialColumn + ring; column += 1) {
                        if (Math.max(
                            Math.abs(column - initialColumn),
                            Math.abs(row - initialRow)
                        ) !== ring || !validCell(column, row)) continue;
                        const candidatePoint = pointFor(column, row);
                        const dx = candidatePoint.x - point.x;
                        const dz = candidatePoint.z - point.z;
                        candidates.push({
                            column: column,
                            row: row,
                            distance: dx * dx + dz * dz,
                        });
                    }
                }
                candidates.sort(function (left, right) {
                    return left.distance - right.distance
                        || left.row - right.row
                        || left.column - right.column;
                });
                if (candidates.length) return candidates[0];
            }
            return null;
        };
        const startCell = nearestCell(start);
        const goalCell = nearestCell(goal);
        if (!startCell || !goalCell) {
            return { ok: false, reason: 'no_walkable_cells', points: [] };
        }
        const goalKey = keyFor(goalCell.column, goalCell.row);
        const heuristic = function (column, row) {
            const dx = Math.abs(goalCell.column - column);
            const dz = Math.abs(goalCell.row - row);
            return Math.max(dx, dz) + (Math.SQRT2 - 1) * Math.min(dx, dz);
        };
        const startKey = keyFor(startCell.column, startCell.row);
        const records = new Map();
        const open = [];
        const closed = new Set();
        const startRecord = {
            key: startKey,
            column: startCell.column,
            row: startCell.row,
            g: 0,
            h: heuristic(startCell.column, startCell.row),
            parent: null,
        };
        startRecord.f = startRecord.g + startRecord.h;
        records.set(startKey, startRecord);
        open.push(startRecord);
        const directions = [
            [1, 0], [0, 1], [-1, 0], [0, -1],
            [1, 1], [-1, 1], [-1, -1], [1, -1],
        ];
        let visitedNodeCount = 0;
        while (open.length && visitedNodeCount < maximumNodes) {
            open.sort(function (left, right) {
                return left.f - right.f || left.h - right.h
                    || left.row - right.row || left.column - right.column;
            });
            const current = open.shift();
            if (closed.has(current.key)) continue;
            closed.add(current.key);
            visitedNodeCount += 1;
            if (current.key === goalKey) break;
            directions.forEach(function (direction) {
                const column = current.column + direction[0];
                const row = current.row + direction[1];
                if (!validCell(column, row)) return;
                const diagonal = direction[0] !== 0 && direction[1] !== 0;
                if (diagonal && (!validCell(current.column + direction[0], current.row)
                        || !validCell(current.column, current.row + direction[1]))) {
                    return;
                }
                const key = keyFor(column, row);
                if (closed.has(key)) return;
                const candidateG = current.g + (diagonal ? Math.SQRT2 : 1);
                const existing = records.get(key);
                if (existing && candidateG >= existing.g - 1e-9) return;
                const record = existing || {
                    key: key,
                    column: column,
                    row: row,
                };
                record.g = candidateG;
                record.h = heuristic(column, row);
                record.f = record.g + record.h;
                record.parent = current.key;
                records.set(key, record);
                open.push(record);
            });
        }
        if (!closed.has(goalKey)) {
            return { ok: false, reason: 'no_path', points: [] };
        }
        const gridPoints = [];
        let cursor = goalKey;
        while (cursor) {
            const record = records.get(cursor);
            if (!record) break;
            gridPoints.push(pointFor(record.column, record.row));
            cursor = record.parent;
        }
        gridPoints.reverse();
        const rawPoints = [start].concat(gridPoints, [goal]).filter(
            function (point, index, source) {
                if (!index) return true;
                return Math.abs(point.x - source[index - 1].x) > 1e-9
                    || Math.abs(point.z - source[index - 1].z) > 1e-9;
            }
        );
        const points = smoothWalkthroughRoute(rawPoints, segmentInput);
        return {
            ok: true,
            reason: 'routed',
            points: points,
            rawPointCount: rawPoints.length,
            visitedNodeCount: visitedNodeCount,
            distance: routeDistance(points),
            gridSpacing: spacing,
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
        const PointerLockControls = options.PointerLockControls
            || (THREE && THREE.PointerLockControls)
            || (root && root.PointerLockControls);
        const GLTFLoader = options.GLTFLoader
            || (THREE && THREE.GLTFLoader)
            || (root && root.GLTFLoader);
        const assetResolver = options.assetResolver || null;
        const placementFootprintResolver = options.placementFootprint || null;
        const documentObject = options.document || (root && root.document);
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
        const preserveAssetColors = options.preserveAssetColors === true;
        const requestedAssetColor = Number(options.neutralAssetColor);
        const neutralAssetColor = Number.isFinite(requestedAssetColor)
            ? Math.max(0, Math.min(0xffffff, Math.floor(requestedAssetColor)))
            : DEFAULT_ASSET_COLOR;
        const navigationSettings = {
            zoomToCursor: options.zoomToCursor !== false,
            zoomSpeed: clamp(options.zoomSpeed, 0.1, 4, 1.8),
            panSpeed: clamp(options.panSpeed, 0.1, 4, 1.25),
            rotateSpeed: clamp(options.rotateSpeed, 0.1, 4, 1),
            interactivePixelRatio: clamp(
                options.interactivePixelRatio,
                0.5,
                2,
                1
            ),
            restoreDelayMs: clamp(
                options.navigationResolutionRestoreDelayMs,
                0,
                500,
                140
            ),
        };
        const largeLayoutDetailThreshold = Math.max(
            1,
            Math.floor(finite(options.largeLayoutDetailThreshold, 250))
        );
        const preferOverviewForLargeLayouts =
            options.preferOverviewForLargeLayouts !== false;
        const largeLayoutHeavyVisualBytes = Math.max(
            1,
            Math.floor(finite(
                options.largeLayoutHeavyVisualBytes,
                8 * 1024 * 1024
            ))
        );
        const deferredVisualPixelThreshold = clamp(
            options.deferredVisualPixelThreshold,
            8,
            400,
            48
        );
        const deferredLoadsPerInteraction = Math.max(
            1,
            Math.floor(finite(options.deferredLoadsPerInteraction, 1))
        );
        const walkthroughSettings = {
            eyeHeight: clamp(
                options.walkthroughEyeHeight,
                1,
                2.5,
                DEFAULT_WALKTHROUGH_SETTINGS.eyeHeight
            ),
            radius: clamp(
                options.walkthroughRadius,
                0.15,
                0.8,
                DEFAULT_WALKTHROUGH_SETTINGS.radius
            ),
            walkSpeed: clamp(
                options.walkthroughSpeed,
                0.2,
                8,
                DEFAULT_WALKTHROUGH_SETTINGS.walkSpeed
            ),
            fastSpeed: clamp(
                options.walkthroughFastSpeed,
                0.5,
                15,
                DEFAULT_WALKTHROUGH_SETTINGS.fastSpeed
            ),
            navigationSpeed: clamp(
                options.walkthroughNavigationSpeed,
                0.2,
                8,
                DEFAULT_WALKTHROUGH_SETTINGS.navigationSpeed
            ),
            spawnClearance: clamp(
                options.walkthroughSpawnClearance,
                0.1,
                3,
                DEFAULT_WALKTHROUGH_SETTINGS.spawnClearance
            ),
            contextRadius: clamp(
                options.walkthroughContextRadius,
                1,
                12,
                5
            ),
        };
        const droneSettings = {
            radius: clamp(
                options.droneRadius,
                0.15,
                2,
                DEFAULT_DRONE_SETTINGS.radius
            ),
            cruiseSpeed: clamp(
                options.droneCruiseSpeed,
                0.5,
                40,
                DEFAULT_DRONE_SETTINGS.cruiseSpeed
            ),
            boostSpeed: clamp(
                options.droneBoostSpeed,
                1,
                100,
                DEFAULT_DRONE_SETTINGS.boostSpeed
            ),
            slowdownDistance: clamp(
                options.droneSlowdownDistance,
                0.5,
                15,
                DEFAULT_DRONE_SETTINGS.slowdownDistance
            ),
            stopDistance: clamp(
                options.droneStopDistance,
                0.05,
                3,
                DEFAULT_DRONE_SETTINGS.stopDistance
            ),
            minimumCeiling: clamp(
                options.droneMinimumCeiling,
                5,
                200,
                DEFAULT_DRONE_SETTINGS.minimumCeiling
            ),
            ceilingPadding: clamp(
                options.droneCeilingPadding,
                1,
                100,
                DEFAULT_DRONE_SETTINGS.ceilingPadding
            ),
            maximumCeiling: clamp(
                options.droneMaximumCeiling,
                20,
                2000,
                DEFAULT_DRONE_SETTINGS.maximumCeiling
            ),
            fieldOfView: clamp(
                options.droneFieldOfView,
                50,
                85,
                DEFAULT_DRONE_SETTINGS.fieldOfView
            ),
            viewDistance: clamp(
                options.droneViewDistance,
                30,
                500,
                DEFAULT_DRONE_SETTINGS.viewDistance
            ),
            altitudeViewMultiplier: clamp(
                options.droneAltitudeViewMultiplier,
                0,
                12,
                DEFAULT_DRONE_SETTINGS.altitudeViewMultiplier
            ),
            maximumViewDistance: clamp(
                options.droneMaximumViewDistance,
                60,
                2000,
                DEFAULT_DRONE_SETTINGS.maximumViewDistance
            ),
            cullUpdateDistance: clamp(
                options.droneCullUpdateDistance,
                1,
                25,
                DEFAULT_DRONE_SETTINGS.cullUpdateDistance
            ),
            motionPixelRatio: clamp(
                options.droneMotionPixelRatio,
                0.5,
                1,
                DEFAULT_DRONE_SETTINGS.motionPixelRatio
            ),
            assistedFlight: options.droneAssistedFlight !== false,
            contextRadius: clamp(
                options.droneContextRadius,
                2,
                50,
                15
            ),
        };

        const state = {
            host: null,
            mounted: false,
            suspended: false,
            disposed: false,
            degraded: false,
            contextLost: false,
            status: 'unmounted',
            statusReason: null,
            renderer: null,
            rendererFromPool: false,
            scene: null,
            ambientLight: null,
            directionalLight: null,
            environmentRoot: null,
            floorObject: null,
            gridObjects: [],
            axisObjects: [],
            environmentSignature: null,
            environmentDiagnostics: null,
            ownsBackground: false,
            themeCleanup: null,
            modelRoot: null,
            floorMarkingObjects: [],
            routeObjects: [],
            camera: null,
            controls: null,
            walkthroughControls: null,
            raycaster: null,
            canvas: null,
            resizeObserver: null,
            resizeObserverActive: false,
            resizeHandler: null,
            contextLostHandler: null,
            contextRestoredHandler: null,
            controlChangeHandler: null,
            controlStartHandler: null,
            controlEndHandler: null,
            walkthroughChangeHandler: null,
            walkthroughLockHandler: null,
            walkthroughUnlockHandler: null,
            walkthroughErrorHandler: null,
            walkthroughKeyDownHandler: null,
            walkthroughKeyUpHandler: null,
            walkthroughBlurHandler: null,
            walkthroughVisibilityHandler: null,
            pointerHandler: null,
            selectionHandler: null,
            walkthroughStateHandler: null,
            droneStateHandler: null,
            walkthroughContextHandler: null,
            cameraOrientationHandler: null,
            lastCameraOrientation: null,
            walkthroughContextFocus: null,
            frameId: null,
            needsRender: false,
            mountGeneration: 0,
            sceneGeneration: 0,
            abortController: null,
            currentInput: null,
            ghostInput: null,
            ghostObject: null,
            proposalInput: null,
            proposalRoot: null,
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
            displayPixelRatio: 1,
            interactivePixelRatio: 1,
            currentPixelRatio: 1,
            navigationInteracting: false,
            navigationRestoreTimer: null,
            deferredLoadQueue: Promise.resolve(),
            mountCount: 0,
            teardownCount: 0,
            listenerCount: 0,
            lastFit: null,
            worldBounds: null,
            reloadOnResume: false,
            navigationMode: 'orbit',
            gridVisible: options.showGrid !== false,
            visualSettings: normalizeVisualSettings(options.visualSettings),
            walkthrough: {
                active: false,
                locked: false,
                exiting: false,
                previousCamera: null,
                keys: new Set(),
                lastFrameTime: null,
                obstaclePolygons: [],
                bounds: null,
                floorY: 0,
                spawn: null,
                targetPlacementId: null,
                collisionCount: 0,
                lastReason: null,
                route: {
                    active: false,
                    points: [],
                    pointIndex: 0,
                    distance: 0,
                    targetPlacementId: null,
                    destination: null,
                    reason: null,
                },
            },
            drone: {
                active: false,
                locked: false,
                exiting: false,
                previousCamera: null,
                keys: new Set(),
                lastFrameTime: null,
                obstacleVolumes: [],
                obstacleIndex: null,
                bounds: null,
                floorY: 0,
                spawn: null,
                collisionCount: 0,
                lastReason: null,
                currentSpeed: 0,
                altitude: 0,
                nearestObstacleDistance: null,
                nearestObstacleId: null,
                visiblePlacementCount: 0,
                lastVisualCullPosition: null,
                lastVisualViewDistance: null,
                assistedFlight: droneSettings.assistedFlight,
                lastNotificationTime: null,
            },
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
            if (state.walkthrough.active) {
                exitWalkthrough(reason || 'renderer_degraded');
            }
            if (state.drone.active) {
                exitDrone(reason || 'renderer_degraded');
            }
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
            if (!state.mounted || state.suspended
                    || !state.renderer || !state.camera || !state.host) {
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
            if (!state.mounted || state.suspended || state.degraded
                || !state.renderer || !state.scene || !state.camera) {
                return false;
            }
            try {
                updateWalkthroughContextFocus();
                notifyCameraOrientation(false);
                state.renderer.render(state.scene, state.camera);
                state.renderedFrames += 1;
                return true;
            } catch (error) {
                reportError('render_failed', error);
                enterDegraded('render_failed', false);
                return false;
            }
        }

        function cameraOrientationSnapshot() {
            return state.camera
                ? cameraOrientationFromQuaternion(state.camera.quaternion)
                : null;
        }

        function orientationDelta(left, right) {
            const difference = Math.abs(
                finite(left, 0) - finite(right, 0)
            ) % 360;
            return Math.min(difference, 360 - difference);
        }

        function notifyCameraOrientation(force) {
            const value = cameraOrientationSnapshot();
            if (!value) return null;
            const previous = state.lastCameraOrientation;
            state.lastCameraOrientation = value;
            if (!force && previous && orientationDelta(
                previous.headingDegrees,
                value.headingDegrees
            ) < 0.05) return value;
            if (typeof state.cameraOrientationHandler === 'function') {
                state.cameraOrientationHandler(value, api);
            }
            if (typeof options.onCameraOrientationChange === 'function') {
                options.onCameraOrientationChange(value, api);
            }
            return value;
        }

        function setCameraOrientationHandler(handler) {
            state.cameraOrientationHandler = typeof handler === 'function'
                ? handler : null;
            if (state.cameraOrientationHandler) {
                notifyCameraOrientation(true);
            }
            return Boolean(state.cameraOrientationHandler);
        }

        function onAnimationFrame(timestamp, generation) {
            state.frameId = null;
            if (!state.mounted || state.suspended
                    || generation !== state.mountGeneration) return;
            const walking = updateWalkthrough(timestamp);
            const flying = updateDrone(timestamp);
            const rotating = !immersiveActive()
                && state.visualSettings.autoRotate
                && state.controls
                && typeof state.controls.update === 'function';
            if (rotating) {
                state.controls.autoRotate = true;
                state.controls.update();
                state.needsRender = true;
            }
            if (walking || flying) state.needsRender = true;
            if (!state.needsRender) return;
            state.needsRender = false;
            renderNow();
            if ((rotating || walking || flying) && requestFrame
                    && state.frameId === null) {
                state.frameId = requestFrame(function (nextTimestamp) {
                    onAnimationFrame(nextTimestamp, generation);
                });
            }
        }

        function invalidate() {
            state.renderRequests += 1;
            if (!state.mounted || state.suspended
                    || state.degraded || !state.renderer) return false;
            state.needsRender = true;
            if (state.frameId !== null) return true;
            if (!requestFrame) {
                state.needsRender = false;
                return renderNow();
            }
            const generation = state.mountGeneration;
            state.frameId = requestFrame(function (timestamp) {
                onAnimationFrame(timestamp, generation);
            });
            return true;
        }

        function setRendererPixelRatio(value) {
            if (!state.renderer
                    || typeof state.renderer.setPixelRatio !== 'function') {
                return false;
            }
            const ratio = clamp(value, 0.5, 2, 1);
            if (Math.abs(state.currentPixelRatio - ratio) < 0.001) {
                return false;
            }
            state.renderer.setPixelRatio(ratio);
            state.currentPixelRatio = ratio;
            return true;
        }

        function beginNavigationInteraction() {
            const timerHost = options.window || root;
            if (state.navigationRestoreTimer !== null
                    && timerHost
                    && typeof timerHost.clearTimeout === 'function') {
                timerHost.clearTimeout(state.navigationRestoreTimer);
                state.navigationRestoreTimer = null;
            }
            state.navigationInteracting = true;
            setRendererPixelRatio(state.interactivePixelRatio);
            invalidate();
        }

        function beginDroneInteraction() {
            beginNavigationInteraction();
            setRendererPixelRatio(Math.min(
                state.displayPixelRatio,
                droneSettings.motionPixelRatio
            ));
        }

        function endNavigationInteraction() {
            const restore = function () {
                state.navigationRestoreTimer = null;
                if (state.drone.active && droneHasMovement()) {
                    state.navigationInteracting = true;
                    setRendererPixelRatio(Math.min(
                        state.displayPixelRatio,
                        droneSettings.motionPixelRatio
                    ));
                    return;
                }
                state.navigationInteracting = false;
                setRendererPixelRatio(state.displayPixelRatio);
                invalidate();
                loadDeferredVisibleGroups();
            };
            const timerHost = options.window || root;
            if (navigationSettings.restoreDelayMs > 0
                    && timerHost
                    && typeof timerHost.setTimeout === 'function') {
                state.navigationRestoreTimer = timerHost.setTimeout(
                    restore,
                    navigationSettings.restoreDelayMs
                );
                return;
            }
            restore();
        }

        function makeSceneGraph() {
            state.scene = new THREE.Scene();
            const RootType = THREE.Group || THREE.Object3D;
            applySceneBackground();
            state.environmentRoot = new RootType();
            state.environmentRoot.name = 'InspectorProFacilityEnvironmentRoot';
            state.scene.add(state.environmentRoot);
            state.modelRoot = new RootType();
            state.modelRoot.name = 'InspectorProFacilityModelRoot';
            state.scene.add(state.modelRoot);
            state.camera = options.camera || new THREE.PerspectiveCamera(
                finite(options.fov, 45),
                1,
                0.01,
                10000
            );
            if (state.camera.position && typeof state.camera.position.set === 'function') {
                state.camera.position.set(8, 8, 8);
            }
            if (typeof THREE.HemisphereLight === 'function') {
                state.ambientLight = new THREE.HemisphereLight(
                    0xffffff,
                    0x334155,
                    state.visualSettings.ambient
                );
                state.scene.add(state.ambientLight);
            }
            if (typeof THREE.DirectionalLight === 'function') {
                state.directionalLight = new THREE.DirectionalLight(
                    0xffffff,
                    state.visualSettings.directional
                );
                if (state.directionalLight.position
                        && typeof state.directionalLight.position.set
                            === 'function') {
                    state.directionalLight.position.set(8, 16, 10);
                }
                state.scene.add(state.directionalLight);
            }
            syncEnvironment();
            applyVisualSettingsRuntime();
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
                if (state.currentInput) {
                    Promise.resolve(setScene(state.currentInput)).catch(
                        function () {
                            enterDegraded('webgl_restore_failed', false);
                        }
                    );
                    return;
                }
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
                if (state.drone.active) return;
                if (state.walkthrough.active) {
                    if (state.walkthrough.locked
                            && (!event || event.button === undefined
                                || event.button === 0)) {
                        const floorPoint = worldPointOnFloor(
                            { normalized: true, x: 0, y: 0 },
                            state.walkthrough.floorY
                        );
                        if (floorPoint) {
                            navigateWalkthroughToPoint(floorPoint);
                        } else {
                            state.walkthrough.route.reason =
                                'floor_target_unavailable';
                            notifyWalkthroughState();
                        }
                    }
                    return;
                }
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
                state.controls.zoomToCursor = navigationSettings.zoomToCursor;
                state.controls.zoomSpeed = navigationSettings.zoomSpeed;
                state.controls.panSpeed = navigationSettings.panSpeed;
                state.controls.rotateSpeed = navigationSettings.rotateSpeed;
                state.controls.screenSpacePanning = true;
                state.controls.enableDamping = false;
                setNavigationMode(state.navigationMode);
                state.controlChangeHandler = invalidate;
                state.controlStartHandler = beginNavigationInteraction;
                state.controlEndHandler = endNavigationInteraction;
                addListener(state.controls, 'change', state.controlChangeHandler);
                addListener(state.controls, 'start', state.controlStartHandler);
                addListener(state.controls, 'end', state.controlEndHandler);
            }

            if (typeof PointerLockControls === 'function') {
                state.walkthroughControls = new PointerLockControls(
                    state.camera,
                    state.canvas
                );
                state.walkthroughControls.enabled = false;
                state.walkthroughChangeHandler = function () {
                    if (state.drone.active) {
                        beginDroneInteraction();
                        endNavigationInteraction();
                    }
                    invalidate();
                };
                state.walkthroughLockHandler = function () {
                    const walkthroughActive = state.walkthrough.active;
                    const droneActive = state.drone.active;
                    if (!walkthroughActive && !droneActive) return;
                    if (walkthroughActive) {
                        state.walkthrough.locked = true;
                        state.walkthrough.lastReason = 'active';
                    }
                    if (droneActive) {
                        state.drone.locked = true;
                        state.drone.lastReason = 'active';
                    }
                    const enableMouseLook = function () {
                        if (immersiveActive()
                                && (state.walkthrough.locked
                                    || state.drone.locked)
                                && state.walkthroughControls) {
                            state.walkthroughControls.enabled = true;
                        }
                    };
                    state.walkthroughControls.enabled = false;
                    if (root && typeof root.setTimeout === 'function') {
                        root.setTimeout(enableMouseLook, 0);
                    } else {
                        enableMouseLook();
                    }
                    if (walkthroughActive) notifyWalkthroughState();
                    if (droneActive) notifyDroneState(true);
                    invalidate();
                };
                state.walkthroughUnlockHandler = function () {
                    if (state.walkthrough.active
                            && !state.walkthrough.exiting) {
                        exitWalkthrough('pointer_lock_released', true);
                    } else if (state.drone.active
                            && !state.drone.exiting) {
                        exitDrone('pointer_lock_released', true);
                    }
                };
                state.walkthroughErrorHandler = function () {
                    if (state.walkthrough.active) {
                        exitWalkthrough('pointer_lock_failed', true);
                    } else if (state.drone.active) {
                        exitDrone('pointer_lock_failed', true);
                    }
                };
                addListener(
                    state.walkthroughControls,
                    'change',
                    state.walkthroughChangeHandler
                );
                addListener(
                    state.walkthroughControls,
                    'lock',
                    state.walkthroughLockHandler
                );
                addListener(
                    state.walkthroughControls,
                    'unlock',
                    state.walkthroughUnlockHandler
                );
                addListener(
                    state.walkthroughControls,
                    'error',
                    state.walkthroughErrorHandler
                );
                state.walkthroughKeyDownHandler = function (event) {
                    if (state.drone.active) handleDroneKey(event, true);
                    else handleWalkthroughKey(event, true);
                };
                state.walkthroughKeyUpHandler = function (event) {
                    if (state.drone.active) handleDroneKey(event, false);
                    else handleWalkthroughKey(event, false);
                };
                state.walkthroughVisibilityHandler = function () {
                    if (documentObject && documentObject.hidden) {
                        if (state.walkthrough.active) {
                            exitWalkthrough('document_hidden');
                        } else if (state.drone.active) {
                            exitDrone('document_hidden');
                        }
                    }
                };
                state.walkthroughBlurHandler = function () {
                    if (state.walkthrough.active) {
                        state.walkthrough.keys.clear();
                        state.walkthrough.lastFrameTime = null;
                    } else if (state.drone.active) {
                        state.drone.keys.clear();
                        state.drone.lastFrameTime = null;
                        state.drone.currentSpeed = 0;
                    }
                };
                addListener(
                    documentObject,
                    'keydown',
                    state.walkthroughKeyDownHandler,
                    false
                );
                addListener(
                    documentObject,
                    'keyup',
                    state.walkthroughKeyUpHandler,
                    false
                );
                addListener(
                    documentObject,
                    'visibilitychange',
                    state.walkthroughVisibilityHandler,
                    false
                );
                addListener(
                    options.window || root,
                    'blur',
                    state.walkthroughBlurHandler,
                    false
                );
            }

            observeResize();
        }

        function observeResize() {
            if (state.suspended || state.resizeObserverActive
                    || typeof ResizeObserverType !== 'function') return;
            state.resizeHandler = resize;
            if (!state.resizeObserver) {
                state.resizeObserver = new ResizeObserverType(
                    state.resizeHandler
                );
            }
            state.resizeObserver.observe(state.host);
            state.resizeObserverActive = true;
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

        function createNeutralAssetMaterial(sourceMaterial) {
            const MaterialType = THREE.MeshStandardMaterial
                || THREE.MeshBasicMaterial;
            if (typeof MaterialType !== 'function') return sourceMaterial;
            const materialOptions = {
                color: neutralAssetColor,
                transparent: false,
                opacity: 1,
                depthWrite: true,
                depthTest: true,
                roughness: DEFAULT_ASSET_ROUGHNESS,
                metalness: DEFAULT_ASSET_METALNESS,
            };
            if (sourceMaterial && sourceMaterial.side !== undefined) {
                materialOptions.side = sourceMaterial.side;
            }
            if (sourceMaterial && sourceMaterial.flatShading !== undefined) {
                materialOptions.flatShading = Boolean(
                    sourceMaterial.flatShading
                );
            }
            const material = new MaterialType(materialOptions);
            material.name = sourceMaterial && sourceMaterial.name
                ? sourceMaterial.name + ':FacilityNeutral'
                : 'FacilityNeutralAsset';
            material.userData = Object.assign(
                {},
                sourceMaterial && sourceMaterial.userData,
                { facilityNeutralAssetMaterial: true }
            );
            if (material.color
                    && typeof material.color.setHex === 'function') {
                material.color.setHex(neutralAssetColor);
            }
            if (material.emissive
                    && typeof material.emissive.setHex === 'function') {
                material.emissive.setHex(0x000000);
            }
            if ('emissiveIntensity' in material) {
                material.emissiveIntensity = 0;
            }
            if ('vertexColors' in material) material.vertexColors = false;
            material.needsUpdate = true;
            return material;
        }

        function applyAssetMaterialPolicy(object) {
            if (!object) return object;
            object.userData = object.userData || {};
            object.userData.facilityAssetMaterialMode = preserveAssetColors
                ? 'source' : 'neutral';
            if (preserveAssetColors) return object;

            const replacements = new Map();
            const originals = new Set();
            const replacementFor = function (material) {
                if (!material) return material;
                if (!replacements.has(material)) {
                    replacements.set(
                        material,
                        createNeutralAssetMaterial(material)
                    );
                    originals.add(material);
                }
                return replacements.get(material);
            };
            const visit = function (candidate) {
                if (!candidate || !candidate.isMesh || !candidate.material) {
                    return;
                }
                candidate.material = Array.isArray(candidate.material)
                    ? candidate.material.map(replacementFor)
                    : replacementFor(candidate.material);
            };
            if (typeof object.traverse === 'function') object.traverse(visit);
            else visit(object);

            const seenMaterials = new Set();
            const seenTextures = new Set();
            originals.forEach(function (material) {
                if (replacements.get(material) !== material) {
                    disposeMaterial(material, seenMaterials, seenTextures);
                }
            });
            return object;
        }

        function applyVisualSettingsToObject(object) {
            if (!object) return false;
            const visit = function (candidate) {
                if (!candidate || !candidate.isMesh || !candidate.material) {
                    return;
                }
                const materials = Array.isArray(candidate.material)
                    ? candidate.material : [candidate.material];
                materials.filter(Boolean).forEach(function (material) {
                    if ('metalness' in material) {
                        material.metalness = state.visualSettings.metalness;
                    }
                    if ('roughness' in material) {
                        material.roughness = state.visualSettings.roughness;
                    }
                    material.wireframe = state.visualSettings.wireframe;
                    material.needsUpdate = true;
                });
            };
            if (typeof object.traverse === 'function') object.traverse(visit);
            else visit(object);
            return true;
        }

        function applyCanvasVisualSettings() {
            if (!state.canvas || !state.canvas.style) return;
            state.canvas.style.filter = 'contrast('
                + state.visualSettings.contrast.toFixed(2) + ')';
        }

        function applyVisualSettingsRuntime() {
            if (state.ambientLight) {
                state.ambientLight.intensity = state.visualSettings.ambient;
            }
            if (state.directionalLight) {
                state.directionalLight.intensity =
                    state.visualSettings.directional;
            }
            if (state.renderer) {
                state.renderer.toneMappingExposure =
                    state.visualSettings.exposure;
            }
            if (state.controls) {
                state.controls.autoRotate = !immersiveActive()
                    && state.visualSettings.autoRotate;
                state.controls.autoRotateSpeed = 1.2;
            }
            applyCanvasVisualSettings();
            applyVisualSettingsToObject(state.modelRoot);
            return true;
        }

        function setVisualSettings(value) {
            state.visualSettings = normalizeVisualSettings(
                value,
                state.visualSettings
            );
            if (state.scene) applySceneBackground();
            applyVisualSettingsRuntime();
            invalidate();
            return Object.assign({}, state.visualSettings);
        }

        function getVisualSettings() {
            return Object.assign({}, state.visualSettings);
        }

        function isLightTheme() {
            if (options.theme === 'light') return true;
            if (options.theme === 'dark') return false;
            const documentObject = options.document || (root && root.document);
            return Boolean(
                documentObject
                && documentObject.documentElement
                && typeof documentObject.documentElement.getAttribute
                    === 'function'
                && documentObject.documentElement.getAttribute('data-theme')
                    === 'light'
            );
        }

        function disposeSceneBackground() {
            if (state.ownsBackground && state.scene && state.scene.background
                    && typeof state.scene.background.dispose === 'function') {
                state.scene.background.dispose();
            }
            state.ownsBackground = false;
        }

        function applySceneBackground() {
            if (!state.scene) return false;
            disposeSceneBackground();
            let background = null;
            if (state.visualSettings.background !== 'auto'
                    && typeof THREE.Color === 'function') {
                background = new THREE.Color(state.visualSettings.background);
            } else if (typeof options.backgroundFactory === 'function') {
                try {
                    background = options.backgroundFactory({
                        THREE: THREE,
                        theme: isLightTheme() ? 'light' : 'dark',
                    });
                } catch (error) {
                    reportError('background_creation_failed', error);
                }
            }
            if (!background && typeof THREE.Color === 'function') {
                background = new THREE.Color(
                    isLightTheme() ? 0xdfe6eb : 0x252e39
                );
            }
            state.scene.background = background;
            state.ownsBackground = Boolean(
                background && typeof background.dispose === 'function'
            );
            return Boolean(background);
        }

        function attachThemeListener() {
            if (typeof state.themeCleanup === 'function') {
                state.themeCleanup();
            }
            state.themeCleanup = null;
            if (typeof options.subscribeThemeChange !== 'function') return;
            const cleanup = options.subscribeThemeChange(function () {
                if (!state.mounted || !state.scene) return;
                applySceneBackground();
                state.environmentSignature = null;
                syncEnvironment();
                invalidate();
            });
            state.themeCleanup = typeof cleanup === 'function'
                ? cleanup : null;
        }

        function configuredEnvironmentBounds() {
            const configured = options.worldBounds;
            if (configured
                    && Number.isFinite(Number(configured.minX))
                    && Number.isFinite(Number(configured.minZ))
                    && Number.isFinite(Number(configured.maxX))
                    && Number.isFinite(Number(configured.maxZ))
                    && Number(configured.maxX) > Number(configured.minX)
                    && Number(configured.maxZ) > Number(configured.minZ)) {
                return {
                    minimum: {
                        x: Number(configured.minX),
                        y: Number.isFinite(Number(configured.floorY))
                            ? Number(configured.floorY) : 0,
                        z: Number(configured.minZ),
                    },
                    maximum: {
                        x: Number(configured.maxX),
                        y: Number.isFinite(Number(configured.floorY))
                            ? Number(configured.floorY) : 0,
                        z: Number(configured.maxZ),
                    },
                };
            }
            if (!state.worldBounds) return null;
            return {
                minimum: {
                    x: finite(state.worldBounds.minimum.x, 0),
                    y: finite(state.worldBounds.minimum.y, 0),
                    z: finite(state.worldBounds.minimum.z, 0),
                },
                maximum: {
                    x: finite(state.worldBounds.maximum.x, 0),
                    y: finite(state.worldBounds.minimum.y, 0),
                    z: finite(state.worldBounds.maximum.z, 0),
                },
            };
        }

        function getWalkthroughState() {
            const walkthrough = state.walkthrough;
            return {
                supported: typeof PointerLockControls === 'function',
                active: walkthrough.active,
                locked: walkthrough.locked,
                eyeHeight: walkthroughSettings.eyeHeight,
                radius: walkthroughSettings.radius,
                walkSpeed: walkthroughSettings.walkSpeed,
                fastSpeed: walkthroughSettings.fastSpeed,
                navigationSpeed: walkthroughSettings.navigationSpeed,
                obstacleCount: walkthrough.obstaclePolygons.length,
                collisionCount: walkthrough.collisionCount,
                movementKeys: Array.from(walkthrough.keys).sort(),
                targetPlacementId: walkthrough.targetPlacementId,
                spawn: walkthrough.spawn
                    ? Object.assign({}, walkthrough.spawn) : null,
                reason: walkthrough.lastReason,
                route: {
                    active: walkthrough.route.active,
                    pointCount: walkthrough.route.points.length,
                    pointIndex: walkthrough.route.pointIndex,
                    remainingPointCount: Math.max(
                        0,
                        walkthrough.route.points.length
                            - walkthrough.route.pointIndex
                    ),
                    distance: walkthrough.route.distance,
                    targetPlacementId:
                        walkthrough.route.targetPlacementId,
                    destination: walkthrough.route.destination
                        ? Object.assign({}, walkthrough.route.destination)
                        : null,
                    reason: walkthrough.route.reason,
                },
            };
        }

        function notifyWalkthroughState() {
            const value = getWalkthroughState();
            if (typeof state.walkthroughStateHandler === 'function') {
                state.walkthroughStateHandler(value, api);
            }
            if (typeof options.onWalkthroughStateChange === 'function') {
                options.onWalkthroughStateChange(value, api);
            }
            return value;
        }

        function setWalkthroughStateHandler(handler) {
            state.walkthroughStateHandler = typeof handler === 'function'
                ? handler : null;
            if (state.walkthroughStateHandler) notifyWalkthroughState();
            return Boolean(state.walkthroughStateHandler);
        }

        function immersiveActive() {
            return state.walkthrough.active || state.drone.active;
        }

        function getDroneState() {
            const drone = state.drone;
            return {
                supported: typeof PointerLockControls === 'function',
                active: drone.active,
                locked: drone.locked,
                radius: droneSettings.radius,
                cruiseSpeed: droneSettings.cruiseSpeed,
                boostSpeed: droneSettings.boostSpeed,
                fieldOfView: droneSettings.fieldOfView,
                viewDistance: droneSettings.viewDistance,
                effectiveViewDistance: droneEffectiveViewDistance(
                    state.camera && state.camera.position
                ),
                assistedFlight: drone.assistedFlight,
                obstacleCount: drone.obstacleVolumes.length,
                broadPhaseCellCount: drone.obstacleIndex
                    ? drone.obstacleIndex.cells.size : 0,
                visiblePlacementCount: drone.visiblePlacementCount,
                collisionCount: drone.collisionCount,
                movementKeys: Array.from(drone.keys).sort(),
                spawn: drone.spawn ? Object.assign({}, drone.spawn) : null,
                reason: drone.lastReason,
                currentSpeed: drone.currentSpeed,
                altitude: drone.altitude,
                nearestObstacleDistance: drone.nearestObstacleDistance,
                nearestObstacleId: drone.nearestObstacleId,
                bounds: drone.bounds ? {
                    minimum: Object.assign({}, drone.bounds.minimum),
                    maximum: Object.assign({}, drone.bounds.maximum),
                } : null,
            };
        }

        function notifyDroneState(force) {
            const drone = state.drone;
            const now = Date.now();
            if (!force && drone.lastNotificationTime !== null
                    && now - drone.lastNotificationTime < 100) {
                return getDroneState();
            }
            drone.lastNotificationTime = now;
            const value = getDroneState();
            if (typeof state.droneStateHandler === 'function') {
                state.droneStateHandler(value, api);
            }
            if (typeof options.onDroneStateChange === 'function') {
                options.onDroneStateChange(value, api);
            }
            return value;
        }

        function setDroneStateHandler(handler) {
            state.droneStateHandler = typeof handler === 'function'
                ? handler : null;
            if (state.droneStateHandler) notifyDroneState(true);
            return Boolean(state.droneStateHandler);
        }

        function fallbackPlacementPolygon(placement) {
            const bounds = transformedBounds(
                boundsForPlacement(placement), placement
            );
            return [
                { x: bounds.minimum.x, z: bounds.minimum.z },
                { x: bounds.maximum.x, z: bounds.minimum.z },
                { x: bounds.maximum.x, z: bounds.maximum.z },
                { x: bounds.minimum.x, z: bounds.maximum.z },
            ];
        }

        function footprintForPlacement(placement) {
            if (typeof placementFootprintResolver === 'function') {
                try {
                    const source = placement.source || placement;
                    const resolved = placementFootprintResolver(source, {
                        assetCatalog: state.currentInput
                            ? state.currentInput.assetCatalog : [],
                    });
                    const polygon = normalizedPolygon(resolved);
                    if (polygon.length >= 3) return polygon;
                } catch (error) {
                    reportError('walkthrough_footprint_failed', error);
                }
            }
            return fallbackPlacementPolygon(placement);
        }

        function buildWalkthroughObstacles() {
            return state.placements.map(function (placement) {
                return {
                    placementId: placement.placementId,
                    polygon: footprintForPlacement(placement),
                };
            }).filter(function (record) {
                return record.polygon.length >= 3;
            }).sort(function (left, right) {
                return left.placementId.localeCompare(right.placementId);
            });
        }

        function buildDroneObstacleVolumes() {
            return state.placements.map(function (placement) {
                const bounds = transformedBounds(
                    boundsForPlacement(placement),
                    placement
                );
                return normalizedDroneVolume({
                    id: placement.placementId,
                    placementId: placement.placementId,
                    polygon: footprintForPlacement(placement),
                    minimumY: bounds.minimum.y,
                    maximumY: bounds.maximum.y,
                }, 0);
            }).filter(Boolean).sort(function (left, right) {
                return left.placementId.localeCompare(right.placementId);
            });
        }

        function configuredDroneBounds(volumes) {
            const floorBounds = validWalkthroughBounds(
                configuredEnvironmentBounds() || state.worldBounds
            );
            if (!floorBounds) return null;
            const floorY = finite(floorBounds.minimum.y, 0);
            const highest = (Array.isArray(volumes) ? volumes : []).reduce(
                function (maximum, volume) {
                    return Math.max(maximum, finite(volume.maximumY, floorY));
                },
                floorY
            );
            const requestedMaximum = finite(options.droneMaximumAltitude, NaN);
            const ceiling = Number.isFinite(requestedMaximum)
                ? Math.max(floorY + droneSettings.radius * 2, requestedMaximum)
                : Math.min(
                    floorY + droneSettings.maximumCeiling,
                    Math.max(
                        floorY + droneSettings.minimumCeiling,
                        highest + droneSettings.ceilingPadding
                    )
                );
            return validDroneBounds({
                minimum: {
                    x: floorBounds.minimum.x,
                    y: floorY,
                    z: floorBounds.minimum.z,
                },
                maximum: {
                    x: floorBounds.maximum.x,
                    y: ceiling,
                    z: floorBounds.maximum.z,
                },
            });
        }

        function polygonBounds(polygon) {
            const points = normalizedPolygon(polygon);
            if (!points.length) return null;
            return points.reduce(function (bounds, point) {
                bounds.minimum.x = Math.min(bounds.minimum.x, point.x);
                bounds.minimum.z = Math.min(bounds.minimum.z, point.z);
                bounds.maximum.x = Math.max(bounds.maximum.x, point.x);
                bounds.maximum.z = Math.max(bounds.maximum.z, point.z);
                return bounds;
            }, {
                minimum: { x: Infinity, z: Infinity },
                maximum: { x: -Infinity, z: -Infinity },
            });
        }

        function walkthroughSpawnRequest(input, obstacles) {
            const value = input && typeof input === 'object' ? input : {};
            const selected = Array.from(state.selectedIds).sort();
            const placementId = stringValue(
                value.placementId,
                value.ignoreSelection !== true && selected.length === 1
                    ? selected[0] : ''
            );
            const target = placementId
                ? obstacles.find(function (record) {
                    return record.placementId === placementId;
                }) : null;
            if (value.worldPoint
                    && Number.isFinite(Number(value.worldPoint.x))
                    && Number.isFinite(Number(value.worldPoint.z))) {
                return {
                    desired: {
                        x: Number(value.worldPoint.x),
                        z: Number(value.worldPoint.z),
                    },
                    target: target,
                };
            }
            if (target) {
                const bounds = polygonBounds(target.polygon);
                const center = {
                    x: (bounds.minimum.x + bounds.maximum.x) / 2,
                    z: (bounds.minimum.z + bounds.maximum.z) / 2,
                };
                const targetSpan = Math.max(
                    bounds.maximum.x - bounds.minimum.x,
                    bounds.maximum.z - bounds.minimum.z
                );
                // Imported visuals may carry a source-to-canonical translation
                // beyond their authoritative planning footprint. Start far enough
                // away to frame the selected asset without changing collision or
                // placement semantics.
                const viewingOffset = Math.min(
                    8,
                    Math.max(1.5, targetSpan * 0.65)
                );
                const clearance = walkthroughSettings.radius
                    + walkthroughSettings.spawnClearance
                    + viewingOffset;
                const candidates = [
                    { x: bounds.minimum.x - clearance, z: center.z },
                    { x: bounds.maximum.x + clearance, z: center.z },
                    { x: center.x, z: bounds.minimum.z - clearance },
                    { x: center.x, z: bounds.maximum.z + clearance },
                ];
                const camera = state.camera && state.camera.position || center;
                candidates.sort(function (left, right) {
                    const leftDistance = (left.x - finite(camera.x, 0)) ** 2
                        + (left.z - finite(camera.z, 0)) ** 2;
                    const rightDistance = (right.x - finite(camera.x, 0)) ** 2
                        + (right.z - finite(camera.z, 0)) ** 2;
                    return leftDistance - rightDistance
                        || left.x - right.x || left.z - right.z;
                });
                return { desired: candidates[0], target: target };
            }
            const camera = state.camera && state.camera.position;
            return {
                desired: camera ? {
                    x: finite(camera.x, 0),
                    z: finite(camera.z, 0),
                } : null,
                target: null,
            };
        }

        function cameraSnapshot() {
            const camera = state.camera || {};
            return {
                position: copyPoint(
                    camera.position,
                    { x: 8, y: 8, z: 8 }
                ),
                quaternion: copyQuaternion(camera.quaternion),
                up: copyPoint(camera.up, { x: 0, y: 1, z: 0 }),
                near: finite(camera.near, 0.01),
                far: finite(camera.far, 10000),
                fov: finite(camera.fov, NaN),
                target: state.controls && state.controls.target
                    ? copyPoint(state.controls.target, { x: 0, y: 0, z: 0 })
                    : null,
                navigationMode: state.navigationMode,
            };
        }

        function setQuaternion(target, value) {
            if (!target || !value) return;
            if (typeof target.set === 'function') {
                target.set(value.x, value.y, value.z, value.w);
                return;
            }
            target.x = value.x;
            target.y = value.y;
            target.z = value.z;
            target.w = value.w;
        }

        function restoreWalkthroughCamera(snapshot) {
            if (!snapshot || !state.camera) return;
            setVector(state.camera.position, snapshot.position);
            setQuaternion(state.camera.quaternion, snapshot.quaternion);
            setVector(state.camera.up, snapshot.up);
            state.camera.near = snapshot.near;
            state.camera.far = snapshot.far;
            if (Number.isFinite(snapshot.fov)
                    && Number.isFinite(Number(state.camera.fov))) {
                state.camera.fov = snapshot.fov;
            }
            state.navigationMode = snapshot.navigationMode || 'orbit';
            if (state.controls) {
                state.controls.enabled = true;
                if (snapshot.target && state.controls.target) {
                    setVector(state.controls.target, snapshot.target);
                }
                setNavigationMode(state.navigationMode);
                state.controls.autoRotate = state.visualSettings.autoRotate;
                if (typeof state.controls.update === 'function') {
                    state.controls.update();
                }
            }
            if (typeof state.camera.updateProjectionMatrix === 'function') {
                state.camera.updateProjectionMatrix();
            }
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld(true);
            }
        }

        function getCameraView() {
            if (!state.camera) return null;
            return cameraSnapshot();
        }

        function applyCameraView(value) {
            const view = value && typeof value === 'object' ? value : null;
            const position = view && view.position;
            const quaternion = view && view.quaternion;
            if (!view || !position || !quaternion
                    || ![position.x, position.y, position.z,
                        quaternion.x, quaternion.y, quaternion.z, quaternion.w]
                        .every(function (item) {
                            return Number.isFinite(Number(item));
                        })) return false;
            if (state.walkthrough.active) {
                exitWalkthrough('camera_view_applied');
            }
            if (state.drone.active) {
                exitDrone('camera_view_applied');
            }
            setVector(state.camera.position, position);
            setQuaternion(state.camera.quaternion, quaternion);
            if (view.up) setVector(state.camera.up, view.up);
            if (Number.isFinite(Number(view.near))) {
                state.camera.near = Number(view.near);
            }
            if (Number.isFinite(Number(view.far))) {
                state.camera.far = Number(view.far);
            }
            if (Number.isFinite(Number(view.fov))
                    && Number.isFinite(Number(state.camera.fov))) {
                state.camera.fov = clamp(Number(view.fov), 1, 179, 45);
            }
            state.navigationMode = view.navigationMode === 'pan'
                ? 'pan' : 'orbit';
            if (state.controls) {
                state.controls.enabled = true;
                state.controls.autoRotate = false;
                if (view.target && state.controls.target) {
                    setVector(state.controls.target, view.target);
                }
                setNavigationMode(state.navigationMode);
                if (typeof state.controls.update === 'function') {
                    state.controls.update();
                }
            }
            state.visualSettings.autoRotate = false;
            if (typeof state.camera.updateProjectionMatrix === 'function') {
                state.camera.updateProjectionMatrix();
            }
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld(true);
            }
            invalidate();
            return true;
        }

        function exitWalkthrough(reason, skipUnlock) {
            const walkthrough = state.walkthrough;
            if (!walkthrough.active && !walkthrough.exiting) return false;
            const snapshot = walkthrough.previousCamera;
            walkthrough.exiting = true;
            walkthrough.active = false;
            walkthrough.locked = false;
            walkthrough.keys.clear();
            walkthrough.lastFrameTime = null;
            walkthrough.lastReason = reason || 'exited';
            if (state.walkthroughControls) {
                state.walkthroughControls.enabled = false;
                if (!skipUnlock && state.walkthroughControls.isLocked
                        && typeof state.walkthroughControls.unlock === 'function') {
                    try { state.walkthroughControls.unlock(); } catch (error) {
                        reportError('walkthrough_unlock_failed', error);
                    }
                }
            }
            restoreWalkthroughCamera(snapshot);
            walkthrough.previousCamera = null;
            walkthrough.obstaclePolygons = [];
            walkthrough.bounds = null;
            walkthrough.spawn = null;
            walkthrough.targetPlacementId = null;
            walkthrough.route.active = false;
            walkthrough.route.points = [];
            walkthrough.route.pointIndex = 0;
            walkthrough.route.distance = 0;
            walkthrough.route.targetPlacementId = null;
            walkthrough.route.destination = null;
            walkthrough.route.reason = reason || 'exited';
            walkthrough.exiting = false;
            setWalkthroughContextFocus(null);
            applySelection();
            notifyWalkthroughState();
            invalidate();
            return true;
        }

        function deactivateWalkthroughForHandoff(reason) {
            const walkthrough = state.walkthrough;
            const overviewCamera = walkthrough.previousCamera;
            walkthrough.exiting = true;
            walkthrough.active = false;
            walkthrough.locked = false;
            walkthrough.keys.clear();
            walkthrough.lastFrameTime = null;
            walkthrough.lastReason = reason || 'handoff';
            walkthrough.previousCamera = null;
            walkthrough.obstaclePolygons = [];
            walkthrough.bounds = null;
            walkthrough.spawn = null;
            walkthrough.targetPlacementId = null;
            walkthrough.route.active = false;
            walkthrough.route.points = [];
            walkthrough.route.pointIndex = 0;
            walkthrough.route.distance = 0;
            walkthrough.route.targetPlacementId = null;
            walkthrough.route.destination = null;
            walkthrough.route.reason = walkthrough.lastReason;
            walkthrough.exiting = false;
            return overviewCamera;
        }

        function enterWalkthrough(input) {
            const walkthrough = state.walkthrough;
            if (state.drone.active) {
                return switchImmersiveMode('walkthrough');
            }
            const entry = input && typeof input === 'object' ? input : {};
            const handoff = entry.immersiveHandoff
                && typeof entry.immersiveHandoff === 'object'
                ? entry.immersiveHandoff : null;
            if (walkthrough.active) {
                if (!walkthrough.locked && state.walkthroughControls
                        && typeof state.walkthroughControls.lock === 'function') {
                    try { state.walkthroughControls.lock(false); } catch (error) {
                        reportError('walkthrough_lock_failed', error);
                    }
                }
                return getWalkthroughState();
            }
            if (typeof PointerLockControls !== 'function'
                    || !state.walkthroughControls || !state.camera
                    || !state.canvas || state.degraded || state.suspended) {
                walkthrough.lastReason = 'walkthrough_unavailable';
                warning(
                    'walkthrough_unavailable',
                    'Walkthrough controls are unavailable in this 3D runtime.'
                );
                return notifyWalkthroughState();
            }
            const bounds = validWalkthroughBounds(
                configuredEnvironmentBounds() || state.worldBounds
            );
            if (!bounds) {
                walkthrough.lastReason = 'facility_bounds_unavailable';
                warning(
                    'walkthrough_bounds_unavailable',
                    'A valid facility floor is required for walkthrough mode.'
                );
                return notifyWalkthroughState();
            }
            const records = buildWalkthroughObstacles();
            const request = walkthroughSpawnRequest(input, records);
            const polygons = records.map(function (record) {
                return record.polygon;
            });
            const spawn = findWalkthroughSpawn({
                desired: request.desired,
                radius: walkthroughSettings.radius,
                bounds: bounds,
                obstacles: polygons,
            });
            if (!spawn) {
                walkthrough.lastReason = 'no_valid_spawn';
                warning(
                    'walkthrough_no_valid_spawn',
                    'No collision-free walkthrough starting point was found.'
                );
                return notifyWalkthroughState();
            }
            const floorY = finite(bounds.minimum.y, 0);
            walkthrough.previousCamera = handoff && handoff.overviewCamera
                ? handoff.overviewCamera : cameraSnapshot();
            walkthrough.active = true;
            walkthrough.locked = false;
            walkthrough.keys.clear();
            walkthrough.lastFrameTime = null;
            walkthrough.obstaclePolygons = polygons;
            walkthrough.bounds = bounds;
            walkthrough.floorY = floorY;
            walkthrough.spawn = { x: spawn.x, y: floorY, z: spawn.z };
            walkthrough.targetPlacementId = request.target
                ? request.target.placementId : null;
            walkthrough.collisionCount = 0;
            walkthrough.lastReason = 'entering';
            applySelection();
            if (state.controls) {
                state.controls.autoRotate = false;
                state.controls.enabled = false;
            }
            // Pointer lock can emit a synthetic first mouse delta. Mouse-look
            // is armed by the lock handler on the next task to ignore it.
            state.walkthroughControls.enabled = false;
            setVector(state.camera.position, {
                x: spawn.x,
                y: floorY + walkthroughSettings.eyeHeight,
                z: spawn.z,
            });
            if (state.camera.up) setVector(state.camera.up, { x: 0, y: 1, z: 0 });
            if (handoff && handoff.camera) {
                setQuaternion(state.camera.quaternion, handoff.camera.quaternion);
                const overview = handoff.overviewCamera;
                if (overview) {
                    state.camera.near = overview.near;
                    state.camera.far = overview.far;
                    if (Number.isFinite(overview.fov)
                            && Number.isFinite(Number(state.camera.fov))) {
                        state.camera.fov = overview.fov;
                    }
                    if (typeof state.camera.updateProjectionMatrix
                            === 'function') {
                        state.camera.updateProjectionMatrix();
                    }
                }
                walkthrough.lastReason = 'handoff_from_drone';
            } else if (request.target && typeof state.camera.lookAt === 'function') {
                const targetBounds = polygonBounds(request.target.polygon);
                state.camera.lookAt(
                    (targetBounds.minimum.x + targetBounds.maximum.x) / 2,
                    floorY + walkthroughSettings.eyeHeight * 0.65,
                    (targetBounds.minimum.z + targetBounds.maximum.z) / 2
                );
            } else if (typeof state.camera.lookAt === 'function') {
                const previousTarget = walkthrough.previousCamera.target;
                let direction = previousTarget ? {
                    x: previousTarget.x - walkthrough.previousCamera.position.x,
                    z: previousTarget.z - walkthrough.previousCamera.position.z,
                } : { x: 0, z: -1 };
                const length = Math.sqrt(
                    direction.x * direction.x + direction.z * direction.z
                ) || 1;
                direction = {
                    x: direction.x / length,
                    z: direction.z / length,
                };
                state.camera.lookAt(
                    spawn.x + direction.x,
                    floorY + walkthroughSettings.eyeHeight,
                    spawn.z + direction.z
                );
            }
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld(true);
            }
            const reusePointerLock = Boolean(
                handoff && handoff.pointerLocked
                && state.walkthroughControls.isLocked
            );
            if (reusePointerLock) {
                walkthrough.locked = true;
                state.walkthroughControls.enabled = true;
            }
            notifyWalkthroughState();
            invalidate();
            if (!reusePointerLock) {
                try {
                    state.walkthroughControls.lock(false);
                } catch (error) {
                    reportError('walkthrough_lock_failed', error);
                    exitWalkthrough('pointer_lock_failed', true);
                }
            }
            return getWalkthroughState();
        }

        function droneSpawnRequest(input, volumes, bounds) {
            const value = input && typeof input === 'object' ? input : {};
            const selected = Array.from(state.selectedIds).sort();
            const placementId = stringValue(
                value.placementId,
                value.ignoreSelection !== true && selected.length === 1
                    ? selected[0] : ''
            );
            const target = placementId
                ? volumes.find(function (volume) {
                    return volume.placementId === placementId;
                }) : null;
            if (value.worldPoint
                    && Number.isFinite(Number(value.worldPoint.x))
                    && Number.isFinite(Number(value.worldPoint.y))
                    && Number.isFinite(Number(value.worldPoint.z))) {
                return {
                    desired: {
                        x: Number(value.worldPoint.x),
                        y: Number(value.worldPoint.y),
                        z: Number(value.worldPoint.z),
                    },
                    target: target,
                };
            }
            if (target) {
                const targetBounds = polygonBounds(target.polygon);
                const center = {
                    x: (targetBounds.minimum.x + targetBounds.maximum.x) / 2,
                    y: (target.minimumY + target.maximumY) / 2,
                    z: (targetBounds.minimum.z + targetBounds.maximum.z) / 2,
                };
                const span = Math.max(
                    targetBounds.maximum.x - targetBounds.minimum.x,
                    targetBounds.maximum.z - targetBounds.minimum.z,
                    target.maximumY - target.minimumY
                );
                const clearance = droneSettings.radius
                    + Math.min(15, Math.max(2, span * 0.8));
                return {
                    desired: {
                        x: targetBounds.minimum.x - clearance,
                        y: Math.max(
                            bounds.minimum.y + 2,
                            Math.min(bounds.maximum.y - droneSettings.radius,
                                center.y)
                        ),
                        z: center.z,
                    },
                    target: target,
                };
            }
            const cameraPoint = state.camera && state.camera.position
                ? copyPoint(state.camera.position, null) : null;
            const margin = droneSettings.radius;
            const cameraInside = cameraPoint
                && cameraPoint.x >= bounds.minimum.x + margin
                && cameraPoint.x <= bounds.maximum.x - margin
                && cameraPoint.y >= bounds.minimum.y + margin
                && cameraPoint.y <= bounds.maximum.y - margin
                && cameraPoint.z >= bounds.minimum.z + margin
                && cameraPoint.z <= bounds.maximum.z - margin;
            return {
                desired: cameraInside ? cameraPoint : {
                    x: (bounds.minimum.x + bounds.maximum.x) / 2,
                    y: Math.min(
                        bounds.maximum.y - margin,
                        bounds.minimum.y + 8
                    ),
                    z: (bounds.minimum.z + bounds.maximum.z) / 2,
                },
                target: null,
            };
        }

        function setDroneRecordPlacements(record, placements) {
            const visible = Array.isArray(placements) ? placements : [];
            if (!record || !record.instanced) return;
            record.pickObjects.forEach(function (object, meshIndex) {
                if (!object || typeof object.setMatrixAt !== 'function') return;
                const prototypeMatrix = record.prototypeMatrices[meshIndex];
                const placementIds = [];
                visible.forEach(function (placement, instanceIndex) {
                    object.setMatrixAt(
                        instanceIndex,
                        multiplyPlacementAndPrototype(
                            placement,
                            prototypeMatrix
                        )
                    );
                    placementIds.push(placement.placementId);
                });
                object.count = visible.length;
                if (object.instanceMatrix) {
                    object.instanceMatrix.needsUpdate = true;
                }
                if (typeof object.computeBoundingBox === 'function') {
                    object.computeBoundingBox();
                }
                if (typeof object.computeBoundingSphere === 'function') {
                    object.computeBoundingSphere();
                }
                object.userData = object.userData || {};
                object.userData.facilityInstancePlacementIds =
                    placementIds.slice();
                state.instanceLookup.set(object, placementIds);
                if (object.uuid) {
                    state.instanceLookup.set(object.uuid, placementIds);
                }
            });
        }

        function dronePlacementInRange(placement, position, rangeSquared) {
            const point = placement && placement.transform
                && placement.transform.position;
            if (!point) return false;
            const dx = finite(point.x, 0) - finite(position && position.x, 0);
            const dz = finite(point.z, 0) - finite(position && position.z, 0);
            return dx * dx + dz * dz <= rangeSquared;
        }

        function dronePlacementMap() {
            return new Map(state.placements.map(function (placement) {
                return [placement.placementId, placement];
            }));
        }

        function droneEffectiveViewDistance(position) {
            const altitude = Math.max(
                0,
                finite(position && position.y, state.drone.floorY)
                    - finite(state.drone.floorY, 0)
            );
            return droneViewDistanceForAltitude(
                altitude,
                droneSettings.viewDistance,
                droneSettings.altitudeViewMultiplier,
                droneSettings.maximumViewDistance
            );
        }

        function updateDroneProjection(viewDistance) {
            if (!state.camera) return false;
            const altitude = Math.max(
                0,
                finite(state.camera.position && state.camera.position.y, 0)
                    - finite(state.drone.floorY, 0)
            );
            const requiredFar = Math.min(
                Math.max(droneSettings.maximumViewDistance * 1.5, 100),
                Math.hypot(viewDistance, altitude) + 20
            );
            const changed = Math.abs(
                finite(state.camera.far, requiredFar) - requiredFar
            ) > 0.5;
            state.camera.far = requiredFar;
            if (changed
                    && typeof state.camera.updateProjectionMatrix === 'function') {
                state.camera.updateProjectionMatrix();
            }
            return changed;
        }

        function droneVisiblePlacementIds(position) {
            const viewDistance = droneEffectiveViewDistance(position);
            const rangeSquared = viewDistance * viewDistance;
            const selected = state.selectedIds;
            return new Set(state.placements.filter(function (placement) {
                return selected.has(placement.placementId)
                    || dronePlacementInRange(
                        placement,
                        position,
                        rangeSquared
                    );
            }).map(function (placement) {
                return placement.placementId;
            }));
        }

        function applyDroneRecordWindow(record, visibleIds, placementsById) {
            if (!record) return;
            const placements = record.placementIds.map(function (id) {
                return placementsById.get(id);
            }).filter(Boolean);
            const visible = placements.filter(function (placement) {
                return visibleIds.has(placement.placementId);
            });
            if (record.instanced) {
                setDroneRecordPlacements(record, visible);
                return;
            }
            record.pickObjects.forEach(function (object, index) {
                if (object) object.visible = Boolean(
                    placements[index]
                    && visibleIds.has(placements[index].placementId)
                );
            });
        }

        function applyDroneRenderWindow(force) {
            const drone = state.drone;
            if (!drone.active || !state.camera) return false;
            const current = state.camera.position;
            const previous = drone.lastVisualCullPosition;
            const viewDistance = droneEffectiveViewDistance(current);
            const moved = previous ? Math.hypot(
                finite(current.x, 0) - previous.x,
                finite(current.y, 0) - previous.y,
                finite(current.z, 0) - previous.z
            ) : Infinity;
            const viewDistanceChanged = drone.lastVisualViewDistance === null
                || Math.abs(
                    viewDistance - drone.lastVisualViewDistance
                ) >= droneSettings.cullUpdateDistance;
            if (!force && moved < droneSettings.cullUpdateDistance
                    && !viewDistanceChanged) {
                return false;
            }
            const visibleIds = droneVisiblePlacementIds(current);
            const placementsById = dronePlacementMap();
            state.renderGroups.forEach(function (record) {
                applyDroneRecordWindow(record, visibleIds, placementsById);
            });
            drone.visiblePlacementCount = visibleIds.size;
            drone.lastVisualViewDistance = viewDistance;
            drone.lastVisualCullPosition = {
                x: finite(current.x, 0),
                y: finite(current.y, 0),
                z: finite(current.z, 0),
            };
            updateDroneProjection(viewDistance);
            applySelection(true);
            return true;
        }

        function applyCurrentDroneRecordWindow(record) {
            if (!state.drone.active || !state.camera || !record) return;
            const visibleIds = droneVisiblePlacementIds(state.camera.position);
            applyDroneRecordWindow(record, visibleIds, dronePlacementMap());
            state.drone.visiblePlacementCount = visibleIds.size;
            applySelection(true);
        }

        function restoreDroneRenderWindow() {
            const placementsById = dronePlacementMap();
            state.renderGroups.forEach(function (record) {
                const placements = record.placementIds.map(function (id) {
                    return placementsById.get(id);
                }).filter(Boolean);
                if (record.instanced) {
                    setDroneRecordPlacements(record, placements);
                    return;
                }
                record.pickObjects.forEach(function (object) {
                    if (object) object.visible = true;
                });
            });
            state.drone.visiblePlacementCount = state.placements.length;
            state.drone.lastVisualCullPosition = null;
            state.drone.lastVisualViewDistance = null;
            applySelection(true);
        }

        function exitDrone(reason, skipUnlock) {
            const drone = state.drone;
            if (!drone.active && !drone.exiting) return false;
            const snapshot = drone.previousCamera;
            drone.exiting = true;
            drone.active = false;
            drone.locked = false;
            drone.keys.clear();
            const timerHost = options.window || root;
            if (state.navigationRestoreTimer !== null && timerHost
                    && typeof timerHost.clearTimeout === 'function') {
                timerHost.clearTimeout(state.navigationRestoreTimer);
            }
            state.navigationRestoreTimer = null;
            state.navigationInteracting = false;
            setRendererPixelRatio(state.displayPixelRatio);
            drone.lastFrameTime = null;
            drone.currentSpeed = 0;
            drone.lastReason = reason || 'exited';
            if (state.walkthroughControls) {
                state.walkthroughControls.enabled = false;
                if (!skipUnlock && state.walkthroughControls.isLocked
                        && typeof state.walkthroughControls.unlock === 'function') {
                    try { state.walkthroughControls.unlock(); } catch (error) {
                        reportError('drone_unlock_failed', error);
                    }
                }
            }
            restoreDroneRenderWindow();
            restoreWalkthroughCamera(snapshot);
            drone.previousCamera = null;
            drone.obstacleVolumes = [];
            drone.obstacleIndex = null;
            drone.bounds = null;
            drone.spawn = null;
            drone.altitude = 0;
            drone.nearestObstacleDistance = null;
            drone.nearestObstacleId = null;
            drone.visiblePlacementCount = 0;
            drone.lastVisualCullPosition = null;
            drone.lastVisualViewDistance = null;
            drone.exiting = false;
            setWalkthroughContextFocus(null);
            applySelection();
            notifyDroneState(true);
            invalidate();
            return true;
        }

        function deactivateDroneForHandoff(reason) {
            const drone = state.drone;
            const overviewCamera = drone.previousCamera;
            drone.exiting = true;
            drone.active = false;
            drone.locked = false;
            drone.keys.clear();
            const timerHost = options.window || root;
            if (state.navigationRestoreTimer !== null && timerHost
                    && typeof timerHost.clearTimeout === 'function') {
                timerHost.clearTimeout(state.navigationRestoreTimer);
            }
            state.navigationRestoreTimer = null;
            state.navigationInteracting = false;
            setRendererPixelRatio(state.displayPixelRatio);
            drone.lastFrameTime = null;
            drone.currentSpeed = 0;
            drone.lastReason = reason || 'handoff';
            restoreDroneRenderWindow();
            drone.previousCamera = null;
            drone.obstacleVolumes = [];
            drone.obstacleIndex = null;
            drone.bounds = null;
            drone.spawn = null;
            drone.altitude = 0;
            drone.nearestObstacleDistance = null;
            drone.nearestObstacleId = null;
            drone.visiblePlacementCount = 0;
            drone.lastVisualCullPosition = null;
            drone.lastVisualViewDistance = null;
            drone.exiting = false;
            return overviewCamera;
        }

        function switchImmersiveMode(requestedMode) {
            const targetMode = String(requestedMode || '').toLowerCase();
            if (targetMode !== 'walkthrough' && targetMode !== 'drone') {
                return false;
            }
            const sourceMode = state.drone.active
                ? 'drone' : (state.walkthrough.active ? 'walkthrough' : null);
            if (!sourceMode) {
                return targetMode === 'drone'
                    ? enterDrone({ ignoreSelection: true })
                    : enterWalkthrough({ ignoreSelection: true });
            }
            if (sourceMode === targetMode) {
                return targetMode === 'drone'
                    ? getDroneState() : getWalkthroughState();
            }

            const handoffCamera = cameraSnapshot();
            const pointerLocked = Boolean(
                state.walkthroughControls
                && state.walkthroughControls.isLocked
            );
            const overviewCamera = sourceMode === 'drone'
                ? deactivateDroneForHandoff('handoff_to_walkthrough')
                : deactivateWalkthroughForHandoff('handoff_to_drone');
            const entry = {
                ignoreSelection: true,
                worldPoint: copyPoint(handoffCamera.position),
                immersiveHandoff: {
                    sourceMode: sourceMode,
                    camera: handoffCamera,
                    overviewCamera: overviewCamera || handoffCamera,
                    pointerLocked: pointerLocked,
                },
            };
            const result = targetMode === 'drone'
                ? enterDrone(entry) : enterWalkthrough(entry);
            const active = Boolean(result && result.active);
            if (!active) {
                restoreWalkthroughCamera(overviewCamera || handoffCamera);
                setWalkthroughContextFocus(null);
            }
            if (sourceMode === 'drone') notifyDroneState(true);
            else notifyWalkthroughState();
            applySelection();
            invalidate();
            return result;
        }

        function enterDrone(input) {
            const drone = state.drone;
            if (state.walkthrough.active) {
                return switchImmersiveMode('drone');
            }
            const entry = input && typeof input === 'object' ? input : {};
            const handoff = entry.immersiveHandoff
                && typeof entry.immersiveHandoff === 'object'
                ? entry.immersiveHandoff : null;
            if (drone.active) {
                if (!drone.locked && state.walkthroughControls
                        && typeof state.walkthroughControls.lock === 'function') {
                    try { state.walkthroughControls.lock(false); } catch (error) {
                        reportError('drone_lock_failed', error);
                    }
                }
                return getDroneState();
            }
            if (typeof PointerLockControls !== 'function'
                    || !state.walkthroughControls || !state.camera
                    || !state.canvas || state.degraded || state.suspended) {
                drone.lastReason = 'drone_unavailable';
                warning(
                    'drone_unavailable',
                    'Drone controls are unavailable in this 3D runtime.'
                );
                return notifyDroneState(true);
            }
            const volumes = buildDroneObstacleVolumes();
            const obstacleIndex = buildDroneSpatialIndex(
                volumes,
                finite(options.droneSpatialCellSize, 10)
            );
            const bounds = configuredDroneBounds(volumes);
            if (!bounds) {
                drone.lastReason = 'facility_bounds_unavailable';
                warning(
                    'drone_bounds_unavailable',
                    'A valid facility volume is required for Drone mode.'
                );
                return notifyDroneState(true);
            }
            const request = droneSpawnRequest(input, volumes, bounds);
            const spawn = findDroneSpawn({
                desired: request.desired,
                radius: droneSettings.radius,
                bounds: bounds,
                volumes: obstacleIndex,
            });
            if (!spawn) {
                drone.lastReason = 'no_valid_spawn';
                warning(
                    'drone_no_valid_spawn',
                    'No collision-free Drone starting point was found.'
                );
                return notifyDroneState(true);
            }
            drone.previousCamera = handoff && handoff.overviewCamera
                ? handoff.overviewCamera : cameraSnapshot();
            drone.active = true;
            drone.locked = false;
            drone.keys.clear();
            drone.lastFrameTime = null;
            drone.obstacleVolumes = volumes;
            drone.obstacleIndex = obstacleIndex;
            drone.bounds = bounds;
            drone.floorY = bounds.minimum.y;
            drone.spawn = Object.assign({}, spawn);
            drone.collisionCount = 0;
            drone.currentSpeed = 0;
            drone.altitude = Math.max(0, spawn.y - drone.floorY);
            drone.nearestObstacleDistance = null;
            drone.nearestObstacleId = null;
            drone.lastReason = 'entering';
            drone.lastNotificationTime = null;
            applySelection();
            if (state.controls) {
                state.controls.autoRotate = false;
                state.controls.enabled = false;
            }
            state.walkthroughControls.enabled = false;
            setVector(state.camera.position, spawn);
            if (state.camera.up) setVector(state.camera.up, { x: 0, y: 1, z: 0 });
            if (request.target && typeof state.camera.lookAt === 'function') {
                const targetBounds = polygonBounds(request.target.polygon);
                state.camera.lookAt(
                    (targetBounds.minimum.x + targetBounds.maximum.x) / 2,
                    (request.target.minimumY + request.target.maximumY) / 2,
                    (targetBounds.minimum.z + targetBounds.maximum.z) / 2
                );
            }
            if (handoff && handoff.camera) {
                setQuaternion(state.camera.quaternion, handoff.camera.quaternion);
                drone.lastReason = 'handoff_from_walkthrough';
            }
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld(true);
            }
            state.camera.near = Math.max(0.05, finite(state.camera.near, 0.05));
            state.camera.far = Math.min(
                finite(
                    state.camera.far,
                    droneEffectiveViewDistance(spawn)
                ),
                droneSettings.maximumViewDistance * 1.5
            );
            if (Number.isFinite(Number(state.camera.fov))) {
                state.camera.fov = droneSettings.fieldOfView;
            }
            if (typeof state.camera.updateProjectionMatrix === 'function') {
                state.camera.updateProjectionMatrix();
            }
            applyDroneRenderWindow(true);
            const reusePointerLock = Boolean(
                handoff && handoff.pointerLocked
                && state.walkthroughControls.isLocked
            );
            if (reusePointerLock) {
                drone.locked = true;
                state.walkthroughControls.enabled = true;
            }
            notifyDroneState(true);
            invalidate();
            if (!reusePointerLock) {
                try {
                    state.walkthroughControls.lock(false);
                } catch (error) {
                    reportError('drone_lock_failed', error);
                    exitDrone('pointer_lock_failed', true);
                }
            }
            return getDroneState();
        }

        function cancelWalkthroughNavigation(reason) {
            const route = state.walkthrough.route;
            const changed = route.active || route.points.length > 0;
            route.active = false;
            route.points = [];
            route.pointIndex = 0;
            route.distance = 0;
            route.targetPlacementId = null;
            route.destination = null;
            route.reason = reason || 'cancelled';
            if (changed) {
                state.walkthrough.lastReason = route.reason;
                notifyWalkthroughState();
                invalidate();
            }
            return changed;
        }

        function beginWalkthroughNavigation(destination, metadata) {
            const walkthrough = state.walkthrough;
            if (!walkthrough.active || !state.camera || !destination) {
                return { ok: false, reason: 'walkthrough_inactive', points: [] };
            }
            const plan = planWalkthroughRoute({
                start: {
                    x: finite(state.camera.position.x, NaN),
                    z: finite(state.camera.position.z, NaN),
                },
                goal: destination,
                radius: walkthroughSettings.radius,
                bounds: walkthrough.bounds,
                obstacles: walkthrough.obstaclePolygons,
                gridSpacing: finite(
                    options.walkthroughRouteGridSpacing,
                    0.5
                ),
                maximumNodes: finite(
                    options.walkthroughRouteMaximumNodes,
                    20000
                ),
            });
            if (!plan.ok) {
                walkthrough.route.reason = plan.reason;
                warning(
                    'walkthrough_route_' + plan.reason,
                    'No collision-free walking route was found.'
                );
                notifyWalkthroughState();
                return plan;
            }
            walkthrough.route.active = plan.points.length > 1
                && plan.distance > 1e-6;
            walkthrough.route.points = plan.points.map(function (point) {
                return { x: point.x, z: point.z };
            });
            walkthrough.route.pointIndex = walkthrough.route.active ? 1 : 0;
            walkthrough.route.distance = plan.distance;
            walkthrough.route.targetPlacementId = metadata
                && metadata.targetPlacementId || null;
            walkthrough.route.destination = {
                x: destination.x,
                z: destination.z,
            };
            walkthrough.route.reason = walkthrough.route.active
                ? 'navigating' : 'arrived';
            walkthrough.targetPlacementId =
                walkthrough.route.targetPlacementId;
            walkthrough.lastReason = walkthrough.route.reason;
            const next = walkthrough.route.points[walkthrough.route.pointIndex];
            if (next && typeof state.camera.lookAt === 'function') {
                state.camera.lookAt(
                    next.x,
                    walkthrough.floorY + walkthroughSettings.eyeHeight,
                    next.z
                );
                if (typeof state.camera.updateMatrixWorld === 'function') {
                    state.camera.updateMatrixWorld(true);
                }
            }
            notifyWalkthroughState();
            invalidate();
            return plan;
        }

        function ensureWalkthroughForNavigation() {
            if (state.walkthrough.active) return true;
            enterWalkthrough({ ignoreSelection: true });
            return state.walkthrough.active;
        }

        function navigateWalkthroughToPoint(value) {
            const point = value && typeof value === 'object' ? {
                x: finite(value.x, NaN),
                z: finite(value.z, NaN),
            } : null;
            if (!point || !Number.isFinite(point.x)
                    || !Number.isFinite(point.z)) {
                return { ok: false, reason: 'invalid_goal', points: [] };
            }
            if (!ensureWalkthroughForNavigation()) {
                return { ok: false, reason: 'walkthrough_unavailable', points: [] };
            }
            return beginWalkthroughNavigation(point, null);
        }

        function navigateWalkthroughToPlacement(placementId) {
            const targetId = stringValue(placementId, '');
            const records = buildWalkthroughObstacles();
            const target = records.find(function (record) {
                return record.placementId === targetId;
            });
            if (!target) {
                return { ok: false, reason: 'target_not_found', points: [] };
            }
            if (!ensureWalkthroughForNavigation()) {
                return { ok: false, reason: 'walkthrough_unavailable', points: [] };
            }
            const request = walkthroughSpawnRequest(
                { placementId: targetId },
                records
            );
            const destination = findWalkthroughSpawn({
                desired: request.desired,
                radius: walkthroughSettings.radius,
                bounds: state.walkthrough.bounds,
                obstacles: state.walkthrough.obstaclePolygons,
            });
            if (!destination) {
                return { ok: false, reason: 'no_valid_destination', points: [] };
            }
            return beginWalkthroughNavigation(destination, {
                targetPlacementId: targetId,
            });
        }

        function movementCode(event) {
            const code = String(event && (event.code || event.key) || '');
            const aliases = {
                w: 'KeyW', a: 'KeyA', s: 'KeyS', d: 'KeyD',
                g: 'KeyG',
                ArrowUp: 'KeyW', ArrowLeft: 'KeyA',
                ArrowDown: 'KeyS', ArrowRight: 'KeyD',
                Shift: 'ShiftLeft',
                Control: 'ControlLeft',
                ' ': 'Space',
            };
            return aliases[code] || aliases[code.toLowerCase()] || code;
        }

        function walkthroughHasMovement() {
            const keys = state.walkthrough.keys;
            return keys.has('KeyW') || keys.has('KeyA')
                || keys.has('KeyS') || keys.has('KeyD');
        }

        function walkthroughHasActivity() {
            return walkthroughHasMovement()
                || state.walkthrough.route.active;
        }

        function handleWalkthroughKey(event, pressed) {
            if (!state.walkthrough.active) return;
            const code = movementCode(event);
            if (code === 'KeyG') {
                if (pressed && !event.repeat) {
                    if (typeof event.preventDefault === 'function') {
                        event.preventDefault();
                    }
                    switchImmersiveMode('drone');
                }
                return;
            }
            if (code === 'Escape') {
                if (pressed) exitWalkthrough('escape');
                return;
            }
            if (!['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ShiftLeft', 'ShiftRight']
                    .includes(code)) return;
            if (typeof event.preventDefault === 'function') event.preventDefault();
            if (pressed && ['KeyW', 'KeyA', 'KeyS', 'KeyD'].includes(code)) {
                cancelWalkthroughNavigation('manual_input');
            }
            if (pressed) state.walkthrough.keys.add(code);
            else state.walkthrough.keys.delete(code);
            if (!walkthroughHasMovement()) {
                state.walkthrough.lastFrameTime = null;
            }
            invalidate();
        }

        function updateWalkthrough(timestamp) {
            const walkthrough = state.walkthrough;
            if (!walkthrough.active || !walkthrough.locked
                    || !walkthroughHasActivity() || !state.camera
                    || !state.walkthroughControls) {
                walkthrough.lastFrameTime = null;
                return false;
            }
            const now = finite(timestamp, 0);
            const deltaSeconds = walkthrough.lastFrameTime === null
                ? 1 / 60
                : Math.max(0.001, Math.min(
                    0.05, (now - walkthrough.lastFrameTime) / 1000
                ));
            walkthrough.lastFrameTime = now;
            const keys = walkthrough.keys;
            let moveX = 0;
            let moveZ = 0;
            let deltaX = 0;
            let deltaZ = 0;
            const manualMovement = walkthroughHasMovement();
            if (manualMovement) {
                let forwardVector = null;
                if (typeof THREE.Vector3 === 'function') {
                    forwardVector = new THREE.Vector3();
                    state.walkthroughControls.getDirection(forwardVector);
                }
                const forward = {
                    x: finite(forwardVector && forwardVector.x, 0),
                    z: finite(forwardVector && forwardVector.z, -1),
                };
                const forwardLength = Math.sqrt(
                    forward.x * forward.x + forward.z * forward.z
                ) || 1;
                forward.x /= forwardLength;
                forward.z /= forwardLength;
                const right = { x: -forward.z, z: forward.x };
                if (keys.has('KeyW')) {
                    moveX += forward.x;
                    moveZ += forward.z;
                }
                if (keys.has('KeyS')) {
                    moveX -= forward.x;
                    moveZ -= forward.z;
                }
                if (keys.has('KeyD')) {
                    moveX += right.x;
                    moveZ += right.z;
                }
                if (keys.has('KeyA')) {
                    moveX -= right.x;
                    moveZ -= right.z;
                }
                const movementLength = Math.sqrt(
                    moveX * moveX + moveZ * moveZ
                ) || 1;
                moveX /= movementLength;
                moveZ /= movementLength;
                const speed = keys.has('ShiftLeft') || keys.has('ShiftRight')
                    ? walkthroughSettings.fastSpeed
                    : walkthroughSettings.walkSpeed;
                const distance = speed * deltaSeconds;
                deltaX = moveX * distance;
                deltaZ = moveZ * distance;
            } else if (walkthrough.route.active) {
                const target = walkthrough.route.points[
                    walkthrough.route.pointIndex
                ];
                if (!target) {
                    cancelWalkthroughNavigation('arrived');
                    return true;
                }
                const dx = target.x - state.camera.position.x;
                const dz = target.z - state.camera.position.z;
                const remaining = Math.sqrt(dx * dx + dz * dz);
                const maximumDistance = walkthroughSettings.navigationSpeed
                    * deltaSeconds;
                if (remaining <= Math.max(1e-6, maximumDistance)) {
                    deltaX = dx;
                    deltaZ = dz;
                    walkthrough.route.pointIndex += 1;
                } else {
                    deltaX = dx / remaining * maximumDistance;
                    deltaZ = dz / remaining * maximumDistance;
                }
            }
            const result = resolveWalkthroughMovement({
                start: state.camera.position,
                delta: {
                    x: deltaX,
                    z: deltaZ,
                },
                radius: walkthroughSettings.radius,
                bounds: walkthrough.bounds,
                obstacles: walkthrough.obstaclePolygons,
            });
            if (result.collided) {
                walkthrough.collisionCount += 1;
                if (walkthrough.route.active) {
                    cancelWalkthroughNavigation('route_blocked');
                }
            }
            state.camera.position.x = result.position.x;
            state.camera.position.y = walkthrough.floorY
                + walkthroughSettings.eyeHeight;
            state.camera.position.z = result.position.z;
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld(true);
            }
            if (!manualMovement && walkthrough.route.active
                    && walkthrough.route.pointIndex
                        >= walkthrough.route.points.length) {
                cancelWalkthroughNavigation('arrived');
            }
            return true;
        }

        function droneHasMovement() {
            const keys = state.drone.keys;
            return keys.has('KeyW') || keys.has('KeyA')
                || keys.has('KeyS') || keys.has('KeyD')
                || keys.has('Space') || keys.has('ControlLeft')
                || keys.has('ControlRight');
        }

        function handleDroneKey(event, pressed) {
            if (!state.drone.active) return;
            const code = movementCode(event);
            if (code === 'KeyG') {
                if (pressed && !event.repeat) {
                    if (typeof event.preventDefault === 'function') {
                        event.preventDefault();
                    }
                    switchImmersiveMode('walkthrough');
                }
                return;
            }
            if (code === 'Escape') {
                if (pressed) exitDrone('escape');
                return;
            }
            const accepted = [
                'KeyW', 'KeyA', 'KeyS', 'KeyD',
                'Space', 'ControlLeft', 'ControlRight',
                'ShiftLeft', 'ShiftRight',
            ];
            if (!accepted.includes(code)) return;
            if (typeof event.preventDefault === 'function') event.preventDefault();
            const hadMovement = droneHasMovement();
            if (pressed) state.drone.keys.add(code);
            else state.drone.keys.delete(code);
            const hasMovement = droneHasMovement();
            if (hasMovement && !hadMovement) beginDroneInteraction();
            if (!hasMovement) {
                state.drone.lastFrameTime = null;
                state.drone.currentSpeed = 0;
                endNavigationInteraction();
            }
            invalidate();
        }

        function updateDrone(timestamp) {
            const drone = state.drone;
            if (!drone.active || !drone.locked || !droneHasMovement()
                    || !state.camera || !state.walkthroughControls) {
                drone.lastFrameTime = null;
                if (drone.currentSpeed !== 0) {
                    drone.currentSpeed = 0;
                    notifyDroneState(false);
                }
                return false;
            }
            const now = finite(timestamp, 0);
            const deltaSeconds = drone.lastFrameTime === null
                ? 1 / 60
                : Math.max(0.001, Math.min(
                    0.05,
                    (now - drone.lastFrameTime) / 1000
                ));
            drone.lastFrameTime = now;
            const keys = drone.keys;
            let directionVector = null;
            if (typeof THREE.Vector3 === 'function') {
                directionVector = new THREE.Vector3();
                state.walkthroughControls.getDirection(directionVector);
            }
            const forward = {
                x: finite(directionVector && directionVector.x, 0),
                y: finite(directionVector && directionVector.y, 0),
                z: finite(directionVector && directionVector.z, -1),
            };
            const forwardLength = Math.hypot(
                forward.x,
                forward.y,
                forward.z
            ) || 1;
            forward.x /= forwardLength;
            forward.y /= forwardLength;
            forward.z /= forwardLength;
            const horizontalLength = Math.hypot(forward.x, forward.z) || 1;
            const right = {
                x: -forward.z / horizontalLength,
                y: 0,
                z: forward.x / horizontalLength,
            };
            const movement = { x: 0, y: 0, z: 0 };
            if (keys.has('KeyW')) {
                movement.x += forward.x;
                movement.y += forward.y;
                movement.z += forward.z;
            }
            if (keys.has('KeyS')) {
                movement.x -= forward.x;
                movement.y -= forward.y;
                movement.z -= forward.z;
            }
            if (keys.has('KeyD')) {
                movement.x += right.x;
                movement.z += right.z;
            }
            if (keys.has('KeyA')) {
                movement.x -= right.x;
                movement.z -= right.z;
            }
            if (keys.has('Space')) movement.y += 1;
            if (keys.has('ControlLeft') || keys.has('ControlRight')) {
                movement.y -= 1;
            }
            const movementLength = Math.hypot(
                movement.x,
                movement.y,
                movement.z
            ) || 1;
            movement.x /= movementLength;
            movement.y /= movementLength;
            movement.z /= movementLength;
            const requestedSpeed = keys.has('ShiftLeft')
                    || keys.has('ShiftRight')
                ? droneSettings.boostSpeed
                : droneSettings.cruiseSpeed;
            let speedScale = 1;
            let proximity = {
                distance: null,
                obstacleId: null,
                bounded: false,
            };
            if (drone.assistedFlight) {
                proximity = probeDroneClearance({
                    start: state.camera.position,
                    direction: movement,
                    maximumDistance: droneSettings.slowdownDistance,
                    radius: droneSettings.radius,
                    bounds: drone.bounds,
                    volumes: drone.obstacleIndex || drone.obstacleVolumes,
                });
                if (proximity.bounded) {
                    const usable = Math.max(
                        0,
                        proximity.distance - droneSettings.stopDistance
                    );
                    const range = Math.max(
                        0.01,
                        droneSettings.slowdownDistance
                            - droneSettings.stopDistance
                    );
                    speedScale = Math.max(0, Math.min(1, usable / range));
                }
            }
            const actualSpeed = requestedSpeed * speedScale;
            const result = resolveDroneMovement({
                start: state.camera.position,
                delta: {
                    x: movement.x * actualSpeed * deltaSeconds,
                    y: movement.y * actualSpeed * deltaSeconds,
                    z: movement.z * actualSpeed * deltaSeconds,
                },
                radius: droneSettings.radius,
                bounds: drone.bounds,
                volumes: drone.obstacleIndex || drone.obstacleVolumes,
            });
            if (result.collided) drone.collisionCount += 1;
            state.camera.position.x = result.position.x;
            state.camera.position.y = result.position.y;
            state.camera.position.z = result.position.z;
            applyDroneRenderWindow(false);
            drone.currentSpeed = actualSpeed;
            drone.altitude = Math.max(
                0,
                result.position.y - drone.floorY
            );
            drone.nearestObstacleDistance = proximity.bounded
                ? Math.round(proximity.distance * 100) / 100 : null;
            drone.nearestObstacleId = proximity.obstacleId || null;
            drone.lastReason = result.collided
                ? 'collision_avoided' : 'active';
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld(true);
            }
            notifyDroneState(false);
            return true;
        }

        function clearEnvironmentObjects() {
            if (state.environmentRoot
                    && Array.isArray(state.environmentRoot.children)) {
                const children = state.environmentRoot.children.slice();
                children.forEach(function (child) {
                    if (typeof state.environmentRoot.remove === 'function') {
                        state.environmentRoot.remove(child);
                    }
                });
                disposeObjectGraphs(children);
            }
            state.floorObject = null;
            state.gridObjects = [];
            state.axisObjects = [];
            state.environmentSignature = null;
            state.environmentDiagnostics = null;
        }

        function gridCoordinateValues(minimum, maximum, spacing) {
            const epsilon = spacing * 0.000001;
            const output = [];
            let value = Math.ceil((minimum - epsilon) / spacing) * spacing;
            const maximumCount = 512;
            while (value <= maximum + epsilon
                    && output.length < maximumCount) {
                output.push(Number(value.toFixed(6)));
                value += spacing;
            }
            return output;
        }

        function isMajorGridCoordinate(value, majorSpacing) {
            const quotient = value / majorSpacing;
            return Math.abs(quotient - Math.round(quotient)) < 0.000001;
        }

        function createGridLineObject(
            positions,
            color,
            opacity,
            name,
            environmentKind,
            renderOrder
        ) {
            if (!positions.length
                    || typeof THREE.BufferGeometry !== 'function'
                    || typeof THREE.Float32BufferAttribute !== 'function'
                    || typeof THREE.LineBasicMaterial !== 'function'
                    || typeof THREE.LineSegments !== 'function') {
                return null;
            }
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute(
                'position',
                new THREE.Float32BufferAttribute(positions, 3)
            );
            const material = new THREE.LineBasicMaterial({
                color: color,
                transparent: true,
                opacity: opacity,
                depthWrite: false,
                depthTest: true,
                toneMapped: false,
            });
            const lines = new THREE.LineSegments(geometry, material);
            lines.name = name;
            lines.renderOrder = finite(renderOrder, -9);
            lines.userData = lines.userData || {};
            lines.userData.facilityEnvironment = environmentKind || 'floor-grid';
            return lines;
        }

        function createFloorGrid(bounds, floorY, spacing, majorSpacing) {
            const minorPositions = [];
            const majorPositions = [];
            const y = floorY + 0.0002;
            const xValues = gridCoordinateValues(
                bounds.minimum.x,
                bounds.maximum.x,
                spacing
            );
            const zValues = gridCoordinateValues(
                bounds.minimum.z,
                bounds.maximum.z,
                spacing
            );
            xValues.forEach(function (x) {
                const target = isMajorGridCoordinate(x, majorSpacing)
                    ? majorPositions : minorPositions;
                target.push(
                    x, y, bounds.minimum.z,
                    x, y, bounds.maximum.z
                );
            });
            zValues.forEach(function (z) {
                const target = isMajorGridCoordinate(z, majorSpacing)
                    ? majorPositions : minorPositions;
                target.push(
                    bounds.minimum.x, y, z,
                    bounds.maximum.x, y, z
                );
            });
            const light = isLightTheme();
            const minor = createGridLineObject(
                minorPositions,
                light ? 0xb1c0c9 : 0x354958,
                light ? 0.42 : 0.34,
                'InspectorProFacilityFloorGridMinor'
            );
            const major = createGridLineObject(
                majorPositions,
                light ? 0x8299a8 : 0x587184,
                light ? 0.68 : 0.58,
                'InspectorProFacilityFloorGridMajor'
            );
            return {
                objects: [minor, major].filter(Boolean),
                minorLineCount: minorPositions.length / 6,
                majorLineCount: majorPositions.length / 6,
            };
        }

        function createFloorAxes(bounds, floorY, majorSpacing) {
            const width = Math.max(0.01, bounds.maximum.x - bounds.minimum.x);
            const depth = Math.max(0.01, bounds.maximum.z - bounds.minimum.z);
            const length = Math.min(width, depth, majorSpacing * 2);
            const y = floorY + 0.008;
            const origin = {
                x: bounds.minimum.x,
                y: floorY,
                z: bounds.minimum.z,
            };
            const xAxis = createGridLineObject([
                origin.x, y, origin.z,
                origin.x + length, y, origin.z,
            ], 0xd1495b, 0.92, 'InspectorProFacilityAxisX', 'floor-axis-x', -8);
            const zAxis = createGridLineObject([
                origin.x, y, origin.z,
                origin.x, y, origin.z + length,
            ], 0x1683c4, 0.92, 'InspectorProFacilityAxisZ', 'floor-axis-z', -8);
            return {
                objects: [xAxis, zAxis].filter(Boolean),
                origin: origin,
                length: length,
            };
        }

        function syncEnvironment() {
            if (!state.environmentRoot || options.showFloor === false) {
                clearEnvironmentObjects();
                invalidate();
                return false;
            }
            const bounds = configuredEnvironmentBounds();
            if (!bounds) return false;
            const width = Math.max(
                0.01,
                bounds.maximum.x - bounds.minimum.x
            );
            const depth = Math.max(
                0.01,
                bounds.maximum.z - bounds.minimum.z
            );
            const floorY = finite(bounds.minimum.y, 0);
            const requestedSpacing = Math.max(
                0.05,
                finite(options.floorGridSpacing, DEFAULT_GRID_SPACING)
            );
            const minimumSpacing = Math.max(width, depth) / 240;
            const spacing = Math.max(
                requestedSpacing,
                Math.ceil(minimumSpacing / requestedSpacing)
                    * requestedSpacing
            );
            const requestedMajor = Math.max(
                spacing,
                finite(
                    options.floorMajorGridSpacing,
                    DEFAULT_MAJOR_GRID_SPACING
                )
            );
            const majorSpacing = Math.max(
                spacing,
                Math.round(requestedMajor / spacing) * spacing
            );
            const signature = JSON.stringify({
                bounds: bounds,
                spacing: spacing,
                majorSpacing: majorSpacing,
                gridVisible: state.gridVisible,
                theme: isLightTheme() ? 'light' : 'dark',
            });
            if (signature === state.environmentSignature) return true;

            clearEnvironmentObjects();
            state.environmentSignature = signature;
            const light = isLightTheme();
            if (typeof THREE.BoxGeometry === 'function'
                    && typeof THREE.MeshStandardMaterial === 'function'
                    && typeof THREE.Mesh === 'function') {
                const floor = new THREE.Mesh(
                    new THREE.BoxGeometry(width, FLOOR_THICKNESS, depth),
                    new THREE.MeshStandardMaterial({
                        color: light ? 0xd7e0e6 : 0x2d3945,
                        transparent: true,
                        opacity: light ? 0.62 : 0.48,
                        roughness: 1,
                        metalness: 0,
                        depthWrite: true,
                    })
                );
                floor.name = 'InspectorProFacilityFloor';
                floor.position.set(
                    (bounds.minimum.x + bounds.maximum.x) / 2,
                    floorY - FLOOR_THICKNESS / 2,
                    (bounds.minimum.z + bounds.maximum.z) / 2
                );
                floor.receiveShadow = true;
                floor.renderOrder = -10;
                floor.userData = floor.userData || {};
                floor.userData.facilityEnvironment = 'floor';
                state.environmentRoot.add(floor);
                state.floorObject = floor;
            }
            const grid = state.gridVisible
                ? createFloorGrid(
                    bounds,
                    floorY,
                    spacing,
                    majorSpacing
                )
                : {
                    objects: [],
                    minorLineCount: 0,
                    majorLineCount: 0,
                };
            grid.objects.forEach(function (object) {
                state.environmentRoot.add(object);
            });
            state.gridObjects = grid.objects;
            const axes = createFloorAxes(bounds, floorY, majorSpacing);
            axes.objects.forEach(function (object) {
                state.environmentRoot.add(object);
            });
            state.axisObjects = axes.objects;
            state.environmentDiagnostics = {
                floorVisible: Boolean(state.floorObject),
                gridVisible: state.gridObjects.length > 0,
                axesVisible: state.axisObjects.length === 2,
                floorY: floorY,
                width: width,
                depth: depth,
                spacing: spacing,
                majorSpacing: majorSpacing,
                minorLineCount: grid.minorLineCount,
                majorLineCount: grid.majorLineCount,
                axisLength: axes.length,
                origin: axes.origin,
            };
            invalidate();
            return true;
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
            disposeProposalObjects();
            state.renderGroups.forEach(disposeRenderGroup);
            state.renderGroups.clear();
            disposeObjectGraphs(state.floorMarkingObjects);
            state.floorMarkingObjects = [];
            disposeObjectGraphs(state.routeObjects);
            state.routeObjects = [];
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

        function markingColorNumber(value, fallback) {
            const text = String(value || '');
            return /^#[0-9a-f]{6}$/i.test(text)
                ? parseInt(text.slice(1), 16)
                : fallback;
        }

        function configureFloorMarkingTexture(texture) {
            if (!texture) return null;
            texture.needsUpdate = true;
            texture.generateMipmaps = true;
            texture.premultiplyAlpha = false;
            if ('colorSpace' in texture && THREE.SRGBColorSpace) {
                texture.colorSpace = THREE.SRGBColorSpace;
            }
            if (THREE.LinearMipmapLinearFilter !== undefined) {
                texture.minFilter = THREE.LinearMipmapLinearFilter;
            }
            if (THREE.LinearFilter !== undefined) {
                texture.magFilter = THREE.LinearFilter;
            }
            const capabilities = state.renderer && state.renderer.capabilities;
            if (capabilities
                    && typeof capabilities.getMaxAnisotropy === 'function') {
                texture.anisotropy = Math.max(
                    1,
                    finite(capabilities.getMaxAnisotropy(), 1)
                );
            }
            return texture;
        }

        function floorMarkingTexture(marking) {
            const documentRef = options.document || (root && root.document);
            if (!documentRef || typeof documentRef.createElement !== 'function'
                    || typeof THREE.CanvasTexture !== 'function') return null;
            const canvas = documentRef.createElement('canvas');
            canvas.width = 1024;
            canvas.height = 1024;
            const context = typeof canvas.getContext === 'function'
                ? canvas.getContext('2d') : null;
            if (!context) return null;
            context.scale(2, 2);
            const fill = marking.fillColor || '#facc15';
            const stroke = marking.strokeColor || '#111827';
            context.clearRect(0, 0, 512, 512);
            context.lineJoin = 'round';
            context.lineCap = 'butt';
            context.strokeStyle = stroke;
            context.fillStyle = fill;
            context.lineWidth = 18;
            const type = marking.markingType || 'solid_line';
            if (type === 'direction_arrow') {
                context.beginPath();
                context.moveTo(256, 22);
                context.lineTo(474, 212);
                context.lineTo(348, 212);
                context.lineTo(348, 490);
                context.lineTo(164, 490);
                context.lineTo(164, 212);
                context.lineTo(38, 212);
                context.closePath();
                context.fill();
                context.stroke();
            } else if (type === 'dashed_line') {
                context.lineWidth = 170;
                if (typeof context.setLineDash === 'function') {
                    context.setLineDash([88, 62]);
                }
                context.beginPath();
                context.moveTo(256, 0);
                context.lineTo(256, 512);
                context.strokeStyle = fill;
                context.stroke();
            } else if (type === 'crosswalk') {
                for (let index = 0; index < 6; index += 1) {
                    context.fillRect(18, 28 + index * 84, 476, 46);
                }
            } else if (type === 'hazard_stripe') {
                context.fillStyle = fill;
                context.fillRect(0, 0, 512, 512);
                context.strokeStyle = stroke;
                context.lineWidth = 68;
                for (let offset = -512; offset <= 1024; offset += 142) {
                    context.beginPath();
                    context.moveTo(offset, 512);
                    context.lineTo(offset + 512, 0);
                    context.stroke();
                }
            } else if (type === 'keep_clear' || type === 'parking_box') {
                context.globalAlpha = 0.16;
                context.fillRect(16, 16, 480, 480);
                context.globalAlpha = 1;
                context.strokeStyle = fill;
                context.lineWidth = 28;
                context.strokeRect(18, 18, 476, 476);
                context.fillStyle = stroke;
                context.font = 'bold 58px Segoe UI, Arial, sans-serif';
                context.textAlign = 'center';
                context.textBaseline = 'middle';
                context.fillText(
                    marking.text || (type === 'keep_clear'
                        ? 'KEEP CLEAR' : 'PARKING'),
                    256,
                    256,
                    430
                );
            } else if (type === 'floor_text') {
                context.fillStyle = stroke;
                context.font = 'bold 76px Segoe UI, Arial, sans-serif';
                context.textAlign = 'center';
                context.textBaseline = 'middle';
                context.fillText(String(marking.text || ''), 256, 256, 472);
            } else {
                context.fillRect(0, 0, 512, 512);
            }
            return configureFloorMarkingTexture(
                new THREE.CanvasTexture(canvas)
            );
        }

        function floorMarkingTextTexture(marking, value) {
            const label = String(value || '').trim();
            const documentRef = options.document || (root && root.document);
            if (!label || !documentRef
                    || typeof documentRef.createElement !== 'function'
                    || typeof THREE.CanvasTexture !== 'function') return null;
            const canvas = documentRef.createElement('canvas');
            canvas.width = 2048;
            canvas.height = 512;
            const context = typeof canvas.getContext === 'function'
                ? canvas.getContext('2d') : null;
            if (!context) return null;
            context.clearRect(0, 0, canvas.width, canvas.height);
            context.fillStyle = marking.strokeColor || '#111827';
            context.font = '800 300px Segoe UI, Arial, sans-serif';
            context.textAlign = 'center';
            context.textBaseline = 'middle';
            context.fillText(label, 1024, 256, 1960);
            return configureFloorMarkingTexture(
                new THREE.CanvasTexture(canvas)
            );
        }

        function floorPaintMaterial(marking, optionsValue) {
            const settings = optionsValue || {};
            const MaterialType = THREE.MeshBasicMaterial
                || THREE.MeshStandardMaterial;
            if (typeof MaterialType !== 'function') return null;
            const texture = settings.texture || null;
            const opacity = clamp(
                settings.opacity,
                0,
                1,
                clamp(marking.opacity, 0, 1, 1)
            );
            const material = new MaterialType({
                color: texture ? 0xffffff : markingColorNumber(
                    settings.color || marking.fillColor,
                    0xfacc15
                ),
                map: texture || undefined,
                transparent: Boolean(texture) || opacity < 1,
                opacity: opacity,
                alphaTest: texture ? 0.01 : 0,
                depthWrite: !texture && opacity >= 0.999,
                depthTest: true,
                polygonOffset: true,
                polygonOffsetFactor: -2,
                polygonOffsetUnits: -2,
                side: THREE.DoubleSide,
                toneMapped: false,
            });
            material.alphaTest = texture ? 0.01 : 0;
            material.toneMapped = false;
            return material;
        }

        function addFloorPaintRectangle(
            rootObject,
            marking,
            width,
            depth,
            x,
            z,
            optionsValue
        ) {
            if (typeof THREE.BoxGeometry !== 'function'
                    || typeof THREE.Mesh !== 'function') return null;
            const material = floorPaintMaterial(marking, optionsValue);
            if (!material) return null;
            const mesh = new THREE.Mesh(
                new THREE.BoxGeometry(
                    Math.max(0.001, width),
                    0.0008,
                    Math.max(0.001, depth)
                ),
                material
            );
            mesh.position.set(finite(x, 0), 0, finite(z, 0));
            mesh.renderOrder = 6;
            rootObject.add(mesh);
            return mesh;
        }

        function addFloorPaintPlane(
            rootObject,
            marking,
            width,
            depth,
            texture,
            optionsValue
        ) {
            const GeometryType = THREE.PlaneGeometry || THREE.BoxGeometry;
            if (!texture || typeof GeometryType !== 'function'
                    || typeof THREE.Mesh !== 'function') return null;
            const material = floorPaintMaterial(marking, Object.assign(
                {},
                optionsValue || {},
                { texture: texture }
            ));
            if (!material) return null;
            const geometry = THREE.PlaneGeometry
                ? new GeometryType(width, depth)
                : new GeometryType(width, 0.0008, depth);
            const mesh = new THREE.Mesh(geometry, material);
            if (THREE.PlaneGeometry) {
                const halfSqrt = Math.sqrt(0.5);
                setQuaternion(mesh.quaternion, {
                    x: -halfSqrt,
                    y: 0,
                    z: 0,
                    w: halfSqrt,
                });
            }
            mesh.renderOrder = 6;
            rootObject.add(mesh);
            return mesh;
        }

        function addFloorPaintArrow(rootObject, marking, width, depth) {
            if (typeof THREE.Shape !== 'function'
                    || typeof THREE.ShapeGeometry !== 'function'
                    || typeof THREE.Mesh !== 'function') return false;
            const halfWidth = width / 2;
            const halfDepth = depth / 2;
            const shaftHalfWidth = width * 0.19;
            const shoulderZ = depth * 0.06;
            const shape = new THREE.Shape();
            shape.moveTo(0, -halfDepth);
            shape.lineTo(halfWidth, -shoulderZ);
            shape.lineTo(shaftHalfWidth, -shoulderZ);
            shape.lineTo(shaftHalfWidth, halfDepth);
            shape.lineTo(-shaftHalfWidth, halfDepth);
            shape.lineTo(-shaftHalfWidth, -shoulderZ);
            shape.lineTo(-halfWidth, -shoulderZ);
            shape.closePath();
            const material = floorPaintMaterial(marking, {
                color: marking.fillColor,
            });
            if (!material) return false;
            const mesh = new THREE.Mesh(
                new THREE.ShapeGeometry(shape),
                material
            );
            const halfSqrt = Math.sqrt(0.5);
            setQuaternion(mesh.quaternion, {
                x: -halfSqrt,
                y: 0,
                z: 0,
                w: halfSqrt,
            });
            mesh.renderOrder = 6;
            rootObject.add(mesh);
            return true;
        }

        function buildFloorMarkingVisual(rootObject, marking, width, depth) {
            const type = marking.markingType || 'solid_line';
            const opacity = clamp(marking.opacity, 0, 1, 1);
            if (type === 'direction_arrow') {
                if (!addFloorPaintArrow(rootObject, marking, width, depth)) {
                    addFloorPaintPlane(
                        rootObject,
                        marking,
                        width,
                        depth,
                        floorMarkingTexture(marking),
                        { opacity: opacity }
                    );
                }
                return;
            }
            if (type === 'dashed_line') {
                const dash = Math.min(
                    depth,
                    Math.max(width * 1.6, depth / 7)
                );
                const gap = Math.max(width, dash * 0.65);
                let center = -depth / 2 + dash / 2;
                while (center <= depth / 2 - dash / 2 + 0.000001) {
                    addFloorPaintRectangle(
                        rootObject,
                        marking,
                        width,
                        dash,
                        0,
                        center,
                        { color: marking.fillColor, opacity: opacity }
                    );
                    center += dash + gap;
                }
                return;
            }
            if (type === 'crosswalk') {
                const count = 6;
                const stripeDepth = depth / (count * 1.8);
                for (let index = 0; index < count; index += 1) {
                    addFloorPaintRectangle(
                        rootObject,
                        marking,
                        width,
                        stripeDepth,
                        0,
                        -depth / 2 + (index + 0.4) * depth / count,
                        { color: marking.fillColor, opacity: opacity }
                    );
                }
                return;
            }
            if (type === 'hazard_stripe') {
                addFloorPaintPlane(
                    rootObject,
                    marking,
                    width,
                    depth,
                    floorMarkingTexture(marking),
                    { opacity: opacity }
                );
                return;
            }
            if (type === 'keep_clear' || type === 'parking_box') {
                const border = Math.max(
                    0.02,
                    Math.min(0.12, Math.min(width, depth) * 0.045)
                );
                addFloorPaintRectangle(
                    rootObject,
                    marking,
                    width,
                    depth,
                    0,
                    0,
                    {
                        color: marking.fillColor,
                        opacity: opacity * (type === 'keep_clear' ? 0.08 : 0.05),
                    }
                );
                addFloorPaintRectangle(
                    rootObject, marking, width, border,
                    0, -depth / 2 + border / 2,
                    { color: marking.fillColor, opacity: opacity }
                );
                addFloorPaintRectangle(
                    rootObject, marking, width, border,
                    0, depth / 2 - border / 2,
                    { color: marking.fillColor, opacity: opacity }
                );
                addFloorPaintRectangle(
                    rootObject, marking, border, depth,
                    -width / 2 + border / 2, 0,
                    { color: marking.fillColor, opacity: opacity }
                );
                addFloorPaintRectangle(
                    rootObject, marking, border, depth,
                    width / 2 - border / 2, 0,
                    { color: marking.fillColor, opacity: opacity }
                );
                addFloorPaintPlane(
                    rootObject,
                    marking,
                    width * 0.82,
                    Math.min(depth * 0.34, width * 0.22),
                    floorMarkingTextTexture(
                        marking,
                        marking.text || (type === 'keep_clear'
                            ? 'KEEP CLEAR' : 'PARKING')
                    ),
                    { opacity: opacity }
                );
                return;
            }
            if (type === 'floor_text') {
                addFloorPaintPlane(
                    rootObject,
                    marking,
                    width,
                    depth,
                    floorMarkingTextTexture(marking, marking.text),
                    { opacity: opacity }
                );
                return;
            }
            addFloorPaintRectangle(
                rootObject,
                marking,
                width,
                depth,
                0,
                0,
                { color: marking.fillColor, opacity: opacity }
            );
        }

        function renderFloorMarkings() {
            if (!state.modelRoot || typeof THREE.Mesh !== 'function') return 0;
            const layout = state.currentInput && state.currentInput.layout || {};
            const markings = Array.isArray(layout.floorMarkings)
                ? layout.floorMarkings.slice() : [];
            markings.sort(function (left, right) {
                return String(left && left.markingId || '').localeCompare(
                    String(right && right.markingId || '')
                );
            });
            markings.forEach(function (marking, index) {
                if (!marking || !marking.transform
                        || !marking.transform.position) return;
                const width = Math.max(0.01, finite(marking.width, 1));
                const depth = Math.max(0.01, finite(marking.depth, 1));
                const RootType = THREE.Group || THREE.Object3D;
                if (typeof RootType !== 'function') return;
                const object = new RootType();
                object.name = 'FacilityFloorMarking:'
                    + String(marking.markingId || index);
                buildFloorMarkingVisual(object, marking, width, depth);
                if (!object.children || !object.children.length) return;
                const position = marking.transform.position;
                if (object.position && typeof object.position.set === 'function') {
                    object.position.set(
                        finite(position.x, 0),
                        finite(position.y, 0) + 0.003 + index * 0.000001,
                        finite(position.z, 0)
                    );
                }
                const radians = finite(
                    marking.transform.rotationDegrees,
                    0
                ) * Math.PI / 180;
                setQuaternion(object.quaternion, {
                    x: 0,
                    y: Math.sin(radians / 2),
                    z: 0,
                    w: Math.cos(radians / 2),
                });
                object.renderOrder = 6;
                object.userData = Object.assign({}, object.userData, {
                    facilityFloorMarking: true,
                    markingId: marking.markingId,
                    markingType: marking.markingType,
                    semanticRole: marking.semanticRole,
                });
                state.modelRoot.add(object);
                state.floorMarkingObjects.push(object);
            });
            return state.floorMarkingObjects.length;
        }

        function facilityAisleExtension(route) {
            const extensions = route && route.extensions;
            const aisle = extensions && extensions.facilityAisle;
            return aisle && typeof aisle === 'object' ? aisle : null;
        }

        function routeCenterline(route) {
            const points = Array.isArray(route && route.centerline)
                ? route.centerline : [];
            return points.filter(function (point) {
                return point && Number.isFinite(Number(point.x))
                    && Number.isFinite(Number(point.z));
            }).map(function (point) {
                return {
                    x: finite(point.x, 0),
                    y: finite(point.y, 0),
                    z: finite(point.z, 0),
                };
            });
        }

        function renderFacilityAisles() {
            if (!state.modelRoot || typeof THREE.Mesh !== 'function') return 0;
            const layout = state.currentInput && state.currentInput.layout || {};
            const routes = Array.isArray(layout.routes) ? layout.routes.slice() : [];
            routes.sort(function (left, right) {
                return String(left && left.routeId || '').localeCompare(
                    String(right && right.routeId || '')
                );
            });
            routes.forEach(function (route, routeIndex) {
                const aisle = facilityAisleExtension(route);
                const points = routeCenterline(route);
                if (!aisle || points.length < 2) return;
                const RootType = THREE.Group || THREE.Object3D;
                if (typeof RootType !== 'function') return;
                const object = new RootType();
                object.name = 'FacilityAisle:'
                    + String(route.routeId || routeIndex);
                const width = Math.max(0.05, finite(route.corridorWidth, 1));
                const marking = {
                    fillColor: aisle.color || '#d9a514',
                    opacity: 0.52,
                };
                for (let index = 1; index < points.length; index += 1) {
                    const start = points[index - 1];
                    const end = points[index];
                    const dx = end.x - start.x;
                    const dz = end.z - start.z;
                    const length = Math.hypot(dx, dz);
                    if (length <= 0.000001) continue;
                    const segment = addFloorPaintRectangle(
                        object,
                        marking,
                        length,
                        width,
                        (start.x + end.x) / 2,
                        (start.z + end.z) / 2,
                        { opacity: 0.52 }
                    );
                    if (!segment) continue;
                    segment.position.y = (start.y + end.y) / 2
                        + 0.0015 + routeIndex * 0.000001;
                    const radians = -Math.atan2(dz, dx);
                    setQuaternion(segment.quaternion, {
                        x: 0,
                        y: Math.sin(radians / 2),
                        z: 0,
                        w: Math.cos(radians / 2),
                    });
                    segment.renderOrder = 4;
                }
                if (!object.children || !object.children.length) return;
                object.userData = Object.assign({}, object.userData, {
                    facilityAisle: true,
                    routeId: route.routeId,
                    aisleKind: aisle.aisleKind,
                    direction: aisle.direction,
                });
                state.modelRoot.add(object);
                state.routeObjects.push(object);
            });
            return state.routeObjects.length;
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

        function disposeProposalObjects() {
            if (!state.proposalRoot) return;
            if (state.proposalRoot.parent
                    && typeof state.proposalRoot.parent.remove === 'function') {
                state.proposalRoot.parent.remove(state.proposalRoot);
            }
            disposeObjectGraphs([state.proposalRoot]);
            state.proposalRoot = null;
        }

        function normalizeProposalInput(value) {
            if (!value || value.active !== true) return null;
            function identifiers(name) {
                return Array.from(new Set(
                    (Array.isArray(value[name]) ? value[name] : []).filter(
                        function (identifier) {
                            return typeof identifier === 'string'
                                && identifier;
                        }
                    )
                )).sort();
            }
            function placements(name) {
                return (Array.isArray(value[name]) ? value[name] : []).map(
                    normalizePlacement
                ).sort(function (left, right) {
                    return left.placementId.localeCompare(right.placementId);
                });
            }
            return {
                active: true,
                newPlacementIds: identifiers('newPlacementIds'),
                movedPlacementIds: identifiers('movedPlacementIds'),
                removedPlacementIds: identifiers('removedPlacementIds'),
                beforePlacements: placements('beforePlacements'),
                proposedPlacements: placements('proposedPlacements'),
            };
        }

        function boundsForPlacement(placement) {
            const group = state.baseGroups.get(
                placement.assetId + '|'
                + placement.assetDefinitionRevision
            );
            if (group) return group.bounds;
            const catalog = state.currentInput
                && state.currentInput.assetCatalog;
            const index = buildCatalogIndex(catalog);
            const exactKey = placement.assetId + '|'
                + placement.assetDefinitionRevision;
            return extractBounds(index.exact.get(exactKey))
                || extractBounds(index.byAsset.get(placement.assetId))
                || cloneBounds(DEFAULT_BOUNDS);
        }

        function styleProposalObject(object, role) {
            const colors = {
                before: 0xd97706,
                removed: 0xdc2626,
                moved: 0x8b5cf6,
                new: 0x0ea5e9,
            };
            const opacity = role === 'before' || role === 'removed'
                ? 0.3 : 0.38;
            const visit = function (candidate) {
                const materials = Array.isArray(candidate && candidate.material)
                    ? candidate.material : [candidate && candidate.material];
                materials.filter(Boolean).forEach(function (material) {
                    material.transparent = true;
                    material.opacity = opacity;
                    material.depthWrite = false;
                    material.wireframe = true;
                    if (material.color
                            && typeof material.color.setHex === 'function') {
                        material.color.setHex(colors[role] || 0x8b5cf6);
                    }
                    material.needsUpdate = true;
                });
            };
            if (typeof object.traverse === 'function') object.traverse(visit);
            else visit(object);
        }

        function proposalObject(placement, role) {
            const prototype = makeFallbackPrototype(
                boundsForPlacement(placement)
            );
            const object = prototype.object;
            styleProposalObject(object, role);
            applyPlacementTransform(object, placement);
            object.name = 'FacilityProposalPreview:'
                + role + ':' + placement.placementId;
            object.userData = object.userData || {};
            object.userData.facilityProposalPreview = role;
            object.userData.facilityProposalPlacementId =
                placement.placementId;
            return object;
        }

        function renderProposalObjects() {
            disposeProposalObjects();
            const proposal = state.proposalInput;
            if (!proposal || !state.mounted || !state.modelRoot
                    || state.degraded) {
                invalidate();
                return false;
            }
            const removed = new Set(proposal.removedPlacementIds);
            const added = new Set(proposal.newPlacementIds);
            const rootObject = createContainer();
            rootObject.name = 'FacilityProposalPreviewRoot';
            rootObject.userData = rootObject.userData || {};
            rootObject.userData.facilityProposalPreviewRoot = true;
            proposal.beforePlacements.forEach(function (placement) {
                rootObject.add(proposalObject(
                    placement,
                    removed.has(placement.placementId)
                        ? 'removed' : 'before'
                ));
            });
            proposal.proposedPlacements.forEach(function (placement) {
                const role = added.has(placement.placementId)
                    ? 'new' : 'moved';
                rootObject.add(proposalObject(placement, role));
            });
            state.modelRoot.add(rootObject);
            state.proposalRoot = rootObject;
            invalidate();
            return true;
        }

        function setProposalPreview(value) {
            state.proposalInput = normalizeProposalInput(value);
            const rendered = renderProposalObjects();
            state.worldBounds = computeWorldBounds();
            syncEnvironment();
            return state.proposalInput ? rendered : true;
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
            if (state.walkthrough.active) {
                exitWalkthrough('renderer_teardown');
            }
            if (state.drone.active) {
                exitDrone('renderer_teardown');
            }
            abortLoading();
            if (state.frameId !== null && cancelFrame) cancelFrame(state.frameId);
            state.frameId = null;
            state.needsRender = false;
            const timerHost = options.window || root;
            if (state.navigationRestoreTimer !== null
                    && timerHost
                    && typeof timerHost.clearTimeout === 'function') {
                timerHost.clearTimeout(state.navigationRestoreTimer);
            }
            state.navigationRestoreTimer = null;

            if (state.resizeObserver) {
                state.resizeObserver.disconnect();
                state.resizeObserver = null;
            }
            state.resizeObserverActive = false;
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
            removeListener(
                state.controls,
                'start',
                state.controlStartHandler
            );
            removeListener(
                state.controls,
                'end',
                state.controlEndHandler
            );
            removeListener(
                state.walkthroughControls,
                'change',
                state.walkthroughChangeHandler
            );
            removeListener(
                state.walkthroughControls,
                'lock',
                state.walkthroughLockHandler
            );
            removeListener(
                state.walkthroughControls,
                'unlock',
                state.walkthroughUnlockHandler
            );
            removeListener(
                state.walkthroughControls,
                'error',
                state.walkthroughErrorHandler
            );
            removeListener(
                documentObject,
                'keydown',
                state.walkthroughKeyDownHandler,
                false
            );
            removeListener(
                documentObject,
                'keyup',
                state.walkthroughKeyUpHandler,
                false
            );
            removeListener(
                documentObject,
                'visibilitychange',
                state.walkthroughVisibilityHandler,
                false
            );
            removeListener(
                options.window || root,
                'blur',
                state.walkthroughBlurHandler,
                false
            );
            state.contextLostHandler = null;
            state.contextRestoredHandler = null;
            state.controlChangeHandler = null;
            state.controlStartHandler = null;
            state.controlEndHandler = null;
            state.navigationInteracting = false;
            state.walkthroughChangeHandler = null;
            state.walkthroughLockHandler = null;
            state.walkthroughUnlockHandler = null;
            state.walkthroughErrorHandler = null;
            state.walkthroughKeyDownHandler = null;
            state.walkthroughKeyUpHandler = null;
            state.walkthroughBlurHandler = null;
            state.walkthroughVisibilityHandler = null;
            state.pointerHandler = null;
            state.resizeHandler = null;

            clearModel();
            clearEnvironmentObjects();
            disposeSceneBackground();
            if (typeof state.themeCleanup === 'function') {
                state.themeCleanup();
            }
            state.themeCleanup = null;
            if (state.controls && typeof state.controls.dispose === 'function') {
                state.controls.dispose();
            }
            if (state.walkthroughControls
                    && typeof state.walkthroughControls.dispose === 'function') {
                state.walkthroughControls.dispose();
            }
            const renderer = state.renderer;
            removeCanvas();
            if (renderer) {
                if (state.rendererFromPool && options.rendererPool
                        && typeof options.rendererPool.release === 'function') {
                    options.rendererPool.release(renderer, {
                        discard: state.contextLost,
                    });
                } else {
                    destroyRenderer(renderer);
                }
            }

            state.renderer = null;
            state.rendererFromPool = false;
            state.scene = null;
            state.ambientLight = null;
            state.directionalLight = null;
            state.environmentRoot = null;
            state.floorObject = null;
            state.gridObjects = [];
            state.axisObjects = [];
            state.environmentSignature = null;
            state.environmentDiagnostics = null;
            state.ownsBackground = false;
            state.modelRoot = null;
            state.camera = null;
            state.controls = null;
            state.walkthroughControls = null;
            state.raycaster = null;
            state.canvas = null;
            state.host = null;
            state.mounted = false;
            state.suspended = false;
            state.degraded = false;
            state.contextLost = false;
            state.listenerCount = 0;
            state.teardownCount += 1;
            state.disposed = Boolean(finalDispose);
            state.reloadOnResume = false;
            if (finalDispose) {
                state.currentInput = null;
                state.ghostInput = null;
                state.proposalInput = null;
                state.placements = [];
                state.baseGroups.clear();
                state.selectedIds.clear();
                state.loadTrace = [];
                state.warnings = [];
                state.lastFit = null;
                state.worldBounds = null;
            }
            notifyStatus(finalDispose ? 'disposed' : 'unmounted', null);
        }

        function mount(host) {
            if (!host || typeof host.appendChild !== 'function') {
                throw new TypeError('A DOM-like facility renderer host is required.');
            }
            if (state.mounted && state.host === host) {
                if (state.suspended) resume();
                return api;
            }
            const replayInput = state.currentInput ? {
                layout: state.currentInput.layout,
                assetCatalog: state.currentInput.assetCatalog,
            } : null;
            const replayGhost = state.ghostInput;
            if (state.mounted || state.renderer || state.canvas) teardownMount(false);

            state.disposed = false;
            state.host = host;
            state.mounted = true;
            state.suspended = false;
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
                const rendererFactory = function (context) {
                    return typeof options.rendererFactory === 'function'
                        ? options.rendererFactory(context)
                        : new THREE.WebGLRenderer({
                            antialias: true,
                            alpha: true,
                            powerPreference: 'high-performance',
                        });
                };
                if (options.rendererPool
                        && typeof options.rendererPool.acquire === 'function') {
                    state.renderer = options.rendererPool.acquire(
                        rendererFactory,
                        { THREE: THREE, host: host }
                    );
                    state.rendererFromPool = true;
                } else {
                    state.renderer = rendererFactory({ THREE: THREE, host: host });
                    state.rendererFromPool = false;
                }
                if (typeof options.onRendererReady === 'function') {
                    options.onRendererReady(state.renderer);
                }
                state.canvas = state.renderer.domElement;
                appendCanvas(host, state.canvas);
                if (typeof state.renderer.setPixelRatio === 'function') {
                    const ratio = finite(
                        options.pixelRatio,
                        finite(root && root.devicePixelRatio, 1)
                    );
                    state.displayPixelRatio = Math.max(1, Math.min(ratio, 2));
                    state.interactivePixelRatio = Math.min(
                        state.displayPixelRatio,
                        navigationSettings.interactivePixelRatio
                    );
                    state.currentPixelRatio = state.displayPixelRatio;
                    state.renderer.setPixelRatio(state.displayPixelRatio);
                }
                if (THREE.SRGBColorSpace !== undefined) {
                    state.renderer.outputColorSpace = THREE.SRGBColorSpace;
                }
                if (THREE.ACESFilmicToneMapping !== undefined) {
                    state.renderer.toneMapping = THREE.ACESFilmicToneMapping;
                }
                makeSceneGraph();
                attachThemeListener();
                attachRuntime();
                applyVisualSettingsRuntime();
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
                } else {
                    renderProposalObjects();
                    if (replayGhost) setGhostPlacement(replayGhost);
                }
            } catch (error) {
                reportError('webgl_initialization_failed', error);
                if (state.rendererFromPool && options.rendererPool
                        && typeof options.rendererPool.release === 'function') {
                    options.rendererPool.release(state.renderer, { discard: true });
                } else {
                    destroyRenderer(state.renderer);
                }
                removeCanvas();
                state.renderer = null;
                state.rendererFromPool = false;
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

        function suspend() {
            if (!state.mounted || state.suspended || state.disposed) return false;
            if (state.walkthrough.active) {
                exitWalkthrough('renderer_suspended');
            }
            if (state.drone.active) {
                exitDrone('renderer_suspended');
            }
            state.reloadOnResume = state.pendingLoads > 0;
            if (state.reloadOnResume) abortLoading();
            state.suspended = true;
            state.mountGeneration += 1;
            if (state.frameId !== null && cancelFrame) cancelFrame(state.frameId);
            state.frameId = null;
            state.needsRender = false;
            if (state.resizeObserver) state.resizeObserver.disconnect();
            state.resizeObserverActive = false;
            notifyStatus('suspended', null);
            return true;
        }

        function resume() {
            if (!state.mounted || !state.suspended || state.disposed) return false;
            state.suspended = false;
            state.mountGeneration += 1;
            observeResize();
            if (state.degraded) {
                notifyStatus('degraded', state.statusReason);
                return true;
            }
            notifyStatus('ready', null);
            resize();
            if (state.reloadOnResume && state.currentInput) {
                state.reloadOnResume = false;
                Promise.resolve(setScene(state.currentInput)).catch(function (error) {
                    reportError('scene_resume_failed', error);
                });
            } else {
                state.reloadOnResume = false;
                invalidate();
            }
            return true;
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
                    color: neutralAssetColor,
                    transparent: false,
                    opacity: 1,
                    roughness: DEFAULT_ASSET_ROUGHNESS,
                    metalness: DEFAULT_ASSET_METALNESS,
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
            applyVisualSettingsToObject(prototype.object);
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
                prototypeMatrices: prototypeMeshes.map(function (mesh) {
                    return mesh.matrix;
                }),
                mappings: mappings,
                container: container,
                prototypeObject: prototype.object,
                pickObjects: pickObjects,
            };
            state.renderGroups.set(record.baseKey, record);
            state.pickObjects = state.pickObjects.concat(pickObjects);
            if (state.drone.active) applyCurrentDroneRecordWindow(record);
            else applySelection();
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

        function sourceToCanonicalValues(result, group) {
            const candidates = [
                result && result.sourceToCanonical,
                result && result.coordinateFrame
                    && result.coordinateFrame.sourceToCanonical,
                group && group.catalog && group.catalog.definition
                    && group.catalog.definition.coordinateFrame
                    && group.catalog.definition.coordinateFrame
                        .sourceToCanonical,
                group && group.catalog && group.catalog.assetDefinition
                    && group.catalog.assetDefinition.coordinateFrame
                    && group.catalog.assetDefinition.coordinateFrame
                        .sourceToCanonical,
            ];
            for (let index = 0; index < candidates.length; index += 1) {
                const values = candidates[index];
                if (Array.isArray(values) && values.length === 16
                        && values.every(function (value) {
                            return Number.isFinite(Number(value));
                        })) {
                    return values.map(Number);
                }
            }
            return null;
        }

        function canonicalPrototypeObject(object, matrixValues) {
            if (!matrixValues) return object;
            const wrapper = createContainer();
            wrapper.name = 'FacilityCanonicalPrototype';
            wrapper.userData = wrapper.userData || {};
            wrapper.userData.sourceToCanonical = matrixValues.slice();

            if (typeof THREE.Matrix4 === 'function'
                    && typeof object.applyMatrix4 === 'function') {
                const matrix = new THREE.Matrix4();
                if (typeof matrix.fromArray === 'function') {
                    matrix.fromArray(matrixValues);
                    object.applyMatrix4(matrix);
                }
            } else if (object.position
                    && typeof object.position.set === 'function') {
                object.position.set(
                    finite(matrixValues[12], 0),
                    finite(matrixValues[13], 0),
                    finite(matrixValues[14], 0)
                );
            }
            wrapper.add(object);
            if (typeof wrapper.updateMatrixWorld === 'function') {
                wrapper.updateMatrixWorld(true);
            }
            return wrapper;
        }

        async function normalizeVisualResult(result, stage, group) {
            if (stage === 'footprint' && (!result || typeof result !== 'object')) {
                return makeFallbackPrototype(group.bounds);
            }
            const canonicalMatrix = sourceToCanonicalValues(result, group);
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
            const canonicalObject = canonicalPrototypeObject(
                object,
                canonicalMatrix
            );
            applyAssetMaterialPolicy(canonicalObject);
            return {
                object: canonicalObject,
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

        function visualByteSize(value) {
            if (!value || typeof value !== 'object') return 0;
            const candidates = [
                value.byteSize,
                value.contentLength,
                value.sizeBytes,
                value.metadata && value.metadata.byteSize,
            ];
            for (let index = 0; index < candidates.length; index += 1) {
                const size = Number(candidates[index]);
                if (Number.isFinite(size) && size > 0) return size;
            }
            return 0;
        }

        function shouldDeferOverview(value) {
            return preferOverviewForLargeLayouts
                && state.placements.length >= largeLayoutDetailThreshold
                && visualByteSize(value) > largeLayoutHeavyVisualBytes;
        }

        function projectedGroupPixelSize(group) {
            if (!group || !state.camera || !state.camera.position) return 0;
            const bounds = cloneBounds(group.bounds || DEFAULT_BOUNDS);
            const size = Math.max(
                bounds.maximum.x - bounds.minimum.x,
                bounds.maximum.y - bounds.minimum.y,
                bounds.maximum.z - bounds.minimum.z,
                0.01
            );
            const viewportHeight = Math.max(
                1,
                finite(state.host && state.host.clientHeight, 1)
            );
            const fov = clamp(state.camera.fov, 1, 179, 45) * Math.PI / 180;
            const focalLength = viewportHeight / (2 * Math.tan(fov / 2));
            let direction = null;
            if (typeof state.camera.getWorldDirection === 'function'
                    && typeof THREE.Vector3 === 'function') {
                direction = new THREE.Vector3();
                state.camera.getWorldDirection(direction);
            }
            return group.placements.reduce(function (maximum, placement) {
                const position = placement.transform.position;
                const dx = position.x - state.camera.position.x;
                const dy = position.y - state.camera.position.y;
                const dz = position.z - state.camera.position.z;
                if (direction && dx * direction.x + dy * direction.y
                        + dz * direction.z <= 0) return maximum;
                const distance = Math.max(0.01, Math.hypot(dx, dy, dz));
                const scale = Math.max(
                    0.001,
                    finite(placement.transform.scale, 1)
                );
                return Math.max(
                    maximum,
                    size * scale * focalLength / distance
                );
            }, 0);
        }

        async function loadDeferredGroup(group, reason) {
            if (!group || !group.deferredVisual || group.deferredLoading
                    || !state.mounted) return false;
            const generation = state.sceneGeneration;
            const descriptor = group.deferredVisual;
            group.deferredLoading = true;
            state.pendingLoads += 1;
            traceLoad(group, 'overview', 'started', reason);
            try {
                const prototype = await normalizeVisualResult(
                    descriptor,
                    'overview',
                    group
                );
                if (generation !== state.sceneGeneration || !state.mounted) {
                    disposeUnadoptedVisual(prototype);
                    return false;
                }
                if (!prototype) {
                    traceLoad(group, 'overview', 'skipped', reason);
                    return false;
                }
                group.bounds = prototype.bounds || group.bounds;
                group.deferredVisual = null;
                buildRenderedGroup(group, prototype, 'overview');
                traceLoad(group, 'overview', 'resolved', reason);
                return true;
            } catch (error) {
                traceLoad(
                    group,
                    'overview',
                    'failed',
                    error && error.message ? error.message : String(error)
                );
                warning(
                    'deferred_asset_stage_failed',
                    'Deferred asset visual failed; its footprint remains available.',
                    group.assetId
                );
                return false;
            } finally {
                group.deferredLoading = false;
                state.pendingLoads = Math.max(0, state.pendingLoads - 1);
            }
        }

        function queueDeferredGroup(group, reason) {
            if (!group || !group.deferredVisual || group.deferredLoading
                    || group.deferredQueued) return false;
            group.deferredQueued = true;
            state.deferredLoadQueue = state.deferredLoadQueue.then(
                function () {
                    group.deferredQueued = false;
                    return loadDeferredGroup(group, reason);
                }
            ).catch(function (error) {
                group.deferredQueued = false;
                reportError('deferred_asset_queue_failed', error);
                return false;
            });
            return true;
        }

        function loadDeferredVisibleGroups() {
            if (!state.mounted || state.suspended || state.degraded) return 0;
            const candidates = Array.from(state.baseGroups.values())
                .filter(function (group) {
                    return group.deferredVisual
                        && !group.deferredLoading
                        && !group.deferredQueued;
                })
                .map(function (group) {
                    return {
                        group: group,
                        pixels: projectedGroupPixelSize(group),
                    };
                })
                .filter(function (item) {
                    return item.pixels >= deferredVisualPixelThreshold;
                })
                .sort(function (left, right) {
                    if (right.pixels !== left.pixels) {
                        return right.pixels - left.pixels;
                    }
                    return left.group.assetId.localeCompare(
                        right.group.assetId
                    );
                });
            let queued = 0;
            candidates.slice(0, deferredLoadsPerInteraction).forEach(
                function (item) {
                    if (queueDeferredGroup(
                        item.group,
                        'deferred_visible_after_navigation'
                    )) queued += 1;
                }
            );
            return queued;
        }

        async function resolveGroup(group, generation, signal) {
            let manifest = null;
            let overviewResolved = false;
            const retainOverview = preferOverviewForLargeLayouts
                && state.placements.length >= largeLayoutDetailThreshold;
            for (let index = 0; index < RESOLUTION_STAGES.length; index += 1) {
                const stage = RESOLUTION_STAGES[index];
                if (generation !== state.sceneGeneration || !state.mounted) {
                    return false;
                }
                if (stage === 'detail' && retainOverview && overviewResolved) {
                    traceLoad(
                        group,
                        stage,
                        'skipped',
                        'large_layout_overview_lod'
                    );
                    continue;
                }
                if (stage === 'detail' && group.deferredVisual) {
                    traceLoad(
                        group,
                        stage,
                        'skipped',
                        'large_layout_heavy_visual_deferred'
                    );
                    continue;
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
                        if (stage === 'overview'
                                && shouldDeferOverview(result)) {
                            group.deferredVisual = result;
                            traceLoad(
                                group,
                                stage,
                                'skipped',
                                'large_layout_heavy_visual_deferred'
                            );
                            continue;
                        }
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
                            if (stage === 'overview') overviewResolved = true;
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
                        deferredVisual: null,
                        deferredLoading: false,
                        deferredQueued: false,
                    });
                }
                groups.get(key).placements.push(placement);
            });
            return { placements: placements, groups: groups };
        }

        async function setScene(input) {
            const value = input && typeof input === 'object' ? input : {};
            if (state.walkthrough.active) {
                exitWalkthrough('scene_changed');
            }
            if (state.drone.active) {
                exitDrone('scene_changed');
            }
            setWalkthroughContextFocus(null);
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
            syncEnvironment();

            if (!state.mounted || state.suspended
                    || !state.modelRoot || state.degraded) {
                if (state.suspended) state.reloadOnResume = true;
                if (!state.mounted) notifyStatus('unmounted', null);
                return getDiagnostics();
            }

            clearModel();
            renderFacilityAisles();
            renderFloorMarkings();
            Array.from(state.baseGroups.keys()).sort().forEach(function (key) {
                const group = state.baseGroups.get(key);
                buildRenderedGroup(
                    group,
                    makeFallbackPrototype(group.bounds),
                    'footprint'
                );
            });
            renderProposalObjects();
            renderGhostObject();
            state.worldBounds = computeWorldBounds();
            syncEnvironment();
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
                syncEnvironment();
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

        function computeWorldBounds(includeConfiguredBounds) {
            const configured = options.worldBounds;
            const hasConfigured = includeConfiguredBounds !== false
                && configured
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
            const reviewPlacements = state.proposalInput
                ? state.proposalInput.beforePlacements : [];
            const boundedPlacements = state.placements.concat(
                reviewPlacements
            );
            const floorMarkings = state.currentInput
                && state.currentInput.layout
                && Array.isArray(state.currentInput.layout.floorMarkings)
                ? state.currentInput.layout.floorMarkings : [];
            const routes = state.currentInput
                && state.currentInput.layout
                && Array.isArray(state.currentInput.layout.routes)
                ? state.currentInput.layout.routes : [];
            const aisleRoutes = routes.filter(function (route) {
                return Boolean(facilityAisleExtension(route));
            });
            if (!boundedPlacements.length && !floorMarkings.length
                    && !aisleRoutes.length) {
                return hasConfigured ? output : null;
            }
            boundedPlacements.forEach(function (placement) {
                const bounds = transformedBounds(
                    boundsForPlacement(placement),
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
            floorMarkings.forEach(function (marking) {
                const transform = marking && marking.transform || {};
                const position = transform.position || {};
                const width = Math.max(0.01, finite(marking && marking.width, 1));
                const depth = Math.max(0.01, finite(marking && marking.depth, 1));
                const radius = Math.hypot(width, depth) / 2;
                output.minimum.x = Math.min(
                    output.minimum.x,
                    finite(position.x, 0) - radius
                );
                output.maximum.x = Math.max(
                    output.maximum.x,
                    finite(position.x, 0) + radius
                );
                output.minimum.y = Math.min(
                    output.minimum.y,
                    finite(position.y, 0)
                );
                output.maximum.y = Math.max(
                    output.maximum.y,
                    finite(position.y, 0) + 0.01
                );
                output.minimum.z = Math.min(
                    output.minimum.z,
                    finite(position.z, 0) - radius
                );
                output.maximum.z = Math.max(
                    output.maximum.z,
                    finite(position.z, 0) + radius
                );
            });
            aisleRoutes.forEach(function (route) {
                const radius = Math.max(
                    0.025,
                    finite(route && route.corridorWidth, 1) / 2
                );
                routeCenterline(route).forEach(function (point) {
                    output.minimum.x = Math.min(output.minimum.x, point.x - radius);
                    output.maximum.x = Math.max(output.maximum.x, point.x + radius);
                    output.minimum.y = Math.min(output.minimum.y, point.y);
                    output.maximum.y = Math.max(output.maximum.y, point.y + 0.01);
                    output.minimum.z = Math.min(output.minimum.z, point.z - radius);
                    output.maximum.z = Math.max(output.maximum.z, point.z + radius);
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

        function fitBounds(bounds, mode, targetOverride) {
            if (!state.camera || !state.modelRoot || !bounds
                    || state.degraded) return false;
            const beforeRoot = objectTransform(state.modelRoot);
            const center = {
                x: (bounds.minimum.x + bounds.maximum.x) / 2,
                y: (bounds.minimum.y + bounds.maximum.y) / 2,
                z: (bounds.minimum.z + bounds.maximum.z) / 2,
            };
            const fitTarget = targetOverride || (options.worldBounds
                && Number.isFinite(Number(options.worldBounds.floorY))
                ? {
                    x: center.x,
                    y: Number(options.worldBounds.floorY),
                    z: center.z,
                }
                : center);
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
                mode: mode,
                center: center,
                size: size,
                rootUnchanged: JSON.stringify(beforeRoot)
                    === JSON.stringify(afterRoot),
            };
            invalidate();
            return state.lastFit.rootUnchanged;
        }

        function fitFacility() {
            return fitBounds(
                configuredEnvironmentBounds() || state.worldBounds,
                'facility'
            );
        }

        function fitLayout() {
            return fitBounds(
                computeWorldBounds(false)
                    || configuredEnvironmentBounds()
                    || state.worldBounds,
                'layout'
            );
        }

        function fit() {
            return fitFacility();
        }

        function setNavigationMode(mode) {
            if (mode !== 'orbit' && mode !== 'pan') {
                throw new TypeError('3D navigation mode must be orbit or pan');
            }
            if (state.walkthrough.active) {
                exitWalkthrough('navigation_changed');
            }
            if (state.drone.active) {
                exitDrone('navigation_changed');
            }
            state.navigationMode = mode;
            if (!state.controls) return true;
            const mouse = THREE && THREE.MOUSE || {
                ROTATE: 0,
                DOLLY: 1,
                PAN: 2,
            };
            state.controls.enableRotate = true;
            state.controls.enablePan = true;
            state.controls.enableZoom = true;
            state.controls.mouseButtons = state.controls.mouseButtons || {};
            state.controls.mouseButtons.LEFT = mode === 'pan'
                ? mouse.PAN : mouse.ROTATE;
            state.controls.mouseButtons.MIDDLE = mouse.DOLLY;
            state.controls.mouseButtons.RIGHT = mode === 'pan'
                ? mouse.ROTATE : mouse.PAN;
            if (typeof state.controls.update === 'function') {
                state.controls.update();
            }
            invalidate();
            return true;
        }

        function zoomBy(factor) {
            const zoomFactor = Number(factor);
            if (!state.camera || !Number.isFinite(zoomFactor)
                    || zoomFactor <= 0 || state.degraded) return false;
            if (state.camera.isOrthographicCamera) {
                state.camera.zoom = Math.max(
                    0.05,
                    Math.min(50, finite(state.camera.zoom, 1) * zoomFactor)
                );
            } else {
                const target = state.controls && state.controls.target
                    ? state.controls.target : { x: 0, y: 0, z: 0 };
                const offset = {
                    x: finite(state.camera.position.x, 0) - finite(target.x, 0),
                    y: finite(state.camera.position.y, 0) - finite(target.y, 0),
                    z: finite(state.camera.position.z, 0) - finite(target.z, 0),
                };
                const currentDistance = Math.sqrt(
                    offset.x * offset.x
                    + offset.y * offset.y
                    + offset.z * offset.z
                );
                if (!Number.isFinite(currentDistance) || currentDistance < 0.001) {
                    return false;
                }
                const minimum = Math.max(
                    0.05,
                    finite(state.controls && state.controls.minDistance, 0.05)
                );
                const maximum = Math.max(
                    minimum,
                    finite(state.controls && state.controls.maxDistance, 100000)
                );
                const nextDistance = Math.max(
                    minimum,
                    Math.min(maximum, currentDistance / zoomFactor)
                );
                const scale = nextDistance / currentDistance;
                setVector(state.camera.position, {
                    x: finite(target.x, 0) + offset.x * scale,
                    y: finite(target.y, 0) + offset.y * scale,
                    z: finite(target.z, 0) + offset.z * scale,
                });
            }
            if (typeof state.camera.updateProjectionMatrix === 'function') {
                state.camera.updateProjectionMatrix();
            }
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld(true);
            }
            if (state.controls && typeof state.controls.update === 'function') {
                state.controls.update();
            }
            invalidate();
            return true;
        }

        function setGridVisible(visible) {
            const next = visible !== false;
            if (state.gridVisible === next) return true;
            state.gridVisible = next;
            state.environmentSignature = null;
            syncEnvironment();
            return true;
        }

        function setEnvironmentSettings(settings) {
            const source = settings && typeof settings === 'object' ? settings : {};
            if (source.worldBounds && typeof source.worldBounds === 'object') {
                options.worldBounds = Object.assign({}, source.worldBounds);
            }
            if (Number.isFinite(Number(source.floorGridSpacing))) {
                options.floorGridSpacing = Number(source.floorGridSpacing);
            }
            if (Number.isFinite(Number(source.floorMajorGridSpacing))) {
                options.floorMajorGridSpacing = Number(
                    source.floorMajorGridSpacing
                );
            }
            state.environmentSignature = null;
            syncEnvironment();
            invalidate();
            return true;
        }

        function isometricView() {
            const bounds = configuredEnvironmentBounds() || state.worldBounds;
            if (!state.camera || !bounds || state.degraded) return false;
            const center = {
                x: (bounds.minimum.x + bounds.maximum.x) / 2,
                y: (bounds.minimum.y + bounds.maximum.y) / 2,
                z: (bounds.minimum.z + bounds.maximum.z) / 2,
            };
            const span = Math.max(
                bounds.maximum.x - bounds.minimum.x,
                bounds.maximum.y - bounds.minimum.y,
                bounds.maximum.z - bounds.minimum.z,
                1
            );
            setVector(state.camera.up, { x: 0, y: 1, z: 0 });
            if (state.controls && state.controls.target) {
                setVector(state.controls.target, center);
            }
            setVector(state.camera.position, {
                x: center.x + span,
                y: center.y + span * 0.82,
                z: center.z + span,
            });
            return fitBounds(bounds, 'isometric', center);
        }

        function elevationView(mode) {
            const bounds = configuredEnvironmentBounds() || state.worldBounds;
            if (!state.camera || !bounds || state.degraded) return false;
            const center = {
                x: (bounds.minimum.x + bounds.maximum.x) / 2,
                y: (bounds.minimum.y + bounds.maximum.y) / 2,
                z: (bounds.minimum.z + bounds.maximum.z) / 2,
            };
            const span = Math.max(
                bounds.maximum.x - bounds.minimum.x,
                bounds.maximum.y - bounds.minimum.y,
                bounds.maximum.z - bounds.minimum.z,
                1
            );
            setVector(state.camera.up, { x: 0, y: 1, z: 0 });
            if (state.controls && state.controls.target) {
                setVector(state.controls.target, center);
            }
            setVector(state.camera.position, mode === 'right' ? {
                x: center.x + span,
                y: center.y,
                z: center.z,
            } : {
                x: center.x,
                y: center.y,
                z: center.z + span,
            });
            return fitBounds(bounds, mode, center);
        }

        function frontView() {
            return elevationView('front');
        }

        function rightView() {
            return elevationView('right');
        }

        function topView() {
            const bounds = configuredEnvironmentBounds() || state.worldBounds;
            if (!state.camera || !state.modelRoot || !bounds
                    || state.degraded) return false;
            const beforeRoot = objectTransform(state.modelRoot);
            const floorY = options.worldBounds
                && Number.isFinite(Number(options.worldBounds.floorY))
                ? Number(options.worldBounds.floorY)
                : bounds.minimum.y;
            const center = {
                x: (bounds.minimum.x + bounds.maximum.x) / 2,
                y: floorY,
                z: (bounds.minimum.z + bounds.maximum.z) / 2,
            };
            const size = {
                x: Math.max(0.01, bounds.maximum.x - bounds.minimum.x),
                y: Math.max(0.01, bounds.maximum.y - bounds.minimum.y),
                z: Math.max(0.01, bounds.maximum.z - bounds.minimum.z),
            };
            let distance;
            if (state.camera.isOrthographicCamera) {
                const halfHeight = Math.max(size.z / 2, 0.5) * 1.12;
                const aspect = Math.max(0.01, finite(state.camera.aspect, 1));
                const halfWidth = Math.max(size.x / 2, halfHeight * aspect) * 1.12;
                state.camera.top = Math.max(halfHeight, halfWidth / aspect);
                state.camera.bottom = -state.camera.top;
                state.camera.left = -state.camera.top * aspect;
                state.camera.right = state.camera.top * aspect;
                distance = Math.max(size.x, size.z, 1);
            } else {
                const verticalFov = finite(state.camera.fov, 40) * Math.PI / 180;
                const aspect = Math.max(0.01, finite(state.camera.aspect, 1));
                const horizontalFov = 2 * Math.atan(
                    Math.tan(verticalFov / 2) * aspect
                );
                distance = Math.max(
                    size.z / (2 * Math.tan(verticalFov / 2)),
                    size.x / (2 * Math.tan(horizontalFov / 2)),
                    size.y + 1
                ) * 1.12;
                state.camera.near = Math.max(0.001, distance / 1000);
                state.camera.far = Math.max(100, distance + Math.max(
                    size.x,
                    size.z
                ) * 20);
            }
            setVector(state.camera.up, { x: 0, y: 0, z: -1 });
            setVector(state.camera.position, {
                x: center.x,
                y: center.y + distance,
                z: center.z,
            });
            if (state.controls && state.controls.target) {
                setVector(state.controls.target, center);
                if (typeof state.controls.update === 'function') {
                    state.controls.update();
                }
            } else if (typeof state.camera.lookAt === 'function') {
                state.camera.lookAt(center.x, center.y, center.z);
            }
            if (typeof state.camera.updateProjectionMatrix === 'function') {
                state.camera.updateProjectionMatrix();
            }
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld(true);
            }
            const afterRoot = objectTransform(state.modelRoot);
            state.lastFit = {
                mode: 'top',
                center: center,
                size: size,
                rootUnchanged: JSON.stringify(beforeRoot)
                    === JSON.stringify(afterRoot),
            };
            invalidate();
            return state.lastFit.rootUnchanged;
        }

        function applyMaterialSelection(material, highlightKind) {
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
                    highlightKind === 'selected' ? SELECTED_COLOR
                        : highlightKind === 'context' ? CONTEXT_FOCUS_COLOR
                        : finite(original.emissive, 0)
                );
            }
            if ('emissiveIntensity' in material) {
                material.emissiveIntensity = highlightKind
                    ? (highlightKind === 'context' ? 0.58 : 0.75)
                    : original.emissiveIntensity;
            }
            material.needsUpdate = true;
        }

        function applySelection(skipInvalidate) {
            const selectionVisible = !immersiveActive();
            const contextPlacementId = immersiveActive()
                && state.walkthroughContextFocus
                ? state.walkthroughContextFocus.placementId : null;
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
                                        selectionVisible
                                            && state.selectedIds.has(placementId)
                                            ? SELECTED_COLOR
                                            : contextPlacementId === placementId
                                                ? CONTEXT_FOCUS_COLOR
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
                        object.userData.contextFocusedPlacementId =
                            placementIds.includes(contextPlacementId)
                                ? contextPlacementId : null;
                    });
                    return;
                }
                record.pickObjects.forEach(function (object) {
                    const placementId = object.userData
                        && object.userData.placementId;
                    const selected = selectionVisible
                        && state.selectedIds.has(placementId);
                    const contextFocused = contextPlacementId === placementId;
                    const visit = function (candidate) {
                        const materials = Array.isArray(candidate && candidate.material)
                            ? candidate.material : [candidate && candidate.material];
                        materials.filter(Boolean).forEach(function (material) {
                            applyMaterialSelection(
                                material,
                                selected ? 'selected'
                                    : contextFocused ? 'context' : null
                            );
                        });
                    };
                    if (typeof object.traverse === 'function') object.traverse(visit);
                    else visit(object);
                });
            });
            if (!skipInvalidate) invalidate();
        }

        function setSelection(placementIds) {
            const values = typeof placementIds === 'string'
                ? [placementIds]
                : placementIds;
            state.selectedIds = new Set(sortedUniqueStrings(values));
            applySelection();
            state.baseGroups.forEach(function (group) {
                if (group.deferredVisual && group.placements.some(
                    function (placement) {
                        return state.selectedIds.has(placement.placementId);
                    }
                )) {
                    queueDeferredGroup(group, 'deferred_selected_asset');
                }
            });
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

        function walkthroughContextCandidate() {
            if (!immersiveActive() || !state.camera) return null;
            if (state.drone.active) {
                const direction = typeof THREE.Vector3 === 'function'
                    ? new THREE.Vector3() : null;
                if (!direction
                        || typeof state.camera.getWorldDirection !== 'function') {
                    return null;
                }
                state.camera.getWorldDirection(direction);
                const maximumDistance = droneSettings.contextRadius;
                let nearest = null;
                state.drone.obstacleVolumes.forEach(function (volume) {
                    const distance = rayDroneVolumeDistance(
                        state.camera.position,
                        direction,
                        volume,
                        maximumDistance
                    );
                    if (distance === null || (nearest
                            && nearest.distance <= distance)) return;
                    nearest = { volume: volume, distance: distance };
                });
                if (!nearest) return null;
                return {
                    placementId: nearest.volume.placementId,
                    distanceMeters: Math.round(nearest.distance * 100) / 100,
                    point: {
                        x: finite(state.camera.position.x, 0)
                            + direction.x * nearest.distance,
                        y: finite(state.camera.position.y, 0)
                            + direction.y * nearest.distance,
                        z: finite(state.camera.position.z, 0)
                            + direction.z * nearest.distance,
                    },
                    lineOfSight: true,
                    focusSource: 'center_ray_volume',
                };
            }
            const hit = pick({ normalized: true, x: 0, y: 0 });
            if (!hit || !hit.placementId) return null;
            const placement = state.placements.find(function (record) {
                return record.placementId === hit.placementId;
            });
            if (!placement || !placement.transform
                    || !placement.transform.position) return null;
            const point = hit.point || placement.transform.position;
            const dx = finite(point.x, 0) - finite(state.camera.position.x, 0);
            const dy = finite(point.y, 0) - finite(state.camera.position.y, 0);
            const dz = finite(point.z, 0) - finite(state.camera.position.z, 0);
            const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
            const contextRadius = state.drone.active
                ? droneSettings.contextRadius
                : walkthroughSettings.contextRadius;
            if (distance > contextRadius) return null;
            return {
                placementId: hit.placementId,
                distanceMeters: Math.round(distance * 100) / 100,
                point: {
                    x: finite(point.x, 0),
                    y: finite(point.y, 0),
                    z: finite(point.z, 0),
                },
                lineOfSight: true,
                focusSource: 'center_ray',
            };
        }

        function sameWalkthroughContext(left, right) {
            if (!left || !right) return left === right;
            return left.placementId === right.placementId
                && left.distanceMeters === right.distanceMeters;
        }

        function setWalkthroughContextFocus(value) {
            const next = value && value.placementId
                ? Object.assign({}, value) : null;
            if (sameWalkthroughContext(state.walkthroughContextFocus, next)) {
                return state.walkthroughContextFocus;
            }
            state.walkthroughContextFocus = next;
            applySelection(true);
            if (typeof state.walkthroughContextHandler === 'function') {
                state.walkthroughContextHandler(
                    next ? Object.assign({}, next) : null,
                    api
                );
            }
            if (typeof options.onWalkthroughContextChange === 'function') {
                options.onWalkthroughContextChange(
                    next ? Object.assign({}, next) : null,
                    api
                );
            }
            return state.walkthroughContextFocus;
        }

        function updateWalkthroughContextFocus() {
            return setWalkthroughContextFocus(walkthroughContextCandidate());
        }

        function getWalkthroughContextFocus() {
            return state.walkthroughContextFocus
                ? Object.assign({}, state.walkthroughContextFocus) : null;
        }

        function getRecordingCanvas() {
            return state.mounted && !state.suspended ? state.canvas : null;
        }

        function renderRecordingFrame() {
            if (!renderNow()) return null;
            return state.canvas;
        }

        function setWalkthroughContextHandler(handler) {
            state.walkthroughContextHandler = typeof handler === 'function'
                ? handler : null;
            if (state.walkthroughContextHandler) {
                state.walkthroughContextHandler(
                    getWalkthroughContextFocus(),
                    api
                );
            }
            return Boolean(state.walkthroughContextHandler);
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

        function numbersClose(left, right, tolerance) {
            return Math.abs(finite(left, 0) - finite(right, 0))
                <= finite(tolerance, 1e-6);
        }

        function quaternionMatches(actual, expected) {
            const direct = numbersClose(actual.x, expected.x, 1e-6)
                && numbersClose(actual.y, expected.y, 1e-6)
                && numbersClose(actual.z, expected.z, 1e-6)
                && numbersClose(actual.w, expected.w, 1e-6);
            const negated = numbersClose(actual.x, -expected.x, 1e-6)
                && numbersClose(actual.y, -expected.y, 1e-6)
                && numbersClose(actual.z, -expected.z, 1e-6)
                && numbersClose(actual.w, -expected.w, 1e-6);
            return direct || negated;
        }

        function objectMatchesPlacement(object, placement) {
            if (!object || !placement || !placement.transform) return false;
            const transform = placement.transform;
            return numbersClose(object.position && object.position.x,
                transform.position.x, 1e-6)
                && numbersClose(object.position && object.position.y,
                    transform.position.y, 1e-6)
                && numbersClose(object.position && object.position.z,
                    transform.position.z, 1e-6)
                && quaternionMatches(object.quaternion || {},
                    transform.quaternion)
                && numbersClose(object.scale && object.scale.x,
                    transform.scale, 1e-6)
                && numbersClose(object.scale && object.scale.y,
                    transform.scale, 1e-6)
                && numbersClose(object.scale && object.scale.z,
                    transform.scale, 1e-6);
        }

        function matrixMatches(left, right) {
            if (!left || !right || !Array.isArray(left.elements)
                    || !Array.isArray(right.elements)
                    || left.elements.length !== right.elements.length) {
                return false;
            }
            return left.elements.every(function (value, index) {
                return numbersClose(value, right.elements[index], 1e-5);
            });
        }

        function getPlacementTransformAudit() {
            const expected = new Map(state.placements.map(function (placement) {
                return [placement.placementId, placement];
            }));
            const audited = new Set();
            const mismatchIds = new Set();
            const unavailableIds = new Set();
            state.renderGroups.forEach(function (record) {
                if (record.instanced) {
                    const object = record.pickObjects[0];
                    const prototypeMatrix = record.prototypeMatrices[0];
                    const mapping = object
                        ? state.instanceLookup.get(object) || [] : [];
                    if (!object || typeof object.getMatrixAt !== 'function'
                            || typeof THREE.Matrix4 !== 'function') {
                        record.placementIds.forEach(function (placementId) {
                            unavailableIds.add(placementId);
                        });
                        return;
                    }
                    mapping.forEach(function (placementId, instanceIndex) {
                        const placement = expected.get(placementId);
                        if (!placement) return;
                        const actual = new THREE.Matrix4();
                        object.getMatrixAt(instanceIndex, actual);
                        const expectedMatrix = multiplyPlacementAndPrototype(
                            placement,
                            prototypeMatrix
                        );
                        audited.add(placementId);
                        if (!matrixMatches(actual, expectedMatrix)) {
                            mismatchIds.add(placementId);
                        }
                    });
                    return;
                }
                record.mappings.forEach(function (mapping, index) {
                    const placementId = mapping.placementId;
                    const placement = expected.get(placementId);
                    const object = record.pickObjects[index];
                    if (!placement || !object) {
                        if (placementId) unavailableIds.add(placementId);
                        return;
                    }
                    audited.add(placementId);
                    if (!objectMatchesPlacement(object, placement)) {
                        mismatchIds.add(placementId);
                    }
                });
            });
            const notAuditedIds = Array.from(expected.keys()).filter(
                function (placementId) {
                    return !audited.has(placementId)
                        && !unavailableIds.has(placementId);
                }
            ).sort();
            const incomplete = state.pendingLoads > 0
                || unavailableIds.size > 0
                || state.drone.active;
            const missingIds = incomplete ? [] : notAuditedIds;
            const visibilityOrPendingIds = incomplete ? notAuditedIds : [];
            return {
                adapter: 'three',
                status: mismatchIds.size || missingIds.length
                    ? 'mismatch'
                    : incomplete ? 'incomplete' : 'match',
                expectedPlacementCount: expected.size,
                auditedPlacementCount: audited.size,
                transformMismatchCount: mismatchIds.size,
                transformMismatchIds: Array.from(mismatchIds).sort().slice(0, 20),
                missingPlacementCount: missingIds.length,
                missingPlacementIds: missingIds.slice(0, 20),
                unavailablePlacementCount: unavailableIds.size,
                unavailablePlacementIds: Array.from(unavailableIds).sort().slice(0, 20),
                visibilityOrPendingPlacementCount:
                    visibilityOrPendingIds.length,
                visibilityOrPendingPlacementIds:
                    visibilityOrPendingIds.slice(0, 20),
                pendingLoadCount: state.pendingLoads,
                droneVisibilityWindowActive: state.drone.active,
                evidenceStatus: incomplete ? 'unknown' : 'derived',
                qualification: (
                    'Compares persisted placement transforms with actual object '
                    + 'transforms or rendered instance matrices. Prototype mesh '
                    + 'matrices are included for instanced assets.'
                ),
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
                suspended: state.suspended,
                disposed: state.disposed,
                degraded: state.degraded,
                contextLost: state.contextLost,
                placementCount: state.placements.length,
                placementTransformAudit: getPlacementTransformAudit(),
                floorMarkingCount: state.floorMarkingObjects.length,
                routeCount: state.routeObjects.length,
                assetGroupCount: state.baseGroups.size,
                representationGroups: groups,
                selectedPlacementIds: Array.from(state.selectedIds).sort(),
                walkthroughContextFocus: getWalkthroughContextFocus(),
                ghostActive: Boolean(state.ghostInput),
                proposalPreviewActive: Boolean(state.proposalInput),
                proposalBeforeCount: state.proposalInput
                    ? state.proposalInput.beforePlacements.length : 0,
                proposalProposedCount: state.proposalInput
                    ? state.proposalInput.proposedPlacements.length : 0,
                assetMaterial: {
                    mode: preserveAssetColors ? 'source' : 'neutral',
                    color: neutralAssetColor,
                },
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
                    observerActive: state.resizeObserverActive,
                    listenerCount: state.listenerCount,
                    canvasCount: state.canvas && state.canvas.parentNode ? 1 : 0,
                },
                controlsActive: Boolean(state.controls),
                navigation: {
                    mode: state.navigationMode,
                    gridVisible: state.gridVisible,
                    controls: state.controls ? {
                        zoomToCursor: Boolean(state.controls.zoomToCursor),
                        zoomSpeed: finite(state.controls.zoomSpeed, 1),
                        panSpeed: finite(state.controls.panSpeed, 1),
                        rotateSpeed: finite(state.controls.rotateSpeed, 1),
                        screenSpacePanning: Boolean(
                            state.controls.screenSpacePanning
                        ),
                        enableDamping: Boolean(state.controls.enableDamping),
                    } : null,
                    walkthrough: getWalkthroughState(),
                    drone: getDroneState(),
                },
                rendering: {
                    displayPixelRatio: state.displayPixelRatio,
                    interactivePixelRatio: state.interactivePixelRatio,
                    currentPixelRatio: state.currentPixelRatio,
                    navigationInteracting: state.navigationInteracting,
                    largeLayoutMode: state.placements.length
                        >= largeLayoutDetailThreshold,
                    largeLayoutDetailThreshold: largeLayoutDetailThreshold,
                    preferOverviewForLargeLayouts:
                        preferOverviewForLargeLayouts,
                    heavyVisualByteThreshold: largeLayoutHeavyVisualBytes,
                    deferredVisualPixelThreshold:
                        deferredVisualPixelThreshold,
                    deferredGroupCount: Array.from(
                        state.baseGroups.values()
                    ).filter(function (group) {
                        return Boolean(group.deferredVisual);
                    }).length,
                    calls: state.renderer && state.renderer.info
                        && state.renderer.info.render
                        ? finite(state.renderer.info.render.calls, 0) : null,
                    triangles: state.renderer && state.renderer.info
                        && state.renderer.info.render
                        ? finite(state.renderer.info.render.triangles, 0) : null,
                },
                visualSettings: getVisualSettings(),
                camera: state.camera ? {
                    fov: Number.isFinite(Number(state.camera.fov))
                        ? Number(state.camera.fov) : null,
                    position: state.camera.position ? {
                        x: finite(state.camera.position.x, 0),
                        y: finite(state.camera.position.y, 0),
                        z: finite(state.camera.position.z, 0),
                    } : null,
                    quaternion: state.camera.quaternion ? {
                        x: finite(state.camera.quaternion.x, 0),
                        y: finite(state.camera.quaternion.y, 0),
                        z: finite(state.camera.quaternion.z, 0),
                        w: finite(state.camera.quaternion.w, 1),
                    } : null,
                    direction: (function () {
                        if (!state.camera
                                || typeof state.camera.getWorldDirection
                                    !== 'function'
                                || typeof THREE.Vector3 !== 'function') {
                            return null;
                        }
                        const direction = new THREE.Vector3();
                        state.camera.getWorldDirection(direction);
                        return {
                            x: finite(direction.x, 0),
                            y: finite(direction.y, 0),
                            z: finite(direction.z, -1),
                        };
                    }()),
                    target: state.controls && state.controls.target ? {
                        x: finite(state.controls.target.x, 0),
                        y: finite(state.controls.target.y, 0),
                        z: finite(state.controls.target.z, 0),
                    } : null,
                } : null,
                cameraOrientation: cameraOrientationSnapshot(),
                environment: state.environmentDiagnostics
                    ? Object.assign({}, state.environmentDiagnostics) : null,
                modelRootTransform: objectTransform(state.modelRoot),
                worldBounds: state.worldBounds
                    ? cloneBounds(state.worldBounds) : null,
                lastFit: state.lastFit ? {
                    mode: state.lastFit.mode || 'facility',
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
            suspend: suspend,
            resume: resume,
            setScene: setScene,
            setSelection: setSelection,
            setSelectionHandler: setSelectionHandler,
            setGhostPlacement: setGhostPlacement,
            setProposalPreview: setProposalPreview,
            worldPointOnFloor: worldPointOnFloor,
            worldToClient: worldToClient,
            fit: fit,
            fitFacility: fitFacility,
            fitLayout: fitLayout,
            frontView: frontView,
            topView: topView,
            rightView: rightView,
            isometricView: isometricView,
            setNavigationMode: setNavigationMode,
            enterWalkthrough: enterWalkthrough,
            exitWalkthrough: exitWalkthrough,
            switchImmersiveMode: switchImmersiveMode,
            getWalkthroughState: getWalkthroughState,
            setWalkthroughStateHandler: setWalkthroughStateHandler,
            enterDrone: enterDrone,
            exitDrone: exitDrone,
            getDroneState: getDroneState,
            setDroneStateHandler: setDroneStateHandler,
            getWalkthroughContextFocus: getWalkthroughContextFocus,
            setWalkthroughContextHandler: setWalkthroughContextHandler,
            setCameraOrientationHandler: setCameraOrientationHandler,
            getRecordingCanvas: getRecordingCanvas,
            renderRecordingFrame: renderRecordingFrame,
            navigateWalkthroughToPlacement: navigateWalkthroughToPlacement,
            navigateWalkthroughToPoint: navigateWalkthroughToPoint,
            cancelWalkthroughNavigation: cancelWalkthroughNavigation,
            getCameraView: getCameraView,
            applyCameraView: applyCameraView,
            zoomBy: zoomBy,
            setGridVisible: setGridVisible,
            setEnvironmentSettings: setEnvironmentSettings,
            setVisualSettings: setVisualSettings,
            getVisualSettings: getVisualSettings,
            invalidate: invalidate,
            pick: pick,
            getDiagnostics: getDiagnostics,
            getPlacementTransformAudit: getPlacementTransformAudit,
            dispose: dispose,
        };
        return api;
    }

    return Object.freeze({
        RESOLUTION_STAGES: RESOLUTION_STAGES,
        DEFAULT_WALKTHROUGH_SETTINGS: DEFAULT_WALKTHROUGH_SETTINGS,
        DEFAULT_WALKTHROUGH_POSTURES: DEFAULT_WALKTHROUGH_POSTURES,
        DEFAULT_DRONE_SETTINGS: DEFAULT_DRONE_SETTINGS,
        buildDroneSpatialIndex: buildDroneSpatialIndex,
        circleIntersectsPolygon: circleIntersectsPolygon,
        dronePointValid: dronePointValid,
        droneViewDistanceForAltitude: droneViewDistanceForAltitude,
        findWalkthroughSpawn: findWalkthroughSpawn,
        findDroneSpawn: findDroneSpawn,
        planWalkthroughRoute: planWalkthroughRoute,
        pointInPolygon: pointInPolygon,
        resolveMultiLevelWalkthroughMovement: resolveMultiLevelWalkthroughMovement,
        resolveWalkthroughPostureChange: resolveWalkthroughPostureChange,
        resolveWalkthroughMovement: resolveWalkthroughMovement,
        resolveDroneMovement: resolveDroneMovement,
        probeDroneClearance: probeDroneClearance,
        sphereIntersectsDroneVolume: sphereIntersectsDroneVolume,
        smoothWalkthroughRoute: smoothWalkthroughRoute,
        walkthroughPointValidAtElevation: walkthroughPointValidAtElevation,
        walkthroughPostureProfiles: walkthroughPostureProfiles,
        walkthroughSegmentValid: walkthroughSegmentValid,
        walkthroughSurfaceAtPoint: walkthroughSurfaceAtPoint,
        walkthroughVerticalClearance: walkthroughVerticalClearance,
        walkthroughPointValid: walkthroughPointValid,
        createRendererPool: createRendererPool,
        createThreeAdapter: createThreeAdapter,
    });
}));
