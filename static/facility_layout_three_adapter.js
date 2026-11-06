(function (root, factory) {
    'use strict';

    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityThree = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    const avatarRuntime = root.InspectorProFacilityAvatar
        || (typeof require === 'function' ? require('./facility_layout_avatar.js') : null);
    const wallsRuntime = root.InspectorProFacilityWalls
        || (typeof require === 'function' ? require('./facility_layout_walls.js') : null);
    const groundRuntime = root.InspectorProFacilityGround
        || (typeof require === 'function' ? require('./facility_layout_ground.js') : null);
    const componentRuntime = root.InspectorProFacilityComponentMaterials
        || (typeof require === 'function' ? require('./facility_layout_component_materials.js') : null);
    const floorSurfacesRuntime = root.InspectorProFacilityFloorSurfaces
        || (typeof require === 'function' ? require('./facility_layout_floor_surfaces.js') : null);
    const siteRuntime = root.InspectorProFacilitySite
        || (typeof require === 'function' ? require('./facility_layout_site.js') : null);
    const finishesRuntime = root.InspectorProFacilityFinishes
        || (typeof require === 'function' ? require('./facility_layout_finishes.js') : null);
    const libraryRuntime = root.InspectorProFacilityLibrary
        || (typeof require === 'function' ? require('./facility_layout_library.js') : null);
    const scenesRuntime = root.InspectorProFacilityScenes
        || (typeof require === 'function' ? require('./facility_layout_scenes.js') : null);
    const equipmentDecalsRuntime = root.InspectorProFacilityEquipmentDecals
        || (typeof require === 'function' ? require('./facility_layout_equipment_decals.js') : null);
    const lightPoolsRuntime = root.InspectorProFacilityLightPools
        || (typeof require === 'function' ? require('./facility_layout_light_pools.js') : null);
    const lightCoverageRuntime = root.InspectorProFacilityLightCoverage
        || (typeof require === 'function' ? require('./facility_layout_light_coverage.js') : null);
    const lightAreasRuntime = root.InspectorProFacilityLightAreas
        || (typeof require === 'function' ? require('./facility_layout_light_areas.js') : null);
    // Floor light pools (L3): linear brightness at a pool's centre (times the lamp's glow color), and how far above
    // the floor they lie, over paint and floor finishes.
    const LIGHT_POOL_STRENGTH = 0.08;
    const LIGHT_POOL_LIFT = 0.02;
    // Outdoor light beams (L8): at most this many cones per layout (lamps beyond keep their pools), and a cone's
    // opacity at the lamp, fading toward the ground and its edge.
    const LIGHT_BEAM_CAP = 64;
    const LIGHT_BEAM_STRENGTH = 0.14;
    // A blinking light's redraw is timed a little after its change, so the frame lands past the edge (L4).
    const LIGHT_PATTERN_SLACK_MS = 8;

    const cameraPreferences = root.InspectorProWalkthroughCamera
        || (typeof require === 'function' ? require('./walkthrough_camera_settings.js') : null);

    // Explicit visual substitution only; catalog geometry and route authority stay unchanged.
    const ANIMATED_OPERATOR_REVISION =
        '773d3761fb0796587de7a21ccb8b368f4334c71f73c06682b84472d69d4b5757';

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
    // Glow halo (lighting L6, the scene's adjustments.glowHalo): three's UnrealBloomPass, fed only the pixels where a
    // glow is drawn (GLOW_STENCIL), so bright paint, floor markings and highlights get none. The frame is already
    // tone-mapped and in sRGB, so the threshold is on brightness as shown: a lit lamp of any color passes it (a red one
    // is about 0.45), a lamp switched off or in the dark step of a blink stays under it.
    const BLOOM = Object.freeze({ strength: 1, radius: 0.5, threshold: 0.35, softness: 0.15 });
    const GLOW_STENCIL = 1;
    // A click selects (as in SOLIDWORKS): pressed and released on the view, the pointer moved at most this far.
    const CLICK_SLOP_PIXELS = 5;
    const DEFAULT_LAYER_VISIBILITY = Object.freeze({
        zones: true,
        cells: true,
        routes: true,
        markings: true,
        assets: true,
        walls: true,
        // Viewer-only: the paving (ground tiles, ground marks and the site's outdoor areas), the floor
        // finishes, and the site overlays (the property line, routes to the main road). The aerial
        // photo always stays, so hiding all three with the rest shows the lot as it was.
        ground: true,
        surfaces: true,
        site: true,
        // Assets tagged 'overhead' (roof frame, lights, sprinklers, trays) and 'roof-sheeting'; the
        // sheeting starts hidden so the default view still looks into the building.
        overhead: true,
        roofSheeting: false,
    });
    // Zone limits on the 3D floor: the plan's zone outline color, and the line
    // width in metres.
    const ZONE_LIMIT_COLOR = '#4d7c8a';
    const ZONE_LIMIT_WIDTH = 0.1;
    // A zone ceiling (ceilings.py), seen from inside the room: matte charcoal (no finish), 'acoustic-tile':
    // off-white 600 mm tiles in a thin light grey T-bar grid (about 19 mm), tiled from the plan's origin so the grid
    // lines up across rooms, or 'open-deck': exposed steel (OPEN_DECK).
    const ZONE_CEILING_COLOR = '#2a2a2d';
    // The 'open-deck' finish (2026-11-03; the user chose "Exposed steel like Factory 02"): open-web steel joists
    // (Warren: two chords and a zigzag web) with their underside at the ceiling's height, every `spacing` m and
    // spanning the zone's short way, under a ribbed steel deck seen from below. The depth scales with the room:
    // `depthPerMeter` of the ceiling's height, within `minDepth` and `maxDepth`. A joist spans at most `spanPerDepth`
    // depths; a wider zone gets girders (an I section) that split it into equal bays. Light grey like Factory 02's
    // steel: joists `joist`, girders and edges `girder`, the deck a little lighter (`deck`, its ribs `ribPitch` m
    // apart, one texture tile of `texels` per `ribTile` m). All in metres.
    const OPEN_DECK = Object.freeze({
        spacing: 1.8, depthPerMeter: 0.14, minDepth: 0.45, maxDepth: 0.75, spanPerDepth: 24, sideLift: 0.35,
        chordWidth: 0.08, chordHeight: 0.06, webSize: 0.03,
        flangeWidth: 0.2, flangeThickness: 0.02, webThickness: 0.012, deckThickness: 0.04, edgeInset: 0.02,
        ribPitch: 0.1524, ribTile: 0.6096, texels: 256,
        joist: '#d4d9dd', girder: '#c3cad0', deck: [224, 228, 231],
    });
    const CEILING_TILE = Object.freeze({
        meters: 0.6, texels: 128, gridTexels: 2, tile: [241, 240, 236], grid: [196, 199, 202], plain: '#f1f0ec',
    });
    // A zone roof (ceilings.py): a flat slab whose underside is at the zone's floor plus its height (the wall
    // tops), a light grey membrane on top and a low parapet along its edge that comes down a little below the slab,
    // over a wall a little lower than the roof, capped by a darker coping. All in metres. The membrane is the color
    // without a texture (ROOF_MEMBRANE); the underside is the roof deck seen from inside.
    const ZONE_ROOF = Object.freeze({
        thickness: 0.2, parapetHeight: 0.45, parapetWidth: 0.2, drop: 0.1,
        membrane: '#c4c7c9', parapet: '#a4a7aa', coping: '#8e9296', underside: '#d6dadd',
    });
    // The roof membrane's texture (zoneRoofTexture): single-ply sheets `sheet` m wide that run along the roof's
    // longest edge, heat-welded where they lap (a side lap every sheet, an end lap staggered along each), a little
    // mottled and weathered. One tile of `texels` covers `meters` of roof; `base` is the sheet's sRGB color.
    const ROOF_MEMBRANE = Object.freeze({ meters: 12, texels: 512, sheet: 3, endLapStep: 5, base: [206, 209, 210] });
    // From this many floor markings on, their paint is drawn merged (batchFloorMarkings).
    const FLOOR_MARKING_BATCH_MINIMUM = 40;
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
        distanceCulling: false,
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

    // Mirror a loaded model file across its canonical x = 0 plane: the frame
    // the wrapper defines (ai_inspector/facility_layout/model_axes.py). The
    // vertex data is mirrored, not the transform: negative-determinant
    // transforms break instanced rendering and raycast culling. Geometry is
    // cloned first, so a cached model is never mirrored twice, and a geometry
    // shared by two parts is mirrored once per part frame.
    function mirrorModelFileGeometry(THREE, wrapper) {
        if (typeof wrapper.updateMatrixWorld === 'function') wrapper.updateMatrixWorld(true);
        const toWrapper = new THREE.Matrix4().copy(wrapper.matrixWorld).invert();
        const mirror = new THREE.Matrix4().makeScale(-1, 1, 1);
        const clones = new Map();
        wrapper.traverse(function (node) {
            if (!node.isMesh || node.isSkinnedMesh || node.isInstancedMesh || !node.geometry
                    || typeof node.geometry.clone !== 'function') return;
            const local = new THREE.Matrix4().multiplyMatrices(toWrapper, node.matrixWorld);
            const reflect = new THREE.Matrix4().copy(local).invert()
                .multiply(mirror).multiply(local);
            const key = node.geometry.uuid + ':' + reflect.elements
                .map(function (value) { return value.toFixed(7); }).join(',');
            let geometry = clones.get(key);
            if (!geometry) {
                geometry = node.geometry.clone();
                geometry.applyMatrix4(reflect);
                reverseTriangleWinding(geometry);
                const tangent = geometry.attributes && geometry.attributes.tangent;
                if (tangent && tangent.itemSize === 4 && !tangent.isInterleavedBufferAttribute) {
                    for (let index = 0; index < tangent.count; index += 1) {
                        tangent.array[index * 4 + 3] = -tangent.array[index * 4 + 3];
                    }
                    tangent.needsUpdate = true;
                }
                clones.set(key, geometry);
            }
            node.geometry = geometry;
        });
        return wrapper;
    }

    // A mirror turns every triangle inside out; swap two corners to turn it back.
    function reverseTriangleWinding(geometry) {
        if (geometry.index) {
            const array = geometry.index.array;
            for (let index = 0; index + 2 < array.length; index += 3) {
                const swap = array[index + 1];
                array[index + 1] = array[index + 2];
                array[index + 2] = swap;
            }
            geometry.index.needsUpdate = true;
            return;
        }
        Object.keys(geometry.attributes || {}).forEach(function (name) {
            const attribute = geometry.attributes[name];
            const interleaved = Boolean(attribute.isInterleavedBufferAttribute);
            const array = interleaved ? attribute.data.array : attribute.array;
            const stride = interleaved ? attribute.data.stride : attribute.itemSize;
            const offset = interleaved ? attribute.offset : 0;
            for (let vertex = 0; vertex + 2 < attribute.count; vertex += 3) {
                for (let component = 0; component < attribute.itemSize; component += 1) {
                    const first = (vertex + 1) * stride + offset + component;
                    const second = (vertex + 2) * stride + offset + component;
                    const swap = array[first];
                    array[first] = array[second];
                    array[second] = swap;
                }
            }
            if (interleaved) attribute.data.needsUpdate = true;
            else attribute.needsUpdate = true;
        });
    }

    function cameraOrientationFromQuaternion(value) {
        const quaternion = value && typeof value === 'object' ? value : null;
        if (!quaternion) return null;
        const x = finite(quaternion.x, 0);
        const y = finite(quaternion.y, 0);
        const z = finite(quaternion.z, 0);
        const w = finite(quaternion.w, 1);

        // Project the camera's screen-right axis onto the facility floor. The
        // direction shown at the top of the view is the camera's forward one,
        // a quarter turn from right: (right.z, -right.x). Until 2026-10-21 this
        // used the opposite quarter turn and reported the bottom of the view.
        const rightX = 1 - 2 * (y * y + z * z);
        const rightZ = 2 * (x * z - w * y);
        const magnitude = Math.hypot(rightX, rightZ);
        if (magnitude < 1e-8) return null;
        const projectedTopX = rightZ / magnitude;
        const projectedTopZ = -rightX / magnitude;
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
            output[key] = typeof source[key] === 'boolean' ? source[key]
                : (typeof base[key] === 'boolean' ? base[key] : DEFAULT_LAYER_VISIBILITY[key]);
        });
        return output;
    }

    // The layer a placed model's group shows on: walls, roof sheeting, overhead structure and
    // services (by catalog tag, as walls are), or everything else.
    function assetVisibilityLayer(entry) {
        if (wallsRuntime.isWallAsset(entry)) return 'walls';
        const source = entry && (entry.source || entry) || {};
        const definition = source.definition || source.assetDefinition || source;
        const tags = [].concat(entry && entry.tags || [], definition.tags || []);
        if (tags.includes('roof-sheeting')) return 'roofSheeting';
        return tags.includes('overhead') ? 'overhead' : 'assets';
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

    // The camera boom uses the same conservative footprint obstacles as walking.
    // It retracts along a straight segment, never slides through an obstacle.
    function resolveWalkthroughCamera(input) {
        const anchor = input.anchor;
        const desired = input.desired;
        const radius = 0.15;
        const distance = Math.hypot(desired.x - anchor.x,
            desired.y - anchor.y, desired.z - anchor.z);
        const steps = Math.max(1, Math.ceil(distance / 0.075));
        let position = Object.assign({}, anchor);
        let obstructed = false;
        for (let index = 0; index <= steps; index += 1) {
            const fraction = index / steps;
            const point = {
                x: anchor.x + (desired.x - anchor.x) * fraction,
                y: anchor.y + (desired.y - anchor.y) * fraction,
                z: anchor.z + (desired.z - anchor.z) * fraction,
            };
            if (point.y < input.floorY + radius
                    || !walkthroughPointValid(point, radius, input.bounds, input.obstacles || [])) {
                obstructed = true;
                break;
            }
            position = point;
        }
        return { position, obstructed, distance: Math.hypot(position.x - anchor.x,
            position.y - anchor.y, position.z - anchor.z) };
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

    function walkthroughSweptObstacles(index, start, delta, radius) {
        const minimumX = Math.min(start.x, start.x + delta.x) - radius;
        const maximumX = Math.max(start.x, start.x + delta.x) + radius;
        const minimumZ = Math.min(start.z, start.z + delta.z) - radius;
        const maximumZ = Math.max(start.z, start.z + delta.z) + radius;
        const center = { x: (minimumX + maximumX) / 2, z: (minimumZ + maximumZ) / 2 };
        // The whole swept rectangle includes the solver's axis-slide paths.
        return droneCandidateVolumes(index, center,
            Math.max(maximumX - minimumX, maximumZ - minimumZ) / 2
        ).filter(function (record) {
            const b = record.planarBounds;
            return b.minimumX <= maximumX && b.maximumX >= minimumX
                && b.minimumZ <= maximumZ && b.maximumZ >= minimumZ;
        }).map(function (record) { return record.polygon; });
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
        // Cells and search records are allocated lazily. Bound explored nodes,
        // not the area of the site: a short walk can occur in a large factory.
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
            return {
                ok: false,
                reason: open.length ? 'search_budget_exhausted' : 'no_path',
                points: [],
                visitedNodeCount: visitedNodeCount,
            };
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
        // Appearance/scene/decal library store ({ get, load }) plus the optional
        // three.js addons that realistic finishes, scenes and decals need.
        const facilityLibrary = options.facilityLibrary || null;
        const RoomEnvironmentType = options.RoomEnvironment || null;
        const HDRLoaderType = options.HDRLoader || null;
        const DecalGeometryType = options.DecalGeometry || null;
        // The glow halo's three.js addons (UnrealBloomPass.js, Pass.js, CopyShader.js); without them there is none.
        const BloomPassType = options.UnrealBloomPass || null;
        const FullScreenQuadType = options.FullScreenQuad || null;
        const CopyShaderSource = options.CopyShader || null;
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
        // The blinking lights' shared clock, in ms (docs/facility-lighting-plan.md, L4).
        const lightClock = typeof options.now === 'function' ? options.now : function () {
            const clock = root && root.performance;
            return clock && typeof clock.now === 'function' ? clock.now() : Date.now();
        };
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
            distanceCulling: options.droneDistanceCulling === true,
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
            // Layout axes (+X east, +Z north, north up on the plan) are left-handed;
            // three.js renders right-handed. Mirroring the displayed canvas makes the
            // 3D view agree with the plan; model files are mirrored once in model
            // space so they still look true (ai_inspector/facility_layout/model_axes.py).
            displayMirror: options.displayMirror !== false,
            host: null,
            parkedView: null,
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
            siteRoot: null,
            siteGround: null,
            siteGroundKey: '',
            siteAreaObjects: [],
            siteRouteObjects: [],
            siteRouteKey: '',
            siteAreaKey: '',
            floorObject: null,
            gridObjects: [],
            axisObjects: [],
            environmentSignature: null,
            environmentDiagnostics: null,
            ownsBackground: false,
            themeCleanup: null,
            modelRoot: null,
            floorMarkingObjects: [],
            floorMarkingCount: 0,
            floorMarkingTextures: new Map(),
            zoneObjects: [],
            zoneCeilingObjects: [],
            zoneRoofObjects: [],
            wallObjects: [],
            columnObjects: [],
            floorSurfaceObjects: [],
            wallFinishObjects: [],
            wallArtworkLoads: [],
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
            lightPatternsVisibilityHandler: null,
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
            pointerDownHandler: null,
            pointerCancelHandler: null,
            pointerPress: null,
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
            sceneRequest: 0,       // setScene calls so far (Sage's 3D shots, SV1 round 4: sceneState)
            sceneInstalled: 0,     // the latest of them built into the scene
            requestedInput: null,  // the latest setScene input: what a recovery replays (SV1 round 5)
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
            // A scene rebuild's old materials, out of the scene, disposed once the new one has drawn (keepPrograms).
            retiredMaterials: new Set(),
            retiringMaterials: false,
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
                position: null,
                cameraMode: 'first-person',
                cameraSettings: cameraPreferences.load(),
                lookQuaternion: null,
                avatar: null,
                avatarSettling: false,
                heading: 0,
                cameraDistance: 0,
                cameraObstructed: false,
                obstacleIndex: null,
                performance: { movementFrames: 0, simulatedSeconds: 0,
                    droppedSeconds: 0, collisionCandidates: 0, contextQueries: 0 },
                lastContextTime: null,
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
            // Library finishes, viewport scene and equipment decals.
            finishTextures: null,
            finishGeometryCache: trackedFinishGeometryCache(),
            // Keys of the projections used while a group or a finish preview is built, and how many groups use each.
            finishProjectionSink: null,
            finishProjectionUsers: new Map(),
            // Floor light pools: one mesh (or null, no lamps) per render group, under one root.
            lightPools: { root: null, meshes: new Map(), material: null, texture: null, beams: null, groundKey: '' },
            // Lamps that light things (2026-11-02): spot light candidates per render group and the fixed set of
            // spot lights; the general lighting's fill map and the uniforms every patched material shares.
            lampSpots: { lists: new Map(), candidates: [], root: null, lights: [], key: '', assigned: 0 },
            lightFill: { uniforms: null, texture: null, field: null, key: '', patched: 0,
                mask: null, maskTexture: null, maskKey: '', buildMs: 0 },
            // Lighting coverage estimate (CC3): the workspace's prepared bands and outlines, and their objects.
            lightCoverage: { view: null, root: null },
            // Glow halo (L6): GPU resources only while it is drawn; failed: why it cannot be, for this view;
            // stencil: whether the view's canvas has the stencil the halo needs (asked once per renderer).
            bloom: { pass: null, frame: null, glow: null, copy: null, mask: null, add: null, quad: null, size: null,
                width: 0, height: 0, checked: false, frames: 0, failed: null, stencil: null },
            lightPatterns: {
                timer: null, due: null, clock: 0, drawn: false, next: Infinity, frustum: null, inView: false, redraws: 0,
            },
            // General lights by area (L7): the scene's areas resolved against the layout; a new version makes the
            // lamp tables refill. masks: a glow material's on/off table; pools: a pool mesh's pools.
            // fresh: geometries given lamp numbers during the frame being drawn (the GPU has them from the next one).
            lightAreas: {
                resolved: null, signature: 'null', version: 0, masks: new WeakMap(), pools: new WeakMap(), fresh: new Set(),
            },
            environmentLoader: null,
            viewportScene: null,
            viewportSceneRequest: 0,
            sceneBackgroundKey: JSON.stringify(['theme', null]),
            sceneEnvironment: null,
            sceneBackgroundTexture: null,
            equipmentDecalObjects: new Map(),
            decalTextures: new Map(),
            finishPreview: null,
            libraryWaiting: false,
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

        function usesOperatorAvatar(record) {
            return record && record.assetId === 'asset-operator'
                && record.assetDefinitionRevision === ANIMATED_OPERATOR_REVISION
                && record.representation === 'operator-avatar';
        }

        function createActivityVisual(record) {
            if (!usesOperatorAvatar(record)) return cloneActivityRenderable(record.prototypeObject);
            const avatar = avatarRuntime.createAvatar(THREE);
            avatar.root.name = 'facility-animated-operator';
            avatar.root.userData.navigationOnly = false;
            avatar.root.facilityOperatorAvatar = avatar;
            return avatar.root;
        }

        function operatorVisualEvidence(visual) {
            const avatar = visual && visual.facilityOperatorAvatar;
            return {
                exactCatalogVisual: Boolean(visual) && !avatar,
                visualSource: !visual ? null : avatar ? 'animated-operator-avatar' : 'catalog-glb',
                avatar: avatar ? avatar.snapshot() : null,
            };
        }

        function sampleOperatorGait(visual, distance, pathLength, walking) {
            const avatar = visual && visual.facilityOperatorAvatar;
            if (!avatar) return;
            const scale = Math.max(0.001, finite(visual.scale.x, 1));
            avatar.update({ position: { x: 0, y: 0, z: 0 }, heading: 0, snap: true,
                gaitDistanceMeters: Math.max(0, distance) / scale, walking: walking,
                gaitWeight: Math.max(0, Math.min(1, distance / .2, (pathLength - distance) / .2)),
            });
        }

        // The group that draws a placement, found by the placement itself: its key carries the finish or part suffix
        // (baseGroupKey) that an asset|revision lookup leaves out, so an actor placed only with a finish or finished
        // parts still finds its group, and a finished actor next to plain ones loads its own model (Codex on 5bb9252).
        function baseGroupOfPlacement(placementId) {
            for (const group of state.baseGroups.values()) {
                if (group && Array.isArray(group.placements) && group.placements.some(function (item) {
                    return item && item.placementId === placementId;
                })) return group;
            }
            return null;
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
                        ...operatorVisualEvidence(track.visual),
                        sourcePlacementSuppressed:
                            !activityPlacementStillVisible(
                                track.actor.placementId
                            ),
                        visualForwardAxis: track.visual.facilityOperatorAvatar
                            ? '-Z' : track.actor.visualAlignment.forwardAxis,
                        catalogVisualForwardAxis: track.actor.visualAlignment.forwardAxis,
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
                visualForwardAxis: preview.visual && preview.visual.facilityOperatorAvatar
                    ? '-Z' : payload ? payload.visualForwardAxis : null,
                catalogVisualForwardAxis: payload ? payload.visualForwardAxis : null,
                visualYawRadians: preview.visualYawRadians,
                ...operatorVisualEvidence(preview.visual),
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

        // ENSURE_CURRENT(group) throws once the view, the scene or the group the preview was asked for is gone: it
        // runs before every load this starts and after it, so nothing is drawn into a view mounted since or a newer
        // scene (final rounds 2 and 3).
        async function prepareNavigationPreviewVisual(validated, ensureCurrent) {
            const placement = validated.placement;
            const group = baseGroupOfPlacement(placement.placementId);
            if (!group) {
                throw facilityMotionError(
                    'facility_navigation_preview_visual_unavailable',
                    'The selected actor has no catalog visual group.',
                    { placementId: placement.placementId }
                );
            }
            if (!group.resolved) {
                ensureCurrent(group);
                await resolveBaseGroup(
                    group,
                    state.sceneGeneration,
                    state.abortController ? state.abortController.signal : null
                );
            }
            if (group.deferredVisual) {
                ensureCurrent(group);
                await loadDeferredGroup(
                    group,
                    'navigation_preview_exact_visual'
                );
            }
            ensureCurrent(group);
            const record = activityRenderRecord(placement.placementId);
            if (!usesOperatorAvatar(record)
                    && !['overview', 'detail'].includes(record.representation)) {
                throw facilityMotionError(
                    'facility_navigation_preview_exact_visual_unavailable',
                    'Manual motion preview requires the catalog GLB or the registered operator avatar; footprint and proxy fallbacks are not animated.',
                    {
                        placementId: placement.placementId,
                        representation: record.representation,
                    }
                );
            }
            ensureCurrent(null, record);
            return record;
        }

        async function loadNavigationPreview(payload, activeRevision) {
            const unavailable = function () {
                return facilityMotionError(
                    'facility_navigation_preview_view_unavailable',
                    'Mount the Facility 3D view before previewing a path.'
                );
            };
            if (!state.mounted || state.disposed || !state.modelRoot) throw unavailable();
            const token = sceneToken();
            // It remembers every group and prepared record it was given, so the last call, right before the records
            // are used, checks them all: a finish-only regroup replaces groups and their records without a new scene,
            // and each record is checked against its own drawn group (final rounds 4 and 5).
            const groupsUsed = [];
            const recordsUsed = [];
            const ensureCurrent = function (group, record) {
                if (group && groupsUsed.indexOf(group) < 0) groupsUsed.push(group);
                if (record && recordsUsed.indexOf(record) < 0) recordsUsed.push(record);
                if (state.disposed || state.teardownCount !== token.teardowns || !state.modelRoot) {
                    throw unavailable();
                }
                if (!tokenCurrent(token) || groupsUsed.some(function (used) { return !tokenCurrent(token, used); })
                        || recordsUsed.some(function (used) { return !recordCurrent(used); })) {
                    throw facilityMotionError(
                        'facility_navigation_preview_scene_changed',
                        'The layout changed while the path preview loaded; preview it again.'
                    );
                }
            };
            let validated = validateNavigationPreviewPayload(
                payload,
                activeRevision
            );
            const record = await prepareNavigationPreviewVisual(validated, ensureCurrent);
            // Only into the view, the scene and the actor group it was prepared for.
            ensureCurrent();
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
                const visual = createActivityVisual(record);
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
                // Own resources before any subsequent validation can fail.
                state.navigationPreview.root = rootObject;
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
                    preview.visual.facilityOperatorAvatar ? '-Z' : payload.visualForwardAxis
                ) - pose.heading;
                const pathLength = navigationPreviewRuntime().pathLength(payload.points);
                const travel = pathLength * sampleTime;
                const returning = payload.loopMode === 'out_and_return' && preview.normalizedTime > .5;
                sampleOperatorGait(preview.visual, returning ? pathLength - travel : travel,
                    pathLength, !(payload.loopMode === 'one_way' && preview.normalizedTime >= 1));
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
                    || scenario.actors.length > (navigationActivity ? 64 : 24)
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

        // ENSURE_CURRENT(group) throws once the view, the scene or a group the activity was asked for is gone: every
        // worker runs it before each load it starts, so no actor model is drawn into a view mounted since or a newer
        // scene (final rounds 2 and 3).
        async function prepareActivityActorVisuals(validated, ensureCurrent) {
            const groups = new Map();
            validated.actors.forEach(function (value) {
                // The validator matched the actor's placement to its assetDefinitionRef exactly.
                const group = baseGroupOfPlacement(value.actor.placementId);
                if (!group) {
                    throw facilityMotionError(
                        'facility_activity_actor_visual_unavailable',
                        'The exact catalog visual group is unavailable for an activity actor.',
                        { actorId: value.actor.actorId }
                    );
                }
                groups.set(baseGroupKey(group), group);
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
                        ensureCurrent(group);
                        if (group.deferredVisual) {
                            await loadDeferredGroup(
                                group,
                                'activity_actor_exact_visual'
                            );
                        }
                    }
                }
            ));
            groups.forEach(function (group) { ensureCurrent(group); });
            validated.actors.forEach(function (value) {
                const record = activityRenderRecord(
                    value.actor.placementId
                );
                ensureCurrent(null, record);
                if (!usesOperatorAvatar(record)
                        && !['overview', 'detail'].includes(record.representation)) {
                    throw facilityMotionError(
                        'facility_activity_actor_exact_visual_unavailable',
                        'Activity playback requires the catalog GLB or the registered operator avatar; footprint and proxy fallbacks are not animated.',
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
            const unavailable = function () {
                return facilityMotionError(
                    'facility_activity_view_unavailable',
                    'Mount the Facility 3D view before loading activity.'
                );
            };
            if (!state.mounted || state.disposed || !state.modelRoot) throw unavailable();
            const token = sceneToken();
            // It remembers every group and prepared record it was given, so the last call, right before the records
            // are used, checks them all: a finish-only regroup replaces groups and their records without a new scene,
            // and each record is checked against its own drawn group (final rounds 4 and 5).
            const groupsUsed = [];
            const recordsUsed = [];
            const ensureCurrent = function (group, record) {
                if (group && groupsUsed.indexOf(group) < 0) groupsUsed.push(group);
                if (record && recordsUsed.indexOf(record) < 0) recordsUsed.push(record);
                if (state.disposed || state.teardownCount !== token.teardowns || !state.modelRoot) {
                    throw unavailable();
                }
                if (!tokenCurrent(token) || groupsUsed.some(function (used) { return !tokenCurrent(token, used); })
                        || recordsUsed.some(function (used) { return !recordCurrent(used); })) {
                    throw facilityMotionError(
                        'facility_activity_scene_changed',
                        'The layout changed while the activity loaded; load it again.'
                    );
                }
            };
            let validated = validateActivityPayload(
                payload,
                activeLayoutRevision
            );
            await prepareActivityActorVisuals(validated, ensureCurrent);
            // Only into the view, the scene and the actor groups it was prepared for.
            ensureCurrent();
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
                    const visual = createActivityVisual(value.record);
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
                        track.visual.facilityOperatorAvatar ? '-Z' : track.actor.visualAlignment.forwardAxis
                    ) - pose.heading;
                    const pathLength = motionDistanceAtTime(movement, motionDurationSeconds(movement));
                    const returning = timing.direction === 'return' && timing.movement === track.package.movement;
                    sampleOperatorGait(track.visual, returning ? pathLength - distance : distance,
                        pathLength, timing.direction !== 'turning' && timing.phase !== 'complete');
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
            disposeRetiredMaterials();
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

        // On a mirrored canvas, dragging right must still turn and pan the view
        // to the right: horizontal input is mirrored before the controls use it.
        function mirrorOrbitControls(controls) {
            const rotateLeft = controls._rotateLeft;
            const panLeft = controls._panLeft;
            const updateZoom = controls._updateZoomParameters;
            if (typeof rotateLeft === 'function') {
                controls._rotateLeft = function (angle) { return rotateLeft.call(this, -angle); };
            }
            if (typeof panLeft === 'function') {
                controls._panLeft = function (distance, objectMatrix) {
                    return panLeft.call(this, -distance, objectMatrix);
                };
            }
            if (typeof updateZoom === 'function') {
                controls._updateZoomParameters = function (x, y) {
                    const rect = this.domElement.getBoundingClientRect();
                    return updateZoom.call(this, 2 * rect.left + rect.width - x, y);
                };
            }
        }

        // PointerLockControls registers its mouse handler on connect(); swap in
        // one that turns the view the way the mirrored canvas shows it.
        function mirrorPointerLockLook(controls) {
            if (typeof controls.disconnect !== 'function' || typeof controls.connect !== 'function'
                    || typeof THREE.Euler !== 'function') return;
            const euler = new THREE.Euler(0, 0, 0, 'YXZ');
            const halfPi = Math.PI / 2;
            controls.disconnect();
            controls._onMouseMove = function (event) {
                if (controls.enabled === false || controls.isLocked === false) return;
                euler.setFromQuaternion(controls.object.quaternion);
                euler.y += event.movementX * 0.002 * controls.pointerSpeed;
                euler.x -= event.movementY * 0.002 * controls.pointerSpeed;
                euler.x = Math.max(halfPi - controls.maxPolarAngle,
                    Math.min(halfPi - controls.minPolarAngle, euler.x));
                controls.object.quaternion.setFromEuler(euler);
                controls.dispatchEvent({ type: 'change' });
            };
            controls.connect(state.canvas);
        }

        function appendCanvas(host, canvas) {
            if (!host || !canvas || typeof host.appendChild !== 'function') return;
            if (canvas.parentNode !== host) host.appendChild(canvas);
            if (canvas.style) {
                canvas.style.display = 'block';
                canvas.style.width = '100%';
                canvas.style.height = '100%';
                canvas.style.transform = state.displayMirror ? 'scaleX(-1)' : '';
            }
            if (typeof canvas.setAttribute === 'function') {
                canvas.setAttribute('aria-label', 'Facility layout 3D view');
            }
        }

        function removeCanvas() {
            const canvas = state.canvas;
            if (!canvas) return;
            // A pooled renderer's canvas may serve another view next.
            if (canvas.style) canvas.style.transform = '';
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

        function renderNow(timestamp) {
            if (!state.mounted || state.suspended || state.degraded
                || !state.renderer || !state.scene || !state.camera) {
                return false;
            }
            try {
                updateWalkthroughContextFocus(timestamp);
                notifyCameraOrientation(false);
                beginLightPatternFrame();
                state.lightAreas.fresh.clear();
                if (state.lightCoverage.view) syncLightCoverage();
                assignLampSpots();
                updateLightFillMatrix();
                state.renderer.render(state.scene, state.camera);
                if (bloomWanted()) drawBloom();
                else if (state.bloom.pass) disposeBloom();
                state.renderedFrames += 1;
                if (state.status === 'ready') disposeRetiredMaterials();
                scheduleLightPatterns();
                return true;
            } catch (error) {
                reportError('render_failed', error);
                enterDegraded('render_failed', false);
                return false;
            }
        }

        function cameraOrientationSnapshot() {
            const orientation = state.camera ? cameraOrientationFromQuaternion(state.camera.quaternion) : null;
            const site = state.currentInput && state.currentInput.layout.extensions && state.currentInput.layout.extensions.facilitySiteContext;
            if (orientation && site) {
                orientation.planHeadingDegrees = orientation.headingDegrees;
                orientation.headingDegrees = (orientation.headingDegrees + site.buildingPose.bearingDegrees + 360) % 360;
                const angle = orientation.headingDegrees * Math.PI / 180;
                orientation.screenTop = { x: Math.sin(angle), z: Math.cos(angle) };
                orientation.reference = 'true-north';
            }
            return orientation;
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
            renderNow(timestamp);
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
                if (state.walkthrough.active && walkthroughHasActivity()) {
                    state.navigationInteracting = true;
                    setRendererPixelRatio(state.interactivePixelRatio);
                    return;
                }
                state.navigationInteracting = false;
                setRendererPixelRatio(state.displayPixelRatio);
                invalidate();
                loadDeferredVisibleGroups();
            };
            const timerHost = options.window || root;
            if (state.navigationRestoreTimer !== null && timerHost
                    && typeof timerHost.clearTimeout === 'function') {
                timerHost.clearTimeout(state.navigationRestoreTimer);
                state.navigationRestoreTimer = null;
            }
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
            state.siteRoot = new RootType();
            state.siteRoot.name = 'InspectorProFacilitySiteRoot';
            state.scene.add(state.siteRoot);
            state.siteGround = null;
            state.siteGroundKey = '';
            state.siteAreaObjects = [];
            state.siteAreaKey = '';
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
                // The halo's buffers go with the context; it makes new ones when it is drawn again.
                disposeBloom();
                enterDegraded('webgl_context_lost', true);
            };
            state.contextRestoredHandler = function () {
                state.contextLost = false;
                state.degraded = false;
                const latest = latestInput();
                if (latest) {
                    const restoring = Promise.resolve(setScene(latest));
                    const token = sceneToken({ installs: true });
                    restoring.catch(
                        function () {
                            if (tokenCurrent(token)) enterDegraded('webgl_restore_failed', false);
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
            // Blinking lights (L4): a frame drawn while the window was hidden set no timer; draw one when it shows.
            state.lightPatternsVisibilityHandler = function () {
                if (documentObject && !documentObject.hidden && state.lightPatterns.inView) invalidate();
            };
            addListener(documentObject, 'visibilitychange', state.lightPatternsVisibilityHandler, false);
            // A pick selects only on a click: a press and a release on the view, primary button, pointer still. A
            // drag that turns or pans the view selects nothing, and nor does a release whose press was not on the
            // view (the main session, 2026-11-01: after desktop Sage turns a roof joist or a sprinkler line that
            // nobody clicked was selected, and Sage then refused the next request because of it).
            state.pointerDownHandler = function (event) {
                state.pointerPress = event && (event.button === undefined || event.button === 0) ? {
                    pointerId: event.pointerId,
                    x: finite(event.clientX, 0),
                    y: finite(event.clientY, 0),
                } : null;
            };
            state.pointerCancelHandler = function () {
                state.pointerPress = null;
            };
            state.pointerHandler = function (event) {
                const press = state.pointerPress;
                state.pointerPress = null;
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
                if (!wasClick(press, event)) return;
                const result = pick(event);
                if (result && state.selectionHandler) {
                    // The event carries Ctrl/Cmd, which adds to the selection.
                    state.selectionHandler(result.placementId, api, event);
                }
            };
            addListener(
                state.canvas,
                'pointerup',
                state.pointerHandler,
                false
            );
            addListener(state.canvas, 'pointerdown', state.pointerDownHandler, false);
            addListener(state.canvas, 'pointercancel', state.pointerCancelHandler, false);

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
                if (state.displayMirror) mirrorOrbitControls(state.controls);
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
                if (state.displayMirror) mirrorPointerLockLook(state.walkthroughControls);
                state.walkthroughChangeHandler = function () {
                    if (state.walkthrough.active) {
                        state.walkthrough.lookQuaternion = copyQuaternion(state.camera.quaternion);
                        syncWalkthroughCamera();
                        beginNavigationInteraction();
                        endNavigationInteraction();
                    }
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
                // Pointer-lock aim is independent of the raised render camera.
                state.walkthroughAimHandler = function () {
                    const walk = state.walkthrough;
                    if (walk.active && walk.locked && walk.lookQuaternion)
                        setQuaternion(state.camera.quaternion, walk.lookQuaternion);
                };
                state.walkthroughWheelHandler = function (event) {
                    const walk = state.walkthrough;
                    if (!walk.active || walk.cameraMode !== 'third-person' || event.ctrlKey) return;
                    event.preventDefault();
                    setWalkthroughCameraSettings(cameraPreferences.zoom(walk.cameraSettings, event));
                };
                addListener(documentObject, 'mousemove', state.walkthroughAimHandler, true);
                addListener(state.canvas, 'wheel', state.walkthroughWheelHandler, { passive: false });
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
                        cancelWalkthroughNavigation('window_blurred');
                        endNavigationInteraction();
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
                    const shared = candidate.userData && (candidate.userData.facilityEnvironment
                        || candidate.userData.facilitySharedTexture);
                    // Scene environments and decal images are shared; their owners dispose them.
                    if (shared) return;
                    if (state.finishTextures && finishesRuntime && finishesRuntime.isLibraryTexture(candidate)) {
                        state.finishTextures.forget(candidate);
                    }
                    if (typeof candidate.dispose === 'function') candidate.dispose();
                }
            });
            if (state.retiringMaterials) state.retiredMaterials.add(material);
            else if (typeof material.dispose === 'function') material.dispose();
        }

        // Shader programs outlive a scene rebuild (2026-11-03). three drops a program when the last material using it
        // is disposed, so a rebuild that disposed every material first compiled them all again: 21 programs, about
        // 3 s after each commit or Undo on a 2,242-placement plant. While setScene clears the old model, its
        // materials are set aside (their textures and geometry still go), and disposed once the new scene is ready
        // and has drawn a frame: its materials then use the same programs. Anything that stops drawing disposes them.
        function disposeRetiredMaterials() {
            if (!state.retiredMaterials.size) return;
            const materials = Array.from(state.retiredMaterials);
            state.retiredMaterials.clear();
            materials.forEach(function (material) {
                if (typeof material.dispose === 'function') material.dispose();
            });
        }

        function disposeObjectGraphs(objects) {
            const seenObjects = new Set();
            const avatars = new Set();
            (objects || []).filter(Boolean).forEach(function (object) {
                if (object.traverse) object.traverse(function (child) {
                    if (child.facilityOperatorAvatar) avatars.add(child.facilityOperatorAvatar);
                });
            });
            avatars.forEach(function (avatar) {
                avatar.root.traverse(function (child) { seenObjects.add(child); });
                avatar.dispose();
            });
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

        function isArtworkMaterial(material) {
            return Boolean(material && material.map
                && material.userData && material.userData.facilityArtwork === true);
        }

        function isAuthoredSurfaceMaterial(material) {
            return isArtworkMaterial(material) || Boolean(material
                && material.userData && material.userData.facilityAuthoredFinish === true);
        }

        // A library finish chosen for an object replaces the asset's own colors,
        // authored ones included (an object finish beats the asset's material).
        // Only printed artwork and placed signs keep their look.
        function isFinishProtectedMaterial(material) {
            return isArtworkMaterial(material) || Boolean(material
                && material.userData && material.userData.facilityEquipmentDecal === true);
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
                if (isAuthoredSurfaceMaterial(material)) {
                    material.polygonOffset = true;
                    material.polygonOffsetFactor = -1;
                    material.polygonOffsetUnits = -1;
                    return material;
                }
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
            // A printed surface can share a texture with a neutralized material.
            const retainTextures = function (candidate) {
                const materials = Array.isArray(candidate && candidate.material)
                    ? candidate.material : [candidate && candidate.material];
                materials.filter(Boolean).forEach(function (material) {
                    Object.values(material).forEach(function (value) {
                        if (value && value.isTexture) seenTextures.add(value);
                    });
                });
            };
            if (typeof object.traverse === 'function') object.traverse(retainTextures);
            else retainTextures(object);
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
                    if (material.userData && (material.userData.facilityAuthoredFinish === true
                            || material.userData.facilityComponentOverride === true
                            || material.userData.facilityAppearanceFinish === true)) {
                        material.wireframe = state.visualSettings.wireframe;
                        return;
                    }
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

        // The saved scene sets the base lighting; the viewer's Display settings
        // scale it. The Classic scene equals the defaults, so its result is
        // exactly the original viewport.
        function sceneRelativeSetting(key) {
            const value = state.visualSettings[key];
            const scene = state.viewportScene;
            if (!scene || !Number.isFinite(Number(scene[key])) || !DEFAULT_VISUAL_SETTINGS[key]) return value;
            return Number(scene[key]) * (value / DEFAULT_VISUAL_SETTINGS[key]);
        }

        function applyVisualSettingsRuntime() {
            if (state.ambientLight) {
                state.ambientLight.intensity = sceneRelativeSetting('ambient');
            }
            if (state.directionalLight) {
                state.directionalLight.intensity = sceneRelativeSetting('directional');
            }
            if (state.renderer) {
                state.renderer.toneMappingExposure = sceneRelativeSetting('exposure');
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
            const sceneBackground = state.viewportScene && state.viewportScene.background;
            if ('backgroundBlurriness' in state.scene) state.scene.backgroundBlurriness = 0;
            // A viewer's own background color wins; otherwise the saved scene decides.
            if (state.visualSettings.background === 'auto' && sceneBackground === 'environment'
                    && state.sceneEquirect) {
                state.scene.background = state.sceneEquirect;
                if ('backgroundBlurriness' in state.scene) state.scene.backgroundBlurriness = 0.35;
                state.ownsBackground = false;
                return true;
            }
            if (state.visualSettings.background !== 'auto'
                    && typeof THREE.Color === 'function') {
                background = new THREE.Color(state.visualSettings.background);
            } else if (/^#[0-9a-f]{6}$/i.test(String(sceneBackground || ''))
                    && typeof THREE.Color === 'function') {
                background = new THREE.Color(sceneBackground);
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
            const groundBounds = groundRuntime && groundRuntime.bounds(groundRuntime.surfaces(state.currentInput && state.currentInput.layout));
            if (groundBounds) return groundBounds;
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
                cameraMode: walkthrough.cameraMode,
                cameraSettings: Object.assign({}, walkthrough.cameraSettings),
                avatarSupported: Boolean(avatarRuntime && typeof THREE.SphereGeometry === 'function'),
                position: walkthrough.position ? Object.assign({}, walkthrough.position) : null,
                avatar: walkthrough.avatar ? walkthrough.avatar.snapshot() : null,
                cameraDistance: walkthrough.cameraDistance,
                cameraObstructed: walkthrough.cameraObstructed,
                locked: walkthrough.locked,
                eyeHeight: walkthroughSettings.eyeHeight,
                radius: walkthroughSettings.radius,
                walkSpeed: walkthroughSettings.walkSpeed,
                fastSpeed: walkthroughSettings.fastSpeed,
                navigationSpeed: walkthroughSettings.navigationSpeed,
                obstacleCount: walkthrough.obstaclePolygons.length,
                collisionCount: walkthrough.collisionCount,
                performance: Object.assign({}, walkthrough.performance),
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
                distanceCulling: droneSettings.distanceCulling,
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

        function wallVolumes() {
            const layout = state.currentInput && state.currentInput.layout;
            const floorY = finite(options.worldBounds && options.worldBounds.floorY, 0);
            return wallsRuntime.volumes(layout, floorY);
        }

        // The layout's columns (columns.py) as solids: drawn by renderColumns, and obstacles to the walker and the
        // drone as the walls are.
        function layoutColumnVolumes() {
            if (typeof wallsRuntime.columnVolumes !== 'function') return [];
            return wallsRuntime.columnVolumes(state.currentInput && state.currentInput.layout).map(function (volume) {
                return { id: volume.id, placementId: volume.placementId, polygon: volume.polygon,
                    minimumY: volume.minimumY, maximumY: volume.maximumY };
            });
        }

        function renderPerimeterWalls() {
            if (!state.modelRoot) return;
            wallVolumes().forEach(function (volume) {
                const shape = new THREE.Shape();
                volume.polygon.forEach(function (point, index) {
                    if (index === 0) shape.moveTo(point.x, -point.z);
                    else shape.lineTo(point.x, -point.z);
                });
                shape.closePath();
                const geometry = new THREE.ExtrudeGeometry(shape, {
                    depth: volume.maximumY - volume.minimumY, bevelEnabled: false, steps: 1,
                });
                geometry.rotateX(-Math.PI / 2);
                const material = new THREE.MeshStandardMaterial({ color: volume.color, roughness: 0.88 });
                const mesh = new THREE.Mesh(geometry, material);
                mesh.position.y = volume.minimumY;
                mesh.name = volume.id;
                mesh.visible = state.layerVisibility.walls !== false;
                state.modelRoot.add(mesh); state.wallObjects.push(mesh);
            });
            renderColumns();
            renderExteriorFinishes();
        }

        // Columns (columns.py): their outlines extruded like walls, shown and hidden with them, in their color or
        // their library finish (a plain color until the library has loaded).
        function renderColumns() {
            if (typeof wallsRuntime.columnVolumes !== 'function') return;
            const layout = state.currentInput && state.currentInput.layout;
            wallsRuntime.columnVolumes(layout).forEach(function (volume) {
                const shape = new THREE.Shape();
                volume.polygon.forEach(function (point, index) {
                    if (index === 0) shape.moveTo(point.x, -point.z);
                    else shape.lineTo(point.x, -point.z);
                });
                shape.closePath();
                const geometry = new THREE.ExtrudeGeometry(shape, {
                    depth: volume.maximumY - volume.minimumY, bevelEnabled: false, steps: 1,
                });
                geometry.rotateX(-Math.PI / 2);
                const material = new THREE.MeshStandardMaterial({ color: volume.color, roughness: 0.8 });
                const mesh = new THREE.Mesh(geometry, material);
                mesh.position.y = volume.minimumY;
                mesh.name = volume.id;
                mesh.userData.columnId = volume.columnId;
                mesh.visible = state.layerVisibility.walls !== false;
                state.modelRoot.add(mesh); state.columnObjects.push(mesh);
                const appearance = volume.appearance;
                if (!appearance || !appearance.appearanceId || !libraryRuntime || !finishesRuntime) return;
                const library = currentLibrary();
                const resolved = library && libraryRuntime.resolveAppearance(library, appearance, currentLayout());
                if (!resolved) return;
                mesh.updateMatrixWorld(true);
                // Its projection is its own (a cache of one), not the shared cache's: a column's outline is drawn anew
                // each time, so a shared entry would never be used again and would stay behind (Codex review).
                applyObjectFinish(mesh, createFinishMaterialFor(resolved, 1),
                    resolved.texture ? finishesRuntime.mappingFor(THREE, mesh, resolved) : null, new Map());
                material.dispose();
            });
        }

        // Columns take their finish when they are drawn, so a finish-only change (a custom finish edited) draws them
        // again. Their meshes leave the model root here: the layers' own clear leaves that to its callers.
        function redrawColumns() {
            if (!state.columnObjects.length) return;
            state.columnObjects.forEach(function (object) {
                if (object.parent && typeof object.parent.remove === 'function') object.parent.remove(object);
            });
            disposeObjectGraphs(state.columnObjects);
            state.columnObjects = [];
            renderColumns();
        }

        function renderExteriorFinishes() {
            const layout = state.currentInput.layout;
            const wall = wallsRuntime.data(layout);
            const finish = wall && wall.settings.exteriorFinish;
            if (typeof wallsRuntime.exteriorSurfaces !== 'function') return;
            const floorY = finite(options.worldBounds && options.worldBounds.floorY, 0);
            const generation = state.sceneGeneration;
            const batches = new Map();
            function adopt(mesh) {
                mesh.visible = state.layerVisibility.walls !== false;
                state.modelRoot.add(mesh); state.wallFinishObjects.push(mesh);
            }
            wallsRuntime.exteriorSurfaces(layout).forEach(function (surface) {
                if (!surface.artwork) {
                    // Layers (joint backing, panels, band, strips) sit millimetres apart; batched by layer so each
                    // keeps its own depth bias below, or far views z-fight into black streaks.
                    const key = surface.color + '|' + finite(surface.offset, .003);
                    const vertices = batches.get(key) || [];
                    const corners = [[-.5,-.5],[.5,-.5],[.5,.5],[-.5,.5]].map(function (p) {
                        return [surface.x+p[0]*surface.width*surface.nz,
                            floorY+surface.y+p[1]*surface.height,
                            surface.z-p[0]*surface.width*surface.nx];
                    });
                    [0,1,2,0,2,3].forEach(i=>vertices.push(...corners[i]));
                    batches.set(key,vertices); return;
                }
                const art = surface.artwork;
                const record = {artworkId:art.artworkId,imagePath:art.imagePath,status:'loading'};
                state.wallArtworkLoads.push(record);
                // The outermost layer (14 mm out): its depth bias must beat the panels' and band's, as its offset does.
                const material = new THREE.MeshBasicMaterial({color:0xffffff,transparent:true,alphaTest:.01,depthWrite:false,toneMapped:false,
                    polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-Math.max(1,Math.round(finite(surface.offset,.014)*1000))});
                const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1,1),material);
                mesh.userData.exteriorArtwork=record;
                mesh.name = 'exterior-artwork-'+art.artworkId;
                mesh.position.set(surface.x,floorY+surface.y,surface.z);
                mesh.rotation.y = Math.atan2(surface.nx,surface.nz);
                adopt(mesh); mesh.visible=false;
                state.pendingLoads += 1;
                function done(status) {
                    if (generation !== state.sceneGeneration) return;
                    record.status=status;state.pendingLoads=Math.max(0,state.pendingLoads-1);invalidate();
                }
                const texture = new THREE.TextureLoader().load(art.imagePath,function (loaded) {
                    if (generation !== state.sceneGeneration || !state.mounted) {loaded.dispose();return;}
                    const uv=art.uv||[0,0,1,1];
                    loaded.colorSpace=THREE.SRGBColorSpace;
                    loaded.offset.set(uv[0],uv[1]);loaded.repeat.set(uv[2]-uv[0],uv[3]-uv[1]);
                    mirrorTextureForDisplay(loaded);
                    const ratio=loaded.image.width*(uv[2]-uv[0])/(loaded.image.height*(uv[3]-uv[1]));
                    const width=Math.min(surface.width-.2,(surface.height-.2)*ratio);
                    mesh.scale.set(width,width/ratio,1);
                    material.needsUpdate=true;mesh.visible=state.layerVisibility.walls!==false;done('ready');
                },undefined,function () {
                    if (generation !== state.sceneGeneration) return;
                    warning('exterior_artwork_failed','Exterior artwork could not be loaded.',art.artworkId);done('failed');
                });
                material.map=texture;
            });
            batches.forEach(function (vertices,key) {
                const [color, offset] = key.split('|');
                const geometry=new THREE.BufferGeometry();
                geometry.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));geometry.computeVertexNormals();
                // An outer layer is pulled toward the camera in depth-buffer steps: it wins over the layers under it
                // and over the wall face at any distance.
                adopt(new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color,roughness:.82,metalness:.08,
                    polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-Math.max(1,Math.round(Number(offset)*1000))})));
            });
            const catalog=buildCatalogIndex(state.currentInput.assetCatalog);
            ((finish && finish.wallFaces)||[]).forEach(function (face) {
                const placement=state.placements.find(p=>p.placementId===face.placementId&&p.assetDefinitionRevision===face.assetDefinitionRevision);
                const entry=placement&&catalog.exact.get(placement.assetId+'|'+placement.assetDefinitionRevision);
                if(!placement||!wallsRuntime.isWallAsset(entry)) {
                    warning('exterior_wall_face_unavailable','Exterior finish needs its exact wall asset.',face.placementId);return;
                }
                const bounds=boundsForPlacement(placement),min=bounds.minimum,max=bounds.maximum;
                const mesh=new THREE.Mesh(new THREE.PlaneGeometry(max.x-min.x,max.y-min.y),
                    new THREE.MeshStandardMaterial({color:face.color,roughness:.82,metalness:.08,
                        polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1}));
                mesh.position.set((min.x+max.x)/2,(min.y+max.y)/2,face.face==='positive_z'?max.z+.003:min.z-.003);
                if(face.face==='negative_z')mesh.rotation.y=Math.PI;
                const group=new THREE.Group();group.add(mesh);applyPlacementTransform(group,placement);adopt(group);
            });
            renderFittedWallArt(layout, floorY, generation, adopt, catalog);
        }

        function renderFittedWallArt(layout, floorY, generation, adopt, catalog) {
            if (typeof wallsRuntime.fittedArtworkSurfaces !== 'function') return;
            const surfaces=wallsRuntime.fittedArtworkSurfaces(layout,function (id) {
                const placement=state.placements.find(p=>p.placementId===id);
                const entry=placement&&catalog.exact.get(placement.assetId+'|'+placement.assetDefinitionRevision);
                return placement&&entry?{placement,entry,bounds:boundsForPlacement(placement)}:null;
            });
            const resolvedIds=new Set(surfaces.map(s=>s.artwork.artworkId));
            wallsRuntime.fittedArtworks(layout).forEach(art=>{
                if(!resolvedIds.has(art.artworkId))warning('fitted_artwork_target_unavailable',
                    'Wall artwork needs a valid wall face without a door opening.',art.artworkId);
            });
            surfaces.forEach(function (surface) {
                const art=surface.artwork;
                const record={artworkId:art.artworkId,imagePath:art.imagePath,status:'loading',kind:'fitted',
                    planeWidth:surface.width,planeHeight:surface.height,target:art.target};
                state.wallArtworkLoads.push(record);
                // Keep artwork ahead of the paint decal even at grazing camera angles.
                const material=new THREE.MeshBasicMaterial({color:0xffffff,transparent:true,
                    alphaTest:.01,depthWrite:false,toneMapped:false,
                    polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-2});
                const mesh=new THREE.Mesh(new THREE.PlaneGeometry(surface.width,surface.height),material);
                mesh.name='fitted-artwork-'+art.artworkId;
                mesh.userData.exteriorArtwork=record;
                mesh.position.set(surface.x,surface.y+(surface.placement?0:floorY),surface.z);
                mesh.rotation.y=Math.atan2(surface.nx,surface.nz);
                let visibilityRoot=mesh;
                if (surface.placement) {
                    const group=new THREE.Group();group.add(mesh);
                    group.userData.exteriorArtwork=record;
                    applyPlacementTransform(group,surface.placement);adopt(group);
                    visibilityRoot=group;
                } else adopt(mesh);
                visibilityRoot.visible=false;mesh.visible=false;state.pendingLoads+=1;
                function done(status) {
                    if(generation!==state.sceneGeneration)return;
                    record.status=status;
                    // Layer refreshes can hide the parent while the image is loading.
                    visibilityRoot.visible=status==='ready'&&state.layerVisibility.walls!==false;
                    state.pendingLoads=Math.max(0,state.pendingLoads-1);invalidate();
                }
                const texture=new THREE.TextureLoader().load(art.imagePath,function(loaded) {
                    if(generation!==state.sceneGeneration||!state.mounted){loaded.dispose();return;}
                    const frame=wallsRuntime.fittedArtworkFrame(surface.width,surface.height,
                        loaded.image.width,loaded.image.height,art.uv);
                    record.imageFrame=frame;
                    loaded.colorSpace=THREE.SRGBColorSpace;
                    // Keep a full-wall transparent plane; sample only the trimmed, proportionally fitted graphic.
                    material.onBeforeCompile=function(shader) {
                        shader.uniforms.artworkFrame={value:new THREE.Vector4(frame.x,frame.y,frame.width,frame.height)};
                        shader.uniforms.artworkCrop={value:new THREE.Vector4(...art.uv)};
                        shader.fragmentShader='uniform vec4 artworkFrame;\nuniform vec4 artworkCrop;\n'+shader.fragmentShader;
                        shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>',`
                            #ifdef USE_MAP
                                vec2 artUv=(vMapUv-artworkFrame.xy)/artworkFrame.zw;
                                if(any(lessThan(artUv,vec2(0.0)))||any(greaterThan(artUv,vec2(1.0))))discard;
                                ${state.displayMirror ? 'artUv.x=1.0-artUv.x; // reads left to right on the mirrored canvas' : ''}
                                diffuseColor*=texture2D(map,mix(artworkCrop.xy,artworkCrop.zw,artUv));
                            #endif
                        `);
                    };
                    material.customProgramCacheKey=()=> state.displayMirror ? 'fitted-wall-art-v1-mirrored' : 'fitted-wall-art-v1';
                    material.needsUpdate=true;
                    mesh.visible=true;
                    mesh.updateWorldMatrix(true,false);
                    const position=mesh.getWorldPosition(new THREE.Vector3());
                    const scale=mesh.getWorldScale(new THREE.Vector3());
                    record.worldPosition={x:position.x,y:position.y,z:position.z};
                    record.worldWidth=surface.width*scale.x;record.worldHeight=surface.height*scale.y;
                    done('ready');
                },undefined,function() {
                    if(generation!==state.sceneGeneration)return;
                    warning('fitted_artwork_failed','Wall artwork could not be loaded.',art.artworkId);done('failed');
                });
                material.map=texture;
            });
        }

        function buildWalkthroughObstacles() {
            return state.placements.map(function (placement) {
                return {
                    placementId: placement.placementId,
                    polygon: footprintForPlacement(placement),
                };
            }).concat(wallVolumes().concat(layoutColumnVolumes()).map(function (volume) {
                return { placementId: volume.id, polygon: volume.polygon };
            })).filter(function (record) {
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
            }).concat(wallVolumes(), layoutColumnVolumes()).filter(Boolean).sort(function (left, right) {
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
            loadDeferredVisibleGroups();
            return true;
        }

        function disposeWalkthroughAvatar() {
            const walk = state.walkthrough;
            if (walk.avatar) walk.avatar.dispose();
            walk.avatar = null;
            walk.avatarSettling = false;
            walk.position = null;
            walk.obstacleIndex = null;
            walk.cameraDistance = 0;
            walk.cameraObstructed = false;
        }

        function syncWalkthroughCamera() {
            const walk = state.walkthrough;
            if (!walk.active || !walk.position || !state.camera) return;
            const body = walk.position;
            if (walk.lookQuaternion) setQuaternion(state.camera.quaternion, walk.lookQuaternion);
            if (walk.cameraMode === 'first-person') {
                setVector(state.camera.position, { x: body.x,
                    y: body.y + walkthroughSettings.eyeHeight, z: body.z });
                walk.cameraDistance = 0;
                walk.cameraObstructed = false;
                if (walk.avatar) walk.avatar.root.visible = false;
            } else {
                const direction = new THREE.Vector3();
                state.walkthroughControls.getDirection(direction);
                const anchor = { x: body.x, y: body.y + 1.05, z: body.z };
                const distance = walk.cameraSettings.distance;
                const desired = { x: anchor.x - direction.x * distance,
                    y: anchor.y - direction.y * distance + walk.cameraSettings.height,
                    z: anchor.z - direction.z * distance };
                const nearby = walkthroughSweptObstacles(walk.obstacleIndex, anchor,
                    { x: desired.x - anchor.x, z: desired.z - anchor.z }, 0.15);
                const resolved = resolveWalkthroughCamera({ anchor,
                    desired: desired,
                    bounds: walk.bounds, floorY: walk.floorY, obstacles: nearby });
                setVector(state.camera.position, resolved.position);
                walk.cameraDistance = resolved.distance;
                walk.cameraObstructed = resolved.obstructed;
                if (!walk.avatar) {
                    walk.avatar = avatarRuntime.createAvatar(THREE);
                    state.scene.add(walk.avatar.root);
                    walk.avatar.update({ position: body, heading: walk.heading, snap: true });
                }
                const minimumFrame = Math.max(1.05, 0.4 / Math.max(0.1, state.camera.aspect || 1))
                    / Math.tan((state.camera.fov || 45) * Math.PI / 360);
                walk.avatar.root.visible = resolved.distance >= minimumFrame;
                if (walk.avatar.root.visible && typeof state.camera.lookAt === 'function') {
                    state.camera.lookAt(anchor.x, anchor.y, anchor.z);
                } else if (!walk.avatar.root.visible) {
                    setVector(state.camera.position, { x: body.x, y: body.y + walkthroughSettings.eyeHeight, z: body.z });
                }
            }
            if (typeof state.camera.updateMatrixWorld === 'function') state.camera.updateMatrixWorld(true);
        }

        function setWalkthroughCameraSettings(value) {
            state.walkthrough.cameraSettings = cameraPreferences.save(value);
            syncWalkthroughCamera();
            notifyWalkthroughState();
            invalidate();
            return Object.assign({}, state.walkthrough.cameraSettings);
        }

        function setWalkthroughCameraMode(mode) {
            if (!['first-person', 'third-person'].includes(mode)) return false;
            if (mode === 'third-person'
                    && !(avatarRuntime && typeof THREE.SphereGeometry === 'function')) return false;
            state.walkthrough.cameraMode = mode;
            syncWalkthroughCamera();
            notifyWalkthroughState();
            invalidate();
            return true;
        }

        function lookWalkthroughAt(target) {
            const walk = state.walkthrough;
            if (!walk.active || !walk.position || !state.camera || !target
                    || !['x', 'y', 'z'].every(axis => Number.isFinite(target[axis]))) return false;
            const eye = {x: walk.position.x, y: walk.position.y + walkthroughSettings.eyeHeight, z: walk.position.z};
            if (Math.hypot(target.x - eye.x, target.y - eye.y, target.z - eye.z) < 1e-6) return false;
            setVector(state.camera.position, eye);
            state.camera.lookAt(target.x, target.y, target.z);
            walk.lookQuaternion = copyQuaternion(state.camera.quaternion);
            syncWalkthroughCamera();
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
            disposeWalkthroughAvatar();
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
            endNavigationInteraction();
            setWalkthroughContextFocus(null);
            applySelection();
            notifyWalkthroughState();
            invalidate();
            return true;
        }

        function deactivateWalkthroughForHandoff(reason) {
            const walkthrough = state.walkthrough;
            disposeWalkthroughAvatar();
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
            const groundRows = groundRuntime && groundRuntime.surfaces(state.currentInput.layout);
            const groundAtSpawn = groundRows && groundRuntime.sample(groundRows, spawn, 0);
            if (groundRows && !groundAtSpawn) {
                walkthrough.lastReason = 'no_ground_at_spawn';
                return notifyWalkthroughState();
            }
            const floorY = groundAtSpawn ? groundAtSpawn.y : finite(bounds.minimum.y, 0);
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
            walkthrough.position = Object.assign({}, walkthrough.spawn);
            // Only planar buckets are used; height does not change walking collision semantics.
            walkthrough.obstacleIndex = buildDroneSpatialIndex(records.map(record => ({
                id: record.placementId, polygon: record.polygon, minimumY: 0, maximumY: 1,
            })));
            walkthrough.performance = { movementFrames: 0, simulatedSeconds: 0,
                droppedSeconds: 0, collisionCandidates: 0, contextQueries: 0 };
            walkthrough.lastContextTime = null;
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
            const facing = new THREE.Vector3();
            state.walkthroughControls.getDirection(facing);
            walkthrough.heading = Math.atan2(-facing.x, -facing.z);
            walkthrough.lookQuaternion = copyQuaternion(state.camera.quaternion);
            walkthrough.cameraSettings = cameraPreferences.load();
            syncWalkthroughCamera();
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
            if (!placement || !placement.transform) return false;
            const bounds = transformedBounds(boundsForPlacement(placement), placement);
            const x = finite(position && position.x, 0);
            const z = finite(position && position.z, 0);
            // A nearby end of a long or rotated asset must not vanish with its origin.
            const dx = Math.max(bounds.minimum.x - x, 0, x - bounds.maximum.x);
            const dz = Math.max(bounds.minimum.z - z, 0, z - bounds.maximum.z);
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
            let requiredFar = Math.min(
                Math.max(droneSettings.maximumViewDistance * 1.5, 100),
                Math.hypot(viewDistance, altitude) + 20
            );
            if (!droneSettings.distanceCulling) {
                const bounds = state.worldBounds || state.drone.bounds;
                if (bounds) {
                    const distances = ['x', 'y', 'z'].map(function (axis) {
                        const point = finite(state.camera.position[axis], 0);
                        return Math.max(Math.abs(bounds.minimum[axis] - point),
                            Math.abs(bounds.maximum[axis] - point));
                    });
                    requiredFar = Math.max(requiredFar, Math.hypot(...distances) + 20);
                }
            }
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
            // Full scene is the normal product behavior. Distance hiding is opt-in,
            // distinct from Three's ordinary camera-frustum culling and asset LOD.
            if (!droneSettings.distanceCulling) {
                return new Set(state.placements.map(placement => placement.placementId));
            }
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
            if (sourceMode === 'walkthrough' && state.walkthrough.position) {
                handoffCamera.position = Object.assign({}, state.walkthrough.position,
                    { y: state.walkthrough.position.y + walkthroughSettings.eyeHeight });
            }
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
                endNavigationInteraction();
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
                    x: finite(walkthrough.position.x, NaN),
                    z: finite(walkthrough.position.z, NaN),
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
                setVector(state.camera.position, { x: walkthrough.position.x,
                    y: walkthrough.floorY + walkthroughSettings.eyeHeight, z: walkthrough.position.z });
                state.camera.lookAt(
                    next.x,
                    walkthrough.floorY + walkthroughSettings.eyeHeight,
                    next.z
                );
                walkthrough.lookQuaternion = copyQuaternion(state.camera.quaternion);
                if (typeof state.camera.updateMatrixWorld === 'function') {
                    state.camera.updateMatrixWorld(true);
                }
            }
            syncWalkthroughCamera();
            if (walkthrough.route.active) beginNavigationInteraction();
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
                g: 'KeyG', c: 'KeyC',
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
            if (event.target && event.target.closest
                    && event.target.closest('input,textarea,select,[contenteditable="true"],.ip-walk-camera-panel')) return;
            const code = movementCode(event);
            if (code === 'KeyC') {
                if (pressed && !event.repeat) {
                    if (typeof event.preventDefault === 'function') event.preventDefault();
                    setWalkthroughCameraMode(state.walkthrough.cameraMode === 'first-person'
                        ? 'third-person' : 'first-person');
                }
                return;
            }
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
            const hadMovement = walkthroughHasMovement();
            if (pressed) state.walkthrough.keys.add(code);
            else state.walkthrough.keys.delete(code);
            if (!hadMovement && walkthroughHasMovement()) beginNavigationInteraction();
            if (!walkthroughHasMovement()) {
                state.walkthrough.lastFrameTime = null;
                endNavigationInteraction();
            }
            invalidate();
        }

        function updateWalkthrough(timestamp) {
            const walkthrough = state.walkthrough;
            if (!walkthrough.active || !walkthrough.locked
                    || (!walkthroughHasActivity() && !walkthrough.avatarSettling) || !state.camera
                    || !state.walkthroughControls) {
                walkthrough.lastFrameTime = null;
                return false;
            }
            const now = finite(timestamp, 0);
            const elapsedSeconds = walkthrough.lastFrameTime === null
                ? 1 / 60
                : Math.max(0, (now - walkthrough.lastFrameTime) / 1000);
            // Consume ordinary slow frames in full. Bound long stalls, with no catch-up debt.
            // Collision subdivision below still checks every spatial step, including thin walls.
            const deltaSeconds = Math.min(0.25, elapsedSeconds);
            walkthrough.performance.movementFrames += 1;
            walkthrough.performance.simulatedSeconds += deltaSeconds;
            walkthrough.performance.droppedSeconds += elapsedSeconds - deltaSeconds;
            walkthrough.lastFrameTime = now;
            const keys = walkthrough.keys;
            let moveX = 0;
            let moveZ = 0;
            let deltaX = 0;
            let deltaZ = 0;
            let reachedWaypoint = null;
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
                // Screen right on the mirrored canvas is the camera's left.
                const side = state.displayMirror ? -1 : 1;
                const right = { x: -forward.z * side, z: forward.x * side };
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
                const dx = target.x - walkthrough.position.x;
                const dz = target.z - walkthrough.position.z;
                const remaining = Math.sqrt(dx * dx + dz * dz);
                const maximumDistance = walkthroughSettings.navigationSpeed
                    * deltaSeconds;
                if (remaining <= Math.max(1e-6, maximumDistance)) {
                    deltaX = dx;
                    deltaZ = dz;
                    reachedWaypoint = target;
                    walkthrough.route.pointIndex += 1;
                } else {
                    deltaX = dx / remaining * maximumDistance;
                    deltaZ = dz / remaining * maximumDistance;
                }
            }
            const nearby = walkthroughSweptObstacles(walkthrough.obstacleIndex,
                walkthrough.position, { x: deltaX, z: deltaZ }, walkthroughSettings.radius);
            walkthrough.performance.collisionCandidates = nearby.length;
            const result = resolveWalkthroughMovement({
                start: walkthrough.position,
                delta: {
                    x: deltaX,
                    z: deltaZ,
                },
                radius: walkthroughSettings.radius,
                bounds: walkthrough.bounds,
                obstacles: nearby,
            });
            if (!result.collided && reachedWaypoint) {
                result.position = { x: reachedWaypoint.x, z: reachedWaypoint.z };
            }
            const groundRows = groundRuntime && groundRuntime.surfaces(state.currentInput.layout);
            if (groundRows) {
                const grounded = groundRuntime.move(groundRows, walkthrough.position, result.position);
                result.position = grounded.position;
                result.collided = result.collided || grounded.collided;
                walkthrough.floorY = grounded.position.y;
            }
            if (result.collided) {
                walkthrough.collisionCount += 1;
                if (walkthrough.route.active) {
                    cancelWalkthroughNavigation('route_blocked');
                }
            }
            const travelX = result.position.x - walkthrough.position.x;
            const travelZ = result.position.z - walkthrough.position.z;
            const traveled = Math.hypot(travelX, travelZ);
            if (traveled > 1e-5) walkthrough.heading = Math.atan2(-travelX, -travelZ);
            walkthrough.position = { x: result.position.x, y: walkthrough.floorY, z: result.position.z };
            if (walkthrough.avatar) {
                walkthrough.avatarSettling = walkthrough.avatar.update({
                    position: walkthrough.position, heading: walkthrough.heading,
                    distance: traveled, deltaSeconds: deltaSeconds });
            }
            syncWalkthroughCamera();
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
            // Screen right on the mirrored canvas is the camera's left.
            const side = state.displayMirror ? -1 : 1;
            const right = {
                x: -forward.z / horizontalLength * side,
                y: 0,
                z: forward.x / horizontalLength * side,
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
            const groundRows = groundRuntime && groundRuntime.surfaces(state.currentInput.layout);
            if (groundRows) {
                const sample = groundRuntime.sample(groundRows,result.position,result.position.y);
                if (sample && result.position.y < sample.y+droneSettings.radius) {
                    result.position = {x:state.camera.position.x,y:state.camera.position.y,z:state.camera.position.z};
                    result.collided = true;
                }
            }
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

        function syncGroundEnvironment(rows, bounds) {
            const extensionsNow = state.currentInput && state.currentInput.layout && state.currentInput.layout.extensions;
            const planNow = extensionsNow && extensionsNow.facilityPlan;
            const marks = (extensionsNow && extensionsNow.facilityGround && extensionsNow.facilityGround.marks) || [];
            const signature = JSON.stringify({ground: rows, marks: marks, grid: state.gridVisible, theme: isLightTheme(),
                plan: planNow ? [planNow.widthMeters, planNow.depthMeters] : null});
            if (signature === state.environmentSignature) return true;
            clearEnvironmentObjects();
            state.environmentSignature = signature;
            rows.forEach(function (surface) {
                const data = groundRuntime.vertices(surface, FLOOR_THICKNESS, bounds.minimum.y-FLOOR_THICKNESS);
                const geometry = new THREE.BufferGeometry();
                geometry.setAttribute('position', new THREE.Float32BufferAttribute(data.positions, 3));
                geometry.setIndex(data.indices);
                geometry.computeVertexNormals();
                const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
                    color: surface.color, roughness: 1, metalness: 0}));
                mesh.name = 'InspectorProGround-' + surface.surfaceId;
                mesh.userData = {facilityEnvironment: 'floor', groundSurfaceId: surface.surfaceId};
                mesh.receiveShadow = true;
                state.environmentRoot.add(mesh);
                state.floorObject = mesh;
                // The grid belongs to the facility plan: ground reaching past it (a paved yard) has none.
                const plan = state.currentInput && state.currentInput.layout && state.currentInput.layout.extensions
                    && state.currentInput.layout.extensions.facilityPlan;
                const planWidth = plan ? finite(plan.widthMeters, Infinity) : Infinity;
                const planDepth = plan ? finite(plan.depthMeters, Infinity) : Infinity;
                const gridMinX = Math.max(surface.minX, plan ? 0 : -Infinity), gridMaxX = Math.min(surface.maxX, planWidth);
                const gridMinZ = Math.max(surface.minZ, plan ? 0 : -Infinity), gridMaxZ = Math.min(surface.maxZ, planDepth);
                if (state.gridVisible && surface.startElevation === surface.endElevation
                        && gridMaxX - gridMinX > 1e-6 && gridMaxZ - gridMinZ > 1e-6) {
                    const b = {minimum:{x:gridMinX,z:gridMinZ},maximum:{x:gridMaxX,z:gridMaxZ}};
                    const spacing = Math.max(.05, finite(options.floorGridSpacing,1),
                        (gridMaxX-gridMinX)/240, (gridMaxZ-gridMinZ)/240);
                    const grid = createFloorGrid(b, surface.startElevation, spacing, Math.max(spacing, finite(options.floorMajorGridSpacing,5)));
                    grid.objects.forEach(object => state.environmentRoot.add(object));
                    state.gridObjects.push(...grid.objects);
                }
            });
            // Ground marks: images painted flat on the paving, just above the surface under each one's centre.
            if (typeof THREE.TextureLoader === 'function' && typeof THREE.PlaneGeometry === 'function') {
                marks.forEach(function (mark) {
                    const below = groundRuntime.sample(rows, {x: mark.x, z: mark.z}, 0);
                    if (!below) return;
                    const texture = new THREE.TextureLoader().load(mark.imagePath, function () { invalidate(); });
                    if (THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
                    texture.offset.set(mark.uv[0], mark.uv[1]);
                    texture.repeat.set(mark.uv[2] - mark.uv[0], mark.uv[3] - mark.uv[1]);
                    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(mark.widthMeters, mark.depthMeters),
                        new THREE.MeshBasicMaterial({map: texture, transparent: true, alphaTest: .01, depthWrite: false,
                            toneMapped: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2}));
                    mesh.rotation.order = 'YXZ';  // lie flat, then turn about the vertical like a floor marking
                    mesh.rotation.set(-Math.PI / 2, finite(mark.rotationDegrees, 0) * Math.PI / 180, 0);
                    mesh.position.set(mark.x, below.y + 0.012, mark.z);
                    mesh.name = 'InspectorProGroundMark-' + mark.markId;
                    mesh.userData = {facilityEnvironment: 'ground-mark', groundMarkId: mark.markId};
                    mesh.raycast = function () {};
                    state.environmentRoot.add(mesh);
                });
            }
            state.environmentDiagnostics = {floorVisible:true, gridVisible:state.gridObjects.length>0,
                axesVisible:false, groundSurfaceCount:rows.length, minimumElevation:bounds.minimum.y,
                maximumElevation:bounds.maximum.y, width:bounds.maximum.x-bounds.minimum.x,
                depth:bounds.maximum.z-bounds.minimum.z};
            // An outdoor lamp's pool and beam end on the ground (L8).
            if (lightPoolsWanted()) syncLightPools();
            invalidate();
            return true;
        }

        // Site context (SC1): the layout's aerial photo lies just under the building
        // floor, at true scale. The server keeps each photo's corners in the
        // property frame (+X east, +Z north); the building pose maps them into the
        // layout's own frame. u runs east and v north, so the photo reads true on
        // the mirrored canvas without a flip (see state.displayMirror).
        function propertyToLayout(pose, x, z) {
            const bearing = finite(pose && pose.bearingDegrees, 0) * Math.PI / 180;
            const dx = x - finite(pose && pose.x, 0);
            const dz = z - finite(pose && pose.z, 0);
            return {
                x: dx * Math.cos(bearing) - dz * Math.sin(bearing),
                z: dx * Math.sin(bearing) + dz * Math.cos(bearing),
            };
        }

        function disposeSiteGround() {
            const ground = state.siteGround;
            state.siteGround = null;
            state.siteGroundKey = '';
            if (!ground) return;
            if (ground.parent && typeof ground.parent.remove === 'function') ground.parent.remove(ground);
            if (ground.geometry && typeof ground.geometry.dispose === 'function') ground.geometry.dispose();
            if (ground.material) {
                if (ground.material.map && typeof ground.material.map.dispose === 'function') {
                    ground.material.map.dispose();
                }
                if (typeof ground.material.dispose === 'function') ground.material.dispose();
            }
        }

        function syncSiteGround() {
            const layout = state.currentInput && state.currentInput.layout;
            const site = layout && layout.extensions && layout.extensions.facilitySiteContext;
            const image = site && Array.isArray(site.imagery) ? site.imagery[0] : null;
            const usable = image && Array.isArray(image.corners) && image.corners.length === 4
                && typeof image.imagePath === 'string';
            const floorY = finite(layout && layout.coordinateFrame && layout.coordinateFrame.floorElevation, 0);
            const key = usable ? JSON.stringify([image.imageId, image.corners, site.buildingPose, floorY]) : '';
            if (key === state.siteGroundKey && (key === '' || state.siteGround)) return;
            disposeSiteGround();
            if (!usable || !state.siteRoot || typeof THREE.BufferGeometry !== 'function'
                    || typeof THREE.MeshBasicMaterial !== 'function'
                    || typeof THREE.TextureLoader !== 'function') return;
            const corners = image.corners.map(function (corner) {
                return propertyToLayout(site.buildingPose, finite(corner.x, 0), finite(corner.z, 0));
            });
            const y = floorY - 0.05;
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.Float32BufferAttribute([].concat.apply([],
                corners.map(function (corner) { return [corner.x, y, corner.z]; })), 3));
            geometry.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
            geometry.setIndex([0, 2, 1, 0, 3, 2]);
            geometry.computeVertexNormals();
            const texture = new THREE.TextureLoader().load(image.imagePath, function () { invalidate(); });
            if (THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
            if (state.renderer && state.renderer.capabilities
                    && typeof state.renderer.capabilities.getMaxAnisotropy === 'function') {
                texture.anisotropy = Math.min(8, state.renderer.capabilities.getMaxAnisotropy());
            }
            // A backdrop: drawn first (renderOrder) and writing no depth, so ground the plan sinks below the
            // photo (a dock-height truck yard) and what stands on it show over it instead of being buried.
            const material = new THREE.MeshBasicMaterial({
                map: texture, side: THREE.DoubleSide, toneMapped: false, depthWrite: false,
            });
            const ground = new THREE.Mesh(geometry, material);
            ground.name = 'InspectorProFacilitySiteGround';
            ground.renderOrder = -20;
            ground.userData = { facilityEnvironment: 'site-ground', imageId: image.imageId };
            ground.raycast = function () {};
            state.siteRoot.add(ground);
            state.siteGround = ground;
            state.siteGroundKey = key;
            invalidate();
        }

        function syncEnvironment() {
            syncSiteGround();
            syncSiteAreas();
            syncSiteRoutes();
            if (!state.environmentRoot || options.showFloor === false) {
                clearEnvironmentObjects();
                invalidate();
                return false;
            }
            const bounds = configuredEnvironmentBounds();
            if (!bounds) return false;
            const groundRows = groundRuntime && groundRuntime.surfaces(state.currentInput && state.currentInput.layout);
            if (groundRows) return syncGroundEnvironment(groundRows, bounds);
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

        // Projected finish geometries belong to the groups (and finish previews) that use them. Between full rebuilds
        // nothing else clears the cache: removed groups left theirs (2026-11-03, Codex on 4a05de6), and so did a
        // projection replaced on its mesh before it was drawn, as a textured part finish over an object finish
        // replaces the object finish's (Codex on 33fb535). The cache notes each key used while something is built.
        function trackedFinishGeometryCache() {
            const cache = new Map();
            cache.get = function (key) {
                if (state.finishProjectionSink) state.finishProjectionSink.add(key);
                return Map.prototype.get.call(cache, key);
            };
            return cache;
        }

        // A removed group's projections leave the cache once no other group uses them. Those it drew are disposed with
        // its objects; those it replaced before drawing are disposed here. The cache holds only projections it made
        // (cachedFinishGeometry hands a model's own geometry back uncached), so none of these is a model's.
        function forgetFinishGeometries(record) {
            const keys = record.finishProjections || [];
            if (!keys.length) return;
            const drawn = new Set();
            [record.container, record.prototypeObject].forEach(function (root) {
                if (root && typeof root.traverse === 'function') {
                    root.traverse(function (object) { if (object.geometry) drawn.add(object.geometry); });
                }
            });
            keys.forEach(function (key) {
                const users = (state.finishProjectionUsers.get(key) || 1) - 1;
                if (users > 0) {
                    state.finishProjectionUsers.set(key, users);
                    return;
                }
                state.finishProjectionUsers.delete(key);
                const geometry = Map.prototype.get.call(state.finishGeometryCache, key);
                state.finishGeometryCache.delete(key);
                if (geometry && !drawn.has(geometry) && typeof geometry.dispose === 'function') geometry.dispose();
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
            forgetFinishGeometries(record);
            disposeObjectGraphs([record.container, record.prototypeObject]);
            dropLightPools(record);
            state.lampSpots.lists.delete(record);
            record.pickObjects.forEach(function (object) {
                state.instanceLookup.delete(object);
                if (object && object.uuid) state.instanceLookup.delete(object.uuid);
            });
            const removed = new Set(record.pickObjects);
            state.pickObjects = state.pickObjects.filter(function (object) {
                return !removed.has(object);
            });
        }

        // Everything clearModel removes except the model groups and the finish geometries they use.
        function clearModelLayers() {
            state.appearanceSceneKey = null;
            state.finishSceneKey = null;
            if(state.componentHighlight){disposeObjectGraphs([state.componentHighlight]);state.componentHighlight=null;}
            clearFinishPreview();
            clearEquipmentDecals();
            disposeObjectGraphs(state.wallObjects);
            state.wallObjects = [];
            disposeObjectGraphs(state.columnObjects);
            state.columnObjects = [];
            disposeObjectGraphs(state.floorSurfaceObjects);
            state.floorSurfaceObjects = [];
            disposeObjectGraphs(state.wallFinishObjects);
            state.wallFinishObjects = [];
            state.wallArtworkLoads = [];
            disposeGhostObject();
            disposeProposalObjects();
            disposeObjectGraphs(state.floorMarkingObjects);
            state.floorMarkingObjects = [];
            state.floorMarkingCount = 0;
            state.floorMarkingTextures = new Map();
            disposeObjectGraphs(state.zoneObjects);
            state.zoneObjects = [];
            disposeObjectGraphs(state.zoneCeilingObjects);
            state.zoneCeilingObjects = [];
            disposeObjectGraphs(state.zoneRoofObjects);
            state.zoneRoofObjects = [];
            disposeObjectGraphs(state.routeObjects);
            state.routeObjects = [];
        }

        function detachModelRootChildren() {
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

        function clearModel() {
            clearModelLayers();
            state.renderGroups.forEach(disposeRenderGroup);
            state.renderGroups.clear();
            state.pickObjects = [];
            state.instanceLookup.clear();
            // Prototypes reload on a full rebuild, so their projected copies are stale.
            state.finishGeometryCache.forEach(function (geometry) {
                if (geometry && geometry.userData && geometry.userData.facilityFinishGeometry
                        && typeof geometry.dispose === 'function') geometry.dispose();
            });
            state.finishGeometryCache.clear();
            state.finishProjectionUsers.clear();
            detachModelRootChildren();
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
            // Markings that look alike share one texture.
            const key = JSON.stringify(['paint', marking.markingType || 'solid_line', marking.fillColor || '',
                marking.strokeColor || '', marking.text || '']);
            if (state.floorMarkingTextures.has(key)) return state.floorMarkingTextures.get(key);
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
            const texture = mirrorTextureForDisplay(configureFloorMarkingTexture(
                new THREE.CanvasTexture(canvas)
            ), 'v');
            state.floorMarkingTextures.set(key, texture);
            return texture;
        }

        function floorMarkingTextTexture(marking, value) {
            const label = String(value || '').trim();
            const documentRef = options.document || (root && root.document);
            if (!label || !documentRef
                    || typeof documentRef.createElement !== 'function'
                    || typeof THREE.CanvasTexture !== 'function') return null;
            // One texture per label and colour (a car park's PARKING boxes share one), at 1024 x 256: about
            // 450 pixels a metre on a 2.25 m stall label, a quarter of the memory of 2048 x 512.
            const key = JSON.stringify(['text', label, marking.strokeColor || '#111827']);
            if (state.floorMarkingTextures.has(key)) return state.floorMarkingTextures.get(key);
            const canvas = documentRef.createElement('canvas');
            canvas.width = 1024;
            canvas.height = 256;
            const context = typeof canvas.getContext === 'function'
                ? canvas.getContext('2d') : null;
            if (!context) return null;
            context.clearRect(0, 0, canvas.width, canvas.height);
            context.fillStyle = marking.strokeColor || '#111827';
            context.font = '800 150px Segoe UI, Arial, sans-serif';
            context.textAlign = 'center';
            context.textBaseline = 'middle';
            context.fillText(label, 512, 128, 980);
            const texture = mirrorTextureForDisplay(configureFloorMarkingTexture(
                new THREE.CanvasTexture(canvas)
            ), 'v');
            state.floorMarkingTextures.set(key, texture);
            return texture;
        }

        // Writing and pictures must still read correctly on the mirrored canvas,
        // so they are sampled mirrored (u -> offset + repeat - repeat * u). On a
        // wall the flip is left-right. A floor plane's texture "up" points south
        // (PlaneGeometry turned -90 degrees about x), so floor writing flips top
        // to bottom instead and then reads upright with north up, as on the plan.
        function mirrorTextureForDisplay(texture, axis) {
            if (!state.displayMirror || !texture || !texture.offset || !texture.repeat) return texture;
            const key = axis === 'v' ? 'y' : 'x';
            texture.offset[key] += texture.repeat[key];
            texture.repeat[key] = -texture.repeat[key];
            return texture;
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
            const GeometryType = THREE.PlaneGeometry || THREE.BoxGeometry;
            if (typeof GeometryType !== 'function'
                    || typeof THREE.Mesh !== 'function') return null;
            const material = floorPaintMaterial(marking, optionsValue);
            if (!material) return null;
            // Paint has no thickness. Opposing box faces fight for depth at
            // overview distances; bake the plane rotation so aisle yaw stays local.
            const geometry = THREE.PlaneGeometry
                ? new GeometryType(Math.max(0.001, width), Math.max(0.001, depth))
                : new GeometryType(Math.max(0.001, width), 0.0008, Math.max(0.001, depth));
            if (THREE.PlaneGeometry) geometry.rotateX(-Math.PI / 2);
            const mesh = new THREE.Mesh(geometry, material);
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

        // A large layout's paint is drawn as one mesh per colour and per label texture: hundreds of markings of
        // several planes each otherwise cost thousands of draw calls a frame (Factory 02: 1,156 markings, about
        // 3,900 calls). Markings are never picked in 3D, so nothing needs them one by one; a small layout keeps
        // one object per marking.
        function batchFloorMarkings(objects) {
            const buckets = new Map(), output = [];
            objects.forEach(function (object) {
                object.updateMatrix();
                object.children.forEach(function (mesh) {
                    const material = mesh.material, geometry = mesh.geometry;
                    mesh.updateMatrix();
                    const key = JSON.stringify([material.map ? material.map.uuid : null, material.color.getHex(),
                        material.opacity, material.transparent, material.depthWrite, material.side, !!geometry.index,
                        Object.keys(geometry.attributes).sort()]);
                    if (!buckets.has(key)) buckets.set(key, { material: material, meshes: [] });
                    buckets.get(key).meshes.push({ mesh: mesh, object: object });
                });
            });
            try {
                buckets.forEach(function (bucket) {
                    const copies = bucket.meshes.map(function (entry) {
                        return entry.mesh.geometry.clone().applyMatrix4(
                            new THREE.Matrix4().multiplyMatrices(entry.object.matrix, entry.mesh.matrix));
                    });
                    const geometry = options.mergeGeometries(copies, false);
                    copies.forEach(function (copy) { if (copy !== geometry) copy.dispose(); });
                    if (!geometry) throw new Error('floor marking geometries did not merge');
                    geometry.computeBoundingBox();
                    geometry.computeBoundingSphere();
                    const mesh = new THREE.Mesh(geometry, bucket.material);
                    const material = bucket.material;
                    // Paint first, then see-through fills, then the writing on top.
                    mesh.renderOrder = material.map ? 8 : (material.transparent ? 7 : 6);
                    mesh.name = 'FacilityFloorMarkings:' + output.length;
                    mesh.userData = { facilityFloorMarkingBatch: true, pieceCount: bucket.meshes.length };
                    mesh.visible = state.layerVisibility.markings !== false;
                    output.push(mesh);
                });
            } catch (error) {
                output.forEach(function (mesh) { mesh.geometry.dispose(); });
                reportError('floor_marking_batch_failed', error);
                return null;
            }
            const kept = new Set(output.map(function (batch) { return batch.material; }));
            objects.forEach(function (object) {
                object.children.forEach(function (mesh) {
                    mesh.geometry.dispose();
                    // Textures are shared through the cache and stay with the batches.
                    if (!kept.has(mesh.material)) mesh.material.dispose();
                });
            });
            return output;
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
            const built = [];
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
                built.push(object);
            });
            state.floorMarkingCount = built.length;
            const batches = built.length >= FLOOR_MARKING_BATCH_MINIMUM
                && typeof options.mergeGeometries === 'function'
                ? batchFloorMarkings(built) : null;
            (batches || built).forEach(function (object) {
                state.modelRoot.add(object);
                state.floorMarkingObjects.push(object);
            });
            return state.floorMarkingCount;
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

        // Zone limits on the 3D floor: a thin line along every zone edge in the
        // plan's zone outline color, centred on the boundary so neighbouring
        // zones share one line. Presentation only: the layout is unchanged and
        // nothing here is pickable.
        function zoneFloorPoints(zone) {
            const points = (Array.isArray(zone && zone.boundary) ? zone.boundary : [])
                .map(function (point) {
                    return {
                        x: finite(point && point.x, NaN),
                        z: finite(point && point.z, NaN),
                    };
                })
                .filter(function (point) {
                    return Number.isFinite(point.x) && Number.isFinite(point.z);
                });
            const first = points[0];
            const last = points[points.length - 1];
            if (points.length > 1 && first.x === last.x && first.z === last.z) {
                points.pop();
            }
            return points;
        }

        function addZoneLimits(rootObject, points) {
            points.forEach(function (start, index) {
                const end = points[(index + 1) % points.length];
                const dx = end.x - start.x;
                const dz = end.z - start.z;
                const length = Math.hypot(dx, dz);
                if (!(length > 0.000001)) return;
                // Half a line longer at each end, so corners close.
                const segment = addFloorPaintRectangle(
                    rootObject,
                    { fillColor: ZONE_LIMIT_COLOR },
                    length + ZONE_LIMIT_WIDTH,
                    ZONE_LIMIT_WIDTH,
                    (start.x + end.x) / 2,
                    (start.z + end.z) / 2,
                    { color: ZONE_LIMIT_COLOR, opacity: 0.95 }
                );
                if (!segment) return;
                const radians = -Math.atan2(dz, dx);
                setQuaternion(segment.quaternion, {
                    x: 0,
                    y: Math.sin(radians / 2),
                    z: 0,
                    w: Math.cos(radians / 2),
                });
                segment.renderOrder = 3;
            });
        }

        function renderZoneMarkings() {
            if (!state.modelRoot || typeof THREE.Mesh !== 'function') return 0;
            const RootType = THREE.Group || THREE.Object3D;
            if (typeof RootType !== 'function') return 0;
            const layout = state.currentInput && state.currentInput.layout || {};
            const zones = Array.isArray(layout.zones) ? layout.zones.slice() : [];
            zones.sort(function (left, right) {
                return String(left && left.zoneId || '').localeCompare(
                    String(right && right.zoneId || '')
                );
            });
            zones.forEach(function (zone, index) {
                const points = zoneFloorPoints(zone);
                if (points.length < 3) return;
                const object = new RootType();
                object.name = 'FacilityZone:' + String(zone.zoneId || index);
                addZoneLimits(object, points);
                if (!object.children || !object.children.length) return;
                if (object.position && typeof object.position.set === 'function') {
                    object.position.set(
                        0,
                        finite(zone.floorElevation, 0) + 0.001 + index * 0.000001,
                        0
                    );
                }
                const extensions = zone.extensions || {};
                const knowledge = extensions.knowledgeFoundation || {};
                object.userData = Object.assign({}, object.userData, {
                    facilityZone: true,
                    zoneId: zone.zoneId,
                    zoneType: zone.zoneType,
                    visibilityLayer: knowledge.parentZoneId ? 'cells' : 'zones',
                });
                object.visible = state.layerVisibility[
                    object.userData.visibilityLayer
                ] !== false;
                state.modelRoot.add(object);
                state.zoneObjects.push(object);
            });
            return state.zoneObjects.length;
        }

        // ---- Zone ceilings (2026-11-02) ----------------------------------------------------------------------------
        // A zone with extensions.ceiling {heightMeters} (ceilings.py: lamps hang from it) shows a flat ceiling over its
        // boundary at its floor plus that height: matte charcoal, facing down only, so it is seen from inside the room
        // and the view from above or outside looks straight in. It casts no shadow, is never picked and follows the
        // overhead layer. Hung lamps sit in it: anything at its own height is drawn in front of it. Its finish
        // 'acoustic-tile' draws it as a white tiled suspended ceiling instead (CEILING_TILE). 'open-deck' (2026-11-03)
        // draws exposed steel whose underside is at that height (OPEN_DECK): the flat face is its ribbed deck, at the
        // top of the steel, and the joists, girders and edges are a child of it (zoneOpenDeckStructures). Where it
        // borders a lower ceiling, a bulkhead closes the step between them (zoneCeilingSteps), up to the deck.
        function renderZoneCeilings() {
            if (!state.modelRoot || typeof THREE.Mesh !== 'function' || typeof THREE.BufferGeometry !== 'function'
                    || !THREE.ShapeUtils || typeof THREE.MeshStandardMaterial !== 'function') return 0;
            const layout = state.currentInput && state.currentInput.layout || {};
            let tiles = null;
            let ribs = null;
            (Array.isArray(layout.zones) ? layout.zones : []).forEach(function (zone) {
                const ceiling = zone && zone.extensions && zone.extensions.ceiling;
                const height = Number(ceiling && ceiling.heightMeters);
                if (!(height > 0)) return;
                const textures = typeof THREE.DataTexture === 'function';
                const tiled = ceiling.finish === 'acoustic-tile' && textures;
                const deck = ceiling.finish === 'open-deck';
                const points = zoneFloorPoints(zone);
                const floor = finite(zone.floorElevation, 0);
                const depth = deck ? openDeckDepth(height) : 0;
                const frame = deck ? outlineFrame(points) : null;
                const geometry = zoneCeilingGeometry(points, floor + height + depth, tiled ? function (point) {
                    return [point.x / CEILING_TILE.meters, point.z / CEILING_TILE.meters];
                } : (deck && textures ? function (point) {
                    // Across the ribs, which run at right angles to the joists.
                    return [(point.x * frame.across.x + point.z * frame.across.z) / OPEN_DECK.ribTile,
                        (point.x * frame.along.x + point.z * frame.along.z) / OPEN_DECK.ribTile];
                } : null));
                if (!geometry) return;
                if (tiled && !tiles) tiles = ceilingTileTexture();
                if (deck && textures && !ribs) ribs = openDeckTexture();
                const look = tiled ? { color: '#ffffff', map: tiles } : (deck ? (ribs ? { color: '#ffffff', map: ribs }
                    : { color: new THREE.Color().setRGB(OPEN_DECK.deck[0] / 255, OPEN_DECK.deck[1] / 255,
                        OPEN_DECK.deck[2] / 255, THREE.SRGBColorSpace) }) : { color: ZONE_CEILING_COLOR });
                const material = new THREE.MeshStandardMaterial(Object.assign({
                    roughness: 1, metalness: 0,
                    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
                }, look));
                const mesh = new THREE.Mesh(geometry, material);
                mesh.name = 'FacilityZoneCeiling:' + String(zone.zoneId || '');
                mesh.castShadow = false;
                mesh.receiveShadow = false;
                mesh.raycast = function () {};
                mesh.userData = Object.assign({}, mesh.userData, {
                    facilityZoneCeiling: true, zoneId: zone.zoneId, heightMeters: height,
                    finish: tiled ? 'acoustic-tile' : (deck ? 'open-deck' : null),
                    ceilingY: floor + height, deckDepth: depth,
                });
                mesh.visible = state.layerVisibility.overhead !== false;
                state.modelRoot.add(mesh);
                state.zoneCeilingObjects.push(mesh);
            });
            const entries = state.zoneCeilingObjects.map(function (mesh) {
                const zone = (layout.zones || []).find(function (item) { return item && item.zoneId === mesh.userData.zoneId; });
                return { mesh: mesh, points: zoneFloorPoints(zone), y: mesh.geometry.attributes.position.getY(0) };
            });
            zoneCeilingSteps(entries);
            zoneOpenDeckStructures(entries);
            return state.zoneCeilingObjects.length;
        }

        // The 'open-deck' steel's depth under a ceiling `height` m up (OPEN_DECK).
        function openDeckDepth(height) {
            return Math.min(OPEN_DECK.maxDepth, Math.max(OPEN_DECK.minDepth, OPEN_DECK.depthPerMeter * height));
        }

        // An outline's plan frame: `along` its longest side and `across` at right angles to it (a rectangle's short
        // way), unit vectors. A side is a run of edges in one straight line, so an edge split in parts counts whole.
        function outlineFrame(points) {
            const edges = [];
            points.forEach(function (point, i) {
                const next = points[(i + 1) % points.length];
                const length = Math.hypot(next.x - point.x, next.z - point.z);
                if (length > 1e-9) edges.push({ length: length, x: (next.x - point.x) / length, z: (next.z - point.z) / length });
            });
            const straight = function (a, b) { return Math.abs(a.x * b.z - a.z * b.x) < 1e-6 && a.x * b.x + a.z * b.z > 0; };
            // Start at an edge that begins a side, so a side across the outline's first point is not split.
            let start = 0;
            while (start < edges.length && straight(edges[(start + edges.length - 1) % edges.length], edges[start])) start += 1;
            if (start === edges.length) start = 0;
            let along = { x: 1, z: 0 };
            let longest = 0;
            let side = null;
            for (let k = 0; k <= edges.length; k += 1) {
                const edge = k < edges.length ? edges[(start + k) % edges.length] : null;
                if (side && edge && straight(side, edge)) {
                    side.length += edge.length;
                    continue;
                }
                if (side && side.length > longest + 1e-9) {
                    longest = side.length;
                    along = { x: side.x, z: side.z };
                }
                side = edge && { length: edge.length, x: edge.x, z: edge.z };
            }
            return { along: along, across: { x: -along.z, z: along.x } };
        }

        // An outline for overlap tests: its points and plan bounds, and its triangles once outlinesOverlap needs them.
        function overlapOutline(points) {
            const outline = { points: points, triangles: null };
            Object.assign(outline, planBounds(points));
            return outline;
        }

        function planBounds(points) {
            let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
            points.forEach(function (point) {
                minX = Math.min(minX, point.x);
                minZ = Math.min(minZ, point.z);
                maxX = Math.max(maxX, point.x);
                maxZ = Math.max(maxZ, point.z);
            });
            return { minX: minX, minZ: minZ, maxX: maxX, maxZ: maxZ };
        }

        // The plan area two bounds share (0 when apart or only touching).
        function boundsShared(a, b) {
            return Math.max(0, Math.min(a.maxX, b.maxX) - Math.max(a.minX, b.minX))
                * Math.max(0, Math.min(a.maxZ, b.maxZ) - Math.max(a.minZ, b.minZ));
        }

        // Whether two outlines (overlapOutline) share more than `least` square metres of plan: their triangles
        // clipped pair by pair (each triangle is convex). Outlines or triangles whose bounds share no more are
        // skipped, it stops once the total passes `least`, and areas are taken from a corner of each polygon (and the
        // triangulation from the outline's first point) so they stay exact far from the origin.
        function outlinesOverlap(a, b, least) {
            if (a.points.length < 3 || b.points.length < 3 || boundsShared(a, b) <= least) return false;
            const triangles = function (outline) {
                if (!outline.triangles) {
                    const points = outline.points;
                    const origin = points[0];
                    outline.triangles = THREE.ShapeUtils.triangulateShape(points.map(function (point) {
                        return new THREE.Vector2(point.x - origin.x, point.z - origin.z);
                    }), []).map(function (corners) {
                        const triangle = corners.map(function (k) { return points[k]; });
                        return { corners: triangle, bounds: planBounds(triangle) };
                    });
                }
                return outline.triangles;
            };
            const area = function (polygon) {
                const o = polygon[0];
                let twice = 0;
                for (let i = 1; i + 1 < polygon.length; i += 1) {
                    twice += (polygon[i].x - o.x) * (polygon[i + 1].z - o.z) - (polygon[i + 1].x - o.x) * (polygon[i].z - o.z);
                }
                return twice / 2;
            };
            const clip = function (subject, by) {
                const sign = area(by) > 0 ? 1 : -1;
                let polygon = subject;
                for (let i = 0; i < by.length && polygon.length; i += 1) {
                    const p = by[i];
                    const q = by[(i + 1) % by.length];
                    const side = function (v) { return sign * ((q.x - p.x) * (v.z - p.z) - (q.z - p.z) * (v.x - p.x)); };
                    const kept = [];
                    polygon.forEach(function (v, k) {
                        const w = polygon[(k + 1) % polygon.length];
                        const sv = side(v);
                        const sw = side(w);
                        if (sv >= 0) kept.push(v);
                        if ((sv >= 0) !== (sw >= 0)) {
                            const t = sv / (sv - sw);
                            kept.push({ x: v.x + (w.x - v.x) * t, z: v.z + (w.z - v.z) * t });
                        }
                    });
                    polygon = kept;
                }
                return polygon.length >= 3 ? Math.abs(area(polygon)) : 0;
            };
            const fromB = triangles(b);
            let shared = 0;
            for (const triangle of triangles(a)) {
                for (const other of fromB) {
                    if (boundsShared(triangle.bounds, other.bounds) <= 0) continue;
                    shared += clip(triangle.corners, other.corners);
                    if (shared > least) return true;
                }
            }
            return false;
        }

        // Under each 'open-deck' ceiling (its mesh is the deck), its steel (openDeckGeometry), a child of the ceiling:
        // its layer, its disposal. No shadow, never picked; one pair of materials for all.
        function zoneOpenDeckStructures(entries) {
            let materials = null;
            entries.forEach(function (entry) {
                if (!(entry.mesh.userData.deckDepth > 0)) return;
                const geometry = openDeckGeometry(entry, entries);
                if (!geometry) return;
                if (!materials) {
                    materials = [
                        new THREE.MeshStandardMaterial({ color: OPEN_DECK.joist, roughness: 0.8, metalness: 0 }),
                        new THREE.MeshStandardMaterial({ color: OPEN_DECK.girder, roughness: 0.8, metalness: 0 }),
                    ];
                }
                const steel = new THREE.Mesh(geometry, materials);
                steel.name = 'FacilityZoneOpenDeck:' + String(entry.mesh.userData.zoneId || '');
                steel.castShadow = false;
                steel.receiveShadow = false;
                steel.raycast = function () {};
                steel.userData = Object.assign({}, steel.userData, { facilityZoneOpenDeck: true },
                    geometry.userData.openDeck);
                entry.mesh.add(steel);
            });
        }

        // The steel under 'open-deck' ceiling `entry` ({mesh, points, y}; y is its deck, the top of the steel), in the
        // outline's frame (outlineFrame):
        // - joists every OPEN_DECK.spacing along the outline's longest edge, evenly from end to end, each across the
        //   outline wherever a line at right angles to that edge is inside it: a bottom chord with its underside at
        //   the ceiling's height, a top chord under the deck and a zigzag web, about one depth per panel;
        // - where the outline is more than OPEN_DECK.spanPerDepth depths across, girders along it (an I section as
        //   deep as the joists) split it into equal bays, and the joists span from girder to girder;
        // - edges: a face from the ceiling's height up to the deck, facing in, just inside each part of the outline
        //   that has no ceiling beyond it (an outer wall) or a higher one or one that is not this open deck, so the
        //   band above the wall tops does not open onto the outside. Over a lower ceiling the bulkhead closes it from
        //   that ceiling up (zoneCeilingSteps); next to the same open deck the steel just goes on.
        // Groups: 0 the joists, 1 the girders and edges. Flat faces, shaded mostly as facing up, like the ceilings: lit
        // like the room, so the light grey reads in any scene and the sides are not half as bright. Null if empty.
        function openDeckGeometry(entry, entries) {
            const points = entry.points;
            if (points.length < 3) return null;
            const depth = entry.mesh.userData.deckDepth;
            const bottom = entry.mesh.userData.ceilingY;
            const top = entry.y;
            const frame = outlineFrame(points);
            const L = frame.along;
            const S = frame.across;
            const parts = [{ positions: [], normals: [] }, { positions: [], normals: [] }];
            // A quad a b c d into group `part`, turned to face `facing`, shaded with normal `lit` (by default: a face
            // seen from below or above as facing up, a side by where it faces, tipped up by OPEN_DECK.sideLift).
            const face = function (part, a, b, c, d, facing, lit) {
                const ux = b[0] - a[0]; const uy = b[1] - a[1]; const uz = b[2] - a[2];
                const vx = c[0] - a[0]; const vy = c[1] - a[1]; const vz = c[2] - a[2];
                const toward = (uy * vz - uz * vy) * facing[0] + (uz * vx - ux * vz) * facing[1]
                    + (ux * vy - uy * vx) * facing[2];
                let shade = lit || [0, 1, 0];
                if (!lit && Math.abs(facing[1]) < 0.5) {
                    const length = Math.hypot(facing[0], OPEN_DECK.sideLift, facing[2]);
                    shade = [facing[0] / length, OPEN_DECK.sideLift / length, facing[2] / length];
                }
                (toward < 0 ? [a, c, b, a, d, c] : [a, b, c, a, c, d]).forEach(function (corner) {
                    parts[part].positions.push(corner[0], corner[1], corner[2]);
                    parts[part].normals.push(shade[0], shade[1], shade[2]);
                });
            };
            // A bar from a to b, `wide` along `side` (a unit vector at right angles to it) and `high` the third way:
            // its four long faces.
            const bar = function (part, a, b, side, wide, high) {
                const ux = b[0] - a[0];
                const uy = b[1] - a[1];
                const uz = b[2] - a[2];
                const length = Math.hypot(ux, uy, uz);
                if (!(length > 1e-6)) return;
                const u = [ux / length, uy / length, uz / length];
                const t = [u[1] * side[2] - u[2] * side[1], u[2] * side[0] - u[0] * side[2], u[0] * side[1] - u[1] * side[0]];
                const corner = function (point, s, k) {
                    return [point[0] + side[0] * s * wide / 2 + t[0] * k * high / 2,
                        point[1] + side[1] * s * wide / 2 + t[1] * k * high / 2,
                        point[2] + side[2] * s * wide / 2 + t[2] * k * high / 2];
                };
                face(part, corner(a, 1, -1), corner(b, 1, -1), corner(b, 1, 1), corner(a, 1, 1), side);
                face(part, corner(a, -1, -1), corner(b, -1, -1), corner(b, -1, 1), corner(a, -1, 1),
                    [-side[0], -side[1], -side[2]]);
                face(part, corner(a, -1, 1), corner(b, -1, 1), corner(b, 1, 1), corner(a, 1, 1), t);
                face(part, corner(a, -1, -1), corner(b, -1, -1), corner(b, 1, -1), corner(a, 1, -1), [-t[0], -t[1], -t[2]]);
            };
            const at = function (l, s, y) { return [L.x * l + S.x * s, y, L.z * l + S.z * s]; };
            const ls = points.map(function (point) { return point.x * L.x + point.z * L.z; });
            const ss = points.map(function (point) { return point.x * S.x + point.z * S.z; });
            // Where the line at `value` of l (alongLine) or of s is inside the outline: [from, to] in the other.
            const runs = function (alongLine, value) {
                const a = alongLine ? ls : ss;
                const b = alongLine ? ss : ls;
                const hits = [];
                for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
                    if ((a[i] > value) !== (a[j] > value)) hits.push(b[i] + (value - a[i]) * (b[j] - b[i]) / (a[j] - a[i]));
                }
                hits.sort(function (u, v) { return u - v; });
                const found = [];
                for (let k = 0; k + 1 < hits.length; k += 2) found.push([hits[k], hits[k + 1]]);
                return found;
            };
            const lMin = Math.min.apply(null, ls);
            const lMax = Math.max.apply(null, ls);
            const sMin = Math.min.apply(null, ss);
            const sMax = Math.max.apply(null, ss);
            const bays = Math.max(1, Math.ceil((sMax - sMin) / (OPEN_DECK.spanPerDepth * depth) - 1e-9));
            const girderLines = [];
            for (let k = 1; k < bays; k += 1) girderLines.push(sMin + (sMax - sMin) * k / bays);
            const chord = OPEN_DECK.chordHeight;
            const lowY = bottom + chord / 2;
            const highY = top - chord / 2;
            const sideL = [L.x, 0, L.z];
            const sideS = [S.x, 0, S.z];
            const count = { joists: 0, girders: 0, edges: 0 };
            const joistLines = Math.max(1, Math.round((lMax - lMin) / OPEN_DECK.spacing));
            for (let k = 0; k < joistLines; k += 1) {
                const l = lMin + (lMax - lMin) * (k + 0.5) / joistLines;
                runs(true, l).forEach(function (run) {
                    const stops = [run[0]].concat(girderLines.filter(function (s) {
                        return s > run[0] + 0.1 && s < run[1] - 0.1;
                    }), [run[1]]);
                    for (let m = 0; m + 1 < stops.length; m += 1) {
                        // Flush with the edges, so the web does not poke out past the outline.
                        const from = stops[m] + OPEN_DECK.edgeInset;
                        const to = stops[m + 1] - OPEN_DECK.edgeInset;
                        if (!(to - from > 0.2)) continue;
                        count.joists += 1;
                        bar(0, at(l, from, lowY), at(l, to, lowY), sideL, OPEN_DECK.chordWidth, chord);
                        bar(0, at(l, from, highY), at(l, to, highY), sideL, OPEN_DECK.chordWidth, chord);
                        const panels = Math.max(2, Math.round((to - from) / depth));
                        for (let panel = 0; panel < panels; panel += 1) {
                            const s0 = from + (to - from) * panel / panels;
                            const s1 = from + (to - from) * (panel + 1) / panels;
                            const rising = panel % 2 === 0;
                            bar(0, at(l, s0, rising ? lowY : highY), at(l, s1, rising ? highY : lowY), sideL,
                                OPEN_DECK.webSize, OPEN_DECK.webSize);
                        }
                    }
                });
            }
            const flange = OPEN_DECK.flangeThickness;
            girderLines.forEach(function (s) {
                runs(false, s).forEach(function (run) {
                    if (!(run[1] - run[0] > 0.2)) return;
                    count.girders += 1;
                    bar(1, at(run[0], s, bottom + flange / 2), at(run[1], s, bottom + flange / 2), sideS,
                        OPEN_DECK.flangeWidth, flange);
                    bar(1, at(run[0], s, top - flange / 2), at(run[1], s, top - flange / 2), sideS,
                        OPEN_DECK.flangeWidth, flange);
                    bar(1, at(run[0], s, (bottom + top) / 2), at(run[1], s, (bottom + top) / 2), sideS,
                        OPEN_DECK.webThickness, top - bottom - 2 * flange);
                });
            });
            let twiceArea = 0;
            points.forEach(function (point, i) {
                const next = points[(i + 1) % points.length];
                twiceArea += point.x * next.z - next.x * point.z;
            });
            const sign = twiceArea > 0 ? 1 : -1;
            const others = entries.filter(function (other) { return other !== entry && other.points.length >= 3; });
            points.forEach(function (point, i) {
                const next = points[(i + 1) % points.length];
                const length = Math.hypot(next.x - point.x, next.z - point.z);
                if (!(length > 1e-6)) return;
                const n = { x: sign * (next.z - point.z) / length, z: -sign * (next.x - point.x) / length };
                const inset = OPEN_DECK.edgeInset;
                outlineEdgePieces(point, next, n, others).forEach(function (piece) {
                    const beyond = piece.beyond;
                    let high = top;
                    if (beyond) {
                        if (beyond.mesh.userData.deckDepth > 0 && Math.abs(beyond.mesh.userData.ceilingY - bottom) < 0.01) return;
                        if (beyond.y < top - 0.01) high = Math.min(top, beyond.y);
                    }
                    if (!(high - bottom > 0.01)) return;
                    count.edges += 1;
                    const a = { x: piece.from.x - n.x * inset, z: piece.from.z - n.z * inset };
                    const b = { x: piece.to.x - n.x * inset, z: piece.to.z - n.z * inset };
                    face(1, [a.x, bottom, a.z], [b.x, bottom, b.z], [b.x, high, b.z], [a.x, high, a.z], [-n.x, 0, -n.z],
                        [0, 1, 0]);
                });
            });
            if (!parts[0].positions.length && !parts[1].positions.length) return null;
            const geometry = new THREE.BufferGeometry();
            const positions = parts[0].positions.concat(parts[1].positions);
            const normals = parts[0].normals.concat(parts[1].normals);
            geometry.addGroup(0, parts[0].positions.length / 3, 0);
            geometry.addGroup(parts[0].positions.length / 3, parts[1].positions.length / 3, 1);
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
            geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
            if (typeof geometry.computeBoundingSphere === 'function') geometry.computeBoundingSphere();
            if (typeof geometry.computeBoundingBox === 'function') geometry.computeBoundingBox();
            geometry.userData.openDeck = { joists: count.joists, girders: count.girders, edges: count.edges, depth: depth };
            return geometry;
        }

        // The parts of outline edge p to q (outward normal n), cut where another outline's corner lies on it or one of
        // its edges crosses it, each {from, to, beyond}: the other ({points, y}) just outside the part's middle, the
        // highest if several, or null.
        function outlineEdgePieces(p, q, n, others) {
            const length = Math.hypot(q.x - p.x, q.z - p.z);
            const ux = (q.x - p.x) / length;
            const uz = (q.z - p.z) / length;
            const cuts = [0, length];
            others.forEach(function (other) {
                other.points.forEach(function (v, index) {
                    const t = (v.x - p.x) * ux + (v.z - p.z) * uz;
                    if (Math.abs(ux * (v.z - p.z) - uz * (v.x - p.x)) <= 0.05 && t > 1e-3 && t < length - 1e-3) cuts.push(t);
                    const w = other.points[(index + 1) % other.points.length];
                    const ex = w.x - v.x;
                    const ez = w.z - v.z;
                    const denominator = ux * ez - uz * ex;
                    if (Math.abs(denominator) < 1e-12) return;
                    const along = ((v.x - p.x) * ez - (v.z - p.z) * ex) / denominator;
                    const across = ((v.x - p.x) * uz - (v.z - p.z) * ux) / denominator;
                    if (across > 0 && across < 1 && along > 1e-3 && along < length - 1e-3) cuts.push(along);
                });
            });
            cuts.sort(function (a, b) { return a - b; });
            const pieces = [];
            for (let k = 0; k + 1 < cuts.length; k += 1) {
                const from = cuts[k];
                const to = cuts[k + 1];
                if (!(to - from > 1e-3)) continue;
                const middle = (from + to) / 2;
                const x = p.x + ux * middle + n.x * 0.05;
                const z = p.z + uz * middle + n.z * 0.05;
                let beyond = null;
                others.forEach(function (other) {
                    if (pointInOutline(other.points, x, z) && (!beyond || other.y > beyond.y)) beyond = other;
                });
                pieces.push({ from: { x: p.x + ux * from, z: p.z + uz * from }, to: { x: p.x + ux * to, z: p.z + uz * to },
                    beyond: beyond });
            }
            return pieces;
        }

        // The open deck's ribs seen from below (OPEN_DECK), across one tile: per rib the low flange (nearest, the
        // lightest), a sloping web, the recessed high flange (a little darker) and the other web, a thin darker line
        // at each fold. The same along the ribs. Mipmapped and anisotropic, so far off it is an even light grey.
        function openDeckTexture() {
            const width = OPEN_DECK.texels;
            const height = 4;
            const perRib = width / Math.round(OPEN_DECK.ribTile / OPEN_DECK.ribPitch);
            const data = new Uint8Array(width * height * 4);
            for (let column = 0; column < width; column += 1) {
                const f = (column % perRib) / perRib;
                let shade = f < 0.3 ? 1 : (f < 0.45 ? 0.86 : (f < 0.85 ? 0.93 : 0.86));
                const fold = [0, 0.3, 0.45, 0.85].some(function (edge) { return Math.abs(f - edge) < 0.5 / perRib; });
                if (fold) shade *= 0.9;
                const color = OPEN_DECK.deck.map(function (value) { return Math.round(value * shade); });
                for (let row = 0; row < height; row += 1) data.set([color[0], color[1], color[2], 255], (row * width + column) * 4);
            }
            const texture = new THREE.DataTexture(data, width, height, THREE.RGBAFormat);
            texture.name = 'FacilityOpenDeck';
            texture.wrapS = THREE.RepeatWrapping;
            texture.wrapT = THREE.RepeatWrapping;
            texture.magFilter = THREE.LinearFilter;
            texture.minFilter = THREE.LinearMipmapLinearFilter;
            texture.generateMipmaps = true;
            if (THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
            if (state.renderer && state.renderer.capabilities
                    && typeof state.renderer.capabilities.getMaxAnisotropy === 'function') {
                texture.anisotropy = Math.min(8, state.renderer.capabilities.getMaxAnisotropy());
            }
            texture.needsUpdate = true;
            return texture;
        }

        // Whether plan point (x, z) is inside the outline (even-odd).
        function pointInOutline(points, x, z) {
            let hit = false;
            for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
                const a = points[i];
                const b = points[j];
                if ((a.z > z) !== (b.z > z) && x < (b.x - a.x) * (z - a.z) / (b.z - a.z) + a.x) hit = !hit;
            }
            return hit;
        }

        // Where a ceiling borders a lower one (their outlines share an edge, the higher one beyond the lower one's
        // edge), a vertical bulkhead from the lower ceiling up to the higher one, so the step does not open onto the
        // space above the lower ceiling. It faces the higher room only, in that ceiling's color (tiles: their plain
        // white; an open deck: its edges' grey, up to the deck), and is a child of that ceiling: its layer, its
        // disposal.
        function zoneCeilingSteps(entries) {
            const inside = pointInOutline;
            const outwardSign = function (points) {
                let twiceArea = 0;
                points.forEach(function (point, i) {
                    const next = points[(i + 1) % points.length];
                    twiceArea += point.x * next.z - next.x * point.z;
                });
                return twiceArea > 0 ? 1 : -1;
            };
            entries.forEach(function (high) {
                const positions = [];
                entries.forEach(function (low) {
                    if (low === high || !(high.y - low.y > 0.01) || low.points.length < 3) return;
                    const sign = outwardSign(low.points);
                    low.points.forEach(function (p, i) {
                        const q = low.points[(i + 1) % low.points.length];
                        const length = Math.hypot(q.x - p.x, q.z - p.z);
                        if (!(length > 0.01)) return;
                        const ux = (q.x - p.x) / length;
                        const uz = (q.z - p.z) / length;
                        const nx = sign * uz;
                        const nz = -sign * ux;
                        high.points.forEach(function (r, k) {
                            const t = high.points[(k + 1) % high.points.length];
                            const off = function (point) { return Math.abs(ux * (point.z - p.z) - uz * (point.x - p.x)); };
                            if (off(r) > 0.05 || off(t) > 0.05) return;
                            const tr = (r.x - p.x) * ux + (r.z - p.z) * uz;
                            const tt = (t.x - p.x) * ux + (t.z - p.z) * uz;
                            const from = Math.max(0, Math.min(tr, tt));
                            const to = Math.min(length, Math.max(tr, tt));
                            if (!(to - from > 0.01)) return;
                            const middle = (from + to) / 2;
                            if (!inside(high.points, p.x + ux * middle + nx * 0.05, p.z + uz * middle + nz * 0.05)) return;
                            const a = [p.x + ux * from, p.z + uz * from];
                            const b = [p.x + ux * to, p.z + uz * to];
                            // Turned to face the higher room (n), as front faces are counter-clockwise.
                            const corners = [[a[0], low.y, a[1]], [a[0], high.y, a[1]], [b[0], high.y, b[1]],
                                [b[0], low.y, b[1]]];
                            const ex = corners[1][0] - corners[0][0];
                            const ey = corners[1][1] - corners[0][1];
                            const ez = corners[1][2] - corners[0][2];
                            const fx = corners[2][0] - corners[0][0];
                            const fy = corners[2][1] - corners[0][1];
                            const fz = corners[2][2] - corners[0][2];
                            const facing = (ey * fz - ez * fy) * nx + (ex * fy - ey * fx) * nz;
                            const order = facing > 0 ? [0, 1, 2, 0, 2, 3] : [0, 2, 1, 0, 3, 2];
                            order.forEach(function (c) { positions.push(corners[c][0], corners[c][1], corners[c][2]); });
                        });
                    });
                });
                if (!positions.length) return;
                const normals = [];
                for (let i = 0; i < positions.length; i += 3) normals.push(0, 1, 0);
                const geometry = new THREE.BufferGeometry();
                geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
                geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
                if (typeof geometry.computeBoundingSphere === 'function') geometry.computeBoundingSphere();
                const finish = high.mesh.userData.finish;
                const step = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
                    color: finish === 'acoustic-tile' ? CEILING_TILE.plain
                        : (finish === 'open-deck' ? OPEN_DECK.girder : ZONE_CEILING_COLOR), roughness: 1, metalness: 0,
                    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
                }));
                step.name = 'FacilityZoneCeilingStep:' + String(high.mesh.userData.zoneId || '');
                step.castShadow = false;
                step.receiveShadow = false;
                step.raycast = function () {};
                step.userData = Object.assign({}, step.userData, { facilityZoneCeilingStep: true });
                high.mesh.add(step);
            });
        }

        function zoneCeilingDiagnostics(mesh) {
            let attached = false;
            for (let object = mesh; object; object = object.parent) if (object === state.scene) attached = true;
            const index = mesh.geometry.index;
            const position = mesh.geometry.attributes.position;
            let facingDown = 0;
            for (let t = 0; index && t < index.count; t += 3) {
                const a = index.getX(t);
                const b = index.getX(t + 1);
                const c = index.getX(t + 2);
                const up = (position.getZ(b) - position.getZ(a)) * (position.getX(c) - position.getX(a))
                    - (position.getX(b) - position.getX(a)) * (position.getZ(c) - position.getZ(a));
                if (up < 0) facingDown += 1;
            }
            const step = (mesh.children || []).find(function (child) { return child.userData.facilityZoneCeilingStep; });
            const steel = (mesh.children || []).find(function (child) { return child.userData.facilityZoneOpenDeck; });
            return { zoneId: mesh.userData.zoneId, heightMeters: mesh.userData.heightMeters, visible: mesh.visible,
                finish: mesh.userData.finish, inScene: attached, y: position.count ? position.getY(0) : null,
                triangles: index ? index.count / 3 : 0, facingDown: facingDown,
                stepTriangles: step ? step.geometry.attributes.position.count / 3 : 0,
                steel: steel ? { joists: steel.userData.joists, girders: steel.userData.girders,
                    edges: steel.userData.edges, depth: steel.userData.depth,
                    triangles: steel.geometry.attributes.position.count / 3 } : null };
        }

        // The acoustic tile: one 600 mm tile, its T-bar half on each edge, repeated by the ceiling's plan UVs.
        function ceilingTileTexture() {
            const size = CEILING_TILE.texels;
            const data = new Uint8Array(size * size * 4);
            for (let row = 0; row < size; row += 1) {
                for (let column = 0; column < size; column += 1) {
                    const edge = Math.min(row, column, size - 1 - row, size - 1 - column) < CEILING_TILE.gridTexels;
                    const color = edge ? CEILING_TILE.grid : CEILING_TILE.tile;
                    data.set([color[0], color[1], color[2], 255], (row * size + column) * 4);
                }
            }
            const texture = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
            texture.name = 'FacilityCeilingTile';
            texture.wrapS = THREE.RepeatWrapping;
            texture.wrapT = THREE.RepeatWrapping;
            texture.magFilter = THREE.LinearFilter;
            texture.minFilter = THREE.LinearMipmapLinearFilter;
            texture.generateMipmaps = true;
            if (THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
            if (state.renderer && state.renderer.capabilities
                    && typeof state.renderer.capabilities.getMaxAnisotropy === 'function') {
                texture.anisotropy = Math.min(8, state.renderer.capabilities.getMaxAnisotropy());
            }
            texture.needsUpdate = true;
            return texture;
        }

        // The outline as triangles facing down at height y, so only the view from below draws them; null if it does
        // not triangulate. Their shading normal points up: lit like the room under it (as indoor light bounces up),
        // not black because no light shines up at it, so it reads as its color by day and dark in Evening.
        // With `uv` (a plan point to [u, v]) it carries UVs: for tiles, plan metres over the tile size, so every tiled
        // ceiling shares one grid; for the open deck, across its ribs.
        function zoneCeilingGeometry(points, y, uv) {
            if (points.length < 3) return null;
            const triangles = THREE.ShapeUtils.triangulateShape(points.map(function (point) {
                return new THREE.Vector2(point.x, point.z);
            }), []);
            if (!triangles.length) return null;
            const positions = [];
            const normals = [];
            const uvs = [];
            const indices = [];
            points.forEach(function (point) {
                positions.push(point.x, y, point.z);
                normals.push(0, 1, 0);
                if (uv) Array.prototype.push.apply(uvs, uv(point));
            });
            triangles.forEach(function (triangle) {
                const a = points[triangle[0]];
                const b = points[triangle[1]];
                const c = points[triangle[2]];
                // The y of (b - a) x (c - a): below zero, a, b, c already turn to face down.
                const up = (b.z - a.z) * (c.x - a.x) - (b.x - a.x) * (c.z - a.z);
                if (up > 0) indices.push(triangle[0], triangle[2], triangle[1]);
                else indices.push(triangle[0], triangle[1], triangle[2]);
            });
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
            geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
            if (uv) geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
            geometry.setIndex(indices);
            if (typeof geometry.computeBoundingSphere === 'function') geometry.computeBoundingSphere();
            if (typeof geometry.computeBoundingBox === 'function') geometry.computeBoundingBox();
            return geometry;
        }

        // ---- Zone roofs (2026-11-02) -------------------------------------------------------------------------------
        // A zone with extensions.roof {heightMeters} (ceilings.py) shows a flat commercial roof over its boundary
        // (ZONE_ROOF): its underside at the zone's floor plus that height, a membrane on top (ROOF_MEMBRANE) and a low
        // parapet along the edge with a coping. It is solid from every side: from above and outside the membrane and
        // the parapet, from inside the underside and the inner side of the parapet's face, so with the roof on no view
        // from inside the building opens onto the sky. A ceiling at the roof's height is drawn in front of the
        // underside (its polygon offset is smaller). It casts no shadow, is never picked and follows the roof
        // sheeting layer (hidden by default, so the overview looks in). Where two roofs meet (a building and its
        // annex), the lower one's parapet has no outer face there (it would face into the other building) and the
        // higher one's outer face comes down to the lower one's membrane. Over an 'open-deck' ceiling (2026-11-03) the
        // roof sits on its deck: the slab rises to the top of the highest deck under it (one whose outline shares some
        // area with the roof's) and the parapet's face still comes down to the wall tops, closing the band between.
        function renderZoneRoofs() {
            if (!state.modelRoot || typeof THREE.Mesh !== 'function' || typeof THREE.BufferGeometry !== 'function'
                    || !THREE.ShapeUtils || typeof THREE.MeshStandardMaterial !== 'function') return 0;
            const layout = state.currentInput && state.currentInput.layout || {};
            let materials = null;
            const entries = [];
            const decks = [];
            (Array.isArray(layout.zones) ? layout.zones : []).forEach(function (zone) {
                const ceiling = zone && zone.extensions && zone.extensions.ceiling;
                const height = Number(ceiling && ceiling.heightMeters);
                if (!(height > 0) || ceiling.finish !== 'open-deck') return;
                const points = zoneFloorPoints(zone);
                if (points.length < 3) return;
                decks.push({
                    outline: overlapOutline(points),
                    top: finite(zone.floorElevation, 0) + height + openDeckDepth(height) + OPEN_DECK.deckThickness,
                });
            });
            (Array.isArray(layout.zones) ? layout.zones : []).forEach(function (zone) {
                const roof = zone && zone.extensions && zone.extensions.roof;
                const height = Number(roof && roof.heightMeters);
                if (!(height > 0)) return;
                const points = zoneFloorPoints(zone);
                const wall = finite(zone.floorElevation, 0) + height;
                let base = wall;
                const outline = points.length >= 3 ? overlapOutline(points) : null;
                decks.forEach(function (deck) {
                    if (outline && deck.top > base && outlinesOverlap(deck.outline, outline, 1e-3)) base = deck.top;
                });
                entries.push({ zone: zone, height: height, points: points, base: base, wall: wall });
            });
            entries.forEach(function (entry) {
                const zone = entry.zone;
                const height = entry.height;
                const geometry = zoneRoofGeometry(entry.points, entry.base, entries.filter(function (other) {
                    return other !== entry && other.points.length >= 3;
                }), entry.wall);
                if (!geometry) return;
                if (!materials) {
                    const membrane = typeof THREE.DataTexture === 'function'
                        ? { color: '#ffffff', map: zoneRoofTexture() } : { color: ZONE_ROOF.membrane };
                    materials = [
                        new THREE.MeshStandardMaterial(Object.assign({ roughness: 0.95, metalness: 0 }, membrane)),
                        new THREE.MeshStandardMaterial({ color: ZONE_ROOF.parapet, roughness: 0.95, metalness: 0 }),
                        new THREE.MeshStandardMaterial({ color: ZONE_ROOF.coping, roughness: 0.8, metalness: 0 }),
                        new THREE.MeshStandardMaterial({
                            color: ZONE_ROOF.underside, roughness: 1, metalness: 0,
                            polygonOffset: true, polygonOffsetFactor: 2, polygonOffsetUnits: 2,
                        }),
                    ];
                }
                const mesh = new THREE.Mesh(geometry, materials);
                mesh.name = 'FacilityZoneRoof:' + String(zone.zoneId || '');
                mesh.castShadow = false;
                mesh.receiveShadow = false;
                mesh.raycast = function () {};
                mesh.userData = Object.assign({}, mesh.userData, {
                    facilityZoneRoof: true, zoneId: zone.zoneId, heightMeters: height, base: entry.base,
                });
                mesh.visible = state.layerVisibility.roofSheeting !== false;
                state.modelRoot.add(mesh);
                state.zoneRoofObjects.push(mesh);
            });
            return state.zoneRoofObjects.length;
        }

        function zoneRoofDiagnostics(mesh) {
            let attached = false;
            for (let object = mesh; object; object = object.parent) if (object === state.scene) attached = true;
            const position = mesh.geometry.attributes.position;
            let low = Infinity;
            let high = -Infinity;
            let facingDown = 0;
            for (let i = 0; i < position.count; i += 1) {
                low = Math.min(low, position.getY(i));
                high = Math.max(high, position.getY(i));
                if (i % 3 !== 0) continue;
                // The y of (b - a) x (c - a): below zero, the triangle faces down.
                const up = (position.getZ(i + 1) - position.getZ(i)) * (position.getX(i + 2) - position.getX(i))
                    - (position.getX(i + 1) - position.getX(i)) * (position.getZ(i + 2) - position.getZ(i));
                if (up < -1e-9) facingDown += 1;
            }
            const underside = (mesh.geometry.groups || []).find(function (group) { return group.materialIndex === 3; });
            const membrane = Array.isArray(mesh.material) ? mesh.material[0] : null;
            return { zoneId: mesh.userData.zoneId, heightMeters: mesh.userData.heightMeters, visible: mesh.visible,
                base: mesh.userData.base,
                inScene: attached, lowest: low, highest: high, triangles: position.count / 3, facingDown: facingDown,
                undersideTriangles: underside ? underside.count / 3 : 0, textured: Boolean(membrane && membrane.map) };
        }

        // The membrane texture (ROOF_MEMBRANE), tileable: smooth noise on lattices that wrap at the tile's edge for the
        // mottling and the weathering, a slightly different tone per sheet, and at each lap a thin shadow line under the
        // upper sheet's edge with its welded strip catching the light. Mipmapped and anisotropic, so the laps fade
        // evenly with distance instead of shimmering.
        function zoneRoofTexture() {
            const size = ROOF_MEMBRANE.texels;
            const perMeter = size / ROOF_MEMBRANE.meters;
            const sheet = Math.round(ROOF_MEMBRANE.sheet * perMeter);
            const hash = function (n) {
                let h = Math.imul(n ^ 0x5bd1e995, 0x27d4eb2d);
                h ^= h >>> 15;
                h = Math.imul(h, 0x85ebca6b);
                h ^= h >>> 13;
                return (h >>> 0) / 4294967296;
            };
            // Smooth noise in [-1, 1] over `cells` lattice cells per side of the tile, added to `shade` as
            // `amount` times it (or, for the weathering, darkening where it is above zero), row by row.
            const shade = new Float32Array(size * size);
            const layer = function (cells, salt, amount, weathering) {
                const values = new Float32Array(cells * cells);
                for (let k = 0; k < values.length; k += 1) values[k] = hash(k + salt * 1000003) * 2 - 1;
                const left = new Int32Array(size);
                const right = new Int32Array(size);
                const blend = new Float32Array(size);
                for (let x = 0; x < size; x += 1) {
                    const u = x / size * cells;
                    const i = Math.floor(u);
                    left[x] = i % cells;
                    right[x] = (i + 1) % cells;
                    blend[x] = (u - i) * (u - i) * (3 - 2 * (u - i));
                }
                for (let y = 0; y < size; y += 1) {
                    const v = y / size * cells;
                    const j = Math.floor(v);
                    const sv = (v - j) * (v - j) * (3 - 2 * (v - j));
                    const low = (j % cells) * cells;
                    const high = ((j + 1) % cells) * cells;
                    for (let x = 0; x < size; x += 1) {
                        const a = values[low + left[x]];
                        const b = values[low + right[x]];
                        const c = values[high + left[x]];
                        const d = values[high + right[x]];
                        const n = (a + (b - a) * blend[x]) * (1 - sv) + (c + (d - c) * blend[x]) * sv;
                        if (weathering) {
                            if (n > 0) shade[y * size + x] -= amount * n * n;
                        } else {
                            shade[y * size + x] += amount * n;
                        }
                    }
                }
            };
            [[4, 4], [16, 2.5], [64, 1.5], [256, 1.2]].forEach(function (spec, k) { layer(spec[0], k + 1, spec[1], false); });
            layer(6, 9, 9, true);
            // Across a lap, d texels from the upper sheet's edge (below zero: on the sheet under it): the shadow it
            // casts, its edge, then the welded strip, about 19 cm in all, so the laps still read from mid distance.
            const lap = function (d) {
                if (d >= -2 && d < 0) return -9;
                if (d >= 0 && d < 2) return -20;
                if (d >= 2 && d < 6) return 6;
                return 0;
            };
            const data = new Uint8Array(size * size * 4);
            for (let y = 0; y < size; y += 1) {
                const strip = Math.floor(y / sheet);
                const across = y - strip * sheet;
                const tone = (hash(strip + 77) - 0.5) * 4;
                const side = across < 6 ? lap(across) : (across >= sheet - 2 ? lap(across - sheet) : 0);
                const endLap = Math.floor(((strip * ROOF_MEMBRANE.endLapStep) % ROOF_MEMBRANE.meters) * perMeter);
                for (let x = 0; x < size; x += 1) {
                    let value = shade[y * size + x] + tone + side;
                    if (!side) {
                        let along = x - endLap;
                        if (along < -size / 2) along += size;
                        if (along >= size / 2) along -= size;
                        value += 0.8 * lap(along);
                    }
                    const at = (y * size + x) * 4;
                    data[at] = Math.max(0, Math.min(255, Math.round(ROOF_MEMBRANE.base[0] + value)));
                    data[at + 1] = Math.max(0, Math.min(255, Math.round(ROOF_MEMBRANE.base[1] + value)));
                    data[at + 2] = Math.max(0, Math.min(255, Math.round(ROOF_MEMBRANE.base[2] + value * 1.06)));
                    data[at + 3] = 255;
                }
            }
            const texture = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
            texture.name = 'FacilityRoofMembrane';
            texture.wrapS = THREE.RepeatWrapping;
            texture.wrapT = THREE.RepeatWrapping;
            texture.magFilter = THREE.LinearFilter;
            texture.minFilter = THREE.LinearMipmapLinearFilter;
            texture.generateMipmaps = true;
            if (THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
            if (state.renderer && state.renderer.capabilities
                    && typeof state.renderer.capabilities.getMaxAnisotropy === 'function') {
                texture.anisotropy = Math.min(8, state.renderer.capabilities.getMaxAnisotropy());
            }
            texture.needsUpdate = true;
            return texture;
        }

        // Non-indexed triangles with flat normals, in groups by material: 0 the membrane (the outline at the slab's
        // top, facing up), 1 the parapet (per edge: its outer face from a little below the slab to its top, the inner
        // side of that face from as low up to the slab's top, and its inner face above the membrane), 2 the coping
        // (the parapet's top), 3 the underside (the outline at the slab's base, facing down, shaded as facing up like
        // a ceiling: lit like the room under it). UVs are plan metres over ROOF_MEMBRANE.meters, along the outline's
        // longest edge, so the membrane's sheets run the length of the roof. The inner line is the outline moved in
        // by the parapet's width (mitred). Neighbours are the other roofs ({points, base}): see zoneRoofEdgeSpans.
        // `wall` (by default `base`) is the wall tops, where a free face comes down to. Null if the outline does not
        // triangulate.
        function zoneRoofGeometry(points, base, neighbours, wall) {
            if (points.length < 3) return null;
            let twiceArea = 0;
            points.forEach(function (point, i) {
                const next = points[(i + 1) % points.length];
                twiceArea += point.x * next.z - next.x * point.z;
            });
            if (!(Math.abs(twiceArea) > 1e-9)) return null;
            const triangles = THREE.ShapeUtils.triangulateShape(points.map(function (point) {
                return new THREE.Vector2(point.x, point.z);
            }), []);
            if (!triangles.length) return null;
            const sign = twiceArea > 0 ? 1 : -1;
            const outward = points.map(function (point, i) {
                const next = points[(i + 1) % points.length];
                const length = Math.hypot(next.x - point.x, next.z - point.z) || 1;
                return { x: sign * (next.z - point.z) / length, z: -sign * (next.x - point.x) / length };
            });
            const width = ZONE_ROOF.parapetWidth;
            const inner = points.map(function (point, i) {
                const before = outward[(i + points.length - 1) % points.length];
                const after = outward[i];
                const det = before.x * after.z - before.z * after.x;
                let dx = -width * before.x;
                let dz = -width * before.z;
                if (Math.abs(det) > 1e-6) {
                    dx = width * (before.z - after.z) / det;
                    dz = width * (after.x - before.x) / det;
                    const reach = Math.hypot(dx, dz);
                    if (reach > 4 * width) { dx *= 4 * width / reach; dz *= 4 * width / reach; }
                }
                return { x: point.x + dx, z: point.z + dz };
            });
            let along = { x: 1, z: 0 };
            let longest = 0;
            points.forEach(function (point, i) {
                const next = points[(i + 1) % points.length];
                const length = Math.hypot(next.x - point.x, next.z - point.z);
                if (length > longest + 1e-9) {
                    longest = length;
                    along = { x: (next.x - point.x) / length, z: (next.z - point.z) / length };
                }
            });
            const top = base + ZONE_ROOF.thickness;
            const crest = top + ZONE_ROOF.parapetHeight;
            const parts = [0, 1, 2, 3].map(function () { return { positions: [], normals: [], uvs: [] }; });
            // One triangle into group `part`, turned so its face is toward `facing` (front faces are counter-clockwise
            // from that side), shaded with normal `shade` (by default `facing`).
            const triangle = function (part, a, b, c, facing, shade) {
                const ux = b[0] - a[0]; const uy = b[1] - a[1]; const uz = b[2] - a[2];
                const vx = c[0] - a[0]; const vy = c[1] - a[1]; const vz = c[2] - a[2];
                const toward = (uy * vz - uz * vy) * facing[0] + (uz * vx - ux * vz) * facing[1]
                    + (ux * vy - uy * vx) * facing[2];
                const normal = shade || facing;
                [a].concat(toward < 0 ? [c, b] : [b, c]).forEach(function (corner) {
                    parts[part].positions.push(corner[0], corner[1], corner[2]);
                    parts[part].normals.push(normal[0], normal[1], normal[2]);
                    parts[part].uvs.push((corner[0] * along.x + corner[2] * along.z) / ROOF_MEMBRANE.meters,
                        (corner[2] * along.x - corner[0] * along.z) / ROOF_MEMBRANE.meters);
                });
            };
            const quad = function (part, a, b, c, d, facing) {
                triangle(part, a, b, c, facing);
                triangle(part, a, c, d, facing);
            };
            triangles.forEach(function (corners) {
                const [a, b, c] = corners.map(function (k) { return [points[k].x, top, points[k].z]; });
                triangle(0, a, b, c, [0, 1, 0]);
                const [d, e, f] = corners.map(function (k) { return [points[k].x, base, points[k].z]; });
                triangle(3, d, e, f, [0, -1, 0], [0, 1, 0]);
            });
            points.forEach(function (point, i) {
                const j = (i + 1) % points.length;
                const next = points[j];
                const out = [outward[i].x, 0, outward[i].z];
                const into = [-out[0], 0, -out[2]];
                zoneRoofEdgeSpans(point, next, outward[i], neighbours || [], base,
                    wall === undefined ? base : Math.min(wall, base)).forEach(function (span) {
                    const a = span.from;
                    const b = span.to;
                    quad(1, [a.x, span.low, a.z], [b.x, span.low, b.z], [b.x, crest, b.z], [a.x, crest, a.z], out);
                    quad(1, [a.x, span.under, a.z], [b.x, span.under, b.z], [b.x, top, b.z], [a.x, top, a.z], into);
                });
                quad(2, [point.x, crest, point.z], [next.x, crest, next.z], [inner[j].x, crest, inner[j].z],
                    [inner[i].x, crest, inner[i].z], [0, 1, 0]);
                quad(1, [inner[i].x, top, inner[i].z], [inner[j].x, top, inner[j].z], [inner[j].x, crest, inner[j].z],
                    [inner[i].x, crest, inner[i].z], into);
            });
            const geometry = new THREE.BufferGeometry();
            const all = { positions: [], normals: [], uvs: [] };
            let start = 0;
            parts.forEach(function (part, index) {
                const count = part.positions.length / 3;
                geometry.addGroup(start, count, index);
                start += count;
                Array.prototype.push.apply(all.positions, part.positions);
                Array.prototype.push.apply(all.normals, part.normals);
                Array.prototype.push.apply(all.uvs, part.uvs);
            });
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(all.positions, 3));
            geometry.setAttribute('normal', new THREE.Float32BufferAttribute(all.normals, 3));
            geometry.setAttribute('uv', new THREE.Float32BufferAttribute(all.uvs, 2));
            if (typeof geometry.computeBoundingSphere === 'function') geometry.computeBoundingSphere();
            if (typeof geometry.computeBoundingBox === 'function') geometry.computeBoundingBox();
            return geometry;
        }

        // The parts of a roof edge (p to q, outward normal n) that get a parapet outer face, each {from, to, low,
        // under}: the edge is cut where a neighbouring roof's corners lie on it or its edges cross it; a part whose
        // outside is another roof as high or higher gets none, a part over a lower roof comes down only to that
        // roof's membrane (however little lower it is), and a free part comes down ZONE_ROOF.drop below the wall tops
        // (`wall`, the slab's underside unless the roof sits on an open deck). `under` is how low its inner side
        // comes: the lower roof's underside (closing its slab's edge from inside) or the free face's foot.
        function zoneRoofEdgeSpans(p, q, n, neighbours, base, wall) {
            const length = Math.hypot(q.x - p.x, q.z - p.z);
            if (!(length > 1e-6)) return [];
            const ux = (q.x - p.x) / length;
            const uz = (q.z - p.z) / length;
            const cuts = [0, length];
            neighbours.forEach(function (other) {
                other.points.forEach(function (v, index) {
                    const t = (v.x - p.x) * ux + (v.z - p.z) * uz;
                    if (Math.abs(ux * (v.z - p.z) - uz * (v.x - p.x)) <= 0.05 && t > 1e-3 && t < length - 1e-3) {
                        cuts.push(t);
                    }
                    // Where the neighbour's edge from v crosses this one.
                    const w = other.points[(index + 1) % other.points.length];
                    const ex = w.x - v.x;
                    const ez = w.z - v.z;
                    const denominator = ux * ez - uz * ex;
                    if (Math.abs(denominator) < 1e-12) return;
                    const along = ((v.x - p.x) * ez - (v.z - p.z) * ex) / denominator;
                    const across = ((v.x - p.x) * uz - (v.z - p.z) * ux) / denominator;
                    if (across > 0 && across < 1 && along > 1e-3 && along < length - 1e-3) cuts.push(along);
                });
            });
            cuts.sort(function (a, b) { return a - b; });
            const spans = [];
            for (let k = 0; k + 1 < cuts.length; k += 1) {
                const from = cuts[k];
                const to = cuts[k + 1];
                if (!(to - from > 1e-3)) continue;
                const middle = (from + to) / 2;
                const x = p.x + ux * middle + n.x * 0.05;
                const z = p.z + uz * middle + n.z * 0.05;
                let beyond = null;
                neighbours.forEach(function (other) {
                    if (pointInOutline(other.points, x, z) && (!beyond || other.base > beyond.base)) beyond = other;
                });
                if (beyond && beyond.base >= base - 1e-6) continue;
                const low = beyond ? beyond.base + ZONE_ROOF.thickness : wall - ZONE_ROOF.drop;
                const under = beyond ? beyond.base : wall - ZONE_ROOF.drop;
                const last = spans[spans.length - 1];
                if (last && last.low === low && last.under === under && Math.abs(last.end - from) < 1e-9) {
                    last.end = to;
                    last.to = { x: p.x + ux * to, z: p.z + uz * to };
                    continue;
                }
                spans.push({ low: low, under: under, end: to, from: { x: p.x + ux * from, z: p.z + uz * from },
                    to: { x: p.x + ux * to, z: p.z + uz * to } });
            }
            return spans;
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
            removeListener(documentObject, 'visibilitychange', state.lightPatternsVisibilityHandler, false);
            state.lightPatternsVisibilityHandler = null;
            removeListener(
                state.canvas,
                'pointerup',
                state.pointerHandler,
                false
            );
            removeListener(state.canvas, 'pointerdown', state.pointerDownHandler, false);
            removeListener(state.canvas, 'pointercancel', state.pointerCancelHandler, false);
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
            removeListener(documentObject, 'mousemove', state.walkthroughAimHandler, true);
            removeListener(state.canvas, 'wheel', state.walkthroughWheelHandler, { passive: false });
            state.walkthroughAimHandler = null;
            state.walkthroughWheelHandler = null;
            state.walkthroughChangeHandler = null;
            state.walkthroughLockHandler = null;
            state.walkthroughUnlockHandler = null;
            state.walkthroughErrorHandler = null;
            state.walkthroughKeyDownHandler = null;
            state.walkthroughKeyUpHandler = null;
            state.walkthroughBlurHandler = null;
            state.walkthroughVisibilityHandler = null;
            state.pointerHandler = null;
            state.pointerDownHandler = null;
            state.pointerCancelHandler = null;
            state.pointerPress = null;
            state.resizeHandler = null;

            clearModel();
            disposeRetiredMaterials();
            clearEnvironmentObjects();
            disposeSceneBackground();
            // Library resources are bound to this renderer; a pooled renderer
            // must not inherit them.
            if (state.scene) {
                state.scene.environment = null;
                if (state.scene.background === state.sceneEquirect) state.scene.background = null;
            }
            if (state.environmentLoader) state.environmentLoader.dispose();
            state.environmentLoader = null;
            state.sceneEnvironment = null;
            state.sceneEquirect = null;
            state.viewportSceneSignature = null;
            state.viewportSceneRequest += 1;
            state.sceneBackgroundKey = JSON.stringify(['theme', null]);
            state.shadowsActive = false;
            state.sunDefaultPosition = null;
            if (state.renderer && state.renderer.shadowMap) state.renderer.shadowMap.enabled = false;
            if (state.finishTextures) state.finishTextures.dispose();
            state.finishTextures = null;
            disposeLightPools();
            disposeBloom();
            state.bloom.failed = null;
            state.bloom.stencil = null;
            stopLightPatterns();
            state.decalTextures.forEach(function (texture) { texture.dispose(); });
            state.decalTextures.clear();
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
            disposeSiteGround();
            disposeSiteAreas();
            disposeSiteRoutes();
            state.environmentRoot = null;
            state.siteRoot = null;
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
            if (finalDispose) forgetScene();
            notifyStatus(finalDispose ? 'disposed' : 'unmounted', null);
        }

        // A final dispose forgets every scene input, the parked view with it, and drops every setScene still waiting
        // (for the appearance library): it would otherwise install its layout into a disposed view, and a later mount
        // would replay it. Whatever is mounted next starts empty until it is given a scene.
        function forgetScene() {
            state.sceneRequest += 1;
            state.parkedView = null;
            state.currentInput = null;
            state.requestedInput = null;
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

        function mount(host) {
            if (!host || typeof host.appendChild !== 'function') {
                throw new TypeError('A DOM-like facility renderer host is required.');
            }
            if (state.mounted && state.host === host) {
                if (state.suspended) resume();
                return api;
            }
            const latest = latestInput();
            const replayInput = latest ? {
                layout: latest.layout,
                assetCatalog: latest.assetCatalog,
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
                            // The glow halo (L6) spreads only from pixels a glow marked in the stencil.
                            stencil: true,
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
                    const replaying = setScene(replayInput);
                    const token = sceneToken({ installs: true });
                    replaying.then(function () {
                        if (replayGhost && tokenCurrent(token)) setGhostPlacement(replayGhost);
                    }).catch(function (error) {
                        if (tokenCurrent(token)) reportError('scene_remount_failed', error);
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
            disposeRetiredMaterials();
            state.mountGeneration += 1;
            if (state.frameId !== null && cancelFrame) cancelFrame(state.frameId);
            state.frameId = null;
            state.needsRender = false;
            stopLightPatterns();
            if (state.resizeObserver) state.resizeObserver.disconnect();
            state.resizeObserverActive = false;
            notifyStatus('suspended', null);
            return true;
        }

        function park() {
            if (!state.mounted || state.disposed || state.parkedView) return false;
            suspend();
            const saved = { host: state.host, camera: getCameraView() };
            // Release the sole renderer lease, retaining inputs for this sheet.
            // Playback is transient and must not appear loaded after teardown.
            disposeMotion('layout_sheet_parked');
            disposeActivity('layout_sheet_parked');
            disposeNavigationPreview('layout_sheet_parked');
            teardownMount(false);
            state.parkedView = saved;
            return true;
        }

        function resume() {
            if (state.parkedView && !state.disposed) {
                const saved = state.parkedView;
                state.parkedView = null;
                mount(saved.host);
                if (saved.camera && state.camera) applyCameraView(saved.camera);
                return true;
            }
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
            if (state.reloadOnResume && latestInput()) {
                state.reloadOnResume = false;
                const reloading = Promise.resolve(setScene(latestInput()));
                const token = sceneToken({ installs: true });
                reloading.catch(function (error) {
                    if (!tokenCurrent(token)) return;
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

        function batchStaticPrototypeMeshes(meshes) {
            if (typeof options.mergeGeometries !== 'function') return meshes;
            const buckets = new Map(), output = [];
            meshes.forEach(function (mesh) {
                const g = mesh.geometry, m = mesh.material;
                const attributes = g && g.attributes;
                if (!mesh.instancingEligible || mesh.source.isInstancedMesh
                        || !m || Array.isArray(m) || !m.userData?.facilityNeutralAssetMaterial
                        || !g?.isBufferGeometry || !attributes?.position
                        || Object.keys(g.morphAttributes || {}).length
                        || g.drawRange.start !== 0
                        || (Number.isFinite(g.drawRange.count)
                            && g.drawRange.count < (g.index?.count || attributes.position.count))
                        || !mesh.matrix?.determinant || mesh.matrix.determinant() <= 0
                        || Object.values(attributes).some(a => a.isInterleavedBufferAttribute)) {
                    output.push(mesh);return;
                }
                // Neutral, static meshes only: no texture, animation, source-color or winding changes.
                const key = JSON.stringify([m.type, m.side, m.flatShading, m.wireframe,
                    m.color.getHex(), m.roughness, m.metalness, m.opacity, m.transparent,
                    m.depthTest, m.depthWrite, !!g.index,
                    Object.keys(attributes).sort().map(name => {
                        const a=attributes[name];return [name,a.itemSize,a.normalized,a.array.constructor.name];
                    })]);
                if (!buckets.has(key)) buckets.set(key, []);
                buckets.get(key).push(mesh);
            });
            buckets.forEach(function (bucket) {
                if (bucket.length < 2) { output.push(...bucket);return; }
                const copies = [];
                let mergedGeometry = null;
                try {
                    bucket.forEach(mesh => copies.push(mesh.geometry.clone().applyMatrix4(mesh.matrix)));
                    const geometry = mergedGeometry = options.mergeGeometries(copies, false);
                    if (!geometry) { output.push(...bucket);return; }
                    geometry.computeBoundingBox();geometry.computeBoundingSphere();
                    output.push(Object.assign({}, bucket[0], { geometry, matrix: new THREE.Matrix4() }));
                } catch (error) {
                    if (mergedGeometry) mergedGeometry.dispose();
                    reportError('static_mesh_batch_failed', error);
                    output.push(...bucket);
                } finally {
                    copies.forEach(geometry => geometry.dispose());
                }
            });
            return output;
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
                // A copy may come from a prototype that is off screen when the lights switch changes
                // (activity actors, finish previews), so it takes the switch's current state.
                syncLights(clone);
                return clone;
            }
            return prototype;
        }

        // A copy of a model on screen for another group, or for the same group drawn again (2026-11-03, Codex on
        // 4a05de6). It owns its geometry and textures as a loaded model does: the group it came from may be disposed
        // first, and each group disposes what it holds. Scene environments and decal images stay shared; their
        // owners dispose them. A texture copy shares the image, so the pixels upload once.
        function copyRenderable(prototype) {
            const copy = cloneRenderable(prototype);
            if (!copy || typeof copy.traverse !== 'function') return copy;
            const geometries = new Map();
            const textures = new Map();
            const ownTexture = function (texture) {
                const shared = texture.userData && (texture.userData.facilityEnvironment
                    || texture.userData.facilitySharedTexture);
                if (shared || typeof texture.clone !== 'function') return texture;
                if (!textures.has(texture)) textures.set(texture, texture.clone());
                return textures.get(texture);
            };
            const ownMaterial = function (material) {
                if (!material) return material;
                Object.keys(material).forEach(function (key) {
                    if (material[key] && material[key].isTexture) material[key] = ownTexture(material[key]);
                });
                return material;
            };
            copy.traverse(function (object) {
                if (object.geometry && typeof object.geometry.clone === 'function') {
                    if (!geometries.has(object.geometry)) geometries.set(object.geometry, object.geometry.clone());
                    object.geometry = geometries.get(object.geometry);
                }
                if (!object.material) return;
                // cloneRenderable copies mesh materials only; lines and points get theirs here.
                const copied = function (material) {
                    return !object.isMesh && material && typeof material.clone === 'function' ? material.clone() : material;
                };
                object.material = Array.isArray(object.material)
                    ? object.material.map(function (material) { return ownMaterial(copied(material)); })
                    : ownMaterial(copied(object.material));
            });
            return copy;
        }

        function createContainer() {
            const Type = THREE.Group || THREE.Object3D;
            return new Type();
        }

        function baseGroupKey(group) {
            return group.assetId + '|' + group.assetDefinitionRevision + (group.materialKey || '');
        }

        function removeExistingGroup(group) {
            const existing = state.renderGroups.get(baseGroupKey(group));
            if (!existing) return;
            disposeRenderGroup(existing);
            state.renderGroups.delete(baseGroupKey(group));
        }

        function buildRenderedGroup(group, prototype, representation) {
            const outer = state.finishProjectionSink;
            const keys = new Set();
            state.finishProjectionSink = keys;
            let record;
            try {
                record = drawRenderedGroup(group, prototype, representation);
            } finally {
                state.finishProjectionSink = outer;
            }
            record.finishProjections = Array.from(keys);
            record.finishProjections.forEach(function (key) {
                state.finishProjectionUsers.set(key, (state.finishProjectionUsers.get(key) || 0) + 1);
            });
            return record;
        }

        function drawRenderedGroup(group, prototype, representation) {
            removeExistingGroup(group);
            applyVisualSettingsToObject(prototype.object);
            const container = createContainer();
            container.name = 'FacilityAssetGroup:' + baseGroupKey(group);
            container.userData = container.userData || {};
            container.userData.assetId = group.assetId;
            container.userData.assetDefinitionRevision =
                group.assetDefinitionRevision;
            container.userData.representation = representation;

            const repeated = group.placements.length > 1;
            const finish = group.finish && finishesRuntime ? group.finish : null;
            // The group shares its part finishes (its own, and the model's defaults for its parts), so they
            // go onto one copy of the prototype and every instance carries them. With a library finish as
            // well, parts must win over it, which the per-placement copies below already do.
            const withParts = Boolean(group.componentKey) || Boolean(componentRuntime
                && typeof componentRuntime.defaults === 'function' && componentRuntime.defaults(prototype.object).length);
            const sharedParts = repeated && !finish && componentRuntime && withParts;
            let prototypeObject = prototype.object;
            if (sharedParts) {
                prototypeObject = cloneRenderable(prototype.object);
                componentRuntime.apply(prototypeObject, group.placements[0].source && group.placements[0].source.componentMaterials,
                    representation, partFinishContext(group.placements[0]));
            }
            let prototypeMeshes = collectPrototypeMeshes(prototypeObject);
            const sourcePrototypeMeshCount = prototypeMeshes.length;
            let containsLights = false;
            if (typeof prototype.object.traverse === 'function') {
                prototype.object.traverse(object => { if (object.isLight) containsLights = true; });
            }
            const eligible = prototype.instancingEligible !== false
                && !containsLights
                && prototypeMeshes.length > 0
                && prototypeMeshes.every(function (item) {
                    return item.instancingEligible;
                })
                && typeof THREE.InstancedMesh === 'function';
            // Part finishes instance when the whole group shares them; a library finish
            // alone still instances, since the whole group shares it.
            const useInstancing = repeated && eligible && (!withParts || Boolean(sharedParts));
            const finishMapping = finish ? finishesRuntime.mappingFor(THREE, prototype.object, finish) : null;
            if (useInstancing && !finish) prototypeMeshes = batchStaticPrototypeMeshes(prototypeMeshes);
            const groupFinishMaterial = finish && useInstancing
                ? createFinishMaterialFor(finish, group.finishScale) : null;
            const pickObjects = [];
            const mappings = [];

            if (useInstancing) {
                prototypeMeshes.forEach(function (mesh, meshIndex) {
                    let material;
                    let geometry = mesh.geometry;
                    if (groupFinishMaterial && !isFinishProtectedMaterial(mesh.material)) {
                        material = groupFinishMaterial;
                        geometry = finishesRuntime.cachedFinishGeometry(THREE, state.finishGeometryCache,
                            mesh.geometry, mesh.matrix, finishMapping);
                    } else {
                        // White material lets instance colors specify an exact finish, not a gray tint.
                        material = mesh.material.clone();
                        material.userData = material.userData || {};
                        material.userData.facilityInstanceBaseColor = material.color.getHex();
                        material.color.setHex(0xffffff);
                    }
                    const instances = new THREE.InstancedMesh(
                        geometry,
                        material,
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
                    // Each copy gets its own finish material so a selection glow
                    // stays on the selected placement.
                    if (finish) applyObjectFinish(object, createFinishMaterialFor(finish, placement.transform.scale), finishMapping);
                    if (typeof object.updateMatrixWorld === 'function') object.updateMatrixWorld(true);
                    if(componentRuntime)componentRuntime.apply(object, placement.source && placement.source.componentMaterials,
                        representation, partFinishContext(placement));
                    applyPlacementTransform(object, placement);
                    container.add(object);
                    pickObjects.push(object);
                    mappings.push({
                        placementId: placement.placementId,
                    });
                });
            }
            if (prototypeObject !== prototype.object && typeof prototypeObject.traverse === 'function') {
                // The finished copy only lent its materials (each instanced mesh cloned its own);
                // its geometry is the prototype's, which stays.
                prototypeObject.traverse(function (object) {
                    if (!object.isMesh) return;
                    [].concat(object.material || []).forEach(function (material) {
                        if (material && typeof material.dispose === 'function') material.dispose();
                    });
                });
            }

            const visibilityLayer = assetVisibilityLayer(group.catalog);
            let renderedLightCount = 0;
            if (typeof container.traverse === 'function') {
                container.traverse(object => { if (object.isLight) renderedLightCount++; });
            }
            container.visible = state.layerVisibility[visibilityLayer] !== false;
            state.modelRoot.add(container);
            const record = {
                baseKey: baseGroupKey(group),
                representationKey: baseGroupKey(group) + '|' + representation,
                assetId: group.assetId,
                visibilityLayer: visibilityLayer,
                assetDefinitionRevision: group.assetDefinitionRevision,
                representation: representation,
                placementIds: group.placements.map(function (placement) {
                    return placement.placementId;
                }),
                instanced: useInstancing,
                meshCount: useInstancing
                    ? prototypeMeshes.length : pickObjects.length,
                prototypeMeshCount: prototypeMeshes.length,
                sourcePrototypeMeshCount: sourcePrototypeMeshCount,
                renderedLightCount: renderedLightCount,
                prototypeMatrices: prototypeMeshes.map(function (mesh) {
                    return mesh.matrix;
                }),
                mappings: mappings,
                container: container,
                prototypeObject: prototype.object,
                prototypeInstancingEligible: prototype.instancingEligible !== false,
                pickObjects: pickObjects,
            };
            state.renderGroups.set(record.baseKey, record);
            state.pickObjects = state.pickObjects.concat(pickObjects);
            if (state.shadowsActive) setShadowCasting(container, true);
            syncLights(container);
            if (lightPoolsWanted()) syncLightPools();
            renderEquipmentDecals(record.placementIds);
            if (state.drone.active) applyCurrentDroneRecordWindow(record);
            else applySelection(false, record);
            if (group.renderSignature !== undefined && !group.drawnDiffers
                    && groupSnapshot(group, currentLayout()).renderSignature !== group.renderSignature) {
                group.drawnDiffers = true;
            }
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

        // Model files enter a layout mirrored across their canonical x = 0 plane
        // (ai_inspector/facility_layout/model_axes.py), so that on the mirrored
        // canvas they look true (see mirrorModelFileGeometry).
        function mirrorModelFile(wrapper) {
            if (!state.displayMirror || !wrapper || typeof wrapper.traverse !== 'function'
                    || typeof THREE.Matrix4 !== 'function') return wrapper;
            if (wrapper.userData && wrapper.userData.modelAxesMirrored) return wrapper;
            const probe = new THREE.Matrix4();
            if (['copy', 'invert', 'multiply', 'multiplyMatrices', 'makeScale']
                .some(function (name) { return typeof probe[name] !== 'function'; })) return wrapper;
            try {
                mirrorModelFileGeometry(THREE, wrapper);
            } catch (error) {
                reportError('model_axes_mirror_failed', error);
            }
            wrapper.userData = Object.assign({}, wrapper.userData, { modelAxesMirrored: true });
            return wrapper;
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
            // Stable part keys come from the glTF node names; the loader's
            // associations are gone once the scene is cloned, so tag them now.
            if (componentRuntime && typeof componentRuntime.annotatePartKeys === 'function') {
                try { componentRuntime.annotatePartKeys(resolved); } catch (error) { reportError('part_keys_failed', error); }
            }
            const object = objectFromResult(resolved);
            if (!object) {
                if (stage === 'footprint') {
                    return makeFallbackPrototype(
                        extractBounds(resolved) || group.bounds
                    );
                }
                return null;
            }
            const canonicalObject = mirrorModelFile(canonicalPrototypeObject(
                object,
                canonicalMatrix
            ));
            // Parts that come with a library finish (a light's lens that comes lit) need the library.
            if (componentRuntime && typeof componentRuntime.recordDefaults === 'function'
                    && componentRuntime.recordDefaults(canonicalObject).length && facilityLibrary
                    && typeof facilityLibrary.get === 'function' && !facilityLibrary.get()
                    && typeof facilityLibrary.load === 'function') {
                try {
                    await facilityLibrary.load();
                } catch (error) {
                    warning('appearance_library_unavailable',
                        'The appearance library could not be loaded; neutral finishes are shown.', null);
                }
            }
            applyAssetMaterialPolicy(canonicalObject);
            recordAuthoredGlows(canonicalObject);
            syncLights(canonicalObject);
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
            // A group the scene no longer has (its view was torn down, or a newer layout replaced it) is never
            // drawn into the current scene (final rounds 2 and 3).
            const token = sceneToken({ group: group });
            if (!tokenCurrent(token)) return Promise.resolve(false);
            if (group.deferredPromise) return group.deferredPromise;
            if (!group.deferredVisual) return Promise.resolve(false);
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
                    if (!tokenCurrent(token) || !state.mounted) {
                        disposeUnadoptedVisual(prototype);
                        return false;
                    }
                    if (!prototype) {
                        traceLoad(group, 'overview', 'skipped', reason);
                        group.deferredFailed = true;
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
                    group.deferredFailed = true;
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

        // One deferred load at a time. A load queued for one scene never starts in another, or for a group the scene no
        // longer has: a stalled load and a layout change would otherwise draw the old models over the new ones. A
        // model that failed stays a footprint: no camera move or shot queues it again (SV1 round 3).
        function queueDeferredGroup(group, reason) {
            if (!group || !group.deferredVisual || group.deferredLoading
                    || group.deferredQueued || group.deferredFailed) return false;
            const token = sceneToken({ group: group });
            group.deferredQueued = true;
            state.deferredLoadQueue = state.deferredLoadQueue.then(
                function () {
                    group.deferredQueued = false;
                    if (!tokenCurrent(token)) return false;
                    return loadDeferredGroup(group, reason);
                }
            ).catch(function (error) {
                group.deferredQueued = false;
                reportError('deferred_asset_queue_failed', error);
                return false;
            });
            return true;
        }

        // Sage's 3D shots (docs/sage-basic-shapes-plan.md, SV1): a camera move loads one deferred model at a time, but
        // a shot waits for every model drawn big enough on screen, so none is copied as its footprint. Queues each one
        // not loading yet and returns how many are still to draw; one that failed stays a footprint, not retried here.
        function loadVisibleDetail() {
            if (!state.mounted || state.suspended || state.degraded) return 0;
            let left = 0;
            state.baseGroups.forEach(function (group) {
                if (!group.deferredVisual || group.deferredFailed) return;
                if (projectedGroupPixelSize(group) < deferredVisualPixelThreshold) return;
                if (group.deferredLoading || group.deferredQueued
                        || queueDeferredGroup(group, 'deferred_visible_for_shot')) left += 1;
            });
            return left;
        }

        function loadDeferredVisibleGroups() {
            if (!state.mounted || state.suspended || state.degraded) return 0;
            const candidates = Array.from(state.baseGroups.values())
                .filter(function (group) {
                    return group.deferredVisual
                        && !group.deferredLoading
                        && !group.deferredQueued
                        && !group.deferredFailed;
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
            const desiredRepresentation = group.desiredRepresentation !== undefined ? group.desiredRepresentation
                : group.placements[0]?.source?.componentMaterials?.representation;
            const retainOverview = desiredRepresentation !== 'detail' && preferOverviewForLargeLayouts
                && state.placements.length >= largeLayoutDetailThreshold;
            for (let index = 0; index < RESOLUTION_STAGES.length; index += 1) {
                const stage = RESOLUTION_STAGES[index];
                if (generation !== state.sceneGeneration || !state.mounted) {
                    return false;
                }
                if (stage === 'detail' && (desiredRepresentation === 'overview' || retainOverview && overviewResolved)) {
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
                        if (group.assetId === 'asset-operator'
                                && group.assetDefinitionRevision === ANIMATED_OPERATOR_REVISION
                                && avatarRuntime && avatarRuntime.createStandingAvatar) {
                            const object = avatarRuntime.createStandingAvatar(THREE);
                            buildRenderedGroup(group, { object: object, bounds: group.bounds }, 'operator-avatar');
                            traceLoad(group, 'operator-avatar', 'resolved', 'illustrative_operator_visual');
                            return true;
                        }
                    } else {
                        if (stage === 'overview' && !desiredRepresentation
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
                const catalogKey = placement.assetId + '|' + placement.assetDefinitionRevision;
                // Placements of one asset group by their exact part finishes (and scale, which textured
                // finishes depend on) and by their exact library finish, so identical finishes stay
                // instanced: a yard of identically painted racks is one group, not hundreds.
                const parts = placement.source && placement.source.componentMaterials;
                const componentKey = parts ? '|components:' + shortHash(JSON.stringify([parts, placement.transform.scale])) : '';
                const finish = placementFinish(placement);
                const finishKey = finish ? '|finish:' + shortHash(libraryRuntime.finishSignature(finish, placement.transform.scale)) : '';
                const materialKey = componentKey + finishKey;
                const key = catalogKey + materialKey;
                if (!groups.has(key)) {
                    const catalogEntry = catalogIndex.exact.get(catalogKey)
                        || catalogIndex.byAsset.get(placement.assetId)
                        || {};
                    if (!catalogIndex.exact.has(catalogKey) && catalogRevision(catalogEntry)
                        && catalogRevision(catalogEntry)
                            !== placement.assetDefinitionRevision) {
                        warning(
                            'asset_revision_mismatch',
                            'Catalog definition does not match the placement revision.',
                            key
                        );
                    }
                    groups.set(key, {
                        materialKey: materialKey,
                        componentKey: componentKey,
                        finish: finish,
                        finishScale: placement.transform.scale,
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
                        deferredFailed: false,
                        resolved: false,
                        resolvePromise: null,
                    });
                }
                groups.get(key).placements.push(placement);
            });
            groups.forEach(function (group) { Object.assign(group, groupSnapshot(group, layout)); });
            return { placements: placements, groups: groups };
        }

        // What a group draws, as text taken when it is grouped (2026-11-03, Codex on 4a05de6 and a5c91fa). The
        // placements' objects and the layout's custom finishes can change in place before the next setScene, so
        // keeping a group or copying its model reads only this and the group's key (asset, revision, part finishes
        // as saved, placement finish as resolved):
        // - desiredRepresentation: the representation its placements ask for (resolveGroup loads by it);
        // - membershipSignature: placements, scales and part finishes as saved (regroupFinishes keeps by it);
        // - partSignature: the part finishes as resolved, custom finishes included;
        // - renderSignature: all of it with the resolved finish and the placements as saved.
        function groupSnapshot(group, layout) {
            const first = group.placements[0];
            const parts = first && first.source && first.source.componentMaterials;
            const desired = parts ? parts.representation : undefined;
            const partSignature = JSON.stringify(group.placements.map(function (placement) {
                return resolvedPartFinishes(placement, layout);
            }));
            return {
                desiredRepresentation: desired === undefined ? null : desired,
                membershipSignature: groupMembershipSignature(group),
                partSignature: partSignature,
                renderSignature: JSON.stringify([group.finish || null, partSignature,
                    group.placements.map(function (placement) { return [placement.placementId, placement.source]; })]),
            };
        }

        function resolvedPartFinishes(placement, layout) {
            const parts = placement && placement.source && placement.source.componentMaterials;
            const overrides = parts && Array.isArray(parts.overrides) ? parts.overrides : [];
            const library = currentLibrary();
            return overrides.filter(function (item) { return item && item.appearanceId; }).map(function (item) {
                return [item.key, library && libraryRuntime
                    ? libraryRuntime.resolveAppearance(library, item, layout) : item.appearanceId];
            });
        }

        function adoptSnapshot(kept, group) {
            ['desiredRepresentation', 'membershipSignature', 'partSignature', 'renderSignature'].forEach(function (key) {
                kept[key] = group[key];
            });
        }

        // Whether every group is drawn as its snapshot says. A placement or custom finish changed in place after
        // grouping, before the group's model arrived, is drawn as it then was (buildRenderedGroup marks the group);
        // no later edit may then keep or copy groups, and the scene is rebuilt in full.
        function drawnAsGrouped() {
            let same = true;
            state.baseGroups.forEach(function (group) { if (group.drawnDiffers) same = false; });
            return same;
        }

        // The model on screen a changed group can be drawn from, or null (2026-11-03, Codex on a5c91fa: the old
        // group's wanted representation was read from its placements' live objects). Its own group's, when that
        // asked for the same representation; else one loaded for a group of the same asset asking for the same;
        // else, when the group asks for a representation, any of the same asset loaded in it. Reads only the old
        // groups' snapshots and what each record was built with.
        function modelSources(previousGroups, previousRecords) {
            const onScreen = function (record) {
                return Boolean(record && record.prototypeObject
                    && (record.representation === 'overview' || record.representation === 'detail'));
            };
            const byWanted = new Map();
            const byRepresentation = new Map();
            previousRecords.forEach(function (record, key) {
                const group = previousGroups.get(key);
                if (!group || !onScreen(record)) return;
                const asset = record.assetId + '|' + record.assetDefinitionRevision + '|';
                if (!byWanted.has(asset + group.desiredRepresentation)) {
                    byWanted.set(asset + group.desiredRepresentation, record);
                }
                if (!byRepresentation.has(asset + record.representation)) {
                    byRepresentation.set(asset + record.representation, record);
                }
            });
            return function (key, group) {
                const own = previousRecords.get(key);
                const oldGroup = previousGroups.get(key);
                if (onScreen(own) && oldGroup && oldGroup.desiredRepresentation === group.desiredRepresentation) return own;
                const asset = group.assetId + '|' + group.assetDefinitionRevision + '|';
                const named = group.desiredRepresentation === 'detail' || group.desiredRepresentation === 'overview';
                return byWanted.get(asset + group.desiredRepresentation)
                    || (named ? byRepresentation.get(asset + group.desiredRepresentation) : null) || null;
            };
        }

        // The layout with every finish removed: object and part finishes,
        // custom finishes, the scene and equipment decals. When only those
        // change, the geometry on screen is still right.
        function finishOnlyKey(layout) {
            const extensions = Object.assign({}, layout.extensions || {});
            delete extensions.facilityScene;
            delete extensions.facilityEquipmentDecals;
            delete extensions.facilityAppearances;
            return JSON.stringify(Object.assign({}, layout, {
                extensions: extensions,
                placements: (layout.placements || []).map(function (placement) {
                    const copy = Object.assign({}, placement);
                    delete copy.appearance;
                    delete copy.componentMaterials;
                    return copy;
                }),
            }));
        }

        function groupMembershipSignature(group) {
            return JSON.stringify(group.placements.map(function (placement) {
                return [placement.placementId, placement.transform.scale,
                    placement.source && placement.source.componentMaterials || null];
            }));
        }

        // Finish-only edits regroup placements without reloading any model:
        // each new or changed group is built from a copy of a model already on
        // screen. Anything that cannot be served that way returns false and
        // the caller rebuilds the scene as usual.
        function regroupFinishes(value) {
            const layout = value.layout || {};
            const catalog = value.assetCatalog || [];
            if (!state.mounted || state.suspended || state.degraded || state.status === 'degraded'
                    || !state.renderGroups.size || state.pendingLoads > 0
                    || state.finishSceneKey !== finishOnlyKey(layout)
                    || state.appearanceCatalogKey !== JSON.stringify(catalog)
                    || state.motion.package || state.motion.root || state.activity.scenario || state.activity.root
                    || state.navigationPreview.payload || state.navigationPreview.root
                    || state.walkthrough.active || state.drone.active) return false;
            let complete = true;
            state.baseGroups.forEach(function (group) {
                if (!group.resolved || group.deferredVisual || group.deferredLoading || group.drawnDiffers) complete = false;
            });
            if (!complete) return false;
            const previousInput = state.currentInput;
            state.currentInput = { layout: layout, assetCatalog: catalog };
            const built = createBaseGroups(layout, catalog);
            const previousGroups = state.baseGroups;
            const previousRecords = new Map(state.renderGroups);
            const modelSource = modelSources(previousGroups, previousRecords);
            const plan = [];
            for (const entry of built.groups) {
                const key = entry[0], group = entry[1];
                const oldGroup = previousGroups.get(key);
                const record = previousRecords.get(key);
                // Custom finishes used by part finishes resolve again here (Codex on a5c91fa).
                if (oldGroup && record && oldGroup.membershipSignature === group.membershipSignature
                        && oldGroup.partSignature === group.partSignature) {
                    plan.push({ group: group, keep: oldGroup });
                    continue;
                }
                const source = modelSource(key, group);
                if (!source) {
                    state.currentInput = previousInput;
                    return false;
                }
                plan.push({ group: group, source: source });
            }
            clearFinishPreview();
            state.placements = built.placements;
            state.baseGroups = built.groups;
            // Kept groups carry their resolved state; rebuilt ones copy it from the model they reuse.
            plan.forEach(function (step) {
                if (step.keep) {
                    step.keep.placements = step.group.placements;
                    adoptSnapshot(step.keep, step.group);
                    state.baseGroups.set(baseGroupKey(step.group), step.keep);
                    return;
                }
                const prototype = {
                    object: copyRenderable(step.source.prototypeObject),
                    bounds: (previousGroups.get(step.source.baseKey) || {}).bounds || step.group.bounds,
                    instancingEligible: step.source.prototypeInstancingEligible !== false,
                };
                step.group.bounds = prototype.bounds;
                step.group.resolved = true;
                buildRenderedGroup(step.group, prototype, step.source.representation);
            });
            previousRecords.forEach(function (record, key) {
                if (!state.baseGroups.has(key)) {
                    disposeRenderGroup(record);
                    state.renderGroups.delete(key);
                }
            });
            state.appearanceSceneKey = appearanceOnlyKey(layout);
            state.finishSceneKey = finishOnlyKey(layout);
            redrawColumns();
            applySelection();
            syncViewportSceneFromLayout();
            renderEquipmentDecals();
            invalidate();
            return true;
        }

        // Changes that leave every model group intact skip the full rebuild:
        // plain-color appearances, the viewport scene, equipment decals and
        // the site (its photo, areas and roads are synced with the environment;
        // a big plant placed on a site reloaded every model, under the globe's fly-in).
        // Library finishes regroup models (see regroupFinishes).
        function appearanceOnlyKey(layout) {
            const extensions = Object.assign({}, layout.extensions || {});
            delete extensions.facilityScene;
            delete extensions.facilityEquipmentDecals;
            delete extensions.facilitySiteContext;
            return JSON.stringify(Object.assign({}, layout, {
                extensions: extensions,
                placements: (layout.placements || []).map(function (placement) {
                    const copy = Object.assign({}, placement);
                    if (!(copy.appearance && copy.appearance.appearanceId)) delete copy.appearance;
                    return copy;
                }),
            }));
        }

        // The scene's layers besides the model groups, as setScene draws them after clearing the model.
        function renderModelLayers() {
            renderPerimeterWalls();
            if(options.showFloor !== false && floorSurfacesRuntime){
                state.floorSurfaceObjects=floorSurfacesRuntime.meshes(THREE,documentObject,state.currentInput.layout);
                state.floorSurfaceObjects.forEach(object=>state.modelRoot.add(object));
                applyGroundLayers();
            }
            renderZoneMarkings();
            renderZoneCeilings();
            renderZoneRoofs();
            renderFacilityAisles();
            renderFloorMarkings();
        }

        // Placement edits rebuild only the model groups they change (2026-11-03). Committing a Sage edit on a
        // 2,242-placement plant changed a few of its 227 groups, yet the full rebuild reloaded and parsed every
        // model: about 17 s before the view was ready, after the commit and again after its Undo. Here the rest of
        // the scene is cleared and drawn again as the full rebuild does it; a group whose placements are the same
        // keeps its objects; a changed group is built from a copy of its own model on screen, else of the same
        // asset's (with the same wanted representation); only a group with neither loads, as in a full rebuild.
        // A load in progress, another catalog, crossing the large-layout threshold, motion, activity, walks,
        // drones and navigation previews take the full rebuild. Returns null then, else setScene's promise.
        function rebuildChangedGroups(value) {
            const layout = value.layout || {};
            const catalog = value.assetCatalog || [];
            if (!state.mounted || state.suspended || state.degraded || state.status !== 'ready'
                    || !state.modelRoot || !state.renderGroups.size || state.pendingLoads > 0
                    || state.appearanceCatalogKey !== JSON.stringify(catalog)
                    || state.motion.package || state.motion.root || state.activity.scenario || state.activity.root
                    || state.navigationPreview.payload || state.navigationPreview.root
                    || state.walkthrough.active || state.drone.active) return null;
            let settled = true;
            state.baseGroups.forEach(function (group) {
                if (!group.resolved || group.resolvePromise || group.deferredLoading || group.deferredQueued
                        || group.drawnDiffers) {
                    settled = false;
                }
            });
            const large = function (count) {
                return preferOverviewForLargeLayouts && count >= largeLayoutDetailThreshold;
            };
            const count = Array.isArray(layout.placements) ? layout.placements.length : 0;
            if (!settled || large(count) !== large(state.placements.length)) return null;
            // Grouping warns again about each catalog mismatch, and resolves custom finishes from the layout drawn
            // now (Codex on 4a05de6: from the previous one, a finish changed with a move kept its old color).
            state.warnings = state.warnings.filter(function (item) { return item.code !== 'asset_revision_mismatch'; });
            clearFinishPreview();
            setWalkthroughContextFocus(null);
            state.currentInput = { layout: layout, assetCatalog: catalog };
            const built = createBaseGroups(layout, catalog);
            const previousGroups = state.baseGroups;
            const previousRecords = new Map(state.renderGroups);
            const modelSource = modelSources(previousGroups, previousRecords);
            const plan = Array.from(built.groups.keys()).sort().map(function (key) {
                const group = built.groups.get(key);
                const oldGroup = previousGroups.get(key);
                const record = previousRecords.get(key);
                if (oldGroup && record && oldGroup.renderSignature === group.renderSignature) {
                    return { key: key, group: group, keep: oldGroup, record: record };
                }
                return { key: key, group: group, source: modelSource(key, group) };
            });

            abortLoading();
            const generation = state.sceneGeneration;
            if (typeof AbortControllerType === 'function') {
                state.abortController = new AbortControllerType();
            }
            const signal = state.abortController ? state.abortController.signal : null;
            state.lastFit = null;
            state.placements = built.placements;
            state.baseGroups = new Map();
            plan.forEach(function (step) {
                if (step.keep) {
                    step.keep.placements = step.group.placements;
                    step.keep.catalog = step.group.catalog;
                    adoptSnapshot(step.keep, step.group);
                    state.baseGroups.set(step.key, step.keep);
                } else {
                    state.baseGroups.set(step.key, step.group);
                }
            });
            state.worldBounds = computeWorldBounds();
            syncEnvironment();

            const loads = [];
            const keptIds = [];
            state.retiringMaterials = true;
            try {
                clearModelLayers();
                previousRecords.forEach(function (record, key) {
                    if (!state.baseGroups.has(key)) {
                        disposeRenderGroup(record);
                        state.renderGroups.delete(key);
                    }
                });
                detachModelRootChildren();
                state.appearanceSceneKey = appearanceOnlyKey(layout);
                state.finishSceneKey = finishOnlyKey(layout);
                state.appearanceCatalogKey = JSON.stringify(catalog);
                renderModelLayers();
                plan.forEach(function (step) {
                    if (step.keep) {
                        state.modelRoot.add(step.record.container);
                        Array.prototype.push.apply(keptIds, step.record.placementIds);
                        return;
                    }
                    if (step.source) {
                        const prototype = {
                            object: copyRenderable(step.source.prototypeObject),
                            bounds: (previousGroups.get(step.source.baseKey) || {}).bounds || step.group.bounds,
                            instancingEligible: step.source.prototypeInstancingEligible !== false,
                        };
                        step.group.bounds = prototype.bounds;
                        step.group.resolved = true;
                        buildRenderedGroup(step.group, prototype, step.source.representation);
                        return;
                    }
                    buildRenderedGroup(step.group, makeFallbackPrototype(step.group.bounds), 'footprint');
                    loads.push(step.group);
                });
            } finally {
                state.retiringMaterials = false;
            }
            if (lightPoolsWanted()) syncLightPools();
            renderEquipmentDecals(keptIds);
            renderProposalObjects();
            renderGhostObject();
            applySelection();
            state.worldBounds = computeWorldBounds();
            syncEnvironment();
            syncViewportSceneFromLayout();
            invalidate();
            if (!loads.length) return Promise.resolve(getDiagnostics());
            notifyStatus('loading', null);
            return (async function () {
                for (let index = 0; index < loads.length; index += 1) {
                    if (generation !== state.sceneGeneration || !state.mounted) break;
                    await resolveBaseGroup(loads[index], generation, signal);
                }
                if (generation === state.sceneGeneration && state.mounted && !state.degraded) {
                    notifyStatus('ready', null);
                    state.worldBounds = computeWorldBounds();
                    syncEnvironment();
                    invalidate();
                }
                return getDiagnostics();
            }());
        }

        // Each call is a scene request. A request that waits for the appearance library is dropped if a newer one
        // came meanwhile, so an older layout never replaces a newer one. A request is installed once installScene
        // has built its layout into the scene, which it does before its first wait (footprints in place, models
        // loading); until then the previous scene is still drawn, and reads as ready (SV1 round 4, sceneState).
        async function setScene(input) {
            const request = state.sceneRequest += 1;
            const value = input && typeof input === 'object' ? input : {};
            state.requestedInput = input && typeof input === 'object' ? input : null;
            // Library finishes and scenes resolve from the bundled manifests;
            // load them before grouping so the first build is already correct.
            if (layoutNeedsLibrary(value.layout) && facilityLibrary && typeof facilityLibrary.get === 'function'
                    && !facilityLibrary.get() && typeof facilityLibrary.load === 'function') {
                try {
                    await facilityLibrary.load();
                } catch (error) {
                    warning('appearance_library_unavailable',
                        'The appearance library could not be loaded; neutral finishes are shown.', null);
                }
            }
            if (request !== state.sceneRequest) return getDiagnostics();
            const installing = installScene(value);
            state.sceneInstalled = request;
            return installing;
        }

        // The scene a recovery (context restored, remount, resume) rebuilds: the latest one asked for. It may still
        // wait for the appearance library while an older one is drawn; replaying the drawn one would supersede it, and
        // a capture would take the older scene as current (SV1 round 5).
        function latestInput() {
            return state.requestedInput || state.currentInput;
        }

        // The token of an async continuation: the mount, the scene and (when it loads one) the group it started with.
        // It is checked after every await, before records are read or objects attached, and fails once the view was
        // torn down or disposed, a newer scene was installed, or the group was replaced: nothing then comes back
        // into a disposed view, a view mounted since or a newer scene. A continuation that installs a scene itself
        // (a remount, resume or restore replay) takes its token right after asking for it, with installs: true;
        // then only a newer scene request counts against it (final round 3).
        function sceneToken(options) {
            const value = options || {};
            return {
                teardowns: state.teardownCount,
                generation: value.installs ? null : state.sceneGeneration,
                request: value.installs ? state.sceneRequest : null,
                group: value.group || null,
            };
        }

        // A render record is current while it is still the drawn record of its own group (record.baseKey, with the
        // finish or part suffix the asset lookup leaves out) and that group is still in the scene (final round 5).
        function recordCurrent(record) {
            return Boolean(record && state.baseGroups.get(record.baseKey)
                && state.renderGroups.get(record.baseKey) === record);
        }

        function tokenCurrent(token, group) {
            const owned = group || token.group;
            return !state.disposed && state.teardownCount === token.teardowns
                && (token.generation === null || state.sceneGeneration === token.generation)
                && (token.request === null || state.sceneRequest === token.request)
                && (!owned || state.baseGroups.get(baseGroupKey(owned)) === owned);
        }

        // Which scene the 3D view draws, for Sage's 3D shots: a shot is copied only from the scene it started on,
        // installed with nothing newer asked for, in a live WebGL context.
        function sceneState() {
            return {
                requested: state.sceneRequest,
                installed: state.sceneInstalled,
                status: state.status,
                mounted: state.mounted,
                suspended: state.suspended,
                degraded: state.degraded,
                contextLost: state.contextLost,
                disposed: state.disposed,
            };
        }

        async function installScene(value) {
            const previous = state.currentInput;
            if (state.mounted && !state.suspended && !state.degraded
                    && state.status !== 'degraded'
                    && state.renderGroups.size && previous && previous.layout && drawnAsGrouped()
                    && state.appearanceSceneKey === appearanceOnlyKey(value.layout || {})
                    && state.appearanceCatalogKey === JSON.stringify(value.assetCatalog || [])) {
                state.currentInput = { layout: value.layout || {}, assetCatalog: value.assetCatalog || [] };
                const byId = new Map((value.layout.placements || []).map(p => [p.placementId, p]));
                // Keep the group objects alive so pending detail loads also see the new finish.
                state.placements.forEach(p => { p.source = byId.get(p.placementId) || p.source; });
                state.baseGroups.forEach(group => { adoptSnapshot(group, groupSnapshot(group, state.currentInput.layout)); });
                state.finishSceneKey = finishOnlyKey(state.currentInput.layout);
                applySelection();
                syncViewportSceneFromLayout();
                renderEquipmentDecals();
                syncEnvironment();
                return getDiagnostics();
            }
            if (regroupFinishes(value)) return getDiagnostics();
            const rebuilt = rebuildChangedGroups(value);
            if (rebuilt) return rebuilt;
            clearFinishPreview();
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

            state.retiringMaterials = true;
            try {
                clearModel();
            } finally {
                state.retiringMaterials = false;
            }
            state.appearanceSceneKey = appearanceOnlyKey(state.currentInput.layout);
            state.finishSceneKey = finishOnlyKey(state.currentInput.layout);
            state.appearanceCatalogKey = JSON.stringify(state.currentInput.assetCatalog);
            renderModelLayers();
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
            syncViewportSceneFromLayout();
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
            const groundBounds = groundRuntime && groundRuntime.bounds(groundRuntime.surfaces(state.currentInput && state.currentInput.layout));
            if (groundBounds && includeConfiguredBounds !== false) {
                ['x','y','z'].forEach(axis => {
                    output.minimum[axis] = Math.min(output.minimum[axis], groundBounds.minimum[axis]);
                    output.maximum[axis] = Math.max(output.maximum[axis], groundBounds.maximum[axis]);
                });
            }
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

        function disposeSiteAreas() {
            state.siteAreaObjects.forEach(object => { if (object.parent) object.parent.remove(object); });
            disposeObjectGraphs(state.siteAreaObjects);
            state.siteAreaObjects = []; state.siteAreaKey = '';
        }

        // Vehicle routes to the main road (site_access.vehicle_routes): two flat lanes just above the photo,
        // incoming solid and outgoing dashed, each on its own side of the street, with arrowheads; colours as
        // on the Site tab.
        function disposeSiteRoutes() {
            state.siteRouteObjects.forEach(object => { if (object.parent) object.parent.remove(object); });
            disposeObjectGraphs(state.siteRouteObjects);
            state.siteRouteObjects = []; state.siteRouteKey = '';
        }

        function routeMesh(strips, triangles, width, y, color, pose) {
            const positions = [];
            const at = point => propertyToLayout(pose, point.x, point.z);
            strips.forEach(function (strip) {
                for (let i = 1; i < strip.length; i++) {
                    const a = strip[i - 1], b = strip[i], length = Math.hypot(b.x - a.x, b.z - a.z);
                    if (length < 1e-6) continue;
                    const nx = -(b.z - a.z) / length * width / 2, nz = (b.x - a.x) / length * width / 2;
                    const corners = [{ x: a.x + nx, z: a.z + nz }, { x: a.x - nx, z: a.z - nz },
                        { x: b.x - nx, z: b.z - nz }, { x: b.x + nx, z: b.z + nz }].map(at);
                    [0, 1, 2, 0, 2, 3].forEach(k => positions.push(corners[k].x, y, corners[k].z));
                }
            });
            triangles.forEach(triangle => triangle.map(at).forEach(p => positions.push(p.x, y + 0.002, p.z)));
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
            const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
                color: color, side: THREE.DoubleSide, toneMapped: false, depthWrite: false }));
            mesh.renderOrder = -5;
            mesh.raycast = function () {};
            return mesh;
        }

        function syncSiteRoutes() {
            const layout = state.currentInput && state.currentInput.layout;
            const site = siteRuntime && siteRuntime.siteContextOf(layout);
            const routes = site && options.showFloor !== false && typeof siteRuntime.offsetLine === 'function'
                ? (site.routes || []).filter(route => route.mainRoad && route.points.length > 1) : [];
            const key = routes.length ? JSON.stringify([routes, site.buildingPose, layout.coordinateFrame]) : '';
            if (key === state.siteRouteKey) return;
            disposeSiteRoutes();
            if (!key || !state.siteRoot || typeof THREE.BufferGeometry !== 'function'
                    || typeof THREE.MeshBasicMaterial !== 'function') return;
            // Just above paving and floor finishes, so the lanes show where they cross the paved lot.
            const y = finite(layout.coordinateFrame && layout.coordinateFrame.floorElevation, 0) + 0.02;
            routes.forEach(function (route) {
                const color = siteRuntime.routeColor(route.use);
                const inward = siteRuntime.offsetLine(route.points.slice().reverse(), 3.2);
                const outward = siteRuntime.offsetLine(route.points, 3.2);
                [[[inward], inward], [siteRuntime.dashes(outward, 7, 5), outward]].forEach(function (pair) {
                    const mesh = routeMesh(pair[0], siteRuntime.arrowsAlong(pair[1], 30, 2.4), 1.4, y, color,
                        site.buildingPose);
                    mesh.name = 'SiteRoute:' + route.routeId;
                    mesh.userData.facilitySiteRoute = route.routeId;
                    state.siteRoot.add(mesh);
                    state.siteRouteObjects.push(mesh);
                });
            });
            state.siteRouteKey = key;
            applyGroundLayers();
            invalidate();
        }

        function syncSiteAreas() {
            const layout = state.currentInput && state.currentInput.layout;
            const site = siteRuntime && siteRuntime.siteContextOf(layout);
            const key = site && options.showFloor !== false ? JSON.stringify([site.property, site.areas, site.buildingPose, layout.coordinateFrame]) : '';
            if (key === state.siteAreaKey) return;
            disposeSiteAreas();
            if (!key || !state.siteRoot || !floorSurfacesRuntime || !THREE.ShapeGeometry) return;
            const surfaces = siteRuntime.areaSurfaces(layout);
            state.siteAreaObjects = floorSurfacesRuntime.meshes(THREE, documentObject,
                { extensions: { facilityFloorSurfaces: { surfaces: surfaces } } });
            state.siteAreaObjects.forEach((mesh, i) => {
                mesh.name = 'SiteArea:' + surfaces[i].surfaceId;
                mesh.userData.facilitySiteArea = surfaces[i].surfaceId;
                mesh.renderOrder = -10; mesh.raycast = function () {}; state.siteRoot.add(mesh);
            });
            if (site.property && THREE.LineLoop) {
                const y = finite(layout.coordinateFrame && layout.coordinateFrame.floorElevation, 0) + 0.025;
                const points = site.property.boundary.map(p => propertyToLayout(site.buildingPose, p.x, p.z));
                const geometry = new THREE.BufferGeometry();
                geometry.setAttribute('position', new THREE.Float32BufferAttribute(points.flatMap(p => [p.x, y, p.z]), 3));
                const line = new THREE.LineLoop(geometry, new THREE.LineBasicMaterial({ color: '#6fe3ae' }));
                line.name = 'SitePropertyBoundary'; line.raycast = function () {};
                state.siteRoot.add(line); state.siteAreaObjects.push(line);
            }
            applyGroundLayers();
            state.siteAreaKey = key; invalidate();
        }

        function siteFitBounds() {
            const base = configuredEnvironmentBounds() || state.worldBounds;
            const layout = state.currentInput && state.currentInput.layout;
            const site = siteRuntime && siteRuntime.siteContextOf(layout);
            if (!base || !site) return base;
            const points = (site.property ? site.property.boundary : []).concat(...(site.areas || []).map(area => area.boundary))
                .map(p => propertyToLayout(site.buildingPose, p.x, p.z));
            return { minimum: { x: Math.min(base.minimum.x, ...points.map(p => p.x)), y: base.minimum.y,
                z: Math.min(base.minimum.z, ...points.map(p => p.z)) },
                maximum: { x: Math.max(base.maximum.x, ...points.map(p => p.x)), y: base.maximum.y,
                    z: Math.max(base.maximum.z, ...points.map(p => p.z)) } };
        }

        function fitFacility() {
            return fitBounds(
                siteFitBounds(),
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
            loadDeferredVisibleGroups();
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
            state.wallObjects.forEach(function (object) { object.visible = next.walls !== false; });
            state.columnObjects.forEach(function (object) { object.visible = next.walls !== false; });
            state.wallFinishObjects.forEach(function (object) {
                const art=object.userData&&object.userData.exteriorArtwork;
                object.visible = next.walls !== false && (!art || art.status==='ready');
            });
            state.routeObjects.forEach(function (object) {
                object.visible = next.routes !== false;
            });
            state.floorMarkingObjects.forEach(function (object) {
                object.visible = next.markings !== false;
            });
            state.zoneObjects.forEach(function (object) {
                object.visible = next[object.userData.visibilityLayer] !== false;
            });
            state.zoneCeilingObjects.forEach(function (object) {
                object.visible = next.overhead !== false;
            });
            state.zoneRoofObjects.forEach(function (object) {
                object.visible = next.roofSheeting !== false;
            });
            state.renderGroups.forEach(function (record) {
                if (record && record.container) {
                    record.container.visible = next[record.visibilityLayer || 'assets'] !== false;
                }
            });
            state.equipmentDecalObjects.forEach(function (entry) {
                entry.meshes.forEach(function (mesh) { mesh.visible = next.assets !== false; });
            });
            if (state.proposalRoot) {
                state.proposalRoot.visible = next.assets !== false;
            }
            syncLightPools();
            applyGroundLayers();
            invalidate();
            return Object.assign({}, state.layerVisibility);
        }

        // Paving, floor finishes and site overlays are rebuilt as the layout changes; each rebuild
        // calls this too, so a hidden layer stays hidden.
        function applyGroundLayers() {
            const layers = state.layerVisibility || DEFAULT_LAYER_VISIBILITY;
            if (state.environmentRoot) state.environmentRoot.visible = layers.ground !== false;
            (state.floorSurfaceObjects || []).forEach(function (object) { object.visible = layers.surfaces !== false; });
            (state.siteAreaObjects || []).concat(state.siteRouteObjects || []).forEach(function (object) {
                const paving = object.userData && object.userData.facilitySiteArea;
                object.visible = (paving ? layers.ground : layers.site) !== false;
            });
        }

        function getLayerVisibility() {
            return Object.assign({}, state.layerVisibility);
        }

        // View only, until the walls are next drawn: hide the wall pieces whose names start with one of `prefixes`
        // (e.g. a closed dock door's panel, 'layout-interior-wall-iw-dock-door-3-', as a camera flies out through
        // it); an empty list shows them all again. The layout is not changed.
        function setWallPiecesHidden(prefixes) {
            const hidden = Array.isArray(prefixes) ? prefixes.filter(function (prefix) {
                return typeof prefix === 'string' && prefix;
            }) : [];
            let count = 0;
            state.wallObjects.forEach(function (object) {
                const hide = hidden.some(function (prefix) { return String(object.name).indexOf(prefix) === 0; });
                object.visible = state.layerVisibility.walls !== false && !hide;
                if (hide) count += 1;
            });
            invalidate();
            return count;
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
                || siteFitBounds();
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
            const site = siteRuntime && siteRuntime.siteContextOf(state.currentInput && state.currentInput.layout);
            const bearing = site ? site.buildingPose.bearingDegrees * Math.PI / 180 : null;
            setVector(state.camera.up, site ? { x: -Math.sin(bearing), y: 0, z: Math.cos(bearing) } : { x: 0, y: 0, z: -1 });
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
            if (material.userData.facilityHighlightKind === highlightKind) return;
            material.userData.facilityHighlightKind = highlightKind;
            markGlowStencil(material);
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
            // Emissive values are uniforms; changing them does not require a new shader program.
        }

        function applySelection(skipInvalidate, onlyRecord) {
            // Plain-color appearances tint here. Library finishes own their
            // materials (their color is already in the material), so they are skipped.
            // onlyRecord: a group just built. Every change of selection, focus or appearance applies to all groups, so
            // the others are already up to date (2026-11-03: applying to all after each build made a scene's load
            // quadratic, 1.7 s on a 2,242-placement plant).
            const records = onlyRecord ? [onlyRecord] : Array.from(state.renderGroups.values());
            const ids = onlyRecord ? new Set(onlyRecord.placementIds || []) : null;
            const appearance = new Map((ids ? state.placements.filter(p => ids.has(p.placementId))
                : state.placements).map(function (p) {
                const value = p.source && p.source.appearance;
                const color = value && !value.appearanceId && value.color;
                return [p.placementId, /^#[0-9a-fA-F]{6}$/.test(color || '') ? parseInt(color.slice(1), 16) : null];
            }));
            const selectionVisible = !immersiveActive();
            const contextPlacementId = immersiveActive()
                && state.walkthroughContextFocus
                ? state.walkthroughContextFocus.placementId : null;
            records.forEach(function (record) {
                if (record.instanced) {
                    record.pickObjects.forEach(function (object) {
                        const placementIds = state.instanceLookup.get(object) || [];
                        object.userData = object.userData || {};
                        const selectedIds = placementIds.filter(id => state.selectedIds.has(id));
                        const focusedId = placementIds.includes(contextPlacementId) ? contextPlacementId : null;
                        const signature = JSON.stringify([selectionVisible, selectedIds, focusedId,
                            placementIds, placementIds.map(id => appearance.get(id))]);
                        if (object.userData.facilityHighlightSignature === signature) return;
                        object.userData.facilityHighlightSignature = signature;
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
                                            : !isAuthoredSurfaceMaterial(object.material) && appearance.get(placementId) != null ? appearance.get(placementId)
                                                : object.material.userData.facilityInstanceBaseColor ?? NORMAL_INSTANCE_COLOR
                                    )
                                );
                            });
                            if (object.instanceColor) {
                                object.instanceColor.needsUpdate = true;
                            }
                        }
                        object.userData = object.userData || {};
                        object.userData.selectedPlacementIds = selectedIds;
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
                            if (!material.userData?.facilityComponentOverride && !material.userData?.facilityAppearanceFinish
                                    && !isAuthoredSurfaceMaterial(material) && material.color && typeof material.color.setHex === 'function') {
                                material.userData = material.userData || {};
                                if (material.userData.facilityAppearanceBaseColor === undefined) {
                                    material.userData.facilityAppearanceBaseColor = material.color.getHex();
                                }
                                material.color.setHex(appearance.get(placementId) != null
                                    ? appearance.get(placementId) : material.userData.facilityAppearanceBaseColor);
                            }
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

        // ---- Appearance library: finishes, viewport scenes, equipment decals ----

        function shortHash(text) {
            let first = 0x811c9dc5, second = 0x9dc5811c;
            for (let index = 0; index < text.length; index += 1) {
                const code = text.charCodeAt(index);
                first = Math.imul(first ^ code, 0x01000193) >>> 0;
                second = Math.imul(second ^ code, 0x01000193) >>> 0;
            }
            return first.toString(16).padStart(8, '0') + second.toString(16).padStart(8, '0');
        }

        function currentLayout() {
            return state.currentInput && state.currentInput.layout || {};
        }

        function currentLibrary() {
            return facilityLibrary && typeof facilityLibrary.get === 'function' ? facilityLibrary.get() : null;
        }

        function layoutNeedsLibrary(layout) {
            if (!layout || typeof layout !== 'object') return false;
            if (layout.extensions && layout.extensions.facilityScene) return true;
            const columns = layout.extensions && layout.extensions.facilityColumns;
            if (columns && Array.isArray(columns.columns) && columns.columns.some(function (column) {
                return column && column.appearance && column.appearance.appearanceId;
            })) return true;
            return (layout.placements || []).some(function (placement) {
                if (placement && placement.appearance && placement.appearance.appearanceId) return true;
                const parts = placement && placement.componentMaterials && placement.componentMaterials.overrides;
                return Array.isArray(parts) && parts.some(function (row) { return row && row.appearanceId; });
            });
        }

        function placementFinish(placement) {
            const value = placement && placement.source && placement.source.appearance;
            if (!value || !value.appearanceId || !libraryRuntime || !finishesRuntime) return null;
            const library = currentLibrary();
            if (!library) return { appearanceId: value.appearanceId, missing: true, label: value.appearanceId };
            return libraryRuntime.resolveAppearance(library, value, currentLayout());
        }

        function finishTextureCache() {
            if (!state.finishTextures && finishesRuntime) {
                const capabilities = state.renderer && state.renderer.capabilities;
                const anisotropy = capabilities && typeof capabilities.getMaxAnisotropy === 'function'
                    ? Math.max(1, Math.min(8, capabilities.getMaxAnisotropy())) : 1;
                state.finishTextures = finishesRuntime.createTextureCache(THREE, {
                    anisotropy: anisotropy,
                    onChange: function () { invalidate(); },
                    onError: function (url) {
                        warning('appearance_texture_missing',
                            'A finish texture could not be loaded; its tint is shown instead.', url);
                    },
                });
            }
            return state.finishTextures;
        }

        function ensureEnvironmentLoader() {
            if (!state.environmentLoader && scenesRuntime && state.renderer
                    && typeof THREE.PMREMGenerator === 'function') {
                state.environmentLoader = scenesRuntime.createEnvironmentLoader({
                    THREE: THREE, renderer: state.renderer,
                    RoomEnvironment: RoomEnvironmentType, HDRLoader: HDRLoaderType,
                });
            }
            return state.environmentLoader;
        }

        // Library finishes need something to reflect. In the Classic scene they
        // get a neutral room of their own, which leaves every other asset looking
        // exactly as before.
        function roomEnvironment() {
            const loader = ensureEnvironmentLoader();
            try {
                return loader ? loader.room() : null;
            } catch (error) {
                reportError('finish_environment_failed', error);
                return null;
            }
        }

        // Finishes carry their own environment map. three.js applies a scene's
        // environment intensity and rotation only to materials without one, so a
        // scene can keep the fill on plain models gentle while finishes keep
        // their reflections (twice the scene's setting; 0.7 in Classic).
        function finishEnvironment() {
            if (state.scene && state.scene.environment) return state.scene.environment;
            return roomEnvironment();
        }

        function finishReflection() {
            if (!(state.scene && state.scene.environment)) return 0.7;
            const intensity = Number(state.viewportScene && state.viewportScene.environmentIntensity);
            return Math.min(2, 2 * (Number.isFinite(intensity) ? Math.max(0, intensity) : 0.5));
        }

        function syncFinishEnvironment(material) {
            const envMap = finishEnvironment();
            if (material.envMap !== envMap) {
                material.envMap = envMap;
                material.needsUpdate = true;
            }
            material.envMapIntensity = finishReflection();
            const rotation = material.envMapRotation;
            if (rotation && typeof rotation.copy === 'function') {
                if (state.scene && state.scene.environment && state.scene.environmentRotation) {
                    rotation.copy(state.scene.environmentRotation);
                } else if (typeof rotation.set === 'function') {
                    rotation.set(0, 0, 0);
                }
            }
        }

        // ---- Lights (docs/facility-lighting-plan.md, L2) -------------------------------------------------
        // A glow is a Lights finish (userData.facilityGlow, drawn outside tone mapping) or a glow authored in a
        // model: an authored-finish or artwork material with an emissive color (a lamp lens, an exit sign, a
        // display), recorded as userData.facilityAuthoredGlow when the model is prepared. The scene's lights
        // switch (adjustments.lights false) turns every glow off, so the plain surface underneath shows, and back
        // on, without rebuilding anything.
        function lightsOn() {
            return !(state.viewportScene && state.viewportScene.lights === false);
        }

        function recordAuthoredGlows(object) {
            eachMaterial(object, function (material) {
                const data = material.userData || {};
                if (data.facilityAuthoredGlow || data.facilityGlow || !isAuthoredSurfaceMaterial(material)) return;
                const emissive = material.emissive;
                const intensity = finite(material.emissiveIntensity, 1);
                if (!emissive || intensity <= 0 || Math.max(emissive.r, emissive.g, emissive.b) <= 0) return;
                material.userData = Object.assign(data, {
                    facilityAuthoredGlow: { rgb: [emissive.r, emissive.g, emissive.b], intensity: intensity },
                });
            });
        }

        function setMaterialLight(material, on, mesh) {
            const data = material && material.userData;
            const glow = data && (data.facilityGlow || data.facilityAuthoredGlow);
            if (!glow || !material.emissive) return false;
            markGlowStencil(material);
            const color = new THREE.Color(0x000000);
            if (on && Array.isArray(glow.rgb)) color.setRGB(glow.rgb[0], glow.rgb[1], glow.rgb[2]);
            else if (on) color.set(glow.color);
            const intensity = on ? finite(glow.intensity, 1) : 0;
            // A highlighted object keeps its highlight; the switch shows when it is deselected.
            if (data.facilitySelectionOriginal) {
                data.facilitySelectionOriginal.emissive = color.getHex();
                data.facilitySelectionOriginal.emissiveIntensity = intensity;
            }
            if (!data.facilityHighlightKind) {
                material.emissive.copy(color);
                material.emissiveIntensity = intensity;
            }
            // A Lights finish leaves tone mapping only while it glows; switched off it is plain plastic.
            if (data.facilityGlow && material.toneMapped !== !on) {
                material.toneMapped = !on;
                material.needsUpdate = true;
            }
            // A cycle light switched off keeps its first color in the lens, as a recolored lamp keeps its color.
            if (!on && data.facilityGlow && data.facilityGlow.pattern === 'cycle' && material.color) {
                material.color.set(finishesRuntime.unlitColor(data.facilityGlow.color));
            }
            // A blinking light sets its own brightness each time it is drawn (L4).
            if (data.facilityGlow && finishesRuntime && finishesRuntime.glowMoves(data.facilityGlow)) {
                material.onBeforeRender = drawPatternedGlow;
            } else if (lightAreasActive()) {
                // A steady glow may be general lighting, which the scene switches by area (L7).
                addLampTable(material, mesh);
            }
            return true;
        }

        // The glow halo (L6) spreads only from glowing pixels: a glow marks the stencil wherever it is drawn, except
        // while it shows a selection highlight. three sets the stencil state per draw, so no program changes.
        function markGlowStencil(material) {
            const data = material.userData || {};
            const mark = Boolean(data.facilityGlow || data.facilityAuthoredGlow) && !data.facilityHighlightKind;
            if (Boolean(material.stencilWrite) === mark || THREE.ReplaceStencilOp === undefined) return;
            material.stencilWrite = mark;
            material.stencilRef = GLOW_STENCIL;
            material.stencilFunc = THREE.AlwaysStencilFunc;
            material.stencilZPass = THREE.ReplaceStencilOp;
        }

        function syncLights(root) {
            const on = lightsOn();
            let glows = 0;
            eachMaterial(root, function (material, mesh) { if (setMaterialLight(material, on, mesh)) glows += 1; });
            return glows;
        }

        // ---- Blinking lights (docs/facility-lighting-plan.md, L4) ----------------------------------------------
        // A Lights finish may blink, strobe or turn like a rotating beacon (emission.pattern). three.js calls
        // drawPatternedGlow just before it draws an object with one, so only lamps actually drawn (in view, on a
        // shown layer, lights on) set their brightness and keep the view redrawing. Rendering stays on demand:
        // after each frame one timer is set for the next change of any lamp drawn, so a 1 s blink redraws twice a
        // second and a turning beacon four times. No timer while none is in view, while the window is hidden, or
        // when the viewer prefers reduced motion (then every pattern shows steady).
        function drawPatternedGlow(renderer, scene, camera, geometry, object) {
            const material = this;
            const data = material && material.userData;
            const glow = data && data.facilityGlow;
            if (!glow || data.facilityHighlightKind || !lightsOn()) return;
            const patterns = state.lightPatterns;
            const still = Boolean(state.motion.prefersReducedMotion);
            const seconds = patterns.clock / 1000;
            material.emissiveIntensity = finite(glow.intensity, 1) * (still ? 1 : finishesRuntime.glowLevel(glow, seconds));
            // A cycle light changes color instead: the glow, and its unlit lens at half brightness (its first color,
            // steady, under reduced motion).
            if (glow.pattern === 'cycle') {
                const color = finishesRuntime.glowColor(glow, still ? 0 : seconds);
                material.emissive.set(color);
                if (material.color) material.color.set(finishesRuntime.unlitColor(color));
            }
            if (still || !glowCopyInView(object, camera)) return;
            patterns.drawn = true;
            patterns.next = Math.min(patterns.next, finishesRuntime.nextGlowChange(glow, seconds));
        }

        // three.js culls an instanced batch as a whole, and a batch of beacons can span the hall: check the copies.
        function glowCopyInView(object, camera) {
            if (!object || !object.isInstancedMesh || !camera || typeof object.getMatrixAt !== 'function') return true;
            const patterns = state.lightPatterns;
            if (!patterns.frustum) {
                patterns.frustum = new THREE.Frustum().setFromProjectionMatrix(
                    new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
            }
            const geometry = object.geometry;
            if (!geometry.boundingSphere) geometry.computeBoundingSphere();
            const matrix = new THREE.Matrix4();
            const sphere = new THREE.Sphere();
            for (let index = 0; index < object.count; index += 1) {
                object.getMatrixAt(index, matrix);
                matrix.premultiply(object.matrixWorld);
                if (patterns.frustum.intersectsSphere(sphere.copy(geometry.boundingSphere).applyMatrix4(matrix))) return true;
            }
            return false;
        }

        function beginLightPatternFrame() {
            const patterns = state.lightPatterns;
            patterns.clock = lightClock();
            patterns.drawn = false;
            patterns.next = Infinity;
            patterns.frustum = null;
        }

        function scheduleLightPatterns() {
            const patterns = state.lightPatterns;
            patterns.inView = patterns.drawn;
            const timerHost = options.window || root;
            const hidden = Boolean(documentObject && documentObject.hidden);
            if (!patterns.drawn || hidden || !Number.isFinite(patterns.next)
                    || !timerHost || typeof timerHost.setTimeout !== 'function') {
                stopLightPatterns();
                return false;
            }
            if (patterns.timer !== null && patterns.due === patterns.next) return true;
            stopLightPatterns();
            const delay = Math.max(0, patterns.next * 1000 - lightClock()) + LIGHT_PATTERN_SLACK_MS;
            patterns.due = patterns.next;
            patterns.timer = timerHost.setTimeout(function () {
                patterns.timer = null;
                patterns.due = null;
                patterns.redraws += 1;
                invalidate();
            }, delay);
            return true;
        }

        function stopLightPatterns() {
            const patterns = state.lightPatterns;
            const timerHost = options.window || root;
            if (patterns.timer !== null && timerHost && typeof timerHost.clearTimeout === 'function') {
                timerHost.clearTimeout(patterns.timer);
            }
            patterns.timer = null;
            patterns.due = null;
        }

        // ---- Floor light pools (docs/facility-lighting-plan.md, L3) -------------------------------------------
        // In a scene that asks for them (lightPools in the scene manifest: Evening) and with the lights on, every lit
        // lamp hung at least 3 m up and facing down throws a soft additive pool on the floor (y 0) below it. One mesh
        // per render group, built the first time it is needed and dropped with the group. The pools follow the
        // group's layer, are never picked and light nothing else. An outdoor lamp (a Lights finish with a beam
        // angle, L8) throws its pool on the ground where its aim lands instead, and shows a beam (syncLightBeams).
        // A low outdoor light (emission.low, 2026-11-05: a bollard, a lantern) throws it from any height, with no beam.
        function lightPoolsWanted() {
            return Boolean(lightPoolsRuntime && lightsOn() && state.viewportScene && state.viewportScene.lightPools);
        }

        function buildLightPools(record) {
            if (!record.container || typeof record.container.traverse !== 'function') return null;
            record.container.updateMatrixWorld(true);
            const toRoot = new THREE.Matrix4();
            if (state.modelRoot && state.modelRoot.matrixWorld) toRoot.copy(state.modelRoot.matrixWorld).invert();
            const pools = [];
            record.container.traverse(function (object) {
                if (!object.isMesh || !object.geometry || !object.material || Array.isArray(object.material)) return;
                const data = object.material.userData || {};
                const glow = data.facilityGlow || data.facilityAuthoredGlow;
                // A blinking lamp throws no pool: a steady pool under it would not blink with it (L4). An accent spot
                // lights what it aims at with a spot light instead (syncLampSpots).
                if (!glow || finishesRuntime.glowMoves(glow) || glow.accent) return;
                const color = new THREE.Color();
                if (Array.isArray(glow.rgb)) color.setRGB(glow.rgb[0], glow.rgb[1], glow.rgb[2]);
                else color.set(glow.color);
                const beam = Number(glow.beamAngleDegrees) > 0
                    ? { angleDegrees: Number(glow.beamAngleDegrees), groundAt: groundHeightAt, low: glow.low === true }
                    : null;
                Array.prototype.push.apply(pools, lightPoolsRuntime.poolsOf(THREE, object, toRoot, color, 0, beam));
            });
            if (!pools.length) return null;
            const shared = state.lightPools;
            if (!shared.material) {
                shared.texture = lightPoolsRuntime.poolTexture(THREE);
                shared.material = new THREE.MeshBasicMaterial({
                    map: shared.texture, vertexColors: true, transparent: true, blending: THREE.AdditiveBlending,
                    depthWrite: false, toneMapped: false, fog: false,
                    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
                });
                shared.material.color.setScalar(LIGHT_POOL_STRENGTH);
                shared.material.userData.facilityLightPools = true;
            }
            const mesh = new THREE.Mesh(lightPoolsRuntime.poolGeometry(THREE, pools, LIGHT_POOL_LIFT), shared.material);
            mesh.name = 'FacilityLightPools:' + record.baseKey;
            mesh.renderOrder = 2;
            mesh.raycast = function () {};
            mesh.userData.facilityLightPools = { pools: pools.length, placementIds: record.placementIds.slice() };
            state.lightAreas.pools.set(mesh, pools);
            return mesh;
        }

        function dropLightPools(record) {
            const pools = state.lightPools;
            const mesh = pools.meshes.get(record);
            pools.meshes.delete(record);
            if (!mesh) return;
            if (mesh.parent) mesh.parent.remove(mesh);
            mesh.geometry.dispose();
        }

        // The ground's height under a point of the layout (L8): a ground surface there (a sunken truck yard, a
        // ramp), else the floor.
        function groundHeightAt(x, z, nearY) {
            const layout = currentLayout();
            const rows = groundRuntime && groundRuntime.surfaces(layout);
            const hit = rows && rows.length ? groundRuntime.sample(rows, { x: x, z: z }, nearY) : null;
            return hit ? hit.y : finite(layout.coordinateFrame && layout.coordinateFrame.floorElevation, 0);
        }

        // Shows the pools when wanted (building any missing), hides them otherwise; a group's pools follow its layer.
        // An outdoor lamp's pool lies on the ground, so a change of the ground builds them again.
        function syncLightPools() {
            const pools = state.lightPools;
            pools.meshes.forEach(function (mesh, record) {
                if (state.renderGroups.get(record.baseKey) !== record) dropLightPools(record);
            });
            const layout = currentLayout();
            const groundKey = JSON.stringify([groundRuntime ? groundRuntime.surfaces(layout) || null : null,
                layout.coordinateFrame ? layout.coordinateFrame.floorElevation : null]);
            if (groundKey !== pools.groundKey) {
                Array.from(pools.meshes.keys()).forEach(dropLightPools);
                pools.groundKey = groundKey;
            }
            const wanted = lightPoolsWanted() && Boolean(state.modelRoot);
            if (pools.root) pools.root.visible = wanted;
            if (!wanted) {
                syncLampLighting();
                return 0;
            }
            if (!pools.root) {
                pools.root = createContainer();
                pools.root.name = 'FacilityLightPools';
            }
            if (pools.root.parent !== state.modelRoot) state.modelRoot.add(pools.root);
            state.renderGroups.forEach(function (record) {
                if (!record || !record.container) return;
                if (!pools.meshes.has(record)) {
                    const mesh = buildLightPools(record);
                    pools.meshes.set(record, mesh);
                    if (mesh) pools.root.add(mesh);
                }
                const mesh = pools.meshes.get(record);
                if (mesh) mesh.visible = record.container.visible !== false;
            });
            maskLightPools();
            syncLampLighting();
            invalidate();
            return countLightPools();
        }

        // ---- Lamps that light things (2026-11-02) ------------------------------------------------------------------
        // In a scene with floor pools (Evening) and with the lights on, lamps also light what they shine on:
        // - Spots: a pendant hung below the pool height over a table, and an accent spot (a Lights finish marked
        //   accent), are candidates for SPOT_COUNT real three.js spot lights without shadows (light_pools.spotsOf and
        //   spotSettings). The count is fixed while the scene has any, so lit materials compile once; before each
        //   frame the lights go to the candidates nearest the view (the orbit target, or ahead of a walker), and
        //   unused ones are dark. A candidate follows its group's layer. Light areas (L7) switch general lighting
        //   only, so they leave these on.
        // - Fill: the general lighting's floor pools (not outdoor beams; lamps the areas leave on, on shown layers)
        //   are summed into a small map over the plan (light_pools.fillField), and every lit material in the model
        //   adds it to its indirect light below the lamps (light_pools.patchFillShader; patched once, the first time
        //   it is wanted, then off by a uniform outside Evening). So a chair under a downlight is lifted, a ceiling
        //   above it is not.
        function syncLampLighting() {
            syncLampSpots();
            syncLightFill();
        }

        function lampLightingAvailable() {
            return Boolean(lightPoolsRuntime && typeof lightPoolsRuntime.spotsOf === 'function'
                && typeof THREE.SpotLight === 'function' && typeof THREE.Matrix4 === 'function');
        }

        function buildLampSpots(record) {
            const spots = [];
            if (!record.container || typeof record.container.traverse !== 'function') return spots;
            record.container.updateMatrixWorld(true);
            const toRoot = new THREE.Matrix4();
            if (state.modelRoot && state.modelRoot.matrixWorld) toRoot.copy(state.modelRoot.matrixWorld).invert();
            record.container.traverse(function (object) {
                if (!object.isMesh || !object.geometry || !object.material || Array.isArray(object.material)) return;
                const data = object.material.userData || {};
                const glow = data.facilityGlow || data.facilityAuthoredGlow;
                // A blinking lamp lights nothing steady, as it throws no pool (L4).
                if (!glow || finishesRuntime.glowMoves(glow)) return;
                const color = new THREE.Color();
                if (Array.isArray(glow.rgb)) color.setRGB(glow.rgb[0], glow.rgb[1], glow.rgb[2]);
                else color.set(glow.color);
                lightPoolsRuntime.spotsOf(THREE, object, toRoot, glow, 0).forEach(function (spot) {
                    spots.push(Object.assign(spot, { color: color, settings: lightPoolsRuntime.spotSettings(spot, glow) }));
                });
            });
            return spots;
        }

        function syncLampSpots() {
            const spots = state.lampSpots;
            spots.lists.forEach(function (list, record) {
                if (state.renderGroups.get(record.baseKey) !== record) spots.lists.delete(record);
            });
            const wanted = lightPoolsWanted() && Boolean(state.modelRoot) && lampLightingAvailable();
            const candidates = [];
            if (wanted) {
                state.renderGroups.forEach(function (record) {
                    if (!record || !record.container) return;
                    if (!spots.lists.has(record)) spots.lists.set(record, buildLampSpots(record));
                    if (record.container.visible === false) return;
                    Array.prototype.push.apply(candidates, spots.lists.get(record));
                });
            }
            spots.candidates = candidates;
            spots.key = '';
            if (!candidates.length) {
                if (spots.root && spots.root.parent) spots.root.parent.remove(spots.root);
                spots.assigned = 0;
                return 0;
            }
            if (!spots.root) {
                spots.root = createContainer();
                spots.root.name = 'FacilityLampSpots';
                for (let slot = 0; slot < lightPoolsRuntime.SPOT_COUNT; slot += 1) {
                    const light = new THREE.SpotLight(0xffffff, 0);
                    light.name = 'FacilityLampSpot:' + slot;
                    light.castShadow = false;
                    spots.root.add(light);
                    spots.root.add(light.target);
                    spots.lights.push(light);
                }
            }
            if (spots.root.parent !== state.modelRoot) state.modelRoot.add(spots.root);
            assignLampSpots();
            invalidate();
            return candidates.length;
        }

        // Where the view looks, in the model's coordinates: the orbit target, or 3 m ahead of a walker.
        function lampSpotFocus() {
            const focus = new THREE.Vector3();
            const target = state.controls && state.controls.target;
            if (!state.walkthrough.active && target && Number.isFinite(target.x)) {
                focus.set(target.x, finite(target.y, 0), finite(target.z, 0));
            } else if (state.camera) {
                state.camera.getWorldDirection(focus);
                focus.multiplyScalar(3).add(state.camera.position);
            }
            if (state.modelRoot && typeof state.modelRoot.worldToLocal === 'function') state.modelRoot.worldToLocal(focus);
            return focus;
        }

        function assignLampSpots() {
            const spots = state.lampSpots;
            if (!spots.root || !spots.root.parent || !spots.candidates.length) return;
            const focus = lampSpotFocus();
            const chosen = spots.candidates.map(function (spot, index) {
                const dx = spot.x - focus.x;
                const dy = spot.y - focus.y;
                const dz = spot.z - focus.z;
                return { index: index, distance: dx * dx + dy * dy + dz * dz };
            }).sort(function (a, b) { return a.distance - b.distance || a.index - b.index; })
                .slice(0, spots.lights.length);
            const key = chosen.map(function (pick) { return pick.index; }).join(',');
            if (key === spots.key) return;
            spots.key = key;
            spots.lights.forEach(function (light, slot) {
                const pick = chosen[slot];
                if (!pick) {
                    light.intensity = 0;
                    return;
                }
                const spot = spots.candidates[pick.index];
                const settings = spot.settings;
                light.color.copy(spot.color);
                light.intensity = settings.intensity;
                light.angle = settings.angle;
                light.penumbra = settings.penumbra;
                light.distance = settings.distance;
                light.decay = settings.decay;
                light.position.set(spot.x, spot.y, spot.z);
                light.target.position.set(spot.x + spot.aim.x, spot.y + spot.aim.y, spot.z + spot.aim.z);
                light.updateMatrixWorld();
                light.target.updateMatrixWorld();
            });
            spots.assigned = chosen.length;
        }

        function lightFillAvailable() {
            return Boolean(lightPoolsRuntime && typeof lightPoolsRuntime.fillField === 'function'
                && typeof lightPoolsRuntime.insideOutline === 'function' && typeof lightPoolsRuntime.fillMask === 'function'
                && typeof THREE.DataTexture === 'function' && THREE.DataUtils && THREE.HalfFloatType !== undefined
                && THREE.RedFormat !== undefined && THREE.RGFormat !== undefined && typeof THREE.Vector4 === 'function');
        }

        // The zones with a ceiling (ceilings.py), as outlines: the fill is only under them, from their lamps.
        function ceilingOutlines() {
            const layout = state.currentInput && state.currentInput.layout || {};
            return (Array.isArray(layout.zones) ? layout.zones : []).filter(function (zone) {
                const ceiling = zone && zone.extensions && zone.extensions.ceiling;
                return Number(ceiling && ceiling.heightMeters) > 0;
            }).map(zoneFloorPoints).filter(function (points) { return points.length >= 3; });
        }

        // The fill (lightPoolsRuntime.fillField): only under zone ceilings, from the pools of lamps inside them (the
        // user's choice, 2026-11-02), cut off at the ceilings' footprint by the mask (fillMask, built once per grid
        // and outlines). A layout without a zone ceiling gets none and no material is patched; when its last
        // ceiling goes, the maps are freed.
        function syncLightFill() {
            const fill = state.lightFill;
            const outlines = lightFillAvailable() ? ceilingOutlines() : [];
            if (!outlines.length) {
                clearLightFill();
                return 0;
            }
            const wanted = lightPoolsWanted() && Boolean(state.modelRoot);
            if (!wanted) {
                if (fill.uniforms) fill.uniforms.facilityFillStrength.value = 0;
                return 0;
            }
            if (!fill.uniforms) {
                fill.uniforms = { facilityFillMap: { value: null }, facilityFillMask: { value: null },
                    facilityFillChannels: { value: new THREE.Vector4(1, 0, 0, 0) },
                    facilityFillMatrix: { value: new THREE.Matrix4() }, facilityFillStrength: { value: 0 } };
            }
            const areas = state.lightAreas.resolved;
            const pools = [];
            const parts = [state.lightAreas.version, JSON.stringify(outlines)];
            state.lightPools.meshes.forEach(function (mesh) {
                if (!mesh || mesh.visible === false) return;
                parts.push(mesh.uuid);
                (state.lightAreas.pools.get(mesh) || []).forEach(function (pool) {
                    // General lighting indoors: an outdoor lamp's beam pool (L8) gives no fill.
                    if (pool.lamp) return;
                    if (lightAreasRuntime && !lightAreasRuntime.lit(areas, pool.x, pool.z)) return;
                    if (!outlines.some(function (outline) {
                        return lightPoolsRuntime.insideOutline(outline, pool.x, pool.z);
                    })) return;
                    pools.push({ x: pool.x, z: pool.z, radius: pool.radius, color: pool.color, lampY: pool.lampY });
                });
            });
            const key = parts.join('|');
            if (key !== fill.key) {
                const started = typeof performance !== 'undefined' ? performance.now() : Date.now();
                fill.key = key;
                if (fill.texture) fill.texture.dispose();
                fill.texture = null;
                fill.field = lightPoolsRuntime.fillField(pools);
                if (fill.field) {
                    fill.texture = halfFloatMap(fill.field.data, fill.field.cols, fill.field.rows, THREE.RGBAFormat);
                    const grid = fill.field;
                    const maskKey = JSON.stringify(outlines) + '|' + [grid.minX, grid.minZ, grid.cell, grid.cols,
                        grid.rows].join(',');
                    if (maskKey !== fill.maskKey) {
                        if (fill.maskTexture) fill.maskTexture.dispose();
                        fill.maskKey = maskKey;
                        fill.mask = lightPoolsRuntime.fillMask(grid, outlines);
                        const channels = fill.mask.channels || 1;
                        fill.maskTexture = halfFloatMap(fill.mask.data, fill.mask.cols, fill.mask.rows,
                            { 1: THREE.RedFormat, 2: THREE.RGFormat, 4: THREE.RGBAFormat }[channels]);
                        fill.uniforms.facilityFillChannels.value.set(1, channels > 1 ? 1 : 0, channels > 2 ? 1 : 0,
                            channels > 3 ? 1 : 0);
                    }
                }
                fill.uniforms.facilityFillMap.value = fill.texture;
                fill.uniforms.facilityFillMask.value = fill.field ? fill.maskTexture : null;
                fill.buildMs = Math.round(((typeof performance !== 'undefined' ? performance.now() : Date.now())
                    - started) * 10) / 10;
            }
            fill.uniforms.facilityFillStrength.value = fill.field ? 1 : 0;
            if (fill.field) {
                eachMaterial(state.modelRoot, patchFillMaterial);
                updateLightFillMatrix();
            }
            invalidate();
            return fill.field ? fill.field.pools : 0;
        }

        // A float map as a half-float texture, read with linear filtering.
        function halfFloatMap(values, cols, rows, format) {
            const data = new Uint16Array(values.length);
            for (let k = 0; k < data.length; k += 1) data[k] = THREE.DataUtils.toHalfFloat(values[k]);
            const texture = new THREE.DataTexture(data, cols, rows, format, THREE.HalfFloatType);
            texture.magFilter = THREE.LinearFilter;
            texture.minFilter = THREE.LinearFilter;
            texture.generateMipmaps = false;
            texture.needsUpdate = true;
            return texture;
        }

        function clearLightFill() {
            const fill = state.lightFill;
            if (fill.texture) fill.texture.dispose();
            if (fill.maskTexture) fill.maskTexture.dispose();
            fill.texture = null;
            fill.field = null;
            fill.key = '';
            fill.maskTexture = null;
            fill.mask = null;
            fill.maskKey = '';
            fill.buildMs = 0;
            if (fill.uniforms) {
                fill.uniforms.facilityFillMap.value = null;
                fill.uniforms.facilityFillMask.value = null;
                fill.uniforms.facilityFillStrength.value = 0;
            }
        }

        // World space to the fill map: x and z to 0..1 over the map, y the model's own height.
        function updateLightFillMatrix() {
            const fill = state.lightFill;
            if (!fill.field || !fill.uniforms || !fill.uniforms.facilityFillStrength.value) return;
            const field = fill.field;
            const width = field.cols * field.cell;
            const depth = field.rows * field.cell;
            const toMap = new THREE.Matrix4().set(1 / width, 0, 0, -field.minX / width, 0, 1, 0, 0,
                0, 0, 1 / depth, -field.minZ / depth, 0, 0, 0, 1);
            const toRoot = new THREE.Matrix4();
            if (state.modelRoot && state.modelRoot.matrixWorld) toRoot.copy(state.modelRoot.matrixWorld).invert();
            fill.uniforms.facilityFillMatrix.value.multiplyMatrices(toMap, toRoot);
        }

        // A lit material (not a glow, not unlit) gets the fill once; its own shader hook, if any, runs first.
        function patchFillMaterial(material) {
            const data = material && material.userData;
            if (!data || data.facilityFill || data.facilityGlow || data.facilityAuthoredGlow) return;
            if (!(material.isMeshStandardMaterial || material.isMeshLambertMaterial || material.isMeshPhongMaterial
                    || material.isMeshToonMaterial)) return;
            const fill = state.lightFill;
            const before = material.onBeforeCompile;
            const beforeKey = material.customProgramCacheKey;
            material.onBeforeCompile = function (shader, renderer) {
                if (typeof before === 'function') before.call(this, shader, renderer);
                Object.assign(shader.uniforms, fill.uniforms);
                lightPoolsRuntime.patchFillShader(shader);
            };
            material.customProgramCacheKey = function () {
                return (typeof beforeKey === 'function' ? beforeKey.call(this) : '') + '|facility-fill-1';
            };
            data.facilityFill = true;
            fill.patched += 1;
            material.needsUpdate = true;
        }

        function disposeLampLighting() {
            const spots = state.lampSpots;
            if (spots.root && spots.root.parent) spots.root.parent.remove(spots.root);
            spots.lights.forEach(function (light) { if (typeof light.dispose === 'function') light.dispose(); });
            spots.root = null;
            spots.lights = [];
            spots.lists.clear();
            spots.candidates = [];
            spots.key = '';
            spots.assigned = 0;
            clearLightFill();
        }

        function lampLightingDiagnostics() {
            const spots = state.lampSpots;
            const fill = state.lightFill;
            const lit = spots.root && spots.root.parent ? spots.lights.filter(function (light) {
                return light.intensity > 0;
            }) : [];
            return {
                spots: {
                    candidates: spots.candidates.length,
                    lights: spots.root && spots.root.parent ? spots.lights.length : 0,
                    lit: lit.length,
                    accents: spots.candidates.filter(function (spot) { return spot.kind === 'accent'; }).length,
                    pendants: spots.candidates.filter(function (spot) { return spot.kind === 'pendant'; }).length,
                },
                fill: {
                    on: Boolean(fill.uniforms && fill.uniforms.facilityFillStrength.value > 0),
                    pools: fill.field ? fill.field.pools : 0,
                    cells: fill.field ? fill.field.cols * fill.field.rows : 0,
                    patchedMaterials: fill.patched,
                    buildMs: fill.buildMs,
                },
            };
        }

        // ---- Lighting coverage (docs/facility-lighting-plan.md, CC3) --------------------------------------------
        // The workspace's estimate of one area, drawn on the floor (one mesh per lux band, then the dark spot
        // outlines) until it is cleared. Kept across a remount; not pickable; never saved.
        function setLightCoverage(view) {
            disposeLightCoverage();
            state.lightCoverage.view = view && Array.isArray(view.parts) ? view : null;
            syncLightCoverage();
            invalidate();
            return true;
        }

        function syncLightCoverage() {
            const coverage = state.lightCoverage;
            if (!coverage.view || !state.modelRoot || !lightCoverageRuntime || !THREE.BufferGeometry) return;
            if (!coverage.root) coverage.root = lightCoverageRuntime.sceneObjects(THREE, coverage.view, createContainer());
            if (coverage.root.parent !== state.modelRoot) state.modelRoot.add(coverage.root);
        }

        function disposeLightCoverage() {
            const root = state.lightCoverage.root;
            state.lightCoverage.root = null;
            if (!root) return;
            if (root.parent) root.parent.remove(root);
            (root.children || []).forEach(function (object) {
                if (object.geometry && typeof object.geometry.dispose === 'function') object.geometry.dispose();
                if (object.material && typeof object.material.dispose === 'function') object.material.dispose();
            });
        }

        // ---- General lights by area (docs/facility-lighting-plan.md, L7) ---------------------------------------
        // The scene may switch the general lighting on only inside some areas, or everywhere except inside them
        // (adjustments.lightAreas: floor areas or plan rectangles). General lighting is the lamps that throw floor
        // pools: a steady glow facing down, hung at least 3 m up; exit signs, beacons and displays stay on. Each
        // steady glow material gets a small on/off table, one texel per part per copy, that its shader reads, so a
        // batch of light rows stays one draw call. A table refills when its lamp is drawn after the areas, the
        // layout or the copies changed; switching areas rebuilds nothing. Pools under lamps that are off are blanked.
        function lightAreasActive() {
            return Boolean(lightAreasRuntime && lightPoolsRuntime && state.lightAreas.resolved);
        }

        // Resolve the scene's areas against the layout's floor areas; when they change, the tables refill.
        function syncLightAreas() {
            if (!lightAreasRuntime || !lightPoolsRuntime) return false;
            const value = state.viewportScene && state.viewportScene.lightAreas || null;
            const resolved = lightAreasRuntime.resolveAreas(value, currentLayout());
            const signature = JSON.stringify(resolved);
            if (signature === state.lightAreas.signature) return false;
            const wasActive = lightAreasActive();
            state.lightAreas.signature = signature;
            state.lightAreas.resolved = resolved;
            state.lightAreas.version += 1;
            // The first scene with areas adds the tables; later ones only refill them.
            if (resolved && !wasActive && state.modelRoot) syncLights(state.modelRoot);
            maskLightPools();
            invalidate();
            return true;
        }

        // The lamp numbers a glow geometry's shader reads (one per vertex), added once per geometry that has lamps.
        function lampPartsFor(geometry, duringFrame) {
            const parts = lightPoolsRuntime.lampPartsOf(geometry);
            if (parts && parts.lamps && geometry.attributes && !geometry.attributes.facilityLamp
                    && typeof geometry.setAttribute === 'function') {
                geometry.setAttribute('facilityLamp', new THREE.BufferAttribute(parts.vertexPart, 1));
                if (duringFrame) state.lightAreas.fresh.add(geometry);
            }
            return parts;
        }

        function createLampTable(width, height) {
            const table = new THREE.DataTexture(new Uint8Array(width * height).fill(255), width, height,
                THREE.RedFormat, THREE.UnsignedByteType);
            table.magFilter = THREE.NearestFilter;
            table.minFilter = THREE.NearestFilter;
            table.generateMipmaps = false;
            table.unpackAlignment = 1;  // rows of one byte per texel are not padded to 4
            table.needsUpdate = true;
            return table;
        }

        function addLampTable(material, mesh) {
            if (mesh && mesh.geometry) lampPartsFor(mesh.geometry);
            const masks = state.lightAreas.masks;
            if (masks.has(material) || typeof material.addEventListener !== 'function') return;
            const mask = {
                key: null, lamps: { on: 0, off: 0 },
                uniforms: {
                    facilityLampTable: { value: createLampTable(1, 1) }, facilityLampParts: { value: 1 },
                    facilityLampWidth: { value: 1 }, facilityLampMaskOn: { value: 0 },
                },
            };
            masks.set(material, mask);
            material.onBeforeCompile = function (shader) {
                Object.assign(shader.uniforms, mask.uniforms);
                mask.patched = lightAreasRuntime.patchGlowShader(shader,
                    lightAreasRuntime.toneMappingName(THREE, state.renderer && state.renderer.toneMapping));
            };
            material.customProgramCacheKey = function () {
                return 'facility-lamp-table:' + (state.renderer ? state.renderer.toneMapping : '');
            };
            material.onBeforeRender = drawLampTable;
            material.addEventListener('dispose', function () { mask.uniforms.facilityLampTable.value.dispose(); });
            material.needsUpdate = true;
        }

        // Before three.js draws an object with a lamp table: the table is used only while the scene has areas, the
        // lights are on and the object is not highlighted (a highlight shows whole), and it refills when stale.
        function drawLampTable(renderer, scene, camera, geometry, object) {
            const material = this;
            const mask = state.lightAreas.masks.get(material);
            if (!mask) return;
            const data = material.userData || {};
            mask.uniforms.facilityLampMaskOn.value = 0;
            if (!lightAreasActive() || !lightsOn() || data.facilityHighlightKind || !geometry) return;
            const parts = lampPartsFor(geometry, true);
            if (!parts || !parts.lamps) return;
            if (state.lightAreas.fresh.has(geometry)) {
                // Lamp numbers added during a frame reach the GPU with the next one: draw this one whole, ask for it.
                invalidate();
                return;
            }
            const instances = object.isInstancedMesh && object.instanceMatrix
                ? object.instanceMatrix.version + ':' + object.count : '-';
            const key = state.lightAreas.version + '|' + instances + '|' + object.matrixWorld.elements.join(',')
                + '|' + (state.modelRoot ? state.modelRoot.matrixWorld.elements.join(',') : '');
            if (mask.key !== key) {
                mask.key = key;
                fillLampTable(mask, object, parts);
            }
            mask.uniforms.facilityLampMaskOn.value = 1;
        }

        // Which lamps of an object are off: a lamp part on a copy that hangs 3 m up facing down (general lighting)
        // and whose centre the areas leave dark. Positions are in the layout's plan coordinates (the model root's).
        function lampStates(object, parts) {
            const copies = object.isInstancedMesh ? Math.max(0, object.count || 0) : 1;
            const off = new Uint8Array(parts.parts.length * Math.max(1, copies));
            const areas = state.lightAreas.resolved;
            const toRoot = new THREE.Matrix4();
            if (state.modelRoot && state.modelRoot.matrixWorld) toRoot.copy(state.modelRoot.matrixWorld).invert();
            const base = new THREE.Matrix4().multiplyMatrices(toRoot, object.matrixWorld);
            const instance = new THREE.Matrix4();
            const matrix = new THREE.Matrix4();
            const point = new THREE.Vector3();
            const down = new THREE.Vector3();
            let on = 0;
            let dark = 0;
            for (let copy = 0; copy < copies; copy += 1) {
                if (object.isInstancedMesh) {
                    object.getMatrixAt(copy, instance);
                    matrix.multiplyMatrices(base, instance);
                } else {
                    matrix.copy(base);
                }
                if (Math.abs(matrix.determinant()) < 1e-12) continue;  // a hidden, zero-scale copy
                down.set(0, -1, 0).transformDirection(matrix);
                if (down.y > lightPoolsRuntime.FACING_DOWN) continue;  // tipped over: not lighting the floor
                parts.parts.forEach(function (part, index) {
                    if (!part.lamp) return;
                    point.set(part.x, part.y, part.z).applyMatrix4(matrix);
                    if (point.y < lightPoolsRuntime.MIN_HEIGHT) return;  // the floor is y 0, as for the pools
                    if (lightAreasRuntime.lit(areas, point.x, point.z)) {
                        on += 1;
                        return;
                    }
                    off[copy * parts.parts.length + index] = 1;
                    dark += 1;
                });
            }
            return { copies: copies, off: off, on: on, dark: dark };
        }

        function fillLampTable(mask, object, parts) {
            const states = lampStates(object, parts);
            const size = lightAreasRuntime.tableSize(parts.parts.length, states.copies);
            let table = mask.uniforms.facilityLampTable.value;
            if (table.image.width !== size.width || table.image.height !== size.height) {
                table.dispose();
                table = createLampTable(size.width, size.height);
                mask.uniforms.facilityLampTable.value = table;
            }
            mask.uniforms.facilityLampParts.value = parts.parts.length;
            mask.uniforms.facilityLampWidth.value = size.width;
            const texels = table.image.data;
            texels.fill(255);
            states.off.forEach(function (value, index) { if (value) texels[index] = 0; });
            table.needsUpdate = true;
            mask.lamps = { on: states.on, off: states.dark };
        }

        // A pool whose lamp the areas leave dark is blanked (its color set to black adds nothing).
        function maskLightPools() {
            const areas = state.lightAreas.resolved;
            state.lightPools.meshes.forEach(function (mesh) {
                const list = mesh && state.lightAreas.pools.get(mesh);
                const color = mesh && mesh.geometry && mesh.geometry.attributes.color;
                const info = mesh && mesh.userData.facilityLightPools;
                if (!list || !color || !info || info.areasVersion === state.lightAreas.version) return;
                let dark = 0;
                list.forEach(function (pool, index) {
                    // A lamp is in an area when its centre is; an outdoor lamp's pool may lie away from it (L8).
                    const at = pool.lamp || pool;
                    const on = !lightAreasRuntime || lightAreasRuntime.lit(areas, at.x, at.z);
                    if (!on) dark += 1;
                    for (let corner = 0; corner < 4; corner += 1) {
                        color.setXYZ(index * 4 + corner, on ? pool.color.r : 0, on ? pool.color.g : 0, on ? pool.color.b : 0);
                    }
                });
                color.needsUpdate = true;
                info.areasVersion = state.lightAreas.version;
                info.dark = dark;
            });
            syncLightBeams();
            syncLightFill();
        }

        // ---- Outdoor light beams (docs/facility-lighting-plan.md, L8) ------------------------------------------
        // A lamp whose Lights finish has a beam angle shows a soft see-through cone from the lamp along its aim down
        // to the ground, where its pool lies: additive, writing no depth, fading toward the ground and its edge. All
        // cones are one instanced mesh among the pools, so they show when the pools do (Evening, lights on). A cone
        // follows its lamp's layer and L7's areas (decided at the lamp, as for its pool). At most LIGHT_BEAM_CAP per
        // layout; lamps beyond the cap keep their pools. Never picked; it lights nothing.
        function syncLightBeams() {
            const shared = state.lightPools;
            if (!shared.root || typeof THREE.InstancedMesh !== 'function' || typeof THREE.ShaderMaterial !== 'function'
                    || typeof lightPoolsRuntime.beamGeometry !== 'function') return 0;
            const beams = [];
            let total = 0;
            shared.meshes.forEach(function (mesh) {
                if (!mesh || !mesh.visible) return;
                (state.lightAreas.pools.get(mesh) || []).forEach(function (pool) {
                    if (!pool.aim || pool.low) return;  // a low light's pool (a bollard, a lantern) needs no beam
                    total += 1;
                    if (beams.length < LIGHT_BEAM_CAP) beams.push(pool);
                });
            });
            let beam = shared.beams;
            if (!beams.length && !beam) return 0;
            if (!beam) {
                beam = shared.beams = { geometry: lightPoolsRuntime.beamGeometry(THREE), material: null, mesh: null };
                beam.material = new THREE.ShaderMaterial({
                    name: 'FacilityLightBeams',
                    uniforms: { facilityBeamStrength: { value: LIGHT_BEAM_STRENGTH } },
                    vertexShader: lightPoolsRuntime.BEAM_VERTEX_SHADER,
                    fragmentShader: lightPoolsRuntime.BEAM_FRAGMENT_SHADER,
                    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
                    toneMapped: false, fog: false,
                });
                beam.material.userData.facilityLightBeams = true;
                beam.mesh = new THREE.InstancedMesh(beam.geometry, beam.material, LIGHT_BEAM_CAP);
                beam.mesh.name = 'FacilityLightBeams';
                beam.mesh.frustumCulled = false;
                beam.mesh.renderOrder = 3;
                beam.mesh.raycast = function () {};
            }
            if (beam.mesh.parent !== shared.root) shared.root.add(beam.mesh);
            const areas = state.lightAreas.resolved;
            const matrix = new THREE.Matrix4();
            const turn = new THREE.Quaternion();
            const down = new THREE.Vector3(0, -1, 0);
            const aim = new THREE.Vector3();
            const lamp = new THREE.Vector3();
            const size = new THREE.Vector3();
            const color = new THREE.Color();
            let lit = 0;
            beams.forEach(function (pool, index) {
                turn.setFromUnitVectors(down, aim.set(pool.aim.x, pool.aim.y, pool.aim.z));
                lamp.set(pool.lamp.x, pool.lamp.y, pool.lamp.z);
                size.set(pool.radius, pool.length, pool.radius);
                beam.mesh.setMatrixAt(index, matrix.compose(lamp, turn, size));
                const on = !lightAreasRuntime || lightAreasRuntime.lit(areas, pool.lamp.x, pool.lamp.z);
                if (on) lit += 1;
                beam.mesh.setColorAt(index, on ? color.copy(pool.color) : color.setRGB(0, 0, 0));
            });
            beam.mesh.count = beams.length;
            beam.mesh.instanceMatrix.needsUpdate = true;
            if (beam.mesh.instanceColor) beam.mesh.instanceColor.needsUpdate = true;
            beam.mesh.visible = beams.length > 0;
            beam.mesh.boundingBox = null;  // three keeps an instanced mesh's bounds until told they changed
            beam.mesh.boundingSphere = null;
            beam.mesh.userData.facilityLightBeams = { beams: beams.length, lit: lit, beyondCap: total - beams.length };
            invalidate();
            return lit;
        }

        function countLightBeams() {
            const pools = state.lightPools;
            const mesh = pools.beams && pools.beams.mesh;
            if (!mesh || !mesh.visible || !pools.root || !pools.root.visible || !pools.root.parent) return 0;
            return mesh.userData.facilityLightBeams.lit;
        }

        function lightAreasDiagnostics() {
            const areas = state.lightAreas.resolved;
            const result = {
                mode: areas ? areas.mode : null,
                areas: areas ? areas.shapes.map(function (shape) {
                    return shape.kind === 'floor' ? shape.surfaceId : 'rectangle';
                }) : [],
                missing: areas ? areas.missing.slice() : [],
                tables: 0, patched: 0, lamps: { on: 0, off: 0 }, pools: { on: 0, off: 0 },
            };
            eachMaterial(state.modelRoot, function (material, mesh) {
                const mask = state.lightAreas.masks.get(material);
                if (!mask) return;
                result.tables += 1;
                if (mask.patched) result.patched += 1;
                const parts = areas && mesh && mesh.geometry && lightPoolsRuntime.lampPartsOf(mesh.geometry);
                if (!parts || !parts.lamps) return;
                const states = lampStates(mesh, parts);  // counted now, whether or not drawn since
                result.lamps.on += states.on;
                result.lamps.off += states.dark;
            });
            if (state.lightPools.root && state.lightPools.root.visible) {
                state.lightPools.meshes.forEach(function (mesh) {
                    const info = mesh && mesh.visible && mesh.userData.facilityLightPools;
                    if (!info) return;
                    result.pools.off += info.dark || 0;
                    result.pools.on += info.pools - (info.dark || 0);
                });
            }
            return result;
        }

        function countLightPools() {
            const pools = state.lightPools;
            if (!pools.root || !pools.root.visible || !pools.root.parent) return 0;
            let count = 0;
            pools.meshes.forEach(function (mesh) { if (mesh && mesh.visible) count += mesh.userData.facilityLightPools.pools; });
            return count;
        }

        function disposeLightPools() {
            const pools = state.lightPools;
            Array.from(pools.meshes.keys()).forEach(dropLightPools);
            if (pools.root && pools.root.parent) pools.root.parent.remove(pools.root);
            pools.root = null;
            if (pools.material) pools.material.dispose();
            if (pools.texture) pools.texture.dispose();
            pools.material = null;
            pools.texture = null;
            if (pools.beams) {
                if (pools.beams.mesh.parent) pools.beams.mesh.parent.remove(pools.beams.mesh);
                if (typeof pools.beams.mesh.dispose === 'function') pools.beams.mesh.dispose();
                pools.beams.geometry.dispose();
                pools.beams.material.dispose();
                pools.beams = null;
            }
            pools.groundKey = '';
            disposeLampLighting();
        }

        // Glow halo (lighting L6): a scene adjustment (glowHalo), off by default, drawn only in a scene with floor
        // pools (Evening) and with the lights on. The frame is drawn as always, keeping its antialiasing and
        // per-material tone mapping, and every glow marks the stencil where it shows (markGlowStencil). Then:
        // the frame is copied; everything a glow did not mark is painted black and copied again; three's
        // UnrealBloomPass spreads that copy into a soft halo; the frame is drawn back and the halo added around the
        // glows. (EffectComposer would draw the scene off screen and tone-map everything at the end.)
        function bloomAvailable() {
            return Boolean(BloomPassType && FullScreenQuadType && CopyShaderSource && state.renderer
                && typeof state.renderer.copyFramebufferToTexture === 'function'
                && typeof state.renderer.getDrawingBufferSize === 'function'
                && typeof THREE.WebGLRenderTarget === 'function' && typeof THREE.ShaderMaterial === 'function'
                && typeof THREE.Vector2 === 'function' && THREE.UniformsUtils && THREE.NotEqualStencilFunc !== undefined
                && canvasHasStencil());
        }

        // A renderer made elsewhere (a pool, a test) may have no stencil: then there is no halo, rather than one
        // around every bright thing.
        function canvasHasStencil() {
            const bloom = state.bloom;
            if (bloom.stencil === null) {
                const gl = typeof state.renderer.getContext === 'function' ? state.renderer.getContext() : null;
                const attributes = gl && typeof gl.getContextAttributes === 'function' ? gl.getContextAttributes() : null;
                bloom.stencil = Boolean(attributes && attributes.stencil);
            }
            return bloom.stencil;
        }

        function bloomWanted() {
            const scene = state.viewportScene;
            return Boolean(scene && scene.glowHalo === true && scene.lightPools) && lightsOn() && !state.bloom.failed
                && bloomAvailable();
        }

        function bloomQuadMaterial(name, fragmentShader, extra) {
            return new THREE.ShaderMaterial(Object.assign({
                name: name,
                uniforms: THREE.UniformsUtils.clone(CopyShaderSource.uniforms),
                vertexShader: CopyShaderSource.vertexShader,
                fragmentShader: fragmentShader,
                depthTest: false,
                depthWrite: false,
            }, extra || {}));
        }

        function prepareBloom(width, height) {
            const bloom = state.bloom;
            if (!bloom.pass) {
                bloom.pass = new BloomPassType(new THREE.Vector2(width, height), BLOOM.strength, BLOOM.radius,
                    BLOOM.threshold);
                bloom.pass.highPassUniforms.smoothWidth.value = BLOOM.softness;
                bloom.frame = new THREE.WebGLRenderTarget(width, height, { depthBuffer: false });
                bloom.glow = new THREE.WebGLRenderTarget(width, height, { depthBuffer: false });
                bloom.frame.texture.generateMipmaps = false;
                bloom.glow.texture.generateMipmaps = false;
                const outsideGlows = {
                    stencilWrite: true, stencilRef: GLOW_STENCIL, stencilFunc: THREE.NotEqualStencilFunc,
                    stencilFail: THREE.KeepStencilOp, stencilZFail: THREE.KeepStencilOp, stencilZPass: THREE.KeepStencilOp,
                };
                bloom.copy = bloomQuadMaterial('FacilityBloomCopy', CopyShaderSource.fragmentShader);
                bloom.mask = bloomQuadMaterial('FacilityBloomMask',
                    'void main() { gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0); }', outsideGlows);
                bloom.add = bloomQuadMaterial('FacilityBloomAdd', CopyShaderSource.fragmentShader, Object.assign({
                    transparent: true, blending: THREE.AdditiveBlending, premultipliedAlpha: true,
                }, outsideGlows));
                bloom.quad = new FullScreenQuadType(bloom.copy);
            } else if (bloom.width === width && bloom.height === height) {
                return;
            } else {
                bloom.pass.setSize(width, height);
                bloom.frame.setSize(width, height);
                bloom.glow.setSize(width, height);
            }
            bloom.width = width;
            bloom.height = height;
            bloom.checked = false;
            // Allocate the targets on the GPU, so the frame can be copied into them.
            state.renderer.setRenderTarget(bloom.frame);
            state.renderer.setRenderTarget(bloom.glow);
            state.renderer.setRenderTarget(null);
        }

        function drawBloomQuad(material, texture) {
            const bloom = state.bloom;
            if (texture) material.uniforms.tDiffuse.value = texture;
            bloom.quad.material = material;
            bloom.quad.render(state.renderer);
        }

        function drawBloom() {
            const renderer = state.renderer;
            const bloom = state.bloom;
            // three resets its draw counts at each render call; the halo's passes add to the draw counts of the frame.
            const info = renderer.info || null;
            const autoReset = info ? info.autoReset : undefined;
            const autoClear = renderer.autoClear;
            if (info) info.autoReset = false;
            // The quads draw over the frame and read its stencil: nothing may clear the canvas in between.
            renderer.autoClear = false;
            try {
                const size = renderer.getDrawingBufferSize(bloom.size || (bloom.size = new THREE.Vector2()));
                prepareBloom(Math.max(1, Math.floor(size.x)), Math.max(1, Math.floor(size.y)));
                // The first copies after (re)sizing are checked: a failed copy would show as a black view.
                const gl = !bloom.checked && typeof renderer.getContext === 'function' ? renderer.getContext() : null;
                // WebGL keeps one flag per kind of error; clear any left by earlier calls.
                for (let i = 0; gl && i < 8 && gl.getError() !== gl.NO_ERROR; i += 1) { /* cleared */ }
                renderer.copyFramebufferToTexture(bloom.frame.texture);
                drawBloomQuad(bloom.mask, null);
                renderer.copyFramebufferToTexture(bloom.glow.texture);
                if (gl) {
                    const code = gl.getError();
                    if (code !== gl.NO_ERROR) throw new Error('The frame could not be copied (WebGL error ' + code + ').');
                    bloom.checked = true;
                }
                bloom.pass.render(renderer, null, bloom.glow, 0, false);
                renderer.setRenderTarget(null);
                drawBloomQuad(bloom.copy, bloom.frame.texture);
                drawBloomQuad(bloom.add, bloom.glow.texture);
                bloom.frames += 1;
            } catch (error) {
                bloom.failed = String(error && error.message || error);
                disposeBloom();
                warning('bloom_unavailable', 'The glow halo cannot be drawn here; the view is shown without it.',
                    bloom.failed);
                if (info) info.autoReset = autoReset;
                renderer.autoClear = autoClear;
                renderer.setRenderTarget(null);
                renderer.render(state.scene, state.camera);
            } finally {
                if (info) info.autoReset = autoReset;
                renderer.autoClear = autoClear;
            }
        }

        function disposeBloom() {
            const bloom = state.bloom;
            ['pass', 'frame', 'glow', 'copy', 'mask', 'add', 'quad'].forEach(function (key) {
                if (bloom[key]) bloom[key].dispose();
                bloom[key] = null;
            });
            bloom.width = 0;
            bloom.height = 0;
            bloom.checked = false;
        }

        function bloomDiagnostics() {
            const bloom = state.bloom;
            return {
                scene: Boolean(state.viewportScene && state.viewportScene.glowHalo === true),
                available: bloomAvailable(), drawn: bloomWanted(),
                size: bloom.pass ? [bloom.width, bloom.height] : null, frames: bloom.frames, failed: bloom.failed,
            };
        }

        function createFinishMaterialFor(resolved, scale) {
            const material = finishesRuntime.createFinishMaterial(THREE, resolved, {
                textures: finishTextureCache(), scale: scale, envMap: finishEnvironment(), envMapIntensity: finishReflection(),
            });
            syncFinishEnvironment(material);
            setMaterialLight(material, lightsOn());
            const fallback = material.userData && material.userData.fallback || [];
            if (fallback.indexOf('appearance_missing') >= 0) {
                warning('appearance_missing', 'A saved finish is not in the library; a neutral finish is shown.',
                    resolved.appearanceId);
            }
            material.wireframe = state.visualSettings.wireframe;
            return material;
        }

        function applyObjectFinish(object, material, mapping, geometryCache) {
            const replaced = finishesRuntime.applyFinishToObject(THREE, object, material, mapping, {
                geometryCache: geometryCache || state.finishGeometryCache,
                skip: function (candidate) { return isFinishProtectedMaterial(candidate); },
            });
            replaced.forEach(function (old) {
                (Array.isArray(old) ? old : [old]).forEach(function (item) {
                    // Copies made for this placement only; their textures stay with the source.
                    if (item && item !== material && typeof item.dispose === 'function') item.dispose();
                });
            });
        }

        // Library finishes on single parts. The part's own bounds choose the
        // grain axis, so a shelf board's grain follows the board.
        function partFinishContext(placement) {
            return {
                materialFor: function (override, mesh) {
                    const library = currentLibrary();
                    if (!library || !libraryRuntime || !finishesRuntime) return null;
                    const resolved = libraryRuntime.resolveAppearance(library, override, currentLayout());
                    if (!resolved) return null;
                    const material = createFinishMaterialFor(resolved, placement.transform.scale);
                    if (resolved.texture && mesh && mesh.geometry && mesh.matrixWorld) {
                        const mapping = finishesRuntime.mappingFor(THREE, mesh, resolved);
                        mesh.geometry = finishesRuntime.cachedFinishGeometry(THREE, state.finishGeometryCache,
                            mesh.geometry, mesh.matrixWorld, mapping);
                    }
                    return material;
                },
            };
        }

        function eachMaterial(root, visit) {
            if (!root || typeof root.traverse !== 'function') return;
            root.traverse(function (child) {
                const materials = Array.isArray(child.material) ? child.material : [child.material];
                materials.forEach(function (material) { if (material) visit(material, child); });
            });
        }

        function refreshFinishEnvironments() {
            eachMaterial(state.modelRoot, function (material) {
                if (!material.userData || material.userData.facilityAppearanceFinish !== true) return;
                syncFinishEnvironment(material);
            });
        }

        function syncViewportSceneFromLayout() {
            if (state.viewportScenePreview || !libraryRuntime) return false;
            const saved = libraryRuntime.layoutScene(currentLayout());
            const library = currentLibrary();
            if (saved && !library && facilityLibrary && typeof facilityLibrary.load === 'function') {
                facilityLibrary.load().then(function () {
                    if (!state.disposed) syncViewportSceneFromLayout();
                }).catch(function () {});
                return false;
            }
            const changed = applyViewportScene(libraryRuntime.resolveScene(library, saved));
            syncLightAreas();
            return changed;
        }

        // Apply a resolved scene: lighting levels, image-based lighting,
        // background and sun shadows. Equipment and the layout never change.
        function applyViewportScene(resolved) {
            const signature = JSON.stringify(resolved || null);
            if (signature === state.viewportSceneSignature) return false;
            state.viewportSceneSignature = signature;
            const lightsWereOn = lightsOn();
            state.viewportScene = resolved || null;
            if (lightsOn() !== lightsWereOn && state.modelRoot) syncLights(state.modelRoot);
            syncLightAreas();
            syncLightPools();
            const request = ++state.viewportSceneRequest;
            if (state.ambientLight) state.ambientLight.intensity = sceneRelativeSetting('ambient');
            if (state.directionalLight) state.directionalLight.intensity = sceneRelativeSetting('directional');
            if (state.renderer) state.renderer.toneMappingExposure = sceneRelativeSetting('exposure');
            const finish = function (environment, equirect) {
                if (request !== state.viewportSceneRequest || !state.scene) return;
                state.sceneEnvironment = environment || null;
                state.sceneEquirect = equirect || null;
                state.scene.environment = environment || null;
                if ('environmentIntensity' in state.scene) {
                    const intensity = Number(resolved && resolved.environmentIntensity);
                    state.scene.environmentIntensity = Number.isFinite(intensity) ? intensity : 1;
                }
                const rotation = (Number(resolved && resolved.environmentRotationDegrees) || 0) * Math.PI / 180;
                if (state.scene.environmentRotation && typeof state.scene.environmentRotation.set === 'function') {
                    state.scene.environmentRotation.set(0, rotation, 0);
                }
                if (state.scene.backgroundRotation && typeof state.scene.backgroundRotation.set === 'function') {
                    state.scene.backgroundRotation.set(0, rotation, 0);
                }
                // Rebuild the background only when the scene changes it.
                const backgroundKey = JSON.stringify([resolved ? resolved.background : 'theme',
                    equirect ? equirect.uuid || 'equirect' : null]);
                if (backgroundKey !== state.sceneBackgroundKey) {
                    state.sceneBackgroundKey = backgroundKey;
                    applySceneBackground();
                }
                applySceneShadows(Boolean(resolved && resolved.shadows));
                refreshFinishEnvironments();
                invalidate();
            };
            if (!resolved || !resolved.environment || !state.renderer) {
                finish(null, null);
                return true;
            }
            const loader = ensureEnvironmentLoader();
            if (!loader) {
                finish(null, null);
                return true;
            }
            if (resolved.environment === 'room' || !resolved.environmentUrl) {
                finish(roomEnvironment(), null);
                return true;
            }
            state.pendingLoads += 1;
            loader.load(resolved.environmentUrl).then(function (loaded) {
                finish(loaded.environment, loaded.equirect);
            }).catch(function () {
                warning('scene_environment_unavailable',
                    'The scene lighting file could not be loaded; neutral lighting is shown instead.', resolved.sceneId);
                finish(roomEnvironment(), null);
            }).finally(function () {
                state.pendingLoads = Math.max(0, state.pendingLoads - 1);
                invalidate();
            });
            return true;
        }

        function setShadowCasting(object, enabled) {
            if (!object || typeof object.traverse !== 'function') return;
            object.traverse(function (child) {
                if (!child.isMesh) return;
                child.castShadow = Boolean(enabled);
                if (enabled) child.receiveShadow = true;
            });
        }

        function fitShadowsToWorld() {
            if (!state.shadowsActive || !scenesRuntime || !state.directionalLight) return false;
            return scenesRuntime.fitSunShadow(THREE, state.directionalLight,
                configuredEnvironmentBounds() || state.worldBounds);
        }

        function applySceneShadows(enabled) {
            const renderer = state.renderer;
            const light = state.directionalLight;
            if (!renderer || !renderer.shadowMap || !light || !light.shadow) {
                state.shadowsActive = false;
                return false;
            }
            if (!state.sunDefaultPosition && light.position && typeof light.position.clone === 'function') {
                state.sunDefaultPosition = light.position.clone();
            }
            if (Boolean(enabled) === Boolean(state.shadowsActive)) {
                if (enabled) fitShadowsToWorld();
                return true;
            }
            state.shadowsActive = Boolean(enabled);
            renderer.shadowMap.enabled = state.shadowsActive;
            if (THREE.PCFSoftShadowMap !== undefined) renderer.shadowMap.type = THREE.PCFSoftShadowMap;
            light.castShadow = state.shadowsActive;
            if (state.shadowsActive) {
                fitShadowsToWorld();
            } else if (state.sunDefaultPosition) {
                light.position.copy(state.sunDefaultPosition);
                if (light.target && light.target.position) {
                    light.target.position.set(0, 0, 0);
                    light.target.updateMatrixWorld();
                }
            }
            state.renderGroups.forEach(function (record) { setShadowCasting(record.container, state.shadowsActive); });
            // Shadow sampling is compiled into each material's program.
            eachMaterial(state.modelRoot, function (material) { material.needsUpdate = true; });
            return true;
        }

        function equipmentDecalRows() {
            const extensions = currentLayout().extensions;
            const value = extensions && extensions.facilityEquipmentDecals;
            return value && Array.isArray(value.decals) ? value.decals : [];
        }

        function clearEquipmentDecals(keep) {
            Array.from(state.equipmentDecalObjects.entries()).forEach(function (pair) {
                const entry = pair[1];
                if (keep && !keep(entry)) return;
                entry.meshes.forEach(function (mesh) {
                    if (mesh.parent) mesh.parent.remove(mesh);
                    if (mesh.geometry) mesh.geometry.dispose();
                });
                if (entry.material) entry.material.dispose();
                state.equipmentDecalObjects.delete(pair[0]);
            });
        }

        function decalTexture(path) {
            if (state.decalTextures.has(path)) return state.decalTextures.get(path);
            const texture = new THREE.TextureLoader().load(path, function () { invalidate(); }, undefined, function () {
                warning('equipment_decal_image_missing', 'An equipment decal image could not be loaded.', path);
            });
            if (THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
            mirrorTextureForDisplay(texture);
            texture.userData = Object.assign({}, texture.userData, { facilitySharedTexture: true });
            state.decalTextures.set(path, texture);
            return texture;
        }

        function renderRecordFor(placementId) {
            return Array.from(state.renderGroups.values()).find(function (record) {
                return record.placementIds.indexOf(placementId) >= 0;
            }) || null;
        }

        // Project each saved decal onto a world-space copy of its placement's
        // current model. Runs again whenever that placement's model loads.
        function renderEquipmentDecals(placementIds) {
            if (!equipmentDecalsRuntime || !DecalGeometryType || !state.modelRoot
                    || typeof THREE.TextureLoader !== 'function') return 0;
            const only = Array.isArray(placementIds) ? new Set(placementIds) : null;
            clearEquipmentDecals(only ? function (entry) { return only.has(entry.placementId); } : null);
            let count = 0;
            equipmentDecalRows().forEach(function (row) {
                if (only && !only.has(row.placementId)) return;
                const placement = state.placements.find(function (item) { return item.placementId === row.placementId; });
                const record = placement && renderRecordFor(row.placementId);
                if (!placement || !record || !record.prototypeObject) return;
                const target = record.prototypeObject.clone(true);
                applyPlacementTransform(target, placement);
                const material = equipmentDecalsRuntime.decalMaterial(THREE, decalTexture(row.imagePath));
                let meshes = [];
                try {
                    meshes = equipmentDecalsRuntime.buildDecalMeshes(THREE, DecalGeometryType, target, row, material);
                } catch (error) {
                    reportError('equipment_decal_failed', error);
                }
                if (!meshes.length) {
                    material.dispose();
                    return;
                }
                meshes.forEach(function (mesh) {
                    mesh.visible = state.layerVisibility.assets !== false;
                    state.modelRoot.add(mesh);
                });
                state.equipmentDecalObjects.set(row.decalId, { placementId: row.placementId, meshes: meshes, material: material });
                count += 1;
            });
            invalidate();
            return count;
        }

        // Where a decal dropped at a screen point would sit, in the anchor form
        // the layout stores (the placement's own coordinates).
        function decalAnchorAt(input, rotationDegrees) {
            if (!equipmentDecalsRuntime) return null;
            const hit = pick(input);
            if (!hit || !hit.point || !hit.normal) return null;
            const placement = state.placements.find(function (item) { return item.placementId === hit.placementId; });
            if (!placement) return null;
            return {
                placementId: hit.placementId,
                anchor: equipmentDecalsRuntime.anchorFromHit(THREE, placementMatrix(placement), hit.point, hit.normal,
                    rotationDegrees),
            };
        }

        function findRenderedObject(record, placementId) {
            const children = record && record.container && record.container.children || [];
            return children.find(function (child) {
                return child && child.userData && child.userData.placementId === placementId;
            }) || null;
        }

        // Live preview: temporary copies with the candidate finish replace the
        // chosen placements on screen. Nothing is saved; clearing restores them.
        function previewFinish(spec) {
            clearFinishPreview();
            const outer = state.finishProjectionSink;
            const keys = new Set();
            state.finishProjectionSink = keys;
            try {
                return showFinishPreview(spec, keys);
            } finally {
                state.finishProjectionSink = outer;
            }
        }

        function showFinishPreview(spec, projections) {
            const request = spec && typeof spec === 'object' ? spec : {};
            const library = currentLibrary();
            if (!library || !libraryRuntime || !finishesRuntime || !state.modelRoot) return false;
            const resolved = libraryRuntime.resolveAppearance(library, request.appearance, currentLayout());
            if (!resolved) return false;
            const preview = { objects: [], hidden: [], projections: projections };
            (Array.isArray(request.placementIds) ? request.placementIds : []).forEach(function (placementId) {
                const record = renderRecordFor(placementId);
                const placement = state.placements.find(function (item) { return item.placementId === placementId; });
                if (!record || !placement || !record.prototypeObject) return;
                let object = null;
                const rendered = record.instanced ? null : findRenderedObject(record, placementId);
                if (rendered) {
                    object = cloneRenderable(rendered);
                    preview.hidden.push({ kind: 'object', object: rendered, visible: rendered.visible });
                    rendered.visible = false;
                } else {
                    object = cloneRenderable(record.prototypeObject);
                    const group = state.baseGroups.get(record.baseKey);
                    if (group && group.finish) {
                        applyObjectFinish(object, createFinishMaterialFor(group.finish, placement.transform.scale),
                            finishesRuntime.mappingFor(THREE, record.prototypeObject, group.finish));
                    }
                    applyPlacementTransform(object, placement);
                    record.pickObjects.forEach(function (mesh) {
                        const ids = state.instanceLookup.get(mesh) || [];
                        const index = ids.indexOf(placementId);
                        if (index < 0 || typeof mesh.getMatrixAt !== 'function') return;
                        const matrix = new THREE.Matrix4();
                        mesh.getMatrixAt(index, matrix);
                        preview.hidden.push({ kind: 'instance', mesh: mesh, index: index, matrix: matrix });
                        mesh.setMatrixAt(index, new THREE.Matrix4().makeScale(0, 0, 0));
                        if (mesh.instanceMatrix) mesh.instanceMatrix.needsUpdate = true;
                    });
                }
                // Show the finish itself, not the selection glow.
                eachMaterial(object, function (material) {
                    const original = material.userData && material.userData.facilitySelectionOriginal;
                    if (original && material.emissive && typeof material.emissive.setHex === 'function') {
                        material.emissive.setHex(finite(original.emissive, 0));
                        material.emissiveIntensity = original.emissiveIntensity;
                    }
                });
                const material = createFinishMaterialFor(resolved, placement.transform.scale);
                if (request.partKey && componentRuntime) {
                    object.updateMatrixWorld(true);
                    const rootInverse = new THREE.Matrix4().copy(object.matrixWorld).invert();
                    const slot = componentRuntime.slots(object).find(function (item) {
                        return item.key === request.partKey || item.legacyKey === request.partKey;
                    });
                    const sourceSlot = componentRuntime.slots(record.prototypeObject).find(function (item) {
                        return item.key === request.partKey || item.legacyKey === request.partKey;
                    });
                    if (slot) {
                        if (resolved.texture && sourceSlot) {
                            const relative = new THREE.Matrix4().multiplyMatrices(rootInverse, slot.node.matrixWorld);
                            slot.node.geometry = finishesRuntime.cachedFinishGeometry(THREE, state.finishGeometryCache,
                                slot.node.geometry, relative, finishesRuntime.mappingFor(THREE, sourceSlot.node, resolved));
                        }
                        if (typeof componentRuntime.keepDepthOffset === 'function') {
                            componentRuntime.keepDepthOffset(slot.material, material);
                        }
                        slot.node.material = material;
                    }
                } else {
                    applyObjectFinish(object, material, finishesRuntime.mappingFor(THREE, record.prototypeObject, resolved));
                }
                object.userData.facilityFinishPreview = true;
                // The original copy is hidden while previewing, so the preview
                // stands in for it when picking (selection, part pick, decals).
                object.userData.facilityPreviewPlacementId = placementId;
                state.modelRoot.add(object);
                preview.objects.push(object);
            });
            state.finishPreview = preview;
            invalidate();
            return preview.objects.length > 0;
        }

        function clearFinishPreview() {
            const preview = state.finishPreview;
            if (!preview) return false;
            state.finishPreview = null;
            preview.hidden.forEach(function (item) {
                if (item.kind === 'object') {
                    item.object.visible = item.visible;
                } else if (item.mesh && typeof item.mesh.setMatrixAt === 'function') {
                    item.mesh.setMatrixAt(item.index, item.matrix);
                    if (item.mesh.instanceMatrix) item.mesh.instanceMatrix.needsUpdate = true;
                }
            });
            const seenMaterials = new Set(), seenTextures = new Set();
            preview.objects.forEach(function (object) {
                if (object.parent) object.parent.remove(object);
                eachMaterial(object, function (material) {
                    if (material.userData && material.userData.facilityAppearanceFinish) {
                        disposeMaterial(material, seenMaterials, seenTextures);
                    } else if (!seenMaterials.has(material) && typeof material.dispose === 'function') {
                        // A per-preview copy; its textures belong to the original.
                        seenMaterials.add(material);
                        material.dispose();
                    }
                });
            });
            // Its projections that no group uses go with it: only its objects drew them.
            (preview.projections || []).forEach(function (key) {
                if (state.finishProjectionUsers.has(key)) return;
                const geometry = Map.prototype.get.call(state.finishGeometryCache, key);
                state.finishGeometryCache.delete(key);
                if (geometry && typeof geometry.dispose === 'function') geometry.dispose();
            });
            invalidate();
            return true;
        }

        function previewViewportScene(value) {
            const library = currentLibrary();
            if (!library || !libraryRuntime) return false;
            state.viewportScenePreview = true;
            applyViewportScene(libraryRuntime.resolveScene(library, value));
            return true;
        }

        function clearViewportScenePreview() {
            if (!state.viewportScenePreview) return false;
            state.viewportScenePreview = false;
            syncViewportSceneFromLayout();
            return true;
        }

        function getViewportScene() {
            return state.viewportScene ? JSON.parse(JSON.stringify(state.viewportScene)) : null;
        }

        function finishDiagnostics() {
            let finishGroups = 0;
            state.baseGroups.forEach(function (group) { if (group.finish) finishGroups += 1; });
            return {
                libraryLoaded: Boolean(currentLibrary()),
                finishGroups: finishGroups,
                projectedGeometries: state.finishGeometryCache.size,
                textures: state.finishTextures ? state.finishTextures.stats() : { images: 0, ready: 0, failed: 0, uses: 0 },
                previewObjects: state.finishPreview ? state.finishPreview.objects.length : 0,
                sceneId: state.viewportScene ? state.viewportScene.sceneId : null,
                sceneEnvironment: Boolean(state.scene && state.scene.environment),
                shadows: Boolean(state.shadowsActive),
                lights: lightsOn(),
                lightPools: countLightPools(),
                lightBeams: countLightBeams(),
                lampLighting: lampLightingDiagnostics(),
                lightPatterns: {
                    inView: state.lightPatterns.inView,
                    timer: state.lightPatterns.timer !== null,
                    redraws: state.lightPatterns.redraws,
                    reducedMotion: Boolean(state.motion.prefersReducedMotion),
                },
                lightAreas: lightAreasDiagnostics(),
                bloom: bloomDiagnostics(),
                equipmentDecals: state.equipmentDecalObjects.size,
            };
        }

        async function getComponentMaterials(placementId) {
            const group=Array.from(state.baseGroups.values()).find(g=>g.placements.some(p=>p.placementId===placementId));
            if(!group)throw new Error('The selected model is not loaded.');
            // Read only from the view, the scene and the model it was asked of (final round 3).
            const token=sceneToken({group});
            const changed=()=>new Error('The model changed while it loaded; select it again.');
            await resolveBaseGroup(group,state.sceneGeneration,state.abortController?.signal);
            if(!tokenCurrent(token))throw changed();
            if(group.deferredVisual)await loadDeferredGroup(group,'component_materials');
            if(!tokenCurrent(token))throw changed();
            const record=state.renderGroups.get(baseGroupKey(group));
            if(!record || !['overview','detail'].includes(record.representation))throw new Error('Load the CAD model before editing its components.');
            return {representation:record.representation,slots:componentRuntime.slots(record.prototypeObject).map(item=>({
                key:item.key,legacyKey:item.legacyKey,label:item.label,color:'#'+item.material.color.getHexString(),
                roughness:finite(item.material.roughness,.6),metalness:finite(item.material.metalness,0)}))};
        }

        function highlightComponent(placementId,key) {
            if(state.componentHighlight){
                state.componentHighlight.removeFromParent();state.componentHighlight.geometry.dispose();state.componentHighlight.material.dispose();state.componentHighlight=null;
            }
            if(placementId && THREE.Box3Helper){
                const record=Array.from(state.renderGroups.values()).find(r=>r.placementIds.includes(placementId));
                const placement=state.placements.find(p=>p.placementId===placementId);
                if(record&&placement){
                    const object=record.prototypeObject.clone(true);applyPlacementTransform(object,placement);object.updateMatrixWorld(true);
                    const slot=componentRuntime.slots(object).find(v=>v.key===key);
                    if(slot){const helper=new THREE.Box3Helper(new THREE.Box3().setFromObject(slot.node),0xc99b39);helper.material.depthTest=false;helper.renderOrder=1000;state.modelRoot.add(helper);state.componentHighlight=helper;}
                }
            }
            invalidate();
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
            const screenX = ((clientX - finite(rect.left, 0)) / width) * 2 - 1;
            return {
                // The displayed canvas is mirrored; the render is not.
                x: state.displayMirror ? -screenX : screenX,
                y: -((clientY - finite(rect.top, 0)) / height) * 2 + 1,
            };
        }

        function placementIdFromObject(object) {
            let cursor = object;
            while (cursor) {
                if (cursor.userData && cursor.userData.placementId) {
                    return cursor.userData.placementId;
                }
                if (cursor.userData && cursor.userData.facilityPreviewPlacementId) {
                    return cursor.userData.facilityPreviewPlacementId;
                }
                cursor = cursor.parent;
            }
            return null;
        }

        // Instanced and merged copies have no per-part meshes, so the part
        // under the current ray is found on a copy of the placement's model.
        function partKeyAlongRay(placementId) {
            const record = renderRecordFor(placementId);
            const placement = state.placements.find(function (item) { return item.placementId === placementId; });
            if (!record || !record.prototypeObject || !placement || !state.raycaster
                    || typeof state.raycaster.intersectObject !== 'function') return null;
            const probe = record.prototypeObject.clone(true);
            applyPlacementTransform(probe, placement);
            if (typeof probe.updateMatrixWorld === 'function') probe.updateMatrixWorld(true);
            const hits = state.raycaster.intersectObject(probe, true) || [];
            for (let index = 0; index < hits.length; index += 1) {
                const key = hits[index].object && hits[index].object.userData
                    && hits[index].object.userData.facilityPartKey;
                if (key) return key;
            }
            return null;
        }

        // A release ends a click when its press was on the view with the same pointer and the primary button, and
        // the pointer moved at most CLICK_SLOP_PIXELS between them.
        function wasClick(press, event) {
            if (!press || !event) return false;
            if (event.button !== undefined && event.button !== 0) return false;
            if (press.pointerId !== undefined && event.pointerId !== undefined
                    && press.pointerId !== event.pointerId) return false;
            const dx = finite(event.clientX, press.x) - press.x;
            const dy = finite(event.clientY, press.y) - press.y;
            return dx * dx + dy * dy <= CLICK_SLOP_PIXELS * CLICK_SLOP_PIXELS;
        }

        function pick(input) {
            if (state.degraded || !state.raycaster || !state.camera) return null;
            const pointer = normalizedPointer(input);
            if (!pointer) return null;
            const vector = typeof THREE.Vector2 === 'function'
                ? new THREE.Vector2(pointer.x, pointer.y) : pointer;
            state.raycaster.setFromCamera(vector, state.camera);
            const previousFar = state.raycaster.far;
            const maximumDistance = Number(input && input.maximumDistance);
            let hits;
            try {
                if (Number.isFinite(maximumDistance) && maximumDistance > 0) {
                    state.raycaster.far = maximumDistance;
                }
                const previews = state.finishPreview ? state.finishPreview.objects : [];
                hits = state.raycaster.intersectObjects(previews.length
                    ? state.pickObjects.concat(previews) : state.pickObjects, true) || [];
            } finally {
                state.raycaster.far = previousFar;
            }
            for (let index = 0; index < hits.length; index += 1) {
                const hit = hits[index];
                let ancestor = hit.object, hidden = false;
                while (ancestor) { if (ancestor.visible === false) { hidden = true; break; } ancestor = ancestor.parent; }
                if (hidden) continue;
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
                const result = {
                    placementId: placementId,
                    instanceId: instanceId,
                    point: hit.point ? {
                        x: finite(hit.point.x, 0),
                        y: finite(hit.point.y, 0),
                        z: finite(hit.point.z, 0),
                    } : null,
                };
                // Surface normal and stable part key: decals sit on the surface
                // under the cursor and part finishes target the part that was hit.
                if (hit.face && hit.face.normal && typeof hit.face.normal.clone === 'function'
                        && hit.object && hit.object.matrixWorld && typeof THREE.Matrix4 === 'function') {
                    const world = new THREE.Matrix4().copy(hit.object.matrixWorld);
                    if (instanceId !== null && typeof hit.object.getMatrixAt === 'function') {
                        const instanceMatrix = new THREE.Matrix4();
                        hit.object.getMatrixAt(instanceId, instanceMatrix);
                        world.multiply(instanceMatrix);
                    }
                    const normal = hit.face.normal.clone().transformDirection(world);
                    result.normal = { x: finite(normal.x, 0), y: finite(normal.y, 1), z: finite(normal.z, 0) };
                }
                const partKey = hit.object && hit.object.userData && hit.object.userData.facilityPartKey;
                if (partKey && instanceId === null) result.partKey = partKey;
                else if (input && input.parts === true) result.partKey = partKeyAlongRay(placementId);
                return result;
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
            const eye = state.walkthrough.position
                ? { x: state.walkthrough.position.x,
                    y: state.walkthrough.position.y + walkthroughSettings.eyeHeight,
                    z: state.walkthrough.position.z } : state.camera.position;
            const cameraOffset = Math.hypot(state.camera.position.x - eye.x,
                state.camera.position.y - eye.y, state.camera.position.z - eye.z);
            const hit = pick({ normalized: true, x: 0, y: 0,
                maximumDistance: walkthroughSettings.contextRadius + cameraOffset });
            if (!hit || !hit.placementId) return null;
            const placement = state.placements.find(function (record) {
                return record.placementId === hit.placementId;
            });
            if (!placement || !placement.transform
                    || !placement.transform.position) return null;
            const point = hit.point || placement.transform.position;
            const dx = finite(point.x, 0) - finite(eye.x, 0);
            const dy = finite(point.y, 0) - finite(eye.y, 0);
            const dz = finite(point.z, 0) - finite(eye.z, 0);
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
            const previousId = state.walkthroughContextFocus && state.walkthroughContextFocus.placementId;
            state.walkthroughContextFocus = next;
            if (previousId !== (next && next.placementId)) applySelection(true);
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

        function updateWalkthroughContextFocus(timestamp) {
            const walk = state.walkthrough;
            if (walk.active && (walkthroughHasActivity() || state.navigationInteracting) && Number.isFinite(timestamp)) {
                if (walk.lastContextTime !== null && timestamp >= walk.lastContextTime
                        && timestamp - walk.lastContextTime < 100) return state.walkthroughContextFocus;
                walk.lastContextTime = timestamp;
            }
            if (walk.active) walk.performance.contextQueries += 1;
            return setWalkthroughContextFocus(walkthroughContextCandidate());
        }

        function getWalkthroughContextFocus() {
            // Explicit user actions need a fresh hit, not the throttled hover observation.
            updateWalkthroughContextFocus();
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
            if (groundRuntime && groundRuntime.surfaces(state.currentInput && state.currentInput.layout)) {
                const floors = state.environmentRoot.children.filter(object => object.userData && object.userData.groundSurfaceId);
                const hits = state.raycaster.intersectObjects(floors, false);
                return hits.length ? {x:hits[0].point.x, y:hits[0].point.y, z:hits[0].point.z} : null;
            }
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
            const screenX = state.displayMirror ? -point.x : point.x;
            const clientX = finite(rect.left, 0) + (screenX + 1) * width / 2;
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
                sourcePrototypeMeshCount: record.sourcePrototypeMeshCount,
                renderedLightCount: record.renderedLightCount,
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
                floorMarkingCount: state.floorMarkingCount,
                zoneMarkingCount: state.zoneObjects.length,
                zoneCeilingCount: state.zoneCeilingObjects.length,
                zoneCeilings: state.zoneCeilingObjects.map(zoneCeilingDiagnostics),
                zoneRoofCount: state.zoneRoofObjects.length,
                zoneRoofs: state.zoneRoofObjects.map(zoneRoofDiagnostics),
                appearanceLibrary: finishDiagnostics(),
                perimeterWallCount: state.wallObjects.length,
                visiblePerimeterWallCount: state.wallObjects.filter(object => object.visible).length,
                columnCount: state.columnObjects.length,
                visibleColumnCount: state.columnObjects.filter(object => object.visible).length,
                exteriorFinishObjectCount: state.wallFinishObjects.length,
                exteriorArtwork: state.wallArtworkLoads.map(function (record) {
                    const object = state.wallFinishObjects.find(item =>
                        item.userData && item.userData.exteriorArtwork === record);
                    let visible = Boolean(object);
                    for (let node = object; node; node = node.parent) {
                        if (node.visible === false) visible = false;
                    }
                    return Object.assign({}, record, {visible});
                }),
                legacyWallPlacementCount: Array.from(state.renderGroups.values())
                    .filter(record => record.visibilityLayer === 'walls')
                    .reduce((count, record) => count + record.placementIds.length, 0),
                visibleLegacyWallPlacementCount: Array.from(state.renderGroups.values())
                    .filter(record => record.visibilityLayer === 'walls' && record.container.visible)
                    .reduce((count, record) => count + record.placementIds.length, 0),
                // Placements per model layer: [shown, total].
                layerPlacementCounts: Array.from(state.renderGroups.values()).reduce(function (counts, record) {
                    const row = counts[record.visibilityLayer] || (counts[record.visibilityLayer] = [0, 0]);
                    if (record.container.visible) row[0] += record.placementIds.length;
                    row[1] += record.placementIds.length;
                    return counts;
                }, {}),
                routeCount: state.routeObjects.length,
                assetGroupCount: state.baseGroups.size,
                representationGroups: groups,
                selectedPlacementIds: Array.from(state.selectedIds).sort(),
                walkthroughContextFocus: state.walkthroughContextFocus
                    ? Object.assign({}, state.walkthroughContextFocus) : null,
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
                site: { areaIds: state.siteAreaObjects.filter(object => object.userData.facilitySiteArea)
                    .map(object => object.userData.facilitySiteArea), groundLoaded: Boolean(state.siteGround) },
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
            disposeLightCoverage();
            state.lightCoverage.view = null;
            if (!state.mounted && !state.renderer && !state.canvas) {
                // Parked or never mounted: nothing to tear down, but the inputs go all the same.
                abortLoading();
                state.disposed = true;
                state.reloadOnResume = false;
                forgetScene();
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
            park: park,
            resume: resume,
            setScene: setScene,
            setSelection: setSelection,
            getComponentMaterials: getComponentMaterials,
            highlightComponent: highlightComponent,
            setLightCoverage: setLightCoverage,
            previewFinish: previewFinish,
            clearFinishPreview: clearFinishPreview,
            previewViewportScene: previewViewportScene,
            clearViewportScenePreview: clearViewportScenePreview,
            getViewportScene: getViewportScene,
            decalAnchorAt: decalAnchorAt,
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
            setWalkthroughCameraMode: setWalkthroughCameraMode,
            lookWalkthroughAt: lookWalkthroughAt,
            setWalkthroughCameraSettings: setWalkthroughCameraSettings,
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
            loadVisibleDetail: loadVisibleDetail,
            sceneState: sceneState,
            navigateWalkthroughToPlacement: navigateWalkthroughToPlacement,
            navigateWalkthroughToPoint: navigateWalkthroughToPoint,
            cancelWalkthroughNavigation: cancelWalkthroughNavigation,
            getCameraView: getCameraView,
            applyCameraView: applyCameraView,
            zoomBy: zoomBy,
            setGridVisible: setGridVisible,
            setLayerVisibility: setLayerVisibility,
            getLayerVisibility: getLayerVisibility,
            setWallPiecesHidden: setWallPiecesHidden,
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
        mirrorModelFileGeometry: mirrorModelFileGeometry,
        resolveMultiLevelWalkthroughMovement: resolveMultiLevelWalkthroughMovement,
        resolveWalkthroughPostureChange: resolveWalkthroughPostureChange,
        resolveWalkthroughMovement: resolveWalkthroughMovement,
        walkthroughSweptObstacles: walkthroughSweptObstacles,
        resolveWalkthroughCamera: resolveWalkthroughCamera,
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
