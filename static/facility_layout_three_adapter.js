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
    const DEFAULT_LAYER_VISIBILITY = Object.freeze({
        zones: true,
        cells: true,
        routes: true,
        markings: true,
        assets: true,
    });
    const FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1 =
        'facility-motion-package-v1';
    const FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2 =
        'facility-motion-package-v2';
    const FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3 =
        'facility-motion-package-v3';
    const FACILITY_MOTION_PACKAGE_SCHEMA_VERSION =
        FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1;
    const FACILITY_MOTION_QUALIFICATION = (
        'Replays one deterministically planned traversal against nominal '
        + 'geometry at an exact vehicle revision. It does not establish '
        + 'throughput, congestion, traffic safety, or regulatory compliance.'
    );
    const FACILITY_MOTION_DISCLOSURE = (
        'Nominal geometry playback at an exact revision-bound profile. '
        + 'Sampled validation only; not vehicle dynamics, traffic, safety, '
        + 'or regulatory validation.'
    );
    const FACILITY_NAVIGATION_MOTION_QUALIFICATION = (
        'Replays one accepted revision-bound navigation journey for an existing '
        + 'placed actor on a shared display clock. Presentation timing is not process '
        + 'timing and does not establish throughput, congestion, staffing, traffic '
        + 'safety, or regulatory compliance.'
    );
    const FACILITY_ACTIVITY_SCENARIO_SCHEMA_VERSION =
        'facility-activity-scenario-v6';
    const FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION =
        'facility-activity-scenario-v7';
    const FACILITY_ACTIVITY_SCENARIO_QUALIFICATION = (
        'Prototype activity playback presents independently revision-bound '
        + 'route results on one shared display clock. It is not a discrete-event '
        + 'simulation and does not establish traffic safety, throughput, '
        + 'utilization, staffing, machine cycles, or regulatory compliance.'
    );
    const FACILITY_NAVIGATION_ACTIVITY_QUALIFICATION = (
        'Prototype navigation playback presents accepted revision-bound actor '
        + 'journeys on one shared display clock. Path intersections and sampled '
        + 'center proximity are presentation diagnostics, not safety, capacity, '
        + 'staffing, timing, or regulatory findings.'
    );
    const FACILITY_NAVIGATION_PRESENTATION_QUALIFICATION = (
        'Derived display diagnostics preserve accepted journey geometry and do not '
        + 'reschedule actors or alter paths to conceal visual overlap.'
    );
    const FACILITY_ACTIVITY_DISCLOSURE = (
        'Prototype presentation of independently validated route traversals. '
        + 'Fixed machines remain stationary without revision-bound kinematic '
        + 'tracks; this is not a traffic or production simulation.'
    );
    const FACILITY_LEAN_MOTION_SCHEMA_VERSION = 'facility-lean-motion-v3';
    const FACILITY_LEAN_MOTION_QUALIFICATION = (
        'Derived prototype motion borrows existing placed operator identities, '
        + 'assigns them to nearby placed stations, and routes the responsible '
        + 'endpoint operators to derived FIFO handoff points. Material handoff '
        + 'lines show workpiece transfer relationships, not operator walking. '
        + 'The routes are geometrically feasible paths, not time-optimal standard '
        + 'work, and do not establish staffing, task frequency, synchronized '
        + 'transfer timing, capacity, traffic safety, or compliance.'
    );
    const DEFAULT_MOTION_PLAYBACK_RATE = 1;
    const DEFAULT_REFUSED_PRESENTATION_SPEED = 1;
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

    function normalizeLayerVisibility(value, fallback) {
        const source = value && typeof value === 'object' ? value : {};
        const base = fallback && typeof fallback === 'object'
            ? fallback : DEFAULT_LAYER_VISIBILITY;
        const output = {};
        Object.keys(DEFAULT_LAYER_VISIBILITY).forEach(function (key) {
            output[key] = typeof source[key] === 'boolean'
                ? source[key] : base[key] !== false;
        });
        return output;
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

    function detachedJson(value) {
        return value === undefined
            ? undefined : JSON.parse(JSON.stringify(value));
    }

    function facilityMotionError(code, message, details) {
        const error = new Error(message);
        error.code = code;
        error.details = details && typeof details === 'object'
            ? detachedJson(details) : {};
        return error;
    }

    function motionTrajectory(movement) {
        if (!movement || typeof movement !== 'object') return null;
        const poses = movement.outcome === 'accepted'
            ? movement.poses
            : movement.outcome === 'envelope_refused'
                ? movement.attemptedPoses : null;
        const cumulativeDistance = movement.cumulativeDistance;
        if (!Array.isArray(poses) || !poses.length
                || !Array.isArray(cumulativeDistance)
                || poses.length !== cumulativeDistance.length) return null;
        return { poses: poses, cumulativeDistance: cumulativeDistance };
    }

    function activityDisplayOffsetPoints(points, requestedOffset) {
        const offset = finite(requestedOffset, 0);
        if (!Array.isArray(points) || points.length < 2
                || Math.abs(offset) <= 1e-9) return points;
        return points.map(function (point, index) {
            const previous = points[Math.max(0, index - 1)];
            const next = points[Math.min(points.length - 1, index + 1)];
            let dx = finite(next.x, 0) - finite(previous.x, 0);
            let dz = finite(next.z, 0) - finite(previous.z, 0);
            if (dx < -1e-9 || (Math.abs(dx) <= 1e-9 && dz < 0)) {
                dx *= -1;
                dz *= -1;
            }
            const length = Math.hypot(dx, dz);
            if (length <= 1e-9) return point;
            return Object.assign({}, point, {
                x: finite(point.x, 0) - (dz / length) * offset,
                z: finite(point.z, 0) + (dx / length) * offset,
            });
        });
    }

    function sampleFacilityMotionAtDistance(movement, requestedDistance) {
        const trajectory = motionTrajectory(movement);
        if (!trajectory) {
            throw facilityMotionError(
                'facility_motion_not_replayable',
                'This movement has no trajectory to replay.'
            );
        }
        const poses = trajectory.poses;
        const cumulative = trajectory.cumulativeDistance.map(function (value) {
            return Math.max(0, finite(value, 0));
        });
        const maximum = cumulative[cumulative.length - 1];
        const target = clamp(requestedDistance, 0, maximum, 0);
        let lower = 0;
        let upper = 0;
        if (target >= maximum) {
            lower = poses.length - 1;
            upper = lower;
        } else if (target > 0) {
            upper = cumulative.findIndex(function (value) {
                return value > target;
            });
            if (upper < 0) upper = poses.length - 1;
            lower = Math.max(0, upper - 1);
        }
        const span = cumulative[upper] - cumulative[lower];
        const ratio = upper === lower || span <= 0
            ? 0 : (target - cumulative[lower]) / span;
        const start = poses[lower] || {};
        const end = poses[upper] || start;
        const startHeading = finite(start.heading, 0);
        const endHeading = finite(end.heading, startHeading);
        const headingDelta = Math.atan2(
            Math.sin(endHeading - startHeading),
            Math.cos(endHeading - startHeading)
        );
        return {
            x: finite(start.x, 0)
                + (finite(end.x, 0) - finite(start.x, 0)) * ratio,
            z: finite(start.z, 0)
                + (finite(end.z, 0) - finite(start.z, 0)) * ratio,
            heading: startHeading + headingDelta * ratio,
            gear: stringValue(start.gear, 'forward'),
            distanceMeters: target,
            lowerPoseIndex: lower,
            upperPoseIndex: upper,
            interpolationRatio: ratio,
        };
    }

    function motionDurationSeconds(movement) {
        if (!motionTrajectory(movement)) return 0;
        if (movement.outcome === 'accepted') {
            return Math.max(
                0,
                finite(
                    movement.presentationDurationSeconds,
                    finite(movement.plannerDurationEstimateSeconds, 0)
                )
            );
        }
        const cumulative = movement.cumulativeDistance;
        return Math.max(
            0,
            finite(cumulative[cumulative.length - 1], 0)
                / DEFAULT_REFUSED_PRESENTATION_SPEED
        );
    }

    function normalizedHeading(value) {
        const heading = finite(value, 0);
        return Math.atan2(Math.sin(heading), Math.cos(heading));
    }

    function activityVisualHeadingOffset(forwardAxis) {
        if (forwardAxis === '+X') return 0;
        if (forwardAxis === '-X') return Math.PI;
        if (forwardAxis === '+Z') return Math.PI / 2;
        if (forwardAxis === '-Z') return -Math.PI / 2;
        throw facilityMotionError(
            'facility_activity_visual_alignment_invalid',
            'The activity actor visual has no supported forward axis.'
        );
    }

    function motionDistanceAtTime(movement, elapsedSeconds) {
        const trajectory = motionTrajectory(movement);
        if (!trajectory) return 0;
        const duration = motionDurationSeconds(movement);
        const distance = finite(
            trajectory.cumulativeDistance[
                trajectory.cumulativeDistance.length - 1
            ],
            0
        );
        if (duration <= 0) return 0;
        return distance * clamp(elapsedSeconds, 0, duration, 0) / duration;
    }

    function clearanceSampleAtOrBefore(movement, distanceMeters) {
        const samples = movement && movement.clearance
            && movement.clearance.samples;
        if (!Array.isArray(samples) || !samples.length) return null;
        const target = Math.max(0, finite(distanceMeters, 0));
        let selected = samples[0];
        for (let index = 1; index < samples.length; index += 1) {
            if (finite(samples[index].distanceMeters, 0) > target) break;
            selected = samples[index];
        }
        return detachedJson(selected);
    }

    function nearestClearanceSample(movement, distanceMeters) {
        const samples = movement && movement.clearance
            && movement.clearance.samples;
        if (!Array.isArray(samples) || !samples.length) return null;
        const target = Math.max(0, finite(distanceMeters, 0));
        return detachedJson(samples.reduce(function (nearest, sample) {
            return Math.abs(finite(sample.distanceMeters, 0) - target)
                < Math.abs(finite(nearest.distanceMeters, 0) - target)
                ? sample : nearest;
        }, samples[0]));
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
        const reducedMotionMedia = options.window
            && typeof options.window.matchMedia === 'function'
            ? options.window.matchMedia('(prefers-reduced-motion: reduce)')
            : null;
        const prefersReducedMotion = typeof options.prefersReducedMotion
            === 'boolean'
            ? options.prefersReducedMotion
            : Boolean(reducedMotionMedia && reducedMotionMedia.matches);

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
            layerVisibility: normalizeLayerVisibility(
                options.layerVisibility
            ),
            visualSettings: normalizeVisualSettings(options.visualSettings),
            motion: {
                package: null,
                vehicleProfile: null,
                root: null,
                ribbonRoot: null,
                vehicleRoot: null,
                createdObjects: [],
                borrowedObjects: [],
                playing: false,
                poseDirty: false,
                elapsedSeconds: 0,
                playbackRateMultiplier: DEFAULT_MOTION_PLAYBACK_RATE,
                lastFrameTime: null,
                currentPose: null,
                clearanceSample: null,
                following: false,
                status: 'idle',
                statusReason: null,
                prefersReducedMotion: prefersReducedMotion,
                generation: 0,
                stateHandler: null,
            },
            activity: {
                scenario: null,
                actorPayloads: null,
                candidatePresentation: null,
                root: null,
                pathRoot: null,
                tracks: [],
                hiddenObjects: [],
                playing: false,
                poseDirty: false,
                elapsedSeconds: 0,
                playbackRateMultiplier: DEFAULT_MOTION_PLAYBACK_RATE,
                lastFrameTime: null,
                status: 'idle',
                statusReason: null,
                selectedActorId: null,
                visibleActorTypes: {
                    vehicle: true,
                    operator: true,
                    mobile_equipment: true,
                },
                visiblePathTypes: {
                    vehicle: true,
                    operator: true,
                    mobile_equipment: true,
                },
                pathsVisible: true,
                departmentZoneId: null,
                generation: 0,
                stateHandler: null,
            },
            navigationPreview: {
                payload: null,
                root: null,
                pathRoot: null,
                actorRoot: null,
                visual: null,
                placement: null,
                hiddenObjects: [],
                playing: false,
                poseDirty: false,
                normalizedTime: 0,
                playbackRateMultiplier: 1,
                lastFrameTime: null,
                durationSeconds: 0,
                currentPose: null,
                visualYawRadians: null,
                pathsVisible: true,
                status: 'idle',
                statusReason: null,
                generation: 0,
                stateHandler: null,
            },
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

        function motionStateSnapshot() {
            const movement = state.motion.package
                && state.motion.package.movement;
            const duration = movement ? motionDurationSeconds(movement) : 0;
            const trajectory = movement ? motionTrajectory(movement) : null;
            const maximumDistance = trajectory
                ? finite(
                    trajectory.cumulativeDistance[
                        trajectory.cumulativeDistance.length - 1
                    ],
                    0
                ) : 0;
            return {
                loaded: Boolean(state.motion.package),
                status: state.motion.status,
                statusReason: state.motion.statusReason,
                packageId: state.motion.package
                    ? state.motion.package.packageId : null,
                movementId: movement ? movement.movementId : null,
                outcome: movement ? movement.outcome : null,
                vehiclePlacementId: movement && movement.vehiclePlacementId
                    ? movement.vehiclePlacementId : null,
                vehiclePresentation: movement && movement.vehiclePlacementId
                    ? 'placed_asset' : movement ? 'profile_proxy' : null,
                laneBinding: movement && movement.laneBinding
                    ? detachedJson(movement.laneBinding) : null,
                following: state.motion.following,
                playing: state.motion.playing,
                elapsedSeconds: state.motion.elapsedSeconds,
                durationSeconds: duration,
                playbackRateMultiplier:
                    state.motion.playbackRateMultiplier,
                distanceMeters: state.motion.currentPose
                    ? state.motion.currentPose.distanceMeters : 0,
                totalDistanceMeters: maximumDistance,
                pose: state.motion.currentPose
                    ? detachedJson(state.motion.currentPose) : null,
                clearanceAtValidatedSample: state.motion.clearanceSample
                    ? detachedJson(state.motion.clearanceSample) : null,
                sampleSpacingMeters: movement && movement.clearance
                    ? finite(movement.clearance.sampleSpacingMeters, 0)
                    : movement && movement.sweptEnvelope
                        ? finite(
                            movement.sweptEnvelope.sampleSpacingMeters,
                            0
                        ) : null,
                prefersReducedMotion: state.motion.prefersReducedMotion,
                qualification: state.motion.package
                    ? state.motion.package.qualification : null,
                disclosure: state.motion.package
                    ? FACILITY_MOTION_DISCLOSURE : null,
                plannerDurationEstimate: Boolean(
                    movement && movement.outcome === 'accepted'
                ),
                blocking: movement && movement.blocking
                    ? detachedJson(movement.blocking) : null,
            };
        }

        function notifyMotionState() {
            const snapshot = motionStateSnapshot();
            if (typeof state.motion.stateHandler === 'function') {
                state.motion.stateHandler(snapshot, api);
            }
            if (typeof options.onMotionStateChange === 'function') {
                options.onMotionStateChange(snapshot, api);
            }
            return snapshot;
        }

        function setMotionStateHandler(handler) {
            state.motion.stateHandler = typeof handler === 'function'
                ? handler : null;
            if (state.motion.stateHandler) notifyMotionState();
            return Boolean(state.motion.stateHandler);
        }

        function motionShape(points) {
            if (typeof THREE.Shape !== 'function'
                    || !Array.isArray(points) || points.length < 3) {
                throw facilityMotionError(
                    'facility_motion_geometry_unavailable',
                    'The exact motion footprint cannot be rendered.'
                );
            }
            const shape = new THREE.Shape();
            points.forEach(function (point, index) {
                const x = finite(point && point.x, NaN);
                const z = finite(point && point.z, NaN);
                if (!Number.isFinite(x) || !Number.isFinite(z)) {
                    throw facilityMotionError(
                        'facility_motion_geometry_invalid',
                        'Motion geometry contains an invalid point.'
                    );
                }
                if (index === 0) shape.moveTo(x, -z);
                else shape.lineTo(x, -z);
            });
            if (typeof shape.closePath === 'function') shape.closePath();
            return shape;
        }

        function orientMotionFloorMesh(mesh, elevation) {
            const halfSqrt = Math.sqrt(0.5);
            if (mesh.quaternion && typeof mesh.quaternion.set === 'function') {
                mesh.quaternion.set(-halfSqrt, 0, 0, halfSqrt);
            }
            if (mesh.position && typeof mesh.position.set === 'function') {
                mesh.position.set(0, finite(elevation, 0.04), 0);
            }
            mesh.renderOrder = 20;
            return mesh;
        }

        function createMotionRibbonRoot(movement) {
            const swept = movement && movement.sweptEnvelope;
            const polygons = swept && swept.geometry
                && swept.geometry.polygons;
            if (!Array.isArray(polygons) || !polygons.length) return null;
            if (typeof THREE.ShapeGeometry !== 'function'
                    || typeof THREE.MeshBasicMaterial !== 'function'
                    || typeof THREE.Mesh !== 'function') {
                throw facilityMotionError(
                    'facility_motion_geometry_unavailable',
                    'The validated swept envelope cannot be rendered.'
                );
            }
            const rootObject = createContainer();
            rootObject.name = 'FacilityMotionSweptEnvelope';
            rootObject.userData = rootObject.userData || {};
            rootObject.userData.facilityMotionRibbon = true;
            rootObject.userData.motionOutcome = movement.outcome;
            polygons.forEach(function (polygon) {
                const shape = motionShape(polygon.exterior);
                shape.holes = Array.isArray(shape.holes) ? shape.holes : [];
                (Array.isArray(polygon.holes) ? polygon.holes : [])
                    .forEach(function (holePoints) {
                        shape.holes.push(motionShape(holePoints));
                    });
                const geometry = new THREE.ShapeGeometry(shape);
                const material = new THREE.MeshBasicMaterial({
                    color: movement.outcome === 'envelope_refused'
                        ? 0xd14343 : 0x16a085,
                    transparent: true,
                    opacity: movement.outcome === 'envelope_refused'
                        ? 0.28 : 0.20,
                    depthWrite: false,
                    side: THREE.DoubleSide,
                });
                const mesh = orientMotionFloorMesh(
                    new THREE.Mesh(geometry, material),
                    0.035
                );
                mesh.userData = mesh.userData || {};
                mesh.userData.facilityMotionRibbon = true;
                rootObject.add(mesh);
            });
            return rootObject;
        }

        function createMotionVehicleRoot(profile, movement) {
            const footprint = profile && profile.footprint;
            if (!Array.isArray(footprint) || footprint.length < 3
                    || typeof THREE.ShapeGeometry !== 'function'
                    || typeof THREE.MeshBasicMaterial !== 'function'
                    || typeof THREE.Mesh !== 'function') {
                throw facilityMotionError(
                    'facility_motion_vehicle_profile_invalid',
                    'The exact published vehicle footprint is unavailable.'
                );
            }
            const rootObject = createContainer();
            rootObject.name = 'FacilityMotionVehicle';
            rootObject.visible = false;
            rootObject.userData = rootObject.userData || {};
            rootObject.userData.facilityMotionVehicle = true;
            rootObject.userData.vehicleProfileId =
                movement.vehicleProfileRef.vehicleProfileId;
            rootObject.userData.vehicleProfileRevision =
                movement.vehicleProfileRef.vehicleProfileRevision;
            const body = orientMotionFloorMesh(
                new THREE.Mesh(
                    new THREE.ShapeGeometry(motionShape(footprint)),
                    new THREE.MeshBasicMaterial({
                        color: movement.outcome === 'envelope_refused'
                            ? 0xe04b4b : 0x00a6d6,
                        transparent: true,
                        opacity: 0.94,
                        depthWrite: true,
                        side: THREE.DoubleSide,
                    })
                ),
                0.08
            );
            body.userData = body.userData || {};
            body.userData.facilityMotionVehicleFootprint = true;
            rootObject.add(body);
            return rootObject;
        }

        function placementRecord(placementId) {
            for (const record of state.renderGroups.values()) {
                if (!record || !record.placementIds.includes(placementId)) {
                    continue;
                }
                if (record.instanced) {
                    throw facilityMotionError(
                        'facility_motion_vehicle_instance_not_independent',
                        'This placement is rendered as a shared instance and '
                            + 'cannot be reparented without changing its peers.',
                        { placementId: placementId }
                    );
                }
                let found = null;
                if (record.container
                        && typeof record.container.traverse === 'function') {
                    record.container.traverse(function (object) {
                        if (!found && object && object.userData
                                && object.userData.placementId === placementId) {
                            found = object;
                        }
                    });
                }
                if (found) return found;
            }
            throw facilityMotionError(
                'facility_motion_vehicle_visual_unavailable',
                'The requested placement has no independent rendered visual.',
                { placementId: placementId }
            );
        }

        function placementValue(placementId) {
            return state.placements.find(function (placement) {
                return placement.placementId === placementId;
            }) || null;
        }

        function snapshotBorrowedObject(placementId, vehiclePlacement) {
            const object = placementRecord(placementId);
            const placement = placementValue(placementId);
            if (!placement || !object.parent) {
                throw facilityMotionError(
                    'facility_motion_vehicle_visual_unavailable',
                    'The requested placement transform is unavailable.',
                    { placementId: placementId }
                );
            }
            const parent = object.parent;
            const transform = placement.transform || {};
            const vehicleTransform = vehiclePlacement.transform || {};
            const position = transform.position || {};
            const vehiclePosition = vehicleTransform.position || {};
            return {
                placementId: placementId,
                object: object,
                parent: parent,
                siblingIndex: Array.isArray(parent.children)
                    ? parent.children.indexOf(object) : -1,
                transform: objectTransform(object),
                visible: object.visible !== false,
                selected: state.selectedIds.has(placementId),
                relativePosition: {
                    x: finite(position.x, 0) - finite(vehiclePosition.x, 0),
                    y: finite(position.y, 0) - finite(vehiclePosition.y, 0),
                    z: finite(position.z, 0) - finite(vehiclePosition.z, 0),
                },
                originalQuaternion: copyQuaternion(transform.quaternion),
            };
        }

        function preflightBorrowedObjects(movement) {
            if (!movement.vehiclePlacementId) return [];
            const vehiclePlacement = placementValue(
                movement.vehiclePlacementId
            );
            if (!vehiclePlacement) {
                throw facilityMotionError(
                    'facility_motion_vehicle_placement_missing',
                    'The movement vehicle is not present in this layout revision.'
                );
            }
            return [movement.vehiclePlacementId].concat(
                Array.isArray(movement.carriedPlacementIds)
                    ? movement.carriedPlacementIds : []
            ).map(function (placementId) {
                return snapshotBorrowedObject(
                    placementId,
                    vehiclePlacement
                );
            });
        }

        function restoreBorrowedObjects() {
            state.motion.borrowedObjects.forEach(function (snapshot) {
                const object = snapshot.object;
                const parent = snapshot.parent;
                if (!object || !parent) return;
                if (typeof parent.add === 'function') parent.add(object);
                if (Array.isArray(parent.children)
                        && snapshot.siblingIndex >= 0) {
                    const current = parent.children.indexOf(object);
                    if (current >= 0) parent.children.splice(current, 1);
                    parent.children.splice(
                        Math.min(snapshot.siblingIndex, parent.children.length),
                        0,
                        object
                    );
                    object.parent = parent;
                }
                const transform = snapshot.transform || {};
                if (object.position && typeof object.position.set === 'function') {
                    object.position.set(
                        finite(transform.position && transform.position.x, 0),
                        finite(transform.position && transform.position.y, 0),
                        finite(transform.position && transform.position.z, 0)
                    );
                }
                if (object.quaternion
                        && typeof object.quaternion.set === 'function') {
                    object.quaternion.set(
                        finite(transform.quaternion && transform.quaternion.x, 0),
                        finite(transform.quaternion && transform.quaternion.y, 0),
                        finite(transform.quaternion && transform.quaternion.z, 0),
                        finite(transform.quaternion && transform.quaternion.w, 1)
                    );
                }
                if (object.scale && typeof object.scale.set === 'function') {
                    object.scale.set(
                        finite(transform.scale && transform.scale.x, 1),
                        finite(transform.scale && transform.scale.y, 1),
                        finite(transform.scale && transform.scale.z, 1)
                    );
                }
                object.visible = snapshot.visible;
                if (snapshot.selected) state.selectedIds.add(snapshot.placementId);
                else state.selectedIds.delete(snapshot.placementId);
            });
            state.motion.borrowedObjects = [];
            if (typeof applySelection === 'function') applySelection();
        }

        function activateBorrowedObjects() {
            if (!state.motion.borrowedObjects.length
                    || state.motion.borrowedObjects.every(function (snapshot) {
                        return snapshot.object.parent === state.motion.vehicleRoot;
                    })) return;
            state.motion.borrowedObjects.forEach(function (snapshot) {
                state.motion.vehicleRoot.add(snapshot.object);
                if (snapshot.object.position
                        && typeof snapshot.object.position.set === 'function') {
                    snapshot.object.position.set(
                        snapshot.relativePosition.x,
                        snapshot.relativePosition.y,
                        snapshot.relativePosition.z
                    );
                }
                if (snapshot.object.quaternion
                        && typeof snapshot.object.quaternion.set === 'function') {
                    const value = snapshot.originalQuaternion;
                    snapshot.object.quaternion.set(
                        value.x,
                        value.y,
                        value.z,
                        value.w
                    );
                }
            });
        }

        function resetMotionState(reason) {
            state.motion.package = null;
            state.motion.vehicleProfile = null;
            state.motion.root = null;
            state.motion.ribbonRoot = null;
            state.motion.vehicleRoot = null;
            state.motion.createdObjects = [];
            state.motion.borrowedObjects = [];
            state.motion.playing = false;
            state.motion.poseDirty = false;
            state.motion.elapsedSeconds = 0;
            state.motion.playbackRateMultiplier =
                DEFAULT_MOTION_PLAYBACK_RATE;
            state.motion.lastFrameTime = null;
            state.motion.currentPose = null;
            state.motion.clearanceSample = null;
            state.motion.following = false;
            state.motion.status = 'idle';
            state.motion.statusReason = reason || null;
            state.motion.generation += 1;
        }

        function disposeMotion(reason, silent) {
            const hadMotion = Boolean(state.motion.package || state.motion.root);
            restoreBorrowedObjects();
            const rootObject = state.motion.root;
            if (rootObject && rootObject.parent
                    && typeof rootObject.parent.remove === 'function') {
                rootObject.parent.remove(rootObject);
            }
            if (rootObject) disposeObjectGraphs([rootObject]);
            resetMotionState(reason || 'disposed');
            if (!silent) notifyMotionState();
            if (hadMotion) invalidate();
            return hadMotion;
        }

        function validateMotionPayload(
            payload,
            activeLayoutRevision,
            activeValidationContextFingerprint
        ) {
            const value = payload && typeof payload === 'object' ? payload : {};
            const packageValue = value.package && typeof value.package === 'object'
                ? value.package : value;
            const schemaVersion = packageValue.schemaVersion;
            if (![FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1,
                    FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2,
                    FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3].includes(
                schemaVersion
            )) {
                throw facilityMotionError(
                    'facility_motion_package_schema_unsupported',
                    'Unsupported Facility Motion Package schema.'
                );
            }
            if (!packageValue.packageId || !packageValue.movement) {
                throw facilityMotionError(
                    'facility_motion_package_schema_invalid',
                    'The Facility Motion Package is incomplete.'
                );
            }
            if (schemaVersion === FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1) {
                if (typeof activeLayoutRevision !== 'string'
                        || !activeLayoutRevision
                        || packageValue.layoutRevision !== activeLayoutRevision) {
                    throw facilityMotionError(
                        'facility_motion_package_stale',
                        'The motion package does not match the active layout revision.',
                        {
                            packageRevision: packageValue.layoutRevision || null,
                            activeLayoutRevision: activeLayoutRevision || null,
                        }
                    );
                }
            } else {
                const recomputedFingerprint = activeValidationContextFingerprint
                    || value.activeValidationContextFingerprint;
                if (typeof packageValue.generationLayoutRevision !== 'string'
                        || !packageValue.generationLayoutRevision
                        || typeof packageValue.validationContextFingerprint
                            !== 'string'
                        || !packageValue.validationContextFingerprint) {
                    throw facilityMotionError(
                        'facility_motion_package_schema_invalid',
                        'The v2 Facility Motion Package is incomplete.'
                    );
                }
                if (typeof recomputedFingerprint !== 'string'
                        || !recomputedFingerprint) {
                    throw facilityMotionError(
                        'facility_motion_validation_context_unavailable',
                        'The v2 validation context was not recomputed before playback.'
                    );
                }
                if (recomputedFingerprint
                        !== packageValue.validationContextFingerprint) {
                    throw facilityMotionError(
                        'facility_motion_package_stale',
                        'The motion package validation context changed.',
                        {
                            packageFingerprint:
                                packageValue.validationContextFingerprint,
                            activeValidationContextFingerprint:
                                recomputedFingerprint,
                        }
                    );
                }
            }
            const expectedMotionQualification = schemaVersion
                    === FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3
                ? FACILITY_NAVIGATION_MOTION_QUALIFICATION
                : FACILITY_MOTION_QUALIFICATION;
            if (packageValue.qualification !== expectedMotionQualification) {
                throw facilityMotionError(
                    'facility_motion_package_qualification_invalid',
                    'The motion evidence qualification is unavailable or changed.'
                );
            }
            const movement = packageValue.movement;
            if (!['accepted', 'envelope_refused', 'unroutable'].includes(
                movement.outcome
            )) {
                throw facilityMotionError(
                    'facility_motion_outcome_invalid',
                    'Unsupported motion outcome.'
                );
            }
            const navigationJourney = schemaVersion
                === FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3;
            const vehicleProfile = navigationJourney
                ? value.actorProfile : value.vehicleProfile;
            if (navigationJourney) {
                const profileRef = movement.actorProfileRef;
                if (movement.outcome !== 'accepted'
                        || !movement.actorPlacementId
                        || !['pedestrian', 'vehicle'].includes(
                            movement.actorClass
                        )
                        || !profileRef || !vehicleProfile
                        || vehicleProfile.profileKind !== profileRef.profileKind
                        || vehicleProfile.profileId !== profileRef.profileId
                        || vehicleProfile.profileRevision
                            !== profileRef.profileRevision
                        || !Array.isArray(vehicleProfile.footprint)
                        || vehicleProfile.footprint.length < 3
                        || !motionTrajectory(movement)) {
                    throw facilityMotionError(
                        'facility_motion_actor_profile_mismatch',
                        'The exact navigation actor profile or trajectory is unavailable.'
                    );
                }
            } else if (movement.outcome !== 'unroutable') {
                if (!vehicleProfile || !movement.vehicleProfileRef
                        || vehicleProfile.vehicleProfileId
                            !== movement.vehicleProfileRef.vehicleProfileId
                        || vehicleProfile.vehicleProfileRevision
                            !== movement.vehicleProfileRef
                                .vehicleProfileRevision) {
                    throw facilityMotionError(
                        'facility_motion_vehicle_profile_mismatch',
                        'The exact vehicle profile revision is unavailable.'
                    );
                }
                if (!motionTrajectory(movement)) {
                    throw facilityMotionError(
                        'facility_motion_not_replayable',
                        'This movement has no trajectory to replay.'
                    );
                }
            }
            return {
                package: detachedJson(packageValue),
                vehicleProfile: vehicleProfile
                    ? detachedJson(vehicleProfile) : null,
            };
        }

        function loadMotionPackage(
            payload,
            activeLayoutRevision,
            activeValidationContextFingerprint
        ) {
            if (!state.mounted || state.disposed || !state.modelRoot) {
                throw facilityMotionError(
                    'facility_motion_view_unavailable',
                    'Mount the Facility 3D view before loading motion.'
                );
            }
            const validated = validateMotionPayload(
                payload,
                activeLayoutRevision,
                activeValidationContextFingerprint
            );
            disposeActivity('motion_loaded', true);
            disposeNavigationPreview('motion_loaded', true);
            disposeMotion('replaced', true);
            const packageValue = validated.package;
            const movement = packageValue.movement;
            const borrowedObjects = movement.outcome !== 'unroutable'
                ? preflightBorrowedObjects(movement) : [];
            state.motion.package = packageValue;
            state.motion.vehicleProfile = validated.vehicleProfile;
            state.motion.status = movement.outcome === 'unroutable'
                ? 'unroutable' : 'ready';
            state.motion.statusReason = null;
            state.motion.playing = false;
            state.motion.elapsedSeconds = 0;
            state.motion.lastFrameTime = null;
            state.motion.currentPose = null;
            state.motion.clearanceSample = null;
            state.motion.following = Boolean(movement.vehiclePlacementId);
            state.motion.poseDirty = movement.outcome !== 'unroutable';
            if (movement.outcome !== 'unroutable') {
                try {
                    const rootObject = createContainer();
                    rootObject.name = 'FacilityMotionPlayback';
                    rootObject.userData = rootObject.userData || {};
                    rootObject.userData.facilityMotionPackageId =
                        packageValue.packageId;
                    const ribbon = createMotionRibbonRoot(movement);
                    if (ribbon) rootObject.add(ribbon);
                    const vehicleRoot = movement.vehiclePlacementId
                        ? createContainer()
                        : createMotionVehicleRoot(
                            validated.vehicleProfile,
                            movement
                        );
                    vehicleRoot.name = 'FacilityMotionVehicleRoot';
                    vehicleRoot.visible = false;
                    rootObject.add(vehicleRoot);
                    state.motion.borrowedObjects = borrowedObjects;
                    state.motion.root = rootObject;
                    state.motion.ribbonRoot = ribbon;
                    state.motion.vehicleRoot = vehicleRoot;
                    state.motion.createdObjects = [rootObject];
                    state.modelRoot.add(rootObject);
                    invalidate();
                } catch (error) {
                    disposeMotion(
                        error && error.code
                            ? error.code : 'facility_motion_load_failed',
                        true
                    );
                    throw error;
                }
            }
            notifyMotionState();
            return motionStateSnapshot();
        }

        function motionVehicleBounds(pose) {
            const profile = state.motion.vehicleProfile || {};
            const dimensions = profile.overallDimensions || {};
            const length = Math.max(0.5, finite(dimensions.length, 1));
            const width = Math.max(0.5, finite(dimensions.width, 1));
            const height = Math.max(0.5, finite(dimensions.height, 1));
            const heading = finite(pose && pose.heading, 0);
            const cosine = Math.abs(Math.cos(heading));
            const sine = Math.abs(Math.sin(heading));
            const halfX = (cosine * length + sine * width) / 2;
            const halfZ = (sine * length + cosine * width) / 2;
            const movement = state.motion.package && state.motion.package.movement;
            const placement = movement && movement.vehiclePlacementId
                ? placementValue(movement.vehiclePlacementId) : null;
            const floorY = placement
                ? finite(
                    placement.transform && placement.transform.position
                        && placement.transform.position.y,
                    0
                ) : 0;
            return {
                minimum: {
                    x: finite(pose && pose.x, 0) - halfX,
                    y: floorY,
                    z: finite(pose && pose.z, 0) - halfZ,
                },
                maximum: {
                    x: finite(pose && pose.x, 0) + halfX,
                    y: floorY + height,
                    z: finite(pose && pose.z, 0) + halfZ,
                },
            };
        }

        function focusMotionVehicle(poseOverride) {
            const movement = state.motion.package && state.motion.package.movement;
            const trajectory = motionTrajectory(movement);
            if (!trajectory || !state.motion.vehicleRoot || state.walkthrough.active
                    || state.drone.active) return false;
            let pose = poseOverride || state.motion.currentPose;
            if (!pose) {
                pose = sampleFacilityMotionAtDistance(
                    movement,
                    motionDistanceAtTime(movement, state.motion.elapsedSeconds)
                );
            }
            const bounds = motionVehicleBounds(pose);
            return fitBounds(bounds, 'motion_vehicle', {
                x: finite(pose.x, 0),
                y: bounds.minimum.y
                    + (bounds.maximum.y - bounds.minimum.y) * 0.45,
                z: finite(pose.z, 0),
            });
        }

        function setMotionFollow(requested) {
            const movement = state.motion.package && state.motion.package.movement;
            const enabled = requested === true;
            if (!movement || !movement.vehiclePlacementId || state.walkthrough.active
                    || state.drone.active) {
                state.motion.following = false;
                notifyMotionState();
                return false;
            }
            state.motion.following = enabled;
            if (enabled) focusMotionVehicle();
            notifyMotionState();
            return state.motion.following;
        }

        function translateFollowingCamera(previousPose, nextPose) {
            if (!state.motion.following || !previousPose || state.walkthrough.active
                    || state.drone.active || !state.camera) return;
            const dx = finite(nextPose.x, 0) - finite(previousPose.x, 0);
            const dz = finite(nextPose.z, 0) - finite(previousPose.z, 0);
            state.camera.position.x = finite(state.camera.position.x, 0) + dx;
            state.camera.position.z = finite(state.camera.position.z, 0) + dz;
            if (state.controls && state.controls.target) {
                state.controls.target.x = finite(state.controls.target.x, 0) + dx;
                state.controls.target.z = finite(state.controls.target.z, 0) + dz;
                if (typeof state.controls.update === 'function') {
                    state.controls.update();
                }
            }
            if (typeof state.camera.updateMatrixWorld === 'function') {
                state.camera.updateMatrixWorld(true);
            }
        }

        function playMotion() {
            const movement = state.motion.package
                && state.motion.package.movement;
            if (!motionTrajectory(movement)) return false;
            const duration = motionDurationSeconds(movement);
            if (state.motion.elapsedSeconds >= duration && duration > 0) {
                state.motion.elapsedSeconds = 0;
                state.motion.poseDirty = true;
            }
            state.motion.playing = true;
            state.motion.status = 'playing';
            state.motion.lastFrameTime = null;
            notifyMotionState();
            invalidate();
            return true;
        }

        function pauseMotion() {
            if (!state.motion.package) return false;
            state.motion.playing = false;
            state.motion.status = motionTrajectory(
                state.motion.package.movement
            ) ? 'paused' : state.motion.status;
            state.motion.lastFrameTime = null;
            notifyMotionState();
            return true;
        }

        function seekMotion(requestedSeconds) {
            const movement = state.motion.package
                && state.motion.package.movement;
            if (!motionTrajectory(movement)) return false;
            const duration = motionDurationSeconds(movement);
            let elapsed = clamp(requestedSeconds, 0, duration, 0);
            if (!state.motion.playing && movement.outcome === 'accepted') {
                const requestedDistance = motionDistanceAtTime(
                    movement,
                    elapsed
                );
                const sample = nearestClearanceSample(
                    movement,
                    requestedDistance
                );
                const totalDistance = finite(movement.distanceMeters, 0);
                if (sample && duration > 0 && totalDistance > 0) {
                    elapsed = duration
                        * finite(sample.distanceMeters, 0) / totalDistance;
                }
            }
            state.motion.elapsedSeconds = elapsed;
            state.motion.lastFrameTime = null;
            state.motion.poseDirty = true;
            state.motion.status = 'paused';
            invalidate();
            return true;
        }

        function setMotionRate(requestedRate) {
            if (!state.motion.package) return false;
            state.motion.playbackRateMultiplier = clamp(
                requestedRate,
                0.25,
                4,
                DEFAULT_MOTION_PLAYBACK_RATE
            );
            notifyMotionState();
            return state.motion.playbackRateMultiplier;
        }

        function updateMotion(timestamp) {
            const movement = state.motion.package
                && state.motion.package.movement;
            if (!motionTrajectory(movement) || !state.motion.vehicleRoot) {
                return false;
            }
            const duration = motionDurationSeconds(movement);
            if (state.motion.playing) {
                if (state.motion.lastFrameTime === null) {
                    state.motion.lastFrameTime = finite(timestamp, 0);
                } else {
                    const deltaSeconds = Math.max(
                        0,
                        (finite(timestamp, state.motion.lastFrameTime)
                            - state.motion.lastFrameTime) / 1000
                    );
                    state.motion.lastFrameTime = finite(
                        timestamp,
                        state.motion.lastFrameTime
                    );
                    state.motion.elapsedSeconds = Math.min(
                        duration,
                        state.motion.elapsedSeconds
                            + deltaSeconds
                                * state.motion.playbackRateMultiplier
                    );
                    state.motion.poseDirty = true;
                }
            }
            if (!state.motion.poseDirty) return state.motion.playing;
            try {
                activateBorrowedObjects();
                const distance = motionDistanceAtTime(
                    movement,
                    state.motion.elapsedSeconds
                );
                const pose = sampleFacilityMotionAtDistance(
                    movement,
                    distance
                );
                const previousPose = state.motion.currentPose;
                const firstPose = motionTrajectory(movement).poses[0];
                const heading = movement.vehiclePlacementId
                    ? -(pose.heading - finite(firstPose.heading, 0))
                    : -pose.heading;
                const vehiclePlacement = movement.vehiclePlacementId
                    ? placementValue(movement.vehiclePlacementId) : null;
                const vertical = vehiclePlacement
                    ? finite(
                        vehiclePlacement.transform
                            && vehiclePlacement.transform.position
                            && vehiclePlacement.transform.position.y,
                        0
                    ) : 0;
                if (state.motion.vehicleRoot.position
                        && typeof state.motion.vehicleRoot.position.set
                            === 'function') {
                    state.motion.vehicleRoot.position.set(
                        pose.x,
                        vertical,
                        pose.z
                    );
                }
                if (state.motion.vehicleRoot.quaternion
                        && typeof state.motion.vehicleRoot.quaternion.set
                            === 'function') {
                    state.motion.vehicleRoot.quaternion.set(
                        0,
                        Math.sin(heading / 2),
                        0,
                        Math.cos(heading / 2)
                    );
                }
                state.motion.vehicleRoot.visible = true;
                state.motion.currentPose = pose;
                if (state.motion.following) {
                    if (previousPose) {
                        translateFollowingCamera(previousPose, pose);
                    } else {
                        focusMotionVehicle(pose);
                    }
                }
                state.motion.clearanceSample = clearanceSampleAtOrBefore(
                    movement,
                    pose.distanceMeters
                );
                state.motion.poseDirty = false;
                if (state.motion.playing
                        && state.motion.elapsedSeconds >= duration) {
                    state.motion.playing = false;
                    state.motion.status = 'complete';
                    state.motion.lastFrameTime = null;
                }
                notifyMotionState();
                return true;
            } catch (error) {
                reportError('facility_motion_playback_failed', error);
                disposeMotion(
                    error && error.code
                        ? error.code : 'facility_motion_playback_failed'
                );
                return false;
            }
        }

        function activityRenderRecord(placementId) {
            for (const record of state.renderGroups.values()) {
                if (record && Array.isArray(record.placementIds)
                        && record.placementIds.includes(placementId)) {
                    return record;
                }
            }
            throw facilityMotionError(
                'facility_activity_actor_visual_unavailable',
                'An activity actor has no rendered catalog visual.',
                { placementId: placementId }
            );
        }

        function activitySuppressedPlacementIds() {
            const result = new Set();
            if (!state.activity.scenario) return result;
            state.activity.tracks.forEach(function (track) {
                if (track && track.sourcePlacementHidden === true
                        && track.actor && track.actor.placementId) {
                    result.add(track.actor.placementId);
                }
            });
            const stationary = state.activity.candidatePresentation
                && state.activity.candidatePresentation
                    .suppressedOperatorPlacementIds;
            if (Array.isArray(stationary)) {
                stationary.forEach(function (placementId) {
                    if (placementId) result.add(placementId);
                });
            }
            return result;
        }

        function activityIndependentObject(record, placementId) {
            let found = null;
            if (record && record.container
                    && typeof record.container.traverse === 'function') {
                record.container.traverse(function (object) {
                    if (!found && object && object.userData
                            && object.userData.placementId === placementId) {
                        found = object;
                    }
                });
            }
            return found;
        }

        function cloneActivityRenderable(prototype) {
            const clone = cloneRenderable(prototype);
            if (clone && typeof clone.traverse === 'function') {
                clone.traverse(function (object) {
                    if (object && object.isMesh && object.geometry
                            && typeof object.geometry.clone === 'function') {
                        object.geometry = object.geometry.clone();
                    }
                });
            }
            return clone;
        }

        function hideActivityPlacement(record, placementId) {
            if (!record.instanced) {
                const object = activityIndependentObject(record, placementId);
                if (!object) {
                    throw facilityMotionError(
                        'facility_activity_actor_visual_unavailable',
                        'The activity actor visual cannot be isolated.',
                        { placementId: placementId }
                    );
                }
                const snapshot = {
                    kind: 'object',
                    object: object,
                    visible: object.visible !== false,
                };
                object.visible = false;
                return [snapshot];
            }
            if (typeof THREE.Matrix4 !== 'function') {
                throw facilityMotionError(
                    'facility_activity_instance_isolation_unavailable',
                    'Instanced actor isolation requires Matrix4 support.',
                    { placementId: placementId }
                );
            }
            const instanceIndex = record.placementIds.indexOf(placementId);
            if (instanceIndex < 0) return [];
            return (record.pickObjects || []).map(function (mesh) {
                if (!mesh || typeof mesh.getMatrixAt !== 'function'
                        || typeof mesh.setMatrixAt !== 'function') {
                    throw facilityMotionError(
                        'facility_activity_instance_isolation_unavailable',
                        'The rendered actor instance cannot be isolated.',
                        { placementId: placementId }
                    );
                }
                const matrix = new THREE.Matrix4();
                mesh.getMatrixAt(instanceIndex, matrix);
                const hidden = new THREE.Matrix4();
                if (typeof hidden.makeScale === 'function') {
                    hidden.makeScale(0, 0, 0);
                }
                mesh.setMatrixAt(instanceIndex, hidden);
                if (mesh.instanceMatrix) mesh.instanceMatrix.needsUpdate = true;
                return {
                    kind: 'instance',
                    mesh: mesh,
                    instanceIndex: instanceIndex,
                    matrix: matrix,
                };
            });
        }

        function restoreActivityPlacements() {
            state.activity.hiddenObjects.slice().reverse().forEach(
                function (snapshot) {
                    if (snapshot.kind === 'object' && snapshot.object) {
                        snapshot.object.visible = snapshot.visible;
                    } else if (snapshot.kind === 'instance' && snapshot.mesh
                            && typeof snapshot.mesh.setMatrixAt === 'function') {
                        snapshot.mesh.setMatrixAt(
                            snapshot.instanceIndex,
                            snapshot.matrix
                        );
                        if (snapshot.mesh.instanceMatrix) {
                            snapshot.mesh.instanceMatrix.needsUpdate = true;
                        }
                    }
                }
            );
            state.activity.hiddenObjects = [];
        }

        function activityPlacementStillVisible(placementId) {
            const record = activityRenderRecord(placementId);
            if (!record.instanced) {
                const object = activityIndependentObject(record, placementId);
                return Boolean(object && object.visible !== false);
            }
            if (typeof THREE.Matrix4 !== 'function') return true;
            return (record.pickObjects || []).some(function (mesh) {
                if (!mesh || typeof mesh.getMatrixAt !== 'function') return true;
                const renderedPlacementIds = state.instanceLookup.get(mesh)
                    || record.placementIds;
                const instanceIndex = renderedPlacementIds.indexOf(placementId);
                if (instanceIndex < 0) return false;
                const matrix = new THREE.Matrix4();
                mesh.getMatrixAt(instanceIndex, matrix);
                const elements = matrix.elements || [];
                return [0, 1, 2, 4, 5, 6, 8, 9, 10].some(function (index) {
                    return Math.abs(finite(elements[index], 0)) > 1e-9;
                });
            });
        }

        function resetActivityState(reason) {
            state.activity.scenario = null;
            state.activity.actorPayloads = null;
            state.activity.candidatePresentation = null;
            state.activity.root = null;
            state.activity.pathRoot = null;
            state.activity.tracks = [];
            state.activity.hiddenObjects = [];
            state.activity.playing = false;
            state.activity.poseDirty = false;
            state.activity.elapsedSeconds = 0;
            state.activity.playbackRateMultiplier =
                DEFAULT_MOTION_PLAYBACK_RATE;
            state.activity.lastFrameTime = null;
            state.activity.status = 'idle';
            state.activity.statusReason = reason || null;
            state.activity.selectedActorId = null;
            state.activity.visibleActorTypes = {
                vehicle: true,
                operator: true,
                mobile_equipment: true,
            };
            state.activity.visiblePathTypes = {
                vehicle: true,
                operator: true,
                mobile_equipment: true,
            };
            state.activity.pathsVisible = true;
            state.activity.departmentZoneId = null;
            state.activity.generation += 1;
        }

        function activityStateSnapshot() {
            const scenario = state.activity.scenario;
            const duration = scenario
                ? Math.max(0.001, finite(scenario.cycleDurationSeconds, 0.001))
                : 0;
            const elapsed = scenario && scenario.repeat
                ? state.activity.elapsedSeconds % duration
                : state.activity.elapsedSeconds;
            return {
                loaded: Boolean(scenario),
                scenarioId: scenario ? scenario.scenarioId : null,
                label: scenario ? scenario.label : null,
                status: state.activity.status,
                statusReason: state.activity.statusReason,
                playing: state.activity.playing,
                elapsedSeconds: elapsed,
                durationSeconds: duration,
                playbackRateMultiplier:
                    state.activity.playbackRateMultiplier,
                selectedActorId: state.activity.selectedActorId,
                visibleActorTypes: Object.assign(
                    {},
                    state.activity.visibleActorTypes
                ),
                visiblePathTypes: Object.assign(
                    {},
                    state.activity.visiblePathTypes
                ),
                pathsVisible: state.activity.pathsVisible !== false,
                borrowedPlacementCount: state.activity.tracks.length,
                suppressedStationaryOperatorCount:
                    state.activity.candidatePresentation
                    && Array.isArray(
                        state.activity.candidatePresentation
                            .suppressedOperatorPlacementIds
                    )
                        ? state.activity.candidatePresentation
                            .suppressedOperatorPlacementIds.length
                        : 0,
                duplicateVisiblePlacementIds: state.activity.tracks
                    .map(function (track) {
                        return track.actor.placementId;
                    })
                    .filter(activityPlacementStillVisible)
                    .sort(),
                visibleSourcePlacementIds: scenario ? Array.from(new Set(
                    state.activity.tracks.map(function (track) {
                        return track.actor.placementId;
                    }).concat(
                        state.activity.candidatePresentation
                        && Array.isArray(
                            state.activity.candidatePresentation
                                .suppressedOperatorPlacementIds
                        )
                            ? state.activity.candidatePresentation
                                .suppressedOperatorPlacementIds : []
                    )
                )).filter(activityPlacementStillVisible).sort() : [],
                leanMotionCounts: scenario ? {
                    operatorPaths: scenario.leanMotion.operatorPaths.length,
                    pedestrianConnections:
                        scenario.leanMotion.pedestrianConnections.length,
                    assistanceGates:
                        scenario.leanMotion.assistanceGates.length,
                    materialHandoffs:
                        scenario.leanMotion.materialHandoffs.length,
                    fifoPoints: scenario.leanMotion.fifoPoints.length,
                    renderedObjects: state.activity.pathRoot
                        && Array.isArray(state.activity.pathRoot.children)
                        ? state.activity.pathRoot.children.length : 0,
                } : null,
                candidatePresentation: state.activity.candidatePresentation
                    ? {
                        authority:
                            state.activity.candidatePresentation.authority,
                        reviewStatus:
                            state.activity.candidatePresentation.reviewStatus,
                        productionEligible:
                            state.activity.candidatePresentation.productionEligible,
                        candidateCounts: detachedJson(
                            state.activity.candidatePresentation.candidateCounts
                        ),
                        packagingPathLegend: Array.isArray(
                            state.activity.candidatePresentation
                                .packagingPathLegend
                        ) ? detachedJson(
                                state.activity.candidatePresentation
                                    .packagingPathLegend
                            ) : [],
                        inspectionPathLegend: Array.isArray(
                            state.activity.candidatePresentation
                                .inspectionPathLegend
                        ) ? detachedJson(
                                state.activity.candidatePresentation
                                    .inspectionPathLegend
                            ) : [],
                        finishedGoodsPathLegend: Array.isArray(
                            state.activity.candidatePresentation
                                .finishedGoodsPathLegend
                        ) ? detachedJson(
                                state.activity.candidatePresentation
                                    .finishedGoodsPathLegend
                            ) : [],
                        receivingPathLegend: Array.isArray(
                            state.activity.candidatePresentation
                                .receivingPathLegend
                        ) ? detachedJson(
                                state.activity.candidatePresentation
                                    .receivingPathLegend
                            ) : [],
                        parkedVehiclePlacementIds: Array.isArray(
                            state.activity.candidatePresentation
                                .parkedVehiclePlacementIds
                        ) ? detachedJson(
                                state.activity.candidatePresentation
                                    .parkedVehiclePlacementIds
                            ) : [],
                        parkedVehicleVisiblePlacementIds: Array.isArray(
                            state.activity.candidatePresentation
                                .parkedVehiclePlacementIds
                        ) ? state.activity.candidatePresentation
                                .parkedVehiclePlacementIds.filter(
                                    activityPlacementStillVisible
                                ).sort() : [],
                        qualification:
                            state.activity.candidatePresentation.qualification,
                    } : null,
                departmentZoneId: state.activity.departmentZoneId,
                actors: state.activity.tracks.map(function (track) {
                    return {
                        actorId: track.actor.actorId,
                        actorType: track.actor.actorType,
                        label: track.actor.label,
                        placementId: track.actor.placementId,
                        routeId: track.actor.routeId,
                        repeat: track.actor.repeat === true,
                        loopMode: track.actor.loopMode,
                        cycleDurationSeconds: motionDurationSeconds(
                            track.package.movement
                        ),
                        cycleClosed: (function () {
                            const trajectory = motionTrajectory(
                                track.package.movement
                            );
                            const first = trajectory.poses[0];
                            const last = trajectory.poses[
                                trajectory.poses.length - 1
                            ];
                            return Boolean(first && last
                                && Math.hypot(
                                    finite(last.x, 0) - finite(first.x, 0),
                                    finite(last.z, 0) - finite(first.z, 0)
                                ) <= 1e-6);
                        }()),
                        departmentZoneIds:
                            track.actor.departmentZoneIds.slice(),
                        visible: track.root.visible !== false,
                        pose: track.currentPose
                            ? detachedJson(track.currentPose) : null,
                        localElapsedSeconds: track.localElapsedSeconds,
                        playbackPhase: track.playbackPhase,
                        travelDirection: track.travelDirection,
                        currentMotionPackageId:
                            track.currentMotionPackageId,
                        exactCatalogVisual: Boolean(track.visual),
                        sourcePlacementSuppressed:
                            !activityPlacementStillVisible(
                                track.actor.placementId
                            ),
                        visualForwardAxis:
                            track.actor.visualAlignment.forwardAxis,
                        visualYawRadians: track.visualYawRadians,
                    };
                }),
                stationaryEvidence: scenario
                    ? detachedJson(scenario.stationaryEvidence) : null,
                unavailableActivity: scenario
                    ? detachedJson(scenario.unavailableActivity) : [],
                prototypeMode: Boolean(scenario),
                qualification: scenario ? scenario.qualification : null,
                disclosure: scenario ? FACILITY_ACTIVITY_DISCLOSURE : null,
            };
        }

        function notifyActivityState() {
            const snapshot = activityStateSnapshot();
            if (typeof state.activity.stateHandler === 'function') {
                state.activity.stateHandler(snapshot, api);
            }
            if (typeof options.onActivityStateChange === 'function') {
                options.onActivityStateChange(snapshot, api);
            }
            return snapshot;
        }

        function setActivityStateHandler(handler) {
            state.activity.stateHandler = typeof handler === 'function'
                ? handler : null;
            if (state.activity.stateHandler) notifyActivityState();
            return Boolean(state.activity.stateHandler);
        }

        function disposeActivity(reason, silent) {
            const hadActivity = Boolean(
                state.activity.scenario || state.activity.root
            );
            restoreActivityPlacements();
            const rootObject = state.activity.root;
            if (rootObject && rootObject.parent
                    && typeof rootObject.parent.remove === 'function') {
                rootObject.parent.remove(rootObject);
            }
            if (rootObject) disposeObjectGraphs([rootObject]);
            resetActivityState(reason || 'disposed');
            if (hadActivity) restoreBasePlacementVisibility();
            if (!silent) notifyActivityState();
            if (hadActivity) invalidate();
            return hadActivity;
        }

        function navigationPreviewRuntime() {
            const runtime = root
                && root.InspectorProFacilityNavigationAuthoring;
            if (!runtime
                    || typeof runtime.samplePathAtNormalizedTime
                        !== 'function'
                    || typeof runtime.pathLength !== 'function') {
                throw facilityMotionError(
                    'facility_navigation_preview_runtime_unavailable',
                    'The deterministic navigation authoring runtime is unavailable.'
                );
            }
            return runtime;
        }

        function validateNavigationPreviewPayload(value, activeRevision) {
            const payload = value && typeof value === 'object'
                ? detachedJson(value) : null;
            if (!payload || typeof payload.previewId !== 'string'
                    || !payload.previewId
                    || typeof payload.actorPlacementId !== 'string'
                    || !['pedestrian', 'vehicle'].includes(payload.actorClass)
                    || !Array.isArray(payload.points)
                    || payload.points.length < 2
                    || !['+X', '-X', '+Z', '-Z'].includes(
                        payload.visualForwardAxis
                    )) {
                throw facilityMotionError(
                    'facility_navigation_preview_invalid',
                    'The manual navigation preview payload is incomplete.'
                );
            }
            if (payload.layoutRevision !== activeRevision) {
                throw facilityMotionError(
                    'facility_navigation_preview_stale',
                    'The manual navigation preview does not match the active base revision.',
                    {
                        previewRevision: payload.layoutRevision || null,
                        activeRevision: activeRevision || null,
                    }
                );
            }
            payload.points.forEach(function (point, index) {
                if (!point || !Number.isFinite(Number(point.x))
                        || !Number.isFinite(Number(point.z))) {
                    throw facilityMotionError(
                        'facility_navigation_preview_invalid',
                        'A manual path waypoint is invalid.',
                        { pointIndex: index }
                    );
                }
            });
            const placement = state.placements.find(function (item) {
                return item.placementId === payload.actorPlacementId;
            });
            if (!placement) {
                throw facilityMotionError(
                    'facility_navigation_preview_actor_unavailable',
                    'The selected existing actor is unavailable in the active layout.',
                    { placementId: payload.actorPlacementId }
                );
            }
            return { payload: payload, placement: placement };
        }

        function restoreNavigationPreviewPlacement() {
            state.navigationPreview.hiddenObjects.slice().reverse().forEach(
                function (snapshot) {
                    if (snapshot.kind === 'object' && snapshot.object) {
                        snapshot.object.visible = snapshot.visible;
                    } else if (snapshot.kind === 'instance' && snapshot.mesh
                            && typeof snapshot.mesh.setMatrixAt === 'function') {
                        snapshot.mesh.setMatrixAt(
                            snapshot.instanceIndex,
                            snapshot.matrix
                        );
                        if (snapshot.mesh.instanceMatrix) {
                            snapshot.mesh.instanceMatrix.needsUpdate = true;
                        }
                    }
                }
            );
            state.navigationPreview.hiddenObjects = [];
        }

        function resetNavigationPreviewState(reason) {
            const handler = state.navigationPreview.stateHandler;
            state.navigationPreview.payload = null;
            state.navigationPreview.root = null;
            state.navigationPreview.pathRoot = null;
            state.navigationPreview.actorRoot = null;
            state.navigationPreview.visual = null;
            state.navigationPreview.placement = null;
            state.navigationPreview.hiddenObjects = [];
            state.navigationPreview.playing = false;
            state.navigationPreview.poseDirty = false;
            state.navigationPreview.normalizedTime = 0;
            state.navigationPreview.playbackRateMultiplier = 1;
            state.navigationPreview.lastFrameTime = null;
            state.navigationPreview.durationSeconds = 0;
            state.navigationPreview.currentPose = null;
            state.navigationPreview.visualYawRadians = null;
            state.navigationPreview.pathsVisible = true;
            state.navigationPreview.status = 'idle';
            state.navigationPreview.statusReason = reason || null;
            state.navigationPreview.generation += 1;
            state.navigationPreview.stateHandler = handler;
        }

        function navigationPreviewStateSnapshot() {
            const preview = state.navigationPreview;
            const payload = preview.payload;
            return {
                loaded: Boolean(payload),
                previewId: payload ? payload.previewId : null,
                actorPlacementId: payload
                    ? payload.actorPlacementId : null,
                actorClass: payload ? payload.actorClass : null,
                status: preview.status,
                statusReason: preview.statusReason,
                playing: preview.playing,
                normalizedTime: preview.normalizedTime,
                durationSeconds: preview.durationSeconds,
                playbackRateMultiplier: preview.playbackRateMultiplier,
                pathsVisible: preview.pathsVisible !== false,
                pose: preview.currentPose
                    ? detachedJson(preview.currentPose) : null,
                visualForwardAxis: payload
                    ? payload.visualForwardAxis : null,
                visualYawRadians: preview.visualYawRadians,
                exactCatalogVisual: Boolean(preview.visual),
                sourcePlacementSuppressed: Boolean(
                    preview.hiddenObjects.length
                ),
                duplicateVisiblePlacementCount:
                    payload && preview.hiddenObjects.length ? 0 : 1,
                validationStatus: payload
                    ? payload.validationStatus || 'pending' : null,
                qualification: payload ? (
                    'Manual UI-authored navigation preview. Path geometry is '
                    + 'not a safety, capacity, timing, or compliance approval.'
                ) : null,
            };
        }

        function notifyNavigationPreviewState() {
            const snapshot = navigationPreviewStateSnapshot();
            if (typeof state.navigationPreview.stateHandler === 'function') {
                state.navigationPreview.stateHandler(snapshot, api);
            }
            if (typeof options.onNavigationPreviewStateChange === 'function') {
                options.onNavigationPreviewStateChange(snapshot, api);
            }
            return snapshot;
        }

        function setNavigationPreviewStateHandler(handler) {
            state.navigationPreview.stateHandler = typeof handler === 'function'
                ? handler : null;
            if (state.navigationPreview.stateHandler) {
                notifyNavigationPreviewState();
            }
            return Boolean(state.navigationPreview.stateHandler);
        }

        function disposeNavigationPreview(reason, silent) {
            const hadPreview = Boolean(
                state.navigationPreview.payload
                    || state.navigationPreview.root
            );
            restoreNavigationPreviewPlacement();
            const rootObject = state.navigationPreview.root;
            if (rootObject && rootObject.parent
                    && typeof rootObject.parent.remove === 'function') {
                rootObject.parent.remove(rootObject);
            }
            if (rootObject) disposeObjectGraphs([rootObject]);
            resetNavigationPreviewState(reason || 'disposed');
            if (!silent) notifyNavigationPreviewState();
            if (hadPreview) invalidate();
            return hadPreview;
        }

        function buildNavigationPreviewPath(payload) {
            const color = payload.validationStatus === 'validated'
                ? '#0f8f62' : payload.validationStatus === 'invalid'
                    ? '#c9363e' : '#0878d1';
            const line = leanMotionLine(
                payload.points,
                color,
                'ManualNavigationPath:' + payload.previewId,
                'manual_navigation_path',
                0.98
            );
            const pathRoot = createContainer();
            pathRoot.name = 'FacilityManualNavigationPath';
            pathRoot.userData = pathRoot.userData || {};
            pathRoot.userData.facilityNavigationPreviewId = payload.previewId;
            if (line) pathRoot.add(line);
            pathRoot.visible = state.navigationPreview.pathsVisible !== false;
            return pathRoot;
        }

        async function prepareNavigationPreviewVisual(validated) {
            const placement = validated.placement;
            const key = placement.assetId + '|'
                + placement.assetDefinitionRevision;
            const group = state.baseGroups.get(key);
            if (!group) {
                throw facilityMotionError(
                    'facility_navigation_preview_visual_unavailable',
                    'The selected actor has no catalog visual group.',
                    { placementId: placement.placementId }
                );
            }
            if (!group.resolved) {
                await resolveBaseGroup(
                    group,
                    state.sceneGeneration,
                    state.abortController ? state.abortController.signal : null
                );
            }
            if (group.deferredVisual) {
                await loadDeferredGroup(
                    group,
                    'navigation_preview_exact_visual'
                );
            }
            const record = activityRenderRecord(placement.placementId);
            if (!['overview', 'detail'].includes(record.representation)) {
                throw facilityMotionError(
                    'facility_navigation_preview_exact_visual_unavailable',
                    'Manual motion preview requires the exact catalog GLB; footprint and proxy fallbacks are not animated.',
                    {
                        placementId: placement.placementId,
                        representation: record.representation,
                    }
                );
            }
            return record;
        }

        async function loadNavigationPreview(payload, activeRevision) {
            if (!state.mounted || state.disposed || !state.modelRoot) {
                throw facilityMotionError(
                    'facility_navigation_preview_view_unavailable',
                    'Mount the Facility 3D view before previewing a path.'
                );
            }
            let validated = validateNavigationPreviewPayload(
                payload,
                activeRevision
            );
            const record = await prepareNavigationPreviewVisual(validated);
            validated = validateNavigationPreviewPayload(
                payload,
                activeRevision
            );
            disposeMotion('navigation_preview_loaded', true);
            disposeActivity('navigation_preview_loaded', true);
            disposeNavigationPreview('replaced', true);
            try {
                const rootObject = createContainer();
                rootObject.name = 'FacilityManualNavigationPreview';
                rootObject.userData = rootObject.userData || {};
                rootObject.userData.facilityNavigationPreviewId =
                    validated.payload.previewId;
                const visual = cloneActivityRenderable(
                    record.prototypeObject
                );
                if (!visual) {
                    throw facilityMotionError(
                        'facility_navigation_preview_visual_unavailable',
                        'The exact selected actor visual could not be cloned.'
                    );
                }
                applyVisualSettingsToObject(visual);
                applyPlacementTransform(visual, validated.placement);
                if (visual.position && typeof visual.position.set === 'function') {
                    visual.position.set(0, 0, 0);
                }
                if (visual.quaternion
                        && typeof visual.quaternion.set === 'function') {
                    visual.quaternion.set(0, 0, 0, 1);
                }
                const actorRoot = createContainer();
                actorRoot.name = 'FacilityManualNavigationActor:'
                    + validated.payload.actorPlacementId;
                actorRoot.userData = actorRoot.userData || {};
                actorRoot.userData.facilityNavigationActorPlacementId =
                    validated.payload.actorPlacementId;
                actorRoot.add(visual);
                rootObject.add(actorRoot);
                const pathRoot = buildNavigationPreviewPath(
                    validated.payload
                );
                rootObject.add(pathRoot);
                const hidden = hideActivityPlacement(
                    record,
                    validated.payload.actorPlacementId
                );
                if (!hidden.length) {
                    throw facilityMotionError(
                        'facility_navigation_preview_source_not_hidden',
                        'The stationary actor visual could not be suppressed.'
                    );
                }
                state.navigationPreview.payload = validated.payload;
                state.navigationPreview.root = rootObject;
                state.navigationPreview.pathRoot = pathRoot;
                state.navigationPreview.actorRoot = actorRoot;
                state.navigationPreview.visual = visual;
                state.navigationPreview.placement = validated.placement;
                state.navigationPreview.hiddenObjects = hidden;
                state.navigationPreview.playing = false;
                state.navigationPreview.poseDirty = true;
                state.navigationPreview.normalizedTime = 0;
                state.navigationPreview.lastFrameTime = null;
                state.navigationPreview.pathsVisible =
                    validated.payload.pathsVisible !== false;
                state.navigationPreview.durationSeconds = Math.max(
                    1,
                    navigationPreviewRuntime().pathLength(
                        validated.payload.points
                    ) / 1.2
                );
                state.navigationPreview.status = 'ready';
                state.modelRoot.add(rootObject);
                invalidate();
            } catch (error) {
                disposeNavigationPreview(
                    error && error.code
                        ? error.code : 'facility_navigation_preview_load_failed',
                    true
                );
                throw error;
            }
            notifyNavigationPreviewState();
            return navigationPreviewStateSnapshot();
        }

        function updateNavigationPreviewPath(value) {
            if (!state.navigationPreview.payload) return false;
            const source = value && typeof value === 'object' ? value : {};
            const next = Object.assign(
                {},
                state.navigationPreview.payload,
                {
                    points: detachedJson(source.points
                        || state.navigationPreview.payload.points),
                    loopMode: source.loopMode
                        || state.navigationPreview.payload.loopMode,
                    direction: source.direction
                        || state.navigationPreview.payload.direction,
                    validationStatus: source.validationStatus
                        || state.navigationPreview.payload.validationStatus,
                }
            );
            validateNavigationPreviewPayload(
                next,
                next.layoutRevision
            );
            const previous = state.navigationPreview.pathRoot;
            if (previous && previous.parent
                    && typeof previous.parent.remove === 'function') {
                previous.parent.remove(previous);
            }
            if (previous) disposeObjectGraphs([previous]);
            state.navigationPreview.payload = next;
            state.navigationPreview.durationSeconds = Math.max(
                1,
                navigationPreviewRuntime().pathLength(next.points) / 1.2
            );
            const pathRoot = buildNavigationPreviewPath(next);
            pathRoot.visible = state.navigationPreview.pathsVisible !== false;
            state.navigationPreview.pathRoot = pathRoot;
            state.navigationPreview.root.add(pathRoot);
            state.navigationPreview.poseDirty = true;
            invalidate();
            return true;
        }

        function playNavigationPreview() {
            if (!state.navigationPreview.payload) return false;
            state.navigationPreview.playing = true;
            state.navigationPreview.status = 'playing';
            state.navigationPreview.lastFrameTime = null;
            notifyNavigationPreviewState();
            invalidate();
            return true;
        }

        function pauseNavigationPreview() {
            if (!state.navigationPreview.payload) return false;
            state.navigationPreview.playing = false;
            state.navigationPreview.status = 'paused';
            state.navigationPreview.lastFrameTime = null;
            notifyNavigationPreviewState();
            return true;
        }

        function seekNavigationPreview(requestedNormalizedTime) {
            if (!state.navigationPreview.payload) return false;
            state.navigationPreview.normalizedTime = clamp(
                requestedNormalizedTime,
                0,
                1,
                0
            );
            state.navigationPreview.lastFrameTime = null;
            state.navigationPreview.poseDirty = true;
            state.navigationPreview.status = 'paused';
            invalidate();
            return true;
        }

        function setNavigationPreviewRate(requestedRate) {
            if (!state.navigationPreview.payload) return false;
            state.navigationPreview.playbackRateMultiplier = clamp(
                requestedRate,
                0.25,
                4,
                1
            );
            notifyNavigationPreviewState();
            return state.navigationPreview.playbackRateMultiplier;
        }

        function setNavigationPreviewPathsVisible(requested) {
            state.navigationPreview.pathsVisible = requested !== false;
            if (state.navigationPreview.pathRoot) {
                state.navigationPreview.pathRoot.visible =
                    state.navigationPreview.pathsVisible;
            }
            invalidate();
            notifyNavigationPreviewState();
            return state.navigationPreview.pathsVisible;
        }

        function navigationPreviewEffectiveTime(payload, normalizedTime) {
            const value = clamp(normalizedTime, 0, 1, 0);
            if (payload.loopMode === 'out_and_return') {
                return value <= 0.5 ? value * 2 : (1 - value) * 2;
            }
            if (payload.direction === 'reverse') return 1 - value;
            return value;
        }

        function updateNavigationPreview(timestamp) {
            const preview = state.navigationPreview;
            const payload = preview.payload;
            if (!payload || !preview.actorRoot) return false;
            if (preview.playing) {
                if (preview.lastFrameTime === null) {
                    preview.lastFrameTime = finite(timestamp, 0);
                } else {
                    const deltaSeconds = Math.max(
                        0,
                        (finite(timestamp, preview.lastFrameTime)
                            - preview.lastFrameTime) / 1000
                    );
                    preview.lastFrameTime = finite(
                        timestamp,
                        preview.lastFrameTime
                    );
                    const delta = deltaSeconds
                        * preview.playbackRateMultiplier
                        / Math.max(0.001, preview.durationSeconds);
                    const next = preview.normalizedTime + delta;
                    if (payload.loopMode === 'one_way') {
                        preview.normalizedTime = Math.min(1, next);
                        if (preview.normalizedTime >= 1) {
                            preview.playing = false;
                        }
                    } else {
                        preview.normalizedTime = next % 1;
                    }
                    preview.poseDirty = true;
                }
            }
            if (!preview.poseDirty) return preview.playing;
            try {
                const sampleTime = navigationPreviewEffectiveTime(
                    payload,
                    preview.normalizedTime
                );
                const pose = navigationPreviewRuntime()
                    .samplePathAtNormalizedTime(payload.points, sampleTime);
                if (payload.loopMode === 'out_and_return'
                        && preview.normalizedTime > 0.5) {
                    pose.heading = normalizedHeading(pose.heading + Math.PI);
                }
                const heading = activityVisualHeadingOffset(
                    payload.visualForwardAxis
                ) - pose.heading;
                const vertical = finite(
                    preview.placement.transform
                        && preview.placement.transform.position
                        && preview.placement.transform.position.y,
                    0
                );
                if (preview.actorRoot.position
                        && typeof preview.actorRoot.position.set === 'function') {
                    preview.actorRoot.position.set(pose.x, vertical, pose.z);
                }
                if (preview.actorRoot.quaternion
                        && typeof preview.actorRoot.quaternion.set
                            === 'function') {
                    preview.actorRoot.quaternion.set(
                        0,
                        Math.sin(heading / 2),
                        0,
                        Math.cos(heading / 2)
                    );
                }
                preview.actorRoot.visible = true;
                preview.currentPose = Object.assign({}, pose, {
                    normalizedTime: preview.normalizedTime,
                });
                preview.visualYawRadians = normalizedHeading(heading);
                preview.poseDirty = false;
                preview.status = preview.playing ? 'playing' : 'paused';
                notifyNavigationPreviewState();
                return true;
            } catch (error) {
                reportError('facility_navigation_preview_failed', error);
                disposeNavigationPreview(
                    error && error.code
                        ? error.code : 'facility_navigation_preview_failed'
                );
                return false;
            }
        }

        function leanMotionLine(points, color, name, kind, opacity) {
            if (!Array.isArray(points) || points.length < 2) return null;
            const positions = [];
            points.slice(0, -1).forEach(function (point, index) {
                const next = points[index + 1];
                positions.push(
                    finite(point.x, 0), 0.035, finite(point.z, 0),
                    finite(next.x, 0), 0.035, finite(next.z, 0)
                );
            });
            const line = createGridLineObject(
                positions,
                color,
                opacity,
                name,
                'activity-lean-motion',
                9
            );
            if (line) {
                line.userData = line.userData || {};
                line.userData.facilityLeanMotionKind = kind;
            }
            return line;
        }

        function leanMotionDashedLine(
            points,
            color,
            name,
            kind,
            opacity
        ) {
            if (!Array.isArray(points) || points.length < 2) return null;
            const positions = [];
            const dashLength = 0.72;
            const gapLength = 0.42;
            points.slice(0, -1).forEach(function (point, index) {
                const next = points[index + 1];
                const dx = finite(next.x, 0) - finite(point.x, 0);
                const dz = finite(next.z, 0) - finite(point.z, 0);
                const length = Math.hypot(dx, dz);
                if (length <= 0.000001) return;
                let cursor = 0;
                while (cursor < length) {
                    const end = Math.min(length, cursor + dashLength);
                    positions.push(
                        finite(point.x, 0) + dx * cursor / length,
                        0.042,
                        finite(point.z, 0) + dz * cursor / length,
                        finite(point.x, 0) + dx * end / length,
                        0.042,
                        finite(point.z, 0) + dz * end / length
                    );
                    cursor += dashLength + gapLength;
                }
            });
            const line = createGridLineObject(
                positions,
                color,
                opacity,
                name,
                'activity-lean-motion',
                10
            );
            if (line) {
                line.userData = line.userData || {};
                line.userData.facilityLeanMotionKind = kind;
            }
            return line;
        }

        function leanMotionRibbon(
            points,
            color,
            name,
            kind,
            opacity,
            dashed
        ) {
            if (!Array.isArray(points) || points.length < 2) return null;
            const RootType = THREE.Group || THREE.Object3D;
            if (typeof RootType !== 'function') return null;
            const rootObject = new RootType();
            const addSegment = function (start, end) {
                const dx = finite(end.x, 0) - finite(start.x, 0);
                const dz = finite(end.z, 0) - finite(start.z, 0);
                const length = Math.hypot(dx, dz);
                if (length <= 0.000001) return;
                const segment = addFloorPaintRectangle(
                    rootObject,
                    { fillColor: color, opacity: opacity },
                    length,
                    0.18,
                    (finite(start.x, 0) + finite(end.x, 0)) / 2,
                    (finite(start.z, 0) + finite(end.z, 0)) / 2,
                    { color: color, opacity: opacity }
                );
                if (!segment) return;
                segment.position.y = 0.06;
                const radians = -Math.atan2(dz, dx);
                setQuaternion(segment.quaternion, {
                    x: 0,
                    y: Math.sin(radians / 2),
                    z: 0,
                    w: Math.cos(radians / 2),
                });
                segment.renderOrder = 11;
            };
            points.slice(0, -1).forEach(function (point, index) {
                const next = points[index + 1];
                const dx = finite(next.x, 0) - finite(point.x, 0);
                const dz = finite(next.z, 0) - finite(point.z, 0);
                const length = Math.hypot(dx, dz);
                if (!dashed || length <= 0.000001) {
                    addSegment(point, next);
                    return;
                }
                const dashLength = 0.72;
                const gapLength = 0.42;
                for (let cursor = 0; cursor < length;
                        cursor += dashLength + gapLength) {
                    const end = Math.min(length, cursor + dashLength);
                    addSegment({
                        x: finite(point.x, 0) + dx * cursor / length,
                        z: finite(point.z, 0) + dz * cursor / length,
                    }, {
                        x: finite(point.x, 0) + dx * end / length,
                        z: finite(point.z, 0) + dz * end / length,
                    });
                }
            });
            if (!rootObject.children || !rootObject.children.length) return null;
            rootObject.name = name;
            rootObject.userData = rootObject.userData || {};
            rootObject.userData.facilityLeanMotionKind = kind;
            rootObject.userData.facilityActivityPathRibbon = true;
            return rootObject;
        }

        function buildLeanMotionVisual(leanMotion) {
            const rootObject = createContainer();
            rootObject.name = 'FacilityLeanMotionPaths';
            rootObject.userData = rootObject.userData || {};
            rootObject.userData.facilityLeanMotion = true;
            leanMotion.operatorPaths.forEach(function (path) {
                const line = leanMotionLine(
                    path.centerline,
                    '#2563eb',
                    'OperatorPath:' + path.pathId,
                    'operator_path',
                    0.96
                );
                if (line) rootObject.add(line);
            });
            leanMotion.pedestrianConnections.forEach(function (connection) {
                const line = leanMotionDashedLine(
                    connection.centerline,
                    '#0891b2',
                    'PedestrianConnection:' + connection.connectionId,
                    'pedestrian_connection',
                    0.96
                );
                if (line) rootObject.add(line);
            });
            leanMotion.assistanceGates.forEach(function (gate) {
                const center = gate.position;
                const radius = 0.5;
                const circle = [];
                for (let index = 0; index <= 20; index += 1) {
                    const angle = Math.PI * 2 * index / 20;
                    circle.push({
                        x: center.x + Math.cos(angle) * radius,
                        z: center.z + Math.sin(angle) * radius,
                    });
                }
                const line = leanMotionLine(
                    circle,
                    '#06b6d4',
                    'AssistanceGate:' + gate.gateId,
                    'assistance_gate',
                    1
                );
                if (line) rootObject.add(line);
            });
            leanMotion.materialHandoffs.forEach(function (handoff) {
                const line = leanMotionLine(
                    handoff.centerline,
                    '#059669',
                    'MaterialHandoff:' + handoff.handoffId,
                    'material_handoff',
                    0.94
                );
                if (line) rootObject.add(line);
            });
            leanMotion.fifoPoints.forEach(function (point) {
                const center = point.position;
                const radius = 0.42;
                const diamond = [
                    { x: center.x, z: center.z - radius },
                    { x: center.x + radius, z: center.z },
                    { x: center.x, z: center.z + radius },
                    { x: center.x - radius, z: center.z },
                    { x: center.x, z: center.z - radius },
                ];
                const line = leanMotionLine(
                    diamond,
                    '#f59e0b',
                    'FifoPoint:' + point.pointId,
                    'fifo_point',
                    1
                );
                if (line) rootObject.add(line);
            });
            return rootObject;
        }

        function buildNavigationActivityVisual(validated) {
            const rootObject = createContainer();
            rootObject.name = 'FacilityNavigationActivityPaths';
            rootObject.userData = rootObject.userData || {};
            rootObject.userData.facilityNavigationActivity = true;
            const candidatePresentation = validated
                && validated.candidatePresentation;
            const finishedGoodsPresentation = Boolean(
                candidatePresentation
                && Array.isArray(
                    candidatePresentation.finishedGoodsPathLegend
                )
                && candidatePresentation.finishedGoodsPathLegend.length
            );
            const receivingPresentation = Boolean(
                candidatePresentation
                && Array.isArray(candidatePresentation.receivingPathLegend)
                && candidatePresentation.receivingPathLegend.length
            );
            const handlingPresentation = finishedGoodsPresentation
                || receivingPresentation;
            if (!validated || !validated.scenario
                    || (
                        validated.scenario.schemaVersion
                            !== FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION
                        && !candidatePresentation
                    )) {
                return rootObject;
            }
            const evidenceByPlacement = new Map(
                candidatePresentation
                    && Array.isArray(candidatePresentation.programEvidence)
                    ? candidatePresentation.programEvidence.map(function (item) {
                        return [item.actorPlacementId, item];
                    }) : []
            );
            validated.actors.forEach(function (entry) {
                const actorType = entry.actor.actorType;
                const evidence = evidenceByPlacement.get(
                    entry.actor.placementId
                );
                const pathSegments = evidence
                    && Array.isArray(evidence.pathSegments)
                    ? evidence.pathSegments : [];
                const segmentByPackage = new Map(pathSegments.map(
                    function (segment) {
                        return [segment.motionPackageId, segment];
                    }
                ));
                const packages = entry.actor.loopMode === 'closed_path'
                    && Array.isArray(entry.cyclePackages)
                    && entry.cyclePackages.length
                    ? entry.cyclePackages : [entry.package];
                packages.forEach(function (packageValue) {
                    const movement = packageValue.movement;
                    const trajectory = motionTrajectory(movement);
                    if (!trajectory) return;
                    const segment = segmentByPackage.get(
                        packageValue.packageId
                    );
                    const phase = segment && segment.phase;
                    const loadedPhase = [
                        'carry_out',
                        'loaded_putaway',
                        'loaded_dispatch',
                    ].includes(phase);
                    const emptyPhase = [
                        'return_empty',
                        'empty_to_rack',
                    ].includes(phase);
                    const handlingPhase = handlingPresentation && [
                        'finished_goods_pick',
                        'receiving_pick',
                        'loaded_putaway',
                        'return_empty',
                        'empty_to_rack',
                        'loaded_dispatch',
                    ].includes(phase);
                    const color = loadedPhase
                        ? '#d97706' : emptyPhase
                            ? '#059669' : [
                                'finished_goods_pick',
                                'receiving_pick',
                            ].includes(phase)
                                ? '#2563eb' : actorType === 'operator'
                                ? '#2563eb'
                                : actorType === 'mobile_equipment'
                                    ? '#0f8f62' : '#d97706';
                    const lineFactory = emptyPhase
                        ? leanMotionDashedLine : leanMotionLine;
                    const displayPoints = activityDisplayOffsetPoints(
                        trajectory.poses,
                        segment && segment.displayOffsetMeters
                    );
                    const line = (handlingPhase
                        ? leanMotionRibbon : lineFactory)(
                            displayPoints,
                            color,
                            'NavigationJourney:'
                                + (movement.journeySolutionId || movement.routeId),
                            phase ? 'navigation_journey_' + phase
                                : 'navigation_journey',
                            0.96,
                            emptyPhase
                        );
                    if (!line) return;
                    line.userData = line.userData || {};
                    line.userData.facilityActivityPathActorType = actorType;
                    line.userData.facilityActivityActorId = entry.actor.actorId;
                    line.userData.facilityActivityPathPhase = phase || null;
                    line.userData.facilityActivityDisplayOffsetMeters = finite(
                        segment && segment.displayOffsetMeters,
                        0
                    );
                    rootObject.add(line);
                });
            });
            const candidateHandoffs = candidatePresentation
                && Array.isArray(candidatePresentation.handoffs)
                    ? candidatePresentation.handoffs : [];
            candidateHandoffs.forEach(function (handoff) {
                const line = leanMotionLine(
                    handoff.centerline,
                    '#059669',
                    'CandidateHandoff:' + handoff.candidateId,
                    'candidate_handoff',
                    0.94
                );
                if (line) rootObject.add(line);
                [
                    handoff.centerline[0],
                    handoff.centerline[handoff.centerline.length - 1],
                ].forEach(function (center, index) {
                    const radius = 0.42;
                    const diamond = leanMotionLine([
                        { x: center.x, z: center.z - radius },
                        { x: center.x + radius, z: center.z },
                        { x: center.x, z: center.z + radius },
                        { x: center.x - radius, z: center.z },
                        { x: center.x, z: center.z - radius },
                    ], '#f59e0b',
                    'CandidateHandoffEndpoint:' + handoff.candidateId + ':' + index,
                    'candidate_handoff_endpoint', 1);
                    if (diamond) rootObject.add(diamond);
                });
            });
            const intersections = validated.scenario.navigationPresentation
                && validated.scenario.navigationPresentation.pathIntersections;
            (Array.isArray(intersections) ? intersections : []).forEach(
                function (intersection) {
                    const center = intersection.position;
                    const radius = 0.28;
                    const first = leanMotionLine([
                        { x: center.x - radius, z: center.z - radius },
                        { x: center.x + radius, z: center.z + radius },
                    ], '#dc2626', 'PathIntersection:' + intersection.conflictId,
                    'navigation_visual_conflict', 0.95);
                    const second = leanMotionLine([
                        { x: center.x - radius, z: center.z + radius },
                        { x: center.x + radius, z: center.z - radius },
                    ], '#dc2626', 'PathIntersection:' + intersection.conflictId,
                    'navigation_visual_conflict', 0.95);
                    if (first) rootObject.add(first);
                    if (second) rootObject.add(second);
                }
            );
            return rootObject;
        }

        function applyActivityPathVisibility() {
            if (!state.activity.pathRoot) return false;
            const globallyVisible = state.activity.pathsVisible !== false;
            state.activity.pathRoot.visible = globallyVisible;
            if (typeof state.activity.pathRoot.traverse === 'function') {
                state.activity.pathRoot.traverse(function (object) {
                    const actorType = object && object.userData
                        && object.userData.facilityActivityPathActorType;
                    if (!actorType) return;
                    object.visible = globallyVisible
                        && state.activity.visiblePathTypes[actorType] !== false;
                });
            }
            return globallyVisible;
        }

        function validateActivityPayload(payload, activeLayoutRevision) {
            const value = payload && typeof payload === 'object' ? payload : {};
            const scenario = value.scenario;
            const navigationActivity = scenario && scenario.schemaVersion
                === FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION;
            if (!scenario || ![
                FACILITY_ACTIVITY_SCENARIO_SCHEMA_VERSION,
                FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION,
            ].includes(scenario.schemaVersion)) {
                throw facilityMotionError(
                    'facility_activity_scenario_schema_unsupported',
                    'Unsupported Facility activity scenario schema.'
                );
            }
            if (scenario.layoutRevision !== activeLayoutRevision) {
                throw facilityMotionError(
                    'facility_activity_scenario_stale',
                    'The activity scenario does not match the active layout revision.'
                );
            }
            const expectedActivityQualification = navigationActivity
                ? FACILITY_NAVIGATION_ACTIVITY_QUALIFICATION
                : FACILITY_ACTIVITY_SCENARIO_QUALIFICATION;
            if (scenario.qualification !== expectedActivityQualification) {
                throw facilityMotionError(
                    'facility_activity_scenario_qualification_invalid',
                    'The mandatory activity qualification is unavailable or changed.'
                );
            }
            if (!Array.isArray(scenario.actors) || !scenario.actors.length
                    || !value.actorPayloads
                    || typeof value.actorPayloads !== 'object') {
                throw facilityMotionError(
                    'facility_activity_scenario_invalid',
                    'The activity scenario has no replayable actors.'
                );
            }
            const actors = scenario.actors.map(function (actor) {
                const visualAlignment = actor.visualAlignment;
                const pairedLanePackageIds = [
                    actor.returnMotionPackageId,
                    actor.endTransferMotionPackageId,
                    actor.startTransferMotionPackageId,
                ];
                const cyclePackageIds = Array.isArray(
                    actor.cycleMotionPackageIds
                ) ? actor.cycleMotionPackageIds.slice() : null;
                const pairedLanes = actor.repeat
                    && actor.loopMode === 'paired_lanes';
                const pingPong = actor.repeat
                    && actor.loopMode === 'ping_pong';
                const closedPath = actor.repeat
                    && actor.loopMode === 'closed_path';
                const journeyCycle = actor.repeat
                    && actor.loopMode === 'journey_cycle';
                const once = !actor.repeat && actor.loopMode === 'once';
                const endpointTurnSeconds = Number(actor.endpointTurnSeconds);
                if (!visualAlignment
                        || !['+X', '-X', '+Z', '-Z'].includes(
                            visualAlignment.forwardAxis
                        )
                        || visualAlignment.authority
                            !== 'curated_revision_bound_visual_review'
                        || typeof visualAlignment.evidenceArtifact !== 'string'
                        || !visualAlignment.evidenceArtifact
                        || (!pairedLanes && !pingPong && !closedPath
                            && !journeyCycle && !once)
                        || (journeyCycle && !navigationActivity)
                        || !cyclePackageIds
                        || !Number.isFinite(endpointTurnSeconds)
                        || (pingPong && (
                            endpointTurnSeconds < 0.1
                            || endpointTurnSeconds > 10
                        ))
                        || (!pingPong && !closedPath
                            && endpointTurnSeconds !== 0)
                        || (closedPath && (
                            endpointTurnSeconds < 0.1
                            || endpointTurnSeconds > 10
                            || cyclePackageIds.length < 3
                            || cyclePackageIds[0] !== actor.motionPackageId
                            || new Set(cyclePackageIds).size
                                !== cyclePackageIds.length
                        ))
                        || (pairedLanes && pairedLanePackageIds.some(
                            packageId => typeof packageId !== 'string'
                                || !packageId
                        ))
                        || (!pairedLanes && pairedLanePackageIds.some(
                            packageId => packageId !== null
                        ))
                        || (!closedPath && cyclePackageIds.length)) {
                    throw facilityMotionError(
                        'facility_activity_visual_alignment_invalid',
                        'An activity actor has invalid visual alignment or loop timing.',
                        { actorId: actor.actorId }
                    );
                }
                const placement = placementValue(actor.placementId);
                if (!placement
                        || placement.assetId
                            !== actor.assetDefinitionRef.assetId
                        || placement.assetDefinitionRevision
                            !== actor.assetDefinitionRef
                                .assetDefinitionRevision) {
                    throw facilityMotionError(
                        'facility_activity_actor_binding_mismatch',
                        'An activity actor does not match its exact layout identity.',
                        { actorId: actor.actorId }
                    );
                }
                function actorPackage(packageId, requireActorRoute) {
                    const actorPayload = value.actorPayloads[packageId];
                    const validated = validateMotionPayload(
                        actorPayload,
                        activeLayoutRevision
                    );
                    const movement = validated.package.movement;
                    const movementPlacementId = movement.actorPlacementId
                        || movement.vehiclePlacementId;
                    const movementRouteId = movement.movementProgramId
                        || movement.routeId;
                    if (movementPlacementId !== actor.placementId
                            || validated.package.packageId !== packageId
                            || (requireActorRoute !== false
                                && movementRouteId !== actor.routeId)) {
                        throw facilityMotionError(
                            'facility_activity_actor_binding_mismatch',
                            'An activity package does not match its exact actor.',
                            { actorId: actor.actorId, packageId: packageId }
                        );
                    }
                    if (!motionTrajectory(movement)) {
                        throw facilityMotionError(
                            'facility_activity_actor_not_replayable',
                            'An activity actor has no replayable trajectory.',
                            { actorId: actor.actorId, packageId: packageId }
                        );
                    }
                    return validated;
                }
                const outbound = actorPackage(actor.motionPackageId);
                let returnLane = null;
                let endTransfer = null;
                let startTransfer = null;
                let cyclePackages = [];
                if (pairedLanes) {
                    returnLane = actorPackage(actor.returnMotionPackageId);
                    endTransfer = actorPackage(
                        actor.endTransferMotionPackageId
                    );
                    startTransfer = actorPackage(
                        actor.startTransferMotionPackageId
                    );
                    const outboundMovement = outbound.package.movement;
                    const returnMovement = returnLane.package.movement;
                    const endMovement = endTransfer.package.movement;
                    const startMovement = startTransfer.package.movement;
                    const outboundLane = outboundMovement.laneBinding;
                    const pairedLane = returnMovement.laneBinding;
                    const outboundMarkings = outboundLane
                        && outboundLane.sourceMarkingIds;
                    const returnMarkings = pairedLane
                        && pairedLane.sourceMarkingIds;
                    const markingsOverlap = Array.isArray(outboundMarkings)
                        && Array.isArray(returnMarkings)
                        && outboundMarkings.some(id => returnMarkings.includes(id));
                    function boundaryPose(movement, atEnd) {
                        const trajectory = motionTrajectory(movement);
                        return trajectory.poses[
                            atEnd ? trajectory.poses.length - 1 : 0
                        ];
                    }
                    function continuous(left, right) {
                        const dx = finite(left.x, 0) - finite(right.x, 0);
                        const dz = finite(left.z, 0) - finite(right.z, 0);
                        const dh = normalizedHeading(
                            finite(left.heading, 0) - finite(right.heading, 0)
                        );
                        return Math.hypot(dx, dz) <= 1e-5
                            && Math.abs(dh) <= 1e-5;
                    }
                    const profileRevision = outbound.package.movement
                        .vehicleProfileRef.vehicleProfileRevision;
                    if (outboundMovement.outcome !== 'accepted'
                            || returnMovement.outcome !== 'accepted'
                            || endMovement.outcome !== 'accepted'
                            || startMovement.outcome !== 'accepted'
                            || !outboundLane || !pairedLane
                            || outboundLane.status !== 'direction_markings'
                            || pairedLane.status !== 'direction_markings'
                            || outboundLane.travelDirection
                                === pairedLane.travelDirection
                            || !Array.isArray(outboundMarkings)
                            || !outboundMarkings.length
                            || !Array.isArray(returnMarkings)
                            || !returnMarkings.length
                            || markingsOverlap
                            || [returnLane, endTransfer, startTransfer].some(
                                item => item.package.movement.vehicleProfileRef
                                    .vehicleProfileRevision !== profileRevision
                            )
                            || !continuous(
                                boundaryPose(outboundMovement, true),
                                boundaryPose(endMovement, false)
                            )
                            || !continuous(
                                boundaryPose(endMovement, true),
                                boundaryPose(returnMovement, false)
                            )
                            || !continuous(
                                boundaryPose(returnMovement, true),
                                boundaryPose(startMovement, false)
                            )
                            || !continuous(
                                boundaryPose(startMovement, true),
                                boundaryPose(outboundMovement, false)
                            )) {
                        throw facilityMotionError(
                            'facility_activity_paired_lane_binding_invalid',
                            'The paired-lane loop is incomplete or inconsistent.',
                            { actorId: actor.actorId }
                        );
                    }
                }
                if (closedPath) {
                    cyclePackages = cyclePackageIds.map(function (packageId) {
                        return packageId === actor.motionPackageId
                            ? outbound : actorPackage(packageId, false);
                    });
                    function profileRevision(movement) {
                        const reference = movement.actorProfileRef
                            || movement.vehicleProfileRef;
                        return reference && (
                            reference.profileRevision
                            || reference.vehicleProfileRevision
                        );
                    }
                    const outboundProfileRevision = profileRevision(
                        outbound.package.movement
                    );
                    function endpoint(movement, atEnd) {
                        const trajectory = motionTrajectory(movement);
                        return trajectory.poses[
                            atEnd ? trajectory.poses.length - 1 : 0
                        ];
                    }
                    function positionContinuous(left, right) {
                        return Math.hypot(
                            finite(left.x, 0) - finite(right.x, 0),
                            finite(left.z, 0) - finite(right.z, 0)
                        ) <= 1e-5;
                    }
                    const invalidCycle = cyclePackages.some(
                        item => item.package.movement.outcome !== 'accepted'
                            || profileRevision(item.package.movement)
                                !== outboundProfileRevision
                    ) || cyclePackages.some(function (item, index) {
                        const next = cyclePackages[
                            (index + 1) % cyclePackages.length
                        ];
                        return !positionContinuous(
                            endpoint(item.package.movement, true),
                            endpoint(next.package.movement, false)
                        );
                    });
                    if (invalidCycle) {
                        throw facilityMotionError(
                            'facility_activity_closed_path_invalid',
                            'The local operator path is incomplete or inconsistent.',
                            { actorId: actor.actorId }
                        );
                    }
                }
                return {
                    actor: detachedJson(actor),
                    package: outbound.package,
                    returnPackage: returnLane ? returnLane.package : null,
                    endTransferPackage: endTransfer
                        ? endTransfer.package : null,
                    startTransferPackage: startTransfer
                        ? startTransfer.package : null,
                    cyclePackages: cyclePackages.map(function (item) {
                        return item.package;
                    }),
                    profile: outbound.vehicleProfile,
                    placement: placement,
                    record: activityRenderRecord(actor.placementId),
                };
            });
            const leanMotion = scenario.leanMotion;
            const validPoint = point => point
                && Number.isFinite(Number(point.x))
                && Number.isFinite(Number(point.z));
            const actorIds = new Set(actors.map(item => item.actor.actorId));
            const actorById = new Map(actors.map(function (item) {
                return [item.actor.actorId, item.actor];
            }));
            const candidatePresentation = value.candidatePresentation;
            let validatedCandidatePresentation = null;
            if (candidatePresentation !== undefined
                    && candidatePresentation !== null) {
                const counts = candidatePresentation.candidateCounts;
                const handoffs = candidatePresentation.handoffs;
                const suppressedOperatorPlacementIds =
                    candidatePresentation.suppressedOperatorPlacementIds;
                const parkedVehiclePlacementIds =
                    candidatePresentation.parkedVehiclePlacementIds;
                const actorPlacementIds = new Set(actors.map(function (item) {
                    return item.actor.placementId;
                }));
                const programEvidence = candidatePresentation.programEvidence;
                const programEvidenceValid = programEvidence === undefined
                    || (Array.isArray(programEvidence)
                        && programEvidence.every(function (evidence) {
                            const entry = actors.find(function (item) {
                                return item.actor.placementId
                                    === evidence.actorPlacementId;
                            });
                            const segments = evidence.pathSegments;
                            if (!entry || !Array.isArray(segments)
                                    || !segments.length) return false;
                            const packageIds = new Set([
                                entry.actor.motionPackageId,
                                ...entry.actor.cycleMotionPackageIds,
                            ]);
                            return segments.every(function (segment) {
                                return segment
                                    && [
                                        'carry_in',
                                        'carry_out',
                                        'inspection_pick',
                                        'inspection_place',
                                        'return_empty',
                                        'candidate_loop',
                                        'finished_goods_pick',
                                        'receiving_pick',
                                        'loaded_putaway',
                                        'empty_to_rack',
                                        'loaded_dispatch',
                                    ].includes(segment.phase)
                                    && packageIds.has(segment.motionPackageId)
                                    && Number.isFinite(
                                        Number(segment.distanceMeters)
                                    )
                                    && Number.isInteger(segment.turnCount);
                            })
                                && Number.isFinite(Number(
                                    evidence.interactionPauseSeconds
                                ))
                                && evidence.timingAuthority
                                    === 'derived_display_only';
                        }));
                const pathLegend = candidatePresentation.packagingPathLegend;
                const pathLegendValid = pathLegend === undefined
                    || (Array.isArray(pathLegend)
                        && pathLegend.length === 3
                        && pathLegend.map(item => item.phase).join('|')
                            === 'carry_in|carry_out|return_empty'
                        && pathLegend.every(function (item) {
                            return item
                                && typeof item.label === 'string'
                                && item.label.length > 0
                                && ['solid', 'dashed'].includes(
                                    item.lineStyle
                                );
                        }));
                const inspectionPathLegend =
                    candidatePresentation.inspectionPathLegend;
                const inspectionPathLegendValid =
                    inspectionPathLegend === undefined
                    || (Array.isArray(inspectionPathLegend)
                        && inspectionPathLegend.length === 3
                        && inspectionPathLegend.map(item => item.phase).join('|')
                            === 'inspection_pick|inspection_place|return_empty'
                        && inspectionPathLegend.every(function (item) {
                            return item
                                && typeof item.label === 'string'
                                && item.label.length > 0
                                && ['solid', 'dashed'].includes(
                                    item.lineStyle
                                );
                        }));
                const finishedGoodsPathLegend =
                    candidatePresentation.finishedGoodsPathLegend;
                const finishedGoodsPathLegendValid =
                    finishedGoodsPathLegend === undefined
                    || (Array.isArray(finishedGoodsPathLegend)
                        && [2, 3].includes(finishedGoodsPathLegend.length)
                        && finishedGoodsPathLegend.every(function (item) {
                            return item
                                && [
                                    'finished_goods_pick',
                                    'loaded_putaway',
                                    'return_empty',
                                    'empty_to_rack',
                                    'loaded_dispatch',
                                ].includes(item.phase)
                                && typeof item.label === 'string'
                                && item.label.length > 0
                                && ['solid', 'dashed'].includes(
                                    item.lineStyle
                                );
                        }));
                const receivingPathLegend =
                    candidatePresentation.receivingPathLegend;
                const receivingPathLegendValid =
                    receivingPathLegend === undefined
                    || (Array.isArray(receivingPathLegend)
                        && receivingPathLegend.map(item => item.phase).join('|')
                            === 'receiving_pick|loaded_putaway|return_empty'
                        && receivingPathLegend.every(function (item) {
                            return item
                                && typeof item.label === 'string'
                                && item.label.length > 0
                                && ['solid', 'dashed'].includes(
                                    item.lineStyle
                                );
                        }));
                const parkedVehiclePlacementIdsValid =
                    parkedVehiclePlacementIds === undefined
                    || (Array.isArray(parkedVehiclePlacementIds)
                        && new Set(parkedVehiclePlacementIds).size
                            === parkedVehiclePlacementIds.length
                        && parkedVehiclePlacementIds.every(function (
                            placementId
                        ) {
                            return typeof placementId === 'string'
                                && placementId.length > 0
                                && !actorPlacementIds.has(placementId)
                                && Boolean(placementValue(placementId));
                        }));
                const candidateValid = candidatePresentation.schemaVersion
                        === 'facility-reference-movement-candidates-v1'
                    && typeof candidatePresentation.sourceLayoutId === 'string'
                    && candidatePresentation.sourceLayoutId.length > 0
                    && /^[a-f0-9]{64}$/.test(
                        candidatePresentation.sourceLayoutRevision || ''
                    )
                    && candidatePresentation.authority === 'inferred_candidate'
                    && candidatePresentation.reviewStatus === 'pending'
                    && candidatePresentation.productionEligible === false
                    && counts && typeof counts === 'object'
                    && [
                        counts.operators,
                        counts.vehicles,
                        counts.handoffs,
                        counts.displayedActors,
                        counts.displayedHandoffs,
                        counts.unavailableActors,
                        counts.partialPrograms,
                        counts.suppressedStationaryOperators,
                    ].every(item => Number.isInteger(item) && item >= 0)
                    && counts.displayedActors === actors.length
                    && programEvidenceValid
                    && pathLegendValid
                    && inspectionPathLegendValid
                    && finishedGoodsPathLegendValid
                    && receivingPathLegendValid
                    && parkedVehiclePlacementIdsValid
                    && Array.isArray(suppressedOperatorPlacementIds)
                    && counts.suppressedStationaryOperators
                        === suppressedOperatorPlacementIds.length
                    && new Set(suppressedOperatorPlacementIds).size
                        === suppressedOperatorPlacementIds.length
                    && suppressedOperatorPlacementIds.every(function (
                        placementId
                    ) {
                        const placement = placementValue(placementId);
                        return typeof placementId === 'string'
                            && placementId.length > 0
                            && !actorPlacementIds.has(placementId)
                            && placement
                            && placement.assetId === 'asset-operator';
                    })
                    && Array.isArray(handoffs)
                    && counts.displayedHandoffs === handoffs.length
                    && handoffs.every(function (handoff) {
                        return handoff
                            && typeof handoff.candidateId === 'string'
                            && handoff.candidateId.length > 0
                            && actorIds.has(handoff.fromActorId)
                            && actorIds.has(handoff.toActorId)
                            && handoff.fromActorId !== handoff.toActorId
                            && typeof handoff.fromZoneId === 'string'
                            && handoff.fromZoneId.length > 0
                            && typeof handoff.toZoneId === 'string'
                            && handoff.toZoneId.length > 0
                            && Array.isArray(handoff.centerline)
                            && handoff.centerline.length >= 2
                            && handoff.centerline.every(validPoint)
                            && handoff.evidenceStatus === 'derived'
                            && handoff.reviewStatus === 'pending'
                            && handoff.productionEligible === false;
                    })
                    && typeof candidatePresentation.qualification === 'string'
                    && candidatePresentation.qualification.length > 0
                    && /^[a-f0-9]{64}$/.test(
                        candidatePresentation.presentationFingerprint || ''
                    );
                if (!candidateValid) {
                    throw facilityMotionError(
                        'facility_activity_candidate_presentation_invalid',
                        'The reference movement-candidate presentation is incomplete or over-authoritative.'
                    );
                }
                validatedCandidatePresentation = detachedJson(
                    candidatePresentation
                );
            }
            const operatorPathById = new Map(
                (leanMotion && Array.isArray(leanMotion.operatorPaths)
                    ? leanMotion.operatorPaths : []).map(function (path) {
                    return [path.pathId, path];
                })
            );
            const fifoPointById = new Map(
                (leanMotion && Array.isArray(leanMotion.fifoPoints)
                    ? leanMotion.fifoPoints : []).map(function (point) {
                    return [point.pointId, point];
                })
            );
            const connectionById = new Map(
                (leanMotion && Array.isArray(leanMotion.pedestrianConnections)
                    ? leanMotion.pedestrianConnections : []).map(
                    function (connection) {
                        return [connection.connectionId, connection];
                    }
                )
            );
            const handoffIds = new Set(
                (leanMotion && Array.isArray(leanMotion.materialHandoffs)
                    ? leanMotion.materialHandoffs : []).map(function (handoff) {
                    return handoff.handoffId;
                })
            );
            const leanValid = leanMotion
                && leanMotion.schemaVersion
                    === FACILITY_LEAN_MOTION_SCHEMA_VERSION
                && leanMotion.qualification
                    === FACILITY_LEAN_MOTION_QUALIFICATION
                && leanMotion.evidenceStatus === 'derived'
                && Array.isArray(leanMotion.operatorPaths)
                && Array.isArray(leanMotion.pedestrianConnections)
                && Array.isArray(leanMotion.assistanceGates)
                && Array.isArray(leanMotion.materialHandoffs)
                && Array.isArray(leanMotion.fifoPoints)
                && leanMotion.operatorPaths.every(path => path
                    && actorIds.has(path.actorId)
                    && path.closed === true
                    && path.evidenceStatus === 'derived'
                    && Number.isInteger(path.segmentIndex)
                    && Number.isInteger(path.segmentCount)
                    && path.segmentIndex >= 0
                    && path.segmentCount > path.segmentIndex
                    && Array.isArray(path.assignedPlacementIds)
                    && Array.isArray(path.centerline)
                    && path.centerline.length >= 4
                    && path.centerline.every(validPoint)
                    && JSON.stringify(path.centerline[0])
                        === JSON.stringify(
                            path.centerline[path.centerline.length - 1]
                        ))
                && leanMotion.pedestrianConnections.every(connection => connection
                    && connection.evidenceStatus === 'derived'
                    && connection.closed === true
                    && actorIds.has(connection.actorId)
                    && operatorPathById.has(connection.pathId)
                    && operatorPathById.get(connection.pathId).actorId
                        === connection.actorId
                    && actorById.get(connection.actorId).actorType === 'operator'
                    && fifoPointById.has(connection.fifoPointId)
                    && Array.isArray(connection.handoffIds)
                    && connection.handoffIds.length >= 1
                    && connection.handoffIds.every(id => handoffIds.has(id))
                    && Array.isArray(connection.motionPackageIds)
                    && connection.motionPackageIds.length === 2
                    && connection.motionPackageIds.every(id =>
                        actorById.get(connection.actorId)
                            .cycleMotionPackageIds.includes(id))
                    && Array.isArray(connection.centerline)
                    && connection.centerline.length >= 3
                    && connection.centerline.every(validPoint)
                    && JSON.stringify(connection.centerline[0])
                        === JSON.stringify(connection.centerline[
                            connection.centerline.length - 1
                        ])
                    && connection.centerline.some(point => JSON.stringify(point)
                        === JSON.stringify(
                            fifoPointById.get(connection.fifoPointId).position
                        )))
                && leanMotion.assistanceGates.every(gate => gate
                    && gate.evidenceStatus === 'derived'
                    && Array.isArray(gate.participantPathIds)
                    && gate.participantPathIds.length === 2
                    && Array.isArray(gate.participantActorIds)
                    && gate.participantActorIds.length === 2
                    && validPoint(gate.position))
                && leanMotion.materialHandoffs.every(handoff => handoff
                    && handoff.evidenceStatus === 'derived'
                    && actorIds.has(handoff.fromActorId)
                    && actorIds.has(handoff.toActorId)
                    && handoff.fromActorId !== handoff.toActorId
                    && operatorPathById.has(handoff.fromPathId)
                    && operatorPathById.has(handoff.toPathId)
                    && operatorPathById.get(handoff.fromPathId).actorId
                        === handoff.fromActorId
                    && operatorPathById.get(handoff.toPathId).actorId
                        === handoff.toActorId
                    && connectionById.has(handoff.fromConnectionId)
                    && connectionById.has(handoff.toConnectionId)
                    && connectionById.get(handoff.fromConnectionId).fifoPointId
                        === handoff.fromPointId
                    && connectionById.get(handoff.toConnectionId).fifoPointId
                        === handoff.toPointId
                    && Array.isArray(handoff.centerline)
                    && handoff.centerline.length >= 2
                    && handoff.centerline.every(validPoint)
                    && fifoPointById.has(handoff.fromPointId)
                    && fifoPointById.has(handoff.toPointId)
                    && JSON.stringify(handoff.centerline[0])
                        === JSON.stringify(
                            fifoPointById.get(handoff.fromPointId).position
                        )
                    && JSON.stringify(handoff.centerline[
                        handoff.centerline.length - 1
                    ]) === JSON.stringify(
                        fifoPointById.get(handoff.toPointId).position
                    ))
                && leanMotion.fifoPoints.every(point => point
                    && point.evidenceStatus === 'derived'
                    && validPoint(point.position));
            if (!leanValid) {
                throw facilityMotionError(
                    'facility_activity_lean_motion_invalid',
                    'The derived lean-motion presentation is incomplete.'
                );
            }
            if (navigationActivity) {
                const presentation = scenario.navigationPresentation;
                const phaseByActor = new Map(
                    presentation && Array.isArray(presentation.phaseOffsets)
                        ? presentation.phaseOffsets.map(item => [item.actorId, item])
                        : []
                );
                const bindingByActor = new Map(
                    presentation && Array.isArray(presentation.pathBindings)
                        ? presentation.pathBindings.map(item => [item.actorId, item])
                        : []
                );
                const navigationValid = presentation
                    && presentation.schemaVersion
                        === 'facility-navigation-presentation-v1'
                    && presentation.qualification
                        === FACILITY_NAVIGATION_PRESENTATION_QUALIFICATION
                    && presentation.sharedClock === true
                    && presentation.processTimingClaimed === false
                    && presentation.generatedCollisionAvoidanceOffsets === false
                    && phaseByActor.size === actors.length
                    && bindingByActor.size === actors.length
                    && actors.every(function (entry) {
                        const actor = entry.actor;
                        const phase = phaseByActor.get(actor.actorId);
                        const binding = bindingByActor.get(actor.actorId);
                        return phase && binding
                            && Number(phase.offsetSeconds)
                                === Number(actor.startOffsetSeconds)
                            && (phase.authority !== 'none'
                                || Number(phase.offsetSeconds) === 0)
                            && binding.motionPackageId
                                === actor.motionPackageId
                            && binding.journeySolutionId
                                === (entry.package.movement.journeySolutionId
                                    || entry.package.movement.movementId);
                    });
                if (!navigationValid) {
                    throw facilityMotionError(
                        'facility_activity_navigation_presentation_invalid',
                        'The navigation presentation is incomplete or rescheduled.'
                    );
                }
            }
            return {
                scenario: detachedJson(scenario),
                actorPayloads: detachedJson(value.actorPayloads),
                actors: actors,
                candidatePresentation: validatedCandidatePresentation,
            };
        }

        async function prepareActivityActorVisuals(validated) {
            const groups = new Map();
            validated.actors.forEach(function (value) {
                const reference = value.actor.assetDefinitionRef;
                const key = reference.assetId + '|'
                    + reference.assetDefinitionRevision;
                const group = state.baseGroups.get(key);
                if (!group) {
                    throw facilityMotionError(
                        'facility_activity_actor_visual_unavailable',
                        'The exact catalog visual group is unavailable for an activity actor.',
                        { actorId: value.actor.actorId }
                    );
                }
                groups.set(key, group);
            });
            const keys = Array.from(groups.keys()).sort();
            let nextKeyIndex = 0;
            const workerCount = Math.min(4, keys.length);
            await Promise.all(Array.from(
                { length: workerCount },
                async function () {
                    while (nextKeyIndex < keys.length) {
                        const keyIndex = nextKeyIndex;
                        nextKeyIndex += 1;
                        const group = groups.get(keys[keyIndex]);
                        if (group.deferredVisual) {
                            await loadDeferredGroup(
                                group,
                                'activity_actor_exact_visual'
                            );
                        }
                    }
                }
            ));
            validated.actors.forEach(function (value) {
                const record = activityRenderRecord(
                    value.actor.placementId
                );
                if (!['overview', 'detail'].includes(record.representation)) {
                    throw facilityMotionError(
                        'facility_activity_actor_exact_visual_unavailable',
                        'Activity playback requires the exact catalog GLB; footprint and proxy fallbacks are not animated.',
                        {
                            actorId: value.actor.actorId,
                            placementId: value.actor.placementId,
                            representation: record.representation,
                        }
                    );
                }
            });
        }

        async function loadActivityScenario(payload, activeLayoutRevision) {
            if (!state.mounted || state.disposed || !state.modelRoot) {
                throw facilityMotionError(
                    'facility_activity_view_unavailable',
                    'Mount the Facility 3D view before loading activity.'
                );
            }
            let validated = validateActivityPayload(
                payload,
                activeLayoutRevision
            );
            await prepareActivityActorVisuals(validated);
            validated = validateActivityPayload(
                payload,
                activeLayoutRevision
            );
            disposeMotion('activity_loaded', true);
            disposeNavigationPreview('activity_loaded', true);
            disposeActivity('replaced', true);
            try {
                const activityRoot = createContainer();
                activityRoot.name = 'FacilityActivityPlayback';
                activityRoot.userData = activityRoot.userData || {};
                activityRoot.userData.facilityActivityScenarioId =
                    validated.scenario.scenarioId;
                state.activity.scenario = validated.scenario;
                state.activity.actorPayloads = validated.actorPayloads;
                state.activity.candidatePresentation =
                    validated.candidatePresentation;
                state.activity.root = activityRoot;
                state.activity.status = 'ready';
                state.activity.poseDirty = true;
                state.activity.elapsedSeconds = 0;
                state.activity.lastFrameTime = null;
                const pathRoot = buildLeanMotionVisual(
                    validated.scenario.leanMotion
                );
                if (validated.scenario.schemaVersion
                        === FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION
                        || validated.candidatePresentation) {
                    const navigationPathRoot = buildNavigationActivityVisual(
                        validated
                    );
                    if (navigationPathRoot) pathRoot.add(navigationPathRoot);
                }
                activityRoot.add(pathRoot);
                state.activity.pathRoot = pathRoot;
                applyActivityPathVisibility();
                validated.actors.forEach(function (value) {
                    const visual = cloneActivityRenderable(
                        value.record.prototypeObject
                    );
                    if (!visual) {
                        throw facilityMotionError(
                            'facility_activity_actor_visual_unavailable',
                            'The exact catalog visual could not be cloned.',
                            { actorId: value.actor.actorId }
                        );
                    }
                    applyVisualSettingsToObject(visual);
                    applyPlacementTransform(visual, value.placement);
                    if (visual.position && typeof visual.position.set
                            === 'function') {
                        visual.position.set(0, 0, 0);
                    }
                    if (visual.quaternion && typeof visual.quaternion.set
                            === 'function') {
                        visual.quaternion.set(0, 0, 0, 1);
                    }
                    const actorRoot = createContainer();
                    actorRoot.name = 'FacilityActivityActor:'
                        + value.actor.actorId;
                    actorRoot.visible = false;
                    actorRoot.userData = actorRoot.userData || {};
                    actorRoot.userData.facilityActivityActorId =
                        value.actor.actorId;
                    actorRoot.userData.facilityActivityActorType =
                        value.actor.actorType;
                    actorRoot.userData.facilityActivityPlacementId =
                        value.actor.placementId;
                    actorRoot.add(visual);
                    activityRoot.add(actorRoot);
                    const hiddenSource = hideActivityPlacement(
                        value.record,
                        value.actor.placementId
                    );
                    if (!hiddenSource.length) {
                        throw facilityMotionError(
                            'facility_activity_actor_source_not_hidden',
                            'The existing actor visual could not be borrowed for playback.',
                            { placementId: value.actor.placementId }
                        );
                    }
                    state.activity.hiddenObjects =
                        state.activity.hiddenObjects.concat(hiddenSource);
                    state.activity.tracks.push({
                        actor: value.actor,
                        package: value.package,
                        returnPackage: value.returnPackage,
                        endTransferPackage: value.endTransferPackage,
                        startTransferPackage: value.startTransferPackage,
                        cyclePackages: value.cyclePackages,
                        profile: value.profile,
                        placement: value.placement,
                        root: actorRoot,
                        visual: visual,
                        currentPose: null,
                        localElapsedSeconds: 0,
                        playbackPhase: 'waiting',
                        travelDirection: 'outbound',
                        currentMotionPackageId: value.package.packageId,
                        visualYawRadians: null,
                        sourcePlacementHidden: true,
                    });
                });
                const suppressedOperatorPlacementIds =
                    validated.candidatePresentation
                    && validated.candidatePresentation
                        .suppressedOperatorPlacementIds;
                if (Array.isArray(suppressedOperatorPlacementIds)) {
                    suppressedOperatorPlacementIds.forEach(function (
                        placementId
                    ) {
                        const hiddenSource = hideActivityPlacement(
                            activityRenderRecord(placementId),
                            placementId
                        );
                        if (!hiddenSource.length) {
                            throw facilityMotionError(
                                'facility_activity_stationary_operator_not_hidden',
                                'A stationary operator visual could not be suppressed for activity playback.',
                                { placementId: placementId }
                            );
                        }
                        state.activity.hiddenObjects =
                            state.activity.hiddenObjects.concat(hiddenSource);
                    });
                }
                state.activity.selectedActorId =
                    state.activity.tracks[0].actor.actorId;
                state.modelRoot.add(activityRoot);
                invalidate();
            } catch (error) {
                disposeActivity(
                    error && error.code
                        ? error.code : 'facility_activity_load_failed',
                    true
                );
                throw error;
            }
            notifyActivityState();
            return activityStateSnapshot();
        }

        function activityTrackVisible(track, active) {
            if (!active || state.activity.visibleActorTypes[
                track.actor.actorType
            ] === false) return false;
            const filter = state.activity.departmentZoneId;
            return !filter || track.actor.departmentZoneIds.includes(filter);
        }

        function activityTrackTime(track, scenarioSeconds) {
            const movement = track.package.movement;
            const duration = motionDurationSeconds(movement);
            const shifted = scenarioSeconds
                - finite(track.actor.startOffsetSeconds, 0);
            if (shifted < 0) {
                return {
                    active: false,
                    elapsed: 0,
                    duration: duration,
                    headingOffset: 0,
                    phase: 'waiting',
                    direction: 'outbound',
                    movement: movement,
                    motionPackageId: track.package.packageId,
                };
            }
            if (track.actor.repeat && track.actor.loopMode === 'closed_path') {
                const turnDuration = Math.max(
                    0.1,
                    finite(track.actor.endpointTurnSeconds, 0.45)
                );
                const packages = track.cyclePackages || [];
                const segments = packages.map(function (packageValue, index) {
                    return {
                        package: packageValue,
                        duration: motionDurationSeconds(packageValue.movement),
                        index: index,
                    };
                });
                const cycleDuration = segments.reduce(
                    (total, segment) => total + segment.duration + turnDuration,
                    0
                );
                let phaseTime = shifted % cycleDuration;
                for (let index = 0; index < segments.length; index += 1) {
                    const segment = segments[index];
                    if (phaseTime < segment.duration) {
                        return {
                            active: true,
                            elapsed: phaseTime,
                            duration: segment.duration,
                            headingOffset: 0,
                            phase: 'local_path_' + (index + 1),
                            direction: 'local_loop',
                            movement: segment.package.movement,
                            motionPackageId: segment.package.packageId,
                        };
                    }
                    phaseTime -= segment.duration;
                    if (phaseTime < turnDuration) {
                        const next = segments[(index + 1) % segments.length];
                        const priorTrajectory = motionTrajectory(
                            segment.package.movement
                        );
                        const nextTrajectory = motionTrajectory(
                            next.package.movement
                        );
                        const priorPose = priorTrajectory.poses[
                            priorTrajectory.poses.length - 1
                        ];
                        const nextPose = nextTrajectory.poses[0];
                        const turnDelta = normalizedHeading(
                            finite(nextPose.heading, 0)
                            - finite(priorPose.heading, 0)
                        );
                        return {
                            active: true,
                            elapsed: segment.duration,
                            duration: segment.duration,
                            headingOffset: turnDelta
                                * (phaseTime / turnDuration),
                            phase: 'local_turn_' + (index + 1),
                            direction: 'turning',
                            movement: segment.package.movement,
                            motionPackageId: segment.package.packageId,
                        };
                    }
                    phaseTime -= turnDuration;
                }
            }
            if (track.actor.repeat && track.actor.loopMode === 'journey_cycle'
                    && duration > 0) {
                return {
                    active: true,
                    elapsed: shifted % duration,
                    duration: duration,
                    headingOffset: 0,
                    phase: 'journey_cycle',
                    direction: 'authored_cycle',
                    movement: movement,
                    motionPackageId: track.package.packageId,
                };
            }
            if (track.actor.repeat && track.actor.loopMode === 'paired_lanes') {
                const segments = [
                    {
                        package: track.package,
                        phase: 'outbound',
                        direction: 'outbound',
                    },
                    {
                        package: track.endTransferPackage,
                        phase: 'lane_change_at_end',
                        direction: 'turning',
                    },
                    {
                        package: track.returnPackage,
                        phase: 'return',
                        direction: 'return',
                    },
                    {
                        package: track.startTransferPackage,
                        phase: 'lane_change_at_start',
                        direction: 'turning',
                    },
                ].map(function (segment) {
                    return Object.assign({}, segment, {
                        duration: motionDurationSeconds(
                            segment.package.movement
                        ),
                    });
                });
                const cycleDuration = segments.reduce(
                    (total, segment) => total + segment.duration,
                    0
                );
                let phaseTime = shifted % cycleDuration;
                for (let index = 0; index < segments.length; index += 1) {
                    const segment = segments[index];
                    if (phaseTime < segment.duration
                            || index === segments.length - 1) {
                        return {
                            active: true,
                            elapsed: Math.min(phaseTime, segment.duration),
                            duration: segment.duration,
                            headingOffset: 0,
                            phase: segment.phase,
                            direction: segment.direction,
                            movement: segment.package.movement,
                            motionPackageId: segment.package.packageId,
                        };
                    }
                    phaseTime -= segment.duration;
                }
            }
            if (track.actor.repeat && track.actor.loopMode === 'ping_pong'
                    && duration > 0) {
                const turnDuration = Math.max(
                    0.1,
                    finite(track.actor.endpointTurnSeconds, 1)
                );
                const cycleDuration = 2 * duration + 2 * turnDuration;
                const phaseTime = shifted % cycleDuration;
                if (phaseTime < duration) {
                    return {
                        active: true,
                        elapsed: phaseTime,
                        duration: duration,
                        headingOffset: 0,
                        phase: 'outbound',
                        direction: 'outbound',
                        movement: movement,
                        motionPackageId: track.package.packageId,
                    };
                }
                if (phaseTime < duration + turnDuration) {
                    const turnRatio = (phaseTime - duration) / turnDuration;
                    return {
                        active: true,
                        elapsed: duration,
                        duration: duration,
                        headingOffset: Math.PI * turnRatio,
                        phase: 'turn_at_end',
                        direction: 'turning',
                        movement: movement,
                        motionPackageId: track.package.packageId,
                    };
                }
                if (phaseTime < 2 * duration + turnDuration) {
                    const returnElapsed = phaseTime - duration - turnDuration;
                    return {
                        active: true,
                        elapsed: duration - returnElapsed,
                        duration: duration,
                        headingOffset: Math.PI,
                        phase: 'return',
                        direction: 'return',
                        movement: movement,
                        motionPackageId: track.package.packageId,
                    };
                }
                const turnRatio = (
                    phaseTime - 2 * duration - turnDuration
                ) / turnDuration;
                return {
                    active: true,
                    elapsed: 0,
                    duration: duration,
                    headingOffset: Math.PI * (1 - turnRatio),
                    phase: 'turn_at_start',
                    direction: 'turning',
                    movement: movement,
                    motionPackageId: track.package.packageId,
                };
            }
            return {
                active: true,
                elapsed: Math.min(shifted, duration),
                duration: duration,
                headingOffset: 0,
                phase: shifted >= duration ? 'complete' : 'outbound',
                direction: 'outbound',
                movement: movement,
                motionPackageId: track.package.packageId,
            };
        }

        function updateActivity(timestamp) {
            const scenario = state.activity.scenario;
            if (!scenario || !state.activity.root) return false;
            const duration = Math.max(
                0.001,
                finite(scenario.cycleDurationSeconds, 0.001)
            );
            if (state.activity.playing) {
                if (state.activity.lastFrameTime === null) {
                    state.activity.lastFrameTime = finite(timestamp, 0);
                } else {
                    const deltaSeconds = Math.max(
                        0,
                        (finite(timestamp, state.activity.lastFrameTime)
                            - state.activity.lastFrameTime) / 1000
                    );
                    state.activity.lastFrameTime = finite(
                        timestamp,
                        state.activity.lastFrameTime
                    );
                    const advanced = state.activity.elapsedSeconds
                        + deltaSeconds
                            * state.activity.playbackRateMultiplier;
                    state.activity.elapsedSeconds = scenario.repeat
                        ? advanced % duration : Math.min(duration, advanced);
                    state.activity.poseDirty = true;
                }
            }
            if (!state.activity.poseDirty) return state.activity.playing;
            try {
                state.activity.tracks.forEach(function (track) {
                    const timing = activityTrackTime(
                        track,
                        state.activity.elapsedSeconds
                    );
                    track.localElapsedSeconds = timing.elapsed;
                    track.playbackPhase = timing.phase;
                    track.travelDirection = timing.direction;
                    track.currentMotionPackageId = timing.motionPackageId;
                    if (!timing.active) {
                        track.root.visible = false;
                        track.currentPose = null;
                        track.visualYawRadians = null;
                        return;
                    }
                    const movement = timing.movement;
                    const distance = motionDistanceAtTime(
                        movement,
                        timing.elapsed
                    );
                    const sampledPose = sampleFacilityMotionAtDistance(
                        movement,
                        distance
                    );
                    const pose = Object.assign({}, sampledPose, {
                        heading: normalizedHeading(
                            sampledPose.heading + timing.headingOffset
                        ),
                    });
                    const heading = activityVisualHeadingOffset(
                        track.actor.visualAlignment.forwardAxis
                    ) - pose.heading;
                    const vertical = finite(
                        track.placement.transform
                            && track.placement.transform.position
                            && track.placement.transform.position.y,
                        0
                    );
                    if (track.root.position
                            && typeof track.root.position.set === 'function') {
                        track.root.position.set(pose.x, vertical, pose.z);
                    }
                    if (track.root.quaternion
                            && typeof track.root.quaternion.set === 'function') {
                        track.root.quaternion.set(
                            0,
                            Math.sin(heading / 2),
                            0,
                            Math.cos(heading / 2)
                        );
                    }
                    track.root.visible = activityTrackVisible(track, true);
                    track.currentPose = pose;
                    track.visualYawRadians = normalizedHeading(heading);
                });
                state.activity.poseDirty = false;
                state.activity.status = state.activity.playing
                    ? 'playing' : 'paused';
                notifyActivityState();
                return true;
            } catch (error) {
                reportError('facility_activity_playback_failed', error);
                disposeActivity(
                    error && error.code
                        ? error.code : 'facility_activity_playback_failed'
                );
                return false;
            }
        }

        function playActivity() {
            if (!state.activity.scenario) return false;
            state.activity.playing = true;
            state.activity.status = 'playing';
            state.activity.lastFrameTime = null;
            notifyActivityState();
            invalidate();
            return true;
        }

        function pauseActivity() {
            if (!state.activity.scenario) return false;
            state.activity.playing = false;
            state.activity.status = 'paused';
            state.activity.lastFrameTime = null;
            notifyActivityState();
            return true;
        }

        function seekActivity(requestedSeconds) {
            if (!state.activity.scenario) return false;
            state.activity.elapsedSeconds = clamp(
                requestedSeconds,
                0,
                finite(state.activity.scenario.cycleDurationSeconds, 0),
                0
            );
            state.activity.lastFrameTime = null;
            state.activity.poseDirty = true;
            state.activity.status = 'paused';
            invalidate();
            return true;
        }

        function setActivityRate(requestedRate) {
            if (!state.activity.scenario) return false;
            state.activity.playbackRateMultiplier = clamp(
                requestedRate,
                0.25,
                4,
                DEFAULT_MOTION_PLAYBACK_RATE
            );
            notifyActivityState();
            return state.activity.playbackRateMultiplier;
        }

        function setActivityActorTypeVisible(actorType, requested) {
            if (!['vehicle', 'operator', 'mobile_equipment'].includes(actorType)) {
                return false;
            }
            state.activity.visibleActorTypes[actorType] = requested !== false;
            state.activity.poseDirty = true;
            invalidate();
            return true;
        }

        function setActivityPathsVisible(requested) {
            state.activity.pathsVisible = requested !== false;
            applyActivityPathVisibility();
            invalidate();
            notifyActivityState();
            return state.activity.pathsVisible;
        }

        function setActivityPathTypeVisible(actorType, requested) {
            if (!['vehicle', 'operator', 'mobile_equipment'].includes(actorType)) {
                return false;
            }
            state.activity.visiblePathTypes[actorType] = requested !== false;
            applyActivityPathVisibility();
            invalidate();
            notifyActivityState();
            return state.activity.visiblePathTypes[actorType];
        }

        function setActivityDepartmentFilter(zoneId) {
            state.activity.departmentZoneId = typeof zoneId === 'string'
                && zoneId ? zoneId : null;
            state.activity.poseDirty = true;
            invalidate();
            return state.activity.departmentZoneId;
        }

        function selectActivityActor(actorId) {
            const exists = state.activity.tracks.some(function (track) {
                return track.actor.actorId === actorId;
            });
            if (!exists) return false;
            state.activity.selectedActorId = actorId;
            notifyActivityState();
            return true;
        }

        function focusActivityActor(actorId) {
            const selected = actorId || state.activity.selectedActorId;
            const track = state.activity.tracks.find(function (candidate) {
                return candidate.actor.actorId === selected;
            });
            if (!track || !track.currentPose || state.walkthrough.active
                    || state.drone.active) return false;
            const dimensions = track.profile.overallDimensions || {};
            const pose = track.currentPose;
            const length = Math.max(0.5, finite(dimensions.length, 1));
            const width = Math.max(0.5, finite(dimensions.width, 1));
            const height = Math.max(0.5, finite(dimensions.height, 1));
            const halfX = Math.max(length, width) / 2;
            const floorY = finite(
                track.placement.transform
                    && track.placement.transform.position
                    && track.placement.transform.position.y,
                0
            );
            return fitBounds({
                minimum: {
                    x: pose.x - halfX,
                    y: floorY,
                    z: pose.z - halfX,
                },
                maximum: {
                    x: pose.x + halfX,
                    y: floorY + height,
                    z: pose.z + halfX,
                },
            }, 'activity_actor', {
                x: pose.x,
                y: floorY + height * 0.45,
                z: pose.z,
            });
        }

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
            if (state.motion.package || state.motion.root) {
                disposeMotion(reason || 'renderer_degraded', true);
            }
            if (state.activity.scenario || state.activity.root) {
                disposeActivity(reason || 'renderer_degraded', true);
            }
            if (state.navigationPreview.payload
                    || state.navigationPreview.root) {
                disposeNavigationPreview(
                    reason || 'renderer_degraded',
                    true
                );
            }
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
            if (generation !== state.mountGeneration) {
                if (state.motion.package || state.motion.root) {
                    disposeMotion('stale_generation', false);
                }
                if (state.activity.scenario || state.activity.root) {
                    disposeActivity('stale_generation', false);
                }
                if (state.navigationPreview.payload
                        || state.navigationPreview.root) {
                    disposeNavigationPreview('stale_generation', false);
                }
                return;
            }
            if (!state.mounted || state.suspended) return;
            const walking = updateWalkthrough(timestamp);
            const flying = updateDrone(timestamp);
            const moving = updateMotion(timestamp);
            const activityMoving = updateActivity(timestamp);
            const navigationPreviewMoving = updateNavigationPreview(timestamp);
            const rotating = !immersiveActive()
                && state.visualSettings.autoRotate
                && state.controls
                && typeof state.controls.update === 'function';
            if (rotating) {
                state.controls.autoRotate = true;
                state.controls.update();
                state.needsRender = true;
            }
            if (walking || flying || moving || activityMoving
                    || navigationPreviewMoving) {
                state.needsRender = true;
            }
            if (!state.needsRender) return;
            state.needsRender = false;
            renderNow();
            if ((rotating || walking || flying || state.motion.playing
                    || state.activity.playing
                    || state.navigationPreview.playing)
                    && requestFrame
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
            if (state.motion.following) {
                state.motion.following = false;
                notifyMotionState();
            }
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

        function applyDroneRecordWindow(
            record,
            visibleIds,
            placementsById,
            suppressedPlacementIds
        ) {
            if (!record) return;
            const suppressed = suppressedPlacementIds || new Set();
            const placements = record.placementIds.map(function (id) {
                return placementsById.get(id);
            }).filter(Boolean);
            const visible = placements.filter(function (placement) {
                return visibleIds.has(placement.placementId)
                    && !suppressed.has(placement.placementId);
            });
            if (record.instanced) {
                setDroneRecordPlacements(record, visible);
                return;
            }
            record.pickObjects.forEach(function (object, index) {
                if (object) object.visible = Boolean(
                    placements[index]
                    && visibleIds.has(placements[index].placementId)
                    && !suppressed.has(placements[index].placementId)
                );
            });
        }

        function restoreBasePlacementVisibility() {
            if (state.drone.active && state.camera) {
                applyDroneRenderWindow(true);
                return;
            }
            const placementsById = dronePlacementMap();
            const suppressed = activitySuppressedPlacementIds();
            const allPlacementIds = new Set(placementsById.keys());
            state.renderGroups.forEach(function (record) {
                applyDroneRecordWindow(
                    record,
                    allPlacementIds,
                    placementsById,
                    suppressed
                );
            });
            applySelection(true);
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
            const suppressed = activitySuppressedPlacementIds();
            state.renderGroups.forEach(function (record) {
                applyDroneRecordWindow(
                    record,
                    visibleIds,
                    placementsById,
                    suppressed
                );
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
            applyDroneRecordWindow(
                record,
                visibleIds,
                dronePlacementMap(),
                activitySuppressedPlacementIds()
            );
            state.drone.visiblePlacementCount = visibleIds.size;
            applySelection(true);
        }

        function restoreDroneRenderWindow() {
            const placementsById = dronePlacementMap();
            const suppressed = activitySuppressedPlacementIds();
            const allPlacementIds = new Set(placementsById.keys());
            state.renderGroups.forEach(function (record) {
                applyDroneRecordWindow(
                    record,
                    allPlacementIds,
                    placementsById,
                    suppressed
                );
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
            if (state.motion.following) {
                state.motion.following = false;
                notifyMotionState();
            }
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
                object.visible = state.layerVisibility.markings !== false;
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
                object.visible = state.layerVisibility.routes !== false;
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
                preservedPlacementIds: identifiers('preservedPlacementIds'),
                newRouteIds: identifiers('newRouteIds'),
                changedRouteIds: identifiers('changedRouteIds'),
                removedRouteIds: identifiers('removedRouteIds'),
                preservedRouteIds: identifiers('preservedRouteIds'),
                beforePlacements: placements('beforePlacements'),
                proposedPlacements: placements('proposedPlacements'),
                beforeRoutes: (Array.isArray(value.beforeRoutes)
                    ? value.beforeRoutes : []).map(detachedJson),
                proposedRoutes: (Array.isArray(value.proposedRoutes)
                    ? value.proposedRoutes : []).map(detachedJson),
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
                preserved: 0x087f5b,
            };
            const opacity = role === 'before' || role === 'removed'
                ? 0.3 : role === 'preserved' ? 0.24 : 0.38;
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

        function proposalRouteObject(route, role) {
            const points = routeCenterline(route);
            if (points.length < 2) return null;
            const object = createContainer();
            const colors = {
                before: '#d97706',
                removed: '#dc2626',
                proposed: '#7c3aed',
                preserved: '#087f5b',
            };
            const width = Math.max(0.08, finite(route.corridorWidth, 1));
            for (let index = 1; index < points.length; index += 1) {
                const start = points[index - 1];
                const end = points[index];
                const dx = end.x - start.x;
                const dz = end.z - start.z;
                const length = Math.hypot(dx, dz);
                if (length <= 0.000001) continue;
                const segment = addFloorPaintRectangle(
                    object,
                    { fillColor: colors[role] || '#7c3aed' },
                    length,
                    width,
                    (start.x + end.x) / 2,
                    (start.z + end.z) / 2,
                    { opacity: role === 'preserved' ? 0.26 : 0.42 }
                );
                if (!segment) continue;
                segment.position.y = 0.018 + index * 0.000001;
                const radians = -Math.atan2(dz, dx);
                setQuaternion(segment.quaternion, {
                    x: 0,
                    y: Math.sin(radians / 2),
                    z: 0,
                    w: Math.cos(radians / 2),
                });
            }
            object.name = 'FacilityProposalRoute:'
                + role + ':' + String(route.routeId || 'route');
            object.userData = object.userData || {};
            object.userData.facilityProposalPreview = role;
            object.userData.facilityProposalRouteId = route.routeId || null;
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
            const currentLayout = state.currentInput
                && state.currentInput.layout || {};
            const currentPlacements = new Map(
                (Array.isArray(currentLayout.placements)
                    ? currentLayout.placements : []).filter(function (item) {
                    return item && item.placementId;
                }).map(function (item) {
                    return [item.placementId, item];
                })
            );
            proposal.preservedPlacementIds.forEach(function (placementId) {
                const placement = currentPlacements.get(placementId);
                if (placement) rootObject.add(
                    proposalObject(placement, 'preserved')
                );
            });
            const currentRoutes = new Map(
                (Array.isArray(currentLayout.routes)
                    ? currentLayout.routes : []).filter(function (item) {
                    return item && item.routeId;
                }).map(function (item) {
                    return [item.routeId, item];
                })
            );
            const removedRoutes = new Set(proposal.removedRouteIds);
            proposal.beforeRoutes.forEach(function (route) {
                const object = proposalRouteObject(
                    route,
                    removedRoutes.has(route.routeId) ? 'removed' : 'before'
                );
                if (object) rootObject.add(object);
            });
            proposal.proposedRoutes.forEach(function (route) {
                const object = proposalRouteObject(route, 'proposed');
                if (object) rootObject.add(object);
            });
            proposal.preservedRouteIds.forEach(function (routeId) {
                const route = currentRoutes.get(routeId);
                const object = route
                    ? proposalRouteObject(route, 'preserved') : null;
                if (object) rootObject.add(object);
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
            if (state.motion.package || state.motion.root) {
                disposeMotion('renderer_teardown', true);
            }
            if (state.activity.scenario || state.activity.root) {
                disposeActivity('renderer_teardown', true);
            }
            if (state.navigationPreview.payload
                    || state.navigationPreview.root) {
                disposeNavigationPreview('renderer_teardown', true);
            }
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

            container.visible = state.layerVisibility.assets !== false;
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
                prototypeMeshCount: prototypeMeshes.length,
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

        function loadDeferredGroup(group, reason) {
            if (!group || !state.mounted) return Promise.resolve(false);
            if (group.deferredPromise) return group.deferredPromise;
            if (!group.deferredVisual) return Promise.resolve(false);
            const generation = state.sceneGeneration;
            const descriptor = group.deferredVisual;
            group.deferredLoading = true;
            state.pendingLoads += 1;
            traceLoad(group, 'overview', 'started', reason);
            const promise = (async function () {
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
                    group.deferredPromise = null;
                    state.pendingLoads = Math.max(0, state.pendingLoads - 1);
                }
            }());
            group.deferredPromise = promise;
            return promise;
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

        function resolveBaseGroup(group, generation, signal) {
            if (!group || group.resolved) return Promise.resolve(true);
            if (group.resolvePromise) return group.resolvePromise;
            const promise = Promise.resolve(
                resolveGroup(group, generation, signal)
            ).then(function (resolved) {
                if (resolved && generation === state.sceneGeneration) {
                    group.resolved = true;
                }
                return resolved;
            }).finally(function () {
                group.resolvePromise = null;
            });
            group.resolvePromise = promise;
            return promise;
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
                        deferredPromise: null,
                        deferredQueued: false,
                        resolved: false,
                        resolvePromise: null,
                    });
                }
                groups.get(key).placements.push(placement);
            });
            return { placements: placements, groups: groups };
        }

        async function setScene(input) {
            const value = input && typeof input === 'object' ? input : {};
            if (state.motion.package || state.motion.root) {
                disposeMotion('scene_changed', true);
            }
            if (state.activity.scenario || state.activity.root) {
                disposeActivity('scene_changed', true);
            }
            if (state.navigationPreview.payload
                    || state.navigationPreview.root) {
                disposeNavigationPreview('scene_changed', true);
            }
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
                await resolveBaseGroup(
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
            // A hidden 3D tab can retain a stale camera aspect. Measure the
            // now-visible host before calculating fit distance.
            if (state.mounted && !state.suspended) resize();
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
                const forward = {
                    x: -direction.x,
                    y: -direction.y,
                    z: -direction.z,
                };
                let upReference = { x: 0, y: 1, z: 0 };
                let right = {
                    x: forward.y * upReference.z
                        - forward.z * upReference.y,
                    y: forward.z * upReference.x
                        - forward.x * upReference.z,
                    z: forward.x * upReference.y
                        - forward.y * upReference.x,
                };
                let rightLength = Math.sqrt(
                    right.x * right.x + right.y * right.y + right.z * right.z
                );
                if (rightLength < 0.0001) {
                    upReference = { x: 0, y: 0, z: 1 };
                    right = {
                        x: forward.y * upReference.z
                            - forward.z * upReference.y,
                        y: forward.z * upReference.x
                            - forward.x * upReference.z,
                        z: forward.x * upReference.y
                            - forward.y * upReference.x,
                    };
                    rightLength = Math.sqrt(
                        right.x * right.x
                        + right.y * right.y
                        + right.z * right.z
                    );
                }
                right = {
                    x: right.x / rightLength,
                    y: right.y / rightLength,
                    z: right.z / rightLength,
                };
                const cameraUp = {
                    x: right.y * forward.z - right.z * forward.y,
                    y: right.z * forward.x - right.x * forward.z,
                    z: right.x * forward.y - right.y * forward.x,
                };
                const tanVertical = Math.max(0.01, Math.tan(verticalFov / 2));
                const tanHorizontal = Math.max(
                    0.01,
                    Math.tan(horizontalFov / 2)
                );
                let requiredDistance = 0.5;
                [bounds.minimum.x, bounds.maximum.x].forEach(function (x) {
                    [bounds.minimum.y, bounds.maximum.y].forEach(function (y) {
                        [bounds.minimum.z, bounds.maximum.z].forEach(function (z) {
                            const relative = {
                                x: x - fitTarget.x,
                                y: y - fitTarget.y,
                                z: z - fitTarget.z,
                            };
                            const depthOffset = relative.x * direction.x
                                + relative.y * direction.y
                                + relative.z * direction.z;
                            const horizontal = Math.abs(
                                relative.x * right.x
                                + relative.y * right.y
                                + relative.z * right.z
                            );
                            const vertical = Math.abs(
                                relative.x * cameraUp.x
                                + relative.y * cameraUp.y
                                + relative.z * cameraUp.z
                            );
                            requiredDistance = Math.max(
                                requiredDistance,
                                depthOffset + horizontal / tanHorizontal,
                                depthOffset + vertical / tanVertical
                            );
                        });
                    });
                });
                const distance = requiredDistance * 1.12;
                setVector(state.camera.position, {
                    x: fitTarget.x + direction.x * distance,
                    y: fitTarget.y + direction.y * distance,
                    z: fitTarget.z + direction.z * distance,
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
            const projectedCorners = [];
            if (typeof THREE.Vector3 === 'function'
                    && typeof state.camera.updateProjectionMatrix === 'function') {
                [bounds.minimum.x, bounds.maximum.x].forEach(function (x) {
                    [bounds.minimum.y, bounds.maximum.y].forEach(function (y) {
                        [bounds.minimum.z, bounds.maximum.z].forEach(function (z) {
                            const projected = new THREE.Vector3(x, y, z);
                            if (typeof projected.project !== 'function') return;
                            projected.project(state.camera);
                            if (Number.isFinite(projected.x)
                                    && Number.isFinite(projected.y)) {
                                projectedCorners.push(projected);
                            }
                        });
                    });
                });
            }
            const viewportOccupancy = projectedCorners.length === 8 ? {
                widthRatio: Math.min(1, (Math.max.apply(null,
                    projectedCorners.map(function (point) { return point.x; })
                ) - Math.min.apply(null,
                    projectedCorners.map(function (point) { return point.x; })
                )) / 2),
                heightRatio: Math.min(1, (Math.max.apply(null,
                    projectedCorners.map(function (point) { return point.y; })
                ) - Math.min.apply(null,
                    projectedCorners.map(function (point) { return point.y; })
                )) / 2),
            } : null;
            if (viewportOccupancy) {
                viewportOccupancy.maximumRatio = Math.max(
                    viewportOccupancy.widthRatio,
                    viewportOccupancy.heightRatio
                );
            }
            const afterRoot = objectTransform(state.modelRoot);
            state.lastFit = {
                mode: mode,
                center: center,
                size: size,
                viewportOccupancy: viewportOccupancy,
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

        function setLayerVisibility(visibility) {
            const next = normalizeLayerVisibility(
                visibility,
                state.layerVisibility
            );
            state.layerVisibility = next;
            state.routeObjects.forEach(function (object) {
                object.visible = next.routes !== false;
            });
            state.floorMarkingObjects.forEach(function (object) {
                object.visible = next.markings !== false;
            });
            state.renderGroups.forEach(function (record) {
                if (record && record.container) {
                    record.container.visible = next.assets !== false;
                }
            });
            if (state.proposalRoot) {
                state.proposalRoot.visible = next.assets !== false;
            }
            invalidate();
            return Object.assign({}, state.layerVisibility);
        }

        function getLayerVisibility() {
            return Object.assign({}, state.layerVisibility);
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

        function topView(requestedBounds) {
            const boundedRequest = requestedBounds
                && requestedBounds.minimum && requestedBounds.maximum
                && ['x', 'y', 'z'].every(function (axis) {
                    return Number.isFinite(Number(requestedBounds.minimum[axis]))
                        && Number.isFinite(Number(
                            requestedBounds.maximum[axis]
                        ))
                        && Number(requestedBounds.maximum[axis])
                            >= Number(requestedBounds.minimum[axis]);
                }) ? requestedBounds : null;
            const bounds = boundedRequest
                || configuredEnvironmentBounds() || state.worldBounds;
            if (!state.camera || !state.modelRoot || !bounds
                    || state.degraded) return false;
            const beforeRoot = objectTransform(state.modelRoot);
            const floorY = !boundedRequest && options.worldBounds
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
                prototypeMeshCount: record.prototypeMeshCount,
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
            return Number.isFinite(left) && Number.isFinite(right)
                && Math.abs(left - right) <= finite(tolerance, 1e-6);
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

        const INSTANCE_MATRIX_AUDIT_TOLERANCE = 1e-5;
        const MATRIX_AUDIT_SAMPLE_LIMIT = 128;

        function compareInstanceMatrix(actual, expected, object) {
            const actualValues = actual && actual.elements;
            const expectedValues = expected && expected.elements;
            const buffer = object && object.instanceMatrix
                && object.instanceMatrix.array;
            const float32 = Object.prototype.toString.call(buffer)
                === '[object Float32Array]';
            const validShape = Array.isArray(actualValues)
                && Array.isArray(expectedValues)
                && actualValues.length === 16 && expectedValues.length === 16;
            // Three stores instance matrices in Float32Array. Compare read-back
            // with that exact encoding, keeping the existing absolute tolerance.
            // Retain double values and their quantization loss as separate evidence.
            const storedExpected = validShape ? expectedValues.map(function (value) {
                return float32 ? Math.fround(value) : value;
            }) : [];
            const nonFiniteElements = validShape ? actualValues.map(function (value, index) {
                return Number.isFinite(value) && Number.isFinite(expectedValues[index])
                    && Number.isFinite(storedExpected[index]) ? null : index;
            }).filter(function (value) { return value !== null; }) : [];
            const valid = validShape && !nonFiniteElements.length;
            const rawDelta = valid ? actualValues.map(function (value, index) {
                return value - expectedValues[index];
            }) : [];
            const storedDelta = valid ? actualValues.map(function (value, index) {
                return value - storedExpected[index];
            }) : [];
            const maxRawDelta = valid ? Math.max.apply(null, rawDelta.map(Math.abs)) : null;
            const maxStoredDelta = valid ? Math.max.apply(null, storedDelta.map(Math.abs)) : null;
            return {
                matches: valid && maxStoredDelta <= INSTANCE_MATRIX_AUDIT_TOLERANCE,
                storage: float32 ? 'Float32Array' : 'unquantized',
                validShape: validShape,
                nonFiniteElements: nonFiniteElements,
                actual: validShape ? actualValues : [],
                expectedDouble: validShape ? expectedValues : [],
                expectedStored: storedExpected,
                rawDelta: rawDelta,
                storedDelta: storedDelta,
                maxRawDelta: maxRawDelta,
                maxStoredDelta: maxStoredDelta,
            };
        }

        function getPlacementTransformAudit() {
            const expected = new Map(state.placements.map(function (placement) {
                return [placement.placementId, placement];
            }));
            const audited = new Set();
            const mismatchIds = new Set();
            const unavailableIds = new Set();
            const quantizedIds = new Set();
            const matrixSamples = new Map();
            let auditedMatrixCount = 0;
            let rawMatrixMismatchCount = 0;
            let maxRawMatrixDelta = 0;
            let maxStoredMatrixDelta = 0;
            function recordComparison(placementId, record, meshIndex, instanceIndex, comparison) {
                auditedMatrixCount += 1;
                maxRawMatrixDelta = Math.max(maxRawMatrixDelta, comparison.maxRawDelta || 0);
                maxStoredMatrixDelta = Math.max(maxStoredMatrixDelta, comparison.maxStoredDelta || 0);
                const rawMismatch = comparison.maxRawDelta > INSTANCE_MATRIX_AUDIT_TOLERANCE;
                if (rawMismatch) rawMatrixMismatchCount += 1;
                if (rawMismatch && comparison.matches) quantizedIds.add(placementId);
                if (comparison.matches && !rawMismatch) return;
                // One representative matrix per placement. A genuine mismatch
                // takes precedence over a precision-only sample for that placement.
                const prior = matrixSamples.get(placementId);
                if (prior && (!prior.matches || comparison.matches)) return;
                const jsonNumber = function (value) {
                    return Number.isFinite(value) ? value : String(value);
                };
                matrixSamples.set(placementId, {
                    placementId: placementId, assetId: record.assetId,
                    meshIndex: meshIndex, instanceIndex: instanceIndex,
                    matches: comparison.matches, storage: comparison.storage,
                    validShape: comparison.validShape,
                    nonFiniteElements: comparison.nonFiniteElements,
                    expectedDouble: comparison.expectedDouble.map(jsonNumber),
                    expectedStored: comparison.expectedStored.map(jsonNumber),
                    actual: comparison.actual.map(jsonNumber),
                    rawDelta: comparison.rawDelta, storedDelta: comparison.storedDelta,
                    maxRawDelta: comparison.maxRawDelta,
                    maxStoredDelta: comparison.maxStoredDelta,
                });
            }
            state.renderGroups.forEach(function (record) {
                if (record.instanced) {
                    const complete = new Set(record.placementIds);
                    if (!record.prototypeMatrices.length
                            || record.pickObjects.length !== record.prototypeMatrices.length) complete.clear();
                    record.prototypeMatrices.forEach(function (prototypeMatrix, meshIndex) {
                        const object = record.pickObjects[meshIndex];
                        const mapping = object
                            ? state.instanceLookup.get(object) || [] : [];
                        if (!object || typeof object.getMatrixAt !== 'function'
                                || !prototypeMatrix || typeof THREE.Matrix4 !== 'function') {
                            complete.clear();
                            return;
                        }
                        const seen = new Set();
                        mapping.forEach(function (placementId, instanceIndex) {
                            const placement = expected.get(placementId);
                            if (!placement) return;
                            const actual = new THREE.Matrix4();
                            object.getMatrixAt(instanceIndex, actual);
                            const expectedMatrix = multiplyPlacementAndPrototype(
                                placement, prototypeMatrix
                            );
                            seen.add(placementId);
                            const comparison = compareInstanceMatrix(actual, expectedMatrix, object);
                            recordComparison(placementId, record, meshIndex, instanceIndex, comparison);
                            if (!comparison.matches) mismatchIds.add(placementId);
                        });
                        complete.forEach(function (placementId) {
                            if (!seen.has(placementId)) complete.delete(placementId);
                        });
                    });
                    record.placementIds.forEach(function (placementId) {
                        if (complete.has(placementId)) audited.add(placementId);
                        else unavailableIds.add(placementId);
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
                transformMismatchIdsAll: Array.from(mismatchIds).sort(),
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
                matrixComparison: {
                    revision: 'instance-storage-matrix-audit-v1',
                    tolerance: INSTANCE_MATRIX_AUDIT_TOLERANCE,
                    auditedMatrixCount: auditedMatrixCount,
                    rawDoubleMismatchMatrixCount: rawMatrixMismatchCount,
                    quantizationOnlyPlacementIds: Array.from(quantizedIds).filter(function (id) {
                        return !mismatchIds.has(id);
                    }).sort(),
                    maxRawAbsoluteDelta: maxRawMatrixDelta,
                    maxStoredAbsoluteDelta: maxStoredMatrixDelta,
                    sampleLimit: MATRIX_AUDIT_SAMPLE_LIMIT,
                    sampleCount: matrixSamples.size,
                    samplesTruncated: matrixSamples.size > MATRIX_AUDIT_SAMPLE_LIMIT,
                    samples: Array.from(matrixSamples.values()).sort(function (left, right) {
                        if (left.matches !== right.matches) return left.matches ? 1 : -1;
                        return left.placementId.localeCompare(right.placementId);
                    }).slice(0, MATRIX_AUDIT_SAMPLE_LIMIT),
                },
                evidenceStatus: incomplete ? 'unknown' : 'derived',
                qualification: (
                    'Compares persisted placement transforms with actual object '
                    + 'transforms or every rendered instance matrix. Expected matrices '
                    + 'include prototype transforms and the instance storage encoding; '
                    + 'double-precision rounding differences remain in matrixComparison.'
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
                motion: motionStateSnapshot(),
                activity: activityStateSnapshot(),
                navigationPreview: navigationPreviewStateSnapshot(),
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
                layerVisibility: getLayerVisibility(),
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
                    viewportOccupancy: state.lastFit.viewportOccupancy
                        ? Object.assign({}, state.lastFit.viewportOccupancy)
                        : null,
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
            motion: Object.freeze({
                load: loadMotionPackage,
                play: playMotion,
                pause: pauseMotion,
                seek: seekMotion,
                setRate: setMotionRate,
                focus: focusMotionVehicle,
                setFollow: setMotionFollow,
                dispose: disposeMotion,
                getState: motionStateSnapshot,
                setStateHandler: setMotionStateHandler,
            }),
            activity: Object.freeze({
                load: loadActivityScenario,
                play: playActivity,
                pause: pauseActivity,
                seek: seekActivity,
                setRate: setActivityRate,
                setActorTypeVisible: setActivityActorTypeVisible,
                setPathsVisible: setActivityPathsVisible,
                setPathTypeVisible: setActivityPathTypeVisible,
                setDepartmentFilter: setActivityDepartmentFilter,
                selectActor: selectActivityActor,
                focusActor: focusActivityActor,
                dispose: disposeActivity,
                getState: activityStateSnapshot,
                setStateHandler: setActivityStateHandler,
            }),
            navigationPreview: Object.freeze({
                load: loadNavigationPreview,
                updatePath: updateNavigationPreviewPath,
                play: playNavigationPreview,
                pause: pauseNavigationPreview,
                seek: seekNavigationPreview,
                setRate: setNavigationPreviewRate,
                setPathsVisible: setNavigationPreviewPathsVisible,
                dispose: disposeNavigationPreview,
                getState: navigationPreviewStateSnapshot,
                setStateHandler: setNavigationPreviewStateHandler,
            }),
            loadMotionPackage: loadMotionPackage,
            playMotion: playMotion,
            pauseMotion: pauseMotion,
            seekMotion: seekMotion,
            setMotionRate: setMotionRate,
            focusMotionVehicle: focusMotionVehicle,
            setMotionFollow: setMotionFollow,
            disposeMotion: disposeMotion,
            getMotionState: motionStateSnapshot,
            setMotionStateHandler: setMotionStateHandler,
            loadActivityScenario: loadActivityScenario,
            playActivity: playActivity,
            pauseActivity: pauseActivity,
            seekActivity: seekActivity,
            setActivityRate: setActivityRate,
            disposeActivity: disposeActivity,
            getActivityState: activityStateSnapshot,
            setActivityStateHandler: setActivityStateHandler,
            loadNavigationPreview: loadNavigationPreview,
            updateNavigationPreviewPath: updateNavigationPreviewPath,
            playNavigationPreview: playNavigationPreview,
            pauseNavigationPreview: pauseNavigationPreview,
            seekNavigationPreview: seekNavigationPreview,
            disposeNavigationPreview: disposeNavigationPreview,
            getNavigationPreviewState: navigationPreviewStateSnapshot,
            setNavigationPreviewStateHandler:
                setNavigationPreviewStateHandler,
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
            setLayerVisibility: setLayerVisibility,
            getLayerVisibility: getLayerVisibility,
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
        FACILITY_MOTION_PACKAGE_SCHEMA_VERSION:
            FACILITY_MOTION_PACKAGE_SCHEMA_VERSION,
        FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1:
            FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1,
        FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2:
            FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2,
        FACILITY_MOTION_DISCLOSURE: FACILITY_MOTION_DISCLOSURE,
        sampleFacilityMotionAtDistance: sampleFacilityMotionAtDistance,
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
