(function (root, factory) {
    'use strict';

    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityWorkspace = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    'use strict';

    const API_VERSION = 1;
    const wallsRuntime = typeof module === 'object' && module.exports
        ? require('./facility_layout_walls.js') : root.InspectorProFacilityWalls;
    const decalsRuntime = typeof module === 'object' && module.exports
        ? require('./facility_layout_decals.js') : root.InspectorProFacilityDecals;
    const componentMaterialsRuntime = typeof module === 'object' && module.exports
        ? require('./facility_layout_component_materials.js') : root.InspectorProFacilityComponentMaterials;
    const authoringDialogs = typeof module === 'object' && module.exports
        ? require('./facility_layout_authoring_dialog.js') : root.InspectorProFacilityAuthoringDialog;
    const interiorWallsRuntime = typeof module === 'object' && module.exports
        ? require('./facility_layout_interior_walls.js') : root.InspectorProFacilityInteriorWalls;
    const floorSurfacesRuntime = typeof module === 'object' && module.exports
        ? require('./facility_layout_floor_surfaces.js') : root.InspectorProFacilityFloorSurfaces;
    const replaceAssetRuntime = typeof module === 'object' && module.exports
        ? require('./facility_layout_replace_asset.js') : root.InspectorProFacilityReplaceAsset;
    const NAVIGATION_ACTIVITY_MAXIMUM_ACTORS = 64;
    const generationView = typeof module === 'object' && module.exports
        ? require('./facility_layout_generation_view.js') : root.InspectorProGenerationPlanningView;
    const siteRuntime = typeof module === 'object' && module.exports
        ? require('./facility_layout_site.js') : root.InspectorProFacilitySite;
    const ASSET_MIME = 'application/x-inspectorpro-facility-asset';
    const DEFAULT_GRID_SIZE = 0.5;
    const DEFAULT_DUPLICATE_OFFSET = Object.freeze({ x: 1, y: 0, z: 1 });
    const DUPLICATE_DRAG_THRESHOLD_PX = 4;
    const DEFAULT_ASSET_CLEARANCE = 0.75;
    const MAX_ASSET_BATCH_ITEMS = 48;
    const METERS_TO_FEET = 3.280839895;
    const PLAN_SETTINGS_EXTENSION_KEY = 'facilityPlan';
    const DEFAULT_PLAN_WIDTH_METERS = 40;
    const DEFAULT_PLAN_DEPTH_METERS = 30;
    const DEFAULT_PLAN_GRID_METERS = 1;
    const PLAN_SCALE_TARGET_PIXELS = 130;
    const PLAN_VIEW_PREFERENCE_PREFIX = 'inspectorpro.facility-plan-view.';
    const THREE_VIEWPOINT_PREFIX = 'inspectorpro.facility-viewpoints.';
    const MAX_THREE_VIEWPOINTS = 20;
    const SCALE_DISTANCES = Object.freeze({
        m: [0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100],
        ft: [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500],
    });
    const VIEWPORT_ICON_ROOT =
        '/static/assets/facility-layout-ribbon-icons/svg/';
    const VIEW_ORIENTATION_ICON_ROOT =
        '/static/assets/view-toolbar-icons/';
    const THREE_VIEW_ORIENTATIONS = Object.freeze([
        Object.freeze({ key: 'front', label: 'Front' }),
        Object.freeze({ key: 'top', label: 'Top' }),
        Object.freeze({ key: 'right', label: 'Right' }),
        Object.freeze({ key: 'iso', label: 'Iso' }),
    ]);
    const DEFAULT_THREE_VISUAL_SETTINGS = Object.freeze({
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
    const DEFAULT_LAYER_VISIBILITY = Object.freeze({
        zones: true,
        cells: true,
        routes: true,
        markings: true,
        assets: true,
        walls: true,
    });
    const TOOL_MODES = Object.freeze([
        'select',
        'pan',
        'rectangle-zone',
        'polygon-zone',
        'aisle',
        'floor-marking',
        'motion-path',
    ]);
    const ZONE_PURPOSE_OPTIONS = Object.freeze([
        Object.freeze({ value: 'workcell', label: 'Department / equipment area' }),
        Object.freeze({ value: 'receiving', label: 'Receiving' }),
        Object.freeze({ value: 'storage', label: 'Storage' }),
        Object.freeze({ value: 'staging', label: 'Staging' }),
        Object.freeze({ value: 'shipping', label: 'Shipping' }),
        Object.freeze({ value: 'inspection', label: 'Inspection' }),
        Object.freeze({ value: 'dock', label: 'Dock' }),
        Object.freeze({ value: 'charging', label: 'Charging' }),
        Object.freeze({ value: 'service', label: 'Service clearance - no equipment' }),
        Object.freeze({ value: 'operator', label: 'Operator clearance - no equipment' }),
        Object.freeze({ value: 'safety', label: 'Safety zone - no equipment' }),
        Object.freeze({ value: 'exclusion', label: 'Exclusion zone - no equipment' }),
        Object.freeze({ value: 'utility', label: 'Utility corridor - no equipment' }),
        Object.freeze({ value: 'aisle', label: 'Aisle - no equipment' }),
    ]);
    const VIEW_MODES = Object.freeze(['plan', '3d', 'site']);
    const WALKTHROUGH_CONTEXT_MODES = Object.freeze([
        Object.freeze({ key: 'production', label: 'Production' }),
        Object.freeze({ key: 'maintenance', label: 'Maintenance' }),
        Object.freeze({ key: 'safety', label: 'Safety' }),
        Object.freeze({ key: 'training', label: 'Training' }),
        Object.freeze({ key: 'quality', label: 'Quality' }),
    ]);
    const WALKTHROUGH_CONTEXT_FIELDS = Object.freeze({
        production: Object.freeze([
            ['status', 'Status'],
            ['processStep', 'Process step'],
            ['cycleTime', 'Cycle time'],
            ['taktTime', 'Takt time'],
            ['throughput', 'Throughput'],
            ['capacity', 'Capacity'],
            ['batchSize', 'Batch size'],
            ['operator', 'Operator'],
            ['shift', 'Shift'],
            ['upstream', 'Upstream'],
            ['downstream', 'Downstream'],
        ]),
        maintenance: Object.freeze([
            ['status', 'Status'],
            ['lastMaintenance', 'Last maintenance'],
            ['nextMaintenance', 'Next maintenance'],
            ['maintenanceNotes', 'Maintenance notes'],
            ['accessConstraints', 'Access constraints'],
            ['serviceReference', 'Service reference'],
        ]),
        safety: Object.freeze([
            ['ppe', 'Required PPE'],
            ['safetyNotes', 'Safety notes'],
            ['accessConstraints', 'Access constraints'],
            ['clearanceRequirements', 'Clearance requirements'],
            ['lockoutReference', 'Lockout reference'],
        ]),
        training: Object.freeze([
            ['purpose', 'Purpose'],
            ['processStep', 'Process step'],
            ['workInstructionRef', 'Work instruction'],
            ['trainingNotes', 'Training notes'],
            ['capabilities', 'Capabilities'],
        ]),
        quality: Object.freeze([
            ['inspectionRequirements', 'Inspection requirements'],
            ['qualityNotes', 'Quality notes'],
            ['commonDefects', 'Common defects'],
            ['qualityReference', 'Quality reference'],
        ]),
    });
    const RECORDING_PRESENTATION_MODES = Object.freeze([
        Object.freeze({ key: 'clean', label: 'Clean presentation' }),
        Object.freeze({ key: 'training', label: 'Training / demo' }),
    ]);
    const RECORDING_RESOLUTIONS = Object.freeze([
        Object.freeze({ key: 'current', label: 'Current viewport' }),
        Object.freeze({ key: '720p', label: '720p' }),
        Object.freeze({ key: '1080p', label: '1080p' }),
    ]);
    const PRECISION_MODES = Object.freeze([
        'align', 'distribute', 'relative', 'distance', 'offset',
    ]);
    const PATTERN_MODES = Object.freeze([
        'linear-pattern', 'circular-pattern', 'perimeter-pattern',
        'cell-layout', 'vertical-stack', 'surface-stack', 'mirror', 'swap',
    ]);
    const CELL_LAYOUT_PRESETS = Object.freeze([
        Object.freeze({ value: 'line', label: 'Straight / I-line' }),
        Object.freeze({ value: 'l', label: 'L-shaped cell' }),
        Object.freeze({ value: 'u', label: 'U-shaped cell' }),
        Object.freeze({ value: 'grid', label: 'Grid' }),
        Object.freeze({ value: 'parallel', label: 'Parallel rows' }),
        Object.freeze({ value: 'serpentine', label: 'Serpentine flow' }),
        Object.freeze({ value: 'loop', label: 'Loop / closed cell' }),
        Object.freeze({ value: 'spine', label: 'Spine and branch' }),
        Object.freeze({ value: 'herringbone', label: 'Herringbone' }),
        Object.freeze({ value: 'cluster', label: 'Cluster' }),
    ]);
    const SELECTION_TOOLBAR_COMMANDS = Object.freeze({
        align: Object.freeze({ label: 'Align', icon: 'bounding-box' }),
        distribute: Object.freeze({ label: 'Distribute', icon: 'grid-four' }),
        relative: Object.freeze({ label: 'Relative position', icon: 'sphere' }),
        distance: Object.freeze({ label: 'Measure or set distance', icon: 'corners-out' }),
        offset: Object.freeze({ label: 'Offset', icon: 'cursor-click' }),
        rotate: Object.freeze({ label: 'Rotate 90 degrees', icon: 'arrow-clockwise' }),
        duplicate: Object.freeze({ label: 'Duplicate', icon: 'copy' }),
        'vertical-stack': Object.freeze({ label: 'Stack', icon: 'stack' }),
        'surface-stack': Object.freeze({ label: 'On surface', icon: 'stack' }),
        mirror: Object.freeze({ label: 'Mirror', icon: 'mirror' }),
        lock: Object.freeze({ label: 'Lock', icon: 'lock-simple' }),
        delete: Object.freeze({ label: 'Delete', icon: 'trash' }),
        'save-zone-name': Object.freeze({
            label: 'Apply zone name', icon: 'floppy-disk',
        }),
        'delete-zone': Object.freeze({ label: 'Delete zone', icon: 'trash' }),
        'save-floor-marking': Object.freeze({
            label: 'Apply floor marking details', icon: 'floppy-disk',
        }),
    });
    const FLOOR_MARKING_PRESETS = Object.freeze([
        Object.freeze({
            type: 'direction_arrow', label: 'Direction Arrow',
            semanticRole: 'material_flow', width: 0.8, depth: 1.6,
            fillColor: '#ffffff', strokeColor: '#1f2937', text: '',
        }),
        Object.freeze({
            type: 'solid_line', label: 'Solid Line',
            semanticRole: 'decorative', width: 0.12, depth: 2,
            fillColor: '#ffffff', strokeColor: '#1f2937', text: '',
        }),
        Object.freeze({
            type: 'dashed_line', label: 'Dashed Line',
            semanticRole: 'pedestrian_lane', width: 0.12, depth: 2,
            fillColor: '#facc15', strokeColor: '#1f2937', text: '',
        }),
        Object.freeze({
            type: 'keep_clear', label: 'Keep Clear',
            semanticRole: 'keep_clear', width: 2.4, depth: 1.5,
            fillColor: '#facc15', strokeColor: '#111827', text: 'KEEP CLEAR',
        }),
        Object.freeze({
            type: 'crosswalk', label: 'Crosswalk',
            semanticRole: 'pedestrian_lane', width: 2.4, depth: 2,
            fillColor: '#ffffff', strokeColor: '#1f2937', text: '',
        }),
        Object.freeze({
            type: 'hazard_stripe', label: 'Hazard Stripe',
            semanticRole: 'safety', width: 2.4, depth: 1,
            fillColor: '#facc15', strokeColor: '#111827', text: '',
        }),
        Object.freeze({
            type: 'floor_text', label: 'Floor Text',
            semanticRole: 'decorative', width: 3, depth: 1,
            fillColor: '#ffffff', strokeColor: '#1f2937', text: 'FLOOR TEXT',
        }),
        Object.freeze({
            type: 'parking_box', label: 'Parking Box',
            semanticRole: 'parking', width: 2, depth: 3,
            fillColor: '#2563eb', strokeColor: '#ffffff', text: 'PARKING',
        }),
    ]);
    const NON_PLACEMENT_ZONE_TYPES = Object.freeze(new Set([
        'aisle', 'exclusion', 'operator', 'safety', 'service', 'utility',
    ]));
    let autoArrangeSequence = 0;
    let threeViewpointSequence = 0;

    function selectionToolbarCommands(count) {
        const total = Math.max(0, Math.floor(finite(count, 0)));
        if (!total) return [];
        if (total === 1) {
            return [
                'rotate', 'offset', 'duplicate', 'vertical-stack',
                'mirror', 'lock', 'delete',
            ];
        }
        const commands = ['align'];
        if (total >= 3) commands.push('distribute');
        commands.push('relative');
        if (total === 2) commands.push('distance');
        commands.push('offset', 'duplicate', 'surface-stack', 'mirror', 'lock', 'delete');
        return commands;
    }

    function clone(value) {
        if (value === undefined) return undefined;
        return JSON.parse(JSON.stringify(value));
    }

    function finite(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function clamp(value, minimum, maximum, fallback) {
        return Math.max(minimum, Math.min(maximum, finite(value, fallback)));
    }

    function compassHeading(value) {
        const headingDegrees = (
            finite(value, 0) % 360 + 360
        ) % 360;
        const names = [
            'north', 'northeast', 'east', 'southeast',
            'south', 'southwest', 'west', 'northwest',
        ];
        return {
            headingDegrees: headingDegrees,
            cardinal: names[Math.round(headingDegrees / 45) % names.length],
        };
    }

    function normalizeThreeVisualSettings(value) {
        const input = value && typeof value === 'object' ? value : {};
        const background = typeof input.background === 'string'
            && (/^#[0-9a-f]{6}$/i.test(input.background)
                || input.background === 'auto')
            ? input.background : DEFAULT_THREE_VISUAL_SETTINGS.background;
        return {
            ambient: clamp(input.ambient, 0, 3,
                DEFAULT_THREE_VISUAL_SETTINGS.ambient),
            directional: clamp(input.directional, 0, 5,
                DEFAULT_THREE_VISUAL_SETTINGS.directional),
            exposure: clamp(input.exposure, 0, 3,
                DEFAULT_THREE_VISUAL_SETTINGS.exposure),
            contrast: clamp(input.contrast, 0.5, 1.5,
                DEFAULT_THREE_VISUAL_SETTINGS.contrast),
            metalness: clamp(input.metalness, 0, 1,
                DEFAULT_THREE_VISUAL_SETTINGS.metalness),
            roughness: clamp(input.roughness, 0, 1,
                DEFAULT_THREE_VISUAL_SETTINGS.roughness),
            autoRotate: input.autoRotate === true,
            wireframe: input.wireframe === true,
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

    function cleanString(value, fallback) {
        return typeof value === 'string' && value.trim()
            ? value.trim()
            : fallback;
    }

    function recordingElapsedText(value) {
        const totalSeconds = Math.max(0, Math.floor(finite(value, 0) / 1000));
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        return String(minutes).padStart(2, '0') + ':'
            + String(seconds).padStart(2, '0');
    }

    function threeViewIconSrc(view) {
        const normalized = THREE_VIEW_ORIENTATIONS.some(function (item) {
            return item.key === view;
        }) ? view : 'iso';
        return VIEW_ORIENTATION_ICON_ROOT + 'view-' + normalized + '.png';
    }

    function normalizedDistanceUnit(value) {
        return value === 'ft' ? 'ft' : 'm';
    }

    function displayDistance(meters, unit) {
        const value = finite(meters, 0);
        return normalizedDistanceUnit(unit) === 'ft'
            ? value * METERS_TO_FEET
            : value;
    }

    function canonicalDistance(value, unit) {
        const distance = Number(value);
        if (!Number.isFinite(distance)) return NaN;
        return normalizedDistanceUnit(unit) === 'ft'
            ? distance / METERS_TO_FEET
            : distance;
    }

    function formattedDistance(value) {
        const absolute = Math.abs(finite(value, 0));
        const decimals = absolute >= 100 ? 0 : (absolute >= 10 ? 1 : 2);
        return Number(finite(value, 0).toFixed(decimals)).toString();
    }

    function normalizePlanPreferences(value) {
        const source = value && typeof value === 'object' ? value : {};
        return {
            unit: normalizedDistanceUnit(source.unit),
            showGrid: source.showGrid !== false,
            snapToGrid: source.snapToGrid !== false,
        };
    }

    function normalizePlanSettings(value, fallback) {
        const base = fallback && typeof fallback === 'object' ? fallback : {};
        const source = value && typeof value === 'object' ? value : {};
        const widthMeters = clamp(
            source.widthMeters,
            0.5,
            10000,
            finite(base.widthMeters, DEFAULT_PLAN_WIDTH_METERS)
        );
        const depthMeters = clamp(
            source.depthMeters,
            0.5,
            10000,
            finite(base.depthMeters, DEFAULT_PLAN_DEPTH_METERS)
        );
        const maximumGrid = Math.max(widthMeters, depthMeters);
        const gridSpacingMeters = clamp(
            source.gridSpacingMeters,
            0.05,
            maximumGrid,
            Math.min(
                maximumGrid,
                finite(base.gridSpacingMeters, DEFAULT_PLAN_GRID_METERS)
            )
        );
        const maximumMultiple = Math.max(
            1,
            Math.floor(maximumGrid / gridSpacingMeters + 1e-9)
        );
        const requestedMajor = finite(
            source.majorGridSpacingMeters,
            finite(base.majorGridSpacingMeters, gridSpacingMeters * 5)
        );
        const majorMultiple = Math.max(1, Math.min(
            maximumMultiple,
            Math.round(requestedMajor / gridSpacingMeters)
        ));
        return {
            widthMeters: widthMeters,
            depthMeters: depthMeters,
            gridSpacingMeters: gridSpacingMeters,
            majorGridSpacingMeters: gridSpacingMeters * majorMultiple,
        };
    }

    function planSettingsFromLayout(layout, fallback) {
        const extensions = layout && layout.extensions;
        const stored = extensions && extensions[PLAN_SETTINGS_EXTENSION_KEY];
        return normalizePlanSettings(stored, fallback);
    }

    function worldBoundsFromPlanSettings(settings, fallback) {
        const base = fallback && typeof fallback === 'object' ? fallback : {};
        const normalized = normalizePlanSettings(settings);
        const minX = finite(base.minX, 0);
        const minZ = finite(base.minZ, 0);
        return {
            minX: minX,
            minZ: minZ,
            maxX: minX + normalized.widthMeters,
            maxZ: minZ + normalized.depthMeters,
            floorY: finite(base.floorY, 0),
        };
    }

    function loadPlanPreferences(storage, key, fallback) {
        if (!storage || typeof storage.getItem !== 'function') {
            return normalizePlanPreferences(fallback);
        }
        try {
            const stored = JSON.parse(storage.getItem(key) || 'null');
            return normalizePlanPreferences(Object.assign({}, fallback, stored));
        } catch (error) {
            return normalizePlanPreferences(fallback);
        }
    }

    function storePlanPreferences(storage, key, value) {
        if (!storage || typeof storage.setItem !== 'function') return false;
        try {
            storage.setItem(key, JSON.stringify(normalizePlanPreferences(value)));
            return true;
        } catch (error) {
            return false;
        }
    }

    function normalizedCameraPoint(value, includeW) {
        const source = value && typeof value === 'object' ? value : {};
        const keys = includeW ? ['x', 'y', 'z', 'w'] : ['x', 'y', 'z'];
        if (!keys.every(function (key) {
            return Number.isFinite(Number(source[key]));
        })) return null;
        const output = {
            x: Number(source.x),
            y: Number(source.y),
            z: Number(source.z),
        };
        if (includeW) output.w = Number(source.w);
        return output;
    }

    function normalizeThreeCameraView(value) {
        const source = value && typeof value === 'object' ? value : {};
        const position = normalizedCameraPoint(source.position, false);
        const quaternion = normalizedCameraPoint(source.quaternion, true);
        if (!position || !quaternion) return null;
        const output = {
            position: position,
            quaternion: quaternion,
            up: normalizedCameraPoint(source.up, false)
                || { x: 0, y: 1, z: 0 },
            target: normalizedCameraPoint(source.target, false),
            near: Math.max(0.0001, finite(source.near, 0.01)),
            far: Math.max(1, finite(source.far, 10000)),
            navigationMode: source.navigationMode === 'pan' ? 'pan' : 'orbit',
        };
        return output;
    }

    function normalizeThreeViewpoints(value) {
        const seen = new Set();
        return (Array.isArray(value) ? value : []).map(function (item, index) {
            const camera = normalizeThreeCameraView(item && item.camera);
            if (!camera) return null;
            let viewpointId = cleanString(
                item && item.viewpointId,
                'viewpoint-' + (index + 1)
            );
            if (seen.has(viewpointId)) {
                viewpointId += '-' + (index + 1);
            }
            seen.add(viewpointId);
            return {
                viewpointId: viewpointId,
                name: cleanString(item && item.name, 'Viewpoint ' + (index + 1))
                    .slice(0, 60),
                camera: camera,
            };
        }).filter(Boolean).slice(0, MAX_THREE_VIEWPOINTS);
    }

    function loadThreeViewpoints(storage, key) {
        if (!storage || typeof storage.getItem !== 'function') return [];
        try {
            return normalizeThreeViewpoints(JSON.parse(
                storage.getItem(key) || '[]'
            ));
        } catch (error) {
            return [];
        }
    }

    function storeThreeViewpoints(storage, key, value) {
        if (!storage || typeof storage.setItem !== 'function') return false;
        try {
            storage.setItem(key, JSON.stringify(normalizeThreeViewpoints(value)));
            return true;
        } catch (error) {
            return false;
        }
    }

    function planWorldAtScreen(projection, screenX, screenY) {
        return {
            x: projection.minX
                + (screenX - projection.offsetX) / projection.scale,
            z: projection.maxZ
                - (screenY - projection.offsetY) / projection.scale,
        };
    }

    function planScreenForWorld(projection, worldX, worldZ) {
        return {
            x: projection.offsetX
                + (worldX - projection.minX) * projection.scale,
            y: projection.offsetY
                + (projection.maxZ - worldZ) * projection.scale,
        };
    }

    function alignedValues(minimum, maximum, spacing, maximumCount) {
        if (!Number.isFinite(spacing) || spacing <= 0) return [];
        const output = [];
        const epsilon = spacing * 0.000001;
        let value = Math.ceil((minimum - epsilon) / spacing) * spacing;
        while (value <= maximum + epsilon
                && output.length < (maximumCount || 300)) {
            output.push(Number(value.toFixed(9)));
            value += spacing;
        }
        return output;
    }

    function preferredScaleDistance(projectionScale, unit) {
        const normalizedUnit = normalizedDistanceUnit(unit);
        const metersPerUnit = normalizedUnit === 'ft'
            ? 1 / METERS_TO_FEET : 1;
        const candidates = SCALE_DISTANCES[normalizedUnit];
        let best = candidates[0];
        let bestDelta = Infinity;
        candidates.forEach(function (distance) {
            const pixels = distance * metersPerUnit * projectionScale;
            const delta = Math.abs(pixels - 130)
                + (pixels < 88 ? (88 - pixels) * 3 : 0)
                + (pixels > 190 ? (pixels - 190) * 3 : 0);
            if (delta < bestDelta) {
                best = distance;
                bestDelta = delta;
            }
        });
        return {
            displayDistance: best,
            meters: best * metersPerUnit,
            pixels: best * metersPerUnit * projectionScale,
        };
    }

    function boundedText(value, maximum) {
        const text = cleanString(value, '');
        const limit = maximum || 120;
        return text.length <= limit
            ? text
            : text.slice(0, Math.max(0, limit - 3)) + '...';
    }

    function candidateSafetyStatus(value) {
        return value === 'safe' || value === 'unsafe'
            ? value
            : 'unverified';
    }

    function candidateSafetyLabel(value) {
        const status = candidateSafetyStatus(value);
        if (status === 'safe') return 'Authoritatively validated';
        if (status === 'unsafe') return 'Invalid placement';
        return 'Engineering evidence incomplete';
    }

    function candidateFindingSummary(findings) {
        if (!Array.isArray(findings) || !findings.length) return '';
        const maximum = 2;
        const visible = findings.slice(0, maximum).map(function (finding) {
            if (typeof finding === 'string') return boundedText(finding, 100);
            if (!finding || typeof finding !== 'object') return '';
            return boundedText(
                finding.message || finding.label || finding.code,
                100
            );
        }).filter(Boolean);
        if (!visible.length) return '';
        const remaining = findings.length - visible.length;
        return 'Findings: ' + visible.join('; ')
            + (remaining > 0 ? '; +' + remaining + ' more' : '');
    }

    function candidateMetricSummary(metrics) {
        if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) {
            return '';
        }
        const preferred = [
            'errorCount',
            'unverifiedCount',
            'warningCount',
            'physicalCollisions',
            'clearanceConflicts',
            'distanceFromRequested',
        ];
        const keys = preferred.filter(function (key) {
            return Object.prototype.hasOwnProperty.call(metrics, key);
        }).concat(Object.keys(metrics).sort().filter(function (key) {
            return !preferred.includes(key);
        })).slice(0, 3);
        const values = keys.map(function (key) {
            const value = metrics[key];
            if (typeof value === 'number' && Number.isFinite(value)) {
                return key + ' ' + Number(value.toFixed(3));
            }
            if (typeof value === 'string' || typeof value === 'boolean') {
                return key + ' ' + boundedText(String(value), 40);
            }
            return '';
        }).filter(Boolean);
        return values.length ? 'Metrics: ' + values.join(', ') : '';
    }

    function candidateAssessment(candidate) {
        const source = candidate || {};
        const status = candidateSafetyStatus(source.safetyStatus);
        const details = [
            candidateFindingSummary(source.findings),
            candidateMetricSummary(source.metrics),
        ].filter(Boolean);
        return {
            status: status,
            label: candidateSafetyLabel(status),
            summary: details.join('. '),
        };
    }

    function assertObject(value, label) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            throw new TypeError(label + ' must be an object');
        }
        return value;
    }

    function setAttributes(element, attributes) {
        Object.keys(attributes || {}).forEach(function (name) {
            const value = attributes[name];
            if (value === undefined || value === null || value === false) return;
            if (name === 'className') {
                element.className = String(value);
            } else if (name === 'textContent') {
                element.textContent = String(value);
            } else if (name === 'disabled') {
                element.disabled = Boolean(value);
                if (value) element.setAttribute('disabled', '');
                else element.removeAttribute('disabled');
            } else if (name === 'hidden') {
                element.hidden = Boolean(value);
            } else {
                element.setAttribute(name, value === true ? '' : String(value));
            }
        });
        return element;
    }

    function element(documentRef, tagName, attributes, text) {
        const node = documentRef.createElement(tagName);
        setAttributes(node, attributes);
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    function clearElement(node) {
        while (node && node.firstChild) node.removeChild(node.firstChild);
    }

    function setClassToken(node, token, enabled) {
        if (!node) return;
        const classes = String(node.className || '').split(/\s+/).filter(Boolean);
        const filtered = classes.filter(function (item) { return item !== token; });
        if (enabled) filtered.push(token);
        node.className = filtered.join(' ');
    }

    function append(parent) {
        Array.prototype.slice.call(arguments, 1).forEach(function (child) {
            if (child) parent.appendChild(child);
        });
        return parent;
    }

    function normalizeQuarterTurns(turns) {
        const value = finite(turns, 0);
        if (!Number.isInteger(value)) {
            throw new TypeError('quarter turns must be an integer');
        }
        return ((value % 4) + 4) % 4;
    }

    function quarterTurnQuaternion(turns) {
        const normalized = normalizeQuarterTurns(turns === undefined ? 1 : turns);
        const angle = normalized * Math.PI / 2;
        return {
            x: 0,
            y: Math.sin(angle / 2),
            z: 0,
            w: Math.cos(angle / 2),
        };
    }

    function snapCoordinate(value, gridSize) {
        const number = finite(value, 0);
        const step = finite(gridSize, DEFAULT_GRID_SIZE);
        if (step <= 0) return number;
        const snapped = Math.round(number / step) * step;
        return Math.abs(snapped) < 1e-12 ? 0 : Number(snapped.toFixed(9));
    }

    function snapWorldPoint(value, gridSize) {
        assertObject(value, 'world point');
        return {
            x: snapCoordinate(value.x, gridSize),
            y: finite(value.y, 0),
            z: snapCoordinate(value.z, gridSize),
        };
    }

    function resizeFloorMarkingFromHandle(marking, handleIndex, worldPoint, gridSize) {
        const source = assertObject(marking, 'floor marking');
        const target = assertObject(worldPoint, 'resize point');
        const index = Math.floor(finite(handleIndex, -1));
        if (index < 0 || index > 3) {
            throw new RangeError('floor marking resize handle must be 0 through 3');
        }
        const transform = source.transform && typeof source.transform === 'object'
            ? source.transform : {};
        const position = transform.position || {};
        const center = {
            x: finite(position.x, 0),
            y: finite(position.y, 0),
            z: finite(position.z, 0),
        };
        const width = Math.max(0.05, finite(source.width, 1));
        const depth = Math.max(0.05, finite(source.depth, 1));
        const degrees = finite(transform.rotationDegrees, 0);
        const radians = degrees * Math.PI / 180;
        const cosine = Math.cos(radians);
        const sine = Math.sin(radians);
        const corners = [
            { x: -width / 2, z: -depth / 2 },
            { x: width / 2, z: -depth / 2 },
            { x: width / 2, z: depth / 2 },
            { x: -width / 2, z: depth / 2 },
        ];
        const opposite = corners[(index + 2) % 4];
        const fixed = {
            x: center.x + opposite.x * cosine + opposite.z * sine,
            z: center.z - opposite.x * sine + opposite.z * cosine,
        };
        const worldDelta = {
            x: finite(target.x, fixed.x) - fixed.x,
            z: finite(target.z, fixed.z) - fixed.z,
        };
        let localX = worldDelta.x * cosine - worldDelta.z * sine;
        let localZ = worldDelta.x * sine + worldDelta.z * cosine;
        const step = Math.max(0, finite(gridSize, 0));
        if (step > 0) {
            localX = Math.sign(localX || (index === 0 || index === 3 ? -1 : 1))
                * Math.max(step, Math.abs(snapCoordinate(localX, step)));
            localZ = Math.sign(localZ || (index === 0 || index === 1 ? -1 : 1))
                * Math.max(step, Math.abs(snapCoordinate(localZ, step)));
        }
        const minimum = 0.05;
        const fallbackX = index === 0 || index === 3 ? -1 : 1;
        const fallbackZ = index === 0 || index === 1 ? -1 : 1;
        if (Math.abs(localX) < minimum) localX = fallbackX * minimum;
        if (Math.abs(localZ) < minimum) localZ = fallbackZ * minimum;
        const halfLocal = { x: localX / 2, z: localZ / 2 };
        const resized = clone(source);
        resized.width = Number(Math.abs(localX).toFixed(9));
        resized.depth = Number(Math.abs(localZ).toFixed(9));
        resized.positionMode = 'manual';
        resized.transform = Object.assign({}, clone(transform), {
            position: {
                x: Number((fixed.x + halfLocal.x * cosine
                    + halfLocal.z * sine).toFixed(9)),
                y: center.y,
                z: Number((fixed.z - halfLocal.x * sine
                    + halfLocal.z * cosine).toFixed(9)),
            },
            rotationDegrees: degrees,
        });
        return resized;
    }

    function createAssetDragPayload(asset, dragSessionId) {
        const source = assertObject(asset, 'asset');
        const payload = {
            assetId: cleanString(source.assetId, ''),
            assetDefinitionRevision: cleanString(source.assetDefinitionRevision, ''),
            dragSessionId: cleanString(dragSessionId, ''),
        };
        if (!payload.assetId) throw new TypeError('assetId is required');
        if (!payload.assetDefinitionRevision) {
            throw new TypeError('assetDefinitionRevision is required');
        }
        if (!payload.dragSessionId) throw new TypeError('dragSessionId is required');
        return JSON.stringify(payload);
    }

    function dragPayloadText(value) {
        if (typeof value === 'string') return value;
        const transfer = value && (
            value.dataTransfer
            || (typeof value.getData === 'function' ? value : null)
        );
        if (!transfer || typeof transfer.getData !== 'function') return '';
        return transfer.getData(ASSET_MIME)
            || transfer.getData('application/json')
            || transfer.getData('text/plain')
            || '';
    }

    function parseAssetDragPayload(value) {
        const text = dragPayloadText(value);
        if (!text) return null;
        let parsed;
        try {
            parsed = JSON.parse(text);
        } catch (error) {
            return null;
        }
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
        const result = {
            assetId: cleanString(parsed.assetId, ''),
            assetDefinitionRevision: cleanString(
                parsed.assetDefinitionRevision,
                ''
            ),
            dragSessionId: cleanString(parsed.dragSessionId, ''),
        };
        return result.assetId && result.assetDefinitionRevision && result.dragSessionId
            ? result
            : null;
    }

    function catalogArray(catalog) {
        if (Array.isArray(catalog)) return catalog.slice();
        if (!catalog || typeof catalog !== 'object') return [];
        if (Array.isArray(catalog.entries)) return catalog.entries.slice();
        if (Array.isArray(catalog.assets)) return catalog.assets.slice();
        return Object.keys(catalog).sort().map(function (key) {
            const record = catalog[key];
            if (!record || typeof record !== 'object') return null;
            return record.assetId ? record : Object.assign({ assetId: key }, record);
        }).filter(Boolean);
    }

    function normalizeCatalog(catalog) {
        return catalogArray(catalog).map(function (record) {
            const source = record.source || record;
            const definition = record.definition
                || record.assetDefinition
                || source.definition
                || source.assetDefinition
                || {};
            const geometry = definition.geometry || record.geometry || {};
            const aabb = geometry.aabb || definition.aabb || record.aabb || {};
            const minimum = aabb.minimum || aabb.min || {};
            const maximum = aabb.maximum || aabb.max || {};
            const dimensions = record.dimensions || definition.dimensions || {};
            const width = finite(
                record.width !== undefined ? record.width : dimensions.width,
                finite(maximum.x, NaN) - finite(minimum.x, NaN)
            );
            const depth = finite(
                record.depth !== undefined ? record.depth : dimensions.depth,
                finite(maximum.z, NaN) - finite(minimum.z, NaN)
            );
            const height = finite(
                record.height !== undefined ? record.height : dimensions.height,
                finite(maximum.y, NaN) - finite(minimum.y, NaN)
            );
            const thumbnail = record.thumbnail
                || source.thumbnail
                || definition.thumbnail
                || {};
            const thumbnailUrl = cleanString(
                record.thumbnailUrl
                || record.previewImage
                || source.thumbnailUrl
                || source.previewImage
                || (typeof thumbnail === 'string'
                    ? thumbnail
                    : thumbnail.path || thumbnail.url),
                ''
            );
            const rawTags = record.tags || source.tags || definition.tags || [];
            const supportSurfaces = record.supportSurfaces
                || source.supportSurfaces
                || definition.supportSurfaces
                || [];
            return {
                source: source,
                assetId: cleanString(record.assetId || definition.assetId, ''),
                assetDefinitionRevision: cleanString(
                    record.assetDefinitionRevision
                    || record.publishedAssetDefinitionRevision
                    || record.definitionRevision
                    || definition.assetDefinitionRevision,
                    ''
                ),
                label: cleanString(
                    record.displayName
                    || record.label
                    || record.name
                    || definition.displayName
                    || record.assetId,
                    'Unnamed asset'
                ),
                category: cleanString(
                    record.category
                    || record.assetClass
                    || record.assetType
                    || definition.category,
                    'Other'
                ),
                description: cleanString(
                    record.description || definition.description,
                    ''
                ),
                manufacturer: cleanString(
                    record.manufacturer
                    || source.manufacturer
                    || definition.manufacturer,
                    ''
                ),
                tags: Array.isArray(rawTags) ? rawTags.map(function (value) {
                    return cleanString(value, '');
                }).filter(Boolean) : [],
                thumbnailUrl: thumbnailUrl,
                width: Number.isFinite(width) && width > 0 ? width : 1.2,
                depth: Number.isFinite(depth) && depth > 0 ? depth : 0.8,
                height: Number.isFinite(height) && height > 0 ? height : 1,
                supportSurfaces: Array.isArray(supportSurfaces)
                    ? clone(supportSurfaces) : [],
            };
        }).filter(function (record) {
            return record.assetId && record.assetDefinitionRevision;
        }).sort(function (left, right) {
            return left.category.localeCompare(right.category)
                || left.label.localeCompare(right.label)
                || left.assetId.localeCompare(right.assetId);
        });
    }

    function rectangleBounds(center, width, depth) {
        return {
            minX: center.x - width / 2,
            maxX: center.x + width / 2,
            minZ: center.z - depth / 2,
            maxZ: center.z + depth / 2,
        };
    }

    function boundsOverlap(left, right, clearance) {
        const gap = Math.max(0, finite(clearance, 0));
        return !(left.maxX + gap <= right.minX
            || left.minX - gap >= right.maxX
            || left.maxZ + gap <= right.minZ
            || left.minZ - gap >= right.maxZ);
    }

    function boundsInsideWorld(value, worldBounds) {
        if (!worldBounds || typeof worldBounds !== 'object') return true;
        const minX = finite(worldBounds.minX, NaN);
        const minZ = finite(worldBounds.minZ, NaN);
        const maxX = finite(worldBounds.maxX, NaN);
        const maxZ = finite(worldBounds.maxZ, NaN);
        if (![minX, minZ, maxX, maxZ].every(Number.isFinite)) return true;
        return value.minX >= minX && value.maxX <= maxX
            && value.minZ >= minZ && value.maxZ <= maxZ;
    }

    function pointOnZoneBoundary(point, boundary) {
        const epsilon = 1e-7;
        for (let index = 0; index < boundary.length; index += 1) {
            const start = boundary[index] || {};
            const end = boundary[(index + 1) % boundary.length] || {};
            const sx = finite(start.x, NaN);
            const sz = finite(start.z, NaN);
            const ex = finite(end.x, NaN);
            const ez = finite(end.z, NaN);
            if (![sx, sz, ex, ez].every(Number.isFinite)) continue;
            const dx = ex - sx;
            const dz = ez - sz;
            const lengthSquared = dx * dx + dz * dz;
            if (lengthSquared <= epsilon) continue;
            const projection = ((point.x - sx) * dx + (point.z - sz) * dz)
                / lengthSquared;
            if (projection < -epsilon || projection > 1 + epsilon) continue;
            const nearestX = sx + projection * dx;
            const nearestZ = sz + projection * dz;
            if (Math.hypot(point.x - nearestX, point.z - nearestZ) <= epsilon) {
                return true;
            }
        }
        return false;
    }

    function pointInsideZone(point, boundary) {
        if (!point || !Array.isArray(boundary) || boundary.length < 3) {
            return false;
        }
        if (pointOnZoneBoundary(point, boundary)) return true;
        let inside = false;
        for (let index = 0, previous = boundary.length - 1;
                index < boundary.length; previous = index, index += 1) {
            const current = boundary[index] || {};
            const prior = boundary[previous] || {};
            const cx = finite(current.x, NaN);
            const cz = finite(current.z, NaN);
            const px = finite(prior.x, NaN);
            const pz = finite(prior.z, NaN);
            if (![cx, cz, px, pz].every(Number.isFinite)) continue;
            const crosses = (cz > point.z) !== (pz > point.z)
                && point.x < (px - cx) * (point.z - cz) / (pz - cz) + cx;
            if (crosses) inside = !inside;
        }
        return inside;
    }

    function boundsInsideZone(value, zone) {
        const boundary = zone && Array.isArray(zone.boundary)
            ? zone.boundary : [];
        if (boundary.length < 3) return false;
        const setbackValues = zone.edgeSetbacks
            && typeof zone.edgeSetbacks === 'object'
            ? Object.keys(zone.edgeSetbacks).map(function (key) {
                return Math.max(0, finite(zone.edgeSetbacks[key], 0));
            }) : [];
        const setback = setbackValues.length
            ? Math.max.apply(null, setbackValues) : 0;
        const candidate = {
            minX: value.minX - setback,
            maxX: value.maxX + setback,
            minZ: value.minZ - setback,
            maxZ: value.maxZ + setback,
        };
        return [
            { x: candidate.minX, z: candidate.minZ },
            { x: candidate.maxX, z: candidate.minZ },
            { x: candidate.maxX, z: candidate.maxZ },
            { x: candidate.minX, z: candidate.maxZ },
            {
                x: (candidate.minX + candidate.maxX) / 2,
                z: (candidate.minZ + candidate.maxZ) / 2,
            },
        ].every(function (point) {
            return pointInsideZone(point, boundary);
        });
    }

    function operationalPlacementZones(layout) {
        return ((layout && layout.zones) || []).filter(function (zone) {
            return zone && !NON_PLACEMENT_ZONE_TYPES.has(
                cleanString(zone.zoneType, '')
            ) && Array.isArray(zone.boundary) && zone.boundary.length >= 3;
        });
    }

    function zoneAllowsRecord(zone, record) {
        const allowed = zone && zone.allowedAssetCategories;
        return !Array.isArray(allowed) || !allowed.length
            || allowed.includes(record.category);
    }

    function candidateFitsPlacementZone(candidate, zones) {
        if (!zones.length) return true;
        return zones.some(function (zone) {
            return zoneAllowsRecord(zone, candidate.item.record)
                && boundsInsideZone(candidate.bounds, zone);
        });
    }

    function catalogRecord(catalog, assetId, revision) {
        return catalog.find(function (record) {
            return record.assetId === assetId
                && (!revision || record.assetDefinitionRevision === revision);
        }) || null;
    }

    function placementBounds(placement, catalog) {
        const record = catalogRecord(
            catalog,
            placement.assetId,
            placement.assetDefinitionRevision
        );
        const transform = placement.transform || {};
        const position = transform.position || {};
        const scale = Math.max(0.0001, finite(transform.scale, 1));
        let width = (record ? record.width : 1.2) * scale;
        let depth = (record ? record.depth : 0.8) * scale;
        const quarterTurns = Math.round(
            quaternionYawDegrees(transform.quaternion) / 90
        ) % 4;
        if (Math.abs(quarterTurns) % 2 === 1) {
            const swap = width;
            width = depth;
            depth = swap;
        }
        return rectangleBounds({
            x: finite(position.x, 0),
            z: finite(position.z, 0),
        }, width, depth);
    }

    function boundsCenter(bounds) {
        return {
            x: (finite(bounds.minX, 0) + finite(bounds.maxX, 0)) / 2,
            z: (finite(bounds.minZ, 0) + finite(bounds.maxZ, 0)) / 2,
        };
    }

    function unionBounds(values) {
        if (!Array.isArray(values) || !values.length) {
            throw new TypeError('at least one placement bound is required');
        }
        return values.reduce(function (result, value) {
            return {
                minX: Math.min(result.minX, value.minX),
                minZ: Math.min(result.minZ, value.minZ),
                maxX: Math.max(result.maxX, value.maxX),
                maxZ: Math.max(result.maxZ, value.maxZ),
            };
        }, {
            minX: Infinity,
            minZ: Infinity,
            maxX: -Infinity,
            maxZ: -Infinity,
        });
    }

    function precisionPlacements(layout, placementIds) {
        const source = assertObject(layout, 'layout');
        if (!Array.isArray(placementIds)) {
            throw new TypeError('placementIds must be an array');
        }
        const index = new Map((source.placements || []).map(function (placement) {
            return [placement.placementId, placement];
        }));
        const seen = new Set();
        return placementIds.map(function (placementId, itemIndex) {
            const identifier = cleanString(placementId, '');
            if (!identifier || seen.has(identifier)) {
                throw new TypeError(
                    'placementIds[' + itemIndex + '] must be a unique placement ID'
                );
            }
            seen.add(identifier);
            const placement = index.get(identifier);
            if (!placement) {
                throw new TypeError("placement '" + identifier + "' does not exist");
            }
            return placement;
        });
    }

    function placementUpdate(placement, deltaX, deltaZ) {
        const position = placement.transform && placement.transform.position || {};
        const dx = finite(deltaX, 0);
        const dz = finite(deltaZ, 0);
        if (placement.positionMode === 'locked'
                && (Math.abs(dx) > 1e-9 || Math.abs(dz) > 1e-9)) {
            throw new Error(
                "Unlock '" + cleanString(
                    placement.metadata && placement.metadata.instanceLabel,
                    placement.placementId
                ) + "' before repositioning it."
            );
        }
        return {
            placementId: placement.placementId,
            position: {
                x: finite(position.x, 0) + dx,
                y: finite(position.y, 0),
                z: finite(position.z, 0) + dz,
            },
        };
    }

    function changedPlacementUpdate(placement, deltaX, deltaZ) {
        const dx = finite(deltaX, 0);
        const dz = finite(deltaZ, 0);
        if (Math.abs(dx) <= 1e-9 && Math.abs(dz) <= 1e-9) return null;
        return placementUpdate(placement, dx, dz);
    }

    function buildAlignmentUpdates(layout, catalog, placementIds, mode, anchorId) {
        const placements = precisionPlacements(layout, placementIds);
        if (placements.length < 2) {
            throw new TypeError('Select at least two equipment placements to align.');
        }
        const supported = [
            'left', 'center-x', 'right', 'north', 'center-z', 'south',
        ];
        if (!supported.includes(mode)) {
            throw new TypeError('alignment mode is unsupported');
        }
        const normalizedCatalog = normalizeCatalog(catalog || []);
        const anchor = placements.find(function (placement) {
            return placement.placementId === anchorId;
        }) || placements[0];
        const anchorBounds = placementBounds(anchor, normalizedCatalog);
        const anchorCenter = boundsCenter(anchorBounds);
        const target = {
            left: anchorBounds.minX,
            'center-x': anchorCenter.x,
            right: anchorBounds.maxX,
            north: anchorBounds.maxZ,
            'center-z': anchorCenter.z,
            south: anchorBounds.minZ,
        }[mode];
        const updates = placements.map(function (placement) {
            if (placement.placementId === anchor.placementId) return null;
            const bounds = placementBounds(placement, normalizedCatalog);
            const center = boundsCenter(bounds);
            let dx = 0;
            let dz = 0;
            if (mode === 'left') dx = target - bounds.minX;
            else if (mode === 'center-x') dx = target - center.x;
            else if (mode === 'right') dx = target - bounds.maxX;
            else if (mode === 'north') dz = target - bounds.maxZ;
            else if (mode === 'center-z') dz = target - center.z;
            else dz = target - bounds.minZ;
            return changedPlacementUpdate(placement, dx, dz);
        }).filter(Boolean);
        return {
            mode: mode,
            anchorPlacementId: anchor.placementId,
            updates: updates,
        };
    }

    function buildDistributionUpdates(
        layout,
        catalog,
        placementIds,
        axis,
        method,
        exactGap
    ) {
        const placements = precisionPlacements(layout, placementIds);
        if (placements.length < 3) {
            throw new TypeError('Select at least three equipment placements to distribute.');
        }
        if (axis !== 'x' && axis !== 'z') {
            throw new TypeError('distribution axis must be x or z');
        }
        if (!['equal-gap', 'equal-center', 'fixed-gap'].includes(method)) {
            throw new TypeError('distribution method is unsupported');
        }
        const normalizedCatalog = normalizeCatalog(catalog || []);
        const records = placements.map(function (placement) {
            const bounds = placementBounds(placement, normalizedCatalog);
            const center = boundsCenter(bounds);
            return {
                placement: placement,
                bounds: bounds,
                center: center,
                size: axis === 'x'
                    ? bounds.maxX - bounds.minX
                    : bounds.maxZ - bounds.minZ,
            };
        }).sort(function (left, right) {
            const delta = left.center[axis] - right.center[axis];
            return Math.abs(delta) > 1e-9
                ? delta
                : left.placement.placementId.localeCompare(
                    right.placement.placementId
                );
        });
        const first = records[0];
        const last = records[records.length - 1];
        const proposedCenters = new Map();
        let gap = null;
        if (method === 'equal-center') {
            const interval = (last.center[axis] - first.center[axis])
                / (records.length - 1);
            records.forEach(function (record, index) {
                proposedCenters.set(
                    record.placement.placementId,
                    first.center[axis] + interval * index
                );
            });
        } else {
            gap = method === 'fixed-gap'
                ? finite(exactGap, NaN)
                : ((axis === 'x' ? last.bounds.maxX : last.bounds.maxZ)
                    - (axis === 'x' ? first.bounds.minX : first.bounds.minZ)
                    - records.reduce(function (total, record) {
                        return total + record.size;
                    }, 0)) / (records.length - 1);
            if (!Number.isFinite(gap) || gap < 0) {
                throw new TypeError(
                    method === 'fixed-gap'
                        ? 'Exact clear gap must be zero or greater.'
                        : 'The selected span is too small for equal clear gaps.'
                );
            }
            let cursor = axis === 'x' ? first.bounds.minX : first.bounds.minZ;
            records.forEach(function (record) {
                proposedCenters.set(
                    record.placement.placementId,
                    cursor + record.size / 2
                );
                cursor += record.size + gap;
            });
        }
        const updates = records.map(function (record) {
            const delta = proposedCenters.get(record.placement.placementId)
                - record.center[axis];
            return changedPlacementUpdate(
                record.placement,
                axis === 'x' ? delta : 0,
                axis === 'z' ? delta : 0
            );
        }).filter(Boolean);
        return {
            axis: axis,
            method: method,
            clearGap: gap,
            updates: updates,
        };
    }

    function buildRelativePositionUpdates(
        layout,
        catalog,
        movingIds,
        referenceId,
        relation,
        distance,
        alignment
    ) {
        const moving = precisionPlacements(layout, movingIds);
        if (!moving.length) throw new TypeError('Select equipment to reposition.');
        const reference = precisionPlacements(layout, [referenceId])[0];
        if (moving.some(function (placement) {
            return placement.placementId === reference.placementId;
        })) {
            throw new TypeError('The reference cannot also be repositioned.');
        }
        if (!['east', 'west', 'north', 'south'].includes(relation)) {
            throw new TypeError('relative relation is unsupported');
        }
        if (!['minimum', 'center', 'maximum'].includes(alignment)) {
            throw new TypeError('relative alignment is unsupported');
        }
        const gap = finite(distance, NaN);
        if (!Number.isFinite(gap) || gap < 0) {
            throw new TypeError('Relative distance must be zero or greater.');
        }
        const normalizedCatalog = normalizeCatalog(catalog || []);
        const referenceBounds = placementBounds(reference, normalizedCatalog);
        const groupBounds = unionBounds(moving.map(function (placement) {
            return placementBounds(placement, normalizedCatalog);
        }));
        const referenceCenter = boundsCenter(referenceBounds);
        const groupCenter = boundsCenter(groupBounds);
        let dx = 0;
        let dz = 0;
        if (relation === 'east') dx = referenceBounds.maxX + gap - groupBounds.minX;
        else if (relation === 'west') dx = referenceBounds.minX - gap - groupBounds.maxX;
        else if (relation === 'north') dz = referenceBounds.maxZ + gap - groupBounds.minZ;
        else dz = referenceBounds.minZ - gap - groupBounds.maxZ;

        if (relation === 'east' || relation === 'west') {
            if (alignment === 'minimum') dz = referenceBounds.minZ - groupBounds.minZ;
            else if (alignment === 'center') dz = referenceCenter.z - groupCenter.z;
            else dz = referenceBounds.maxZ - groupBounds.maxZ;
        } else if (alignment === 'minimum') {
            dx = referenceBounds.minX - groupBounds.minX;
        } else if (alignment === 'center') {
            dx = referenceCenter.x - groupCenter.x;
        } else {
            dx = referenceBounds.maxX - groupBounds.maxX;
        }
        return {
            referencePlacementId: reference.placementId,
            relation: relation,
            distance: gap,
            alignment: alignment,
            updates: moving.map(function (placement) {
                return changedPlacementUpdate(placement, dx, dz);
            }).filter(Boolean),
        };
    }

    function measurePlacementDistance(layout, catalog, firstId, secondId, mode) {
        const placements = precisionPlacements(layout, [firstId, secondId]);
        const normalizedCatalog = normalizeCatalog(catalog || []);
        const first = placementBounds(placements[0], normalizedCatalog);
        const second = placementBounds(placements[1], normalizedCatalog);
        const firstCenter = boundsCenter(first);
        const secondCenter = boundsCenter(second);
        const gapX = second.minX > first.maxX
            ? second.minX - first.maxX
            : first.minX > second.maxX
                ? first.minX - second.maxX : 0;
        const gapZ = second.minZ > first.maxZ
            ? second.minZ - first.maxZ
            : first.minZ > second.maxZ
                ? first.minZ - second.maxZ : 0;
        const values = {
            'horizontal-gap': gapX,
            'vertical-gap': gapZ,
            'horizontal-center': Math.abs(secondCenter.x - firstCenter.x),
            'vertical-center': Math.abs(secondCenter.z - firstCenter.z),
            'center-distance': Math.hypot(
                secondCenter.x - firstCenter.x,
                secondCenter.z - firstCenter.z
            ),
            shortest: Math.hypot(gapX, gapZ),
        };
        if (!Object.prototype.hasOwnProperty.call(values, mode)) {
            throw new TypeError('distance mode is unsupported');
        }
        return values[mode];
    }

    function buildDistanceUpdate(
        layout,
        catalog,
        referenceId,
        movingId,
        mode,
        requestedDistance
    ) {
        if (![
            'horizontal-gap',
            'vertical-gap',
            'horizontal-center',
            'vertical-center',
            'center-distance',
        ].includes(mode)) {
            throw new TypeError('editable distance mode is unsupported');
        }
        const placements = precisionPlacements(layout, [referenceId, movingId]);
        const reference = placements[0];
        const moving = placements[1];
        const distance = finite(requestedDistance, NaN);
        if (!Number.isFinite(distance) || distance < 0) {
            throw new TypeError('Distance must be zero or greater.');
        }
        const normalizedCatalog = normalizeCatalog(catalog || []);
        const referenceBounds = placementBounds(reference, normalizedCatalog);
        const movingBounds = placementBounds(moving, normalizedCatalog);
        const referenceCenter = boundsCenter(referenceBounds);
        const movingCenter = boundsCenter(movingBounds);
        let dx = 0;
        let dz = 0;
        if (mode === 'horizontal-gap') {
            const direction = movingCenter.x >= referenceCenter.x ? 1 : -1;
            const target = direction > 0
                ? referenceBounds.maxX + distance
                    + (movingBounds.maxX - movingBounds.minX) / 2
                : referenceBounds.minX - distance
                    - (movingBounds.maxX - movingBounds.minX) / 2;
            dx = target - movingCenter.x;
        } else if (mode === 'vertical-gap') {
            const direction = movingCenter.z >= referenceCenter.z ? 1 : -1;
            const target = direction > 0
                ? referenceBounds.maxZ + distance
                    + (movingBounds.maxZ - movingBounds.minZ) / 2
                : referenceBounds.minZ - distance
                    - (movingBounds.maxZ - movingBounds.minZ) / 2;
            dz = target - movingCenter.z;
        } else if (mode === 'horizontal-center') {
            const direction = movingCenter.x >= referenceCenter.x ? 1 : -1;
            dx = referenceCenter.x + direction * distance - movingCenter.x;
        } else if (mode === 'vertical-center') {
            const direction = movingCenter.z >= referenceCenter.z ? 1 : -1;
            dz = referenceCenter.z + direction * distance - movingCenter.z;
        } else {
            let vectorX = movingCenter.x - referenceCenter.x;
            let vectorZ = movingCenter.z - referenceCenter.z;
            const length = Math.hypot(vectorX, vectorZ);
            if (length <= 1e-9) {
                vectorX = 1;
                vectorZ = 0;
            } else {
                vectorX /= length;
                vectorZ /= length;
            }
            dx = referenceCenter.x + vectorX * distance - movingCenter.x;
            dz = referenceCenter.z + vectorZ * distance - movingCenter.z;
        }
        return {
            referencePlacementId: reference.placementId,
            movingPlacementId: moving.placementId,
            mode: mode,
            distance: distance,
            updates: [changedPlacementUpdate(moving, dx, dz)].filter(Boolean),
        };
    }

    function squareRingOffsets(maximumRing) {
        const offsets = [{ x: 0, z: 0 }];
        for (let ring = 1; ring <= maximumRing; ring += 1) {
            for (let x = -ring; x <= ring; x += 1) {
                offsets.push({ x: x, z: -ring });
                offsets.push({ x: x, z: ring });
            }
            for (let z = -ring + 1; z < ring; z += 1) {
                offsets.push({ x: -ring, z: z });
                offsets.push({ x: ring, z: z });
            }
        }
        return offsets;
    }

    function buildAssetBatchPlacementRequests(
        selection,
        layout,
        inputCatalog,
        center,
        inputOptions
    ) {
        const options = inputOptions || {};
        const catalog = normalizeCatalog(inputCatalog || []);
        const expanded = [];
        (selection || []).forEach(function (selected) {
            const quantity = Math.max(0, Math.floor(finite(selected.quantity, 0)));
            const record = catalogRecord(
                catalog,
                cleanString(selected.assetId, ''),
                cleanString(selected.assetDefinitionRevision, '')
            );
            if (!record || !quantity) return;
            for (let instance = 0; instance < quantity; instance += 1) {
                expanded.push({ record: record, instance: instance + 1 });
            }
        });
        if (!expanded.length) {
            throw new Error('Select at least one asset to add');
        }
        if (expanded.length > MAX_ASSET_BATCH_ITEMS) {
            throw new Error(
                'Add no more than ' + MAX_ASSET_BATCH_ITEMS
                + ' assets in one batch'
            );
        }
        const clearance = Math.max(
            0,
            finite(options.clearance, DEFAULT_ASSET_CLEARANCE)
        );
        const slotWidth = Math.max.apply(null, expanded.map(function (item) {
            return item.record.width;
        })) + clearance;
        const slotDepth = Math.max.apply(null, expanded.map(function (item) {
            return item.record.depth;
        })) + clearance;
        const columns = Math.min(expanded.length, Math.max(1, Math.ceil(
            Math.sqrt(expanded.length * slotDepth / slotWidth)
        )));
        const rows = Math.ceil(expanded.length / columns);
        const anchor = snapWorldPoint(center || { x: 0, y: 0, z: 0 },
            finite(options.gridSize, DEFAULT_GRID_SIZE));
        const placementZones = operationalPlacementZones(layout);
        const zoneAnchors = placementZones.filter(function (zone) {
            return expanded.every(function (item) {
                return zoneAllowsRecord(zone, item.record);
            });
        }).map(function (zone) {
            const dimensions = zoneDimensions(zone);
            return dimensions && dimensions.center;
        }).filter(Boolean).sort(function (left, right) {
            const leftDistance = Math.hypot(left.x - anchor.x, left.z - anchor.z);
            const rightDistance = Math.hypot(right.x - anchor.x, right.z - anchor.z);
            return leftDistance - rightDistance;
        });
        const anchors = [anchor].concat(zoneAnchors).filter(function (value, index, list) {
            return list.findIndex(function (candidate) {
                return Math.abs(candidate.x - value.x) <= 1e-7
                    && Math.abs(candidate.z - value.z) <= 1e-7;
            }) === index;
        });
        const occupied = ((layout && layout.placements) || []).map(function (value) {
            return placementBounds(value, catalog);
        });
        const offsets = squareRingOffsets(20);
        let accepted = null;
        for (let anchorIndex = 0;
                anchorIndex < anchors.length && !accepted; anchorIndex += 1) {
            const currentAnchor = anchors[anchorIndex];
            const base = expanded.map(function (item, index) {
                const column = index % columns;
                const row = Math.floor(index / columns);
                return {
                    item: item,
                    position: {
                        x: currentAnchor.x
                            + (column - (columns - 1) / 2) * slotWidth,
                        y: finite(currentAnchor.y, anchor.y),
                        z: currentAnchor.z
                            + (row - (rows - 1) / 2) * slotDepth,
                    },
                };
            });
            for (let index = 0; index < offsets.length && !accepted; index += 1) {
                const offset = offsets[index];
                const proposal = base.map(function (candidate) {
                    const position = snapWorldPoint({
                        x: candidate.position.x + offset.x * slotWidth,
                        y: candidate.position.y,
                        z: candidate.position.z + offset.z * slotDepth,
                    }, finite(options.gridSize, DEFAULT_GRID_SIZE));
                    return {
                        item: candidate.item,
                        position: position,
                        bounds: rectangleBounds(
                            position,
                            candidate.item.record.width,
                            candidate.item.record.depth
                        ),
                    };
                });
                const inside = proposal.every(function (candidate) {
                    return boundsInsideWorld(candidate.bounds, options.worldBounds)
                        && candidateFitsPlacementZone(candidate, placementZones);
                });
                const clear = inside && proposal.every(function (
                    candidate,
                    itemIndex
                ) {
                    return !occupied.concat(proposal.slice(0, itemIndex).map(
                        function (item) { return item.bounds; }
                    )).some(function (bounds) {
                        return boundsOverlap(candidate.bounds, bounds, clearance);
                    });
                });
                if (clear) accepted = proposal;
            }
        }
        if (!accepted) {
            throw new Error(
                'No collision-free area is available near the current view'
            );
        }
        return accepted.map(function (candidate, index) {
            const record = candidate.item.record;
            return {
                assetId: record.assetId,
                assetDefinitionRevision: record.assetDefinitionRevision,
                worldPosition: candidate.position,
                positionMode: 'manual',
                metadata: {
                    instanceLabel: record.label,
                    inputMethod: 'asset-browser',
                    batchIndex: index,
                    quantityInstance: candidate.item.instance,
                },
            };
        });
    }

    function buildAutoArrangeRequest(state, catalog, requestId) {
        const snapshot = assertObject(state, 'facility layout state');
        const savedLayout = assertObject(
            snapshot.baseLayout || snapshot.layout,
            'saved facility layout'
        );
        const placements = Array.isArray(savedLayout.placements)
            ? savedLayout.placements : [];
        const assets = normalizeCatalog(catalog || []);
        const assetSet = placements.length
            ? placements.map(function (placement, index) {
                const source = assertObject(
                    placement,
                    'saved placement ' + index
                );
                return {
                    itemId: 'existing-' + cleanString(
                        source.placementId,
                        String(index + 1)
                    ),
                    assetId: cleanString(source.assetId, ''),
                    assetDefinitionRevision: cleanString(
                        source.assetDefinitionRevision,
                        ''
                    ),
                    quantity: 1,
                    stage: index,
                    existingPlacementId: cleanString(
                        source.placementId,
                        ''
                    ),
                };
            })
            : assets.slice(0, 3).map(function (asset, index) {
                return {
                    itemId: 'catalog-' + String(index + 1),
                    assetId: asset.assetId,
                    assetDefinitionRevision:
                        asset.assetDefinitionRevision,
                    quantity: 1,
                    stage: index,
                };
            });
        if (!assetSet.length) {
            throw new Error(
                'Auto Arrange requires an existing placement or catalog asset'
            );
        }
        assetSet.forEach(function (item) {
            if (!item.assetId || !item.assetDefinitionRevision
                    || (item.existingPlacementId !== undefined
                        && !item.existingPlacementId)) {
                throw new Error(
                    'Auto Arrange requires stable asset and placement identities'
                );
            }
        });
        const sourceRevisions = {};
        const shellRevision = savedLayout.sourceShellRef
            && savedLayout.sourceShellRef.shellRevision;
        const policyRevision = savedLayout.policySetRef
            && savedLayout.policySetRef.policySetRevision;
        if (typeof shellRevision === 'string' && shellRevision) {
            sourceRevisions.shell = shellRevision;
        }
        if (typeof policyRevision === 'string' && policyRevision) {
            sourceRevisions.policy = policyRevision;
        }
        return {
            schemaVersion: 1,
            requestId: cleanString(requestId, 'facility-auto-arrange'),
            objective: 'place_and_cleanup',
            assetSet: assetSet,
            strategies: ['compact_rows', 'balanced_grid', 'flow_lanes'],
            maximumAlternatives: 3,
            spacingMeters: 1,
            cleanup: {
                enabled: true,
                moveAuto: true,
                movableManualPlacementIds: [],
            },
            zoneSizing: [],
            routes: [],
            sourceRevisions: sourceRevisions,
        };
    }

    // What the 3D camera fit depends on: the layout without its look. Painting models, wall finishes and
    // scene lighting keep the user's view; moving, adding or resizing anything still fits again.
    const FIT_IGNORED_KEYS = new Set(['componentMaterials', 'exteriorFinish', 'interiorColor', 'facilityScene']);

    function fitFingerprintOf(layout) {
        return JSON.stringify(layout, function (key, value) {
            return FIT_IGNORED_KEYS.has(key) ? undefined : value;
        });
    }

    // A review whose every operation only changes how things look: part colours, finishes, scene lighting, the
    // walls' finish alone, and ground marks over unchanged paving (the paint step's wall look and yard target).
    const APPEARANCE_OPERATIONS = new Set(['set_component_materials', 'set_appearance', 'set_scene']);

    function appearanceOperation(operation, layout) {
        if (!operation) return false;
        if (APPEARANCE_OPERATIONS.has(operation.op)) return true;
        if (operation.op === 'edit_perimeter_walls') {
            const keys = Object.keys(operation.patch || {});
            return keys.length === 1 && keys[0] === 'exteriorFinish';
        }
        if (operation.op === 'set_ground' && operation.ground) {
            const saved = (((layout || {}).extensions || {}).facilityGround || {}).surfaces;
            return Array.isArray(saved) && JSON.stringify(operation.ground.surfaces || []) === JSON.stringify(saved);
        }
        return false;
    }

    function appearanceOnlyAlternative(alternative, layout) {
        const operations = alternative && Array.isArray(alternative.operations) ? alternative.operations : [];
        return operations.length > 0 && operations.every(function (operation) {
            return appearanceOperation(operation, layout);
        });
    }

    // The view that shows a review best (the step-by-step build, 2026-10-24): the building's 2D plan for its size,
    // walls, zones, markings and aisles; the site photo for drives, entrances and outdoor areas; 3D for models and
    // paint. A new review only moves into or out of the Site view; Plan and 3D stay the user's choice.
    const PLAN_SHAPE_OPERATIONS = new Set(['set_plan_settings', 'set_building_pose']);
    const SITE_OPERATIONS = new Set(['set_site_context', 'upsert_site_area', 'delete_site_area',
        'upsert_site_reference', 'delete_site_reference']);
    const MODEL_OPERATIONS = new Set(['place_asset', 'place_asset_array']);

    function reviewViewFor(alternative, layout) {
        const operations = alternative && Array.isArray(alternative.operations) ? alternative.operations : [];
        if (!operations.length) return null;
        const names = operations.map(function (operation) { return operation && operation.op; });
        if (names.some(function (name) { return PLAN_SHAPE_OPERATIONS.has(name); })) return 'plan';
        if (names.some(function (name) { return SITE_OPERATIONS.has(name); })) return 'site';
        if (appearanceOnlyAlternative(alternative, layout)) return '3d';
        if (names.some(function (name) { return MODEL_OPERATIONS.has(name); })) return '3d';
        return 'plan';
    }

    // A step applied directly (Apply Directly mode) moves the view as its review would have opened.
    const PAINT_OPERATIONS = new Set(['set_component_materials', 'set_appearance', 'set_scene',
        'edit_perimeter_walls', 'set_ground', 'upsert_wall_artwork', 'upsert_decal']);

    // Reference points show only on the site photo. Every other outdoor change (truck court, car park, drives) shows in
    // 3D too, so a step applied while 3D is open stays there (the user, 2026-10-24: stay in 3D once the building is in).
    const SITE_PHOTO_OPERATIONS = new Set(['upsert_site_reference', 'delete_site_reference']);

    function directApplyViewFor(names, current) {
        if (!Array.isArray(names) || !names.length) return null;
        if (names.some(function (name) { return PLAN_SHAPE_OPERATIONS.has(name); })) return 'plan';
        if (names.some(function (name) { return SITE_OPERATIONS.has(name); })) {
            const photoOnly = names.some(function (name) { return SITE_PHOTO_OPERATIONS.has(name); });
            return current === '3d' && !photoOnly ? '3d' : 'site';
        }
        if (names.some(function (name) { return MODEL_OPERATIONS.has(name); })) return '3d';
        if (names.every(function (name) { return PAINT_OPERATIONS.has(name); })) return '3d';
        return 'plan';
    }

    function activeLayoutAlternative(state) {
        const proposal = state && state.layoutProposal;
        if (!proposal || !Array.isArray(proposal.alternatives)
                || !proposal.alternatives.length) {
            return null;
        }
        return proposal.alternatives[proposal.selectedIndex] || null;
    }

    function recordIndex(records, identityKey) {
        const index = new Map();
        (Array.isArray(records) ? records : []).forEach(function (record) {
            const identifier = cleanString(
                record && record[identityKey],
                ''
            );
            if (identifier && !index.has(identifier)) {
                index.set(identifier, record);
            }
        });
        return index;
    }

    function placementSpatialSignature(placement) {
        const source = placement || {};
        return JSON.stringify({
            assetId: source.assetId || '',
            assetDefinitionRevision:
                source.assetDefinitionRevision || '',
            transform: source.transform || null,
        });
    }

    function collectionChangeCounts(before, after, identityKey) {
        const beforeIndex = recordIndex(before, identityKey);
        const afterIndex = recordIndex(after, identityKey);
        let added = 0;
        let changed = 0;
        let removed = 0;
        afterIndex.forEach(function (record, identifier) {
            if (!beforeIndex.has(identifier)) {
                added += 1;
            } else if (JSON.stringify(beforeIndex.get(identifier))
                    !== JSON.stringify(record)) {
                changed += 1;
            }
        });
        beforeIndex.forEach(function (record, identifier) {
            if (!afterIndex.has(identifier)) removed += 1;
        });
        return { added: added, changed: changed, removed: removed };
    }

    function collectionChangeReview(before, after, identityKey) {
        const beforeIndex = recordIndex(before, identityKey);
        const afterIndex = recordIndex(after, identityKey);
        const addedIds = [];
        const changedIds = [];
        const removedIds = [];
        const beforeRecords = [];
        const proposedRecords = [];
        afterIndex.forEach(function (record, identifier) {
            const original = beforeIndex.get(identifier);
            if (!original) {
                addedIds.push(identifier);
                proposedRecords.push(clone(record));
            } else if (JSON.stringify(original) !== JSON.stringify(record)) {
                changedIds.push(identifier);
                beforeRecords.push(clone(original));
                proposedRecords.push(clone(record));
            }
        });
        beforeIndex.forEach(function (record, identifier) {
            if (afterIndex.has(identifier)) return;
            removedIds.push(identifier);
            beforeRecords.push(clone(record));
        });
        const byIdentifier = function (left, right) {
            return String(left[identityKey]).localeCompare(
                String(right[identityKey])
            );
        };
        return {
            addedIds: addedIds.sort(),
            changedIds: changedIds.sort(),
            removedIds: removedIds.sort(),
            beforeRecords: beforeRecords.sort(byIdentifier),
            proposedRecords: proposedRecords.sort(byIdentifier),
        };
    }

    function buildLayoutProposalReview(savedLayout, proposedLayout) {
        const before = savedLayout && typeof savedLayout === 'object'
            ? savedLayout : {};
        const after = proposedLayout && typeof proposedLayout === 'object'
            ? proposedLayout : {};
        const beforeIndex = recordIndex(before.placements, 'placementId');
        const afterIndex = recordIndex(after.placements, 'placementId');
        const newPlacementIds = [];
        const movedPlacementIds = [];
        const removedPlacementIds = [];
        const beforePlacements = [];
        const proposedPlacements = [];
        const routeReview = collectionChangeReview(
            before.routes,
            after.routes,
            'routeId'
        );

        afterIndex.forEach(function (placement, placementId) {
            const original = beforeIndex.get(placementId);
            if (!original) {
                newPlacementIds.push(placementId);
                proposedPlacements.push(clone(placement));
                return;
            }
            if (placementSpatialSignature(original)
                    !== placementSpatialSignature(placement)) {
                movedPlacementIds.push(placementId);
                beforePlacements.push(clone(original));
                proposedPlacements.push(clone(placement));
            }
        });
        beforeIndex.forEach(function (placement, placementId) {
            if (afterIndex.has(placementId)) return;
            removedPlacementIds.push(placementId);
            beforePlacements.push(clone(placement));
        });

        newPlacementIds.sort();
        movedPlacementIds.sort();
        removedPlacementIds.sort();
        beforePlacements.sort(function (left, right) {
            return left.placementId.localeCompare(right.placementId);
        });
        proposedPlacements.sort(function (left, right) {
            return left.placementId.localeCompare(right.placementId);
        });
        return {
            newPlacementIds: newPlacementIds,
            movedPlacementIds: movedPlacementIds,
            removedPlacementIds: removedPlacementIds,
            beforePlacements: beforePlacements,
            proposedPlacements: proposedPlacements,
            newRouteIds: routeReview.addedIds,
            changedRouteIds: routeReview.changedIds,
            removedRouteIds: routeReview.removedIds,
            beforeRoutes: routeReview.beforeRecords,
            proposedRoutes: routeReview.proposedRecords,
            zoneChanges: collectionChangeCounts(
                before.zones,
                after.zones,
                'zoneId'
            ),
            routeChanges: collectionChangeCounts(
                before.routes,
                after.routes,
                'routeId'
            ),
        };
    }

    function proposalPreviewDescriptor(state, alternative) {
        const proposedLayout = alternative
            && alternative.ghostPreview
            && alternative.ghostPreview.layout;
        const savedLayout = state && state.layout;
        if (!savedLayout || !proposedLayout) return null;
        return Object.assign({
            active: true,
            proposalId: cleanString(alternative.proposalId, ''),
            alternativeId: cleanString(alternative.alternativeId, ''),
        }, buildLayoutProposalReview(savedLayout, proposedLayout));
    }

    function designProposalPreviewDescriptor(savedLayout, proposal, brief) {
        const proposedLayout = proposal && proposal.candidateLayout;
        if (!savedLayout || !proposedLayout) return null;
        const body = brief && brief.semanticBody || {};
        const preservedPlacementIds = [];
        const preservedRouteIds = [];
        (body.hardConstraints || []).filter(function (constraint) {
            return constraint.status === 'active';
        }).forEach(function (constraint) {
            (constraint.targetRefs || []).forEach(function (ref) {
                if (ref.entityKind === 'placement') {
                    preservedPlacementIds.push(ref.entityId);
                } else if (ref.entityKind === 'route') {
                    preservedRouteIds.push(ref.entityId);
                }
            });
        });
        return Object.assign({
            active: true,
            proposalId: cleanString(proposal.proposalId, ''),
            alternativeId: '',
            reviewKind: 'facility_design_proposal',
            preservedPlacementIds: Array.from(
                new Set(preservedPlacementIds)
            ).sort(),
            preservedRouteIds: Array.from(
                new Set(preservedRouteIds)
            ).sort(),
        }, buildLayoutProposalReview(savedLayout, proposedLayout));
    }

    function shortBindingValue(value) {
        const text = cleanString(value, '');
        if (!text) return 'not reported';
        return text.length <= 14 ? text : text.slice(0, 10) + '...';
    }

    function proposalBindingSummary(layoutProposal, alternative) {
        const binding = alternative
            && alternative.transactionBinding
            && typeof alternative.transactionBinding === 'object'
            ? alternative.transactionBinding : {};
        const sourceRevisions = layoutProposal
            && layoutProposal.request
            && layoutProposal.request.sourceRevisions
            && typeof layoutProposal.request.sourceRevisions === 'object'
            ? layoutProposal.request.sourceRevisions : {};
        return boundedText(
            'Proposal binding: map '
            + shortBindingValue(
                binding.baseRevision
                || (layoutProposal && layoutProposal.baseRevision)
            )
            + '; dependency '
            + shortBindingValue(binding.dependencyFingerprint)
            + '; diff ' + shortBindingValue(binding.diffHash)
            + '; shell ' + shortBindingValue(sourceRevisions.shell)
            + '; policy ' + shortBindingValue(sourceRevisions.policy)
            + '.',
            280
        );
    }

    function firstFiniteMetric(metrics, names) {
        for (let index = 0; index < names.length; index += 1) {
            const value = Number(metrics && metrics[names[index]]);
            if (Number.isFinite(value)) return value;
        }
        return null;
    }

    function proposalDiagnosticSummary(alternative) {
        const source = alternative || {};
        const metrics = source.metrics && typeof source.metrics === 'object'
            ? source.metrics : {};
        const findings = Array.isArray(source.findings) ? source.findings : [];
        function countFindings(severity) {
            return findings.filter(function (finding) {
                return String(
                    finding && (finding.severity || finding.level) || ''
                ).toLowerCase() === severity;
            }).length;
        }
        const errors = firstFiniteMetric(
            metrics,
            ['spatialErrorCount', 'errorCount']
        );
        const warnings = firstFiniteMetric(
            metrics,
            ['spatialWarningCount', 'warningCount']
        );
        const unverified = firstFiniteMetric(
            metrics,
            ['spatialUnverifiedCount', 'unverifiedCount']
        );
        const collisions = firstFiniteMetric(
            metrics,
            ['placementCollisions', 'physicalCollisions']
        );
        const clearance = firstFiniteMetric(
            metrics,
            ['clearanceConflicts']
        );
        const baselineClearance = firstFiniteMetric(
            metrics,
            ['baselineClearanceConflicts', 'clearanceConflictsBefore']
        );
        let clearanceDelta = firstFiniteMetric(
            metrics,
            ['clearanceConflictDelta', 'clearanceConflictsDelta']
        );
        if (clearanceDelta === null
                && clearance !== null
                && baselineClearance !== null) {
            clearanceDelta = clearance - baselineClearance;
        }
        const parts = [
            'errors ' + (errors === null ? countFindings('error') : errors),
            'warnings ' + (
                warnings === null ? countFindings('warning') : warnings
            ),
            'unverified ' + (
                unverified === null
                    ? countFindings('unverified') : unverified
            ),
            'collisions ' + (
                collisions === null ? 'not reported' : collisions
            ),
        ];
        if (clearance === null) {
            parts.push('clearance conflicts not reported');
        } else if (clearanceDelta === null) {
            parts.push(
                'clearance conflicts ' + clearance
                + ' (baseline comparison unavailable)'
            );
        } else {
            parts.push(
                'clearance conflicts ' + clearance
                + ' (difference '
                + (clearanceDelta > 0 ? '+' : '')
                + clearanceDelta + ')'
            );
        }
        if (Array.isArray(source.newHardFindingIds)) {
            parts.push(
                'new hard findings ' + source.newHardFindingIds.length
            );
        } else {
            parts.push('new-hard-finding comparison not reported');
        }
        return boundedText('Proposal diagnostics: ' + parts.join('; ') + '.', 360);
    }

    // Plain-language lines for the proposal card. The engineering detail (bindings,
    // full diagnostics) stays in the card's collapsed technical details.
    function countPhrase(count, singular, plural) {
        return count + ' ' + (count === 1 ? singular : plural);
    }

    function proposalPlainChangeSummary(review, alternative) {
        const source = review || {};
        const zones = source.zoneChanges || {};
        const routes = source.routeChanges || {};
        const parts = [];
        [
            [(source.newPlacementIds || []).length, 'new item', 'new items'],
            [(source.movedPlacementIds || []).length, 'moved item', 'moved items'],
            [(source.removedPlacementIds || []).length, 'removed item', 'removed items'],
            [finite(zones.added, 0), 'new zone', 'new zones'],
            [finite(zones.changed, 0), 'changed zone', 'changed zones'],
            [finite(zones.removed, 0), 'removed zone', 'removed zones'],
            [finite(routes.added, 0), 'new aisle', 'new aisles'],
            [finite(routes.changed, 0), 'changed aisle', 'changed aisles'],
            [finite(routes.removed, 0), 'removed aisle', 'removed aisles'],
        ].forEach(function (item) {
            if (item[0] > 0) parts.push(countPhrase(item[0], item[1], item[2]));
        });
        const siteEdits = ((alternative || {}).operations || []).filter(function (operation) {
            return ['set_site_context', 'set_building_pose', 'upsert_site_area',
                'delete_site_area', 'upsert_site_reference', 'delete_site_reference'].includes(operation.op);
        }).length;
        if (siteEdits) parts.push(countPhrase(siteEdits, 'site edit', 'site edits'));
        const repainted = ((alternative || {}).operations || []).filter(function (operation) {
            return operation.op === 'set_component_materials' || operation.op === 'set_appearance';
        }).length;
        if (repainted) parts.push(countPhrase(repainted, 'repainted item', 'repainted items'));
        return parts.length
            ? 'Changes: ' + parts.join(', ') + '.'
            : 'No items, zones or aisles change.';
    }

    function proposalPlainCheckSummary(alternative) {
        const source = alternative || {};
        const metrics = source.metrics && typeof source.metrics === 'object'
            ? source.metrics : {};
        const findings = Array.isArray(source.findings) ? source.findings : [];
        // The server's check counts (agent previews) come first; option metrics and
        // findings (Auto Arrange) are the fallback.
        const checks = source.validationSummary && typeof source.validationSummary === 'object'
            ? source.validationSummary : null;
        function countFindings(severity) {
            return findings.filter(function (finding) {
                return String(
                    finding && (finding.severity || finding.level) || ''
                ).toLowerCase() === severity;
            }).length;
        }
        function total(values) {
            const known = values.filter(function (value) {
                return value !== null && value !== undefined && Number.isFinite(Number(value));
            });
            return known.length ? known.reduce(function (sum, value) {
                return sum + Number(value);
            }, 0) : null;
        }
        const errors = checks
            ? total([checks.errorCount, checks.routingErrorCount])
            : firstFiniteMetric(metrics, ['spatialErrorCount', 'errorCount']);
        const warnings = checks
            ? total([checks.warningCount])
            : firstFiniteMetric(metrics, ['spatialWarningCount', 'warningCount']);
        const collisions = checks
            ? total([checks.placementCollisions, checks.shellObstacleCollisions])
            : firstFiniteMetric(metrics, ['placementCollisions', 'physicalCollisions']);
        const clearance = checks ? total([checks.clearanceConflicts]) : null;
        const blockedAisles = checks ? total([checks.obstructedAisleCount]) : null;
        const blockedRoutes = checks ? total([checks.blockedRouteCount]) : null;
        if (!checks && errors === null && warnings === null && collisions === null
                && !findings.length) {
            // Saying "no problems" without any check results would overstate them.
            return { text: 'Checks: no results came with this preview.', status: 'unknown' };
        }
        const errorCount = errors === null ? countFindings('error') : errors;
        const warningCount = warnings === null ? countFindings('warning') : warnings;
        const problems = [];
        if (errorCount > 0) problems.push(countPhrase(errorCount, 'error', 'errors'));
        if (collisions > 0) problems.push(countPhrase(collisions, 'collision', 'collisions'));
        if (blockedAisles > 0) problems.push(countPhrase(blockedAisles, 'blocked aisle', 'blocked aisles'));
        if (blockedRoutes > 0) problems.push(countPhrase(blockedRoutes, 'blocked route', 'blocked routes'));
        if (clearance > 0) {
            problems.push(countPhrase(clearance, 'clearance conflict', 'clearance conflicts'));
        }
        if (warningCount > 0) problems.push(countPhrase(warningCount, 'warning', 'warnings'));
        if (checks && checks.siteFindingCount > 0) {
            problems.push(countPhrase(checks.siteFindingCount, 'site finding', 'site findings'));
        }
        // Unverified items and unreported checks stay in the technical details.
        return {
            text: problems.length
                ? 'Checks: ' + problems.join(', ') + '.'
                : 'Checks: no problems found.',
            status: errorCount > 0 || collisions > 0 || blockedAisles > 0 || blockedRoutes > 0
                ? 'error' : problems.length ? 'warning' : 'ok',
        };
    }

    function readableProposalStrategy(strategy) {
        const text = String(strategy || '').trim();
        // Internal identifiers such as exact-operations-v1 mean nothing to a reviewer.
        if (!text || /^exact[-_ ]?operations/i.test(text)) return '';
        return boundedText(text.replace(/[_-]+/g, ' '), 48);
    }

    function proposalChangeSummary(review) {
        const source = review || {};
        const zones = source.zoneChanges || {};
        const routes = source.routeChanges || {};
        return boundedText(
            'Changes: '
            + (source.newPlacementIds || []).length + ' new assets, '
            + (source.movedPlacementIds || []).length + ' moved assets, '
            + (source.removedPlacementIds || []).length + ' removed assets; '
            + finite(zones.added, 0) + ' new, '
            + finite(zones.changed, 0) + ' changed, '
            + finite(zones.removed, 0) + ' removed zones; '
            + finite(routes.added, 0) + ' new, '
            + finite(routes.changed, 0) + ' changed, '
            + finite(routes.removed, 0) + ' removed routes.',
            300
        );
    }

    function zoneDimensions(zone) {
        const points = zone && Array.isArray(zone.boundary) ? zone.boundary : [];
        if (!points.length) return null;
        let minX = Infinity;
        let minZ = Infinity;
        let maxX = -Infinity;
        let maxZ = -Infinity;
        points.forEach(function (point) {
            const x = finite(point && point.x, NaN);
            const z = finite(point && point.z, NaN);
            if (!Number.isFinite(x) || !Number.isFinite(z)) return;
            minX = Math.min(minX, x);
            maxX = Math.max(maxX, x);
            minZ = Math.min(minZ, z);
            maxZ = Math.max(maxZ, z);
        });
        if (!Number.isFinite(minX)) return null;
        return {
            minX: minX,
            minZ: minZ,
            maxX: maxX,
            maxZ: maxZ,
            width: maxX - minX,
            depth: maxZ - minZ,
            center: {
                x: (minX + maxX) / 2,
                y: finite(zone.floorElevation, 0),
                z: (minZ + maxZ) / 2,
            },
        };
    }

    function quaternionYawDegrees(value) {
        const q = value || {};
        const x = finite(q.x, 0);
        const y = finite(q.y, 0);
        const z = finite(q.z, 0);
        const w = finite(q.w, 1);
        const radians = Math.atan2(
            2 * (w * y + x * z),
            1 - 2 * (y * y + z * z)
        );
        let degrees = radians * 180 / Math.PI;
        if (degrees < 0) degrees += 360;
        return Number(degrees.toFixed(6));
    }

    function targetDataId(target, attribute, boundary) {
        let current = target;
        while (current && current !== boundary) {
            if (typeof current.getAttribute === 'function') {
                const value = current.getAttribute(attribute);
                if (value) return value;
            }
            current = current.parentNode;
        }
        return null;
    }

    function isTypingTarget(target) {
        const name = String(target && target.nodeName || '').toLowerCase();
        return name === 'input' || name === 'textarea' || name === 'select'
            || Boolean(target && target.isContentEditable);
    }

    function isDialogDragControl(target, boundary) {
        let current = target;
        while (current && current !== boundary) {
            const name = String(current.nodeName || '').toLowerCase();
            if (name === 'button' || name === 'input' || name === 'select'
                    || name === 'textarea' || name === 'a'
                    || current.isContentEditable) return true;
            current = current.parentNode;
        }
        return false;
    }

    function selectionRecord(layout, selection) {
        if (!layout || !Array.isArray(selection) || selection.length !== 1) return null;
        const id = selection[0];
        const placement = layout.placements.find(function (item) {
            return item.placementId === id;
        });
        if (placement) return { kind: 'placement', value: placement };
        const zone = layout.zones.find(function (item) {
            return item.zoneId === id;
        });
        if (zone) return { kind: 'zone', value: zone };
        const marking = (layout.floorMarkings || []).find(function (item) {
            return item.markingId === id;
        });
        if (marking) return { kind: 'floor-marking', value: marking };
        const route = (layout.routes || []).find(function (item) {
            return item.routeId === id;
        });
        return route ? { kind: 'aisle', value: route } : null;
    }

    function Workspace(inputOptions) {
        const options = assertObject(inputOptions || {}, 'workspace options');
        this.options = options;
        this.root = options.root;
        if (!this.root || !this.root.ownerDocument) {
            throw new TypeError('workspace root with ownerDocument is required');
        }
        this.document = this.root.ownerDocument;
        this.session = options.session;
        if (!this.session || typeof this.session.subscribe !== 'function'
                || typeof this.session.getState !== 'function') {
            throw new TypeError('FacilitySession instance is required');
        }
        this.layoutRuntime = options.layoutRuntime
            || (root && root.InspectorProFacilityLayout);
        this.navigationRuntime = options.navigationRuntime
            || (root && root.InspectorProFacilityNavigationAuthoring)
            || null;
        if (!options.controller && (!this.layoutRuntime
                || typeof this.layoutRuntime.createEditor !== 'function'
                || typeof this.layoutRuntime.createTopPlanAdapter !== 'function')) {
            throw new TypeError('FacilityLayout runtime or controller is required');
        }
        this.assetCatalog = normalizeCatalog(options.assetCatalog || []);
        this.capabilities = Object.assign({
            assetLibrary: true,
            manualAuthoring: true,
            authoritativePreview: true,
            automaticRouting: true,
            prototypeMotion: false,
            navigationContract: true,
            navigationManual: true,
            navigationPedestrian: true,
            navigationVehicle: true,
            navigationHandoff: true,
            navigationMultiActor: true,
            navigationSageWrite: true,
            designBrief: true,
            designLoopPreview: true,
            designLoopApply: true,
            constructionPreview: false,
            generationPlanning: false,
            constructionApply: false,
            agentWrite: true,
            fullLayoutProposals: true,
            atomicProposalApply: true,
        }, options.capabilities || {});
        this.externalCommandSurface = options.externalCommandSurface === true;
        this.gridSize = finite(options.gridSize, DEFAULT_GRID_SIZE);
        if (this.gridSize <= 0) this.gridSize = DEFAULT_GRID_SIZE;
        this.eventToWorld = options.eventToWorld || options.worldPointFromPointer;
        this.marqueeResolver = typeof options.marqueeResolver === 'function'
            ? options.marqueeResolver : null;
        this.toolMode = 'select';
        this.viewMode = 'plan';
        this.threeNavigationMode = 'orbit';
        this.threeGridVisible = true;
        this.threeCompassOrientation = compassHeading(0);
        this.threeWalkthrough = {
            supported: false,
            active: false,
            locked: false,
            reason: null,
            route: {
                active: false,
                reason: null,
            },
        };
        this.threeDrone = {
            supported: false,
            active: false,
            locked: false,
            assistedFlight: true,
            altitude: 0,
            currentSpeed: 0,
            nearestObstacleDistance: null,
            reason: null,
        };
        this.motionTransport = options.motionTransport || null;
        this.designTransport = options.designTransport || null;
        this.designTurnSequence = 0;
        this.designPreviewGeneration = 0;
        this.designState = {
            active: false,
            collapsed: false,
            busy: false,
            status: 'idle',
            error: null,
            attentionKind: null,
            attentionRefs: [],
            brief: null,
            run: null,
            baseline: null,
            proposals: [],
            selectedProposal: null,
            transaction: null,
            proposalPreviewVisible: false,
            lastPreviewStartedAt: null,
            lastPreviewVisibleAt: null,
        };
        this.designAttentionSelectionFrame = null;
        this.motionPresentation = null;
        this.motionLayoutFingerprint = null;
        this.motionRequestPending = false;
        this.motionState = {
            loaded: false,
            status: 'idle',
            statusReason: null,
            packageId: null,
            movementId: null,
            outcome: null,
            vehiclePlacementId: null,
            vehiclePresentation: null,
            laneBinding: null,
            following: false,
            playing: false,
            elapsedSeconds: 0,
            durationSeconds: 0,
            playbackRateMultiplier: 1,
            distanceMeters: 0,
            totalDistanceMeters: 0,
            pose: null,
            clearanceAtValidatedSample: null,
            sampleSpacingMeters: null,
            prefersReducedMotion: false,
            qualification: null,
            disclosure: null,
            plannerDurationEstimate: false,
            blocking: null,
            prototypeMode: false,
            prototypeLabel: null,
        };
        this.activityPresentation = null;
        this.activityLayoutFingerprint = null;
        this.activityRequestPending = false;
        this.activityState = {
            loaded: false,
            scenarioId: null,
            label: null,
            status: 'idle',
            statusReason: null,
            playing: false,
            elapsedSeconds: 0,
            durationSeconds: 0,
            playbackRateMultiplier: 1,
            selectedActorId: null,
            visibleActorTypes: {
                vehicle: true,
                operator: true,
                mobile_equipment: true,
            },
            pathsVisible: true,
            departmentZoneId: null,
            actors: [],
            stationaryEvidence: null,
            unavailableActivity: [],
            prototypeMode: false,
            qualification: null,
            disclosure: null,
        };
        this.walkthroughContextState = {
            focus: null,
            expanded: false,
            pinned: false,
            pinnedPlacementId: null,
            mode: 'production',
        };
        this.recordingRuntime = options.recordingRuntime
            || (root && root.InspectorProFacilityRecorder) || null;
        this.patternRuntime = options.patternRuntime
            || (root && root.InspectorProFacilityPatterns) || null;
        this.recordingController = null;
        this.recordingCountdownTimer = null;
        this.recordingCountdownSeconds = Math.max(
            0,
            Math.min(10, Math.round(finite(
                options.recordingCountdownSeconds,
                3
            )))
        );
        this.recordingCursor = { x: 0.5, y: 0.5, visible: false };
        this.recordingState = {
            status: 'idle',
            panelOpen: false,
            previewOpen: false,
            countdown: 0,
            elapsedMs: 0,
            paused: false,
            error: null,
            format: null,
            filename: null,
            settings: {
                presentationMode: 'clean',
                resolution: 'current',
                fps: 30,
                microphone: false,
                includeHud: false,
                includeCursor: false,
            },
        };
        this.threeSettingsOpen = false;
        this.threeViewMenuOpen = false;
        this.threeViewpointsOpen = false;
        this.layerPanelOpen = false;
        this.layerVisibility = normalizeLayerVisibility(
            options.layerVisibility
        );
        this.threeOrientation = 'iso';
        this.threeVisualSettings = normalizeThreeVisualSettings(
            options.threeVisualSettings
        );
        this.state = this.session.getState();
        let planPreferenceStorage = options.planPreferenceStorage || null;
        if (!planPreferenceStorage) {
            try {
                planPreferenceStorage = root && root.sessionStorage;
            } catch (error) {
                planPreferenceStorage = null;
            }
        }
        const layoutId = cleanString(
            this.state && this.state.layout && this.state.layout.layoutId,
            'default'
        );
        this.planPreferenceStorage = planPreferenceStorage;
        this.planPreferenceKey = cleanString(
            options.planPreferenceKey,
            PLAN_VIEW_PREFERENCE_PREFIX + layoutId
        );
        this.threeViewpointKey = cleanString(
            options.threeViewpointKey,
            THREE_VIEWPOINT_PREFIX + layoutId
        );
        this.threeViewpoints = loadThreeViewpoints(
            this.planPreferenceStorage,
            this.threeViewpointKey
        );
        this.planPreferences = loadPlanPreferences(
            this.planPreferenceStorage,
            this.planPreferenceKey,
            Object.assign({
                unit: options.topPlanOptions
                    && options.topPlanOptions.displayUnit,
                showGrid: !options.topPlanOptions
                    || options.topPlanOptions.showGrid !== false,
                snapToGrid: true,
            }, options.planPreferences || {})
        );
        const configuredBounds = options.topPlanOptions
            && options.topPlanOptions.worldBounds || {};
        const fallbackPlanSettings = normalizePlanSettings({
            widthMeters: finite(configuredBounds.maxX, DEFAULT_PLAN_WIDTH_METERS)
                - finite(configuredBounds.minX, 0),
            depthMeters: finite(configuredBounds.maxZ, DEFAULT_PLAN_DEPTH_METERS)
                - finite(configuredBounds.minZ, 0),
            gridSpacingMeters: options.topPlanOptions
                && options.topPlanOptions.floorGridSpacing !== undefined
                ? options.topPlanOptions.floorGridSpacing
                : options.gridSize,
            majorGridSpacingMeters: options.topPlanOptions
                && options.topPlanOptions.floorMajorGridSpacing,
        });
        this.planSettings = planSettingsFromLayout(
            this.state && this.state.layout,
            fallbackPlanSettings
        );
        this.planSettingsState = {
            open: false,
            applying: false,
            focusField: 'widthMeters',
            draft: clone(this.planSettings),
            scaleDistanceMeters: null,
            originalScale: null,
        };
        this.clearAllState = {
            open: false,
            applying: false,
            focusReturn: null,
        };
        this.bulkZoneState = {
            open: false,
            applying: false,
            focusReturn: null,
            nextRowId: 2,
            rows: [{
                rowId: 'zone-row-1',
                label: 'Zone 1',
                zoneType: 'workcell',
                minX: 0,
                minZ: 0,
                width: 10,
                depth: 8,
                color: '#4a90c2',
            }],
        };
        this.cellGroupSequence = 0;
        this.cellGroupState = {
            open: false,
            applying: false,
            focusReturn: null,
            baseName: 'Manufacturing Cell',
            prefix: 'A',
            start: 1,
            numberPadding: 2,
            envelopePadding: 1,
            color: '#2f80b9',
            gateSide: '',
            loadingSide: '',
            serviceSide: '',
        };
        this.aisleState = {
            open: false,
            drawing: false,
            focusReturn: null,
            sequence: 1,
            label: 'Forklift Aisle 1',
            aisleKind: 'forklift',
            direction: 'two_way',
            corridorWidth: 3.6,
            color: '#d9a514',
        };
        this.navigationState = {
            open: false,
            drawing: false,
            anchorPicking: false,
            applying: false,
            focusReturn: null,
            sequence: 1,
            actorPlacementId: null,
            actorClass: null,
            actorProfileId: '',
            actorProfileRevision: '',
            loopMode: 'closed_loop',
            direction: 'forward',
            constraintMode: 'complete_override',
            points: [],
            snapRefs: [],
            lockedSegmentIndexes: [],
            selectedPointIndex: null,
            selectedSegmentIndex: null,
            pathsVisible: true,
            previewLoaded: false,
            previewPlaying: false,
            previewNormalizedTime: 0,
            validationStatus: 'pending',
            validation: null,
            anchorKind: 'station_operate',
            anchorOwnerPlacementId: '',
            message: '',
            lastConstraintId: null,
        };
        this.gridSize = this.planSettings.gridSpacingMeters;
        const initialEnvironment = {
            worldBounds: worldBoundsFromPlanSettings(
                this.planSettings,
                configuredBounds
            ),
            floorGridSpacing: this.planSettings.gridSpacingMeters,
            floorMajorGridSpacing: this.planSettings.majorGridSpacingMeters,
        };
        options.topPlanOptions = Object.assign(
            {},
            options.topPlanOptions || {},
            initialEnvironment
        );
        options.threeOptions = Object.assign(
            {},
            options.threeOptions || {},
            initialEnvironment
        );
        this.destroyed = false;
        this.suspended = false;
        this.suspendedChildren = [];
        this.listeners = [];
        this.pending = Promise.resolve();
        this.lastError = null;
        this.activeDrag = null;
        this.dragAdvisory = null;
        this.spatialAdvisor = options.spatialAdvisor || null;
        this.ownsSpatialAdvisor = options.ownsSpatialAdvisor === true;
        this.useAuthoritativePlacementCandidates =
            options.useAuthoritativePlacementCandidates === true;
        this.pointerGesture = null;
        this.pointerCaptureId = null;
        this.pointerFallbackCleanup = null;
        this.polygonPoints = [];
        this.suppressAdapterSelection = null;
        this.lastLayoutFingerprint = null;
        this.lastLayoutFitFingerprint = null;
        this.lastProposalRepaintOnly = false;
        this.lastThreeFitFingerprint = null;
        this.commandStates = {};
        this.unsubscribe = null;
        // Listeners for anything that changes what the viewport represents.
        // Fired from both refresh paths: the session broadcast, and
        // _syncController, which generation previews call directly without
        // notifying the session.
        this.structureListeners = [];
        this.marqueeCleanup = null;
        this.createdTopAdapter = false;
        this.createdThreeAdapter = false;
        this.ownsController = !options.controller;
        this.lastProposalVisualFingerprint = 'none';
        this.lastDirectApplyReceiptId = null;
        this.proposalFocusReturn = null;
        this.lastPointerWorld = { x: 0, y: 0, z: 0 };
        this.assetBrowserState = {
            open: false,
            query: '',
            category: 'All',
            selected: {},
            selectionOrder: [],
        };
        this.assetBrowserSubmitting = false;
        this.assetBrowserFocusReturn = null;
        this.floorMarkingState = {
            open: false,
            type: 'direction_arrow',
        };
        this.geometryInspectorCollapsed = false;
        this.precisionState = {
            open: false,
            mode: 'align',
            alignMode: 'left',
            anchorId: '',
            distributeAxis: 'x',
            distributeMethod: 'equal-gap',
            distributeGap: 1,
            referenceId: '',
            movingId: '',
            relation: 'east',
            relativeAlignment: 'center',
            relativeDistance: 1,
            distanceMode: 'horizontal-gap',
            requestedDistance: 1,
            offsetX: 1,
            offsetZ: 0,
            createCopies: false,
        };
        this.precisionFocusReturn = null;
        this.precisionMessage = '';
        this.patternState = {
            open: false,
            mode: 'linear-pattern',
            count: 3,
            pitch: 4,
            linearDirection: 'horizontal',
            angleDegrees: 0,
            centerX: 0,
            centerZ: 0,
            sweepDegrees: 360,
            rotateWithPattern: false,
            perimeterShape: 'rectangle',
            perimeterWidthCount: 6,
            perimeterDepthCount: 4,
            perimeterClearGap: 0,
            shape: 'u',
            width: 10,
            depth: 8,
            gap: 1,
            rows: 2,
            orientation: 'preserve',
            invertU: false,
            stackCount: 3,
            stackGap: 0,
            surfaceSupportId: '',
            surfaceId: 'derived-top',
            surfaceSide: 'above',
            surfaceGap: 0,
            surfaceItemGap: 0.05,
            surfaceInset: 0.05,
            mirrorAxisMode: 'vertical',
            mirrorAxisX: 0,
            mirrorAxisZ: 0,
            mirrorAxisStart: null,
            mirrorAxisEnd: null,
            mirrorPicking: false,
            mirrorPickPoints: [],
            applying: false,
        };
        this.patternPreview = null;
        this.patternFocusReturn = null;
        this.patternMessage = '';
        this.movableDialogDrag = null;
        this.floatingDom = options.floatingDom
            || (root && root.FloatingUIDOM) || null;
        this.selectionToolbarManager = null;
        this.selectionToolbarElement = null;
        this.selectionToolbarReference = null;
        this.selectionToolbarKey = null;
        this._build();
        this._initializeSelectionToolbar();
        this._connectRendering();
        this._connectEvents();
        this.unsubscribe = this.session.subscribe(this._handleSessionState.bind(this));
        this._handleSessionState(this.state);
    }

    Workspace.prototype._listen = function (target, type, handler, options) {
        target.addEventListener(type, handler, options);
        this.listeners.push(function () {
            target.removeEventListener(type, handler, options);
        });
    };

    Workspace.prototype._button = function (command, label, keyHint) {
        const button = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-command',
            'data-command': command,
            'aria-label': label,
            title: keyHint ? label + ' (' + keyHint + ')' : label,
        });
        append(button,
            element(this.document, 'span', {
                className: 'ip-flw-command-icon',
                'aria-hidden': 'true',
            }, this.options.commandIcons && this.options.commandIcons[command]
                || label.charAt(0).toUpperCase()),
            element(this.document, 'span', {
                className: 'ip-flw-command-label',
            }, label)
        );
        return button;
    };

    Workspace.prototype._initializeSelectionToolbar = function () {
        const runtime = this.options.floatingSurfaceRuntime
            || (root && root.InspectorProFloating) || null;
        if (!runtime || typeof runtime.createSurfaceManager !== 'function'
                || !this.floatingDom) return false;
        const manager = runtime.createSurfaceManager({
            document: this.document,
            positioning: this.floatingDom,
        });
        if (!manager || manager.available === false) return false;
        this.selectionToolbarManager = manager;
        return true;
    };

    Workspace.prototype._selectedPlacementRecords = function () {
        if (!this.state || !this.state.layout
                || !Array.isArray(this.state.selection)) return [];
        const placementIds = new Set(
            (this.state.layout.placements || []).map(function (placement) {
                return placement.placementId;
            })
        );
        if (this.state.selection.some(function (identifier) {
            return !placementIds.has(identifier);
        })) return [];
        const placements = precisionPlacements(
            this.state.layout,
            this.state.selection
        );
        return placements.length === this.state.selection.length
            ? placements : [];
    };

    Workspace.prototype._selectedZoneRecord = function () {
        if (!this.state || !this.state.layout
                || !Array.isArray(this.state.selection)
                || this.state.selection.length !== 1) return null;
        const identifier = this.state.selection[0];
        return (this.state.layout.zones || []).find(function (zone) {
            return zone.zoneId === identifier;
        }) || null;
    };

    Workspace.prototype._selectedFloorMarkingRecord = function () {
        if (!this.state || !this.state.layout
                || !Array.isArray(this.state.selection)
                || this.state.selection.length !== 1) return null;
        const identifier = this.state.selection[0];
        return (this.state.layout.floorMarkings || []).find(function (marking) {
            return marking.markingId === identifier;
        }) || null;
    };

    Workspace.prototype._selectionToolbarCards = function (placementIds) {
        if (!this.planView || typeof this.planView.querySelectorAll !== 'function') {
            return [];
        }
        const identifiers = new Set(placementIds || []);
        return Array.prototype.filter.call(
            this.planView.querySelectorAll('.ip-flw-plan-card'),
            function (card) {
                return identifiers.has(card.getAttribute('data-placement-id'));
            }
        );
    };

    Workspace.prototype._selectionToolbarZoneElements = function (zoneId) {
        if (!this.planView || typeof this.planView.querySelectorAll !== 'function') {
            return [];
        }
        return Array.prototype.filter.call(
            this.planView.querySelectorAll('[data-zone-id]'),
            function (candidate) {
                return candidate.getAttribute('data-zone-id') === zoneId;
            }
        );
    };

    Workspace.prototype._selectionToolbarFloorMarkingElements = function (
        markingId
    ) {
        if (!this.planView || typeof this.planView.querySelectorAll !== 'function') {
            return [];
        }
        return Array.prototype.filter.call(
            this.planView.querySelectorAll('[data-floor-marking-id]'),
            function (candidate) {
                return candidate.getAttribute('data-floor-marking-id') === markingId;
            }
        );
    };

    Workspace.prototype._selectionToolbarVirtualReference = function (
        placementIds
    ) {
        const workspace = this;
        const identifiers = (placementIds || []).slice();
        return {
            contextElement: this.planView,
            getBoundingClientRect: function () {
                const cards = workspace._selectionToolbarCards(identifiers);
                if (!cards.length) {
                    return workspace.planView.getBoundingClientRect();
                }
                const bounds = cards.reduce(function (result, card) {
                    const rect = card.getBoundingClientRect();
                    const left = finite(rect.left, 0);
                    const top = finite(rect.top, 0);
                    const right = finite(rect.right, left + finite(rect.width, 0));
                    const bottom = finite(rect.bottom, top + finite(rect.height, 0));
                    return {
                        left: Math.min(result.left, left),
                        top: Math.min(result.top, top),
                        right: Math.max(result.right, right),
                        bottom: Math.max(result.bottom, bottom),
                    };
                }, {
                    left: Infinity,
                    top: Infinity,
                    right: -Infinity,
                    bottom: -Infinity,
                });
                return {
                    x: bounds.left,
                    y: bounds.top,
                    left: bounds.left,
                    top: bounds.top,
                    right: bounds.right,
                    bottom: bounds.bottom,
                    width: Math.max(0, bounds.right - bounds.left),
                    height: Math.max(0, bounds.bottom - bounds.top),
                };
            },
        };
    };

    Workspace.prototype._zoneToolbarVirtualReference = function (zoneId) {
        const workspace = this;
        return {
            contextElement: this.planView,
            getBoundingClientRect: function () {
                const elements = workspace._selectionToolbarZoneElements(zoneId);
                return elements.length
                    ? elements[0].getBoundingClientRect()
                    : workspace.planView.getBoundingClientRect();
            },
        };
    };

    Workspace.prototype._floorMarkingToolbarVirtualReference = function (
        markingId
    ) {
        const workspace = this;
        return {
            contextElement: this.planView,
            getBoundingClientRect: function () {
                const elements = workspace
                    ._selectionToolbarFloorMarkingElements(markingId);
                return elements.length
                    ? elements[0].getBoundingClientRect()
                    : workspace.planView.getBoundingClientRect();
            },
        };
    };

    Workspace.prototype._selectionToolbarMiddleware = function () {
        if (!this.floatingDom) return [];
        return [
            this.floatingDom.offset(9),
            this.floatingDom.flip({
                boundary: this.planView,
                fallbackPlacements: ['bottom'],
            }),
            this.floatingDom.shift({
                boundary: this.planView,
                padding: 12,
            }),
        ];
    };

    Workspace.prototype._selectionToolbarButton = function (command) {
        const spec = SELECTION_TOOLBAR_COMMANDS[command];
        const button = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-selection-command'
                + (command === 'delete' || command === 'delete-zone'
                    ? ' is-danger' : ''),
            'data-selection-command': command,
            'aria-label': spec.label,
            title: spec.label,
        });
        button.appendChild(element(this.document, 'img', {
            src: VIEWPORT_ICON_ROOT + spec.icon + '.svg',
            alt: '',
            draggable: 'false',
            'aria-hidden': 'true',
        }));
        return button;
    };

    Workspace.prototype._buildSelectionToolbar = function (placements) {
        const toolbar = element(this.document, 'div', {
            className: 'ip-floating-surface ip-flw-selection-toolbar',
            role: 'toolbar',
            'aria-orientation': 'horizontal',
            'aria-label': placements.length === 1
                ? 'Selected equipment actions'
                : placements.length + ' selected equipment actions',
            'data-facility-selection-toolbar': '',
        });
        if (placements.length > 1) {
            toolbar.appendChild(element(this.document, 'span', {
                className: 'ip-flw-selection-count',
                title: placements.length + ' equipment placements selected',
                'aria-hidden': 'true',
            }, String(placements.length)));
        }
        selectionToolbarCommands(placements.length).forEach(function (command) {
            toolbar.appendChild(this._selectionToolbarButton(command));
        }, this);
        toolbar.addEventListener(
            'click',
            this._handleSelectionToolbarClick.bind(this)
        );
        return toolbar;
    };

    Workspace.prototype._buildZoneToolbar = function (zone) {
        const toolbar = element(this.document, 'div', {
            className: 'ip-floating-surface ip-flw-selection-toolbar ip-flw-zone-toolbar',
            role: 'group',
            'aria-label': 'Selected zone name and actions',
            'data-facility-zone-toolbar': zone.zoneId,
        });
        const name = element(this.document, 'input', {
            type: 'text',
            className: 'ip-flw-zone-name-input',
            value: cleanString(zone.label, zone.zoneId),
            maxlength: '120',
            'data-zone-name': zone.zoneId,
            'aria-label': 'Zone name',
            title: 'Zone name',
        });
        const apply = this._selectionToolbarButton('save-zone-name');
        apply.setAttribute('data-zone-action', 'save-name');
        apply.removeAttribute('data-selection-command');
        const remove = this._selectionToolbarButton('delete-zone');
        remove.setAttribute('data-zone-action', 'delete');
        remove.removeAttribute('data-selection-command');
        append(
            toolbar,
            name,
            apply,
            this._selectionToolbarButton('mirror'),
            remove
        );
        toolbar.addEventListener('click', this._handleZoneToolbarClick.bind(this));
        toolbar.addEventListener('keydown', this._handleZoneToolbarKeyDown.bind(this));
        return toolbar;
    };

    Workspace.prototype._buildFloorMarkingToolbar = function (marking) {
        const toolbar = element(this.document, 'div', {
            className: 'ip-floating-surface ip-flw-selection-toolbar ip-flw-floor-marking-toolbar',
            role: 'group',
            'aria-label': 'Selected floor marking details and actions',
            'data-facility-floor-marking-toolbar': marking.markingId,
        });
        const name = element(this.document, 'input', {
            type: 'text',
            className: 'ip-flw-floor-marking-text-input',
            value: cleanString(marking.text, '')
                || cleanString(marking.label, marking.markingId),
            maxlength: '120',
            'data-floor-marking-text': marking.markingId,
            'aria-label': 'Floor marking label or text',
            title: 'Floor marking label or text',
        });
        const fill = element(this.document, 'input', {
            type: 'color',
            className: 'ip-flw-floor-marking-color-input',
            value: cleanString(marking.fillColor, '#ffffff'),
            'data-floor-marking-color': 'fillColor',
            'aria-label': 'Floor marking fill color',
            title: 'Fill color',
        });
        const stroke = element(this.document, 'input', {
            type: 'color',
            className: 'ip-flw-floor-marking-color-input',
            value: cleanString(marking.strokeColor, '#1f2937'),
            'data-floor-marking-color': 'strokeColor',
            'aria-label': 'Floor marking outline color',
            title: 'Outline color',
        });
        const apply = this._selectionToolbarButton('save-floor-marking');
        apply.setAttribute('data-floor-marking-action', 'save');
        apply.removeAttribute('data-selection-command');
        append(toolbar, name, fill, stroke, apply);
        ['rotate', 'duplicate', 'mirror', 'lock', 'delete'].forEach(
            function (command) {
            toolbar.appendChild(this._selectionToolbarButton(command));
            }, this
        );
        toolbar.addEventListener(
            'click',
            this._handleFloorMarkingToolbarClick.bind(this)
        );
        toolbar.addEventListener(
            'change',
            this._handleFloorMarkingToolbarChange.bind(this)
        );
        toolbar.addEventListener(
            'keydown',
            this._handleFloorMarkingToolbarKeyDown.bind(this)
        );
        return toolbar;
    };

    Workspace.prototype._applyFloorMarkingToolbar = function () {
        if (!this.selectionToolbarElement) return false;
        const marking = this._selectedFloorMarkingRecord();
        const input = this.selectionToolbarElement.querySelector(
            '[data-floor-marking-text]'
        );
        if (!marking || !input) return false;
        const labelOrText = String(input.value || '').trim();
        if (!labelOrText || labelOrText.length > 120) {
            this._setError(new Error(
                'Floor marking label must contain 1 to 120 characters'
            ));
            if (typeof input.focus === 'function') input.focus();
            return false;
        }
        input.value = labelOrText;
        const patch = { label: labelOrText };
        if (['floor_text', 'keep_clear', 'parking_box'].includes(
            marking.markingType
        )) {
            patch.text = labelOrText;
        }
        Array.prototype.forEach.call(
            this.selectionToolbarElement.querySelectorAll(
                '[data-floor-marking-color]'
            ),
            function (colorInput) {
                const field = colorInput.getAttribute('data-floor-marking-color');
                const value = String(colorInput.value || '').trim();
                if (/^#[0-9a-f]{6}$/i.test(value)) patch[field] = value;
            }
        );
        const changed = Object.keys(patch).some(function (field) {
            return patch[field] !== marking[field];
        });
        if (!changed) return true;
        this._invoke('Edit floor marking', function () {
            return this.session.editFloorMarking(marking.markingId, patch);
        }.bind(this));
        return true;
    };

    Workspace.prototype._handleFloorMarkingToolbarClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-floor-marking-action',
            this.selectionToolbarElement
        );
        if (action === 'save') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            if (typeof event.stopPropagation === 'function') event.stopPropagation();
            this._applyFloorMarkingToolbar();
            return;
        }
        this._handleSelectionToolbarClick(event);
    };

    Workspace.prototype._handleFloorMarkingToolbarChange = function (event) {
        if (!targetDataId(
            event.target,
            'data-floor-marking-color',
            this.selectionToolbarElement
        )) return;
        this._applyFloorMarkingToolbar();
    };

    Workspace.prototype._handleFloorMarkingToolbarKeyDown = function (event) {
        if (!event || !targetDataId(
            event.target,
            'data-floor-marking-text',
            this.selectionToolbarElement
        )) return;
        const key = String(event.key || '').toLowerCase();
        if (key === 'enter') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._applyFloorMarkingToolbar();
        } else if (key === 'escape') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            const marking = this._selectedFloorMarkingRecord();
            if (marking) {
                event.target.value = cleanString(marking.text, '')
                    || cleanString(marking.label, marking.markingId);
            }
        }
    };

    Workspace.prototype._applyZoneToolbarName = function () {
        if (!this.selectionToolbarElement) return false;
        const zone = this._selectedZoneRecord();
        const input = this.selectionToolbarElement.querySelector('[data-zone-name]');
        if (!zone || !input) return false;
        const label = String(input.value || '').trim();
        if (!label) {
            this._setError(new Error('Zone name cannot be empty'));
            if (typeof input.focus === 'function') input.focus();
            return false;
        }
        if (label.length > 120) {
            this._setError(new Error('Zone name must be 120 characters or fewer'));
            if (typeof input.focus === 'function') input.focus();
            return false;
        }
        input.value = label;
        if (label === zone.label) return true;
        this._invoke('Rename zone', function () {
            return this.session.editZoneLabel(zone.zoneId, label);
        }.bind(this));
        return true;
    };

    Workspace.prototype._handleZoneToolbarClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-zone-action',
            this.selectionToolbarElement
        );
        if (!action) {
            this._handleSelectionToolbarClick(event);
            return;
        }
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (typeof event.stopPropagation === 'function') event.stopPropagation();
        if (action === 'save-name') this._applyZoneToolbarName();
        else if (action === 'delete') this.executeCommand('delete');
    };

    Workspace.prototype._handleZoneToolbarKeyDown = function (event) {
        if (!event || !targetDataId(
            event.target,
            'data-zone-name',
            this.selectionToolbarElement
        )) return;
        const key = String(event.key || '').toLowerCase();
        if (key === 'enter') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._applyZoneToolbarName();
        } else if (key === 'escape') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            const zone = this._selectedZoneRecord();
            if (zone) event.target.value = cleanString(zone.label, zone.zoneId);
        }
    };

    Workspace.prototype._handleSelectionToolbarClick = function (event) {
        const command = targetDataId(
            event.target,
            'data-selection-command',
            this.selectionToolbarElement
        );
        if (!command) return;
        const button = this.selectionToolbarElement.querySelector(
            '[data-selection-command="' + command + '"]'
        );
        if (!button || button.disabled) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (typeof event.stopPropagation === 'function') event.stopPropagation();
        this.executeCommand(command);
    };

    Workspace.prototype._refreshSelectionToolbar = function () {
        if (!this.selectionToolbarElement) return false;
        const zoneInput = this.selectionToolbarElement.querySelector(
            '[data-zone-name]'
        );
        if (zoneInput) {
            zoneInput.disabled = Boolean(this.state.busy);
            Array.prototype.forEach.call(
                this.selectionToolbarElement.querySelectorAll('[data-zone-action]'),
                function (button) {
                    button.disabled = Boolean(this.state.busy);
                },
                this
            );
            return true;
        }
        const markingInput = this.selectionToolbarElement.querySelector(
            '[data-floor-marking-text]'
        );
        if (markingInput) {
            const marking = this._selectedFloorMarkingRecord();
            const active = this.document.activeElement;
            if (marking && active !== markingInput) {
                markingInput.value = cleanString(marking.text, '')
                    || cleanString(marking.label, marking.markingId);
            }
            Array.prototype.forEach.call(
                this.selectionToolbarElement.querySelectorAll(
                    '[data-floor-marking-color]'
                ),
                function (input) {
                    const field = input.getAttribute('data-floor-marking-color');
                    if (marking && active !== input) {
                        input.value = cleanString(marking[field], input.value);
                    }
                    input.disabled = Boolean(this.state.busy);
                },
                this
            );
            const apply = this.selectionToolbarElement.querySelector(
                '[data-floor-marking-action]'
            );
            if (apply) apply.disabled = Boolean(this.state.busy);
            markingInput.disabled = Boolean(this.state.busy);
        }
        Array.prototype.forEach.call(
            this.selectionToolbarElement.querySelectorAll(
                '[data-selection-command]'
            ),
            function (button) {
                const command = button.getAttribute('data-selection-command');
                const state = this.commandStates[command] || {};
                const spec = SELECTION_TOOLBAR_COMMANDS[command];
                const label = command === 'lock' && state.active
                    ? 'Unlock' : spec.label;
                button.disabled = Boolean(state.disabled || this.state.busy);
                button.setAttribute('aria-label', label);
                button.setAttribute('title', label);
                if (command === 'lock') {
                    button.setAttribute(
                        'aria-pressed',
                        state.active ? 'true' : 'false'
                    );
                }
            },
            this
        );
        return true;
    };

    Workspace.prototype._closeSelectionToolbar = function (
        reason,
        restoreFocus
    ) {
        if (!this.selectionToolbarManager) return false;
        const closed = this.selectionToolbarManager.close(
            reason || 'programmatic',
            { restoreFocus: restoreFocus === true }
        );
        if (!this.selectionToolbarManager.isOpen()) {
            this.selectionToolbarElement = null;
            this.selectionToolbarReference = null;
            this.selectionToolbarKey = null;
        }
        return closed;
    };

    Workspace.prototype._syncSelectionToolbar = function () {
        if (!this.selectionToolbarManager) return false;
        const placements = this._selectedPlacementRecords();
        const zone = placements.length ? null : this._selectedZoneRecord();
        const marking = placements.length || zone
            ? null : this._selectedFloorMarkingRecord();
        const unavailable = this.destroyed
            || this.suspended
            || this.viewMode !== 'plan'
            || this.toolMode !== 'select'
            || this.assetBrowserState.open
            || this.precisionState.open
            || this.bulkZoneState.open
            || this.cellGroupState.open
            || Boolean(this.state.conflict)
            || Boolean(this.state.layoutProposal)
            || Boolean(this.state.placementAlternatives)
            || (!placements.length && !zone && !marking);
        if (unavailable) {
            this._closeSelectionToolbar('selection_unavailable', false);
            return false;
        }
        const identifiers = zone ? [zone.zoneId]
            : marking ? [marking.markingId]
            : placements.map(function (placement) {
                return placement.placementId;
            });
        const anchors = zone
            ? this._selectionToolbarZoneElements(zone.zoneId)
            : marking
                ? this._selectionToolbarFloorMarkingElements(marking.markingId)
                : this._selectionToolbarCards(identifiers);
        if (anchors.length !== identifiers.length) {
            this._closeSelectionToolbar('anchor_unavailable', false);
            return false;
        }
        const key = (zone ? 'zone:' : marking ? 'marking:' : 'placements:')
            + identifiers.join('|');
        if (this.selectionToolbarManager.isOpen()
                && this.selectionToolbarKey === key
                && this.selectionToolbarElement) {
            this._refreshSelectionToolbar();
            this.selectionToolbarManager.reposition();
            return true;
        }
        this._closeSelectionToolbar('selection_changed', false);
        const toolbar = zone
            ? this._buildZoneToolbar(zone)
            : marking
                ? this._buildFloorMarkingToolbar(marking)
                : this._buildSelectionToolbar(placements);
        const reference = zone
            ? this._zoneToolbarVirtualReference(zone.zoneId)
            : marking
                ? this._floorMarkingToolbarVirtualReference(marking.markingId)
                : this._selectionToolbarVirtualReference(identifiers);
        this.selectionToolbarElement = toolbar;
        this.selectionToolbarReference = reference;
        this.selectionToolbarKey = key;
        const opened = this.selectionToolbarManager.open({
            key: key,
            reference: reference,
            floating: toolbar,
            placement: 'top',
            strategy: 'fixed',
            middleware: this._selectionToolbarMiddleware(),
            restoreFocusElement: anchors[0],
            shouldCloseOnOutsidePointerDown: function (event) {
                return !(event && this.planView.contains(event.target));
            }.bind(this),
            onClose: function () {
                if (this.selectionToolbarElement === toolbar) {
                    this.selectionToolbarElement = null;
                    this.selectionToolbarReference = null;
                    this.selectionToolbarKey = null;
                }
            }.bind(this),
        });
        if (!opened) {
            if (typeof toolbar.remove === 'function') toolbar.remove();
            this.selectionToolbarElement = null;
            this.selectionToolbarReference = null;
            this.selectionToolbarKey = null;
        } else {
            this._refreshSelectionToolbar();
        }
        return opened;
    };

    Workspace.prototype._planNavigationButton = function (
        command,
        label,
        glyph,
        icon,
        fallback
    ) {
        // The shortcut letter moves into the tooltip rather than being the
        // button face, which is where SOLIDWORKS puts it too. aria-label keeps
        // the spoken name, so the icon costs a screen reader nothing.
        const button = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-plan-nav-button',
            'data-plan-command': command,
            'aria-label': label,
            title: glyph ? label + ' (' + glyph + ')' : label,
        });
        if (!icon) {
            // Value toggles (the metre/feet switch) read better as their value.
            button.setAttribute('data-icon-source', 'text');
            button.textContent = glyph;
            return button;
        }
        const iconHost = element(this.document, 'span', {
            className: 'ip-flw-plan-nav-icon',
            'aria-hidden': 'true',
        });
        // Same source the 3D toolbar draws from, so both viewports share one
        // icon family rather than the flat outline set this used to load.
        const iconFactory = this.options.viewerToolbarIconMarkup
            || (root && root.InspectorProViewerToolbarIconMarkup);
        let markup = '';
        if (typeof iconFactory === 'function') {
            try {
                markup = iconFactory(icon) || '';
            } catch (error) {
                markup = '';
            }
        }
        if (markup) {
            iconHost.innerHTML = markup;
            button.setAttribute('data-icon-source', 'cad-viewer');
        } else {
            iconHost.appendChild(element(this.document, 'img', {
                src: VIEWPORT_ICON_ROOT + (fallback || icon) + '.svg',
                alt: '',
                draggable: 'false',
                'aria-hidden': 'true',
            }));
            button.setAttribute('data-icon-source', 'fallback');
        }
        button.appendChild(iconHost);
        return button;
    };

    Workspace.prototype._threeNavigationButton = function (
        command,
        label,
        icon,
        groupStart
    ) {
        const button = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-three-nav-button',
            'data-three-command': command,
            'data-group-start': groupStart ? 'true' : 'false',
            'aria-label': label,
            title: label,
        });
        const iconHost = element(this.document, 'span', {
            className: 'ip-flw-three-nav-icon',
            'aria-hidden': 'true',
        });
        const iconFactory = this.options.viewerToolbarIconMarkup
            || (root && root.InspectorProViewerToolbarIconMarkup);
        let markup = '';
        if (typeof iconFactory === 'function') {
            try {
                markup = iconFactory(icon) || '';
            } catch (error) {
                markup = '';
            }
        }
        if (icon === 'settings') {
            iconHost.appendChild(element(this.document, 'img', {
                src: '/static/assets/global-toolbar-icons/gear.png',
                alt: '', draggable: 'false', 'aria-hidden': 'true',
            }));
        } else if (icon === 'record') {
            iconHost.appendChild(element(this.document, 'span', {
                className: 'ip-flw-record-symbol',
            }));
            button.setAttribute('data-icon-source', 'record-symbol');
        } else if (markup) {
            iconHost.innerHTML = markup;
            button.setAttribute('data-icon-source', 'cad-viewer');
        } else {
            const fallbackIcons = {
                zoomfit: 'corners-out',
                'zoom-out': 'magnifying-glass-minus',
                'zoom-in': 'magnifying-glass-plus',
                pan: 'hand',
                orbit: 'sphere',
                walkthrough: 'person-simple-walk',
                'avatar-view': 'camera',
                drone: 'drone',
                'switch-immersive': 'swap',
                'walk-to-selected': 'navigation-arrow',
                viewpoint: 'map-pin',
                reset: 'bounding-box',
                'view-top': 'cube-focus',
                'view-iso': 'cube',
                display: 'sphere',
                grid: 'grid-four',
            };
            iconHost.appendChild(element(this.document, 'img', {
                src: VIEWPORT_ICON_ROOT
                    + (fallbackIcons[icon] || icon) + '.svg',
                alt: '',
                draggable: 'false',
                'aria-hidden': 'true',
            }));
            button.setAttribute('data-icon-source', 'fallback');
        }
        button.appendChild(iconHost);
        return button;
    };

    Workspace.prototype._threeViewOrientationControl = function () {
        const wrapper = element(this.document, 'div', {
            className: 'ip-flw-three-view-menu',
        });
        const trigger = this._threeNavigationButton(
            'view-orientation',
            'View orientation',
            'view-iso',
            true
        );
        trigger.className += ' ip-flw-three-view-trigger';
        trigger.setAttribute('aria-haspopup', 'menu');
        trigger.setAttribute('aria-expanded', 'false');
        trigger.appendChild(element(this.document, 'span', {
            className: 'ip-flw-three-view-caret',
            'aria-hidden': 'true',
        }, '\u25be'));

        const menu = element(this.document, 'div', {
            className: 'ip-flw-three-view-popup',
            role: 'menu',
            'aria-label': 'View orientation',
            hidden: true,
        });
        THREE_VIEW_ORIENTATIONS.forEach(function (view) {
            const item = element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-three-view-option',
                role: 'menuitem',
                'data-three-view': view.key,
                'aria-label': view.label + ' view',
                title: view.label + ' view',
            });
            append(item,
                element(this.document, 'img', {
                    src: threeViewIconSrc(view.key),
                    alt: '',
                    draggable: 'false',
                    'aria-hidden': 'true',
                }),
                element(this.document, 'span', {}, view.label)
            );
            menu.appendChild(item);
        }, this);
        append(wrapper, trigger, menu);
        this.threeViewOrientationTrigger = trigger;
        this.threeViewOrientationMenu = menu;
        return wrapper;
    };

    Workspace.prototype._threeViewpointsControl = function () {
        const wrapper = element(this.document, 'div', {
            className: 'ip-flw-three-viewpoint-menu',
        });
        const trigger = this._threeNavigationButton(
            'viewpoints',
            'Named viewpoints',
            'viewpoint',
            false
        );
        trigger.className += ' ip-flw-three-viewpoint-trigger';
        trigger.setAttribute('aria-haspopup', 'dialog');
        trigger.setAttribute('aria-expanded', 'false');

        const panel = element(this.document, 'section', {
            className: 'ip-flw-three-viewpoint-popup',
            role: 'dialog',
            'aria-label': 'Named viewpoints',
            hidden: true,
        });
        panel.appendChild(element(this.document, 'div', {
            className: 'ip-flw-three-viewpoint-title',
        }, 'Named viewpoints'));
        const createRow = element(this.document, 'div', {
            className: 'ip-flw-three-viewpoint-create',
        });
        const input = element(this.document, 'input', {
            type: 'text',
            maxlength: '60',
            placeholder: 'Viewpoint name',
            'aria-label': 'Viewpoint name',
            'data-viewpoint-name': 'true',
        });
        const save = element(this.document, 'button', {
            type: 'button',
            'data-viewpoint-action': 'save',
            title: 'Save current camera as a named viewpoint',
        }, 'Save current');
        append(createRow, input, save);
        const list = element(this.document, 'div', {
            className: 'ip-flw-three-viewpoint-list',
            role: 'list',
        });
        append(panel, createRow, list);
        append(wrapper, trigger, panel);
        this.threeViewpointTrigger = trigger;
        this.threeViewpointPanel = panel;
        this.threeViewpointInput = input;
        this.threeViewpointList = list;
        this._renderThreeViewpoints();
        return wrapper;
    };

    Workspace.prototype._threeSettingSlider = function (spec) {
        const id = 'ip-flw-three-setting-' + spec.key;
        const row = element(this.document, 'div', {
            className: 'ip-flw-three-setting-row',
        });
        const label = element(this.document, 'label', { for: id });
        append(label,
            element(this.document, 'span', {}, spec.label),
            element(this.document, 'span', {
                className: 'ip-flw-three-setting-value',
                'data-three-setting-value': spec.key,
            })
        );
        append(row, label, element(this.document, 'input', {
            id: id,
            type: 'range',
            min: spec.min,
            max: spec.max,
            step: spec.step,
            value: this.threeVisualSettings[spec.key],
            'data-three-setting': spec.key,
            'aria-label': spec.label,
        }));
        return row;
    };

    Workspace.prototype._buildThreeSettingsPanel = function () {
        const panel = element(this.document, 'section', {
            className: 'ip-flw-three-settings',
            'aria-label': '3D display settings',
            hidden: true,
        });
        panel.appendChild(element(this.document, 'div', {
            className: 'ip-flw-three-settings-title',
        }, 'Display settings'));
        [
            { key: 'ambient', label: 'Ambient', min: 0, max: 3, step: 0.05 },
            { key: 'directional', label: 'Directional', min: 0, max: 5, step: 0.1 },
            { key: 'exposure', label: 'Exposure', min: 0, max: 3, step: 0.05 },
            { key: 'contrast', label: 'Contrast', min: 0.5, max: 1.5, step: 0.05 },
            { key: 'metalness', label: 'Metalness', min: 0, max: 1, step: 0.01 },
            { key: 'roughness', label: 'Roughness', min: 0, max: 1, step: 0.01 },
        ].forEach(function (spec) {
            panel.appendChild(this._threeSettingSlider(spec));
        }, this);
        [
            ['autoRotate', 'Auto Rotate'],
            ['wireframe', 'Wireframe'],
        ].forEach(function (spec) {
            const id = 'ip-flw-three-setting-' + spec[0];
            const row = element(this.document, 'div', {
                className: 'ip-flw-three-setting-check',
            });
            const input = element(this.document, 'input', {
                id: id,
                type: 'checkbox',
                'data-three-setting': spec[0],
                'aria-label': spec[1],
            });
            input.checked = this.threeVisualSettings[spec[0]] === true;
            append(row, input, element(this.document, 'label', {
                for: id,
            }, spec[1]));
            panel.appendChild(row);
        }, this);
        const backgroundRow = element(this.document, 'div', {
            className: 'ip-flw-three-setting-row',
        });
        append(backgroundRow,
            element(this.document, 'label', {
                for: 'ip-flw-three-setting-background',
            }, 'Background'),
            element(this.document, 'input', {
                id: 'ip-flw-three-setting-background',
                type: 'color',
                value: this.threeVisualSettings.background === 'auto'
                    ? '#dfe6eb' : this.threeVisualSettings.background,
                'data-three-setting': 'background',
                'aria-label': '3D background color',
            })
        );
        panel.appendChild(backgroundRow);
        panel.appendChild(element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-three-settings-reset',
            'data-three-settings-action': 'reset',
        }, 'Reset display'));
        this.threeSettingsPanel = panel;
        this._renderThreeVisualSettings();
        return panel;
    };

    Workspace.prototype._buildLayerPanel = function () {
        const panel = element(this.document, 'section', {
            className: 'ip-flw-layer-panel',
            'aria-label': 'Facility layer visibility',
            hidden: true,
        });
        panel.appendChild(element(this.document, 'div', {
            className: 'ip-flw-layer-panel-title',
        }, 'Visible layers'));
        [
            ['zones', 'Departments'],
            ['cells', 'Cells and child areas'],
            ['routes', 'Routes'],
            ['markings', 'Floor markings'],
            ['assets', 'Assets'],
            ['walls', 'Walls'],
        ].forEach(function (spec) {
            const id = 'ip-flw-layer-' + spec[0];
            const row = element(this.document, 'div', {
                className: 'ip-flw-layer-check',
            });
            const input = element(this.document, 'input', {
                id: id,
                type: 'checkbox',
                'data-facility-layer': spec[0],
                'aria-label': 'Show ' + spec[1].toLowerCase(),
            });
            input.checked = this.layerVisibility[spec[0]] !== false;
            append(row, input, element(this.document, 'label', {
                for: id,
            }, spec[1]));
            panel.appendChild(row);
        }, this);
        panel.appendChild(element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-layer-show-all',
            'data-layer-action': 'show-all',
        }, 'Show all'));
        panel.appendChild(element(this.document, 'button', {
            type: 'button', className: 'ip-flw-layer-show-all',
            'data-layer-action': 'perimeter-walls',
        }, 'Perimeter walls...'));
        this.layerPanel = panel;
        return panel;
    };

    Workspace.prototype._buildMotionPanel = function () {
        const docked = this.options.motionPanelHost
            && this.options.motionPanelHost.ownerDocument === this.document
            && typeof this.options.motionPanelHost.appendChild === 'function';
        const panel = element(this.document, 'section', {
            className: 'ip-flw-motion-panel',
            'aria-label': 'Facility motion playback',
            'data-motion-docked': docked ? 'true' : 'false',
            hidden: true,
        });
        const header = element(this.document, 'div', {
            className: 'ip-flw-motion-header',
        });
        this.motionTitle = element(this.document, 'strong', {
            className: 'ip-flw-motion-title',
        }, 'Motion playback');
        this.motionOutcome = element(this.document, 'span', {
            className: 'ip-flw-motion-outcome',
        });
        this.motionCloseButton = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-motion-close',
            'data-motion-action': 'close',
            title: 'Close motion playback',
            'aria-label': 'Close motion playback',
        }, 'Close');
        append(
            header,
            this.motionTitle,
            this.motionOutcome,
            this.motionCloseButton
        );
        const controls = element(this.document, 'div', {
            className: 'ip-flw-motion-controls',
        });
        this.motionPlayButton = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-motion-play',
            'data-motion-action': 'toggle-play',
        }, 'Play');
        this.motionFollowButton = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-motion-follow',
            'data-motion-action': 'toggle-follow',
            title: 'Follow moving vehicle',
            'aria-label': 'Follow moving vehicle',
            'aria-pressed': 'false',
        });
        this.motionFollowButton.appendChild(element(this.document, 'span', {
            className: 'ip-flw-motion-follow-icon',
            'aria-hidden': 'true',
        }));
        this.motionScrubber = element(this.document, 'input', {
            type: 'range',
            className: 'ip-flw-motion-scrubber',
            min: '0',
            max: '0',
            step: '0.001',
            value: '0',
            'aria-label': 'Motion time',
            'data-motion-input': 'time',
        });
        this.motionRate = element(this.document, 'select', {
            className: 'ip-flw-motion-rate',
            'aria-label': 'Playback rate',
            'data-motion-input': 'rate',
        });
        [0.5, 1, 2].forEach(function (rate) {
            const option = element(this.document, 'option', {
                value: String(rate),
            }, rate + 'x');
            if (rate === 1) option.selected = true;
            this.motionRate.appendChild(option);
        }, this);
        this.motionPosition = element(this.document, 'span', {
            className: 'ip-flw-motion-position',
        });
        append(
            controls,
            this.motionPlayButton,
            this.motionFollowButton,
            this.motionScrubber,
            this.motionRate,
            this.motionPosition
        );
        this.activityControls = element(this.document, 'div', {
            className: 'ip-flw-activity-controls',
            hidden: true,
        });
        this.activityTypeControls = element(this.document, 'div', {
            className: 'ip-flw-activity-types',
            role: 'group',
            'aria-label': 'Visible activity actors',
        });
        [
            ['vehicle', 'Vehicles'],
            ['operator', 'People'],
            ['mobile_equipment', 'Mobile equipment'],
        ].forEach(function (spec) {
            const label = element(this.document, 'label', {
                className: 'ip-flw-activity-type',
            });
            const input = element(this.document, 'input', {
                type: 'checkbox',
                checked: true,
                'data-activity-type': spec[0],
            });
            append(
                label,
                input,
                element(this.document, 'span', {}, spec[1])
            );
            this.activityTypeControls.appendChild(label);
        }, this);
        const pathsLabel = element(this.document, 'label', {
            className: 'ip-flw-activity-type',
        });
        this.activityPathsInput = element(this.document, 'input', {
            type: 'checkbox',
            checked: true,
            'data-activity-paths': 'true',
        });
        append(
            pathsLabel,
            this.activityPathsInput,
            element(this.document, 'span', {}, 'Paths')
        );
        this.activityTypeControls.appendChild(pathsLabel);
        this.activityPathLegend = element(this.document, 'div', {
            className: 'ip-flw-activity-path-legend',
            'aria-label': 'Reviewed work-cycle movement phases',
            hidden: true,
        });
        [
            ['carry_in', 'Carry in'],
            ['carry_out', 'Carry out'],
            ['inspection_pick', 'Pick to inspect'],
            ['inspection_place', 'Inspect to place'],
            ['finished_goods_pick', 'Approach staged pallet'],
            ['receiving_pick', 'Approach inbound pallet'],
            ['loaded_putaway', 'Loaded put-away'],
            ['empty_to_rack', 'Empty to rack'],
            ['loaded_dispatch', 'Loaded to staging'],
            ['return_empty', 'Return empty'],
        ].forEach(function (spec) {
            const item = element(this.document, 'span', {
                className: 'ip-flw-activity-path-key',
                'data-path-phase': spec[0],
            });
            append(
                item,
                element(this.document, 'span', {
                    className: 'ip-flw-activity-path-swatch',
                    'aria-hidden': 'true',
                }),
                element(this.document, 'span', {}, spec[1])
            );
            this.activityPathLegend.appendChild(item);
        }, this);
        this.activityActorSelect = element(this.document, 'select', {
            className: 'ip-flw-activity-actor',
            'aria-label': 'Activity actor',
            'data-activity-input': 'actor',
        });
        this.activityFocusButton = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-activity-focus',
            'data-motion-action': 'focus-actor',
            title: 'Focus selected actor',
        }, 'Focus');
        this.activityDepartmentSelect = element(this.document, 'select', {
            className: 'ip-flw-activity-department',
            'aria-label': 'Filter activity by department',
            'data-activity-input': 'department',
        });
        append(
            this.activityControls,
            this.activityTypeControls,
            this.activityPathLegend,
            this.activityActorSelect,
            this.activityFocusButton,
            this.activityDepartmentSelect
        );
        this.motionEvidence = element(this.document, 'div', {
            className: 'ip-flw-motion-evidence',
        });
        this.motionDisclosure = element(this.document, 'div', {
            className: 'ip-flw-motion-disclosure',
            role: 'note',
        });
        append(
            panel,
            header,
            controls,
            this.activityControls,
            this.motionEvidence,
            this.motionDisclosure
        );
        this.motionPanel = panel;
        return panel;
    };

    Workspace.prototype._renderMotionPanel = function () {
        if (!this.motionPanel) return;
        const activity = this.activityState || {};
        const activityMode = activity.loaded === true;
        const value = this.motionState || {};
        const loaded = activityMode || value.loaded === true;
        this.motionPanel.hidden = !loaded;
        if (this.motionPanelVisible !== loaded) {
            this.motionPanelVisible = loaded;
            if (typeof this.options.onMotionPanelVisibilityChange
                    === 'function') {
                this.options.onMotionPanelVisibilityChange(loaded, this);
            }
        }
        if (loaded) this.root.setAttribute('data-motion-loaded', 'true');
        else this.root.removeAttribute('data-motion-loaded');
        if (!loaded) return;
        this.activityControls.hidden = !activityMode;
        if (activityMode) {
            this.motionPanel.setAttribute('data-motion-prototype', 'true');
            this.motionPanel.setAttribute('data-activity-loaded', 'true');
            this.motionTitle.textContent = cleanString(
                activity.label,
                'Prototype factory activity'
            );
            this.motionOutcome.textContent = cleanString(
                activity.status,
                'ready'
            ).replace(/_/g, ' ');
            this.motionOutcome.setAttribute('data-motion-outcome', 'accepted');
            this.motionPlayButton.disabled = false;
            this.motionPlayButton.textContent = activity.playing
                ? 'Pause' : 'Play';
            this.motionPlayButton.setAttribute(
                'aria-pressed',
                activity.playing ? 'true' : 'false'
            );
            this.motionFollowButton.hidden = true;
            this.motionScrubber.disabled = false;
            this.motionScrubber.max = String(Math.max(
                0,
                finite(activity.durationSeconds, 0)
            ));
            this.motionScrubber.value = String(Math.max(
                0,
                finite(activity.elapsedSeconds, 0)
            ));
            this.motionRate.disabled = false;
            this.motionRate.value = String(
                finite(activity.playbackRateMultiplier, 1)
            );
            this.motionPosition.textContent = finite(
                activity.elapsedSeconds,
                0
            ).toFixed(1) + ' / ' + finite(
                activity.durationSeconds,
                0
            ).toFixed(1) + ' s | ' + (
                Array.isArray(activity.actors) ? activity.actors.length : 0
            ) + ' actors';
            const visibleTypes = activity.visibleActorTypes || {};
            this.activityTypeControls.querySelectorAll(
                '[data-activity-type]'
            ).forEach(function (input) {
                input.checked = visibleTypes[
                    input.getAttribute('data-activity-type')
                ] !== false;
            });
            this.activityPathsInput.checked = activity.pathsVisible !== false;
            const actors = Array.isArray(activity.actors)
                ? activity.actors : [];
            const actorSignature = actors.map(function (actor) {
                return actor.actorId + ':' + actor.label;
            }).join('|');
            if (this.activityActorSelect.dataset.signature
                    !== actorSignature) {
                while (this.activityActorSelect.firstChild) {
                    this.activityActorSelect.removeChild(
                        this.activityActorSelect.firstChild
                    );
                }
                actors.forEach(function (actor) {
                    this.activityActorSelect.appendChild(element(
                        this.document,
                        'option',
                        { value: actor.actorId },
                        actor.label
                    ));
                }, this);
                this.activityActorSelect.dataset.signature = actorSignature;
            }
            this.activityActorSelect.value = cleanString(
                activity.selectedActorId,
                actors[0] && actors[0].actorId || ''
            );
            const departmentIds = Array.from(new Set(actors.reduce(
                function (result, actor) {
                    return result.concat(
                        Array.isArray(actor.departmentZoneIds)
                            ? actor.departmentZoneIds : []
                    );
                },
                []
            ))).sort();
            const departmentSignature = departmentIds.join('|');
            if (this.activityDepartmentSelect.dataset.signature
                    !== departmentSignature) {
                while (this.activityDepartmentSelect.firstChild) {
                    this.activityDepartmentSelect.removeChild(
                        this.activityDepartmentSelect.firstChild
                    );
                }
                this.activityDepartmentSelect.appendChild(element(
                    this.document,
                    'option',
                    { value: '' },
                    'All departments'
                ));
                const zones = this.state && this.state.layout
                    && Array.isArray(this.state.layout.zones)
                    ? this.state.layout.zones : [];
                departmentIds.forEach(function (zoneId) {
                    const zone = zones.find(function (candidate) {
                        return candidate.zoneId === zoneId;
                    });
                    this.activityDepartmentSelect.appendChild(element(
                        this.document,
                        'option',
                        { value: zoneId },
                        zone && zone.label ? zone.label : zoneId
                    ));
                }, this);
                this.activityDepartmentSelect.dataset.signature =
                    departmentSignature;
            }
            this.activityDepartmentSelect.value = cleanString(
                activity.departmentZoneId,
                ''
            );
            const typeCounts = actors.reduce(function (counts, actor) {
                counts[actor.actorType] = (counts[actor.actorType] || 0) + 1;
                return counts;
            }, {});
            const stationary = activity.stationaryEvidence || {};
            const unavailable = Array.isArray(activity.unavailableActivity)
                ? activity.unavailableActivity : [];
            const candidates = activity.candidatePresentation;
            const activePathLegend = [
                ...(candidates && Array.isArray(
                    candidates.packagingPathLegend
                ) ? candidates.packagingPathLegend : []),
                ...(candidates && Array.isArray(
                    candidates.inspectionPathLegend
                ) ? candidates.inspectionPathLegend : []),
                ...(candidates && Array.isArray(
                    candidates.finishedGoodsPathLegend
                ) ? candidates.finishedGoodsPathLegend : []),
                ...(candidates && Array.isArray(
                    candidates.receivingPathLegend
                ) ? candidates.receivingPathLegend : []),
            ];
            const activePathPhases = new Set(activePathLegend.map(function (item) {
                return item && item.phase;
            }).filter(Boolean));
            const activePathLabels = new Map(activePathLegend.map(function (item) {
                return [item && item.phase, item && item.label];
            }).filter(function (item) {
                return item[0] && item[1];
            }));
            Array.from(this.activityPathLegend.children).forEach(function (
                item
            ) {
                item.hidden = !activePathPhases.has(item.dataset.pathPhase);
                if (!item.hidden && activePathLabels.has(item.dataset.pathPhase)
                        && item.children[1]) {
                    item.children[1].textContent = activePathLabels.get(
                        item.dataset.pathPhase
                    );
                }
            });
            this.activityPathLegend.hidden = activePathPhases.size === 0;
            if (candidates && candidates.candidateCounts) {
                const counts = candidates.candidateCounts;
                this.motionEvidence.textContent = [
                    finite(counts.operators, 0) + ' operator candidates',
                    finite(counts.vehicles, 0) + ' vehicle candidates',
                    finite(counts.handoffs, 0) + ' handoff candidates',
                    finite(counts.displayedActors, 0) + ' actors displayed',
                    finite(counts.displayedHandoffs, 0)
                        + ' handoff links displayed',
                    finite(counts.unavailableActors, 0)
                        + ' unavailable candidates',
                    finite(counts.partialPrograms, 0)
                        + ' partial candidate programs',
                    finite(counts.suppressedStationaryOperators, 0)
                        + ' stationary operator figures suppressed',
                ].join(' | ');
                this.motionDisclosure.textContent = [
                    cleanString(candidates.qualification, ''),
                    cleanString(activity.disclosure, ''),
                ].filter(Boolean).join(' ');
            } else {
                this.motionEvidence.textContent = [
                    (typeCounts.vehicle || 0) + ' vehicles',
                    (typeCounts.operator || 0) + ' people',
                    (typeCounts.mobile_equipment || 0) + ' mobile equipment',
                    finite(stationary.placementCount, 0)
                        + ' fixed machines stationary: '
                        + cleanString(stationary.reason, 'no kinematic track'),
                    unavailable.length + ' unavailable activity assignments',
                ].join(' | ');
                this.motionDisclosure.textContent = activity.disclosure || '';
            }
            return;
        }
        this.motionPanel.removeAttribute('data-activity-loaded');
        this.activityControls.hidden = true;
        const prototypeMode = value.prototypeMode === true;
        this.motionPanel.setAttribute(
            'data-motion-prototype',
            prototypeMode ? 'true' : 'false'
        );
        this.motionTitle.textContent = prototypeMode
            ? 'Motion playback - prototype fixture'
            : 'Motion playback';
        this.motionOutcome.textContent = cleanString(
            value.outcome,
            value.status || 'ready'
        ).replace(/_/g, ' ');
        this.motionOutcome.setAttribute(
            'data-motion-outcome',
            value.outcome || ''
        );
        const replayable = value.outcome === 'accepted'
            || value.outcome === 'envelope_refused';
        this.motionPlayButton.disabled = !replayable;
        this.motionPlayButton.textContent = value.playing ? 'Pause' : 'Play';
        this.motionPlayButton.setAttribute(
            'aria-pressed',
            value.playing ? 'true' : 'false'
        );
        const placedAsset = value.vehiclePresentation === 'placed_asset';
        this.motionFollowButton.hidden = !placedAsset;
        this.motionFollowButton.disabled = !replayable || !placedAsset;
        this.motionFollowButton.setAttribute(
            'aria-pressed',
            value.following ? 'true' : 'false'
        );
        this.motionFollowButton.title = value.following
            ? 'Stop following moving vehicle'
            : 'Follow moving vehicle';
        this.motionScrubber.disabled = !replayable;
        this.motionScrubber.max = String(Math.max(
            0,
            finite(value.durationSeconds, 0)
        ));
        this.motionScrubber.value = String(Math.max(
            0,
            finite(value.elapsedSeconds, 0)
        ));
        this.motionRate.disabled = !replayable;
        this.motionRate.value = String(
            finite(value.playbackRateMultiplier, 1)
        );
        const elapsed = finite(value.elapsedSeconds, 0);
        const duration = finite(value.durationSeconds, 0);
        const distance = finite(value.distanceMeters, 0);
        this.motionPosition.textContent = elapsed.toFixed(1) + ' / '
            + duration.toFixed(1) + ' s | ' + distance.toFixed(1) + ' m';
        const evidence = [];
        if (prototypeMode) {
            evidence.push(cleanString(
                value.prototypeLabel,
                'Prototype fixture evidence - not a released vehicle profile'
            ));
        }
        const lane = value.laneBinding;
        if (lane && lane.status === 'direction_markings') {
            evidence.push(
                (lane.travelDirection === 'reverse' ? 'Reverse' : 'Forward')
                + ' lane derived from '
                + (Array.isArray(lane.sourceMarkingIds)
                    ? lane.sourceMarkingIds.length : 0)
                + ' authored direction markings; offset '
                + finite(lane.lateralOffsetMeters, 0).toFixed(2) + ' m'
            );
        } else if (lane && lane.status === 'centerline_unmarked') {
            evidence.push('No directional lane marking resolved; using route centerline');
        }
        const sample = value.clearanceAtValidatedSample;
        if (sample) {
            const sampleDistance = finite(sample.distanceMeters, 0);
            if (sample.clearanceMeters === null
                    || sample.clearanceMeters === undefined) {
                evidence.push(
                    'Clearance at validated sample '
                    + sampleDistance.toFixed(2)
                    + ' m: no obstacle in the analysed set'
                );
            } else {
                evidence.push(
                    'Clearance at validated sample '
                    + sampleDistance.toFixed(2) + ' m: '
                    + finite(sample.clearanceMeters, 0).toFixed(2) + ' m'
                );
            }
        }
        if (finite(value.sampleSpacingMeters, 0) > 0) {
            evidence.push(
                'Validation sample spacing: '
                + finite(value.sampleSpacingMeters, 0).toFixed(3) + ' m'
            );
        }
        if (value.plannerDurationEstimate && duration > 0) {
            evidence.push(
                'Estimated at profile maximum speed: '
                + duration.toFixed(1) + ' s'
            );
        }
        if (value.outcome === 'envelope_refused' && value.blocking) {
            const obstacles = Array.isArray(value.blocking.blockingObstacleIds)
                ? value.blocking.blockingObstacleIds.join(', ') : '';
            evidence.push(
                value.blocking.localized
                    ? 'Playback stops at the validated blocking sample'
                        + (obstacles ? ': ' + obstacles : '')
                    : 'The refusal is not localized to a replayable sample'
            );
        }
        if (value.outcome === 'unroutable') {
            evidence.push('No trajectory was established for playback.');
        }
        this.motionEvidence.textContent = evidence.join(' | ');
        this.motionDisclosure.textContent = value.disclosure || '';
    };

    Workspace.prototype._handleMotionState = function (value) {
        this.motionState = Object.assign({}, this.motionState, value || {});
        if (this.topAdapter && typeof this.topAdapter.updateMotionSnapshot
                === 'function' && this.motionState.packageId) {
            this.topAdapter.updateMotionSnapshot(this.motionState);
        }
        this._renderMotionPanel();
        return clone(this.motionState);
    };

    Workspace.prototype._handleActivityState = function (value) {
        this.activityState = Object.assign(
            {},
            this.activityState,
            value || {}
        );
        if (this.topAdapter
                && typeof this.topAdapter.updateActivitySnapshot === 'function'
                && this.activityState.scenarioId) {
            this.topAdapter.updateActivitySnapshot(this.activityState);
        }
        this._renderMotionPanel();
        return clone(this.activityState);
    };

    Workspace.prototype._handleNavigationPreviewState = function (value) {
        const snapshot = value || {};
        this.navigationState.previewLoaded = Boolean(snapshot.loaded);
        this.navigationState.previewPlaying = Boolean(snapshot.playing);
        if (Number.isFinite(Number(snapshot.normalizedTime))) {
            this.navigationState.previewNormalizedTime = Number(
                snapshot.normalizedTime
            );
        }
        if (this.navigationState.open && this.topAdapter
                && typeof this.topAdapter.setNavigationAuthoringPreview
                    === 'function') {
            const descriptor = this._navigationPreviewDescriptor();
            if (snapshot.pose) descriptor.pose = clone(snapshot.pose);
            this.topAdapter.setNavigationAuthoringPreview(descriptor);
        }
        if (this.navigationState.open) this._renderNavigationDialog();
        return clone(snapshot);
    };

    Workspace.prototype._handleMotionClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-motion-action',
            this.motionPanel
        );
        if (!action || !this.threeAdapter) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (this.activityState.loaded && this.threeAdapter.activity) {
            if (action === 'toggle-play') {
                if (this.activityState.playing) {
                    this.threeAdapter.activity.pause();
                } else {
                    this.threeAdapter.activity.play();
                }
            } else if (action === 'focus-actor') {
                this.threeAdapter.activity.focusActor(
                    this.activityState.selectedActorId
                );
            } else if (action === 'close') {
                this.clearActivityPlayback('user_closed');
            }
            return;
        }
        if (!this.threeAdapter.motion) return;
        if (action === 'toggle-play') {
            if (this.motionState.playing) this.threeAdapter.motion.pause();
            else this.threeAdapter.motion.play();
        } else if (action === 'toggle-follow') {
            this.threeAdapter.motion.setFollow(!this.motionState.following);
        } else if (action === 'close') {
            this.clearMotionPlayback('user_closed');
        }
    };

    Workspace.prototype._handleMotionInput = function (event) {
        if (!this.threeAdapter) return;
        if (this.activityState.loaded && this.threeAdapter.activity) {
            const activityInput = targetDataId(
                event.target,
                'data-activity-input',
                this.motionPanel
            );
            const actorType = targetDataId(
                event.target,
                'data-activity-type',
                this.motionPanel
            );
            const pathsInput = targetDataId(
                event.target,
                'data-activity-paths',
                this.motionPanel
            );
            const motionInput = targetDataId(
                event.target,
                'data-motion-input',
                this.motionPanel
            );
            if (motionInput === 'time') {
                this.threeAdapter.activity.seek(
                    finite(event.target.value, 0)
                );
            } else if (motionInput === 'rate') {
                this.threeAdapter.activity.setRate(
                    finite(event.target.value, 1)
                );
            } else if (activityInput === 'actor') {
                this.threeAdapter.activity.selectActor(event.target.value);
            } else if (activityInput === 'department') {
                this.threeAdapter.activity.setDepartmentFilter(
                    event.target.value
                );
            } else if (actorType) {
                this.threeAdapter.activity.setActorTypeVisible(
                    actorType,
                    event.target.checked !== false
                );
                if (typeof this.threeAdapter.activity.setPathTypeVisible
                        === 'function') {
                    this.threeAdapter.activity.setPathTypeVisible(
                        actorType,
                        event.target.checked !== false
                    );
                }
                if (this.topAdapter
                        && typeof this.topAdapter.setActivityPathTypeVisible
                            === 'function') {
                    this.topAdapter.setActivityPathTypeVisible(
                        actorType,
                        event.target.checked !== false
                    );
                }
            } else if (pathsInput) {
                this.threeAdapter.activity.setPathsVisible(
                    event.target.checked !== false
                );
                if (this.topAdapter
                        && typeof this.topAdapter.setActivityPathsVisible
                            === 'function') {
                    this.topAdapter.setActivityPathsVisible(
                        event.target.checked !== false
                    );
                }
            }
            return;
        }
        if (!this.threeAdapter.motion) return;
        const input = targetDataId(
            event.target,
            'data-motion-input',
            this.motionPanel
        );
        if (input === 'time') {
            this.threeAdapter.motion.seek(finite(event.target.value, 0));
        } else if (input === 'rate') {
            this.threeAdapter.motion.setRate(finite(event.target.value, 1));
        }
    };

    Workspace.prototype.startMotionPlayback = async function (request) {
        if (this.destroyed || this.motionRequestPending) {
            throw new Error('Facility motion playback is unavailable.');
        }
        if (!this.motionTransport
                || typeof this.motionTransport.createMotionPackage !== 'function'
                || typeof this.motionTransport.getMotionPackage !== 'function') {
            const error = new Error('Facility motion transport is unavailable.');
            error.code = 'facility_motion_transport_unavailable';
            throw error;
        }
        if (!this.threeAdapter || !this.threeAdapter.motion
                || typeof this.threeAdapter.motion.load !== 'function') {
            const error = new Error('Facility motion renderer is unavailable.');
            error.code = 'facility_motion_view_unavailable';
            throw error;
        }
        const beforeState = this.session.getState();
        const beforeFingerprint = JSON.stringify(beforeState.layout || {});
        this.motionRequestPending = true;
        try {
            const created = await this.motionTransport.createMotionPackage({
                baseRevision: beforeState.baseRevision,
                operations: Array.isArray(beforeState.operations)
                    ? beforeState.operations : [],
                request: clone(request || {}),
            });
            const packageId = cleanString(created && created.packageId, '');
            const activeRevision = cleanString(
                created && created.layoutRevision,
                ''
            );
            if (!packageId || !activeRevision) {
                const error = new Error(
                    'Facility motion package response is incomplete.'
                );
                error.code = 'facility_motion_package_response_invalid';
                throw error;
            }
            const payload = await this.motionTransport.getMotionPackage({
                packageId: packageId,
                activeRevision: activeRevision,
            });
            const currentState = this.session.getState();
            if (JSON.stringify(currentState.layout || {}) !== beforeFingerprint
                    || currentState.baseRevision !== beforeState.baseRevision
                    || JSON.stringify(currentState.operations || [])
                        !== JSON.stringify(beforeState.operations || [])) {
                const error = new Error(
                    'The Facility Layout changed while motion was prepared.'
                );
                error.code = 'facility_motion_package_stale';
                throw error;
            }
            if (this.controller && typeof this.controller.ready === 'function') {
                await this.controller.ready();
            }
            this.motionState.prototypeMode = payload.prototypeMode === true;
            this.motionState.prototypeLabel = cleanString(
                payload.prototypeLabel,
                null
            );
            if (this.activityState.loaded) {
                this.clearActivityPlayback('motion_loaded');
            }
            if (this.topAdapter
                    && typeof this.topAdapter.setMotionPresentation
                        === 'function') {
                this.topAdapter.setMotionPresentation(payload);
            }
            try {
                this.threeAdapter.motion.load(payload, activeRevision);
            } catch (error) {
                if (this.topAdapter
                        && typeof this.topAdapter.clearMotionPresentation
                            === 'function') {
                    this.topAdapter.clearMotionPresentation();
                }
                throw error;
            }
            this.motionPresentation = clone(payload);
            this.motionLayoutFingerprint = beforeFingerprint;
            this._renderMotionPanel();
            return clone(created.summary || {
                packageId: packageId,
                outcome: payload.package
                    && payload.package.movement
                    && payload.package.movement.outcome,
                qualification: payload.package
                    && payload.package.qualification,
            });
        } catch (error) {
            if (typeof this.options.onError === 'function') {
                this.options.onError(error);
            }
            throw error;
        } finally {
            this.motionRequestPending = false;
        }
    };

    Workspace.prototype.loadMotionPresentation = function (
        payload,
        activeRevision
    ) {
        if (!this.threeAdapter || !this.threeAdapter.motion) {
            throw new Error('Facility motion renderer is unavailable.');
        }
        this.motionState.prototypeMode = payload
            && payload.prototypeMode === true;
        this.motionState.prototypeLabel = cleanString(
            payload && payload.prototypeLabel,
            null
        );
        if (this.activityState.loaded) {
            this.clearActivityPlayback('motion_loaded');
        }
        if (this.topAdapter
                && typeof this.topAdapter.setMotionPresentation === 'function') {
            this.topAdapter.setMotionPresentation(payload);
        }
        try {
            const state = this.threeAdapter.motion.load(
                payload,
                activeRevision
            );
            this.motionPresentation = clone(payload);
            this.motionLayoutFingerprint = JSON.stringify(
                this.state && this.state.layout || {}
            );
            return state;
        } catch (error) {
            if (this.topAdapter
                    && typeof this.topAdapter.clearMotionPresentation
                        === 'function') {
                this.topAdapter.clearMotionPresentation();
            }
            throw error;
        }
    };

    Workspace.prototype.clearMotionPlayback = function (reason) {
        if (this.topAdapter
                && typeof this.topAdapter.clearMotionPresentation === 'function') {
            this.topAdapter.clearMotionPresentation();
        }
        if (this.threeAdapter && this.threeAdapter.motion
                && typeof this.threeAdapter.motion.dispose === 'function') {
            this.threeAdapter.motion.dispose(reason || 'cleared');
        }
        this.motionPresentation = null;
        this.motionLayoutFingerprint = null;
        this.motionState = Object.assign({}, this.motionState, {
            loaded: false,
            status: 'idle',
            statusReason: reason || null,
            packageId: null,
            movementId: null,
            outcome: null,
            vehiclePlacementId: null,
            vehiclePresentation: null,
            laneBinding: null,
            following: false,
            playing: false,
            elapsedSeconds: 0,
            durationSeconds: 0,
            distanceMeters: 0,
            totalDistanceMeters: 0,
            pose: null,
            clearanceAtValidatedSample: null,
            sampleSpacingMeters: null,
            qualification: null,
            disclosure: null,
            blocking: null,
            prototypeMode: false,
            prototypeLabel: null,
        });
        this._renderMotionPanel();
        return true;
    };

    Workspace.prototype.startActivityPlayback = async function (request) {
        if (this.destroyed || this.activityRequestPending) {
            throw new Error('Facility activity playback is unavailable.');
        }
        if (!this.motionTransport
                || typeof this.motionTransport.createActivityScenario
                    !== 'function'
                || typeof this.motionTransport.getActivityScenario
                    !== 'function') {
            const error = new Error(
                'Facility activity transport is unavailable.'
            );
            error.code = 'facility_activity_transport_unavailable';
            throw error;
        }
        if (!this.threeAdapter || !this.threeAdapter.activity
                || typeof this.threeAdapter.activity.load !== 'function') {
            const error = new Error(
                'Facility activity renderer is unavailable.'
            );
            error.code = 'facility_activity_view_unavailable';
            throw error;
        }
        const beforeState = this.session.getState();
        const beforeFingerprint = JSON.stringify(beforeState.layout || {});
        this.activityRequestPending = true;
        try {
            const created = await this.motionTransport.createActivityScenario({
                baseRevision: beforeState.baseRevision,
                operations: Array.isArray(beforeState.operations)
                    ? beforeState.operations : [],
                request: clone(request || {}),
            });
            const scenarioId = cleanString(created && created.scenarioId, '');
            const activeRevision = cleanString(
                created && created.layoutRevision,
                ''
            );
            if (!scenarioId || !activeRevision) {
                const error = new Error(
                    'Facility activity scenario response is incomplete.'
                );
                error.code = 'facility_activity_scenario_response_invalid';
                throw error;
            }
            const payload = await this.motionTransport.getActivityScenario({
                scenarioId: scenarioId,
                activeRevision: activeRevision,
            });
            const currentState = this.session.getState();
            if (JSON.stringify(currentState.layout || {}) !== beforeFingerprint
                    || currentState.baseRevision !== beforeState.baseRevision
                    || JSON.stringify(currentState.operations || [])
                        !== JSON.stringify(beforeState.operations || [])) {
                const error = new Error(
                    'The Facility Layout changed while activity was prepared.'
                );
                error.code = 'facility_activity_scenario_stale';
                throw error;
            }
            if (this.controller && typeof this.controller.ready === 'function') {
                await this.controller.ready();
            }
            if (this.motionState.loaded) {
                this.clearMotionPlayback('activity_loaded');
            }
            if (this.topAdapter
                    && typeof this.topAdapter.setActivityPresentation
                        === 'function') {
                this.topAdapter.setActivityPresentation(payload);
            }
            try {
                await this.threeAdapter.activity.load(
                    payload,
                    activeRevision
                );
            } catch (error) {
                if (this.topAdapter
                        && typeof this.topAdapter.clearActivityPresentation
                            === 'function') {
                    this.topAdapter.clearActivityPresentation();
                }
                throw error;
            }
            this.activityPresentation = clone(payload);
            this.activityLayoutFingerprint = beforeFingerprint;
            this._renderMotionPanel();
            return clone(created.summary || {
                scenarioId: scenarioId,
                qualification: payload.scenario
                    && payload.scenario.qualification,
            });
        } catch (error) {
            if (typeof this.options.onError === 'function') {
                this.options.onError(error);
            }
            throw error;
        } finally {
            this.activityRequestPending = false;
        }
    };

    Workspace.prototype.savedMovementChoices = function () {
        const layout = this.state.layout || {};
        const value = layout.extensions && layout.extensions.facilityNavigation
            && layout.extensions.facilityNavigation.movementPrograms || [];
        const programs = Array.isArray(value) ? value.filter(p => p && typeof p === 'object') : [];
        const byId = new Map(programs.map(p => [p.movementProgramId, p]));
        const placements = new Map((layout.placements || []).map(p => [p.placementId, p]));
        const choices = [];
        const add = (label, ids) => {
            if (!Array.isArray(ids) || !ids.length || ids.length > NAVIGATION_ACTIVITY_MAXIMUM_ACTORS
                    || new Set(ids).size !== ids.length
                    || ids.some(id => !byId.has(id) || !placements.has(byId.get(id).actorPlacementId))
                    || new Set(ids.map(id => byId.get(id).actorPlacementId)).size !== ids.length) return;
            choices.push({ label: String(label), movementProgramIds: ids.slice() });
        };
        add('All saved movement (' + programs.length + ' actors)', programs.map(p => p.movementProgramId));
        const selected = new Set(this.state.selection || []);
        add('Selected actors', programs.filter(p => selected.has(p.actorPlacementId)).map(p => p.movementProgramId));
        const presentation = layout.extensions && layout.extensions.facilityProcessPresentation;
        if (presentation && presentation.schemaVersion === 1 && Array.isArray(presentation.groups)) {
            presentation.groups.forEach(g => {
                if (g && typeof g === 'object') add(g.label, g.movementProgramIds);
            });
        }
        programs.forEach(p => {
            const actor = placements.get(p.actorPlacementId);
            add(actor && actor.metadata && actor.metadata.instanceLabel || p.actorPlacementId, [p.movementProgramId]);
        });
        return choices;
    };

    Workspace.prototype._canEditAppearance = function () {
        return !this.destroyed && !this.suspended && this.state.loaded && !this.state.busy
            && this.capabilities.manualAuthoring && !this.state.conflict
            && !this.state.generatedDraft && !this.state.designProposalDraft
            && !this.state.layoutProposal && !this.state.placementAlternatives
            && !this.constructionPreview && !this.activityRequestPending
            && !(this.generationPlanningView && this.generationPlanningView.activeLayout())
            && typeof this.session.setSelectedAppearance === 'function'
            && this._selectedPlacementRecords().length > 0;
    };

    // Library edits (finishes, scenes, decals) need an editable draft but not
    // a selection: a scene or a favorite can be browsed with nothing selected.
    Workspace.prototype._canEditLibrary = function () {
        return !this.destroyed && !this.suspended && this.state.loaded && !this.state.busy
            && this.capabilities.manualAuthoring && !this.state.conflict
            && !this.state.generatedDraft && !this.state.designProposalDraft
            && !this.state.layoutProposal && !this.state.placementAlternatives
            && !this.constructionPreview && !this.activityRequestPending
            && !(this.generationPlanningView && this.generationPlanningView.activeLayout());
    };

    // What the Appearances, Scenes and Decals panel needs, without reaching
    // into workspace internals. Read on every panel refresh; never mutate.
    Workspace.prototype.appearanceLibraryContext = function () {
        const self = this;
        return {
            session: this.session,
            threeAdapter: this.threeAdapter || null,
            document: this.document,
            assetCatalog: this.assetCatalog || [],
            layout: this.state && this.state.layout || null,
            selection: Array.isArray(this.state && this.state.selection) ? this.state.selection.slice() : [],
            canEdit: this._canEditLibrary(),
            viewMode: this.viewMode,
            dropTarget: this.threeView || null,
            show3d: function () { if (self.viewMode !== '3d') self._setViewMode('3d'); },
            openWallDecals: function (prefill) {
                if (!decalsRuntime) throw new Error('Wall decals are unavailable.');
                return decalsRuntime.openDialog(self, undefined, prefill);
            },
            isWallAsset: function (placementId) {
                const placement = (self.state.layout && self.state.layout.placements || [])
                    .find(function (row) { return row.placementId === placementId; });
                const entry = placement && (self.assetCatalog || []).find(function (row) {
                    return row.assetId === placement.assetId;
                });
                return Boolean(entry && wallsRuntime && wallsRuntime.isWallAsset(entry));
            },
        };
    };

    Workspace.prototype.closeAppearanceDialog = function () {
        if (this.appearanceDialog) this.appearanceDialog.remove();
        this.appearanceDialog = null;
        this.refreshAppearanceDialog = null;
    };

    Workspace.prototype.openAppearanceDialog = function () {
        if (!this._canEditAppearance()) return false;
        this.closeAppearanceDialog();
        const selected = this._selectedPlacementRecords();
        const openingRevision = this.state.draftRevision;
        const openingSelection = JSON.stringify(this.state.selection);
        const openingLayout = this.state.layout.layoutId;
        const colors = new Set(selected.map(p => p.appearance && p.appearance.color || null));
        let chosen = colors.size === 1 ? Array.from(colors)[0] : undefined;
        const focusReturn = this.document.activeElement;
        const dialog = element(this.document, 'section', {
            className: 'ip-flw-precision-dialog ip-flw-appearance-dialog', role: 'dialog',
            'aria-modal': 'false', 'aria-label': 'Object appearance',
        });
        const header = element(this.document, 'header', { className: 'ip-flw-precision-header' });
        const close = element(this.document, 'button', { type: 'button',
            className: 'ip-flw-precision-close', title: 'Close', 'aria-label': 'Close appearance' }, 'X');
        const dismiss = () => {
            this.closeAppearanceDialog();
            if (focusReturn && typeof focusReturn.focus === 'function') focusReturn.focus();
        };
        close.addEventListener('click', dismiss);
        dialog.addEventListener('keydown', event => {
            if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); dismiss(); }
        });
        append(header, element(this.document, 'h2', {}, 'Appearance'), close);
        const body = element(this.document, 'div', { className: 'ip-flw-precision-body' });
        body.appendChild(element(this.document, 'div', { className: 'ip-flw-appearance-summary' },
            selected.length === 1 ? (selected[0].metadata && selected[0].metadata.instanceLabel
                || selected[0].assetId) : selected.length + ' objects'));
        const swatches = element(this.document, 'div', { className: 'ip-flw-appearance-swatches',
            role: 'group', 'aria-label': 'Preset colors' });
        const picker = element(this.document, 'input', { type: 'color', value: chosen || '#9aa2a9',
            'aria-label': 'Custom object color', 'data-appearance-color': 'true' });
        const value = element(this.document, 'span', { className: 'ip-flw-appearance-value' });
        const status = element(this.document, 'div', { className: 'ip-flw-precision-status', role: 'status' });
        const apply = element(this.document, 'button', { type: 'button',
            className: 'ip-flw-primary-action', 'data-appearance-apply': 'true' }, 'Apply');
        const refresh = () => {
            const stale = this.state.draftRevision !== openingRevision
                || this.state.layout.layoutId !== openingLayout
                || JSON.stringify(this.state.selection) !== openingSelection;
            apply.disabled = !this._canEditAppearance() || stale || chosen === undefined;
            value.textContent = chosen === undefined ? 'Mixed colors' : chosen === null ? 'Default' : chosen.toUpperCase();
            if (stale) status.textContent = 'Selection or layout changed. Reopen Appearance.';
            Array.from(swatches.children).forEach(button => button.setAttribute('aria-pressed',
                button.getAttribute('data-appearance-swatch') === chosen ? 'true' : 'false'));
        };
        [['#e8ecef', 'White'], ['#9aa2a9', 'Gray'], ['#303940', 'Charcoal'],
            ['#2478bc', 'Blue'], ['#28866b', 'Green'], ['#e4b329', 'Yellow'],
            ['#d97929', 'Orange'], ['#bb4040', 'Red']].forEach(([color, name]) => {
            const button = element(this.document, 'button', { type: 'button',
                className: 'ip-flw-appearance-swatch', title: name, 'aria-label': name,
                'data-appearance-swatch': color, style: 'background-color:' + color });
            button.addEventListener('click', () => { chosen = color; picker.value = color; refresh(); });
            swatches.appendChild(button);
        });
        picker.addEventListener('input', () => { chosen = picker.value; refresh(); });
        picker.addEventListener('change', () => { chosen = picker.value; refresh(); });
        const reset = element(this.document, 'button', { type: 'button',
            className: 'ip-flw-appearance-reset', title: 'Reset to default finish',
            'aria-label': 'Reset to default finish', 'data-appearance-reset': 'true' });
        reset.appendChild(element(this.document, 'img', {
            src: VIEWPORT_ICON_ROOT + 'arrow-u-up-left.svg', alt: '', 'aria-hidden': 'true' }));
        reset.addEventListener('click', () => { chosen = null; refresh(); });
        const custom = element(this.document, 'div', { className: 'ip-flw-appearance-custom' });
        append(custom, picker, value, reset);
        append(body, swatches, custom);
        apply.addEventListener('click', async () => {
            refresh();
            if (apply.disabled) return;
            apply.disabled = true;
            try {
                await this.session.setSelectedAppearance(chosen);
                dismiss();
            } catch (error) {
                status.textContent = String(error.message || error);
                refresh();
            }
        });
        const footer = element(this.document, 'footer', { className: 'ip-flw-precision-footer' });
        append(footer, status, apply);
        append(dialog, header, body, footer);
        this.root.appendChild(dialog);
        this.appearanceDialog = dialog;
        this.refreshAppearanceDialog = refresh;
        refresh();
        picker.focus();
        return true;
    };

    Workspace.prototype.openSavedMovementDialog = function () {
        if (this.destroyed || this.state.busy || this.state.conflict || this.activityRequestPending
                || !this.capabilities.navigationMultiActor
                || activeLayoutAlternative(this.state) || this.constructionPreview
                || (this.generationPlanningView && this.generationPlanningView.activeLayout())) return false;
        const choices = this.savedMovementChoices();
        if (!choices.length) return false;
        if (this.savedMovementDialog) this.savedMovementDialog.remove();
        const openingLayout = JSON.stringify(this.state.layout);
        const focusReturn = this.document.activeElement;
        const abort = new AbortController();
        const dialog = element(this.document, 'section', {
            className: 'ip-flw-precision-dialog ip-flw-saved-movement-dialog',
            role: 'dialog', 'aria-modal': 'false', 'aria-label': 'Saved movement',
        });
        const header = element(this.document, 'header', { className: 'ip-flw-precision-header' });
        const close = element(this.document, 'button', {
            type: 'button', className: 'ip-flw-precision-close', title: 'Close', 'aria-label': 'Close saved movement',
        }, 'X');
        const dismiss = () => {
            abort.abort();
            dialog.remove();
            if (this.savedMovementDialog === dialog) this.savedMovementDialog = null;
            if (focusReturn && typeof focusReturn.focus === 'function') focusReturn.focus();
        };
        close.addEventListener('click', dismiss);
        dialog.addEventListener('keydown', event => {
            if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); dismiss(); }
        });
        append(header, element(this.document, 'h2', {}, 'Saved movement'), close);
        const body = element(this.document, 'div', { className: 'ip-flw-precision-body' });
        const select = element(this.document, 'select', { 'aria-label': 'Movement scope', 'data-saved-movement-group': 'true' });
        select.style.maxWidth = '100%';
        choices.forEach((choice, i) => select.appendChild(element(this.document, 'option', { value: String(i) }, choice.label)));
        select.value = '0';
        body.appendChild(select);
        const status = element(this.document, 'div', { className: 'ip-flw-precision-status', role: 'status', 'aria-live': 'polite' });
        const prepare = element(this.document, 'button', {
            type: 'button', className: 'ip-flw-primary-action', 'data-saved-movement-prepare': 'true',
        }, 'Play movement');
        prepare.addEventListener('click', async () => {
            if (JSON.stringify(this.state.layout) !== openingLayout) {
                status.textContent = 'The layout changed. Reopen Saved movement.';
                return;
            }
            const choice = choices[Number(select.value)];
            if (!choice || prepare.disabled) return;
            prepare.disabled = true;
            select.disabled = true;
            status.textContent = 'Validating movement paths...';
            try {
                await this.startNavigationActivityPlayback({
                    movementProgramIds: choice.movementProgramIds, scenarioLabel: choice.label,
                    prototypeMode: true, signal: abort.signal,
                    onProgress: progress => {
                        if (!abort.signal.aborted) status.textContent = progress;
                    },
                });
                if (!abort.signal.aborted) {
                    this.threeAdapter.activity.play();
                    dismiss();
                }
            } catch (error) {
                if (!abort.signal.aborted) status.textContent = String(error.message || error);
            } finally {
                prepare.disabled = false;
                select.disabled = false;
            }
        });
        const footer = element(this.document, 'footer', { className: 'ip-flw-precision-footer' });
        append(footer, status, prepare);
        append(dialog, header, body, footer);
        this.root.appendChild(dialog);
        this.savedMovementDialog = dialog;
        select.focus();
        return true;
    };

    Workspace.prototype.startNavigationActivityPlayback = async function (request) {
        if (this.destroyed || this.activityRequestPending) {
            throw new Error('Facility navigation activity playback is unavailable.');
        }
        if (this.capabilities.navigationMultiActor !== true) {
            const error = new Error(
                'Facility navigation activity is disabled for this rollout stage.'
            );
            error.code = 'facility_feature_disabled';
            throw error;
        }
        const transport = this.motionTransport;
        if (!transport
                || typeof transport.compileNavigationSnapshot !== 'function'
                || typeof transport.planActorJourney !== 'function'
                || typeof transport.buildNavigationActivityScenario !== 'function'
                || typeof transport.getActivityScenario !== 'function') {
            const error = new Error('Facility navigation activity transport is unavailable.');
            error.code = 'facility_navigation_activity_transport_unavailable';
            throw error;
        }
        if (!this.threeAdapter || !this.threeAdapter.activity
                || typeof this.threeAdapter.activity.load !== 'function') {
            const error = new Error('Facility navigation activity view is unavailable.');
            error.code = 'facility_navigation_activity_view_unavailable';
            throw error;
        }
        const input = request && typeof request === 'object' ? request : {};
        const programIds = Array.isArray(input.movementProgramIds)
            ? Array.from(new Set(input.movementProgramIds.map(String))) : [];
        const suppliedJourneyIds = Array.isArray(input.journeySolutionIds)
            ? Array.from(new Set(input.journeySolutionIds.map(String))) : [];
        if ((!programIds.length && !suppliedJourneyIds.length)
                || programIds.length + suppliedJourneyIds.length > NAVIGATION_ACTIVITY_MAXIMUM_ACTORS
                || input.prototypeMode !== true) {
            const error = new Error(
                'Navigation playback requires 1-' + NAVIGATION_ACTIVITY_MAXIMUM_ACTORS + ' existing program or journey IDs in prototype mode.'
            );
            error.code = 'facility_navigation_activity_request_invalid';
            throw error;
        }
        const beforeState = this.session.getState();
        const beforeFingerprint = JSON.stringify(beforeState.layout || {});
        const beforeOperations = JSON.stringify(beforeState.operations || []);
        const basePayload = {
            baseRevision: beforeState.baseRevision,
            operations: Array.isArray(beforeState.operations)
                ? beforeState.operations : [],
        };
        this.activityRequestPending = true;
        try {
            this._renderToolbarState();
            const plannedJourneyIds = [];
            const ensureCurrent = () => {
                const current = this.session.getState();
                if (this.destroyed || (input.signal && input.signal.aborted)) {
                    const error = new Error('Movement preparation cancelled.');
                    error.code = 'facility_navigation_activity_cancelled';
                    throw error;
                }
                if (current.baseRevision !== beforeState.baseRevision
                        || activeLayoutAlternative(current) || this.constructionPreview
                        || (this.generationPlanningView && this.generationPlanningView.activeLayout())
                        || JSON.stringify(current.layout || {}) !== beforeFingerprint
                        || JSON.stringify(current.operations || []) !== beforeOperations) {
                    const error = new Error('The Facility Layout changed while navigation activity was prepared.');
                    error.code = 'facility_navigation_activity_stale';
                    throw error;
                }
            };
            for (const movementProgramId of programIds) {
                ensureCurrent();
                if (typeof input.onProgress === 'function') {
                    input.onProgress('Validating path ' + (plannedJourneyIds.length + 1)
                        + ' of ' + programIds.length + '...');
                }
                const compiled = await transport.compileNavigationSnapshot({
                    ...basePayload,
                    request: {
                        movementProgramId: movementProgramId,
                        prototypeMode: true,
                    },
                });
                ensureCurrent();
                const navigationPackageId = String(
                    compiled && compiled.summary
                    && compiled.summary.navigationPackageId || ''
                );
                if (!navigationPackageId) {
                    const error = new Error('Navigation snapshot response is incomplete.');
                    error.code = 'facility_navigation_snapshot_response_invalid';
                    throw error;
                }
                const planned = await transport.planActorJourney({
                    ...basePayload,
                    request: {
                        navigationPackageId: navigationPackageId,
                        movementProgramId: movementProgramId,
                        prototypeMode: true,
                    },
                });
                ensureCurrent();
                const summary = planned && planned.summary || {};
                const journeySolutionId = String(summary.journeySolutionId || '');
                if (!journeySolutionId || summary.outcome !== 'accepted') {
                    const error = new Error(
                        'The requested movement program did not produce an accepted journey.'
                    );
                    error.code = String(
                        summary.outcome || 'facility_navigation_journey_refused'
                    );
                    throw error;
                }
                plannedJourneyIds.push(journeySolutionId);
            }
            const journeySolutionIds = Array.from(new Set(
                suppliedJourneyIds.concat(plannedJourneyIds)
            ));
            ensureCurrent();
            const created = await transport.buildNavigationActivityScenario({
                ...basePayload,
                request: {
                    journeySolutionIds: journeySolutionIds,
                    handoffResultIds: Array.isArray(input.handoffResultIds)
                        ? Array.from(new Set(input.handoffResultIds.map(String)))
                        : [],
                    scenarioLabel: String(
                        input.scenarioLabel || 'Sage navigation activity'
                    ),
                    prototypeMode: true,
                },
            });
            ensureCurrent();
            const scenarioId = String(created && created.scenarioId || '');
            const activeRevision = String(created && created.layoutRevision || '');
            if (!scenarioId || !activeRevision) {
                const error = new Error('Navigation activity response is incomplete.');
                error.code = 'facility_navigation_activity_response_invalid';
                throw error;
            }
            const payload = await transport.getActivityScenario({
                scenarioId: scenarioId,
                activeRevision: activeRevision,
            });
            const currentState = this.session.getState();
            ensureCurrent();
            if (JSON.stringify(currentState.layout || {}) !== beforeFingerprint
                    || currentState.baseRevision !== beforeState.baseRevision
                    || JSON.stringify(currentState.operations || [])
                        !== beforeOperations) {
                const error = new Error(
                    'The Facility Layout changed while navigation activity was prepared.'
                );
                error.code = 'facility_navigation_activity_stale';
                throw error;
            }
            if (this.controller && typeof this.controller.ready === 'function') {
                await this.controller.ready();
            }
            ensureCurrent();
            if (this.motionState.loaded) this.clearMotionPlayback('activity_loaded');
            if (this.topAdapter
                    && typeof this.topAdapter.setActivityPresentation === 'function') {
                this.topAdapter.setActivityPresentation(payload);
            }
            try {
                await this.threeAdapter.activity.load(payload, activeRevision);
                try { ensureCurrent(); } catch (error) {
                    this.clearActivityPlayback('preparation_cancelled');
                    throw error;
                }
            } catch (error) {
                if (this.topAdapter
                        && typeof this.topAdapter.clearActivityPresentation === 'function') {
                    this.topAdapter.clearActivityPresentation();
                }
                throw error;
            }
            this.activityPresentation = clone(payload);
            this.activityLayoutFingerprint = beforeFingerprint;
            this._renderMotionPanel();
            return Object.assign({}, clone(created.summary || {}), {
                scenarioId: scenarioId,
                journeySolutionIds: journeySolutionIds,
                plannedJourneyCount: plannedJourneyIds.length,
                readOnlyPresentation: true,
            });
        } catch (error) {
            if (error.code !== 'facility_navigation_activity_cancelled'
                    && typeof this.options.onError === 'function') this.options.onError(error);
            throw error;
        } finally {
            this.activityRequestPending = false;
            if (!this.destroyed) this._renderToolbarState();
        }
    };

    Workspace.prototype.loadActivityPresentation = async function (
        payload,
        activeRevision
    ) {
        if (!this.threeAdapter || !this.threeAdapter.activity) {
            throw new Error('Facility activity renderer is unavailable.');
        }
        if (this.motionState.loaded) {
            this.clearMotionPlayback('activity_loaded');
        }
        if (this.topAdapter
                && typeof this.topAdapter.setActivityPresentation === 'function') {
            this.topAdapter.setActivityPresentation(payload);
        }
        try {
            const value = await this.threeAdapter.activity.load(
                payload,
                activeRevision
            );
            this.activityPresentation = clone(payload);
            this.activityLayoutFingerprint = JSON.stringify(
                this.state && this.state.layout || {}
            );
            return value;
        } catch (error) {
            if (this.topAdapter
                    && typeof this.topAdapter.clearActivityPresentation
                        === 'function') {
                this.topAdapter.clearActivityPresentation();
            }
            throw error;
        }
    };

    Workspace.prototype.clearActivityPlayback = function (reason) {
        if (this.topAdapter
                && typeof this.topAdapter.clearActivityPresentation
                    === 'function') {
            this.topAdapter.clearActivityPresentation();
        }
        if (this.threeAdapter && this.threeAdapter.activity
                && typeof this.threeAdapter.activity.dispose === 'function') {
            this.threeAdapter.activity.dispose(reason || 'cleared');
        }
        this.activityPresentation = null;
        this.activityLayoutFingerprint = null;
        this.activityState = Object.assign({}, this.activityState, {
            loaded: false,
            scenarioId: null,
            label: null,
            status: 'idle',
            statusReason: reason || null,
            playing: false,
            elapsedSeconds: 0,
            durationSeconds: 0,
            selectedActorId: null,
            departmentZoneId: null,
            actors: [],
            stationaryEvidence: null,
            unavailableActivity: [],
            prototypeMode: false,
            qualification: null,
            disclosure: null,
        });
        this._renderMotionPanel();
        return true;
    };

    Workspace.prototype._renderLayerVisibility = function () {
        if (!this.layerPanel) return;
        const wallButton = this.layerPanel.querySelector('[data-layer-action="perimeter-walls"]');
        if (wallButton) wallButton.disabled = !wallsRuntime.canEdit(this);
        Object.keys(DEFAULT_LAYER_VISIBILITY).forEach(function (key) {
            const input = this.layerPanel.querySelector(
                '[data-facility-layer="' + key + '"]'
            );
            if (input) input.checked = this.layerVisibility[key] !== false;
        }, this);
        this.layerPanel.hidden = !this.layerPanelOpen;
        [this.planNavigation, this.threeNavigation].filter(Boolean)
            .forEach(function (navigation) {
                const attribute = navigation === this.planNavigation
                    ? 'data-plan-command' : 'data-three-command';
                const button = navigation.querySelector(
                    '[' + attribute + '="layers"]'
                );
                if (button) {
                    button.setAttribute(
                        'aria-pressed',
                        this.layerPanelOpen ? 'true' : 'false'
                    );
                    button.setAttribute(
                        'aria-expanded',
                        this.layerPanelOpen ? 'true' : 'false'
                    );
                }
            }, this);
    };

    Workspace.prototype._applyLayerVisibility = function () {
        [this.topAdapter, this.threeAdapter].filter(Boolean)
            .forEach(function (adapter) {
                if (typeof adapter.setLayerVisibility === 'function') {
                    adapter.setLayerVisibility(this.layerVisibility);
                }
            }, this);
        this._renderLayerVisibility();
        return clone(this.layerVisibility);
    };

    Workspace.prototype._setLayerPanelOpen = function (open) {
        this.layerPanelOpen = open === true;
        if (this.layerPanelOpen) {
            this.threeSettingsOpen = false;
            this.threeViewMenuOpen = false;
            this.threeViewpointsOpen = false;
            if (this.threeSettingsPanel) this.threeSettingsPanel.hidden = true;
        }
        this._renderLayerVisibility();
        this._renderThreeNavigationState();
    };

    Workspace.prototype._handleLayerPanelInput = function (event) {
        const key = targetDataId(
            event.target,
            'data-facility-layer',
            this.layerPanel
        );
        if (!key || !Object.prototype.hasOwnProperty.call(
            DEFAULT_LAYER_VISIBILITY,
            key
        )) return;
        this.layerVisibility[key] = event.target.checked === true;
        this.layerVisibility = normalizeLayerVisibility(
            this.layerVisibility
        );
        this._applyLayerVisibility();
    };

    Workspace.prototype._handleLayerPanelClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-layer-action',
            this.layerPanel
        );
        if (action === 'perimeter-walls') {
            event.preventDefault();
            try { wallsRuntime.openDialog(this); } catch (error) { this._setError(error); }
            return;
        }
        if (action !== 'show-all') return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        this.layerVisibility = normalizeLayerVisibility(
            DEFAULT_LAYER_VISIBILITY
        );
        this._applyLayerVisibility();
    };

    Workspace.prototype._buildAssetBrowser = function () {
        this.assetBrowser = element(this.document, 'section', {
            className: 'ip-flw-asset-browser',
            role: 'dialog',
            'aria-modal': 'true',
            'aria-label': 'Asset Library',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-asset-browser-header',
        });
        const heading = element(this.document, 'div', {
            className: 'ip-flw-asset-browser-heading',
        });
        heading.appendChild(element(this.document, 'h2', {}, 'Asset Library'));
        heading.appendChild(element(this.document, 'p', {},
            'Select equipment and resources to add to the facility layout'));
        this.assetBrowserClose = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-asset-browser-close',
            'data-asset-browser-action': 'close',
            'aria-label': 'Close asset library',
            title: 'Close asset library',
        }, 'X');
        append(header, heading, this.assetBrowserClose);

        const controls = element(this.document, 'div', {
            className: 'ip-flw-asset-browser-controls',
        });
        const searchLabel = element(this.document, 'label', {
            className: 'ip-flw-asset-browser-search',
        });
        searchLabel.appendChild(element(this.document, 'span', {
            className: 'ip-flw-visually-hidden',
        }, 'Search asset library'));
        this.assetBrowserSearch = element(this.document, 'input', {
            type: 'search',
            placeholder: 'Search machines, material handling, storage, workstations...',
            'aria-label': 'Search asset library',
            autocomplete: 'off',
        });
        searchLabel.appendChild(this.assetBrowserSearch);
        this.assetCategoryNav = element(this.document, 'div', {
            className: 'ip-flw-asset-categories',
            role: 'tablist',
            'aria-label': 'Asset categories',
        });
        append(controls, searchLabel, this.assetCategoryNav);

        this.assetGrid = element(this.document, 'div', {
            className: 'ip-flw-asset-grid',
            role: 'list',
            'aria-label': 'Available facility assets',
        });
        this.assetBrowserEmpty = element(this.document, 'div', {
            className: 'ip-flw-asset-browser-empty',
            hidden: true,
        });
        this.assetBrowserEmpty.appendChild(element(
            this.document,
            'p',
            {},
            'No assets match your search.'
        ));
        this.assetBrowserEmpty.appendChild(element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-secondary-action',
            'data-asset-browser-action': 'clear-filters',
        }, 'Clear filters'));

        const footer = element(this.document, 'footer', {
            className: 'ip-flw-asset-browser-footer',
        });
        this.assetBrowserSelectionStatus = element(this.document, 'div', {
            className: 'ip-flw-asset-selection-status',
            role: 'status',
            'aria-live': 'polite',
            'aria-atomic': 'true',
        }, 'No assets selected');
        const actions = element(this.document, 'div', {
            className: 'ip-flw-asset-browser-actions',
        });
        this.assetBrowserCancel = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-secondary-action',
            'data-asset-browser-action': 'cancel',
        }, 'Cancel');
        this.assetBrowserAdd = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-primary-action',
            'data-asset-browser-action': 'add',
            disabled: true,
        }, 'Add to Layout');
        append(actions, this.assetBrowserCancel, this.assetBrowserAdd);
        append(footer, this.assetBrowserSelectionStatus, actions);
        append(
            this.assetBrowser,
            header,
            controls,
            this.assetGrid,
            this.assetBrowserEmpty,
            footer
        );
    };

    Workspace.prototype._buildFloorMarkingPalette = function () {
        this.floorMarkingPalette = element(this.document, 'section', {
            className: 'ip-flw-floor-marking-palette',
            role: 'dialog',
            'aria-label': 'Floor markings',
            hidden: true,
            'aria-hidden': 'true',
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-floor-marking-palette-header',
        });
        append(header,
            element(this.document, 'h3', {}, 'Floor Markings'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-floor-marking-close',
                'data-floor-marking-action': 'close',
                'aria-label': 'Close floor marking palette',
                title: 'Close',
            }, 'X')
        );
        const grid = element(this.document, 'div', {
            className: 'ip-flw-floor-marking-grid',
            role: 'list',
        });
        FLOOR_MARKING_PRESETS.forEach(function (preset) {
            const button = element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-floor-marking-option',
                'data-floor-marking-type': preset.type,
                'aria-pressed': this.floorMarkingState.type === preset.type
                    ? 'true' : 'false',
                title: preset.label,
            });
            append(button,
                element(this.document, 'span', {
                    className: 'ip-flw-floor-marking-swatch',
                    'data-marking-swatch': preset.type,
                    'aria-hidden': 'true',
                }),
                element(this.document, 'span', {}, preset.label)
            );
            grid.appendChild(button);
        }, this);
        append(this.floorMarkingPalette, header, grid);
    };

    Workspace.prototype._floorMarkingPreset = function (type) {
        return FLOOR_MARKING_PRESETS.find(function (preset) {
            return preset.type === type;
        }) || FLOOR_MARKING_PRESETS[0];
    };

    Workspace.prototype.openFloorMarkingPalette = function () {
        if (!this.capabilities.manualAuthoring || this.viewMode !== 'plan') {
            return false;
        }
        this.floorMarkingState.open = true;
        this.floorMarkingPalette.hidden = false;
        this.floorMarkingPalette.setAttribute('aria-hidden', 'false');
        this._setToolMode('floor-marking');
        return true;
    };

    Workspace.prototype.closeFloorMarkingPalette = function (selectTool) {
        this.floorMarkingState.open = false;
        this.floorMarkingPalette.hidden = true;
        this.floorMarkingPalette.setAttribute('aria-hidden', 'true');
        if (selectTool === true && this.toolMode === 'floor-marking') {
            this._setToolMode('select');
        }
        return true;
    };

    Workspace.prototype._handleFloorMarkingPaletteClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-floor-marking-action',
            this.floorMarkingPalette
        );
        if (action === 'close') {
            this.closeFloorMarkingPalette(true);
            return;
        }
        const type = targetDataId(
            event.target,
            'data-floor-marking-type',
            this.floorMarkingPalette
        );
        if (!type) return;
        const preset = this._floorMarkingPreset(type);
        this.floorMarkingState.type = preset.type;
        Array.prototype.forEach.call(
            this.floorMarkingPalette.querySelectorAll('[data-floor-marking-type]'),
            function (button) {
                button.setAttribute(
                    'aria-pressed',
                    button.getAttribute('data-floor-marking-type') === preset.type
                        ? 'true' : 'false'
                );
            }
        );
        this.closeFloorMarkingPalette(false);
        this._setToolMode('floor-marking');
        if (typeof this.planView.focus === 'function') this.planView.focus();
    };

    Workspace.prototype._floorMarkingFromGesture = function (start, end) {
        const preset = this._floorMarkingPreset(this.floorMarkingState.type);
        const dx = end.x - start.x;
        const dz = end.z - start.z;
        const lineLike = [
            'direction_arrow', 'solid_line', 'dashed_line',
        ].includes(preset.type);
        const distance = Math.hypot(dx, dz);
        const width = lineLike
            ? preset.width : Math.max(Math.abs(dx), preset.width * 0.15);
        const depth = lineLike
            ? Math.max(distance, preset.depth * 0.2)
            : Math.max(Math.abs(dz), preset.depth * 0.15);
        const center = distance > 0.001 ? {
            x: (start.x + end.x) / 2,
            y: finite(start.y, 0),
            z: (start.z + end.z) / 2,
        } : {
            x: start.x,
            y: finite(start.y, 0),
            z: start.z,
        };
        return {
            markingType: preset.type,
            label: preset.label,
            semanticRole: preset.semanticRole,
            transform: {
                position: center,
                rotationDegrees: lineLike && distance > 0.001
                    ? Math.atan2(dx, dz) * 180 / Math.PI : 0,
            },
            width: distance > 0.001 ? width : preset.width,
            depth: distance > 0.001 ? depth : preset.depth,
            fillColor: preset.fillColor,
            strokeColor: preset.strokeColor,
            opacity: 1,
            text: preset.text,
            positionMode: 'manual',
            metadata: { authoredIn: 'facility_plan' },
            evidence: [],
        };
    };

    Workspace.prototype._precisionSelectedPlacements = function () {
        const layout = this.state && this.state.layout;
        if (!layout || !Array.isArray(layout.placements)) return [];
        const selection = new Set(this.state.selection || []);
        return layout.placements.filter(function (placement) {
            return selection.has(placement.placementId);
        });
    };

    Workspace.prototype._precisionPlacementLabel = function (placement) {
        return cleanString(
            placement && placement.metadata
                && placement.metadata.instanceLabel,
            placement && placement.placementId || 'Placement'
        );
    };

    Workspace.prototype._precisionSelect = function (label, field, values) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        const select = element(this.document, 'select', {
            'data-precision-field': field,
            'aria-label': label,
        });
        values.forEach(function (item) {
            const option = element(this.document, 'option', {
                value: item.value,
            }, item.label);
            if (String(item.value) === String(this.precisionState[field])) {
                option.selected = true;
                option.setAttribute('selected', 'selected');
            }
            select.appendChild(option);
        }, this);
        select.value = String(this.precisionState[field] || '');
        wrapper.appendChild(select);
        return wrapper;
    };

    Workspace.prototype._precisionNumber = function (label, field, value) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        wrapper.appendChild(element(this.document, 'input', {
            type: 'number',
            min: field === 'offsetX' || field === 'offsetZ' ? '' : '0',
            step: this.planPreferences.unit === 'ft' ? '0.1' : '0.05',
            value: String(Number(finite(value, 0).toFixed(4))),
            'data-precision-field': field,
            'aria-label': label,
        }));
        return wrapper;
    };

    Workspace.prototype._buildPrecisionDialog = function () {
        this.precisionDialog = element(this.document, 'section', {
            className: 'ip-flw-precision-dialog',
            role: 'dialog',
            'aria-modal': 'false',
            'aria-labelledby': 'ip-flw-precision-title',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-precision-header',
        });
        this.precisionTitle = element(this.document, 'h2', {
            id: 'ip-flw-precision-title',
        }, 'Position equipment');
        this.precisionClose = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-precision-close',
            'data-precision-action': 'close',
            'aria-label': 'Close positioning tools',
            title: 'Close',
        }, 'X');
        append(header, this.precisionTitle, this.precisionClose);
        this.precisionTabs = element(this.document, 'div', {
            className: 'ip-flw-precision-tabs',
            role: 'tablist',
            'aria-label': 'Positioning tool',
        });
        [
            ['align', 'Align'],
            ['distribute', 'Distribute'],
            ['relative', 'Relative'],
            ['distance', 'Distance'],
            ['offset', 'Offset'],
        ].forEach(function (item) {
            this.precisionTabs.appendChild(element(this.document, 'button', {
                type: 'button',
                role: 'tab',
                'data-precision-mode': item[0],
            }, item[1]));
        }, this);
        this.precisionBody = element(this.document, 'div', {
            className: 'ip-flw-precision-body',
        });
        const footer = element(this.document, 'footer', {
            className: 'ip-flw-precision-footer',
        });
        this.precisionStatus = element(this.document, 'div', {
            className: 'ip-flw-precision-status',
            role: 'status',
            'aria-live': 'polite',
        });
        const actions = element(this.document, 'div', {
            className: 'ip-flw-precision-actions',
        });
        this.precisionCancel = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-secondary-action',
            'data-precision-action': 'cancel',
        }, 'Cancel');
        this.precisionApply = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-primary-action',
            'data-precision-action': 'apply',
        }, 'Apply');
        append(actions, this.precisionCancel, this.precisionApply);
        append(footer, this.precisionStatus, actions);
        append(
            this.precisionDialog,
            header,
            this.precisionTabs,
            this.precisionBody,
            footer
        );
    };

    Workspace.prototype._patternSelect = function (label, field, options) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        const select = element(this.document, 'select', {
            'data-pattern-field': field,
            'aria-label': label,
        });
        (options || []).forEach(function (item) {
            select.appendChild(element(this.document, 'option', {
                value: item.value,
            }, item.label));
        }, this);
        select.value = String(this.patternState[field] || '');
        wrapper.appendChild(select);
        return wrapper;
    };

    Workspace.prototype._patternNumber = function (label, field, value, options) {
        const config = options || {};
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        wrapper.appendChild(element(this.document, 'input', {
            type: 'number',
            min: config.min === undefined ? '' : String(config.min),
            max: config.max === undefined ? '' : String(config.max),
            step: config.step === undefined ? '0.1' : String(config.step),
            value: String(Number(finite(value, 0).toFixed(4))),
            'data-pattern-field': field,
            'aria-label': label,
        }));
        return wrapper;
    };

    Workspace.prototype._patternCheckbox = function (label, field) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-check',
        });
        const input = element(this.document, 'input', {
            type: 'checkbox',
            'data-pattern-field': field,
        });
        input.checked = this.patternState[field] === true;
        append(wrapper, input, element(this.document, 'span', {}, label));
        return wrapper;
    };

    Workspace.prototype._buildPatternDialog = function () {
        this.patternDialog = element(this.document, 'section', {
            className: 'ip-flw-precision-dialog ip-flw-pattern-dialog',
            role: 'dialog',
            'aria-modal': 'false',
            'aria-labelledby': 'ip-flw-pattern-title',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-precision-header',
        });
        this.patternTitle = element(this.document, 'h2', {
            id: 'ip-flw-pattern-title',
        }, 'Create layout pattern');
        this.patternClose = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-precision-close',
            'data-pattern-action': 'close',
            'aria-label': 'Close pattern tools',
            title: 'Close',
        }, 'X');
        append(header, this.patternTitle, this.patternClose);
        this.patternTabs = element(this.document, 'div', {
            className: 'ip-flw-precision-tabs',
            role: 'tablist',
            'aria-label': 'Pattern tool',
        });
        [
            ['linear-pattern', 'Linear'],
            ['circular-pattern', 'Circular'],
            ['perimeter-pattern', 'Perimeter'],
            ['cell-layout', 'Cell Layout'],
            ['vertical-stack', 'Stack'],
            ['surface-stack', 'On Surface'],
            ['mirror', 'Mirror'],
            ['swap', 'Swap'],
        ].forEach(function (item) {
            this.patternTabs.appendChild(element(this.document, 'button', {
                type: 'button',
                role: 'tab',
                'data-pattern-mode': item[0],
            }, item[1]));
        }, this);
        this.patternBody = element(this.document, 'div', {
            className: 'ip-flw-precision-body',
        });
        const footer = element(this.document, 'footer', {
            className: 'ip-flw-precision-footer',
        });
        this.patternStatus = element(this.document, 'div', {
            className: 'ip-flw-precision-status',
            role: 'status',
            'aria-live': 'polite',
        });
        const actions = element(this.document, 'div', {
            className: 'ip-flw-precision-actions',
        });
        this.patternCancel = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-secondary-action',
            'data-pattern-action': 'cancel',
        }, 'Cancel');
        this.patternApply = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-primary-action',
            'data-pattern-action': 'apply',
        }, 'Apply');
        append(actions, this.patternCancel, this.patternApply);
        append(footer, this.patternStatus, actions);
        append(
            this.patternDialog,
            header,
            this.patternTabs,
            this.patternBody,
            footer
        );
    };

    Workspace.prototype._buildPlanSettingsDialog = function () {
        this.planSettingsDialog = element(this.document, 'section', {
            className: 'ip-flw-precision-dialog ip-flw-plan-settings-dialog',
            role: 'dialog',
            'aria-modal': 'false',
            'aria-labelledby': 'ip-flw-plan-settings-title',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-precision-header',
        });
        this.planSettingsTitle = element(this.document, 'h2', {
            id: 'ip-flw-plan-settings-title',
        }, 'Facility plan settings');
        const close = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-precision-close',
            'data-plan-settings-action': 'cancel',
            'aria-label': 'Close facility plan settings',
            title: 'Close',
        }, 'X');
        append(header, this.planSettingsTitle, close);
        this.planSettingsBody = element(this.document, 'div', {
            className: 'ip-flw-precision-body',
        });
        const footer = element(this.document, 'footer', {
            className: 'ip-flw-precision-footer',
        });
        this.planSettingsStatus = element(this.document, 'div', {
            className: 'ip-flw-precision-status',
            role: 'status',
            'aria-live': 'polite',
        });
        const actions = element(this.document, 'div', {
            className: 'ip-flw-precision-actions',
        });
        append(actions,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary-action',
                'data-plan-settings-action': 'cancel',
            }, 'Cancel'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-primary-action',
                'data-plan-settings-action': 'apply',
            }, 'Apply')
        );
        append(footer, this.planSettingsStatus, actions);
        append(this.planSettingsDialog, header, this.planSettingsBody, footer);
    };

    Workspace.prototype._buildClearAllDialog = function () {
        this.clearAllDialog = element(this.document, 'section', {
            className: 'ip-flw-precision-dialog ip-flw-clear-all-dialog',
            role: 'alertdialog',
            'aria-modal': 'false',
            'aria-labelledby': 'ip-flw-clear-all-title',
            'aria-describedby': 'ip-flw-clear-all-description',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-precision-header',
        });
        append(header,
            element(this.document, 'h2', {
                id: 'ip-flw-clear-all-title',
            }, 'Clear facility layout'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-precision-close',
                'data-clear-all-action': 'cancel',
                'aria-label': 'Close clear-layout confirmation',
                title: 'Close',
            }, 'X')
        );
        const body = element(this.document, 'div', {
            className: 'ip-flw-precision-body',
        });
        body.appendChild(element(this.document, 'p', {
            id: 'ip-flw-clear-all-description',
            className: 'ip-flw-clear-all-warning',
        }, 'Remove all equipment, cells, floor markings, routes, and utility '
            + 'content from this layout? Facility dimensions and grid settings '
            + 'will be preserved.'));
        body.appendChild(element(this.document, 'p', {
            className: 'ip-flw-precision-selection',
        }, 'This action is recorded as one operation and can be undone.'));
        const footer = element(this.document, 'footer', {
            className: 'ip-flw-precision-footer',
        });
        const status = element(this.document, 'div', {
            className: 'ip-flw-precision-status',
            role: 'status',
            'aria-live': 'polite',
        });
        this.clearAllStatus = status;
        const actions = element(this.document, 'div', {
            className: 'ip-flw-precision-actions',
        });
        append(actions,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary-action',
                'data-clear-all-action': 'cancel',
            }, 'Cancel'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-danger-action',
                'data-clear-all-action': 'apply',
            }, 'Clear layout')
        );
        append(footer, status, actions);
        append(this.clearAllDialog, header, body, footer);
    };

    Workspace.prototype._buildBulkZoneDialog = function () {
        this.bulkZoneDialog = element(this.document, 'section', {
            className: 'ip-flw-precision-dialog ip-flw-bulk-zone-dialog',
            role: 'dialog',
            'aria-modal': 'false',
            'aria-labelledby': 'ip-flw-bulk-zone-title',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-precision-header',
        });
        append(header,
            element(this.document, 'h2', {
                id: 'ip-flw-bulk-zone-title',
            }, 'Create facility zones'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-precision-close',
                'data-bulk-zone-action': 'cancel',
                'aria-label': 'Close bulk zone editor',
                title: 'Close',
            }, 'X')
        );
        this.bulkZoneBody = element(this.document, 'div', {
            className: 'ip-flw-bulk-zone-body',
        });
        const footer = element(this.document, 'footer', {
            className: 'ip-flw-precision-footer',
        });
        this.bulkZoneStatus = element(this.document, 'div', {
            className: 'ip-flw-precision-status',
            role: 'status',
            'aria-live': 'polite',
        });
        const actions = element(this.document, 'div', {
            className: 'ip-flw-precision-actions',
        });
        append(actions,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary-action',
                'data-bulk-zone-action': 'add-row',
            }, 'Add zone'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary-action',
                'data-bulk-zone-action': 'cancel',
            }, 'Cancel'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-primary-action',
                'data-bulk-zone-action': 'apply',
            }, 'Create zones')
        );
        append(footer, this.bulkZoneStatus, actions);
        append(this.bulkZoneDialog, header, this.bulkZoneBody, footer);
    };

    Workspace.prototype._buildCellGroupDialog = function () {
        this.cellGroupDialog = element(this.document, 'section', {
            className: 'ip-flw-precision-dialog ip-flw-cell-group-dialog',
            role: 'dialog',
            'aria-modal': 'false',
            'aria-labelledby': 'ip-flw-cell-group-title',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-precision-header',
        });
        append(header,
            element(this.document, 'h2', {
                id: 'ip-flw-cell-group-title',
            }, 'Create manufacturing cell'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-precision-close',
                'data-cell-group-action': 'cancel',
                'aria-label': 'Close manufacturing cell panel',
                title: 'Close',
            }, 'X')
        );
        this.cellGroupBody = element(this.document, 'div', {
            className: 'ip-flw-precision-body',
        });
        const footer = element(this.document, 'footer', {
            className: 'ip-flw-precision-footer',
        });
        this.cellGroupStatus = element(this.document, 'div', {
            className: 'ip-flw-precision-status',
            role: 'status',
            'aria-live': 'polite',
        });
        const actions = element(this.document, 'div', {
            className: 'ip-flw-precision-actions',
        });
        append(actions,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary-action',
                'data-cell-group-action': 'cancel',
            }, 'Cancel'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-primary-action',
                'data-cell-group-action': 'apply',
            }, 'Create cell')
        );
        append(footer, this.cellGroupStatus, actions);
        append(this.cellGroupDialog, header, this.cellGroupBody, footer);
    };

    Workspace.prototype._buildAisleDialog = function () {
        this.aisleDialog = element(this.document, 'section', {
            className: 'ip-flw-precision-dialog ip-flw-aisle-dialog',
            role: 'dialog',
            'aria-modal': 'false',
            'aria-labelledby': 'ip-flw-aisle-title',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-precision-header',
        });
        append(header,
            element(this.document, 'h2', {
                id: 'ip-flw-aisle-title',
            }, 'Create semantic aisle'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-precision-close',
                'data-aisle-action': 'close',
                'aria-label': 'Close aisle tool',
                title: 'Close',
            }, 'X')
        );
        this.aisleBody = element(this.document, 'div', {
            className: 'ip-flw-precision-body',
        });
        const footer = element(this.document, 'footer', {
            className: 'ip-flw-precision-footer',
        });
        this.aisleStatus = element(this.document, 'div', {
            className: 'ip-flw-precision-status',
            role: 'status',
            'aria-live': 'polite',
        });
        const actions = element(this.document, 'div', {
            className: 'ip-flw-precision-actions',
        });
        append(actions,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary-action',
                'data-aisle-action': 'close',
            }, 'Close'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-primary-action',
                'data-aisle-action': 'draw',
            }, 'Draw aisle')
        );
        append(footer, this.aisleStatus, actions);
        append(this.aisleDialog, header, this.aisleBody, footer);
    };

    Workspace.prototype._buildNavigationDialog = function () {
        this.navigationDialog = element(this.document, 'section', {
            className: 'ip-flw-precision-dialog ip-flw-navigation-dialog',
            role: 'dialog',
            'aria-modal': 'false',
            'aria-labelledby': 'ip-flw-navigation-title',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-precision-header',
        });
        append(header,
            element(this.document, 'h2', {
                id: 'ip-flw-navigation-title',
            }, 'Author motion path'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-precision-close',
                'data-navigation-action': 'close',
                'aria-label': 'Close motion path tool',
                title: 'Close',
            }, 'X')
        );
        this.navigationBody = element(this.document, 'div', {
            className: 'ip-flw-precision-body ip-flw-navigation-body',
        });
        const footer = element(this.document, 'footer', {
            className: 'ip-flw-precision-footer',
        });
        this.navigationStatus = element(this.document, 'div', {
            className: 'ip-flw-precision-status',
            role: 'status',
            'aria-live': 'polite',
        });
        const actions = element(this.document, 'div', {
            className: 'ip-flw-precision-actions',
        });
        append(actions,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary-action',
                'data-navigation-action': 'close',
            }, 'Close'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-primary-action',
                'data-navigation-action': 'apply',
            }, 'Apply path')
        );
        append(footer, this.navigationStatus, actions);
        append(this.navigationDialog, header, this.navigationBody, footer);
    };

    Workspace.prototype._navigationField = function (
        label,
        field,
        type,
        value,
        attributes
    ) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        wrapper.appendChild(element(this.document, 'input', Object.assign({
            type: type,
            value: value,
            'data-navigation-field': field,
        }, attributes || {})));
        return wrapper;
    };

    Workspace.prototype._navigationSelect = function (
        label,
        field,
        options,
        value
    ) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        const select = element(this.document, 'select', {
            'data-navigation-field': field,
        });
        options.forEach(function (option) {
            select.appendChild(element(this.document, 'option', {
                value: option[0],
                selected: option[0] === value,
            }, option[1]));
        }, this);
        wrapper.appendChild(select);
        return wrapper;
    };

    Workspace.prototype._navigationActionButton = function (
        action,
        label,
        disabled,
        pressed
    ) {
        return element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-secondary-action',
            'data-navigation-action': action,
            disabled: Boolean(disabled),
            'aria-pressed': pressed === undefined ? null
                : (pressed ? 'true' : 'false'),
        }, label);
    };

    Workspace.prototype._navigationActorRecord = function () {
        const actorId = this.navigationState.actorPlacementId;
        return this.state && this.state.layout
            ? (this.state.layout.placements || []).find(function (item) {
                return item.placementId === actorId;
            }) || null : null;
    };

    Workspace.prototype._navigationActorLabel = function () {
        const placement = this._navigationActorRecord();
        return placement && placement.metadata
            && (placement.metadata.instanceLabel
                || placement.metadata.displayName)
            || placement && placement.assetId
            || this.navigationState.actorPlacementId
            || 'No actor selected';
    };

    Workspace.prototype._renderNavigationDialog = function () {
        if (!this.navigationDialog) return;
        const navigation = this.navigationState;
        this.navigationDialog.hidden = !navigation.open;
        if (!navigation.open) return;
        clearElement(this.navigationBody);
        const actor = element(this.document, 'div', {
            className: 'ip-flw-navigation-actor',
        });
        append(actor,
            element(this.document, 'strong', {}, this._navigationActorLabel()),
            element(this.document, 'span', {}, navigation.actorClass
                ? navigation.actorClass.replace('_', ' ') : 'unknown actor')
        );
        const configuration = element(this.document, 'div', {
            className: 'ip-flw-navigation-grid',
        });
        append(configuration,
            this._navigationSelect('Loop', 'loopMode', [
                ['one_way', 'One way'],
                ['closed_loop', 'Closed loop'],
                ['out_and_return', 'Out and return'],
                ['paired_lane_return', 'Paired-lane return'],
                ['task_cycle', 'Task cycle'],
            ], navigation.loopMode),
            this._navigationSelect('Direction', 'direction', [
                ['forward', 'Forward'],
                ['reverse', 'Reverse'],
                ['bidirectional', 'Bidirectional'],
            ], navigation.direction),
            this._navigationSelect('Constraint', 'constraintMode', [
                ['complete_override', 'Complete override'],
                ['guide', 'Guide'],
                ['locked_segment', 'Locked segment'],
                ['preferred_corridor', 'Preferred corridor'],
            ], navigation.constraintMode)
        );
        if (navigation.actorClass === 'vehicle') {
            append(configuration,
                this._navigationField(
                    'Vehicle profile ID',
                    'actorProfileId',
                    'text',
                    navigation.actorProfileId
                ),
                this._navigationField(
                    'Exact profile revision',
                    'actorProfileRevision',
                    'text',
                    navigation.actorProfileRevision,
                    { maxlength: 64, spellcheck: 'false' }
                )
            );
        }
        const editActions = element(this.document, 'div', {
            className: 'ip-flw-navigation-actions',
        });
        append(editActions,
            this._navigationActionButton(
                'draw',
                navigation.drawing ? 'Drawing active' : 'Add waypoints',
                false,
                navigation.drawing
            ),
            this._navigationActionButton(
                'finish',
                'Finish drawing',
                navigation.points.length < 2
            ),
            this._navigationActionButton(
                'reverse',
                'Reverse',
                navigation.points.length < 2
            ),
            this._navigationActionButton(
                'insert',
                'Insert after selected',
                navigation.selectedPointIndex === null
                    || navigation.points.length < 2
            ),
            this._navigationActionButton(
                'delete',
                'Delete waypoint',
                navigation.selectedPointIndex === null
                    || navigation.points.length <= 2
            ),
            this._navigationActionButton(
                'lock',
                'Lock segment',
                navigation.selectedPointIndex === null
                    || navigation.selectedPointIndex
                        >= navigation.points.length - 1,
                navigation.lockedSegmentIndexes.includes(
                    navigation.selectedPointIndex
                )
            )
        );
        const anchorActions = element(this.document, 'div', {
            className: 'ip-flw-navigation-anchor-row',
        });
        const ownerOptions = (this.state.layout.placements || []).map(
            function (placement) {
                const label = placement.metadata
                    && (placement.metadata.instanceLabel
                        || placement.metadata.displayName)
                    || placement.assetId || placement.placementId;
                return [placement.placementId, label];
            }
        );
        append(anchorActions,
            this._navigationSelect('Anchor', 'anchorKind', [
                ['station_operate', 'Station operate'],
                ['station_load', 'Station load'],
                ['station_unload', 'Station unload'],
                ['station_inspect', 'Station inspect'],
                ['fifo_input', 'FIFO input'],
                ['fifo_output', 'FIFO output'],
                ['cell_entrance', 'Cell entrance'],
                ['crossing', 'Crossing'],
                ['vehicle_parking', 'Vehicle parking'],
                ['vehicle_turnaround', 'Vehicle turnaround'],
                ['handoff_endpoint', 'Handoff endpoint'],
            ], navigation.anchorKind),
            this._navigationSelect(
                'Anchor owner',
                'anchorOwnerPlacementId',
                ownerOptions,
                navigation.anchorOwnerPlacementId
            ),
            this._navigationActionButton(
                'add-anchor',
                navigation.anchorPicking ? 'Click anchor point'
                    : 'Place anchor',
                !navigation.anchorOwnerPlacementId,
                navigation.anchorPicking
            )
        );
        const previewActions = element(this.document, 'div', {
            className: 'ip-flw-navigation-actions',
        });
        append(previewActions,
            this._navigationActionButton(
                'preview',
                navigation.previewPlaying ? 'Pause preview' : 'Play preview',
                navigation.points.length < 2,
                navigation.previewPlaying
            ),
            this._navigationActionButton(
                'paths',
                navigation.pathsVisible ? 'Hide paths' : 'Show paths',
                false,
                navigation.pathsVisible
            ),
            this._navigationActionButton(
                'export',
                'Export gold case',
                !navigation.lastConstraintId
            )
        );
        const timeline = this._navigationField(
            'Preview position',
            'previewNormalizedTime',
            'range',
            navigation.previewNormalizedTime,
            { min: 0, max: 1, step: 0.001 }
        );
        const summary = element(this.document, 'p', {
            className: 'ip-flw-property-note',
        }, navigation.points.length + ' waypoint'
            + (navigation.points.length === 1 ? '' : 's')
            + '. Coordinates come only from Plan pointer input. '
            + 'A pending path is navigation intent, not a safety, capacity, '
            + 'timing, or compliance approval.');
        append(
            this.navigationBody,
            actor,
            configuration,
            editActions,
            anchorActions,
            previewActions,
            timeline,
            summary
        );
        this.navigationStatus.textContent = navigation.message
            || (navigation.drawing
                ? 'Click the Plan to add waypoints; drag a waypoint to refine it.'
                : navigation.anchorPicking
                    ? 'Click the Plan to author the selected semantic anchor.'
                    : 'Review the path, then apply it as one unsaved gesture.');
        const apply = this.navigationDialog.querySelector(
            '[data-navigation-action="apply"]'
        );
        if (apply) {
            apply.disabled = navigation.applying
                || navigation.points.length < 2
                || (navigation.actorClass === 'vehicle'
                    && (!navigation.actorProfileId
                        || !/^[0-9a-f]{64}$/.test(
                            navigation.actorProfileRevision
                        )));
        }
    };

    Workspace.prototype._planSettingsNumber = function (
        label,
        field,
        value,
        options
    ) {
        const config = options || {};
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        wrapper.appendChild(element(this.document, 'input', {
            type: 'number',
            min: config.min === undefined ? '' : String(config.min),
            max: config.max === undefined ? '' : String(config.max),
            step: config.step === undefined ? '0.1' : String(config.step),
            value: String(Number(finite(value, 0).toFixed(4))),
            'data-plan-settings-field': field,
            'aria-label': label,
        }));
        return wrapper;
    };

    Workspace.prototype._currentPlanScaleDistance = function () {
        const snapshot = this.topAdapter
            && typeof this.topAdapter.getViewportState === 'function'
            ? this.topAdapter.getViewportState() : null;
        const scale = snapshot && snapshot.projection
            ? finite(snapshot.projection.scale, 0) : 0;
        if (!(scale > 0)) return 5;
        const preferred = preferredScaleDistance(
            scale,
            this.planPreferences.unit
        );
        return canonicalDistance(
            preferred.displayDistance,
            this.planPreferences.unit
        );
    };

    Workspace.prototype._renderPlanSettingsDialog = function () {
        if (!this.planSettingsDialog) return;
        this.planSettingsDialog.hidden = !this.planSettingsState.open;
        if (!this.planSettingsState.open) return;
        const unit = this.planPreferences.unit;
        const draft = normalizePlanSettings(
            this.planSettingsState.draft,
            this.planSettings
        );
        this.planSettingsState.draft = draft;
        clearElement(this.planSettingsBody);
        append(
            this.planSettingsBody,
            this._planSettingsNumber(
                'Facility width (' + unit + ')',
                'widthMeters',
                displayDistance(draft.widthMeters, unit),
                { min: 0.5, max: 10000 }
            ),
            this._planSettingsNumber(
                'Facility depth (' + unit + ')',
                'depthMeters',
                displayDistance(draft.depthMeters, unit),
                { min: 0.5, max: 10000 }
            ),
            this._planSettingsNumber(
                'Minor grid spacing (' + unit + ')',
                'gridSpacingMeters',
                displayDistance(draft.gridSpacingMeters, unit),
                { min: 0.05, max: 10000, step: 0.05 }
            ),
            this._planSettingsNumber(
                'Scale bar distance (' + unit + ')',
                'scaleDistanceMeters',
                displayDistance(
                    this.planSettingsState.scaleDistanceMeters,
                    unit
                ),
                { min: 0.01, max: 10000, step: 0.1 }
            )
        );
        this.planSettingsBody.appendChild(element(this.document, 'p', {
            className: 'ip-flw-precision-selection',
        }, 'Major grid lines use five minor intervals when the facility allows. '
            + 'Scale bar distance changes only the Plan camera zoom.'));
        this.planSettingsStatus.textContent = formattedDistance(
            displayDistance(draft.widthMeters, unit)
        ) + ' x ' + formattedDistance(
            displayDistance(draft.depthMeters, unit)
        ) + ' ' + unit + ' | Grid '
            + formattedDistance(displayDistance(
                draft.gridSpacingMeters,
                unit
            )) + ' ' + unit;
    };

    Workspace.prototype._applyPlanEnvironment = function (settings) {
        const normalized = normalizePlanSettings(settings, this.planSettings);
        this.gridSize = normalized.gridSpacingMeters;
        const currentBounds = this.options.topPlanOptions
            && this.options.topPlanOptions.worldBounds || {};
        const environment = {
            worldBounds: worldBoundsFromPlanSettings(
                normalized,
                currentBounds
            ),
            floorGridSpacing: normalized.gridSpacingMeters,
            floorMajorGridSpacing: normalized.majorGridSpacingMeters,
        };
        this.options.topPlanOptions = Object.assign(
            {},
            this.options.topPlanOptions || {},
            environment
        );
        this.options.threeOptions = Object.assign(
            {},
            this.options.threeOptions || {},
            environment
        );
        [this.topAdapter, this.threeAdapter].filter(Boolean).forEach(
            function (adapter) {
                if (typeof adapter.setEnvironmentSettings === 'function') {
                    adapter.setEnvironmentSettings(environment);
                }
            }
        );
        this._renderPlanSpatialOverlays();
        this._renderProperties();
        return normalized;
    };

    Workspace.prototype._applyPlanScaleDistance = function (distanceMeters) {
        const distance = Math.max(0.01, finite(distanceMeters, 0));
        if (!this.topAdapter
                || typeof this.topAdapter.setScaleAt !== 'function'
                || !(distance > 0)) return false;
        return this.topAdapter.setScaleAt(
            this._planViewCenterEvent(),
            PLAN_SCALE_TARGET_PIXELS / distance
        );
    };

    Workspace.prototype.openPlanSettingsDialog = function (focusField) {
        if (!this.capabilities.manualAuthoring
                || this.state.busy
                || this.state.conflict
                || this.state.layoutProposal
                || this.state.placementAlternatives) return false;
        if (this.assetBrowserState.open) this.closeAssetBrowser(false);
        if (this.precisionState.open) this.closePrecisionDialog(false);
        if (this.patternState.open) this.closePatternDialog(false);
        if (this.bulkZoneState.open) this.closeBulkZoneDialog(false);
        this._closeSelectionToolbar('plan_settings_opened', false);
        this.planSettingsFocusReturn = this.document.activeElement;
        const snapshot = this.topAdapter
            && typeof this.topAdapter.getViewportState === 'function'
            ? this.topAdapter.getViewportState() : null;
        this.planSettingsState.open = true;
        this.planSettingsState.applying = false;
        this.planSettingsState.focusField = focusField || 'widthMeters';
        this.planSettingsState.draft = clone(this.planSettings);
        this.planSettingsState.scaleDistanceMeters =
            this._currentPlanScaleDistance();
        this.planSettingsState.originalScale = snapshot && snapshot.projection
            ? finite(snapshot.projection.scale, null) : null;
        this.root.setAttribute('data-plan-settings-open', 'true');
        this._renderPlanSettingsDialog();
        const first = this.planSettingsBody.querySelector(
            '[data-plan-settings-field="'
                + this.planSettingsState.focusField + '"]'
        ) || this.planSettingsBody.querySelector('[data-plan-settings-field]');
        if (first && typeof first.focus === 'function') {
            first.focus();
            if (typeof first.select === 'function') first.select();
        }
        return true;
    };

    Workspace.prototype.closePlanSettingsDialog = function (
        restoreFocus,
        preservePreview
    ) {
        if (!this.planSettingsState.open) return false;
        this._finishMovableDialogDrag(this.planSettingsDialog, true);
        if (preservePreview !== true) {
            this._applyPlanEnvironment(this.planSettings);
            if (this.planSettingsState.originalScale
                    && this.topAdapter
                    && typeof this.topAdapter.setScaleAt === 'function') {
                this.topAdapter.setScaleAt(
                    this._planViewCenterEvent(),
                    this.planSettingsState.originalScale
                );
            }
        }
        this.planSettingsState.open = false;
        this.planSettingsState.applying = false;
        this.planSettingsDialog.hidden = true;
        this.root.removeAttribute('data-plan-settings-open');
        const target = this.planSettingsFocusReturn;
        this.planSettingsFocusReturn = null;
        if (restoreFocus !== false && target
                && typeof target.focus === 'function') target.focus();
        this._syncSelectionToolbar();
        return true;
    };

    Workspace.prototype._handlePlanSettingsChange = function (event) {
        const field = targetDataId(
            event.target,
            'data-plan-settings-field',
            this.planSettingsDialog
        );
        if (!field) return;
        const displayValue = finite(event.target.value, NaN);
        if (!Number.isFinite(displayValue) || !(displayValue > 0)) return;
        const valueMeters = canonicalDistance(
            displayValue,
            this.planPreferences.unit
        );
        if (field === 'scaleDistanceMeters') {
            this.planSettingsState.scaleDistanceMeters = valueMeters;
            this._applyPlanScaleDistance(valueMeters);
            return;
        }
        const draft = Object.assign({}, this.planSettingsState.draft, {
            [field]: valueMeters,
        });
        const maximum = Math.max(
            finite(draft.widthMeters, DEFAULT_PLAN_WIDTH_METERS),
            finite(draft.depthMeters, DEFAULT_PLAN_DEPTH_METERS)
        );
        if (field === 'gridSpacingMeters') {
            const multiple = Math.max(
                1,
                Math.min(5, Math.floor(maximum / valueMeters + 1e-9))
            );
            draft.majorGridSpacingMeters = valueMeters * multiple;
        } else if (draft.majorGridSpacingMeters > maximum) {
            const multiple = Math.max(
                1,
                Math.floor(maximum / draft.gridSpacingMeters + 1e-9)
            );
            draft.majorGridSpacingMeters = draft.gridSpacingMeters * multiple;
        }
        this.planSettingsState.draft = normalizePlanSettings(
            draft,
            this.planSettings
        );
        this._applyPlanEnvironment(this.planSettingsState.draft);
        this.planSettingsStatus.textContent = 'Previewing updated facility plan.';
    };

    Workspace.prototype._handlePlanSettingsClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-plan-settings-action',
            this.planSettingsDialog
        );
        if (action === 'cancel') {
            this.closePlanSettingsDialog(true, false);
        } else if (action === 'apply') {
            this._applyPlanSettings();
        }
    };

    Workspace.prototype._handlePlanSettingsKeyDown = function (event) {
        const key = String(event && event.key || '').toLowerCase();
        if (key === 'escape') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this.closePlanSettingsDialog(true, false);
        } else if (key === 'enter') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._applyPlanSettings();
        }
    };

    Workspace.prototype._applyPlanSettings = function () {
        if (this.planSettingsState.applying) return Promise.resolve(undefined);
        const settings = normalizePlanSettings(
            this.planSettingsState.draft,
            this.planSettings
        );
        const changed = JSON.stringify(settings) !== JSON.stringify(
            this.planSettings
        );
        if (!changed) {
            this.closePlanSettingsDialog(true, true);
            return Promise.resolve(this.getState());
        }
        if (typeof this.session.setPlanSettings !== 'function') {
            const error = new Error('Facility plan settings are unavailable.');
            this._setError(error);
            return Promise.resolve(undefined);
        }
        this.planSettingsState.applying = true;
        this.planSettingsStatus.textContent = 'Applying facility plan settings...';
        return this._invoke('Resize facility plan', function () {
            return this.session.setPlanSettings(settings);
        }.bind(this)).then(function (result) {
            this.closePlanSettingsDialog(true, true);
            return result;
        }.bind(this), function (error) {
            this.planSettingsState.applying = false;
            this.planSettingsStatus.textContent = error && error.message
                ? error.message : String(error);
            return undefined;
        }.bind(this));
    };

    Workspace.prototype._layoutContentCount = function () {
        const layout = this.state && this.state.layout || {};
        return [
            'placements', 'zones', 'floorMarkings', 'routes',
            'utilityNetworks', 'processBindings',
        ].reduce(function (total, key) {
            return total + (Array.isArray(layout[key]) ? layout[key].length : 0);
        }, 0);
    };

    Workspace.prototype.openClearAllDialog = function () {
        if (!this.capabilities.manualAuthoring
                || typeof this.session.clearLayout !== 'function'
                || this.state.busy
                || this.state.conflict
                || this.state.layoutProposal
                || this.state.placementAlternatives
                || this._layoutContentCount() === 0) return false;
        if (this.assetBrowserState.open) this.closeAssetBrowser(false);
        if (this.precisionState.open) this.closePrecisionDialog(false);
        if (this.patternState.open) this.closePatternDialog(false);
        if (this.planSettingsState.open) {
            this.closePlanSettingsDialog(false, false);
        }
        this._closeSelectionToolbar('clear_all_opened', false);
        this.clearAllState.focusReturn = this.document.activeElement;
        this.clearAllState.open = true;
        this.clearAllState.applying = false;
        this.clearAllStatus.textContent = '';
        this.clearAllDialog.hidden = false;
        this.root.setAttribute('data-clear-all-open', 'true');
        this._renderToolbarState();
        const cancel = this.clearAllDialog.querySelector(
            '[data-clear-all-action="cancel"]'
        );
        if (cancel && typeof cancel.focus === 'function') cancel.focus();
        return true;
    };

    Workspace.prototype.closeClearAllDialog = function (restoreFocus) {
        if (!this.clearAllState.open) return false;
        this._finishMovableDialogDrag(this.clearAllDialog, true);
        this.clearAllState.open = false;
        this.clearAllState.applying = false;
        this.clearAllDialog.hidden = true;
        this.root.removeAttribute('data-clear-all-open');
        const target = this.clearAllState.focusReturn;
        this.clearAllState.focusReturn = null;
        this._renderToolbarState();
        if (restoreFocus !== false && target
                && typeof target.focus === 'function') target.focus();
        return true;
    };

    Workspace.prototype._handleClearAllClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-clear-all-action',
            this.clearAllDialog
        );
        if (action === 'cancel') this.closeClearAllDialog(true);
        else if (action === 'apply') this._applyClearAll();
    };

    Workspace.prototype._handleClearAllKeyDown = function (event) {
        const key = String(event && event.key || '').toLowerCase();
        if (key === 'escape') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this.closeClearAllDialog(true);
        }
    };

    Workspace.prototype._applyClearAll = function () {
        if (this.clearAllState.applying) return Promise.resolve(undefined);
        this.clearAllState.applying = true;
        this.clearAllStatus.textContent = 'Clearing facility layout...';
        return this._invoke('Clear facility layout', function () {
            return this.session.clearLayout();
        }.bind(this)).then(function (result) {
            this.closeClearAllDialog(true);
            return result;
        }.bind(this), function (error) {
            this.clearAllState.applying = false;
            this.clearAllStatus.textContent = error && error.message
                ? error.message : String(error);
            return undefined;
        }.bind(this));
    };

    Workspace.prototype._renderBulkZoneDialog = function () {
        if (!this.bulkZoneDialog) return;
        this.bulkZoneDialog.hidden = !this.bulkZoneState.open;
        if (!this.bulkZoneState.open) return;
        const unit = this.planPreferences.unit;
        clearElement(this.bulkZoneBody);
        const table = element(this.document, 'table', {
            className: 'ip-flw-bulk-zone-table',
        });
        const head = element(this.document, 'thead');
        const headRow = element(this.document, 'tr');
        [
            'Name', 'Type', 'Min X (' + unit + ')', 'Min Z (' + unit + ')',
            'Width (' + unit + ')', 'Depth (' + unit + ')', 'Color', '',
        ].forEach(function (label) {
            headRow.appendChild(element(this.document, 'th', {
                scope: 'col',
            }, label));
        }, this);
        head.appendChild(headRow);
        const body = element(this.document, 'tbody');
        this.bulkZoneState.rows.forEach(function (row) {
            const tr = element(this.document, 'tr', {
                'data-bulk-zone-row': row.rowId,
            });
            const textCell = element(this.document, 'td');
            textCell.appendChild(element(this.document, 'input', {
                type: 'text',
                maxlength: '120',
                value: row.label,
                'data-bulk-zone-field': 'label',
                'aria-label': 'Zone name',
            }));
            tr.appendChild(textCell);
            const typeCell = element(this.document, 'td');
            const typeSelect = element(this.document, 'select', {
                'data-bulk-zone-field': 'zoneType',
                'aria-label': 'Zone type',
            });
            [
                ['workcell', 'Workcell'],
                ['storage', 'Storage'],
                ['staging', 'Staging'],
                ['receiving', 'Receiving'],
                ['shipping', 'Shipping'],
                ['inspection', 'Inspection'],
                ['service', 'Service'],
                ['safety', 'Safety'],
                ['exclusion', 'Exclusion'],
            ].forEach(function (option) {
                typeSelect.appendChild(element(this.document, 'option', {
                    value: option[0],
                }, option[1]));
            }, this);
            typeSelect.value = row.zoneType;
            typeCell.appendChild(typeSelect);
            tr.appendChild(typeCell);
            ['minX', 'minZ', 'width', 'depth'].forEach(function (field) {
                const cell = element(this.document, 'td');
                cell.appendChild(element(this.document, 'input', {
                    type: 'number',
                    step: unit === 'ft' ? '0.1' : '0.05',
                    min: field === 'width' || field === 'depth' ? '0.01' : '',
                    value: String(Number(displayDistance(row[field], unit)
                        .toFixed(3))),
                    'data-bulk-zone-field': field,
                    'aria-label': 'Zone ' + field,
                }));
                tr.appendChild(cell);
            }, this);
            const colorCell = element(this.document, 'td');
            colorCell.appendChild(element(this.document, 'input', {
                type: 'color',
                value: row.color,
                'data-bulk-zone-field': 'color',
                'aria-label': 'Zone color',
            }));
            tr.appendChild(colorCell);
            const removeCell = element(this.document, 'td');
            removeCell.appendChild(element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-bulk-zone-remove',
                'data-bulk-zone-action': 'remove-row',
                'data-bulk-zone-row-id': row.rowId,
                'aria-label': 'Remove ' + row.label,
                title: 'Remove zone row',
            }, 'X'));
            tr.appendChild(removeCell);
            body.appendChild(tr);
        }, this);
        append(table, head, body);
        this.bulkZoneBody.appendChild(table);
        this.bulkZoneBody.appendChild(element(this.document, 'p', {
            className: 'ip-flw-precision-selection',
        }, 'Coordinates use the lower-left corner. All zones are created in '
            + 'one undoable transaction.'));
        this.bulkZoneStatus.textContent = this.bulkZoneState.rows.length
            + (this.bulkZoneState.rows.length === 1 ? ' zone' : ' zones');
    };

    Workspace.prototype.openBulkZoneDialog = function () {
        if (!this.capabilities.manualAuthoring
                || typeof this.session.createZones !== 'function'
                || this.state.busy
                || this.state.conflict
                || this.state.layoutProposal
                || this.state.placementAlternatives) return false;
        if (this.assetBrowserState.open) this.closeAssetBrowser(false);
        if (this.precisionState.open) this.closePrecisionDialog(false);
        if (this.patternState.open) this.closePatternDialog(false);
        if (this.planSettingsState.open) {
            this.closePlanSettingsDialog(false, false);
        }
        if (this.clearAllState.open) this.closeClearAllDialog(false);
        this._closeSelectionToolbar('bulk_zone_opened', false);
        this.bulkZoneState.focusReturn = this.document.activeElement;
        this.bulkZoneState.open = true;
        this.bulkZoneState.applying = false;
        this.bulkZoneDialog.hidden = false;
        this.root.setAttribute('data-bulk-zone-open', 'true');
        this._renderBulkZoneDialog();
        this._renderToolbarState();
        const first = this.bulkZoneBody.querySelector('[data-bulk-zone-field]');
        if (first && typeof first.focus === 'function') first.focus();
        return true;
    };

    Workspace.prototype.closeBulkZoneDialog = function (restoreFocus) {
        if (!this.bulkZoneState.open) return false;
        this._finishMovableDialogDrag(this.bulkZoneDialog, true);
        this.bulkZoneState.open = false;
        this.bulkZoneState.applying = false;
        this.bulkZoneDialog.hidden = true;
        this.root.removeAttribute('data-bulk-zone-open');
        const target = this.bulkZoneState.focusReturn;
        this.bulkZoneState.focusReturn = null;
        this._renderToolbarState();
        if (restoreFocus !== false && target
                && typeof target.focus === 'function') target.focus();
        return true;
    };

    Workspace.prototype._addBulkZoneRow = function () {
        const previous = this.bulkZoneState.rows[
            this.bulkZoneState.rows.length - 1
        ] || { minX: 0, minZ: 0, width: 10, depth: 8 };
        const sequence = this.bulkZoneState.nextRowId;
        this.bulkZoneState.nextRowId += 1;
        this.bulkZoneState.rows.push({
            rowId: 'zone-row-' + sequence,
            label: 'Zone ' + sequence,
            zoneType: 'workcell',
            minX: previous.minX + previous.width + 2,
            minZ: previous.minZ,
            width: previous.width,
            depth: previous.depth,
            color: '#4a90c2',
        });
        this._renderBulkZoneDialog();
    };

    Workspace.prototype._handleBulkZoneChange = function (event) {
        const field = targetDataId(
            event.target,
            'data-bulk-zone-field',
            this.bulkZoneDialog
        );
        if (!field) return;
        const rowId = targetDataId(
            event.target,
            'data-bulk-zone-row',
            this.bulkZoneDialog
        );
        const row = this.bulkZoneState.rows.find(function (item) {
            return item.rowId === rowId;
        });
        if (!row) return;
        if (['minX', 'minZ', 'width', 'depth'].includes(field)) {
            const displayValue = finite(event.target.value, NaN);
            if (!Number.isFinite(displayValue)) return;
            row[field] = canonicalDistance(
                displayValue,
                this.planPreferences.unit
            );
        } else {
            row[field] = String(event.target.value || '');
        }
    };

    Workspace.prototype._handleBulkZoneClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-bulk-zone-action',
            this.bulkZoneDialog
        );
        if (!action) return;
        if (action === 'cancel') this.closeBulkZoneDialog(true);
        else if (action === 'add-row') this._addBulkZoneRow();
        else if (action === 'remove-row') {
            const rowId = event.target.getAttribute('data-bulk-zone-row-id');
            this.bulkZoneState.rows = this.bulkZoneState.rows.filter(
                function (row) { return row.rowId !== rowId; }
            );
            if (!this.bulkZoneState.rows.length) this._addBulkZoneRow();
            else this._renderBulkZoneDialog();
        } else if (action === 'apply') this._applyBulkZones();
    };

    Workspace.prototype._handleBulkZoneKeyDown = function (event) {
        const key = String(event && event.key || '').toLowerCase();
        if (key === 'escape') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this.closeBulkZoneDialog(true);
        } else if (key === 'enter' && event.ctrlKey) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._applyBulkZones();
        }
    };

    Workspace.prototype._applyBulkZones = function () {
        if (this.bulkZoneState.applying) return Promise.resolve(undefined);
        let requests;
        try {
            requests = this.bulkZoneState.rows.map(function (row, index) {
                const label = String(row.label || '').trim();
                if (!label) throw new Error('Zone ' + (index + 1)
                    + ' needs a name.');
                if (!(row.width > 0) || !(row.depth > 0)) {
                    throw new Error(label + ' needs positive width and depth.');
                }
                return {
                    label: label,
                    zoneType: row.zoneType,
                    minX: row.minX,
                    minZ: row.minZ,
                    width: row.width,
                    depth: row.depth,
                    extensions: {
                        style: {
                            fillColor: row.color,
                        },
                    },
                };
            });
        } catch (error) {
            this.bulkZoneStatus.textContent = error.message;
            return Promise.resolve(undefined);
        }
        this.bulkZoneState.applying = true;
        this.bulkZoneStatus.textContent = 'Creating zones...';
        return this._invoke('Create facility zones', function () {
            return this.session.createZones(requests);
        }.bind(this)).then(function (result) {
            this.closeBulkZoneDialog(true);
            return result;
        }.bind(this), function (error) {
            this.bulkZoneState.applying = false;
            this.bulkZoneStatus.textContent = error && error.message
                ? error.message : String(error);
            return undefined;
        }.bind(this));
    };

    Workspace.prototype._cellGroupSeed = function () {
        if (!this.patternRuntime
                || typeof this.patternRuntime.collectSelection !== 'function') {
            return [];
        }
        return this.patternRuntime.collectSelection(
            this.state.layout,
            this.assetCatalog,
            this.state.selection,
            { expandZones: true, includeZones: false }
        ).filter(function (item) {
            return item.kind === 'placement' || item.kind === 'floor-marking';
        });
    };

    Workspace.prototype._cellGroupField = function (
        label,
        field,
        type,
        value,
        options
    ) {
        const config = options || {};
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        wrapper.appendChild(element(this.document, 'input', {
            type: type || 'text',
            value: String(value),
            min: config.min === undefined ? '' : String(config.min),
            max: config.max === undefined ? '' : String(config.max),
            step: config.step === undefined ? '' : String(config.step),
            maxlength: config.maxlength === undefined
                ? '' : String(config.maxlength),
            'data-cell-group-field': field,
            'aria-label': label,
        }));
        return wrapper;
    };

    Workspace.prototype._cellGroupSelect = function (
        label,
        field,
        value
    ) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        const select = element(this.document, 'select', {
            'data-cell-group-field': field,
            'aria-label': label,
        });
        [
            ['', 'Not specified'],
            ['north', 'North'],
            ['east', 'East'],
            ['south', 'South'],
            ['west', 'West'],
        ].forEach(function (option) {
            select.appendChild(element(this.document, 'option', {
                value: option[0],
                selected: option[0] === value,
            }, option[1]));
        }, this);
        wrapper.appendChild(select);
        return wrapper;
    };

    Workspace.prototype._renderCellGroupDialog = function () {
        if (!this.cellGroupDialog) return;
        this.cellGroupDialog.hidden = !this.cellGroupState.open;
        if (!this.cellGroupState.open) return;
        const seed = this._cellGroupSeed();
        const unit = this.planPreferences.unit;
        clearElement(this.cellGroupBody);
        this.cellGroupBody.appendChild(element(this.document, 'p', {
            className: 'ip-flw-precision-selection',
        }, seed.length + (seed.length === 1 ? ' object' : ' objects')
            + ' will become one persistent manufacturing cell.'));
        append(this.cellGroupBody,
            this._cellGroupField(
                'Cell family name', 'baseName', 'text',
                this.cellGroupState.baseName, { maxlength: 80 }
            ),
            this._cellGroupField(
                'Series prefix', 'prefix', 'text',
                this.cellGroupState.prefix, { maxlength: 12 }
            ),
            this._cellGroupField(
                'Starting number', 'start', 'number',
                this.cellGroupState.start, { min: 0, max: 999999, step: 1 }
            ),
            this._cellGroupField(
                'Number digits', 'numberPadding', 'number',
                this.cellGroupState.numberPadding, { min: 1, max: 6, step: 1 }
            ),
            this._cellGroupField(
                'Envelope padding (' + unit + ')',
                'envelopePadding',
                'number',
                displayDistance(this.cellGroupState.envelopePadding, unit),
                { min: 0, max: 1000, step: unit === 'ft' ? 0.1 : 0.05 }
            ),
            this._cellGroupField(
                'Cell color', 'color', 'color', this.cellGroupState.color
            ),
            this._cellGroupSelect(
                'Gate / entrance side', 'gateSide',
                this.cellGroupState.gateSide
            ),
            this._cellGroupSelect(
                'Material loading side', 'loadingSide',
                this.cellGroupState.loadingSide
            ),
            this._cellGroupSelect(
                'Maintenance / service side', 'serviceSide',
                this.cellGroupState.serviceSide
            )
        );
        let summary = 'Select equipment or markings to create a cell.';
        if (seed.length && this.patternRuntime
                && typeof this.patternRuntime.selectionBounds === 'function') {
            const bounds = this.patternRuntime.selectionBounds(seed);
            summary = formattedDistance(displayDistance(bounds.width, unit))
                + ' x ' + formattedDistance(displayDistance(bounds.depth, unit))
                + ' ' + unit + ' before padding.';
        }
        this.cellGroupStatus.textContent = summary;
        const apply = this.cellGroupDialog.querySelector(
            '[data-cell-group-action="apply"]'
        );
        if (apply) apply.disabled = seed.length < 1;
    };

    Workspace.prototype.openCellGroupDialog = function () {
        if (!this.capabilities.manualAuthoring
                || typeof this.session.createCellGroup !== 'function'
                || this.state.busy
                || this.state.conflict
                || this.state.layoutProposal
                || this.state.placementAlternatives
                || this._cellGroupSeed().length < 1) return false;
        if (this.assetBrowserState.open) this.closeAssetBrowser(false);
        if (this.precisionState.open) this.closePrecisionDialog(false);
        if (this.patternState.open) this.closePatternDialog(false);
        if (this.bulkZoneState.open) this.closeBulkZoneDialog(false);
        this._closeSelectionToolbar('cell_group_opened', false);
        this.cellGroupState.focusReturn = this.document.activeElement;
        this.cellGroupState.open = true;
        this.cellGroupState.applying = false;
        this.cellGroupDialog.hidden = false;
        this.root.setAttribute('data-cell-group-open', 'true');
        this._renderCellGroupDialog();
        this._renderToolbarState();
        const first = this.cellGroupBody.querySelector('[data-cell-group-field]');
        if (first && typeof first.focus === 'function') first.focus();
        return true;
    };

    Workspace.prototype.closeCellGroupDialog = function (restoreFocus) {
        if (!this.cellGroupState.open) return false;
        this._finishMovableDialogDrag(this.cellGroupDialog, true);
        this.cellGroupState.open = false;
        this.cellGroupState.applying = false;
        this.cellGroupDialog.hidden = true;
        this.root.removeAttribute('data-cell-group-open');
        const target = this.cellGroupState.focusReturn;
        this.cellGroupState.focusReturn = null;
        this._renderToolbarState();
        if (restoreFocus !== false && target
                && typeof target.focus === 'function') target.focus();
        return true;
    };

    Workspace.prototype._handleCellGroupChange = function (event) {
        const field = targetDataId(
            event.target,
            'data-cell-group-field',
            this.cellGroupDialog
        );
        if (!field) return;
        if (['start', 'numberPadding'].includes(field)) {
            this.cellGroupState[field] = Math.round(finite(
                event.target.value,
                this.cellGroupState[field]
            ));
        } else if (field === 'envelopePadding') {
            this.cellGroupState[field] = Math.max(0, canonicalDistance(
                finite(event.target.value, 0),
                this.planPreferences.unit
            ));
        } else {
            this.cellGroupState[field] = String(event.target.value || '');
        }
    };

    Workspace.prototype._handleCellGroupClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-cell-group-action',
            this.cellGroupDialog
        );
        if (action === 'cancel') this.closeCellGroupDialog(true);
        else if (action === 'apply') this._applyCellGroup();
    };

    Workspace.prototype._handleCellGroupKeyDown = function (event) {
        const key = String(event && event.key || '').toLowerCase();
        if (key === 'escape') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this.closeCellGroupDialog(true);
        } else if (key === 'enter' && event.ctrlKey) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._applyCellGroup();
        }
    };

    Workspace.prototype._applyCellGroup = function () {
        if (this.cellGroupState.applying) return Promise.resolve(undefined);
        const seed = this._cellGroupSeed();
        if (!seed.length) return Promise.resolve(undefined);
        const bounds = this.patternRuntime.selectionBounds(seed);
        const padding = Math.max(0, this.cellGroupState.envelopePadding);
        const baseName = String(this.cellGroupState.baseName || '').trim();
        if (!baseName) {
            this.cellGroupStatus.textContent = 'Cell family name is required.';
            return Promise.resolve(undefined);
        }
        this.cellGroupSequence += 1;
        const seriesId = 'cell-series-'
            + Date.now().toString(36) + '-'
            + this.cellGroupSequence.toString(36);
        const request = {
            baseName: baseName,
            prefix: String(this.cellGroupState.prefix || '').trim(),
            start: Math.max(0, Math.round(this.cellGroupState.start)),
            numberPadding: Math.max(
                1,
                Math.min(6, Math.round(this.cellGroupState.numberPadding))
            ),
            envelopePadding: padding,
            minX: bounds.minX - padding,
            minZ: bounds.minZ - padding,
            width: Math.max(0.01, bounds.width + 2 * padding),
            depth: Math.max(0.01, bounds.depth + 2 * padding),
            seriesId: seriesId,
            functionalInterfaces: {
                gate: this.cellGroupState.gateSide,
                loading: this.cellGroupState.loadingSide,
                service: this.cellGroupState.serviceSide,
            },
            extensions: {
                style: { fillColor: this.cellGroupState.color },
            },
        };
        this.cellGroupState.applying = true;
        this.cellGroupStatus.textContent = 'Creating manufacturing cell...';
        return this._invoke('Create manufacturing cell', function () {
            return this.session.createCellGroup(request);
        }.bind(this)).then(function (result) {
            this.closeCellGroupDialog(true);
            return result;
        }.bind(this), function (error) {
            this.cellGroupState.applying = false;
            this.cellGroupStatus.textContent = error && error.message
                ? error.message : String(error);
            return undefined;
        }.bind(this));
    };

    Workspace.prototype._ungroupSelectedCell = function () {
        const zone = this._selectedZoneRecord();
        const metadata = zone && zone.extensions && zone.extensions.cellGroup;
        if (!zone || !metadata
                || metadata.groupKind !== 'manufacturing_cell'
                || typeof this.session.ungroupCell !== 'function') {
            return Promise.resolve(this.getState());
        }
        return this._invoke('Ungroup manufacturing cell', function () {
            return this.session.ungroupCell(zone.zoneId);
        }.bind(this));
    };

    Workspace.prototype._aisleField = function (label, field, type, value) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        wrapper.appendChild(element(this.document, 'input', {
            type: type || 'text',
            value: String(value),
            min: type === 'number' ? '0.01' : '',
            step: type === 'number' ? '0.1' : '',
            maxlength: type === 'text' ? '120' : '',
            'data-aisle-field': field,
            'aria-label': label,
        }));
        return wrapper;
    };

    Workspace.prototype._aisleSelect = function (label, field, options, value) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-precision-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        const select = element(this.document, 'select', {
            'data-aisle-field': field,
            'aria-label': label,
        });
        options.forEach(function (option) {
            select.appendChild(element(this.document, 'option', {
                value: option[0],
                selected: option[0] === value,
            }, option[1]));
        }, this);
        wrapper.appendChild(select);
        return wrapper;
    };

    Workspace.prototype._renderAisleDialog = function () {
        if (!this.aisleDialog) return;
        this.aisleDialog.hidden = !this.aisleState.open;
        if (!this.aisleState.open) return;
        const unit = this.planPreferences.unit;
        clearElement(this.aisleBody);
        append(
            this.aisleBody,
            this._aisleField('Aisle name', 'label', 'text', this.aisleState.label),
            this._aisleSelect('Use', 'aisleKind', [
                ['forklift', 'Forklift'],
                ['pedestrian', 'Pedestrian'],
                ['material', 'Material flow'],
            ], this.aisleState.aisleKind),
            this._aisleSelect('Direction', 'direction', [
                ['two_way', 'Two way'],
                ['one_way', 'One way'],
            ], this.aisleState.direction),
            this._aisleField(
                'Corridor width (' + unit + ')',
                'corridorWidth',
                'number',
                displayDistance(this.aisleState.corridorWidth, unit)
            ),
            this._aisleField('Display color', 'color', 'color', this.aisleState.color),
            element(this.document, 'p', {
                className: 'ip-flw-property-note',
            }, 'The corridor is planning geometry. Safety clearance remains '
                + 'unverified until authoritative evidence is attached.')
        );
        this.aisleStatus.textContent = this.aisleState.drawing
            ? 'Drag from the aisle start to its end on the plan.'
            : 'Set the aisle properties, then choose Draw aisle.';
        const draw = this.aisleDialog.querySelector('[data-aisle-action="draw"]');
        if (draw) draw.textContent = this.aisleState.drawing
            ? 'Drawing active' : 'Draw aisle';
    };

    Workspace.prototype.openAisleDialog = function () {
        if (!this.capabilities.manualAuthoring
                || typeof this.session.createAisle !== 'function'
                || this.state.busy || this.state.conflict) return false;
        if (this.assetBrowserState.open) this.closeAssetBrowser(false);
        if (this.precisionState.open) this.closePrecisionDialog(false);
        if (this.patternState.open) this.closePatternDialog(false);
        if (this.bulkZoneState.open) this.closeBulkZoneDialog(false);
        if (this.cellGroupState.open) this.closeCellGroupDialog(false);
        this._closeSelectionToolbar('aisle_opened', false);
        this.aisleState.focusReturn = this.document.activeElement;
        this.aisleState.open = true;
        this.aisleDialog.hidden = false;
        this.root.setAttribute('data-aisle-open', 'true');
        this._renderAisleDialog();
        this._renderToolbarState();
        const first = this.aisleBody.querySelector('[data-aisle-field]');
        if (first && typeof first.focus === 'function') first.focus();
        return true;
    };

    Workspace.prototype.closeAisleDialog = function (restoreFocus) {
        if (!this.aisleState.open) return false;
        this._finishMovableDialogDrag(this.aisleDialog, true);
        this.aisleState.open = false;
        this.aisleState.drawing = false;
        this.aisleDialog.hidden = true;
        this.root.removeAttribute('data-aisle-open');
        this._setAislePreview(null);
        if (this.toolMode === 'aisle') this._setToolMode('select');
        const target = this.aisleState.focusReturn;
        this.aisleState.focusReturn = null;
        this._renderToolbarState();
        if (restoreFocus !== false && target
                && typeof target.focus === 'function') target.focus();
        return true;
    };

    Workspace.prototype._handleAisleChange = function (event) {
        const field = targetDataId(
            event.target,
            'data-aisle-field',
            this.aisleDialog
        );
        if (!field) return;
        if (field === 'corridorWidth') {
            const value = canonicalDistance(
                finite(event.target.value, NaN),
                this.planPreferences.unit
            );
            if (value > 0) this.aisleState.corridorWidth = value;
        } else {
            this.aisleState[field] = String(event.target.value || '');
        }
    };

    Workspace.prototype._handleAisleClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-aisle-action',
            this.aisleDialog
        );
        if (action === 'close') this.closeAisleDialog(true);
        else if (action === 'draw') {
            const label = String(this.aisleState.label || '').trim();
            if (!label) {
                this.aisleStatus.textContent = 'Aisle name is required.';
                return;
            }
            this.aisleState.label = label;
            this.aisleState.drawing = true;
            this._setToolMode('aisle');
            this._renderAisleDialog();
        }
    };

    Workspace.prototype._handleAisleKeyDown = function (event) {
        if (String(event && event.key || '').toLowerCase() !== 'escape') return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        this.closeAisleDialog(true);
    };

    Workspace.prototype._navigationSelectedActor = function () {
        if (!this.state || !this.state.layout) return null;
        const selected = new Set(this.state.selection || []);
        const placements = (this.state.layout.placements || []).filter(
            function (placement) {
                return selected.has(placement.placementId);
            }
        );
        if (placements.length !== 1) return null;
        try {
            const actorClass = this.navigationRuntime.detectActorClass(
                placements[0]
            );
            return { placement: placements[0], actorClass: actorClass };
        } catch (error) {
            return null;
        }
    };

    Workspace.prototype._navigationVisualForwardAxis = function () {
        const placement = this._navigationActorRecord();
        const catalog = placement ? catalogRecord(
            this.assetCatalog,
            placement.assetId,
            placement.assetDefinitionRevision
        ) : null;
        const axis = placement && placement.metadata
            && placement.metadata.visualForwardAxis
            || catalog && catalog.visualAlignment
                && catalog.visualAlignment.forwardAxis
            || catalog && catalog.extensions
                && catalog.extensions.visualAlignment
                && catalog.extensions.visualAlignment.forwardAxis
            || '+X';
        return ['+X', '-X', '+Z', '-Z'].includes(axis) ? axis : '+X';
    };

    Workspace.prototype._navigationPreviewDescriptor = function () {
        const navigation = this.navigationState;
        let pose = null;
        if (navigation.points.length >= 2) {
            try {
                pose = this.navigationRuntime.samplePathAtNormalizedTime(
                    navigation.points,
                    navigation.previewNormalizedTime
                );
            } catch (error) {
                pose = null;
            }
        }
        return {
            actorPlacementId: navigation.actorPlacementId,
            actorClass: navigation.actorClass,
            points: clone(navigation.points),
            selectedPointIndex: navigation.selectedPointIndex,
            selectedSegmentIndex: navigation.selectedSegmentIndex,
            lockedSegmentIndexes: navigation.lockedSegmentIndexes.slice(),
            validationStatus: navigation.validationStatus,
            validation: navigation.validation
                ? clone(navigation.validation) : null,
            pathsVisible: navigation.pathsVisible !== false,
            pose: pose,
        };
    };

    Workspace.prototype._syncNavigationAuthoringPreview = function () {
        if (this.topAdapter) {
            if (typeof this.topAdapter.setNavigationPathsVisible === 'function') {
                this.topAdapter.setNavigationPathsVisible(
                    this.navigationState.pathsVisible
                );
            }
            if (typeof this.topAdapter.setNavigationAuthoringPreview
                    === 'function') {
                this.topAdapter.setNavigationAuthoringPreview(
                    this.navigationState.open
                        ? this._navigationPreviewDescriptor() : null
                );
            }
        }
        if (this.threeAdapter && this.threeAdapter.navigationPreview
                && this.navigationState.previewLoaded) {
            const preview = this.threeAdapter.navigationPreview;
            if (typeof preview.setPathsVisible === 'function') {
                preview.setPathsVisible(this.navigationState.pathsVisible);
            }
            if (typeof preview.updatePath === 'function') {
                preview.updatePath({
                    points: clone(this.navigationState.points),
                    loopMode: this.navigationState.loopMode,
                    direction: this.navigationState.direction,
                    validationStatus: this.navigationState.validationStatus,
                });
            }
            if (typeof preview.seek === 'function') {
                preview.seek(this.navigationState.previewNormalizedTime);
            }
        }
    };

    Workspace.prototype.openNavigationDialog = function () {
        if (!this.capabilities.manualAuthoring
                || !this.navigationRuntime
                || typeof this.navigationRuntime.buildManualPathIntent
                    !== 'function'
                || typeof this.session.setFacilityNavigation !== 'function'
                || this.state.busy || this.state.conflict) return false;
        const selected = this._navigationSelectedActor();
        if (!selected) {
            this._setError(new Error(
                'Select exactly one existing operator or vehicle before authoring a motion path.'
            ));
            return false;
        }
        if (this.assetBrowserState.open) this.closeAssetBrowser(false);
        if (this.precisionState.open) this.closePrecisionDialog(false);
        if (this.patternState.open) this.closePatternDialog(false);
        if (this.bulkZoneState.open) this.closeBulkZoneDialog(false);
        if (this.cellGroupState.open) this.closeCellGroupDialog(false);
        if (this.aisleState.open) this.closeAisleDialog(false);
        this._closeSelectionToolbar('navigation_opened', false);
        const placement = selected.placement;
        const navigation = this.navigationRuntime.navigationFromLayout(
            this.state.layout
        );
        const existingProgram = navigation.movementPrograms.find(
            function (program) {
                return program.actorPlacementId === placement.placementId;
            }
        );
        const existingConstraint = existingProgram
            ? navigation.manualPathConstraints.find(function (constraint) {
                return (existingProgram.manualPathConstraintIds || [])
                    .includes(constraint.manualPathConstraintId);
            }) : null;
        const embeddedProfile = placement.metadata
            && placement.metadata.navigationProfileRef || null;
        this.navigationState.focusReturn = this.document.activeElement;
        this.navigationState.open = true;
        this.navigationState.drawing = !existingConstraint;
        this.navigationState.anchorPicking = false;
        this.navigationState.applying = false;
        this.navigationState.actorPlacementId = placement.placementId;
        this.navigationState.actorClass = selected.actorClass;
        this.navigationState.actorProfileId = existingProgram
            && existingProgram.actorProfileRef.profileId
            || embeddedProfile && (embeddedProfile.profileId
                || embeddedProfile.vehicleProfileId) || '';
        this.navigationState.actorProfileRevision = existingProgram
            && existingProgram.actorProfileRef.profileRevision
            || embeddedProfile && (embeddedProfile.profileRevision
                || embeddedProfile.vehicleProfileRevision) || '';
        this.navigationState.loopMode = existingProgram
            && existingProgram.loopMode || 'closed_loop';
        this.navigationState.direction = existingConstraint
            && existingConstraint.direction || 'forward';
        this.navigationState.constraintMode = existingConstraint
            && existingConstraint.constraintMode || 'complete_override';
        this.navigationState.points = existingConstraint
            ? clone(existingConstraint.authoredPolyline)
            : [{
                x: finite(placement.transform
                    && placement.transform.position
                    && placement.transform.position.x, 0),
                z: finite(placement.transform
                    && placement.transform.position
                    && placement.transform.position.z, 0),
            }];
        this.navigationState.snapRefs = existingConstraint
            ? clone(existingConstraint.snapRefs || []) : [];
        this.navigationState.lockedSegmentIndexes = existingConstraint
            ? (existingConstraint.lockedSegmentIndexes || []).slice() : [];
        this.navigationState.selectedPointIndex = 0;
        this.navigationState.selectedSegmentIndex = 0;
        this.navigationState.previewNormalizedTime = 0;
        this.navigationState.validationStatus = existingConstraint
            && existingConstraint.reviewStatus === 'confirmed'
            ? 'validated' : existingConstraint
                && existingConstraint.reviewStatus === 'rejected'
                ? 'invalid' : 'pending';
        this.navigationState.validation = null;
        this.navigationState.anchorOwnerPlacementId = placement.placementId;
        this.navigationState.message = existingConstraint
            ? 'Existing UI-authored path loaded for editing.'
            : 'Click the Plan to add the first path segment.';
        this.navigationState.lastConstraintId = existingConstraint
            && existingConstraint.manualPathConstraintId || null;
        this.navigationDialog.hidden = false;
        this.root.setAttribute('data-navigation-open', 'true');
        this._setToolMode('motion-path');
        this._renderNavigationDialog();
        this._syncNavigationAuthoringPreview();
        return true;
    };

    Workspace.prototype.closeNavigationDialog = function (restoreFocus) {
        if (!this.navigationState.open) return false;
        this._finishMovableDialogDrag(this.navigationDialog, true);
        this.navigationState.open = false;
        this.navigationState.drawing = false;
        this.navigationState.anchorPicking = false;
        this.navigationState.previewPlaying = false;
        this.navigationDialog.hidden = true;
        this.root.removeAttribute('data-navigation-open');
        if (this.threeAdapter && this.threeAdapter.navigationPreview
                && typeof this.threeAdapter.navigationPreview.dispose
                    === 'function') {
            this.threeAdapter.navigationPreview.dispose('authoring_closed');
        }
        this.navigationState.previewLoaded = false;
        if (this.topAdapter
                && typeof this.topAdapter.setNavigationAuthoringPreview
                    === 'function') {
            this.topAdapter.setNavigationAuthoringPreview(null);
        }
        if (this.toolMode === 'motion-path') this._setToolMode('select');
        const target = this.navigationState.focusReturn;
        this.navigationState.focusReturn = null;
        this._renderToolbarState();
        if (restoreFocus !== false && target
                && typeof target.focus === 'function') target.focus();
        return true;
    };

    Workspace.prototype._navigationSnapPoint = function (world) {
        const candidates = [];
        const layout = this.state.layout || {};
        (layout.routes || []).forEach(function (route) {
            (route.points || []).forEach(function (value, index) {
                candidates.push({
                    point: { x: value.x, z: value.z },
                    refKind: 'route_point',
                    refId: route.routeId + ':' + index,
                });
            });
        });
        (layout.floorMarkings || []).forEach(function (marking) {
            const position = marking.transform && marking.transform.position;
            if (position) candidates.push({
                point: { x: position.x, z: position.z },
                refKind: 'marking_center',
                refId: marking.markingId,
            });
        });
        const existing = this.navigationRuntime.navigationFromLayout(layout);
        (existing.anchors || []).forEach(function (anchor) {
            if (anchor.localPosition) candidates.push({
                point: clone(anchor.localPosition),
                refKind: 'navigation_anchor',
                refId: anchor.navigationAnchorId,
            });
        });
        const threshold = Math.max(0.25, this._activeSnapStep() * 0.75);
        let best = null;
        candidates.forEach(function (candidate) {
            const distance = Math.hypot(
                candidate.point.x - world.x,
                candidate.point.z - world.z
            );
            if (distance <= threshold && (!best || distance < best.distance)) {
                best = Object.assign({ distance: distance }, candidate);
            }
        });
        return best || {
            point: { x: world.x, z: world.z },
            refKind: null,
            refId: null,
        };
    };

    Workspace.prototype._navigationAddPoint = function (world) {
        const snapped = this._navigationSnapPoint(world);
        const point = {
            x: Number(Number(snapped.point.x).toFixed(6)),
            z: Number(Number(snapped.point.z).toFixed(6)),
        };
        const points = this.navigationState.points;
        if (points.length && this.navigationRuntime.samePoint(
            points[points.length - 1], point
        )) return false;
        points.push(point);
        const index = points.length - 1;
        if (snapped.refKind) {
            this.navigationState.snapRefs = this.navigationState.snapRefs
                .filter(function (item) { return item.pointIndex !== index; });
            this.navigationState.snapRefs.push({
                pointIndex: index,
                refKind: snapped.refKind,
                refId: snapped.refId,
            });
        }
        this.navigationState.selectedPointIndex = index;
        this.navigationState.selectedSegmentIndex = Math.max(0, index - 1);
        this.navigationState.validationStatus = 'pending';
        this.navigationState.validation = null;
        this.navigationState.message = snapped.refKind
            ? 'Waypoint snapped to ' + snapped.refKind.replace('_', ' ') + '.'
            : 'Waypoint authored from the Plan pointer.';
        this._syncNavigationAuthoringPreview();
        this._renderNavigationDialog();
        return true;
    };

    Workspace.prototype._loadNavigationPreview = async function () {
        if (!this.threeAdapter || !this.threeAdapter.navigationPreview
                || typeof this.threeAdapter.navigationPreview.load
                    !== 'function') {
            throw new Error('The exact-actor 3D navigation preview is unavailable.');
        }
        const placement = this._navigationActorRecord();
        const payload = {
            previewId: this.navigationRuntime.stableId('nav-preview', {
                actorPlacementId: placement.placementId,
                sequence: this.navigationState.sequence,
            }),
            layoutRevision: this.state.baseRevision,
            actorPlacementId: placement.placementId,
            actorClass: this.navigationState.actorClass,
            points: clone(this.navigationState.points),
            loopMode: this.navigationState.loopMode,
            direction: this.navigationState.direction,
            visualForwardAxis: this._navigationVisualForwardAxis(),
            validationStatus: this.navigationState.validationStatus,
            pathsVisible: this.navigationState.pathsVisible,
        };
        await this.threeAdapter.navigationPreview.load(
            payload,
            this.state.baseRevision
        );
        this.navigationState.previewLoaded = true;
        this.threeAdapter.navigationPreview.seek(
            this.navigationState.previewNormalizedTime
        );
        return payload;
    };

    Workspace.prototype._applyNavigationPath = function () {
        const navigation = this.navigationState;
        let built;
        try {
            const existingNavigation = this.navigationRuntime
                .navigationFromLayout(this.state.layout);
            const existingConstraint = navigation.lastConstraintId
                ? existingNavigation.manualPathConstraints.find(
                    function (constraint) {
                        return constraint.manualPathConstraintId
                            === navigation.lastConstraintId;
                    }
                ) : null;
            built = this.navigationRuntime.buildManualPathIntent(
                this.state.layout,
                {
                    actorPlacementId: navigation.actorPlacementId,
                    actorClass: navigation.actorClass,
                    actorProfileRef: navigation.actorClass === 'vehicle'
                        ? {
                            profileKind: 'vehicle',
                            profileId: navigation.actorProfileId,
                            profileRevision: navigation.actorProfileRevision,
                        } : null,
                    points: clone(navigation.points),
                    loopMode: navigation.loopMode,
                    direction: navigation.direction,
                    constraintMode: navigation.constraintMode,
                    baseRevision: this.state.baseRevision,
                    sequence: navigation.sequence,
                    snapRefs: clone(navigation.snapRefs),
                    lockedSegmentIndexes:
                        navigation.lockedSegmentIndexes.slice(),
                    movementProgramId: existingConstraint
                        ? existingConstraint.movementProgramId : undefined,
                    manualPathConstraintId:
                        navigation.lastConstraintId || undefined,
                }
            );
        } catch (error) {
            navigation.message = error.message;
            this._renderNavigationDialog();
            return Promise.resolve(false);
        }
        navigation.applying = true;
        navigation.message = navigation.constraintMode === 'complete_override'
            ? 'Validating exact actor geometry...'
            : 'Applying one unsaved navigation gesture...';
        this._renderNavigationDialog();
        const validation = navigation.constraintMode === 'complete_override'
            ? Promise.resolve().then(function () {
                if (!this.motionTransport
                        || typeof this.motionTransport
                            .validateManualNavigationPath !== 'function') {
                    throw new Error(
                        'Deterministic manual-path validation is unavailable.'
                    );
                }
                return this.motionTransport.validateManualNavigationPath({
                    baseRevision: this.state.baseRevision,
                    operations: clone(this.state.operations || []),
                    request: {
                        actorPlacementId: navigation.actorPlacementId,
                        actorClass: navigation.actorClass,
                        actorProfileRef: clone(built.actorProfileRef),
                        constraintMode: navigation.constraintMode,
                        direction: navigation.direction,
                        points: clone(built.points),
                        prototypeMode: this.capabilities.prototypeMotion === true,
                    },
                });
            }.bind(this)) : Promise.resolve(null);
        return validation.then(function (result) {
            if (result) {
                navigation.validation = clone(result);
                navigation.validationStatus = result.valid
                    ? 'validated' : 'invalid';
                this._syncNavigationAuthoringPreview();
                if (!result.valid) {
                    const first = Array.isArray(result.findings)
                        ? result.findings[0] : null;
                    navigation.applying = false;
                    navigation.message = first && first.message
                        ? first.message
                        : 'The path intersects trusted geometry.';
                    this._renderNavigationDialog();
                    return false;
                }
                navigation.message = (
                    'Geometry validated. Applying one unsaved navigation gesture...'
                );
                this._renderNavigationDialog();
            }
            return this._invoke('Author motion path', function () {
                return this.session.setFacilityNavigation(
                    built.facilityNavigation
                );
            }.bind(this));
        }.bind(this)).then(function (result) {
            if (result === false) return false;
            navigation.applying = false;
            navigation.drawing = false;
            navigation.lastConstraintId = built.manualPathConstraintId;
            navigation.sequence += 1;
            navigation.message = (
                'Path is an unsaved pending constraint. Save remains a separate '
                + 'explicit approval.'
            );
            this._renderNavigationDialog();
            this._syncNavigationAuthoringPreview();
            return true;
        }.bind(this)).catch(function (error) {
            navigation.applying = false;
            navigation.message = error.message;
            this._renderNavigationDialog();
            return false;
        }.bind(this));
    };

    Workspace.prototype._placeNavigationAnchor = function (world) {
        let built;
        try {
            built = this.navigationRuntime.addNavigationAnchor(
                this.state.layout,
                {
                    ownerPlacementId:
                        this.navigationState.anchorOwnerPlacementId,
                    actorClass: this.navigationState.actorClass,
                    anchorKind: this.navigationState.anchorKind,
                    position: world,
                    sequence: this.navigationState.sequence,
                }
            );
        } catch (error) {
            this.navigationState.message = error.message;
            this._renderNavigationDialog();
            return Promise.resolve(false);
        }
        this.navigationState.anchorPicking = false;
        return this._invoke('Author navigation anchor', function () {
            return this.session.setFacilityNavigation(
                built.facilityNavigation
            );
        }.bind(this)).then(function () {
            this.navigationState.sequence += 1;
            this.navigationState.message = 'Semantic anchor added as one unsaved gesture.';
            this._setToolMode('motion-path');
            this._renderNavigationDialog();
            return true;
        }.bind(this));
    };

    Workspace.prototype._exportNavigationGold = function () {
        const artifact = this.navigationRuntime.goldArtifact(
            this.state.layout,
            this.navigationState.lastConstraintId,
            this.navigationState.validation
        );
        if (typeof this.options.onNavigationGoldExport === 'function') {
            this.options.onNavigationGoldExport(clone(artifact));
            return artifact;
        }
        if (root && typeof root.Blob === 'function'
                && root.URL && typeof root.URL.createObjectURL === 'function') {
            const url = root.URL.createObjectURL(new root.Blob([
                JSON.stringify(artifact, null, 2),
            ], { type: 'application/json' }));
            const link = this.document.createElement('a');
            link.href = url;
            link.download = this.navigationState.lastConstraintId + '.json';
            link.click();
            root.URL.revokeObjectURL(url);
        }
        return artifact;
    };

    Workspace.prototype._handleNavigationChange = function (event) {
        const field = targetDataId(
            event.target,
            'data-navigation-field',
            this.navigationDialog
        );
        if (!field) return;
        if (field === 'previewNormalizedTime') {
            this.navigationState.previewNormalizedTime = Math.min(
                1,
                Math.max(0, finite(event.target.value, 0))
            );
            this._syncNavigationAuthoringPreview();
            return;
        }
        this.navigationState[field] = String(event.target.value || '');
        this.navigationState.validationStatus = 'pending';
        this.navigationState.validation = null;
        this._syncNavigationAuthoringPreview();
        this._renderNavigationDialog();
    };

    Workspace.prototype._handleNavigationClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-navigation-action',
            this.navigationDialog
        );
        if (!action) return;
        const navigation = this.navigationState;
        if (action === 'close') this.closeNavigationDialog(true);
        else if (action === 'draw') {
            navigation.drawing = true;
            navigation.anchorPicking = false;
            this._setToolMode('motion-path');
            navigation.message = 'Click the Plan to add waypoints.';
        } else if (action === 'finish') {
            navigation.drawing = false;
            navigation.message = 'Drawing complete. Review or preview before applying.';
        } else if (action === 'reverse') {
            navigation.points = this.navigationRuntime.reversePath(
                navigation.points
            );
            navigation.selectedPointIndex = null;
            navigation.selectedSegmentIndex = null;
            navigation.snapRefs = [];
            navigation.lockedSegmentIndexes = [];
            navigation.validationStatus = 'pending';
        } else if (action === 'insert'
                && navigation.selectedPointIndex !== null
                && navigation.selectedPointIndex
                    < navigation.points.length - 1) {
            const index = navigation.selectedPointIndex;
            const left = navigation.points[index];
            const right = navigation.points[index + 1];
            navigation.points = this.navigationRuntime.insertWaypoint(
                navigation.points,
                index,
                { x: (left.x + right.x) / 2, z: (left.z + right.z) / 2 }
            );
            navigation.selectedPointIndex = index + 1;
            navigation.selectedSegmentIndex = index;
            navigation.validationStatus = 'pending';
        } else if (action === 'delete'
                && navigation.selectedPointIndex !== null) {
            navigation.points = this.navigationRuntime.deleteWaypoint(
                navigation.points,
                navigation.selectedPointIndex
            );
            navigation.selectedPointIndex = null;
            navigation.selectedSegmentIndex = null;
            navigation.snapRefs = [];
            navigation.lockedSegmentIndexes = [];
            navigation.validationStatus = 'pending';
        } else if (action === 'lock'
                && navigation.selectedPointIndex !== null
                && navigation.selectedPointIndex
                    < navigation.points.length - 1) {
            const index = navigation.selectedPointIndex;
            navigation.lockedSegmentIndexes =
                navigation.lockedSegmentIndexes.includes(index)
                    ? navigation.lockedSegmentIndexes.filter(function (item) {
                        return item !== index;
                    }) : navigation.lockedSegmentIndexes.concat([index])
                        .sort(function (left, right) { return left - right; });
        } else if (action === 'add-anchor') {
            navigation.anchorPicking = true;
            navigation.drawing = false;
            navigation.message = 'Click the Plan to place the semantic anchor.';
            this._setToolMode('motion-path');
        } else if (action === 'paths') {
            navigation.pathsVisible = !navigation.pathsVisible;
        } else if (action === 'preview') {
            Promise.resolve(navigation.previewLoaded
                ? true : this._loadNavigationPreview()).then(function () {
                if (!this.threeAdapter || !this.threeAdapter.navigationPreview) {
                    return;
                }
                if (navigation.previewPlaying) {
                    this.threeAdapter.navigationPreview.pause();
                    navigation.previewPlaying = false;
                } else {
                    this.threeAdapter.navigationPreview.play();
                    navigation.previewPlaying = true;
                }
                this._renderNavigationDialog();
            }.bind(this)).catch(function (error) {
                navigation.message = error.message;
                this._renderNavigationDialog();
            }.bind(this));
        } else if (action === 'apply') {
            this._applyNavigationPath();
        } else if (action === 'export') {
            try {
                this._exportNavigationGold();
                navigation.message = 'Gold evaluation artifact exported.';
            } catch (error) {
                navigation.message = error.message;
            }
        }
        this._syncNavigationAuthoringPreview();
        this._renderNavigationDialog();
    };

    Workspace.prototype._handleNavigationKeyDown = function (event) {
        const key = String(event && event.key || '').toLowerCase();
        if (key === 'escape') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            if (this.navigationState.drawing
                    || this.navigationState.anchorPicking) {
                this.navigationState.drawing = false;
                this.navigationState.anchorPicking = false;
                this._renderNavigationDialog();
            } else {
                this.closeNavigationDialog(true);
            }
        } else if (key === 'enter' && this.navigationState.drawing) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this.navigationState.drawing = false;
            this.navigationState.message = 'Drawing complete.';
            this._renderNavigationDialog();
        }
    };

    Workspace.prototype._patternSeed = function (includeZones) {
        if (!this.patternRuntime
                || typeof this.patternRuntime.collectSelection !== 'function') {
            throw new Error('Facility pattern tools are unavailable.');
        }
        return this.patternRuntime.collectSelection(
            this.state.layout,
            this.assetCatalog,
            this.state.selection,
            { expandZones: true, includeZones: includeZones !== false }
        );
    };

    Workspace.prototype._initializePatternDefaults = function (mode) {
        const seed = this._patternSeed(![
            'cell-layout', 'perimeter-pattern', 'vertical-stack', 'surface-stack',
        ].includes(mode));
        if (!seed.length) throw new Error('Select equipment or a cell zone first.');
        const bounds = this.patternRuntime.selectionBounds(seed);
        const span = Math.max(bounds.width, bounds.depth, 1);
        const gap = Math.max(0, finite(this.patternState.gap, 1));
        const maxSpan = Math.max.apply(null, seed.map(function (item) {
            return Math.max(finite(item.width, 1), finite(item.depth, 1));
        }));
        const maxRadius = Math.max.apply(null, seed.map(function (item) {
            return Math.hypot(
                finite(item.width, 1),
                finite(item.depth, 1)
            ) / 2;
        }));
        const boundaryInset = maxRadius + gap / 2;
        const cellPitch = maxSpan + gap;
        this.patternState.pitch = Math.max(1, Number((span + 1).toFixed(3)));
        this.patternState.centerX = Number((bounds.center.x - span * 1.5).toFixed(3));
        this.patternState.centerZ = Number(bounds.center.z.toFixed(3));
        this.patternState.width = Math.max(
            4,
            Number((bounds.width + Math.max(2, seed.length - 1) * 1.5).toFixed(3)),
            Number((boundaryInset * 2
                + cellPitch * Math.max(2, Math.ceil(seed.length / 2))).toFixed(3))
        );
        this.patternState.depth = Math.max(
            4,
            Number((bounds.depth + 3).toFixed(3)),
            Number((boundaryInset * 2 + cellPitch * 2).toFixed(3))
        );
        this.patternState.rows = Math.max(
            2,
            Math.min(seed.length, Math.round(Math.sqrt(seed.length)))
        );
        this.patternState.perimeterWidthCount = Math.max(
            1,
            Math.round(finite(this.patternState.perimeterWidthCount, 6))
        );
        this.patternState.perimeterDepthCount = Math.max(
            1,
            Math.round(finite(this.patternState.perimeterDepthCount, 4))
        );
        this.patternState.perimeterClearGap = Math.max(
            0,
            finite(this.patternState.perimeterClearGap, 0)
        );
        const worldBounds = this.options.topPlanOptions
            && this.options.topPlanOptions.worldBounds || {};
        const snap = Math.max(
            0.000001,
            this._activeSnapStep() || this.gridSize || DEFAULT_PLAN_GRID_METERS
        );
        this.patternState.mirrorAxisX = Number((
            Math.ceil((bounds.maxX + Math.max(gap, snap)) / snap) * snap
        ).toFixed(6));
        this.patternState.mirrorAxisZ = Number((
            Math.ceil((bounds.maxZ + Math.max(gap, snap)) / snap) * snap
        ).toFixed(6));
        this.patternState.mirrorAxisStart = {
            x: this.patternState.mirrorAxisX,
            z: finite(worldBounds.minZ, 0),
        };
        this.patternState.mirrorAxisEnd = {
            x: this.patternState.mirrorAxisX,
            z: finite(
                worldBounds.maxZ,
                this.planSettings.depthMeters
            ),
        };
        this.patternState.mirrorPicking = false;
        this.patternState.mirrorPickPoints = [];
        if (mode === 'surface-stack') {
            const placements = seed.filter(function (item) {
                return item.kind === 'placement';
            });
            if (placements.length < 2) {
                throw new Error(
                    'Select one support and at least one item to place on it.'
                );
            }
            const support = placements.slice().sort(function (left, right) {
                const areaDelta = right.width * right.depth
                    - left.width * left.depth;
                return Math.abs(areaDelta) > 1e-9
                    ? areaDelta : String(left.id).localeCompare(String(right.id));
            })[0];
            this.patternState.surfaceSupportId = support.id;
            this.patternState.surfaceId = support.supportSurfaces
                && support.supportSurfaces.length
                ? support.supportSurfaces[0].surfaceId
                : 'derived-top';
        }
        return seed;
    };

    Workspace.prototype._mirrorAxisPoints = function () {
        const bounds = this.options.topPlanOptions
            && this.options.topPlanOptions.worldBounds || {};
        const minX = finite(bounds.minX, 0);
        const minZ = finite(bounds.minZ, 0);
        const maxX = finite(bounds.maxX, minX + this.planSettings.widthMeters);
        const maxZ = finite(bounds.maxZ, minZ + this.planSettings.depthMeters);
        if (this.patternState.mirrorAxisMode === 'vertical') {
            return {
                start: { x: this.patternState.mirrorAxisX, z: minZ },
                end: { x: this.patternState.mirrorAxisX, z: maxZ },
            };
        }
        if (this.patternState.mirrorAxisMode === 'horizontal') {
            return {
                start: { x: minX, z: this.patternState.mirrorAxisZ },
                end: { x: maxX, z: this.patternState.mirrorAxisZ },
            };
        }
        if (!this.patternState.mirrorAxisStart
                || !this.patternState.mirrorAxisEnd) {
            throw new Error('Pick two Plan points for the mirror construction line.');
        }
        return {
            start: clone(this.patternState.mirrorAxisStart),
            end: clone(this.patternState.mirrorAxisEnd),
        };
    };

    Workspace.prototype._buildPatternResult = function () {
        const mode = this.patternState.mode;
        const seed = mode === 'swap' ? [] : this._patternSeed(![
            'cell-layout', 'perimeter-pattern', 'vertical-stack', 'surface-stack',
        ].includes(mode));
        if (mode !== 'vertical-stack' && seed.some(function (item) {
            return item.snapRelationship
                && item.snapRelationship.family === 'vertical_stack';
        })) {
            throw new Error(
                'Move, duplicate, or delete a completed stack as one unit. '
                + 'Nested layout patterns are not supported yet.'
            );
        }
        if (mode === 'linear-pattern') {
            let angle = this.patternState.angleDegrees;
            if (this.patternState.linearDirection === 'horizontal') angle = 0;
            else if (this.patternState.linearDirection === 'vertical') angle = 90;
            return this.patternRuntime.buildLinearPattern(seed, {
                count: this.patternState.count,
                pitch: this.patternState.pitch,
                angleDegrees: angle,
            });
        }
        if (mode === 'circular-pattern') {
            return this.patternRuntime.buildCircularPattern(seed, {
                count: this.patternState.count,
                centerX: this.patternState.centerX,
                centerZ: this.patternState.centerZ,
                sweepDegrees: this.patternState.sweepDegrees,
                rotateWithPattern: this.patternState.rotateWithPattern,
            });
        }
        if (mode === 'vertical-stack') {
            return this.patternRuntime.buildVerticalStack(seed, {
                count: this.patternState.stackCount,
                gap: this.patternState.stackGap,
            });
        }
        if (mode === 'surface-stack') {
            return this.patternRuntime.buildSurfaceStack(seed, {
                supportPlacementId: this.patternState.surfaceSupportId,
                surfaceId: this.patternState.surfaceId,
                side: this.patternState.surfaceSide,
                gap: this.patternState.surfaceGap,
                itemGap: this.patternState.surfaceItemGap,
                inset: this.patternState.surfaceInset,
            });
        }
        if (mode === 'perimeter-pattern') {
            return this.patternRuntime.buildRectangularPerimeter(seed, {
                shape: this.patternState.perimeterShape,
                widthCount: this.patternState.perimeterWidthCount,
                depthCount: this.patternState.perimeterDepthCount,
                clearGap: this.patternState.perimeterClearGap,
                angleDegrees: this.patternState.angleDegrees,
            });
        }
        if (mode === 'mirror') {
            const axis = this._mirrorAxisPoints();
            return this.patternRuntime.buildMirror(seed, {
                axisStart: axis.start,
                axisEnd: axis.end,
            });
        }
        if (mode === 'swap') {
            return this.patternRuntime.buildSwap(
                this.state.layout,
                this.assetCatalog,
                this.state.selection
            );
        }
        return this.patternRuntime.buildCellLayout(seed, {
            shape: this.patternState.shape,
            width: this.patternState.width,
            depth: this.patternState.depth,
            gap: this.patternState.gap,
            rows: this.patternState.rows,
            orientation: this.patternState.orientation,
            angleDegrees: this.patternState.angleDegrees,
            invertU: this.patternState.invertU,
        });
    };

    Workspace.prototype._setPatternPreview = function (preview) {
        this.patternPreview = preview ? clone(preview) : null;
        if (!this.topAdapter
                || typeof this.topAdapter.setTransientPatternPreview
                    !== 'function') return false;
        return this.topAdapter.setTransientPatternPreview(this.patternPreview);
    };

    Workspace.prototype._updatePatternPreview = function () {
        if (!this.patternState.open || this.patternState.applying) {
            this._setPatternPreview(null);
            return null;
        }
        try {
            const result = this._buildPatternResult();
            this.patternMessage = result.mode === 'cell-layout'
                ? result.seedCount + ' cell items will be repositioned.'
                : result.mode === 'vertical-stack'
                    ? result.count + ' items will form a '
                        + formattedDistance(displayDistance(
                            result.guide.totalHeightMeters,
                            this.planPreferences.unit
                        )) + ' ' + this.planPreferences.unit
                        + ' vertical stack.'
                : result.mode === 'surface-stack'
                    ? result.count + ' item' + (result.count === 1 ? '' : 's')
                        + ' will be placed ' + result.guide.side
                        + ' the selected support surface.'
                : result.mode === 'mirror'
                    ? result.seedCount + ' mirrored cop'
                        + (result.seedCount === 1 ? 'y' : 'ies')
                        + ' will be created.'
                : result.mode === 'perimeter'
                    ? (result.count - 1) + ' perimeter module'
                        + (result.count === 2 ? '' : 's')
                        + ' will be created across '
                        + result.guide.widthCount + ' width and '
                        + result.guide.depthCount + ' depth positions per side.'
                : result.mode === 'swap'
                    ? result.seedCount
                        + ' layout objects will exchange cell centers.'
                : (result.count - 1) + ' new instance'
                    + (result.count === 2 ? '' : 's') + ' of '
                    + result.seedCount + ' seed item'
                    + (result.seedCount === 1 ? '' : 's') + ' will be created.';
            this._setPatternPreview(result);
            return result;
        } catch (error) {
            this.patternMessage = error.message;
            this._setPatternPreview(null);
            return null;
        }
    };

    Workspace.prototype._renderPatternDialog = function () {
        if (!this.patternDialog) return;
        const mode = this.patternState.mode;
        this.patternDialog.hidden = !this.patternState.open;
        this.patternTitle.textContent = {
            'linear-pattern': 'Linear pattern',
            'circular-pattern': 'Circular pattern',
            'perimeter-pattern': 'Rectangular perimeter pattern',
            'cell-layout': 'Arrange manufacturing cell',
            'vertical-stack': 'Create vertical stack',
            'surface-stack': 'Place equipment on a support surface',
            mirror: 'Mirror layout selection',
            swap: 'Swap layout positions',
        }[mode] || 'Create layout pattern';
        Array.prototype.forEach.call(
            this.patternTabs.querySelectorAll('[data-pattern-mode]'),
            function (button) {
                const active = button.getAttribute('data-pattern-mode') === mode;
                button.setAttribute('aria-selected', active ? 'true' : 'false');
                button.setAttribute('tabindex', active ? '0' : '-1');
            }
        );
        clearElement(this.patternBody);
        let seed = [];
        try {
            seed = mode === 'swap' ? this.state.selection.map(function (id) {
                return { id: id, kind: 'swap-selection' };
            }) : this._patternSeed(![
                'cell-layout', 'perimeter-pattern', 'vertical-stack', 'surface-stack',
            ].includes(mode));
        } catch (error) {
            this.patternMessage = error.message;
        }
        const counts = seed.reduce(function (result, item) {
            result[item.kind] = (result[item.kind] || 0) + 1;
            return result;
        }, {});
        const summary = [];
        if (counts.placement) summary.push(counts.placement + ' equipment');
        if (counts['floor-marking']) {
            summary.push(counts['floor-marking'] + ' floor marking'
                + (counts['floor-marking'] === 1 ? '' : 's'));
        }
        if (counts.zone) summary.push(counts.zone + ' cell zone');
        if (counts['swap-selection']) {
            summary.push(counts['swap-selection'] + ' swap targets');
        }
        this.patternBody.appendChild(element(this.document, 'p', {
            className: 'ip-flw-precision-selection',
        }, summary.length ? summary.join(', ') + ' in seed'
            : 'No pattern seed selected'));
        const unit = this.planPreferences.unit;
        if (mode === 'linear-pattern') {
            append(this.patternBody,
                this._patternSelect('Direction', 'linearDirection', [
                    { value: 'horizontal', label: 'Horizontal (X)' },
                    { value: 'vertical', label: 'Vertical (Z)' },
                    { value: 'custom', label: 'Custom angle' },
                ]),
                this._patternNumber('Pitch (' + unit + ')', 'pitch',
                    displayDistance(this.patternState.pitch, unit), {
                        min: 0.01,
                    }),
                this._patternNumber('Total instances', 'count',
                    this.patternState.count, { min: 2, max: 50, step: 1 })
            );
            if (this.patternState.linearDirection === 'custom') {
                this.patternBody.appendChild(this._patternNumber(
                    'Direction angle (degrees)',
                    'angleDegrees',
                    this.patternState.angleDegrees,
                    { step: 1 }
                ));
            }
        } else if (mode === 'circular-pattern') {
            append(this.patternBody,
                this._patternNumber('Center X (' + unit + ')', 'centerX',
                    displayDistance(this.patternState.centerX, unit)),
                this._patternNumber('Center Z (' + unit + ')', 'centerZ',
                    displayDistance(this.patternState.centerZ, unit)),
                this._patternNumber('Total instances', 'count',
                    this.patternState.count, { min: 2, max: 50, step: 1 }),
                this._patternNumber('Total angle (degrees)', 'sweepDegrees',
                    this.patternState.sweepDegrees, {
                        min: 0.1, max: 360, step: 1,
                    }),
                this._patternCheckbox(
                    'Rotate instances with pattern',
                    'rotateWithPattern'
                )
            );
        } else if (mode === 'vertical-stack') {
            append(this.patternBody,
                this._patternNumber(
                    'Total items', 'stackCount',
                    this.patternState.stackCount,
                    { min: 2, max: 50, step: 1 }
                ),
                this._patternNumber(
                    'Vertical gap (' + unit + ')', 'stackGap',
                    displayDistance(this.patternState.stackGap, unit),
                    { min: 0 }
                )
            );
            this.patternBody.appendChild(element(this.document, 'p', {
                className: 'ip-flw-precision-selection',
            }, 'The selected equipment is the base. Copies use authoritative '
                + 'asset height and remain one movable stack. Load capacity and '
                + 'stability remain unverified until approved evidence exists.'));
        } else if (mode === 'surface-stack') {
            const placements = seed.filter(function (item) {
                return item.kind === 'placement';
            });
            const supportOptions = placements.map(function (item) {
                return {
                    value: item.id,
                    label: cleanString(item.assetId, item.id) + ' - ' + item.id,
                };
            });
            const selectedSupport = placements.find(function (item) {
                return item.id === this.patternState.surfaceSupportId;
            }, this) || placements[0];
            const surfaceDefinitions = selectedSupport
                && Array.isArray(selectedSupport.supportSurfaces)
                ? selectedSupport.supportSurfaces : [];
            const surfaceOptions = surfaceDefinitions.length
                ? surfaceDefinitions.map(function (surface) {
                    return {
                        value: surface.surfaceId,
                        label: cleanString(surface.label, surface.surfaceId),
                    };
                })
                : [{ value: 'derived-top', label: 'Derived bounding-box surface' }];
            if (!surfaceOptions.some(function (option) {
                return option.value === this.patternState.surfaceId;
            }, this)) {
                this.patternState.surfaceId = surfaceOptions[0].value;
            }
            const selectedSurface = surfaceDefinitions.find(function (surface) {
                return surface.surfaceId === this.patternState.surfaceId;
            }, this);
            const allowedSides = selectedSurface
                && Array.isArray(selectedSurface.allowedSides)
                && selectedSurface.allowedSides.length
                ? selectedSurface.allowedSides : ['above', 'below'];
            if (!allowedSides.includes(this.patternState.surfaceSide)) {
                this.patternState.surfaceSide = allowedSides[0];
            }
            const sideOptions = allowedSides.map(function (side) {
                return {
                    value: side,
                    label: side === 'below'
                        ? 'Below / suspended' : 'Above / on top',
                };
            });
            append(this.patternBody,
                this._patternSelect(
                    'Support equipment', 'surfaceSupportId', supportOptions
                ),
                this._patternSelect('Support surface', 'surfaceId', surfaceOptions),
                this._patternSelect('Surface side', 'surfaceSide', sideOptions),
                this._patternNumber(
                    'Surface gap (' + unit + ')', 'surfaceGap',
                    displayDistance(this.patternState.surfaceGap, unit),
                    { min: 0 }
                ),
                this._patternNumber(
                    'Item gap (' + unit + ')', 'surfaceItemGap',
                    displayDistance(this.patternState.surfaceItemGap, unit),
                    { min: 0 }
                ),
                this._patternNumber(
                    'Edge inset (' + unit + ')', 'surfaceInset',
                    displayDistance(this.patternState.surfaceInset, unit),
                    { min: 0 }
                )
            );
            this.patternBody.appendChild(element(this.document, 'p', {
                className: 'ip-flw-precision-selection',
            }, 'Each child receives an independent local X/Z coordinate on the '
                + 'support. Moving the support carries every attached child. '
                + 'Load capacity and attachment safety remain unverified.'));
        } else if (mode === 'perimeter-pattern') {
            append(this.patternBody,
                this._patternSelect('Perimeter shape', 'perimeterShape', [
                    { value: 'rectangle', label: 'Rectangle' },
                    { value: 'square', label: 'Square' },
                ]),
                this._patternNumber(
                    this.patternState.perimeterShape === 'square'
                        ? 'Modules per side' : 'Modules along width',
                    'perimeterWidthCount',
                    this.patternState.perimeterWidthCount,
                    { min: 1, max: 50, step: 1 }
                )
            );
            if (this.patternState.perimeterShape !== 'square') {
                this.patternBody.appendChild(this._patternNumber(
                    'Modules along depth',
                    'perimeterDepthCount',
                    this.patternState.perimeterDepthCount,
                    { min: 1, max: 50, step: 1 }
                ));
            }
            append(this.patternBody,
                this._patternNumber(
                    'Clear gap (' + unit + ')',
                    'perimeterClearGap',
                    displayDistance(
                        this.patternState.perimeterClearGap,
                        unit
                    ),
                    { min: 0 }
                ),
                this._patternNumber(
                    'Layout angle (degrees)',
                    'angleDegrees',
                    this.patternState.angleDegrees,
                    { step: 1 }
                )
            );
            this.patternBody.appendChild(element(this.document, 'p', {
                className: 'ip-flw-precision-selection',
            }, 'The selected module remains at the first corner. '
                + 'Copies follow the four sides and remain independently editable.'));
        } else if (mode === 'mirror') {
            append(this.patternBody,
                this._patternSelect('Mirror axis', 'mirrorAxisMode', [
                    { value: 'vertical', label: 'Vertical grid line (X)' },
                    { value: 'horizontal', label: 'Horizontal grid line (Z)' },
                    { value: 'two-point', label: 'Two-point construction line' },
                ])
            );
            if (this.patternState.mirrorAxisMode === 'vertical') {
                this.patternBody.appendChild(this._patternNumber(
                    'Axis X (' + unit + ')',
                    'mirrorAxisX',
                    displayDistance(this.patternState.mirrorAxisX, unit)
                ));
            } else if (this.patternState.mirrorAxisMode === 'horizontal') {
                this.patternBody.appendChild(this._patternNumber(
                    'Axis Z (' + unit + ')',
                    'mirrorAxisZ',
                    displayDistance(this.patternState.mirrorAxisZ, unit)
                ));
            } else {
                const start = this.patternState.mirrorAxisStart;
                const end = this.patternState.mirrorAxisEnd;
                this.patternBody.appendChild(element(this.document, 'p', {
                    className: 'ip-flw-precision-selection',
                    'data-pattern-mirror-readout': '',
                }, start && end
                    ? 'Axis: (' + formattedDistance(displayDistance(
                        start.x, unit
                    )) + ', ' + formattedDistance(displayDistance(
                        start.z, unit
                    )) + ') to (' + formattedDistance(displayDistance(
                        end.x, unit
                    )) + ', ' + formattedDistance(displayDistance(
                        end.z, unit
                    )) + ') ' + unit
                    : 'No construction line selected.'));
            }
            this.patternBody.appendChild(element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary-action ip-flw-pattern-pick-axis',
                'data-pattern-action': 'pick-mirror-axis',
                'aria-pressed': this.patternState.mirrorPicking
                    ? 'true' : 'false',
            }, this.patternState.mirrorPicking
                ? (this.patternState.mirrorAxisMode === 'two-point'
                    && this.patternState.mirrorPickPoints.length === 1
                    ? 'Pick second point in Plan'
                    : 'Pick axis in Plan')
                : 'Pick axis in Plan'));
            this.patternBody.appendChild(element(this.document, 'p', {
                className: 'ip-flw-precision-selection',
            }, this.patternState.mirrorAxisMode === 'two-point'
                ? 'Pick two points to define an arbitrary construction axis.'
                : 'Pick one grid line in the Plan view.'));
        } else if (mode === 'swap') {
            this.patternBody.appendChild(element(this.document, 'p', {
                className: 'ip-flw-precision-selection',
            }, 'The two selected objects will exchange centers. Selected cell '
                + 'zones carry their contained equipment and floor markings.'));
        } else {
            append(this.patternBody,
                this._patternSelect('Cell arrangement', 'shape',
                    CELL_LAYOUT_PRESETS),
                this._patternNumber('Cell width (' + unit + ')', 'width',
                    displayDistance(this.patternState.width, unit), {
                        min: 0.01,
                    }),
                this._patternNumber('Cell depth (' + unit + ')', 'depth',
                    displayDistance(this.patternState.depth, unit), {
                        min: 0.01,
                    }),
                this._patternNumber('Preferred clear gap (' + unit + ')', 'gap',
                    displayDistance(this.patternState.gap, unit), { min: 0 }),
                this._patternNumber('Layout angle (degrees)', 'angleDegrees',
                    this.patternState.angleDegrees, { step: 1 }),
                this._patternSelect('Equipment orientation', 'orientation', [
                    { value: 'preserve', label: 'Preserve current orientation' },
                    { value: 'follow-path', label: 'Follow process path' },
                    { value: 'face-center', label: 'Face cell center' },
                    { value: 'face-outward', label: 'Face away from center' },
                ])
            );
            if (this.patternState.shape === 'u') {
                this.patternBody.appendChild(this._patternCheckbox(
                    'Invert U opening',
                    'invertU'
                ));
            }
            if (['grid', 'parallel', 'serpentine'].includes(
                this.patternState.shape
            )) {
                this.patternBody.appendChild(this._patternNumber(
                    'Rows', 'rows', this.patternState.rows,
                    { min: 1, max: Math.max(1, seed.length), step: 1 }
                ));
            }
        }
        const result = this._updatePatternPreview();
        this.patternStatus.textContent = this.patternMessage;
        this.patternApply.disabled = !result
            || this.patternState.applying
            || this.state.busy
            || this.state.conflict;
        this.patternApply.textContent = this.patternState.applying
            ? 'Applying...' : 'Apply';
    };

    Workspace.prototype._syncPrecisionIdentities = function () {
        const placements = this._precisionSelectedPlacements();
        const ids = placements.map(function (placement) {
            return placement.placementId;
        });
        if (!ids.includes(this.precisionState.anchorId)) {
            this.precisionState.anchorId = ids[0] || '';
        }
        if (!ids.includes(this.precisionState.referenceId)) {
            this.precisionState.referenceId = ids[0] || '';
        }
        if (!ids.includes(this.precisionState.movingId)
                || this.precisionState.movingId
                    === this.precisionState.referenceId) {
            this.precisionState.movingId = ids.find(function (id) {
                return id !== this.precisionState.referenceId;
            }, this) || '';
        }
        return placements;
    };

    Workspace.prototype._renderPrecisionDialog = function () {
        if (!this.precisionDialog) return;
        const placements = this._syncPrecisionIdentities();
        const mode = this.precisionState.mode;
        this.precisionDialog.hidden = !this.precisionState.open;
        this.precisionTitle.textContent = {
            align: 'Align equipment',
            distribute: 'Distribute equipment',
            relative: 'Relative placement',
            distance: 'Set distance',
            offset: 'Offset equipment',
        }[mode] || 'Position equipment';
        Array.prototype.forEach.call(
            this.precisionTabs.querySelectorAll('[data-precision-mode]'),
            function (button) {
                const active = button.getAttribute('data-precision-mode') === mode;
                button.setAttribute('aria-selected', active ? 'true' : 'false');
                button.setAttribute('tabindex', active ? '0' : '-1');
            }
        );
        clearElement(this.precisionBody);
        this.precisionBody.appendChild(element(this.document, 'p', {
            className: 'ip-flw-precision-selection',
        }, placements.length + ' equipment placement'
            + (placements.length === 1 ? '' : 's') + ' selected'));
        const placementOptions = placements.map(function (placement) {
            return {
                value: placement.placementId,
                label: this._precisionPlacementLabel(placement),
            };
        }, this);
        const unit = this.planPreferences.unit;
        this.precisionMessage = '';
        if (mode === 'align') {
            append(this.precisionBody,
                this._precisionSelect('Reference', 'anchorId', placementOptions),
                this._precisionSelect('Align', 'alignMode', [
                    { value: 'left', label: 'Left edges' },
                    { value: 'center-x', label: 'Horizontal centers' },
                    { value: 'right', label: 'Right edges' },
                    { value: 'north', label: 'North edges' },
                    { value: 'center-z', label: 'Vertical centers' },
                    { value: 'south', label: 'South edges' },
                ])
            );
            this.precisionMessage = 'The reference stays fixed.';
        } else if (mode === 'distribute') {
            append(this.precisionBody,
                this._precisionSelect('Direction', 'distributeAxis', [
                    { value: 'x', label: 'Horizontal (X)' },
                    { value: 'z', label: 'Vertical (Z)' },
                ]),
                this._precisionSelect('Spacing', 'distributeMethod', [
                    { value: 'equal-gap', label: 'Equal clear gaps' },
                    { value: 'equal-center', label: 'Equal center spacing' },
                    { value: 'fixed-gap', label: 'Exact clear gap' },
                ])
            );
            if (this.precisionState.distributeMethod === 'fixed-gap') {
                this.precisionBody.appendChild(this._precisionNumber(
                    'Clear gap (' + unit + ')',
                    'distributeGap',
                    displayDistance(this.precisionState.distributeGap, unit)
                ));
            }
            this.precisionMessage = 'Equipment is ordered by its current position.';
        } else if (mode === 'relative') {
            append(this.precisionBody,
                this._precisionSelect('Reference', 'referenceId', placementOptions),
                this._precisionSelect('Place selection', 'relation', [
                    { value: 'east', label: 'East / right of reference' },
                    { value: 'west', label: 'West / left of reference' },
                    { value: 'north', label: 'North / above reference' },
                    { value: 'south', label: 'South / below reference' },
                ]),
                this._precisionNumber(
                    'Clear distance (' + unit + ')',
                    'relativeDistance',
                    displayDistance(this.precisionState.relativeDistance, unit)
                ),
                this._precisionSelect('Perpendicular alignment',
                    'relativeAlignment', [
                        { value: 'minimum', label: 'Minimum edges' },
                        { value: 'center', label: 'Centers' },
                        { value: 'maximum', label: 'Maximum edges' },
                    ])
            );
            this.precisionMessage = Math.max(0, placements.length - 1)
                + ' placement' + (placements.length === 2 ? '' : 's')
                + ' will move as one group.';
        } else if (mode === 'distance') {
            const movingOptions = placementOptions.filter(function (item) {
                return item.value !== this.precisionState.referenceId;
            }, this);
            append(this.precisionBody,
                this._precisionSelect('Fixed reference', 'referenceId', placementOptions),
                this._precisionSelect('Placement to move', 'movingId', movingOptions),
                this._precisionSelect('Measurement', 'distanceMode', [
                    { value: 'horizontal-gap', label: 'Horizontal edge gap' },
                    { value: 'vertical-gap', label: 'Vertical edge gap' },
                    { value: 'horizontal-center', label: 'Horizontal centers' },
                    { value: 'vertical-center', label: 'Vertical centers' },
                    { value: 'center-distance', label: 'Center-to-center distance' },
                ]),
                this._precisionNumber(
                    'Requested distance (' + unit + ')',
                    'requestedDistance',
                    displayDistance(this.precisionState.requestedDistance, unit)
                )
            );
            if (this.precisionState.referenceId && this.precisionState.movingId) {
                try {
                    const current = measurePlacementDistance(
                        this.state.layout,
                        this.assetCatalog,
                        this.precisionState.referenceId,
                        this.precisionState.movingId,
                        this.precisionState.distanceMode
                    );
                    this.precisionMessage = 'Current: '
                        + formattedDistance(displayDistance(current, unit))
                        + ' ' + unit;
                } catch (error) {
                    this.precisionMessage = error.message;
                }
            }
        } else {
            append(this.precisionBody,
                this._precisionNumber('X offset (' + unit + ')', 'offsetX',
                    displayDistance(this.precisionState.offsetX, unit)),
                this._precisionNumber('Z offset (' + unit + ')', 'offsetZ',
                    displayDistance(this.precisionState.offsetZ, unit))
            );
            const copyLabel = element(this.document, 'label', {
                className: 'ip-flw-precision-check',
            });
            const copyInput = element(this.document, 'input', {
                type: 'checkbox',
                'data-precision-field': 'createCopies',
                'aria-label': 'Create copies at the offset',
            });
            copyInput.checked = this.precisionState.createCopies === true;
            append(copyLabel, copyInput, element(this.document, 'span', {},
                'Create copies'));
            this.precisionBody.appendChild(copyLabel);
            this.precisionMessage = this.precisionState.createCopies
                ? 'Copies preserve the selected group arrangement.'
                : 'The selected group moves by one exact offset.';
        }
        this.precisionStatus.textContent = this.precisionMessage;
        const minimum = mode === 'distribute' ? 3
            : mode === 'offset' ? 1 : 2;
        this.precisionApply.disabled = placements.length < minimum
            || Boolean(this.state.busy);
    };

    Workspace.prototype._buildWalkthroughContextUi = function () {
        this.walkthroughContextPrompt = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-context-prompt',
            'data-walkthrough-context-action': 'open',
            'aria-label': 'Open focused equipment details',
            hidden: true,
        });
        this.walkthroughContextPromptName = element(this.document, 'strong', {
            className: 'ip-flw-context-prompt-name',
        });
        this.walkthroughContextPromptHint = element(this.document, 'span', {
            className: 'ip-flw-context-prompt-hint',
        }, 'E  Details');
        append(
            this.walkthroughContextPrompt,
            this.walkthroughContextPromptName,
            this.walkthroughContextPromptHint
        );

        this.walkthroughContextCard = element(this.document, 'aside', {
            className: 'ip-flw-context-card',
            'aria-label': 'Focused equipment details',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-context-card-header',
        });
        const identity = element(this.document, 'div', {
            className: 'ip-flw-context-card-identity',
        });
        this.walkthroughContextTitle = element(this.document, 'h3');
        this.walkthroughContextMeta = element(this.document, 'p');
        append(identity, this.walkthroughContextTitle, this.walkthroughContextMeta);
        const headerActions = element(this.document, 'div', {
            className: 'ip-flw-context-card-header-actions',
        });
        const pin = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-context-icon-button',
            'data-walkthrough-context-action': 'pin',
            'aria-label': 'Pin equipment details',
            'aria-pressed': 'false',
            title: 'Pin details',
        });
        pin.appendChild(element(this.document, 'img', {
            src: VIEWPORT_ICON_ROOT + 'map-pin.svg',
            alt: '',
            draggable: 'false',
            'aria-hidden': 'true',
        }));
        const close = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-context-icon-button',
            'data-walkthrough-context-action': 'close',
            'aria-label': 'Close equipment details',
            title: 'Close',
        }, 'X');
        append(headerActions, pin, close);
        append(header, identity, headerActions);

        const modeRow = element(this.document, 'label', {
            className: 'ip-flw-context-mode',
        });
        modeRow.appendChild(element(this.document, 'span', {}, 'View'));
        this.walkthroughContextMode = element(this.document, 'select', {
            'data-walkthrough-context-mode': '',
            'aria-label': 'Equipment information category',
        });
        WALKTHROUGH_CONTEXT_MODES.forEach(function (mode) {
            this.walkthroughContextMode.appendChild(element(
                this.document,
                'option',
                { value: mode.key },
                mode.label
            ));
        }, this);
        this.walkthroughContextMode.value = this.walkthroughContextState.mode;
        modeRow.appendChild(this.walkthroughContextMode);
        this.walkthroughContextBody = element(this.document, 'div', {
            className: 'ip-flw-context-card-body',
        });
        const footer = element(this.document, 'footer', {
            className: 'ip-flw-context-card-actions',
        });
        append(footer,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary',
                'data-walkthrough-context-action': 'select',
            }, 'Select in Layout'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-primary',
                'data-walkthrough-context-action': 'walk-to',
            }, 'Walk to Equipment')
        );
        append(
            this.walkthroughContextCard,
            header,
            modeRow,
            this.walkthroughContextBody,
            footer
        );
    };

    Workspace.prototype._buildThreeRecordingUi = function () {
        const selectRow = function (label, attribute, options, value) {
            const row = element(this.document, 'label', {
                className: 'ip-flw-recording-field',
            });
            row.appendChild(element(this.document, 'span', {}, label));
            const select = element(this.document, 'select', {
                'data-recording-setting': attribute,
                'aria-label': label,
            });
            options.forEach(function (option) {
                select.appendChild(element(this.document, 'option', {
                    value: option.key,
                }, option.label));
            }, this);
            select.value = value;
            row.appendChild(select);
            return { row: row, input: select };
        }.bind(this);
        const checkRow = function (label, attribute, checked) {
            const row = element(this.document, 'label', {
                className: 'ip-flw-recording-check',
            });
            const input = element(this.document, 'input', {
                type: 'checkbox',
                'data-recording-setting': attribute,
                'aria-label': label,
            });
            input.checked = checked === true;
            append(row, input, element(this.document, 'span', {}, label));
            return { row: row, input: input };
        }.bind(this);

        this.threeRecordingPanel = element(this.document, 'section', {
            className: 'ip-flw-recording-panel',
            role: 'dialog',
            'aria-label': 'Record facility view',
            hidden: true,
        });
        const panelHeader = element(this.document, 'header', {
            className: 'ip-flw-recording-header',
        });
        const panelHeading = element(this.document, 'div');
        append(panelHeading,
            element(this.document, 'h3', {}, 'Record facility view'),
            element(this.document, 'p', {}, 'Capture the 3D viewport only.')
        );
        append(panelHeader,
            panelHeading,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-recording-close',
                'data-recording-action': 'cancel',
                'aria-label': 'Close recording settings',
                title: 'Close',
            }, 'X')
        );
        const mode = selectRow(
            'Presentation',
            'presentationMode',
            RECORDING_PRESENTATION_MODES,
            this.recordingState.settings.presentationMode
        );
        const resolution = selectRow(
            'Resolution',
            'resolution',
            RECORDING_RESOLUTIONS,
            this.recordingState.settings.resolution
        );
        const fps = selectRow('Frame rate', 'fps', [
            { key: '30', label: '30 FPS' },
            { key: '60', label: '60 FPS' },
        ], String(this.recordingState.settings.fps));
        const microphone = checkRow(
            'Microphone narration',
            'microphone',
            this.recordingState.settings.microphone
        );
        const includeHud = checkRow(
            'Walkthrough status overlay',
            'includeHud',
            this.recordingState.settings.includeHud
        );
        const includeCursor = checkRow(
            'Pointer indicator',
            'includeCursor',
            this.recordingState.settings.includeCursor
        );
        this.recordingPresentationInput = mode.input;
        this.recordingResolutionInput = resolution.input;
        this.recordingFpsInput = fps.input;
        this.recordingMicrophoneInput = microphone.input;
        this.recordingHudInput = includeHud.input;
        this.recordingCursorInput = includeCursor.input;
        this.recordingFormatText = element(this.document, 'p', {
            className: 'ip-flw-recording-format',
        }, 'Format is selected by browser capability.');
        this.recordingErrorText = element(this.document, 'p', {
            className: 'ip-flw-recording-error',
            role: 'alert',
            hidden: true,
        });
        const panelActions = element(this.document, 'footer', {
            className: 'ip-flw-recording-actions',
        });
        append(panelActions,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary',
                'data-recording-action': 'cancel',
            }, 'Cancel'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-primary',
                'data-recording-action': 'start',
            }, 'Start recording')
        );
        append(this.threeRecordingPanel,
            panelHeader,
            mode.row,
            resolution.row,
            fps.row,
            microphone.row,
            includeHud.row,
            includeCursor.row,
            this.recordingFormatText,
            this.recordingErrorText,
            panelActions
        );

        this.threeRecordingCountdown = element(this.document, 'div', {
            className: 'ip-flw-recording-countdown',
            role: 'status',
            'aria-live': 'assertive',
            hidden: true,
        });
        this.threeRecordingMonitor = element(this.document, 'div', {
            className: 'ip-flw-recording-monitor',
            role: 'status',
            'aria-live': 'polite',
            hidden: true,
        });
        this.recordingTimerText = element(this.document, 'strong', {}, '00:00');
        append(this.threeRecordingMonitor,
            element(this.document, 'span', {
                className: 'ip-flw-recording-live-dot',
                'aria-hidden': 'true',
            }),
            element(this.document, 'span', {
                className: 'ip-flw-recording-live-label',
            }, 'REC'),
            this.recordingTimerText,
            element(this.document, 'button', {
                type: 'button',
                'data-recording-action': 'pause',
            }, 'Pause'),
            element(this.document, 'button', {
                type: 'button',
                'data-recording-action': 'stop',
            }, 'Stop')
        );

        this.threeRecordingPreview = element(this.document, 'section', {
            className: 'ip-flw-recording-preview',
            role: 'dialog',
            'aria-label': 'Recorded facility preview',
            hidden: true,
        });
        this.recordingPreviewVideo = element(this.document, 'video', {
            controls: true,
            preload: 'metadata',
            'aria-label': 'Recorded facility view preview',
        });
        this.recordingPreviewSummary = element(this.document, 'p', {
            className: 'ip-flw-recording-preview-summary',
        });
        const previewActions = element(this.document, 'footer', {
            className: 'ip-flw-recording-actions',
        });
        append(previewActions,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-secondary',
                'data-recording-action': 'discard',
            }, 'Discard'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-primary',
                'data-recording-action': 'download',
            }, 'Save video')
        );
        append(this.threeRecordingPreview,
            element(this.document, 'h3', {}, 'Review recording'),
            this.recordingPreviewVideo,
            this.recordingPreviewSummary,
            previewActions
        );
    };

    Workspace.prototype._designEntityLabel = function (reference) {
        const ref = reference || {};
        const id = String(ref.entityId || ref.placementId || ref.routeId || '');
        const layout = this.state && this.state.layout || {};
        const collections = [
            ['placements', 'placementId'],
            ['routes', 'routeId'],
            ['zones', 'zoneId'],
        ];
        for (let index = 0; index < collections.length; index += 1) {
            const collection = collections[index];
            const record = (layout[collection[0]] || []).find(function (item) {
                return item[collection[1]] === id;
            });
            if (record) {
                return String(
                    record.label
                    || record.metadata && record.metadata.instanceLabel
                    || id
                );
            }
        }
        return id || 'Bound item';
    };

    Workspace.prototype._buildDesignPanel = function () {
        this.designPanel = element(this.document, 'aside', {
            className: 'ip-flw-design-panel',
            'aria-label': 'Facility design brief and alternatives',
            hidden: true,
        });
        const header = element(this.document, 'header', {
            className: 'ip-flw-design-header',
        });
        this.designPanelTitle = element(this.document, 'div', {
            className: 'ip-flw-design-heading',
        });
        append(this.designPanelTitle,
            element(this.document, 'strong', {}, 'Design brief'),
            element(this.document, 'span', {
                className: 'ip-flw-design-status',
                'data-design-status': 'idle',
            }, 'Idle')
        );
        this.designPanelToggle = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-design-toggle',
            'data-design-action': 'toggle',
            'aria-label': 'Collapse Facility design brief',
            title: 'Collapse Facility design brief',
        }, '>');
        append(header, this.designPanelTitle, this.designPanelToggle);
        this.designPanelBody = element(this.document, 'div', {
            className: 'ip-flw-design-body',
        });
        this.designObjective = element(this.document, 'section', {
            className: 'ip-flw-design-section',
            'aria-label': 'Active objective',
        });
        this.designSource = element(this.document, 'div', {
            className: 'ip-flw-design-source',
            'aria-label': 'Bound Facility design source',
        });
        this.designLocks = element(this.document, 'div', {
            className: 'ip-flw-design-chips',
            'aria-label': 'Active geometry locks',
        });
        this.designPreferences = element(this.document, 'div', {
            className: 'ip-flw-design-preferences',
        });
        this.designProposalList = element(this.document, 'div', {
            className: 'ip-flw-design-proposals',
            role: 'radiogroup',
            'aria-label': 'Measured Facility design alternatives',
        });
        this.designLegend = element(this.document, 'div', {
            className: 'ip-flw-design-legend',
            'aria-label': 'Proposal comparison legend',
        });
        this.designQualification = element(this.document, 'p', {
            className: 'ip-flw-design-qualification',
        }, 'Unsaved proposals. Geometry and metrics are deterministic; no safety, capacity, or global-optimality claim.');
        append(this.designPanelBody,
            this.designObjective,
            this.designSource,
            this.designLocks,
            this.designPreferences,
            this.designProposalList,
            this.designLegend,
            this.designQualification
        );
        append(this.designPanel, header, this.designPanelBody);
        return this.designPanel;
    };

    Workspace.prototype._renderDesignPanel = function () {
        if (!this.designPanel) return;
        if (this.generationPlanningView && this.generationPlanningView.render()) return;
        if (this.constructionPreview) {
            this._renderConstructionPreview();
            return;
        }
        if (this.constructionPanelBody) this.constructionPanelBody.hidden = true;
        this.designPanelBody.hidden = false;
        this.designPanelTitle.querySelector('strong').textContent = 'Design brief';
        const design = this.designState;
        this.designPanel.hidden = !design.active;
        this.designPanel.setAttribute(
            'data-collapsed',
            design.collapsed ? 'true' : 'false'
        );
        this.root.setAttribute(
            'data-design-pane-open',
            design.active
                ? (design.collapsed ? 'collapsed' : 'true')
                : 'false'
        );
        this.designPanelToggle.textContent = design.collapsed ? '<' : '>';
        this.designPanelToggle.setAttribute(
            'aria-label',
            design.collapsed
                ? 'Expand Facility design brief'
                : 'Collapse Facility design brief'
        );
        const status = this.designPanelTitle.querySelector(
            '.ip-flw-design-status'
        );
        const noImprovement = design.run
            && design.run.terminalReason
                === 'facility_design_no_improved_alternative';
        status.textContent = design.busy
            ? 'Evaluating'
            : design.error
                ? design.attentionKind === 'stale'
                    ? 'Stale source'
                    : design.attentionKind === 'ambiguous'
                        ? 'Choose a target'
                        : 'Needs attention'
                : design.transaction
                    ? 'Unsaved draft'
                    : design.proposals.length
                        ? 'Ready'
                        : noImprovement
                            ? 'No improvement'
                        : design.status === 'active'
                            ? 'Evaluating'
                            : 'Brief ready';
        status.setAttribute(
            'data-design-status',
            design.error
                ? (design.attentionKind || 'error')
                : design.transaction
                    ? 'draft'
                    : noImprovement
                        ? 'no_improvement'
                        : design.status
        );
        this.root.setAttribute(
            'data-design-attention',
            design.attentionKind || 'none'
        );
        clearElement(this.designObjective);
        clearElement(this.designSource);
        clearElement(this.designLocks);
        clearElement(this.designPreferences);
        clearElement(this.designProposalList);
        clearElement(this.designLegend);
        const body = design.brief && design.brief.semanticBody || {};
        const objective = body.objective || {};
        const targets = objective.targetRefs || [];
        const endpoints = design.run && design.run.objectiveEndpoints;
        const endpointText = endpoints && endpoints.source && endpoints.target
            ? this._designEntityLabel(endpoints.source)
                + ' to '
                + this._designEntityLabel(endpoints.target)
            : targets.length
                ? 'Targets: ' + targets.slice(0, 2).map(
                    this._designEntityLabel.bind(this)
                ).join(', ')
                : 'Revision-bound transfer';
        this.designObjective.appendChild(element(
            this.document,
            'h3',
            {},
            'Reduce loaded material travel'
        ));
        this.designObjective.appendChild(element(
            this.document,
            'p',
            {},
            endpointText
        ));
        const base = body.baseStateRef || {};
        if (base.baseRevision) {
            const sourceLabel = base.baseKind === 'saved_layout'
                ? 'Saved layout'
                : base.baseKind === 'editor_draft'
                    ? 'Unsaved editor draft'
                    : 'Unsaved generated draft';
            append(this.designSource,
                element(this.document, 'strong', {}, sourceLabel),
                element(this.document, 'span', {},
                    'Base ' + String(base.baseRevision).slice(0, 12)),
                element(this.document, 'span', {},
                    'Layout ' + String(base.layoutRevision || '').slice(0, 12))
            );
        }
        (body.hardConstraints || []).filter(function (item) {
            return item.status === 'active';
        }).forEach(function (constraint) {
            (constraint.targetRefs || []).forEach(function (ref) {
                this.designLocks.appendChild(element(this.document, 'span', {
                    className: 'ip-flw-design-chip',
                    title: 'Geometry locked by the active design brief',
                }, this._designEntityLabel(ref)));
            }, this);
        }, this);
        const preferences = (body.preferences || []).filter(function (item) {
            return item.status === 'active';
        });
        this.designPreferences.textContent = preferences.length
            ? 'Preference: ' + preferences.map(function (item) {
                return String(item.metricId || 'measured metric');
            }).join(', ')
            : 'Metrics shown separately; no hidden combined score.';
        if (design.baseline) {
            const baselineMetrics = design.baseline.metrics || [];
            const baselineDistance = baselineMetrics.find(function (metric) {
                return metric.metricId === 'loadedRouteDistanceMeters';
            });
            const baselinePerShift = baselineMetrics.find(function (metric) {
                return metric.metricId === 'loadedTravelMetersPerShift';
            });
            const baseline = element(this.document, 'div', {
                className: 'ip-flw-design-baseline',
                'aria-label': 'Current measured baseline',
            });
            append(baseline,
                element(this.document, 'strong', {}, 'Current baseline'),
                element(this.document, 'span', {}, baselineDistance
                    ? Number(baselineDistance.value).toFixed(2) + ' m loaded route'
                    : 'Loaded-route metric unavailable'),
                element(this.document, 'span', {}, baselinePerShift
                    ? Number(baselinePerShift.value).toFixed(2) + ' m per shift'
                    : 'Per-shift metric unavailable')
            );
            this.designProposalList.appendChild(baseline);
        }
        if (design.error) {
            const errorBox = element(
                this.document,
                'div',
                { className: 'ip-flw-design-error', role: 'alert' },
                ''
            );
            append(errorBox,
                element(this.document, 'strong', {},
                    design.attentionKind === 'ambiguous'
                        ? 'More than one exact target matches'
                        : design.attentionKind === 'stale'
                            ? 'The design source changed'
                            : 'Design request blocked'),
                element(this.document, 'span', {},
                    design.error.message || String(design.error)),
                element(this.document, 'code', {},
                    String(design.error.code || 'facility_design_failed'))
            );
            if (design.attentionRefs.length) {
                const candidates = element(this.document, 'div', {
                    className: 'ip-flw-design-error-targets',
                    'aria-label': 'Affected Facility entities',
                });
                design.attentionRefs.forEach(function (ref) {
                    candidates.appendChild(element(this.document, 'span', {
                        className: 'ip-flw-design-chip',
                        'data-design-attention-entity': ref.entityId,
                    }, this._designEntityLabel(ref)));
                }, this);
                errorBox.appendChild(candidates);
            }
            this.designProposalList.appendChild(errorBox);
        } else if (design.busy) {
            this.designProposalList.appendChild(element(
                this.document,
                'div',
                { className: 'ip-flw-design-empty', role: 'status' },
                'Measuring the baseline and bounded alternatives...'
            ));
        } else if (!design.proposals.length) {
            this.designProposalList.appendChild(element(
                this.document,
                'div',
                { className: 'ip-flw-design-empty' },
                noImprovement
                    ? 'No objective-improved alternative was found in the reviewed bounded candidate set. No geometry was changed.'
                    : 'No measured alternatives yet.'
            ));
        }
        design.proposals.forEach(function (proposal, index) {
            const selected = design.selectedProposal
                && design.selectedProposal.proposalId === proposal.proposalId;
            const option = element(this.document, 'div', {
                className: 'ip-flw-design-proposal',
                'data-selected': selected ? 'true' : 'false',
            });
            const choose = element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-design-proposal-select',
                role: 'radio',
                'aria-checked': selected ? 'true' : 'false',
                'data-design-action': 'select',
                'data-proposal-id': proposal.proposalId,
                title: 'Select this exact measured proposal',
            });
            const distance = (proposal.metrics || []).find(function (metric) {
                return metric.metricId === 'loadedRouteDistanceMeters';
            });
            const moved = (proposal.metrics || []).find(function (metric) {
                return metric.metricId === 'movedPlacementCount';
            });
            append(choose,
                element(this.document, 'strong', {},
                    (proposal.classification
                        && proposal.classification.preferred)
                        ? 'Preferred alternative'
                        : 'Alternative ' + (index + 1)),
                element(this.document, 'span', {}, distance
                    ? Number(distance.value).toFixed(2) + ' m loaded route'
                    : 'Route metric unavailable'),
                element(this.document, 'span', {}, moved
                    ? Number(moved.value).toFixed(0) + ' equipment moves'
                    : 'Disruption metric unavailable')
            );
            option.appendChild(choose);
            if (selected
                    && this.capabilities.designLoopApply
                    && this.capabilities.agentWrite) {
                const apply = element(this.document, 'button', {
                    type: 'button',
                    className: 'ip-flw-design-apply',
                    'data-design-action': 'apply',
                    disabled: design.busy,
                }, 'Apply unsaved');
                option.appendChild(apply);
            }
            this.designProposalList.appendChild(option);
        }, this);
        if (design.selectedProposal && design.proposalPreviewVisible) {
            [
                ['changed', 'Changed geometry'],
                ['preserved', 'Locked and preserved'],
            ].forEach(function (item) {
                this.designLegend.appendChild(element(this.document, 'span', {
                    'data-design-legend': item[0],
                }, item[1]));
            }, this);
        }
    };

    Workspace.prototype._nextDesignTurnRef = function () {
        this.designTurnSequence += 1;
        return 'facility-design-turn-' + Date.now().toString(36)
            + '-' + this.designTurnSequence.toString(36);
    };

    Workspace.prototype._assertCurrentDesignGeneration = function (generation) {
        if (generation === this.designPreviewGeneration) return;
        const error = new Error('Facility design work was superseded by a newer correction');
        error.code = 'facility_design_preview_superseded';
        throw error;
    };

    Workspace.prototype._clearDesignAttention = function () {
        const frame = this.designAttentionSelectionFrame;
        this.designAttentionSelectionFrame = null;
        this.designState.attentionKind = null;
        this.designState.attentionRefs = [];
        if (frame && this.session
                && typeof this.session.selectMany === 'function') {
            this.session.selectMany(frame);
        }
    };

    Workspace.prototype._setDesignError = function (error) {
        const details = error && error.details && typeof error.details === 'object'
            ? error.details : {};
        const candidates = Array.isArray(details.candidates)
            ? details.candidates : [];
        const code = String(error && error.code || 'facility_design_failed');
        let kind = 'blocked';
        let refs = candidates.filter(function (candidate) {
            return candidate && candidate.entityKind && candidate.entityId;
        }).map(function (candidate) {
            return {
                entityKind: candidate.entityKind,
                entityId: candidate.entityId,
            };
        });
        if (refs.length || code.includes('ambiguous')) {
            kind = 'ambiguous';
        } else if (/(?:stale|revision|base_scope|source_changed|mismatch)/.test(code)) {
            kind = 'stale';
            const body = this.designState.brief
                && this.designState.brief.semanticBody || {};
            refs = (body.objective && body.objective.targetRefs || []).concat(
                (body.hardConstraints || []).filter(function (constraint) {
                    return constraint.status === 'active';
                }).flatMap(function (constraint) {
                    return constraint.targetRefs || [];
                })
            );
        }
        const unique = new Map();
        refs.forEach(function (ref) {
            const key = String(ref.entityKind) + ':' + String(ref.entityId);
            if (!unique.has(key)) unique.set(key, clone(ref));
        });
        this.designState.error = error;
        this.designState.attentionKind = kind;
        this.designState.attentionRefs = Array.from(unique.values());
        if (this.designState.attentionRefs.length
                && this.session
                && typeof this.session.selectMany === 'function') {
            if (!this.designAttentionSelectionFrame) {
                const state = this.session.getState();
                this.designAttentionSelectionFrame = clone(state.selection || []);
            }
            this.session.selectMany(this.designState.attentionRefs.map(function (ref) {
                return ref.entityId;
            }));
        }
    };

    Workspace.prototype.showConstructionPreview = async function (summary) {
        if (!this.capabilities.constructionPreview || !this.designTransport) {
            throw new Error('Sage construction previews are not enabled');
        }
        const before = this.session.getState();
        const token = {};
        this.constructionRequest = token;
        if (this.assetBrowserState.open) this.closeAssetBrowser(false);
        if (before.dirty || before.busy || before.history.length || before.draftRevision !== summary.baseRevision) {
            throw new Error('The construction base changed. Existing edits were not changed.');
        }
        const proposal = await this.designTransport.getConstructionPreview(summary.proposalId);
        const current = this.session.getState();
        if (this.constructionRequest !== token || current.editorGenerationId !== before.editorGenerationId
                || current.draftRevision !== proposal.baseRevision
                || proposal.candidateRevision !== summary.candidateRevision) {
            throw new Error('A newer editor state superseded this construction preview');
        }
        this.constructionPreview = {proposal: proposal, frame: before, busy: false, error: null, partial: summary.partial === true,
            requestId: 'apply-' + proposal.proposalId.slice(4, 36) + '-' + before.editorGenerationId};
        this.root.setAttribute('data-construction-preview', 'true');
        this.designState.collapsed = false;
        this._renderDesignPanel();
        this._syncController();
        return {proposalId: proposal.proposalId, candidateRevision: proposal.candidateRevision, editorChanged: false};
    };

    Workspace.prototype.dismissConstructionPreview = function () {
        if (this.constructionPreview && this.constructionPreview.busy) return;
        this.constructionPreview = null;
        this.constructionRequest = null;
        this.root.removeAttribute('data-construction-preview');
        this._syncDesignProposalPreview(false);
        this._renderDesignPanel();
        this._syncController();
    };

    Workspace.prototype.applyConstructionPreview = async function () {
        const review = this.constructionPreview;
        if (!review || review.busy || review.partial || !this.capabilities.constructionApply || !this.capabilities.agentWrite) {
            throw new Error('Construction application is unavailable');
        }
        if (this.session.getState().editorGenerationId !== review.frame.editorGenerationId) {
            throw new Error('The editor changed; request another construction preview');
        }
        review.busy = true;
        review.error = null;
        this._renderDesignPanel();
        try {
            const approval = await this.designTransport.approveConstructionPreview(review.proposal.proposalId, {
                requestId: review.requestId, editorGenerationId: review.frame.editorGenerationId,
                expectedDraftRevision: review.frame.draftRevision, candidateRevision: review.proposal.candidateRevision,
            });
            const result = await this.session.installConstructionApproval(approval);
            review.busy = false;
            this.dismissConstructionPreview();
            return result;
        } catch (error) {
            review.error = error.message;
            throw error;
        } finally {
            review.busy = false;
            this._renderDesignPanel();
        }
    };

    Workspace.prototype._renderConstructionPreview = function () {
        const review = this.constructionPreview;
        this.designPanel.hidden = false;
        this.designPanelBody.hidden = true;
        this.designPanel.setAttribute('data-collapsed', this.designState.collapsed ? 'true' : 'false');
        this.root.setAttribute('data-design-pane-open', this.designState.collapsed ? 'collapsed' : 'true');
        this.designPanelToggle.textContent = this.designState.collapsed ? '<' : '>';
        this.designPanelTitle.querySelector('strong').textContent = 'Sage construction';
        this.designPanelTitle.querySelector('.ip-flw-design-status').textContent = review.busy ? 'Applying' : review.partial ? 'Partial preview' : 'Preview only';
        if (!this.constructionPanelBody) {
            this.constructionPanelBody = element(this.document, 'div', {className: 'ip-flw-design-body ip-flw-construction-body'});
            this.designPanel.appendChild(this.constructionPanelBody);
        }
        const body = this.constructionPanelBody;
        body.hidden = this.designState.collapsed;
        while (body.firstChild) body.removeChild(body.firstChild);
        const proposal = review.proposal;
        append(body, element(this.document, 'strong', {}, proposal.commandCount + ' construction steps'),
            element(this.document, 'p', {}, proposal.candidateLayout.placements.length + ' placements; '
                + proposal.candidateLayout.zones.length + ' zones in the candidate.'),
            element(this.document, 'p', {className: 'ip-flw-design-qualification'}, proposal.validationScope));
        const state = this.session.getState();
        const stale = state.editorGenerationId !== review.frame.editorGenerationId;
        const apply = element(this.document, 'button', {type: 'button', 'data-construction-action': 'apply',
            disabled: review.busy || stale || review.partial || !this.capabilities.constructionApply || !this.capabilities.agentWrite},
            'Apply to unsaved draft');
        apply.addEventListener('click', function () { this.applyConstructionPreview().catch(function () {}); }.bind(this));
        const dismiss = element(this.document, 'button', {type: 'button', 'data-construction-action': 'dismiss',
            disabled: review.busy}, 'Dismiss');
        dismiss.addEventListener('click', this.dismissConstructionPreview.bind(this));
        const actions = element(this.document, 'div', {className: 'ip-flw-construction-actions'});
        append(actions, apply, dismiss);
        append(body, actions);
        if (review.partial) append(body, element(this.document, 'p', {role: 'alert'}, 'A later construction step failed. This partial candidate cannot be applied.'));
        if (review.error || stale) append(body, element(this.document, 'p', {role: 'alert'},
            review.error || 'The editor changed. Request another preview.'));
    };

    Workspace.prototype._syncDesignProposalPreview = function (visible) {
        const descriptor = visible
            ? designProposalPreviewDescriptor(
                this.state && this.state.layout,
                this.designState.selectedProposal,
                this.designState.brief
            )
            : null;
        [this.topAdapter, this.threeAdapter].filter(Boolean).forEach(
            function (adapter) {
                if (typeof adapter.setProposalPreview === 'function') {
                    adapter.setProposalPreview(descriptor);
                }
            }
        );
        this.designState.proposalPreviewVisible = Boolean(descriptor);
        return descriptor;
    };

    Workspace.prototype.getDesignReference = function () {
        const design = this.designState;
        if (!design.brief) return null;
        const result = {
            briefId: design.brief.briefId,
            briefRevision: design.brief.briefRevision,
        };
        if (design.run && design.run.runId && design.run.runRevision) {
            result.runId = design.run.runId;
            result.runRevision = design.run.runRevision;
        }
        if (design.selectedProposal) {
            result.selectedProposal = {
                proposalId: design.selectedProposal.proposalId,
                proposalRevision: design.selectedProposal.proposalRevision,
            };
        }
        const sessionState = this.session.getState();
        if (sessionState.designProposalDraft) {
            result.transactionId =
                sessionState.designProposalDraft.transactionId;
            result.transactionRevision =
                sessionState.designProposalDraft.transactionRevision;
        }
        return result;
    };

    Workspace.prototype.updateDesignBriefFromIntent = async function (intent) {
        if (!this.designTransport) {
            throw new Error('Facility design transport is not configured');
        }
        if (!this.capabilities.designLoopPreview) {
            const error = new Error('Facility design preview is disabled');
            error.code = 'facility_feature_disabled';
            throw error;
        }
        const generation = ++this.designPreviewGeneration;
        const priorRunId = this.designState.run && this.designState.run.runId;
        this._clearDesignAttention();
        this._syncDesignProposalPreview(false);
        this.designState.active = true;
        this.designState.collapsed = false;
        this.designState.busy = true;
        this.designState.error = null;
        this._renderDesignPanel();
        try {
            if (priorRunId && typeof this.designTransport.cancelDesignPreview === 'function') {
                await this.designTransport.cancelDesignPreview({ runId: priorRunId });
                this._assertCurrentDesignGeneration(generation);
            }
            const sourceTurnRef = this._nextDesignTurnRef();
            let result;
            if (!this.designState.brief) {
                result = await this.designTransport.createDesignBrief({
                    workspaceId: 'workspace-facility-layout',
                    editorFrame: this.session.captureDesignEditorFrame(),
                    semanticIntent: clone(intent),
                    sourceTurnRef: sourceTurnRef,
                });
            } else {
                const exactIntent = Object.assign({}, clone(intent), {
                    brief_id: this.designState.brief.briefId,
                    expected_brief_revision:
                        this.designState.brief.briefRevision,
                });
                result = await this.designTransport.updateDesignBrief({
                    briefId: this.designState.brief.briefId,
                    semanticIntent: exactIntent,
                    sourceTurnRef: sourceTurnRef,
                });
            }
            this._assertCurrentDesignGeneration(generation);
            this.designState.brief = clone(result.brief);
            this.designState.run = null;
            this.designState.baseline = null;
            this.designState.proposals = [];
            this.designState.selectedProposal = null;
            this.designState.transaction = null;
            this.designState.status = 'brief_ready';
            this.designState.error = null;
            return clone(result);
        } catch (error) {
            if (generation === this.designPreviewGeneration) {
                this._setDesignError(error);
                this.designState.status = 'blocked';
            }
            throw error;
        } finally {
            if (generation === this.designPreviewGeneration) {
                this.designState.busy = false;
                this._renderDesignPanel();
            }
        }
    };

    Workspace.prototype.runDesignPreview = async function (request) {
        if (!this.designState.brief || !this.designTransport) {
            throw new Error('Create a Facility design brief before previewing it');
        }
        const generation = ++this.designPreviewGeneration;
        this._clearDesignAttention();
        this._syncDesignProposalPreview(false);
        this.designState.active = true;
        this.designState.collapsed = false;
        this.designState.busy = true;
        this.designState.error = null;
        this.designState.lastPreviewStartedAt = Date.now();
        this._renderDesignPanel();
        try {
            const input = request || {};
            let summary;
            if (this.designState.run
                    && this.designState.run.briefRevision
                        === this.designState.brief.briefRevision
                    && input.run_id === this.designState.run.runId) {
                summary = await this.designTransport.continueDesignPreview({
                    runId: this.designState.run.runId,
                    maximumToolCalls: 10,
                });
            } else {
                summary = await this.designTransport.startDesignPreview({
                    briefId: this.designState.brief.briefId,
                    briefRevision: this.designState.brief.briefRevision,
                    workspaceId: 'workspace-facility-layout',
                    clientGenerationId: this._nextDesignTurnRef(),
                    mode: input.mode === 'lab' ? 'lab' : 'production_sage',
                });
            }
            this._assertCurrentDesignGeneration(generation);
            let continuationRequests = 0;
            while (summary.continuationRequired) {
                continuationRequests += 1;
                if (continuationRequests > 4) {
                    const error = new Error(
                        'Facility design preview exceeded its browser continuation limit'
                    );
                    error.code = 'facility_design_continuation_limit_exceeded';
                    throw error;
                }
                summary = await this.designTransport.continueDesignPreview({
                    runId: summary.runId,
                    maximumToolCalls: 10,
                });
                this._assertCurrentDesignGeneration(generation);
            }
            const proposals = [];
            for (const ref of summary.proposalRefs || []) {
                const inspected = await this.designTransport.inspectDesignProposal({
                    proposalId: ref.artifactId,
                    proposalRevision: ref.artifactRevision,
                    includeCandidateLayout: true,
                });
                this._assertCurrentDesignGeneration(generation);
                proposals.push({
                    proposalId: inspected.proposal.proposalId,
                    proposalRevision: inspected.proposal.proposalRevision,
                    classification: clone(inspected.proposal.classification),
                    resultLayoutRevision:
                        inspected.proposal.resultLayoutRevision,
                    diffHash: inspected.proposal.diffHash,
                    metrics: clone(inspected.evaluation.metrics || []),
                    candidateLayout: clone(
                        inspected.candidate
                            && inspected.candidate.candidateLayout || null
                    ),
                });
            }
            this.designState.run = clone(summary);
            this.designState.baseline = clone(summary.baseline || null);
            this.designState.proposals = proposals.slice(0, 2);
            this.designState.selectedProposal =
                this.designState.proposals.find(function (proposal) {
                    return proposal.classification
                        && proposal.classification.preferred;
                }) || this.designState.proposals[0] || null;
            this.designState.status = summary.status;
            this.designState.lastPreviewVisibleAt = Date.now();
            this._syncDesignProposalPreview(true);
            return {
                summary: clone(summary),
                proposals: clone(this.designState.proposals),
                selectedProposal: clone(this.designState.selectedProposal),
            };
        } catch (error) {
            if (generation === this.designPreviewGeneration) {
                this._setDesignError(error);
                this.designState.status = 'blocked';
            }
            throw error;
        } finally {
            if (generation === this.designPreviewGeneration) {
                this.designState.busy = false;
                this._renderDesignPanel();
            }
        }
    };

    Workspace.prototype.inspectDesignBrief = async function () {
        if (!this.designState.brief || !this.designTransport) {
            throw new Error('No active Facility design brief');
        }
        const result = await this.designTransport.inspectDesignBrief({
            briefId: this.designState.brief.briefId,
            briefRevision: this.designState.brief.briefRevision,
        });
        this.designState.brief = clone(result.brief);
        this.designState.active = true;
        this._renderDesignPanel();
        return clone(result);
    };

    Workspace.prototype.selectDesignProposal = function (proposalId) {
        const selected = this.designState.proposals.find(function (proposal) {
            return proposal.proposalId === proposalId;
        });
        if (!selected) throw new Error('Unknown Facility design proposal');
        this.designState.selectedProposal = selected;
        this._syncDesignProposalPreview(true);
        this._renderDesignPanel();
        return clone(selected);
    };

    Workspace.prototype.applySelectedDesignProposal = async function () {
        const selected = this.designState.selectedProposal;
        if (!selected) throw new Error('Select one exact Facility design proposal');
        if (!this.capabilities.designLoopApply || !this.capabilities.agentWrite) {
            const error = new Error('Facility design proposal application is disabled');
            error.code = 'facility_feature_disabled';
            throw error;
        }
        this.designState.busy = true;
        this.designState.error = null;
        this._clearDesignAttention();
        this._syncDesignProposalPreview(false);
        this._renderDesignPanel();
        try {
            const state = await this.session.applyDesignProposal(selected);
            this.designState.transaction = clone(state.designProposalDraft);
            this.designState.status = 'unsaved_draft';
            return clone(state);
        } catch (error) {
            this._setDesignError(error);
            this._syncDesignProposalPreview(true);
            throw error;
        } finally {
            this.designState.busy = false;
            this._renderDesignPanel();
        }
    };

    Workspace.prototype.undoDesignProposal = async function () {
        this.designState.busy = true;
        this.designState.error = null;
        this._clearDesignAttention();
        this._syncDesignProposalPreview(false);
        this._renderDesignPanel();
        try {
            const state = await this.session.undoDesignProposal();
            this.designState.transaction = null;
            this.designState.status = this.designState.proposals.length
                ? 'preview_ready' : 'brief_ready';
            return clone(state);
        } catch (error) {
            this._setDesignError(error);
            throw error;
        } finally {
            this.designState.busy = false;
            this._renderDesignPanel();
        }
    };

    Workspace.prototype._handleDesignPanelClick = function (event) {
        const target = event.target && event.target.closest
            ? event.target.closest('[data-design-action]') : null;
        if (!target) return;
        const action = target.getAttribute('data-design-action');
        if (action === 'toggle') {
            this.designState.collapsed = !this.designState.collapsed;
            this._renderDesignPanel();
        } else if (action === 'select') {
            this.selectDesignProposal(target.getAttribute('data-proposal-id'));
        } else if (action === 'apply') {
            this._invoke('Apply Facility design proposal', function () {
                return this.applySelectedDesignProposal();
            }.bind(this));
        }
    };

    Workspace.prototype._build = function () {
        clearElement(this.root);
        setClassToken(this.root, 'ip-flw-root', true);
        setClassToken(
            this.root,
            'ip-flw-external-command-surface',
            this.externalCommandSurface
        );
        this.root.setAttribute('data-facility-workspace', '');
        this.root.setAttribute('aria-label', 'Facility layout workspace');
        if (this.externalCommandSurface && this.root.style) {
            this.root.style.setProperty('--ip-flw-toolbar-height', '0px');
            this.root.style.gridTemplateRows =
                'minmax(0, 1fr) var(--ip-flw-status-height)';
        }

        this.toolbar = element(this.document, 'div', {
            className: 'ip-flw-toolbar',
            role: 'toolbar',
            'aria-label': 'Facility layout tools',
            hidden: this.externalCommandSurface,
            'aria-hidden': this.externalCommandSurface ? 'true' : 'false',
            style: this.externalCommandSurface ? 'display:none' : '',
        });
        [
            ['assets', 'Assets', ''],
            ['select', 'Select', 'V'],
            ['pan', 'Pan', 'H'],
            ['rectangle-zone', 'Rectangle zone', ''],
            ['polygon-zone', 'Polygon zone', ''],
            ['bulk-zones', 'Bulk zones', ''],
            ['aisle', 'Aisle', ''],
            ['floor-marking', 'Floor marking', 'M'],
            ['rotate', 'Rotate 90', 'R'],
            ['duplicate', 'Duplicate', 'Ctrl+D or Ctrl+drag'],
            ['delete', 'Delete', 'Delete'],
            ['lock', 'Lock', 'L'],
            ['appearance', 'Appearance', ''],
            ['decals', 'Decals', ''],
            ['lettering', 'Wall Lettering', ''],
            ['component-materials', 'Component Materials', ''],
            ['interior-walls', 'Interior Walls', ''],
            ['floor-surfaces', 'Floor Surfaces', ''],
            ['replace-asset', 'Replace Asset', ''],
            ['align', 'Align', ''],
            ['distribute', 'Distribute', ''],
            ['relative', 'Relative', ''],
            ['distance', 'Distance', ''],
            ['offset', 'Offset', ''],
            ['linear-pattern', 'Linear Pattern', ''],
            ['circular-pattern', 'Circular Pattern', ''],
            ['perimeter-pattern', 'Perimeter Pattern', ''],
            ['cell-layout', 'Cell Layout', ''],
            ['create-cell-group', 'Create Cell', ''],
            ['ungroup-cell', 'Ungroup Cell', ''],
            ['vertical-stack', 'Stack', ''],
            ['surface-stack', 'On Surface', ''],
            ['mirror', 'Mirror', ''],
            ['swap', 'Swap Positions', ''],
            ['undo', 'Undo', 'Ctrl+Z'],
            ['redo', 'Redo', 'Ctrl+Y'],
            ['fit', 'Fit Facility', 'F'],
            ['fit-layout', 'Fit Layout', 'Shift+F'],
            ['top-view', 'Top View', 'T'],
            ['auto-arrange', 'Auto Arrange', ''],
            ['saved-movement', 'Saved movement', ''],
            ['clear-all', 'Clear All', ''],
            ['save', 'Save', 'Ctrl+S'],
            ['export-pdf', 'Export PDF', ''],
        ].forEach(function (spec) {
            this.toolbar.appendChild(this._button(spec[0], spec[1], spec[2]));
        }, this);

        this.viewportPane = element(this.document, 'main', {
            className: 'ip-flw-viewport-pane',
        });
        this.viewTabs = element(this.document, 'div', {
            className: 'ip-flw-view-tabs',
            role: 'tablist',
            'aria-label': 'Facility layout view',
        });
        this.planTab = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-view-tab',
            role: 'tab',
            'data-view': 'plan',
            'aria-controls': 'ip-flw-plan-view',
        }, 'Plan');
        this.threeTab = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-view-tab',
            role: 'tab',
            'data-view': '3d',
            'aria-controls': 'ip-flw-three-view',
        }, '3D');
        append(this.viewTabs, this.planTab, this.threeTab);
        this.siteView = siteRuntime && this.session && typeof this.session.setSiteContext === 'function'
            ? siteRuntime.create({ document: this.document, session: this.session,
                onOpenWalls: () => { if (wallsRuntime.canEdit(this)) return wallsRuntime.openDialog(this); } }) : null;
        this.siteTab = null;
        if (this.siteView) {
            this.siteTab = element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-view-tab',
                role: 'tab',
                'data-view': 'site',
                'aria-controls': 'ip-flw-site-view',
                title: 'The layout on its real site: aerial photo, true north up',
            }, 'Site');
            this.siteView.element.hidden = true;
            this.viewTabs.appendChild(this.siteTab);
        }
        if (this.capabilities.generationPlanning && generationView) {
            this.generationPlanningView = generationView.create(this, element);
            const planning = element(this.document, 'button', {type: 'button', title: 'Generation planning',
                className: 'ip-flw-view-tab', 'data-generation-planning': 'open'}, 'Planning');
            planning.addEventListener('click', this.generationPlanningView.open);
            this.viewTabs.appendChild(planning);
        }

        this.viewportStack = element(this.document, 'div', {
            className: 'ip-flw-viewport-stack',
        });
        this.planView = element(this.document, 'div', {
            id: 'ip-flw-plan-view',
            className: 'ip-flw-view ip-flw-plan-view',
            role: 'tabpanel',
            'aria-label': 'Plan view',
            tabindex: '0',
        });
        this.planRulerCorner = element(this.document, 'div', {
            className: 'ip-flw-plan-ruler-corner',
            'aria-hidden': 'true',
        }, 'X/Z');
        this.planTopRuler = element(this.document, 'div', {
            className: 'ip-flw-plan-ruler ip-flw-plan-ruler-top',
            'aria-hidden': 'true',
            'data-plan-overlay': 'top-ruler',
        });
        this.planLeftRuler = element(this.document, 'div', {
            className: 'ip-flw-plan-ruler ip-flw-plan-ruler-left',
            'aria-hidden': 'true',
            'data-plan-overlay': 'left-ruler',
        });
        // Cursor position markers, one per ruler, as a CAD drawing view shows.
        // They repeat what the coordinate readout already states, in the place
        // the eye is already looking while pointing at something.
        this.planTopRulerCursor = element(this.document, 'div', {
            className: 'ip-flw-plan-ruler-cursor',
            'data-ruler-axis': 'x',
            'aria-hidden': 'true',
            hidden: true,
        });
        this.planLeftRulerCursor = element(this.document, 'div', {
            className: 'ip-flw-plan-ruler-cursor',
            'data-ruler-axis': 'z',
            'aria-hidden': 'true',
            hidden: true,
        });
        this.planScaleBar = element(this.document, 'div', {
            className: 'ip-flw-plan-scale',
            'aria-label': 'Plan scale',
            'data-plan-overlay': 'scale',
            'data-plan-settings-trigger': 'scaleDistanceMeters',
            role: 'button',
            tabindex: '0',
            title: 'Double-click to set the Plan scale',
        });
        this.planScaleLabel = element(this.document, 'div', {
            className: 'ip-flw-plan-scale-label',
        });
        this.planScaleTrack = element(this.document, 'div', {
            className: 'ip-flw-plan-scale-track',
            'aria-hidden': 'true',
        });
        append(this.planScaleBar, this.planScaleLabel, this.planScaleTrack);
        this.planCompass = element(this.document, 'div', {
            className: 'ip-flw-plan-compass',
            role: 'img',
            'aria-label': 'Facility orientation: north is positive Z and east is positive X',
            title: 'Facility orientation',
            'data-plan-overlay': 'compass',
        });
        [
            ['north', 'N'],
            ['east', 'E'],
            ['south', 'S'],
            ['west', 'W'],
            ['center', '+'],
        ].forEach(function (item) {
            this.planCompass.appendChild(element(this.document, 'span', {
                'data-compass-direction': item[0],
                'aria-hidden': 'true',
            }, item[1]));
        }, this);
        this.planNavigation = element(this.document, 'div', {
            className: 'ip-flw-plan-navigation',
            role: 'toolbar',
            'aria-label': 'Plan viewport navigation',
            'data-plan-overlay': 'navigation',
        });
        [
            // [command, label, shortcut, viewerIconKind, flatFallbackFile].
            // The kinds are the same rich CAD icons the 3D toolbar renders;
            // the fallback file is only used if that factory is unavailable.
            // A null kind keeps the glyph as the face: the unit control shows
            // its current value rather than an action.
            ['select', 'Select and move assets', 'V', 'pointer', 'cursor-click'],
            ['pan', 'Pan the Plan view', 'H', 'pan', 'hand'],
            ['zoom-out', 'Zoom out', '-', 'zoom-out', 'magnifying-glass-minus'],
            ['zoom-in', 'Zoom in', '+', 'zoom-in', 'magnifying-glass-plus'],
            ['fit-facility', 'Fit facility', 'F', 'zoomfit', 'corners-out'],
            ['fit-layout', 'Fit placed assets', 'L', 'zoom-window', 'bounding-box'],
            ['reset-view', 'Reset Plan view', 'R', 'reset', 'arrow-clockwise'],
            ['grid', 'Show grid', 'G', 'grid-lines', 'grid-four'],
            ['snap', 'Snap to grid', '#', 'snap-grid', 'cell-layout'],
            // The viewer set's 'grid' kind draws stacked sheets, which is the
            // layers metaphor; its name is a legacy of the 3D toolbar.
            ['layers', 'Layer visibility', 'L', 'grid', 'copy'],
            ['unit', 'Display distances in feet', 'm', null, null],
        ].forEach(function (item) {
            this.planNavigation.appendChild(this._planNavigationButton(
                item[0], item[1], item[2], item[3], item[4]
            ));
        }, this);
        append(
            this.planView,
            this.planRulerCorner,
            this.planTopRuler,
            this.planLeftRuler,
            this.planScaleBar,
            this.planCompass,
            this.planNavigation
        );
        this.threeView = element(this.document, 'div', {
            id: 'ip-flw-three-view',
            className: 'ip-flw-view ip-flw-three-view',
            role: 'tabpanel',
            'aria-label': '3D view',
            tabindex: '0',
        });
        this.threeNavigation = element(this.document, 'div', {
            className: 'ip-flw-three-navigation',
            role: 'toolbar',
            'aria-label': '3D viewport navigation',
            'data-three-overlay': 'navigation',
        });
        this.threeCompass = element(this.document, 'div', {
            className: 'ip-flw-three-compass',
            role: 'img',
            'aria-label': 'Facility orientation: north is positive Z and east is positive X',
            title: 'Facility orientation',
            'data-three-overlay': 'compass',
            'data-heading-degrees': '0.0',
            'data-heading-cardinal': 'north',
        });
        this.threeCompassRing = element(this.document, 'div', {
            className: 'ip-flw-three-compass-ring',
            'aria-hidden': 'true',
        });
        [
            ['north', 'N'],
            ['east', 'E'],
            ['south', 'S'],
            ['west', 'W'],
            ['center', '+'],
        ].forEach(function (item) {
            this.threeCompassRing.appendChild(element(this.document, 'span', {
                'data-compass-direction': item[0],
            }, item[1]));
        }, this);
        this.threeCompass.appendChild(this.threeCompassRing);
        [
            ['fit-layout', 'Fit placed equipment', 'zoomfit', false],
            ['zoom-out', 'Zoom out', 'zoom-out', false],
            ['zoom-in', 'Zoom in', 'zoom-in', false],
            ['pan', 'Pan view', 'pan', true],
        ].forEach(function (item) {
            this.threeNavigation.appendChild(this._threeNavigationButton(
                item[0], item[1], item[2], item[3]
            ));
        }, this);
        this.threeNavigation.appendChild(
            this._threeViewOrientationControl()
        );
        [
            ['display-settings', 'Display settings', 'display', false],
            ['appearance', 'Object appearance', 'display', false],
            ['layers', 'Layer visibility', 'stack', false],
            ['orbit', 'Orbit view', 'orbit', true],
            [
                'walkthrough',
                'Walk through facility at human height',
                'walkthrough',
                false,
            ],
            ['avatar-view', 'Show avatar in Walkthrough (C)', 'avatar-view', false],
            [
                'drone',
                'Fly through facility in assisted Drone mode',
                'drone',
                false,
            ],
            [
                'switch-immersive',
                'Switch between Walkthrough and Drone mode (G)',
                'switch-immersive',
                false,
            ],
            [
                'walk-to-selected',
                'Walk to selected equipment',
                'walk-to-selected',
                false,
            ],
        ].forEach(function (item) {
            this.threeNavigation.appendChild(this._threeNavigationButton(
                item[0], item[1], item[2], item[3]
            ));
        }, this);
        if (root.InspectorProWalkthroughCamera && this.document.defaultView) {
            const button = this._threeNavigationButton('camera-settings',
                'Walkthrough camera settings', 'settings', false);
            this.threeNavigation.appendChild(button);
            this.walkCameraControl = root.InspectorProWalkthroughCamera.createControl({
                document: this.document, button,
                onOpen: () => {
                    if (this.threeAdapter && this.threeAdapter.setWalkthroughCameraSettings)
                        this.threeAdapter.setWalkthroughCameraSettings(root.InspectorProWalkthroughCamera.load());
                },
                onChange: value => {
                    if (!this.threeAdapter || !this.threeAdapter.setWalkthroughCameraSettings) return;
                    this.threeAdapter.setWalkthroughCameraSettings(value);
                    this.threeAdapter.setWalkthroughCameraMode('third-person');
                },
            });
        }
        this.threeNavigation.appendChild(this._threeViewpointsControl());
        [
            ['record', 'Record facility view', 'record', true],
            ['fit-facility', 'Fit facility floor', 'reset', false],
            ['grid', 'Hide floor grid', 'grid', false],
        ].forEach(function (item) {
            this.threeNavigation.appendChild(this._threeNavigationButton(
                item[0], item[1], item[2], item[3]
            ));
        }, this);
        this.threeWalkthroughHud = element(this.document, 'div', {
            className: 'ip-flw-walkthrough-hud',
            role: 'status',
            'aria-live': 'polite',
            'aria-label': 'Walkthrough controls: W A S D move, click the floor target to navigate, Shift moves faster, G switches to Drone mode, Escape returns to overview',
            hidden: true,
        });
        this.threeWalkthroughTitle = element(this.document, 'span', {
            className: 'ip-flw-walkthrough-title',
        }, 'Walkthrough');
        const walkthroughKeys = element(this.document, 'span', {
            className: 'ip-flw-walkthrough-keys',
            'aria-hidden': 'true',
        });
        ['W', 'A', 'S', 'D', 'Shift', 'G Fly', 'Esc'].forEach(function (key) {
            walkthroughKeys.appendChild(element(this.document, 'kbd', {}, key));
        }, this);
        walkthroughKeys.appendChild(element(this.document, 'span', {
            className: 'ip-flw-walkthrough-click-hint',
        }, 'Click floor to move'));
        this.threeWalkthroughCrosshair = element(this.document, 'div', {
            className: 'ip-flw-walkthrough-crosshair',
            'aria-hidden': 'true',
            hidden: true,
        });
        this.threeDroneHud = element(this.document, 'div', {
            className: 'ip-flw-drone-hud',
            role: 'status',
            'aria-live': 'polite',
            'aria-label': 'Drone controls: W A S D fly, Space ascends, Control descends, Shift boosts, G switches to Walkthrough mode, Escape returns to overview',
            hidden: true,
        });
        this.threeDroneTitle = element(this.document, 'span', {
            className: 'ip-flw-drone-title',
        }, 'Drone');
        this.threeDroneMetrics = element(this.document, 'span', {
            className: 'ip-flw-drone-metrics',
        });
        this.threeDroneAltitude = element(this.document, 'span', {
            className: 'ip-flw-drone-metric',
        }, 'ALT 0.0 m');
        this.threeDroneSpeed = element(this.document, 'span', {
            className: 'ip-flw-drone-metric',
        }, 'SPD 0.0 m/s');
        this.threeDroneObstacle = element(this.document, 'span', {
            className: 'ip-flw-drone-metric',
        }, 'OBS clear');
        append(
            this.threeDroneMetrics,
            this.threeDroneAltitude,
            this.threeDroneSpeed,
            this.threeDroneObstacle
        );
        const droneKeys = element(this.document, 'span', {
            className: 'ip-flw-drone-keys',
            'aria-hidden': 'true',
        });
        ['W', 'A', 'S', 'D', 'Space Up', 'Ctrl Down', 'Shift', 'G Walk', 'Esc']
            .forEach(function (key) {
                droneKeys.appendChild(element(this.document, 'kbd', {}, key));
            }, this);
        this.threeDroneAssist = element(this.document, 'span', {
            className: 'ip-flw-drone-assist',
        }, 'Assisted');
        append(
            this.threeDroneHud,
            this.threeDroneTitle,
            this.threeDroneMetrics,
            droneKeys,
            this.threeDroneAssist
        );
        this._buildWalkthroughContextUi();
        this._buildThreeRecordingUi();
        append(
            this.threeWalkthroughHud,
            this.threeWalkthroughTitle,
            walkthroughKeys
        );
        append(this.threeView,
            this.threeNavigation,
            this.threeCompass,
            this._buildThreeSettingsPanel(),
            this.threeWalkthroughHud,
            this.threeDroneHud,
            this.threeWalkthroughCrosshair,
            this.walkthroughContextPrompt,
            this.walkthroughContextCard,
            this.threeRecordingPanel,
            this.threeRecordingCountdown,
            this.threeRecordingMonitor,
            this.threeRecordingPreview
        );
        this.ghostOverlay = element(this.document, 'div', {
            className: 'ip-flw-ghost',
            hidden: true,
            'aria-hidden': 'true',
        });
        this.advisoryLiveRegion = element(this.document, 'div', {
            className: 'ip-flw-visually-hidden',
            role: 'status',
            'aria-live': 'polite',
            'aria-atomic': 'true',
        });
        this.gestureOverlay = element(this.document, 'div', {
            className: 'ip-flw-gesture-overlay',
            hidden: true,
            'aria-hidden': 'true',
        });
        this._buildFloorMarkingPalette();
        const motionPanel = this._buildMotionPanel();
        append(this.viewportStack,
            this.planView,
            this.threeView,
            this.siteView ? this.siteView.element : null,
            this._buildLayerPanel(),
            this.floorMarkingPalette,
            this.ghostOverlay,
            this.advisoryLiveRegion,
            this.gestureOverlay
        );
        if (motionPanel.getAttribute('data-motion-docked') === 'true') {
            this.options.motionPanelHost.appendChild(motionPanel);
        } else {
            this.viewportStack.appendChild(motionPanel);
        }
        // Hidden until there are placement alternatives to act on. This strip previously
        // carried a permanent advisory line, which kept the warning styling lit over the
        // viewport at all times even when nothing needed attention. Save still performs
        // authoritative server-side validation; only the standing notice is gone.
        this.validationNotice = element(this.document, 'div', {
            className: 'ip-flw-validation-notice',
            role: 'note',
            hidden: true,
        });
        this.candidateControls = element(this.document, 'div', {
            className: 'ip-flw-view-tabs ip-flw-candidate-controls',
            role: 'group',
            'aria-label': 'Authoritative placement alternatives',
            hidden: true,
        });
        this.candidateSummary = element(this.document, 'span', {
            className: 'ip-flw-candidate-summary',
            role: 'status',
            'aria-live': 'polite',
            'aria-atomic': 'true',
        });
        this.proposalReview = element(this.document, 'div', {
            className: 'ip-flw-proposal-review',
            role: 'note',
            'aria-label': 'Full-layout proposal review details',
            hidden: true,
        });
        this.proposalChangeText = element(this.document, 'div', {
            className: 'ip-flw-proposal-review-line',
            'data-proposal-review': 'changes',
        });
        this.proposalBindingText = element(this.document, 'div', {
            className: 'ip-flw-proposal-review-line',
            'data-proposal-review': 'binding',
        });
        this.proposalDiagnosticText = element(this.document, 'div', {
            className: 'ip-flw-proposal-review-line',
            'data-proposal-review': 'diagnostics',
        });
        // Reviewers see the changes and the check result in plain words; the
        // bindings and the full diagnostics stay one click away for engineers.
        this.proposalCheckText = element(this.document, 'div', {
            className: 'ip-flw-proposal-review-line',
            'data-proposal-review': 'checks',
        });
        this.proposalDetails = element(this.document, 'details', {
            className: 'ip-flw-proposal-details',
        });
        append(this.proposalDetails,
            element(this.document, 'summary', {}, 'Technical details'),
            this.proposalBindingText,
            this.proposalDiagnosticText
        );
        this.proposalLegend = element(this.document, 'div', {
            className: 'ip-flw-proposal-legend',
            'aria-label': 'Proposal visual legend',
        });
        [
            ['new', 'New'],
            ['moved', 'Moved'],
            ['before', 'Original position'],
        ].forEach(function (item) {
            const label = element(this.document, 'span', {
                className: 'ip-flw-proposal-legend-item',
            });
            append(label,
                element(this.document, 'span', {
                    className: 'ip-flw-proposal-swatch',
                    'data-proposal-swatch': item[0],
                    'aria-hidden': 'true',
                }),
                element(this.document, 'span', {}, item[1])
            );
            this.proposalLegend.appendChild(label);
        }, this);
        append(this.proposalReview,
            this.proposalChangeText,
            this.proposalCheckText,
            this.proposalLegend,
            this.proposalDetails
        );
        append(this.candidateControls,
            this.candidateSummary,
            this.proposalReview,
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-view-tab',
                'data-candidate-action': 'previous',
                'aria-label': 'Previous placement alternative',
                title: 'Previous placement alternative',
            }, 'Previous'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-view-tab',
                'data-candidate-action': 'next',
                'aria-label': 'Next placement alternative',
                title: 'Next placement alternative',
            }, 'Next'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-view-tab',
                'data-candidate-action': 'accept',
                'aria-label': 'Accept placement alternative',
                title: 'Accept placement alternative',
            }, 'Accept'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-view-tab',
                'data-candidate-action': 'dismiss',
                'aria-label': 'Dismiss placement alternatives',
                title: 'Dismiss placement alternatives',
            }, 'Dismiss')
        );
        this.validationNotice.appendChild(this.candidateControls);
        append(this.viewportPane,
            this.viewTabs,
            this.viewportStack,
            this.validationNotice
        );

        this.propertiesPane = element(this.document, 'aside', {
            className: 'ip-flw-properties',
            'aria-label': 'Selection properties',
        });
        const propertyHeader = element(this.document, 'div', {
            className: 'ip-flw-pane-header',
        });
        append(propertyHeader,
            element(this.document, 'h2', {}, 'Geometry'),
            element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-geometry-toggle',
                'data-geometry-action': 'toggle',
                'aria-label': 'Collapse geometry inspector',
                title: 'Collapse geometry inspector',
            }, '-')
        );
        this.propertiesBody = element(this.document, 'div', {
            className: 'ip-flw-properties-body',
        });
        append(this.propertiesPane, propertyHeader, this.propertiesBody);
        this._buildDesignPanel();

        this.statusBar = element(this.document, 'div', {
            className: 'ip-flw-statusbar',
        });
        this.statusText = element(this.document, 'div', {
            className: 'ip-flw-status',
            role: 'status',
            'aria-live': 'polite',
        });
        this.coordinateText = element(this.document, 'div', {
            className: 'ip-flw-coordinates',
            'aria-label': 'Pointer world coordinates',
        }, 'Cursor: X 0 ' + this.planPreferences.unit
            + '  Z 0 ' + this.planPreferences.unit);
        append(this.statusBar, this.statusText, this.coordinateText);

        this.shell = element(this.document, 'div', {
            className: 'ip-flw-shell',
        });
        append(
            this.shell,
            this.viewportPane,
            this.propertiesPane,
            this.designPanel
        );
        this._buildAssetBrowser();
        this._buildPrecisionDialog();
        this._buildPatternDialog();
        this._buildPlanSettingsDialog();
        this._buildBulkZoneDialog();
        this._buildCellGroupDialog();
        this._buildAisleDialog();
        this._buildNavigationDialog();
        this._buildClearAllDialog();
        append(
            this.root,
            this.toolbar,
            this.shell,
            this.assetBrowser,
            this.precisionDialog,
            this.patternDialog,
            this.planSettingsDialog,
            this.bulkZoneDialog,
            this.cellGroupDialog,
            this.aisleDialog,
            this.navigationDialog,
            this.clearAllDialog,
            this.statusBar
        );
        this._renderAssetBrowser();
        this._renderPrecisionDialog();
        this._renderPatternDialog();
        this._renderPlanSettingsDialog();
        this._renderAisleDialog();
        this._renderNavigationDialog();
        this._renderMotionPanel();
        this._renderDesignPanel();
        this._setViewMode('plan');
        this._setToolMode('select');
        this._renderThreeNavigationState();
    };

    Workspace.prototype._connectRendering = function () {
        const options = this.options;
        this.topAdapter = options.topAdapter || null;
        if (!this.topAdapter && this.layoutRuntime) {
            this.topAdapter = this.layoutRuntime.createTopPlanAdapter(
                this.planView,
                Object.assign({}, options.topPlanOptions || {}, {
                    assetCatalog: clone(options.assetCatalog || []),
                    displayUnit: this.planPreferences.unit,
                    showGrid: this.planPreferences.showGrid,
                })
            );
            this.createdTopAdapter = true;
        }

        this.threeAdapter = options.threeAdapter || null;
        if (!this.threeAdapter && options.threeRuntime
                && typeof options.threeRuntime.createThreeAdapter === 'function') {
            this.threeAdapter = options.threeRuntime.createThreeAdapter(
                options.threeOptions || {}
            );
            this.createdThreeAdapter = true;
        }
        if (this.threeAdapter && typeof this.threeAdapter.mount === 'function') {
            const diagnostics = typeof this.threeAdapter.getDiagnostics === 'function'
                ? this.threeAdapter.getDiagnostics() : {};
            if (!diagnostics.mounted) this.threeAdapter.mount(this.threeView);
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setNavigationMode === 'function') {
            this.threeAdapter.setNavigationMode(this.threeNavigationMode);
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setWalkthroughStateHandler
                    === 'function') {
            this.threeAdapter.setWalkthroughStateHandler(function (value) {
                this.threeWalkthrough = Object.assign(
                    {},
                    this.threeWalkthrough,
                    value || {}
                );
                if (!this.threeWalkthrough.active
                        && !this.threeDrone.active) {
                    this.walkthroughContextState.focus = null;
                    this.walkthroughContextState.expanded = false;
                    this.walkthroughContextState.pinned = false;
                    this.walkthroughContextState.pinnedPlacementId = null;
                }
                this._renderThreeNavigationState();
            }.bind(this));
        } else if (this.threeAdapter
                && typeof this.threeAdapter.getWalkthroughState === 'function') {
            this.threeWalkthrough = Object.assign(
                {},
                this.threeWalkthrough,
                this.threeAdapter.getWalkthroughState()
            );
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setDroneStateHandler
                    === 'function') {
            this.threeAdapter.setDroneStateHandler(function (value) {
                this.threeDrone = Object.assign(
                    {},
                    this.threeDrone,
                    value || {}
                );
                if (!this.threeDrone.active
                        && !this.threeWalkthrough.active) {
                    this.walkthroughContextState.focus = null;
                    this.walkthroughContextState.expanded = false;
                    this.walkthroughContextState.pinned = false;
                    this.walkthroughContextState.pinnedPlacementId = null;
                }
                this._renderThreeNavigationState();
            }.bind(this));
        } else if (this.threeAdapter
                && typeof this.threeAdapter.getDroneState === 'function') {
            this.threeDrone = Object.assign(
                {},
                this.threeDrone,
                this.threeAdapter.getDroneState()
            );
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setMotionStateHandler
                    === 'function') {
            this.threeAdapter.setMotionStateHandler(
                this._handleMotionState.bind(this)
            );
        } else if (this.threeAdapter
                && typeof this.threeAdapter.getMotionState === 'function') {
            this._handleMotionState(this.threeAdapter.getMotionState());
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setActivityStateHandler
                    === 'function') {
            this.threeAdapter.setActivityStateHandler(
                this._handleActivityState.bind(this)
            );
        } else if (this.threeAdapter
                && typeof this.threeAdapter.getActivityState === 'function') {
            this._handleActivityState(this.threeAdapter.getActivityState());
        }
        if (this.threeAdapter
                && typeof this.threeAdapter
                    .setNavigationPreviewStateHandler === 'function') {
            this.threeAdapter.setNavigationPreviewStateHandler(
                this._handleNavigationPreviewState.bind(this)
            );
        } else if (this.threeAdapter
                && typeof this.threeAdapter.getNavigationPreviewState
                    === 'function') {
            this._handleNavigationPreviewState(
                this.threeAdapter.getNavigationPreviewState()
            );
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setWalkthroughContextHandler
                    === 'function') {
            this.threeAdapter.setWalkthroughContextHandler(function (value) {
                this._setWalkthroughContextFocus(value);
            }.bind(this));
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setCameraOrientationHandler
                    === 'function') {
            this.threeAdapter.setCameraOrientationHandler(function (value) {
                this._renderThreeCompass(value);
            }.bind(this));
        } else if (this.threeAdapter
                && typeof this.threeAdapter.getDiagnostics === 'function') {
            const diagnostics = this.threeAdapter.getDiagnostics();
            this._renderThreeCompass(diagnostics.cameraOrientation);
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setGridVisible === 'function') {
            this.threeAdapter.setGridVisible(this.threeGridVisible);
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setVisualSettings === 'function') {
            this.threeVisualSettings = normalizeThreeVisualSettings(
                this.threeAdapter.setVisualSettings(this.threeVisualSettings)
            );
            this._renderThreeVisualSettings();
        }
        this._applyLayerVisibility();
        // _build() establishes the initial tab state before adapters exist.
        // Reconcile once mounting finishes so a real 3D adapter immediately
        // enables the segmented control.
        this._setViewMode(this.viewMode);

        const adapters = [this.topAdapter, this.threeAdapter].filter(Boolean);
        this.controller = options.controller || this.layoutRuntime.createEditor({
            assetCatalog: clone(options.assetCatalog || []),
            adapters: adapters,
        });
        if (options.controller
                && typeof this.controller.setAssetCatalog === 'function') {
            this.controller.setAssetCatalog(options.assetCatalog || []);
        }
        const selectionHandler = this._handleAdapterSelection.bind(this);
        adapters.forEach(function (adapter) {
            if (typeof adapter.setSelectionHandler === 'function') {
                adapter.setSelectionHandler(selectionHandler);
            }
        });
        if (this.topAdapter
                && typeof this.topAdapter.setViewPreferences === 'function') {
            this.topAdapter.setViewPreferences({
                displayUnit: this.planPreferences.unit,
                showGrid: this.planPreferences.showGrid,
            });
        }
        if (this.topAdapter
                && typeof this.topAdapter.setViewportChangeHandler
                    === 'function') {
            this.topAdapter.setViewportChangeHandler(
                function (snapshot) {
                    this._renderPlanSpatialOverlays(snapshot);
                    if (this.selectionToolbarManager
                            && this.selectionToolbarManager.isOpen()) {
                        this.selectionToolbarManager.reposition();
                    }
                }.bind(this)
            );
        }

        if (typeof options.installPlanMarquee === 'function') {
            const cleanup = options.installPlanMarquee({
                host: this.planView,
                getMode: function () { return this.toolMode; }.bind(this),
                select: this.applyMarqueeSelection.bind(this),
                eventToWorld: this._eventWorld.bind(this),
            });
            this.marqueeCleanup = typeof cleanup === 'function' ? cleanup : null;
        }
    };

    Workspace.prototype._movableDialogBounds = function (dialog) {
        const rootRect = this.root.getBoundingClientRect();
        const boundary = this.shell || this.root;
        const boundaryRect = boundary.getBoundingClientRect();
        const dialogRect = dialog.getBoundingClientRect();
        const padding = 8;
        const rootLeft = finite(rootRect.left, 0);
        const rootTop = finite(rootRect.top, 0);
        const boundaryLeft = finite(boundaryRect.left, rootLeft);
        const boundaryTop = finite(boundaryRect.top, rootTop);
        const boundaryRight = finite(
            boundaryRect.right,
            boundaryLeft + finite(boundaryRect.width, 0)
        );
        const boundaryBottom = finite(
            boundaryRect.bottom,
            boundaryTop + finite(boundaryRect.height, 0)
        );
        const minLeft = boundaryLeft - rootLeft + padding;
        const minTop = boundaryTop - rootTop + padding;
        return {
            minLeft: minLeft,
            minTop: minTop,
            maxLeft: Math.max(
                minLeft,
                boundaryRight - rootLeft - finite(dialogRect.width, 0)
                    - padding
            ),
            maxTop: Math.max(
                minTop,
                boundaryBottom - rootTop - finite(dialogRect.height, 0)
                    - padding
            ),
            rootLeft: rootLeft,
            rootTop: rootTop,
            dialogRect: dialogRect,
        };
    };

    Workspace.prototype._positionMovableDialog = function (
        dialog,
        requestedLeft,
        requestedTop
    ) {
        if (!dialog || !dialog.style) return null;
        const bounds = this._movableDialogBounds(dialog);
        const left = clamp(
            requestedLeft,
            bounds.minLeft,
            bounds.maxLeft,
            bounds.minLeft
        );
        const top = clamp(
            requestedTop,
            bounds.minTop,
            bounds.maxTop,
            bounds.minTop
        );
        dialog.style.left = left + 'px';
        dialog.style.top = top + 'px';
        dialog.style.right = 'auto';
        dialog.setAttribute('data-dialog-left', String(Number(left.toFixed(2))));
        dialog.setAttribute('data-dialog-top', String(Number(top.toFixed(2))));
        return { left: left, top: top };
    };

    Workspace.prototype._finishMovableDialogDrag = function (
        dialog,
        releaseCapture
    ) {
        const drag = this.movableDialogDrag;
        if (!drag || (dialog && drag.dialog !== dialog)) return false;
        this.movableDialogDrag = null;
        drag.dialog.removeAttribute('data-dialog-dragging');
        if (releaseCapture !== false
                && drag.handle
                && typeof drag.handle.hasPointerCapture === 'function'
                && drag.handle.hasPointerCapture(drag.pointerId)
                && typeof drag.handle.releasePointerCapture === 'function') {
            drag.handle.releasePointerCapture(drag.pointerId);
        }
        return true;
    };

    Workspace.prototype._connectMovableDialog = function (dialog, label) {
        if (!dialog) return;
        const handle = dialog.querySelector('.ip-flw-precision-header');
        if (!handle) return;
        const name = String(label || 'command panel');
        handle.setAttribute('data-dialog-drag-handle', 'true');
        handle.setAttribute('tabindex', '0');
        handle.setAttribute('aria-label', 'Move ' + name);
        handle.setAttribute(
            'title',
            'Drag to move. Use arrow keys for precise movement.'
        );
        this._listen(handle, 'pointerdown', function (event) {
            if (finite(event && event.button, 0) !== 0
                    || isDialogDragControl(event && event.target, handle)) {
                return;
            }
            this._finishMovableDialogDrag(null, true);
            const bounds = this._movableDialogBounds(dialog);
            const start = this._positionMovableDialog(
                dialog,
                finite(bounds.dialogRect.left, bounds.rootLeft)
                    - bounds.rootLeft,
                finite(bounds.dialogRect.top, bounds.rootTop)
                    - bounds.rootTop
            );
            if (!start) return;
            const pointerId = finite(event && event.pointerId, 0);
            this.movableDialogDrag = {
                dialog: dialog,
                handle: handle,
                pointerId: pointerId,
                startClientX: finite(event && event.clientX, 0),
                startClientY: finite(event && event.clientY, 0),
                startLeft: start.left,
                startTop: start.top,
            };
            dialog.setAttribute('data-dialog-dragging', 'true');
            if (typeof handle.setPointerCapture === 'function') {
                handle.setPointerCapture(pointerId);
            }
            if (typeof handle.focus === 'function') handle.focus();
            if (event && typeof event.preventDefault === 'function') {
                event.preventDefault();
            }
            if (event && typeof event.stopPropagation === 'function') {
                event.stopPropagation();
            }
        }.bind(this));
        this._listen(handle, 'pointermove', function (event) {
            const drag = this.movableDialogDrag;
            if (!drag || drag.dialog !== dialog
                    || drag.pointerId !== finite(event && event.pointerId, 0)) {
                return;
            }
            this._positionMovableDialog(
                dialog,
                drag.startLeft + finite(event && event.clientX, 0)
                    - drag.startClientX,
                drag.startTop + finite(event && event.clientY, 0)
                    - drag.startClientY
            );
            if (event && typeof event.preventDefault === 'function') {
                event.preventDefault();
            }
            if (event && typeof event.stopPropagation === 'function') {
                event.stopPropagation();
            }
        }.bind(this));
        ['pointerup', 'pointercancel'].forEach(function (type) {
            this._listen(handle, type, function (event) {
                const drag = this.movableDialogDrag;
                if (!drag || drag.dialog !== dialog
                        || drag.pointerId
                            !== finite(event && event.pointerId, 0)) return;
                this._finishMovableDialogDrag(dialog, true);
                if (event && typeof event.preventDefault === 'function') {
                    event.preventDefault();
                }
                if (event && typeof event.stopPropagation === 'function') {
                    event.stopPropagation();
                }
            }.bind(this));
        }, this);
        this._listen(handle, 'lostpointercapture', function () {
            this._finishMovableDialogDrag(dialog, false);
        }.bind(this));
        this._listen(handle, 'keydown', function (event) {
            if (!event || event.target !== handle) return;
            const key = String(event.key || '').toLowerCase();
            const direction = {
                arrowleft: [-1, 0],
                arrowright: [1, 0],
                arrowup: [0, -1],
                arrowdown: [0, 1],
            }[key];
            if (!direction) return;
            const bounds = this._movableDialogBounds(dialog);
            const step = event.shiftKey ? 10 : 2;
            this._positionMovableDialog(
                dialog,
                finite(bounds.dialogRect.left, bounds.rootLeft)
                    - bounds.rootLeft + direction[0] * step,
                finite(bounds.dialogRect.top, bounds.rootTop)
                    - bounds.rootTop + direction[1] * step
            );
            if (typeof event.preventDefault === 'function') {
                event.preventDefault();
            }
            if (typeof event.stopPropagation === 'function') {
                event.stopPropagation();
            }
        }.bind(this));
    };

    Workspace.prototype._connectEvents = function () {
        this._listen(this.toolbar, 'click', this._handleToolbarClick.bind(this));
        this._listen(
            this.planNavigation,
            'click',
            this._handlePlanNavigationClick.bind(this)
        );
        this._listen(
            this.threeNavigation,
            'click',
            this._handleThreeNavigationClick.bind(this)
        );
        this._listen(
            this.threeNavigation,
            'keydown',
            this._handleThreeNavigationKeyDown.bind(this)
        );
        this._listen(
            this.threeSettingsPanel,
            'input',
            this._handleThreeSettingsInput.bind(this)
        );
        this._listen(
            this.threeSettingsPanel,
            'change',
            this._handleThreeSettingsInput.bind(this)
        );
        this._listen(
            this.threeSettingsPanel,
            'click',
            this._handleThreeSettingsClick.bind(this)
        );
        this._listen(
            this.layerPanel,
            'change',
            this._handleLayerPanelInput.bind(this)
        );
        this._listen(
            this.layerPanel,
            'click',
            this._handleLayerPanelClick.bind(this)
        );
        this._listen(
            this.motionPanel,
            'click',
            this._handleMotionClick.bind(this)
        );
        this._listen(
            this.designPanel,
            'click',
            this._handleDesignPanelClick.bind(this)
        );
        this._listen(
            this.motionPanel,
            'input',
            this._handleMotionInput.bind(this)
        );
        this._listen(
            this.motionPanel,
            'change',
            this._handleMotionInput.bind(this)
        );
        ['pointerdown', 'dblclick', 'wheel'].forEach(function (type) {
            this._listen(this.planNavigation, type, function (event) {
                if (typeof event.stopPropagation === 'function') {
                    event.stopPropagation();
                }
            });
        }, this);
        ['pointerdown', 'dblclick', 'wheel'].forEach(function (type) {
            this._listen(this.threeNavigation, type, function (event) {
                if (typeof event.stopPropagation === 'function') {
                    event.stopPropagation();
                }
            });
        }, this);
        ['pointerdown', 'dblclick', 'wheel'].forEach(function (type) {
            this._listen(this.layerPanel, type, function (event) {
                if (typeof event.stopPropagation === 'function') {
                    event.stopPropagation();
                }
            });
        }, this);
        ['pointerdown', 'dblclick', 'wheel'].forEach(function (type) {
            this._listen(this.motionPanel, type, function (event) {
                if (typeof event.stopPropagation === 'function') {
                    event.stopPropagation();
                }
            });
        }, this);
        this._listen(this.viewTabs, 'click', this._handleViewTabClick.bind(this));
        this._listen(
            this.viewTabs,
            'keydown',
            this._handleViewTabKeyDown.bind(this)
        );
        this._listen(this.assetBrowserSearch, 'input', function () {
            this.assetBrowserState.query = this.assetBrowserSearch.value || '';
            this._renderAssetBrowser();
        }.bind(this));
        this._listen(
            this.assetBrowser,
            'click',
            this._handleAssetBrowserClick.bind(this)
        );
        this._listen(
            this.assetBrowser,
            'keydown',
            this._handleAssetBrowserKeyDown.bind(this)
        );
        this._listen(
            this.floorMarkingPalette,
            'click',
            this._handleFloorMarkingPaletteClick.bind(this)
        );
        this._listen(
            this.threeView,
            'click',
            this._handleWalkthroughContextAction.bind(this)
        );
        this._listen(
            this.threeView,
            'click',
            this._handleRecordingAction.bind(this)
        );
        this._listen(
            this.threeRecordingPanel,
            'change',
            this._handleRecordingSetting.bind(this)
        );
        this._listen(
            this.threeView,
            'pointermove',
            this._handleRecordingPointer.bind(this)
        );
        this._listen(this.threeView, 'pointerleave', function () {
            this.recordingCursor.visible = false;
        }.bind(this));
        this._listen(
            this.walkthroughContextMode,
            'change',
            this._handleWalkthroughContextMode.bind(this)
        );
        this._listen(
            this.precisionDialog,
            'click',
            this._handlePrecisionClick.bind(this)
        );
        this._listen(
            this.precisionDialog,
            'input',
            this._handlePrecisionChange.bind(this)
        );
        this._listen(
            this.precisionDialog,
            'change',
            this._handlePrecisionChange.bind(this)
        );
        this._listen(
            this.precisionDialog,
            'keydown',
            this._handlePrecisionKeyDown.bind(this)
        );
        this._listen(
            this.patternDialog,
            'click',
            this._handlePatternClick.bind(this)
        );
        this._listen(
            this.patternDialog,
            'input',
            this._handlePatternChange.bind(this)
        );
        this._listen(
            this.patternDialog,
            'change',
            this._handlePatternChange.bind(this)
        );
        this._listen(
            this.patternDialog,
            'keydown',
            this._handlePatternKeyDown.bind(this)
        );
        this._listen(
            this.planSettingsDialog,
            'click',
            this._handlePlanSettingsClick.bind(this)
        );
        this._listen(
            this.planSettingsDialog,
            'input',
            this._handlePlanSettingsChange.bind(this)
        );
        this._listen(
            this.planSettingsDialog,
            'change',
            this._handlePlanSettingsChange.bind(this)
        );
        this._listen(
            this.planSettingsDialog,
            'keydown',
            this._handlePlanSettingsKeyDown.bind(this)
        );
        this._listen(
            this.clearAllDialog,
            'click',
            this._handleClearAllClick.bind(this)
        );
        this._listen(
            this.clearAllDialog,
            'keydown',
            this._handleClearAllKeyDown.bind(this)
        );
        this._listen(
            this.bulkZoneDialog,
            'click',
            this._handleBulkZoneClick.bind(this)
        );
        this._listen(
            this.bulkZoneDialog,
            'input',
            this._handleBulkZoneChange.bind(this)
        );
        this._listen(
            this.bulkZoneDialog,
            'change',
            this._handleBulkZoneChange.bind(this)
        );
        this._listen(
            this.bulkZoneDialog,
            'keydown',
            this._handleBulkZoneKeyDown.bind(this)
        );
        this._listen(
            this.cellGroupDialog,
            'click',
            this._handleCellGroupClick.bind(this)
        );
        this._listen(
            this.cellGroupDialog,
            'input',
            this._handleCellGroupChange.bind(this)
        );
        this._listen(
            this.cellGroupDialog,
            'change',
            this._handleCellGroupChange.bind(this)
        );
        this._listen(
            this.cellGroupDialog,
            'keydown',
            this._handleCellGroupKeyDown.bind(this)
        );
        this._listen(
            this.aisleDialog,
            'click',
            this._handleAisleClick.bind(this)
        );
        this._listen(
            this.aisleDialog,
            'input',
            this._handleAisleChange.bind(this)
        );
        this._listen(
            this.aisleDialog,
            'change',
            this._handleAisleChange.bind(this)
        );
        this._listen(
            this.aisleDialog,
            'keydown',
            this._handleAisleKeyDown.bind(this)
        );
        this._listen(
            this.navigationDialog,
            'click',
            this._handleNavigationClick.bind(this)
        );
        this._listen(
            this.navigationDialog,
            'input',
            this._handleNavigationChange.bind(this)
        );
        this._listen(
            this.navigationDialog,
            'change',
            this._handleNavigationChange.bind(this)
        );
        this._listen(
            this.navigationDialog,
            'keydown',
            this._handleNavigationKeyDown.bind(this)
        );
        [
            [this.precisionDialog, 'positioning panel'],
            [this.patternDialog, 'pattern panel'],
            [this.planSettingsDialog, 'facility plan settings panel'],
            [this.bulkZoneDialog, 'bulk zone editor'],
            [this.cellGroupDialog, 'manufacturing cell panel'],
            [this.aisleDialog, 'semantic aisle panel'],
            [this.navigationDialog, 'motion path panel'],
            [this.clearAllDialog, 'clear layout confirmation'],
        ].forEach(function (item) {
            this._connectMovableDialog(item[0], item[1]);
        }, this);
        this._listen(this.viewportStack, 'dragover', this._handleDragOver.bind(this));
        this._listen(this.viewportStack, 'drop', this._handleDrop.bind(this));
        this._listen(this.viewportStack, 'dragleave', this._handleDragLeave.bind(this));
        this._listen(
            this.candidateControls,
            'click',
            this._handleCandidateAction.bind(this)
        );
        this._listen(this.planView, 'pointerdown', this._handlePlanPointerDown.bind(this));
        this._listen(this.planView, 'pointermove', this._handlePlanPointerMove.bind(this));
        this._listen(this.planView, 'pointerup', this._handlePlanPointerUp.bind(this));
        this._listen(this.planView, 'pointercancel', this._cancelPointerGesture.bind(this));
        this._listen(this.planView, 'pointerleave', function () {
            this._setRulerCursor(null);
        }.bind(this));
        this._listen(
            this.planView,
            'lostpointercapture',
            this._handleLostPointerCapture.bind(this)
        );
        this._listen(this.planView, 'wheel', this._handlePlanWheel.bind(this), {
            passive: false,
        });
        this._listen(this.planView, 'click', this._handlePlanClick.bind(this));
        this._listen(this.planView, 'dblclick', this._handlePlanDoubleClick.bind(this));
        this._listen(this.planView, 'keydown', this._handlePlanOverlayKeyDown.bind(this));
        this._listen(this.propertiesPane, 'click', function (event) {
            const action = targetDataId(
                event.target,
                'data-geometry-action',
                this.propertiesPane
            );
            if (action !== 'toggle') return;
            this.geometryInspectorCollapsed = !this.geometryInspectorCollapsed;
            this.propertiesPane.setAttribute(
                'data-collapsed',
                this.geometryInspectorCollapsed ? 'true' : 'false'
            );
            const button = this.propertiesPane.querySelector(
                '[data-geometry-action="toggle"]'
            );
            if (button) {
                button.textContent = this.geometryInspectorCollapsed ? '+' : '-';
                button.setAttribute(
                    'aria-label',
                    this.geometryInspectorCollapsed
                        ? 'Expand geometry inspector'
                        : 'Collapse geometry inspector'
                );
            }
        }.bind(this));
        this._listen(this.propertiesBody, 'change', this._handlePropertyChange.bind(this));
        this._listen(this.root, 'keydown', this._handleKeyDown.bind(this));
    };

    Workspace.prototype.openPrecisionDialog = function (mode) {
        if (!PRECISION_MODES.includes(mode)) {
            throw new TypeError('precision positioning mode is unsupported');
        }
        if (this.assetBrowserState.open || this.state.layoutProposal
                || this.state.placementAlternatives) return false;
        if (this.patternState.open) this.closePatternDialog(false);
        if (this.planSettingsState.open) {
            this.closePlanSettingsDialog(false, false);
        }
        const active = this.document.activeElement;
        const activeInToolbar = this.selectionToolbarElement
            && this.selectionToolbarElement.contains(active);
        const selectedCards = activeInToolbar
            ? this._selectionToolbarCards(
                this._selectedPlacementRecords().map(function (placement) {
                    return placement.placementId;
                })
            ) : [];
        this.precisionFocusReturn = selectedCards[0]
            || (active && typeof active.focus === 'function' ? active : null);
        this._closeSelectionToolbar('precision_dialog_opened', false);
        this.precisionState.open = true;
        this.precisionState.mode = mode;
        this.precisionMessage = '';
        this.root.setAttribute('data-precision-open', 'true');
        this._syncPrecisionIdentities();
        if (mode === 'distance' && this.precisionState.referenceId
                && this.precisionState.movingId) {
            try {
                this.precisionState.requestedDistance = measurePlacementDistance(
                    this.state.layout,
                    this.assetCatalog,
                    this.precisionState.referenceId,
                    this.precisionState.movingId,
                    this.precisionState.distanceMode
                );
            } catch (error) {
                this.precisionMessage = error.message;
            }
        }
        this._renderPrecisionDialog();
        this._renderToolbarState();
        const first = this.precisionBody.querySelector(
            '[data-precision-field]'
        );
        if (first && typeof first.focus === 'function') first.focus();
        return true;
    };

    Workspace.prototype.closePrecisionDialog = function (restoreFocus) {
        if (!this.precisionState.open) return false;
        this._finishMovableDialogDrag(this.precisionDialog, true);
        this.precisionState.open = false;
        this.precisionDialog.hidden = true;
        this.root.removeAttribute('data-precision-open');
        this._renderToolbarState();
        const target = this.precisionFocusReturn;
        this.precisionFocusReturn = null;
        if (restoreFocus !== false && target
                && typeof target.focus === 'function') {
            target.focus();
        }
        this._syncSelectionToolbar();
        return true;
    };

    Workspace.prototype._handlePrecisionChange = function (event) {
        const field = targetDataId(
            event.target,
            'data-precision-field',
            this.precisionDialog
        );
        if (!field || !Object.prototype.hasOwnProperty.call(
            this.precisionState,
            field
        )) return;
        const distanceFields = [
            'distributeGap',
            'relativeDistance',
            'requestedDistance',
            'offsetX',
            'offsetZ',
        ];
        if (field === 'createCopies') {
            this.precisionState[field] = event.target.checked === true;
        } else if (distanceFields.includes(field)) {
            const displayValue = finite(event.target.value, NaN);
            if (Number.isFinite(displayValue)) {
                this.precisionState[field] = canonicalDistance(
                    displayValue,
                    this.planPreferences.unit
                );
            }
        } else {
            this.precisionState[field] = String(event.target.value || '');
        }
        if (field === 'referenceId'
                && this.precisionState.movingId
                    === this.precisionState.referenceId) {
            this.precisionState.movingId = '';
        }
        if (event.type === 'change'
                || field === 'createCopies'
                || !distanceFields.includes(field)) {
            this._renderPrecisionDialog();
        }
    };

    Workspace.prototype._handlePrecisionClick = function (event) {
        const mode = targetDataId(
            event.target,
            'data-precision-mode',
            this.precisionDialog
        );
        if (mode && PRECISION_MODES.includes(mode)) {
            this.precisionState.mode = mode;
            this._renderPrecisionDialog();
            return;
        }
        const action = targetDataId(
            event.target,
            'data-precision-action',
            this.precisionDialog
        );
        if (action === 'close' || action === 'cancel') {
            this.closePrecisionDialog(true);
        } else if (action === 'apply') {
            this._applyPrecisionPositioning();
        }
    };

    Workspace.prototype._handlePrecisionKeyDown = function (event) {
        const key = String(event && event.key || '').toLowerCase();
        if (key === 'escape') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this.closePrecisionDialog(true);
        } else if (key === 'enter'
                && event.target !== this.precisionCancel
                && event.target !== this.precisionClose) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._applyPrecisionPositioning();
        }
    };

    Workspace.prototype._applyPrecisionPositioning = function () {
        const placements = this._precisionSelectedPlacements();
        const placementIds = placements.map(function (placement) {
            return placement.placementId;
        });
        const mode = this.precisionState.mode;
        let label = 'Position selection';
        let action = null;
        try {
            if (mode === 'align') {
                const result = buildAlignmentUpdates(
                    this.state.layout,
                    this.assetCatalog,
                    placementIds,
                    this.precisionState.alignMode,
                    this.precisionState.anchorId
                );
                label = 'Align selection';
                action = function () {
                    return this.session.movePlacements(result.updates, label);
                }.bind(this);
            } else if (mode === 'distribute') {
                const result = buildDistributionUpdates(
                    this.state.layout,
                    this.assetCatalog,
                    placementIds,
                    this.precisionState.distributeAxis,
                    this.precisionState.distributeMethod,
                    this.precisionState.distributeGap
                );
                label = 'Distribute selection';
                action = function () {
                    return this.session.movePlacements(result.updates, label);
                }.bind(this);
            } else if (mode === 'relative') {
                const movingIds = placementIds.filter(function (placementId) {
                    return placementId !== this.precisionState.referenceId;
                }, this);
                const result = buildRelativePositionUpdates(
                    this.state.layout,
                    this.assetCatalog,
                    movingIds,
                    this.precisionState.referenceId,
                    this.precisionState.relation,
                    this.precisionState.relativeDistance,
                    this.precisionState.relativeAlignment
                );
                label = 'Position relative to reference';
                action = function () {
                    return this.session.movePlacements(result.updates, label);
                }.bind(this);
            } else if (mode === 'distance') {
                const result = buildDistanceUpdate(
                    this.state.layout,
                    this.assetCatalog,
                    this.precisionState.referenceId,
                    this.precisionState.movingId,
                    this.precisionState.distanceMode,
                    this.precisionState.requestedDistance
                );
                label = 'Set placement distance';
                action = function () {
                    return this.session.movePlacements(result.updates, label);
                }.bind(this);
            } else {
                const delta = {
                    x: this.precisionState.offsetX,
                    y: 0,
                    z: this.precisionState.offsetZ,
                };
                if (this.precisionState.createCopies) {
                    label = 'Offset copies';
                    action = function () {
                        return this.session.duplicatePlacements(
                            placementIds,
                            delta
                        );
                    }.bind(this);
                } else {
                    label = 'Offset selection';
                    action = function () {
                        return this.session.moveSelected(delta);
                    }.bind(this);
                }
            }
            if (!action) throw new Error('Positioning action is unavailable.');
            if (typeof this.session.movePlacements !== 'function'
                    && mode !== 'offset') {
                throw new Error('Precise positioning is not available.');
            }
        } catch (error) {
            this.precisionMessage = error.message;
            this.precisionStatus.textContent = this.precisionMessage;
            this._setError(error);
            return Promise.resolve(undefined);
        }
        const run = this._invoke(label, action);
        return run.then(function (result) {
            this.closePrecisionDialog(true);
            return result;
        }.bind(this), function (error) {
            this.precisionMessage = error && error.message
                ? error.message : String(error);
            this.precisionStatus.textContent = this.precisionMessage;
            return undefined;
        }.bind(this));
    };

    Workspace.prototype.openPatternDialog = function (mode) {
        if (!PATTERN_MODES.includes(mode)) {
            throw new TypeError('facility pattern mode is unsupported');
        }
        if (!this.capabilities.manualAuthoring
                || !this.patternRuntime
                || typeof this.session.applyPattern !== 'function'
                || this.assetBrowserState.open
                || this.state.busy
                || this.state.conflict
                || this.state.layoutProposal
                || this.state.placementAlternatives) return false;
        if (this.precisionState.open) this.closePrecisionDialog(false);
        if (this.planSettingsState.open) {
            this.closePlanSettingsDialog(false, false);
        }
        this._closeSelectionToolbar('pattern_dialog_opened', false);
        this.patternFocusReturn = this.document.activeElement;
        this.patternState.mode = mode;
        this.patternState.open = true;
        this.patternState.applying = false;
        this.patternMessage = '';
        try {
            this._initializePatternDefaults(mode);
        } catch (error) {
            this.patternState.open = false;
            this.patternMessage = error.message;
            this._setError(error);
            return false;
        }
        this._setToolMode('select');
        this._setViewMode('plan');
        this.root.setAttribute('data-pattern-open', 'true');
        this._renderPatternDialog();
        this._renderToolbarState();
        const first = this.patternBody.querySelector('[data-pattern-field]');
        if (first && typeof first.focus === 'function') first.focus();
        return true;
    };

    Workspace.prototype.closePatternDialog = function (restoreFocus) {
        if (!this.patternState.open) return false;
        this._finishMovableDialogDrag(this.patternDialog, true);
        this.patternState.open = false;
        this.patternState.applying = false;
        this.patternState.mirrorPicking = false;
        this.patternState.mirrorPickPoints = [];
        this.patternDialog.hidden = true;
        this.root.removeAttribute('data-pattern-open');
        this.root.removeAttribute('data-mirror-axis-picking');
        this._setPatternPreview(null);
        this._renderToolbarState();
        const target = this.patternFocusReturn;
        this.patternFocusReturn = null;
        if (restoreFocus !== false && target
                && typeof target.focus === 'function') {
            target.focus();
        }
        this._syncSelectionToolbar();
        return true;
    };

    Workspace.prototype._handlePatternChange = function (event) {
        const field = targetDataId(
            event.target,
            'data-pattern-field',
            this.patternDialog
        );
        if (!field || !Object.prototype.hasOwnProperty.call(
            this.patternState,
            field
        )) return;
        const distanceFields = [
            'pitch', 'centerX', 'centerZ', 'width', 'depth', 'gap',
            'perimeterClearGap', 'stackGap',
            'surfaceGap', 'surfaceItemGap', 'surfaceInset',
            'mirrorAxisX', 'mirrorAxisZ',
        ];
        const integerFields = [
            'count', 'rows', 'perimeterWidthCount', 'perimeterDepthCount',
            'stackCount',
        ];
        if (['rotateWithPattern', 'invertU'].includes(field)) {
            this.patternState[field] = event.target.checked === true;
        } else if (distanceFields.includes(field)) {
            const value = finite(event.target.value, NaN);
            if (Number.isFinite(value)) {
                this.patternState[field] = canonicalDistance(
                    value,
                    this.planPreferences.unit
                );
            }
        } else if (integerFields.includes(field)) {
            const value = finite(event.target.value, NaN);
            if (Number.isFinite(value)) {
                this.patternState[field] = Math.round(value);
            }
        } else if (['angleDegrees', 'sweepDegrees'].includes(field)) {
            const value = finite(event.target.value, NaN);
            if (Number.isFinite(value)) this.patternState[field] = value;
        } else {
            this.patternState[field] = String(event.target.value || '');
        }
        if (field === 'surfaceSupportId') {
            const support = this._patternSeed(false).find(function (item) {
                return item.kind === 'placement'
                    && item.id === this.patternState.surfaceSupportId;
            }, this);
            this.patternState.surfaceId = support
                && support.supportSurfaces
                && support.supportSurfaces.length
                ? support.supportSurfaces[0].surfaceId
                : 'derived-top';
        }
        const changesDialogShape = field === 'linearDirection'
            || field === 'shape'
            || field === 'perimeterShape'
            || field === 'mirrorAxisMode'
            || field === 'surfaceSupportId'
            || field === 'surfaceId';
        if (field === 'mirrorAxisMode') {
            this.patternState.mirrorPicking = false;
            this.patternState.mirrorPickPoints = [];
            this.root.removeAttribute('data-mirror-axis-picking');
            if (this.patternState.mirrorAxisMode === 'two-point') {
                this.patternState.mirrorAxisStart = null;
                this.patternState.mirrorAxisEnd = null;
            }
        }
        if (changesDialogShape
                || ['rotateWithPattern', 'invertU'].includes(field)) {
            this._renderPatternDialog();
            return;
        }
        const result = this._updatePatternPreview();
        this.patternStatus.textContent = this.patternMessage;
        this.patternApply.disabled = !result
            || this.patternState.applying
            || this.state.busy
            || this.state.conflict;
    };

    Workspace.prototype._handlePatternClick = function (event) {
        const mode = targetDataId(
            event.target,
            'data-pattern-mode',
            this.patternDialog
        );
        if (mode && PATTERN_MODES.includes(mode)) {
            this.patternState.mode = mode;
            try {
                this._initializePatternDefaults(mode);
            } catch (error) {
                this.patternMessage = error.message;
            }
            this._renderPatternDialog();
            return;
        }
        const action = targetDataId(
            event.target,
            'data-pattern-action',
            this.patternDialog
        );
        if (action === 'close' || action === 'cancel') {
            this.closePatternDialog(true);
        } else if (action === 'pick-mirror-axis') {
            this.patternState.mirrorPicking = true;
            this.patternState.mirrorPickPoints = [];
            if (this.patternState.mirrorAxisMode === 'two-point') {
                this.patternState.mirrorAxisStart = null;
                this.patternState.mirrorAxisEnd = null;
            }
            this.root.setAttribute('data-mirror-axis-picking', 'true');
            this.patternMessage = this.patternState.mirrorAxisMode === 'two-point'
                ? 'Pick the first construction-line point in the Plan.'
                : 'Pick the grid line to use as the mirror axis.';
            this._renderPatternDialog();
        } else if (action === 'apply') {
            this._applyPattern();
        }
    };

    Workspace.prototype._handlePatternKeyDown = function (event) {
        const key = String(event && event.key || '').toLowerCase();
        if (key === 'escape') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this.closePatternDialog(true);
        } else if (key === 'enter'
                && event.target !== this.patternCancel
                && event.target !== this.patternClose) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._applyPattern();
        }
    };

    Workspace.prototype._applyPattern = function () {
        let result;
        try {
            result = this._buildPatternResult();
        } catch (error) {
            this.patternMessage = error.message;
            this.patternStatus.textContent = this.patternMessage;
            this._setError(error);
            return Promise.resolve(undefined);
        }
        const cellPreset = CELL_LAYOUT_PRESETS.find(function (preset) {
            return preset.value === this.patternState.shape;
        }, this);
        const label = {
            'linear-pattern': 'Linear layout pattern',
            'circular-pattern': 'Circular layout pattern',
            'perimeter-pattern': 'Rectangular perimeter pattern',
            'cell-layout': (cellPreset ? cellPreset.label : 'Manufacturing cell')
                + ' layout',
            'vertical-stack': 'Vertical equipment stack',
            'surface-stack': 'Surface equipment stack',
            mirror: 'Mirror layout selection',
            swap: 'Swap layout positions',
        }[this.patternState.mode] || 'Facility layout pattern';
        this.patternState.applying = true;
        this._setPatternPreview(null);
        this._renderPatternDialog();
        const run = this._invoke(label, function () {
            return this.session.applyPattern(result, label);
        }.bind(this));
        return run.then(function (value) {
            this.closePatternDialog(true);
            return value;
        }.bind(this), function (error) {
            this.patternState.applying = false;
            this.patternMessage = error && error.message
                ? error.message : String(error);
            this._renderPatternDialog();
            return undefined;
        }.bind(this));
    };

    Workspace.prototype._assetBrowserTotals = function () {
        const selected = this.assetBrowserState.selected;
        const assetTypes = Object.keys(selected).filter(function (assetId) {
            return finite(selected[assetId], 0) > 0;
        });
        return {
            assetTypes: assetTypes.length,
            totalItems: assetTypes.reduce(function (total, assetId) {
                return total + Math.floor(finite(selected[assetId], 0));
            }, 0),
        };
    };

    Workspace.prototype._removeAssetBrowserSelection = function (assetId) {
        delete this.assetBrowserState.selected[assetId];
        this.assetBrowserState.selectionOrder =
            this.assetBrowserState.selectionOrder.filter(function (value) {
                return value !== assetId;
            });
    };

    Workspace.prototype._setAssetBrowserQuantity = function (assetId, quantity) {
        const next = Math.max(0, Math.floor(finite(quantity, 0)));
        if (!next) {
            this._removeAssetBrowserSelection(assetId);
            return;
        }
        if (!Object.prototype.hasOwnProperty.call(
            this.assetBrowserState.selected,
            assetId
        )) {
            this.assetBrowserState.selectionOrder.push(assetId);
        }
        this.assetBrowserState.selected[assetId] = Math.min(25, next);
    };

    Workspace.prototype._renderAssetBrowserCategories = function () {
        const categories = ['All'].concat(Array.from(new Set(
            this.assetCatalog.map(function (record) { return record.category; })
        )).sort());
        if (!categories.includes(this.assetBrowserState.category)) {
            this.assetBrowserState.category = 'All';
        }
        clearElement(this.assetCategoryNav);
        categories.forEach(function (category) {
            const active = category === this.assetBrowserState.category;
            this.assetCategoryNav.appendChild(element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-asset-category',
                role: 'tab',
                'aria-selected': active ? 'true' : 'false',
                tabindex: active ? '0' : '-1',
                'data-asset-category': category,
            }, category));
        }, this);
    };

    Workspace.prototype._assetBrowserMatches = function (record) {
        if (this.assetBrowserState.category !== 'All'
                && record.category !== this.assetBrowserState.category) {
            return false;
        }
        const needle = String(this.assetBrowserState.query || '')
            .trim().toLowerCase();
        if (!needle) return true;
        return [
            record.label,
            record.assetId,
            record.category,
            record.description,
            record.manufacturer,
        ].concat(record.tags || []).join(' ').toLowerCase().includes(needle);
    };

    Workspace.prototype._renderAssetBrowserCard = function (record) {
        const quantity = Math.floor(finite(
            this.assetBrowserState.selected[record.assetId],
            0
        ));
        const selected = quantity > 0;
        const card = element(this.document, 'article', {
            className: 'ip-flw-asset-card' + (selected ? ' selected' : ''),
            role: 'listitem',
            'data-asset-id': record.assetId,
            'data-asset-revision': record.assetDefinitionRevision,
        });
        const toggle = element(this.document, 'button', {
            type: 'button',
            className: 'ip-flw-asset-card-select',
            'data-asset-browser-action': 'toggle',
            'data-asset-id': record.assetId,
            'aria-pressed': selected ? 'true' : 'false',
            'aria-label': (selected ? 'Deselect ' : 'Select ') + record.label,
        });
        const visual = element(this.document, 'span', {
            className: 'ip-flw-asset-card-visual',
            'aria-hidden': 'true',
        });
        if (record.thumbnailUrl) {
            visual.appendChild(element(this.document, 'img', {
                src: record.thumbnailUrl,
                alt: '',
                loading: 'lazy',
                decoding: 'async',
            }));
        } else {
            visual.appendChild(element(this.document, 'span', {
                className: 'ip-flw-asset-card-fallback',
            }, record.category.charAt(0).toUpperCase()));
        }
        const copy = element(this.document, 'span', {
            className: 'ip-flw-asset-card-copy',
        });
        copy.appendChild(element(this.document, 'strong', {}, record.label));
        copy.appendChild(element(this.document, 'span', {}, record.category));
        copy.appendChild(element(
            this.document,
            'small',
            {},
            Number(record.width.toFixed(2)) + ' x '
                + Number(record.depth.toFixed(2)) + ' m'
        ));
        if (record.description) {
            copy.appendChild(element(this.document, 'small', {
                className: 'ip-flw-asset-card-description',
            }, boundedText(record.description, 110)));
        }
        append(toggle, visual, copy);
        if (selected) {
            toggle.appendChild(element(this.document, 'span', {
                className: 'ip-flw-asset-selected-badge',
                'aria-hidden': 'true',
            }, 'Selected'));
        }
        const stepper = element(this.document, 'div', {
            className: 'ip-flw-asset-quantity',
            role: 'group',
            'aria-label': record.label + ' quantity',
            hidden: !selected,
        });
        append(stepper,
            element(this.document, 'button', {
                type: 'button',
                'data-asset-browser-action': 'decrement',
                'data-asset-id': record.assetId,
                'aria-label': 'Decrease ' + record.label + ' quantity',
            }, '-'),
            element(this.document, 'output', {
                'aria-label': record.label + ' quantity',
            }, String(quantity)),
            element(this.document, 'button', {
                type: 'button',
                'data-asset-browser-action': 'increment',
                'data-asset-id': record.assetId,
                'aria-label': 'Increase ' + record.label + ' quantity',
                disabled: this._assetBrowserTotals().totalItems
                    >= MAX_ASSET_BATCH_ITEMS,
            }, '+')
        );
        append(card, toggle, stepper);
        return card;
    };

    Workspace.prototype._renderAssetBrowser = function () {
        if (!this.assetGrid) return;
        this._renderAssetBrowserCategories();
        clearElement(this.assetGrid);
        const matches = this.assetCatalog.filter(
            this._assetBrowserMatches.bind(this)
        );
        matches.forEach(function (record) {
            this.assetGrid.appendChild(this._renderAssetBrowserCard(record));
        }, this);
        this.assetGrid.hidden = matches.length === 0;
        this.assetBrowserEmpty.hidden = matches.length !== 0;
        const totals = this._assetBrowserTotals();
        this.assetBrowserSelectionStatus.textContent =
            this.assetBrowserSubmitting
                ? 'Adding ' + totals.totalItems + ' asset'
                    + (totals.totalItems === 1 ? '' : 's') + ' to the layout...'
                : totals.totalItems
                    ? totals.assetTypes + ' asset type'
                + (totals.assetTypes === 1 ? '' : 's') + ' selected - '
                + totals.totalItems + ' total item'
                + (totals.totalItems === 1 ? '' : 's')
                    : 'No assets selected';
        this.assetBrowserAdd.textContent = this.assetBrowserSubmitting
            ? 'Adding...' : 'Add to Layout';
        this.assetBrowserAdd.setAttribute(
            'aria-busy',
            this.assetBrowserSubmitting ? 'true' : 'false'
        );
        this.assetBrowserAdd.disabled = this.assetBrowserSubmitting
            || !totals.totalItems
            || totals.totalItems > MAX_ASSET_BATCH_ITEMS
            || this.state.busy
            || !this.capabilities.manualAuthoring
            || Boolean(this.state.conflict);
    };

    Workspace.prototype._focusAssetBrowserControl = function (action, assetId) {
        const controls = Array.prototype.slice.call(
            this.assetBrowser.querySelectorAll(
                '[data-asset-browser-action="' + action + '"]'
            )
        );
        const target = controls.find(function (control) {
            return !assetId
                || control.getAttribute('data-asset-id') === assetId;
        });
        if (target && typeof target.focus === 'function') target.focus();
    };

    Workspace.prototype.openAssetBrowser = function () {
        if (!this.capabilities.assetLibrary
                || this.state.busy
                || this.state.conflict
                || this.state.layoutProposal
                || this.state.placementAlternatives) return false;
        if (this.precisionState.open) this.closePrecisionDialog(false);
        if (this.patternState.open) this.closePatternDialog(false);
        this._closeSelectionToolbar('asset_browser_opened', false);
        this.assetBrowserFocusReturn = this.document.activeElement;
        this.assetBrowserState.open = true;
        this.assetBrowser.hidden = false;
        this.assetBrowser.setAttribute('aria-hidden', 'false');
        this.shell.setAttribute('aria-hidden', 'true');
        this.root.setAttribute('data-asset-browser-open', 'true');
        this._renderAssetBrowser();
        this._renderToolbarState();
        if (typeof this.assetBrowserSearch.focus === 'function') {
            this.assetBrowserSearch.focus();
        }
        if (typeof this.options.onAssetBrowserStateChange === 'function') {
            this.options.onAssetBrowserStateChange(true);
        }
        return true;
    };

    Workspace.prototype.closeAssetBrowser = function (clearSelection) {
        if (!this.assetBrowserState.open) return false;
        if (this.assetBrowserSubmitting) return false;
        if (clearSelection) {
            this.assetBrowserState.selected = {};
            this.assetBrowserState.selectionOrder = [];
        }
        this.assetBrowserState.open = false;
        this.assetBrowser.hidden = true;
        this.assetBrowser.setAttribute('aria-hidden', 'true');
        this.shell.removeAttribute('aria-hidden');
        this.root.removeAttribute('data-asset-browser-open');
        this._renderAssetBrowser();
        this._renderToolbarState();
        const target = this.assetBrowserFocusReturn;
        this.assetBrowserFocusReturn = null;
        if (target && typeof target.focus === 'function'
                && this.root.contains(target)) {
            target.focus();
        } else {
            const assets = this.toolbar.querySelector('[data-command="assets"]');
            if (assets && typeof assets.focus === 'function') assets.focus();
        }
        this._syncSelectionToolbar();
        if (typeof this.options.onAssetBrowserStateChange === 'function') {
            this.options.onAssetBrowserStateChange(false);
        }
        return true;
    };

    Workspace.prototype._selectedAssetBrowserEntries = function () {
        return this.assetBrowserState.selectionOrder.map(function (assetId) {
            const record = catalogRecord(this.assetCatalog, assetId, '');
            return record ? {
                assetId: record.assetId,
                assetDefinitionRevision: record.assetDefinitionRevision,
                quantity: this.assetBrowserState.selected[assetId],
            } : null;
        }, this).filter(Boolean);
    };

    Workspace.prototype._addAssetBrowserSelection = function () {
        if (this.assetBrowserSubmitting) return this.pending;
        if (typeof this.session.placeAssets !== 'function') {
            this._setError(new Error('Batch asset placement is unavailable'));
            return Promise.resolve(this.getState());
        }
        let requests;
        try {
            requests = buildAssetBatchPlacementRequests(
                this._selectedAssetBrowserEntries(),
                this.state.layout,
                this.assetCatalog,
                this._keyboardPlacementWorld(),
                {
                    gridSize: this.gridSize,
                    worldBounds: this.options.topPlanOptions
                        && this.options.topPlanOptions.worldBounds,
                }
            );
        } catch (error) {
            this._setError(error);
            this._renderAssetBrowser();
            this.assetBrowserSelectionStatus.textContent = error && error.message
                ? error.message : String(error);
            return Promise.resolve(this.getState());
        }
        const itemCount = requests.length;
        this.assetBrowserSubmitting = true;
        this._renderAssetBrowser();
        const run = this._invoke('Add assets', function () {
            return this.session.placeAssets(requests);
        }.bind(this));
        run.then(function () {
            this.assetBrowserSubmitting = false;
            this.closeAssetBrowser(true);
            if (this.controller && typeof this.controller.fit === 'function') {
                this.controller.fit();
            }
            this.advisoryLiveRegion.textContent = itemCount + ' asset'
                + (itemCount === 1 ? '' : 's') + ' added to the layout.';
            const select = this.toolbar.querySelector('[data-command="select"]');
            if (select && typeof select.focus === 'function') select.focus();
        }.bind(this)).catch(function (error) {
            this.assetBrowserSubmitting = false;
            this._renderAssetBrowser();
            this.assetBrowserSelectionStatus.textContent = error && error.message
                ? error.message : 'The selected assets could not be added.';
        }.bind(this));
        return run;
    };

    Workspace.prototype._handleAssetBrowserClick = function (event) {
        const category = targetDataId(
            event.target,
            'data-asset-category',
            this.assetBrowser
        );
        if (category) {
            this.assetBrowserState.category = category;
            this._renderAssetBrowser();
            const active = Array.prototype.slice.call(
                this.assetCategoryNav.querySelectorAll('[data-asset-category]')
            ).find(function (control) {
                return control.getAttribute('data-asset-category') === category;
            });
            if (active && typeof active.focus === 'function') active.focus();
            return;
        }
        const action = targetDataId(
            event.target,
            'data-asset-browser-action',
            this.assetBrowser
        );
        if (!action) return;
        const assetId = targetDataId(
            event.target,
            'data-asset-id',
            this.assetBrowser
        );
        if (action === 'toggle' && assetId) {
            const current = finite(this.assetBrowserState.selected[assetId], 0);
            if (current || this._assetBrowserTotals().totalItems
                    < MAX_ASSET_BATCH_ITEMS) {
                this._setAssetBrowserQuantity(assetId, current ? 0 : 1);
            }
            this._renderAssetBrowser();
            this._focusAssetBrowserControl('toggle', assetId);
        } else if (action === 'increment' && assetId) {
            const totals = this._assetBrowserTotals();
            if (totals.totalItems < MAX_ASSET_BATCH_ITEMS) {
                this._setAssetBrowserQuantity(
                    assetId,
                    finite(this.assetBrowserState.selected[assetId], 0) + 1
                );
                this._renderAssetBrowser();
                this._focusAssetBrowserControl('increment', assetId);
            }
        } else if (action === 'decrement' && assetId) {
            const nextQuantity = Math.max(
                0,
                finite(this.assetBrowserState.selected[assetId], 0) - 1
            );
            this._setAssetBrowserQuantity(
                assetId,
                nextQuantity
            );
            this._renderAssetBrowser();
            this._focusAssetBrowserControl(
                nextQuantity ? 'decrement' : 'toggle',
                assetId
            );
        } else if (action === 'clear-filters') {
            this.assetBrowserState.query = '';
            this.assetBrowserState.category = 'All';
            this.assetBrowserSearch.value = '';
            this._renderAssetBrowser();
            if (typeof this.assetBrowserSearch.focus === 'function') {
                this.assetBrowserSearch.focus();
            }
        } else if (action === 'add') {
            this._addAssetBrowserSelection();
        } else if (action === 'cancel') {
            this.closeAssetBrowser(true);
        } else if (action === 'close') {
            this.closeAssetBrowser(false);
        }
    };

    Workspace.prototype._handleAssetBrowserKeyDown = function (event) {
        const key = String(event && event.key || '');
        if (key === 'Escape') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            if (typeof event.stopPropagation === 'function') event.stopPropagation();
            this.closeAssetBrowser(false);
            return;
        }
        const category = targetDataId(
            event.target,
            'data-asset-category',
            this.assetCategoryNav
        );
        if (category && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(key)) {
            const tabs = Array.prototype.slice.call(
                this.assetCategoryNav.querySelectorAll('[data-asset-category]')
            );
            const current = tabs.indexOf(event.target);
            if (current >= 0 && tabs.length) {
                let next = current;
                if (key === 'Home') next = 0;
                else if (key === 'End') next = tabs.length - 1;
                else if (key === 'ArrowRight') next = (current + 1) % tabs.length;
                else next = (current - 1 + tabs.length) % tabs.length;
                if (typeof event.preventDefault === 'function') {
                    event.preventDefault();
                }
                this.assetBrowserState.category = tabs[next].getAttribute(
                    'data-asset-category'
                );
                this._renderAssetBrowser();
                const active = this.assetCategoryNav.querySelector(
                    '[data-asset-category="'
                        + this.assetBrowserState.category + '"]'
                );
                if (active && typeof active.focus === 'function') active.focus();
            }
            return;
        }
        if (key !== 'Tab') return;
        const focusable = Array.prototype.slice.call(
            this.assetBrowser.querySelectorAll('button,input')
        )
            .filter(function (node) {
                if (node.disabled || node.hidden
                        || node.getAttribute('tabindex') === '-1') return false;
                let current = node.parentNode;
                while (current && current !== this.assetBrowser) {
                    if (current.hidden) return false;
                    current = current.parentNode;
                }
                return true;
            }, this);
        if (!focusable.length) return;
        const current = focusable.indexOf(this.document.activeElement);
        if (!event.shiftKey && current === focusable.length - 1) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            focusable[0].focus();
        } else if (event.shiftKey && current <= 0) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            focusable[focusable.length - 1].focus();
        }
    };

    Workspace.prototype._payloadForEvent = function (event) {
        const parsed = parseAssetDragPayload(event);
        if (parsed) return parsed;
        return this.activeDrag && this.activeDrag.payload || null;
    };

    Workspace.prototype._ensureGhost = function (payload) {
        const current = this.session.getState().ghostPlacement;
        if (current && current.assetId === payload.assetId
                && current.assetDefinitionRevision === payload.assetDefinitionRevision) {
            return;
        }
        if (current) this.session.cancelGhostPlacement();
        const asset = this.assetCatalog.find(function (record) {
            return record.assetId === payload.assetId
                && record.assetDefinitionRevision === payload.assetDefinitionRevision;
        });
        this.session.beginGhostPlacement({
            assetId: payload.assetId,
            assetDefinitionRevision: payload.assetDefinitionRevision,
            metadata: {
                instanceLabel: asset ? asset.label : payload.assetId,
                dragSessionId: payload.dragSessionId,
            },
        });
    };

    Workspace.prototype._keyboardPlacementWorld = function () {
        const activeAdapter = this.viewMode === '3d'
            ? this.threeAdapter : this.topAdapter;
        const configured = this.options.keyboardPlacementPoint;
        const supplied = typeof configured === 'function'
            ? configured({
                viewMode: this.viewMode,
                adapter: activeAdapter,
                workspace: this,
            })
            : configured;
        if (supplied && typeof supplied === 'object') {
            return snapWorldPoint(supplied, this._activeSnapStep());
        }
        if (this.viewMode === '3d'
                && this.threeAdapter
                && typeof this.threeAdapter.worldPointOnFloor === 'function') {
            const rect = typeof this.threeView.getBoundingClientRect === 'function'
                ? this.threeView.getBoundingClientRect()
                : null;
            const width = finite(rect && rect.width, 0);
            const height = finite(rect && rect.height, 0);
            if (width > 0 && height > 0) {
                const world = this.threeAdapter.worldPointOnFloor({
                    clientX: finite(rect.left, 0) + width / 2,
                    clientY: finite(rect.top, 0) + height / 2,
                }, 0);
                if (world) return snapWorldPoint(world, this._activeSnapStep());
            }
        }
        if (this.topAdapter
                && typeof this.topAdapter.clientToWorld === 'function') {
            const rect = typeof this.planView.getBoundingClientRect === 'function'
                ? this.planView.getBoundingClientRect()
                : null;
            const left = finite(rect && rect.left, 0);
            const top = finite(rect && rect.top, 0);
            const width = Math.max(
                1,
                finite(rect && rect.width, this.planView.clientWidth || 1)
            );
            const height = Math.max(
                1,
                finite(rect && rect.height, this.planView.clientHeight || 1)
            );
            const world = this.topAdapter.clientToWorld({
                clientX: left + width / 2,
                clientY: top + height / 2,
                floorY: 0,
            });
            if (world) return snapWorldPoint(world, this._activeSnapStep());
        }
        return { x: 0, y: 0, z: 0 };
    };

    Workspace.prototype._eventWorld = function (event) {
        const adapter = this.viewMode === '3d' ? this.threeAdapter : this.topAdapter;
        const context = {
            viewMode: this.viewMode,
            adapter: adapter,
            controller: this.controller,
            root: this.viewportStack,
        };
        let result = null;
        if (typeof this.eventToWorld === 'function') {
            result = this.eventToWorld(event, context);
        } else if (this.viewMode === '3d'
                && adapter
                && typeof adapter.worldPointOnFloor === 'function') {
            result = adapter.worldPointOnFloor(event, 0);
        } else if (adapter && typeof adapter.clientToWorld === 'function') {
            result = adapter.clientToWorld(event);
        }
        if (!result || typeof result !== 'object') {
            throw new Error('eventToWorld did not return a world point');
        }
        return snapWorldPoint(result, this._activeSnapStep());
    };

    Workspace.prototype._tryEventWorld = function (event) {
        try {
            return this._eventWorld(event);
        } catch (error) {
            return null;
        }
    };

    Workspace.prototype._handleDragOver = function (event) {
        const payload = this._payloadForEvent(event);
        if (!payload) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        this._ensureGhost(payload);
        const world = this._tryEventWorld(event);
        if (!world) {
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'none';
            this._showGesture('No valid facility-floor point');
            return;
        }
        this.activeDrag = {
            payload: payload,
            asset: this.activeDrag && this.activeDrag.asset || null,
        };
        this.session.updateGhostPlacement(world, true);
        this._requestDragAdvisory(payload, world);
        this._renderGhost(world, payload.assetId);
        this._setCoordinates(world);
    };

    Workspace.prototype._handleDrop = function (event) {
        if (this.generationPlanningView && this.generationPlanningView.activeLayout()) return;
        if (!this.capabilities.manualAuthoring) return;
        const payload = this._payloadForEvent(event);
        if (!payload) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        this._ensureGhost(payload);
        const world = this._tryEventWorld(event);
        if (!world) {
            this.session.cancelGhostPlacement();
            this.activeDrag = null;
            this._hideGhost();
            this._showGesture('Placement cancelled: no valid floor point');
            return;
        }
        this.session.updateGhostPlacement(world, true);
        this._cancelAdvisoryRequest('Drop completed.');
        if (this.useAuthoritativePlacementCandidates
                && typeof this.session.requestPlacementAlternatives
                    === 'function') {
            this._invoke('Find placement alternatives', function () {
                return this.session.requestPlacementAlternatives({
                    assetId: payload.assetId,
                    assetDefinitionRevision:
                        payload.assetDefinitionRevision,
                    requestedPosition: world,
                    maximumCandidates: 8,
                });
            }.bind(this));
        } else {
            this._invoke('Place asset', function () {
                return this.session.commitGhostPlacement({
                    positionMode: 'manual',
                });
            }.bind(this));
        }
        this.activeDrag = null;
        this.dragAdvisory = null;
        this._hideGhost();
    };

    Workspace.prototype._handleDragLeave = function (event) {
        const related = event && event.relatedTarget;
        if (related && typeof this.viewportStack.contains === 'function'
                && this.viewportStack.contains(related)) return;
        this._cancelGhost();
    };

    Workspace.prototype._cancelGhost = function () {
        if (this.destroyed) return;
        this._cancelAdvisoryRequest('Drag cancelled.');
        if (this.session.getState().ghostPlacement) {
            this.session.cancelGhostPlacement();
        }
        this.activeDrag = null;
        this.dragAdvisory = null;
        this._hideGhost();
    };

    Workspace.prototype._cancelAdvisoryRequest = function (reason) {
        if (this.spatialAdvisor
                && typeof this.spatialAdvisor.cancel === 'function') {
            this.spatialAdvisor.cancel(reason);
        }
    };

    Workspace.prototype._clearDragAdvisory = function () {
        this._cancelAdvisoryRequest('A new drag started.');
        this.dragAdvisory = null;
    };

    Workspace.prototype._requestDragAdvisory = function (payload, world) {
        if (!this.spatialAdvisor
                || typeof this.spatialAdvisor.request !== 'function'
                || !this.state.layout) {
            this.dragAdvisory = null;
            return;
        }
        const dragSessionId = payload.dragSessionId;
        const positionKey = [
            world.x,
            world.y,
            world.z,
        ].join('|');
        this.dragAdvisory = {
            authority: 'browser-advisory',
            authoritative: false,
            status: 'pending',
            summary: 'Checking coarse overlap and zone placement.',
            dragSessionId: dragSessionId,
            positionKey: positionKey,
        };
        this._renderGhost(world, payload.assetId);
        const catalog = this.assetCatalog.map(function (record) {
            return clone(record.source || record);
        });
        this.spatialAdvisor.request({
            layoutRevision: this.state.baseRevision,
            layout: this.state.layout,
            assetCatalog: catalog,
            ghost: {
                assetId: payload.assetId,
                assetDefinitionRevision: payload.assetDefinitionRevision,
                worldPosition: world,
            },
        }).then(function (advisory) {
            if (this.destroyed || !this.activeDrag
                    || this.activeDrag.payload.dragSessionId !== dragSessionId) {
                return;
            }
            const current = this.session.getState().ghostPlacement;
            if (!current || !current.worldPosition
                    || [
                        current.worldPosition.x,
                        current.worldPosition.y,
                        current.worldPosition.z,
                    ].join('|') !== positionKey) {
                return;
            }
            this.dragAdvisory = Object.assign({}, clone(advisory), {
                dragSessionId: dragSessionId,
                positionKey: positionKey,
            });
            this._renderGhost(current.worldPosition, payload.assetId);
        }.bind(this)).catch(function (error) {
            if (error && error.name === 'AbortError') return;
            if (this.destroyed || !this.activeDrag
                    || this.activeDrag.payload.dragSessionId !== dragSessionId) {
                return;
            }
            const current = this.session.getState().ghostPlacement;
            this.dragAdvisory = {
                authority: 'browser-advisory',
                authoritative: false,
                status: 'unavailable',
                summary: 'Coarse advisory is unavailable. The server remains authoritative.',
                dragSessionId: dragSessionId,
                positionKey: positionKey,
            };
            if (current && current.worldPosition) {
                this._renderGhost(current.worldPosition, payload.assetId);
            }
        }.bind(this));
    };

    Workspace.prototype._renderGhost = function (world, assetId) {
        const active = this.session.getState().ghostPlacement || {};
        const candidate = active.metadata
            && active.metadata.previewKind
                === 'authoritative-placement-candidate'
            ? active.metadata
            : null;
        const advisory = candidate ? null : this.dragAdvisory;
        const ghost = {
            assetId: active.assetId || assetId,
            assetDefinitionRevision: active.assetDefinitionRevision || '',
            worldPosition: world,
            valid: active.valid !== false,
            metadata: Object.assign({}, clone(active.metadata || {}), {
                spatialAdvisory: clone(advisory),
            }),
        };
        [this.topAdapter, this.threeAdapter].filter(Boolean).forEach(
            function (adapter) {
                if (typeof adapter.setGhostPlacement === 'function') {
                    adapter.setGhostPlacement(ghost);
                }
            }
        );
        this.ghostOverlay.hidden = false;
        this.ghostOverlay.setAttribute('data-active', 'true');
        if (candidate) {
            const assessment = candidateAssessment(candidate);
            this.ghostOverlay.setAttribute(
                'data-advisory-state',
                'server-authoritative'
            );
            this.ghostOverlay.setAttribute(
                'data-safety-status',
                assessment.status
            );
            this.ghostOverlay.textContent = cleanString(assetId, 'Asset')
                + ' | Authoritative option '
                + (finite(candidate.candidateIndex, 0) + 1)
                + ' of ' + finite(candidate.candidateCount, 1)
                + (candidate.family ? ' | ' + candidate.family : '')
                + ' | ' + assessment.label
                + (assessment.summary ? ' | ' + assessment.summary : '')
                + ' | X ' + world.x.toFixed(2)
                + ' Z ' + world.z.toFixed(2);
            const announcement = 'Authoritative placement option '
                + (finite(candidate.candidateIndex, 0) + 1)
                + ' of ' + finite(candidate.candidateCount, 1)
                + (candidate.family ? ', ' + candidate.family : '')
                + '. ' + assessment.label
                + (assessment.summary ? '. ' + assessment.summary : '')
                + '. Not yet applied.';
            if (this.advisoryLiveRegion.textContent !== announcement) {
                this.advisoryLiveRegion.textContent = announcement;
            }
        } else {
            this.ghostOverlay.removeAttribute('data-safety-status');
            const status = advisory && advisory.status || 'unavailable';
            this.ghostOverlay.setAttribute('data-advisory-state', status);
            this.ghostOverlay.textContent = cleanString(assetId, 'Asset')
                + ' | X ' + world.x.toFixed(2)
                + ' Z ' + world.z.toFixed(2)
                + (advisory
                    ? ' | Advisory: ' + cleanString(
                        advisory.summary,
                        status
                    )
                    : ' | Advisory: server check on placement');
            const announcement = advisory
                ? 'Placement advisory: ' + cleanString(
                    advisory.summary,
                    status
                )
                : 'Placement advisory will be confirmed by the server.';
            if (this.advisoryLiveRegion.textContent !== announcement) {
                this.advisoryLiveRegion.textContent = announcement;
            }
        }
    };

    Workspace.prototype._hideGhost = function () {
        [this.topAdapter, this.threeAdapter].filter(Boolean).forEach(
            function (adapter) {
                if (typeof adapter.setGhostPlacement === 'function') {
                    adapter.setGhostPlacement(null);
                }
            }
        );
        this.ghostOverlay.hidden = true;
        this.ghostOverlay.removeAttribute('data-active');
        this.ghostOverlay.removeAttribute('data-advisory-state');
        this.ghostOverlay.removeAttribute('data-safety-status');
        this.ghostOverlay.textContent = '';
        this.advisoryLiveRegion.textContent = '';
    };

    Workspace.prototype._handleCandidateAction = function (event) {
        const action = targetDataId(
            event.target,
            'data-candidate-action',
            this.candidateControls
        );
        if (!action || this.state.busy) return;
        if (this.state.layoutProposal) {
            if (action === 'previous') {
                this.session.cycleLayoutProposal(-1);
            } else if (action === 'next') {
                this.session.cycleLayoutProposal(1);
            } else if (action === 'dismiss') {
                this._invoke('Dismiss layout proposal', function () {
                    return this.session.dismissLayoutProposal();
                }.bind(this));
            } else if (action === 'accept') {
                this._invoke('Approve layout proposal', function () {
                    return this.session.approveAndApplyLayoutProposal();
                }.bind(this));
            }
            return;
        }
        if (action === 'previous') {
            this.session.cyclePlacementAlternative(-1);
        } else if (action === 'next') {
            this.session.cyclePlacementAlternative(1);
        } else if (action === 'dismiss') {
            this.session.dismissPlacementAlternatives();
        } else if (action === 'accept') {
            this._invoke('Accept placement alternative', function () {
                return this.session.acceptPlacementAlternative();
            }.bind(this));
        }
    };

    Workspace.prototype._renderCandidateControls = function () {
        const layoutProposal = this.state.layoutProposal;
        const acceptButton = this.candidateControls.querySelector(
            '[data-candidate-action="accept"]'
        );
        const dismissButton = this.candidateControls.querySelector(
            '[data-candidate-action="dismiss"]'
        );
        if (layoutProposal && Array.isArray(layoutProposal.alternatives)
                && layoutProposal.alternatives.length) {
            const alternative = layoutProposal.alternatives[
                layoutProposal.selectedIndex
            ];
            this.candidateControls.hidden = false;
            this.validationNotice.hidden = false;
            this.candidateControls.removeAttribute('data-safety-status');
            this.candidateControls.setAttribute(
                'data-preview-kind',
                'full-layout'
            );
            this.candidateControls.setAttribute(
                'aria-label',
                'Full-layout alternatives'
            );
            const optionCount = layoutProposal.alternatives.length;
            const strategy = readableProposalStrategy(alternative.strategy);
            this.candidateSummary.textContent = optionCount > 1
                ? 'Proposed layout, option ' + (layoutProposal.selectedIndex + 1)
                    + ' of ' + optionCount + (strategy ? ': ' + strategy : '')
                    + '. Not saved yet.'
                : 'Proposed change. Not saved yet.';
            const review = buildLayoutProposalReview(
                this.state.layout,
                alternative.ghostPreview.layout
            );
            this.proposalReview.hidden = false;
            this.proposalChangeText.textContent =
                proposalPlainChangeSummary(review, alternative);
            const check = proposalPlainCheckSummary(alternative);
            this.proposalCheckText.textContent = check.text;
            this.proposalCheckText.setAttribute('data-check-status', check.status);
            this.proposalBindingText.textContent =
                proposalBindingSummary(layoutProposal, alternative);
            this.proposalDiagnosticText.textContent =
                proposalDiagnosticSummary(alternative);
            const cycleDisabled = optionCount < 2 || this.state.busy;
            ['previous', 'next'].forEach(function (action) {
                const button = this.candidateControls.querySelector(
                    '[data-candidate-action="' + action + '"]'
                );
                if (button) {
                    // A single proposal has nothing to page through.
                    button.hidden = optionCount < 2;
                    button.disabled = cycleDisabled;
                }
            }, this);
            if (acceptButton) {
                acceptButton.disabled = this.state.busy;
                acceptButton.textContent = 'Approve';
                acceptButton.setAttribute(
                    'aria-label',
                    'Approve and apply full-layout proposal'
                );
                acceptButton.setAttribute(
                    'title',
                    'Approve and apply full-layout proposal'
                );
            }
            if (dismissButton) {
                dismissButton.disabled = this.state.busy;
                dismissButton.setAttribute(
                    'aria-label',
                    'Dismiss full-layout proposal'
                );
                dismissButton.setAttribute(
                    'title',
                    'Dismiss full-layout proposal'
                );
            }
            return;
        }
        this.proposalReview.hidden = true;
        this.proposalChangeText.textContent = '';
        this.proposalCheckText.textContent = '';
        this.proposalBindingText.textContent = '';
        this.proposalDiagnosticText.textContent = '';
        const proposal = this.state.placementAlternatives;
        if (!proposal || !Array.isArray(proposal.candidates)
                || !proposal.candidates.length) {
            this.candidateControls.hidden = true;
            this.validationNotice.hidden = true;
            this.candidateControls.removeAttribute('data-safety-status');
            this.candidateControls.removeAttribute('data-preview-kind');
            this.candidateSummary.textContent = '';
            return;
        }
        this.candidateControls.setAttribute(
            'data-preview-kind',
            'placement'
        );
        this.candidateControls.setAttribute(
            'aria-label',
            'Authoritative placement alternatives'
        );
        if (acceptButton) {
            acceptButton.textContent = 'Accept';
            acceptButton.setAttribute(
                'aria-label',
                'Accept placement alternative'
            );
            acceptButton.setAttribute(
                'title',
                'Accept placement alternative'
            );
        }
        if (dismissButton) {
            dismissButton.setAttribute(
                'aria-label',
                'Dismiss placement alternatives'
            );
            dismissButton.setAttribute(
                'title',
                'Dismiss placement alternatives'
            );
        }
        const candidate = proposal.candidates[proposal.selectedIndex];
        const assessment = candidateAssessment(candidate);
        this.candidateControls.hidden = false;
        this.validationNotice.hidden = false;
        this.candidateControls.setAttribute(
            'data-safety-status',
            assessment.status
        );
        this.candidateSummary.textContent = 'Placement option '
            + (proposal.selectedIndex + 1)
            + ' of ' + proposal.candidates.length
            + (candidate.family ? ': ' + candidate.family : '')
            + '. ' + assessment.label
            + (assessment.summary ? '. ' + assessment.summary : '')
            + '. Not yet applied.';
        const cycleDisabled = proposal.candidates.length < 2 || this.state.busy;
        ['previous', 'next'].forEach(function (action) {
            const button = this.candidateControls.querySelector(
                '[data-candidate-action="' + action + '"]'
            );
            if (button) {
                button.hidden = false;
                button.disabled = cycleDisabled;
            }
        }, this);
        ['accept', 'dismiss'].forEach(function (action) {
            const button = this.candidateControls.querySelector(
                '[data-candidate-action="' + action + '"]'
            );
            if (button) {
                button.disabled = this.state.busy
                    || (action === 'accept'
                        && assessment.status === 'unsafe');
            }
        }, this);
    };

    Workspace.prototype._handleAdapterSelection = function (placementId) {
        if (this.suppressAdapterSelection === placementId) {
            this.suppressAdapterSelection = null;
            return;
        }
        this.session.select(placementId);
    };

    Workspace.prototype.handleViewSelection = function (id, event) {
        const additive = Boolean(event && (event.ctrlKey || event.metaKey));
        return this.session.select(id, {
            additive: additive,
            toggle: additive,
        });
    };

    Workspace.prototype.applyMarqueeSelection = function (ids, event) {
        return this.session.selectMany(Array.isArray(ids) ? ids : [], {
            additive: Boolean(event && (event.ctrlKey || event.metaKey)),
        });
    };

    Workspace.prototype._worldDelta = function (start, end) {
        const snapStep = this._activeSnapStep();
        return {
            x: snapCoordinate(end.x - start.x, snapStep),
            y: finite(end.y, 0) - finite(start.y, 0),
            z: snapCoordinate(end.z - start.z, snapStep),
        };
    };

    Workspace.prototype._setPlacementMovePreview = function (ids, delta) {
        if (!this.topAdapter
                || typeof this.topAdapter.setTransientPlacementMove
                    !== 'function') return false;
        return this.topAdapter.setTransientPlacementMove(ids || [], delta || null);
    };

    Workspace.prototype._setPlacementDuplicatePreview = function (ids, delta) {
        if (!this.topAdapter
                || typeof this.topAdapter.setTransientPlacementDuplicate
                    !== 'function') return false;
        return this.topAdapter.setTransientPlacementDuplicate(
            ids || [],
            delta || null
        );
    };

    Workspace.prototype._setZonePreview = function (points, options) {
        if (!this.topAdapter
                || typeof this.topAdapter.setTransientZonePreview
                    !== 'function') return false;
        return this.topAdapter.setTransientZonePreview(points || [], options || {});
    };

    Workspace.prototype._setFloorMarkingPreview = function (marking) {
        if (!this.topAdapter
                || typeof this.topAdapter.setTransientFloorMarkingPreview
                    !== 'function') return false;
        return this.topAdapter.setTransientFloorMarkingPreview(marking || null);
    };

    Workspace.prototype._setAislePreview = function (preview) {
        if (!this.topAdapter
                || typeof this.topAdapter.setTransientAislePreview
                    !== 'function') return false;
        return this.topAdapter.setTransientAislePreview(preview || null);
    };

    Workspace.prototype._rectangleZonePreviewPoints = function (start, end) {
        return [
            { x: start.x, z: start.z },
            { x: end.x, z: start.z },
            { x: end.x, z: end.z },
            { x: start.x, z: end.z },
        ];
    };

    Workspace.prototype._beginPointerCapture = function (event) {
        this._releasePointerCapture();
        const pointerId = event && Number.isFinite(Number(event.pointerId))
            ? Number(event.pointerId)
            : null;
        this.pointerCaptureId = pointerId;
        let captured = false;
        if (pointerId !== null
                && this.planView
                && typeof this.planView.setPointerCapture === 'function') {
            try {
                this.planView.setPointerCapture(pointerId);
                captured = true;
            } catch (error) {
                captured = false;
            }
        }
        if (captured || !this.document
                || typeof this.document.addEventListener !== 'function') return;
        const move = function (nextEvent) {
            if (this.planView.contains(nextEvent.target)) return;
            this._handlePlanPointerMove(nextEvent);
        }.bind(this);
        const up = function (nextEvent) {
            if (this.planView.contains(nextEvent.target)) return;
            this._handlePlanPointerUp(nextEvent);
        }.bind(this);
        const cancel = this._cancelPointerGesture.bind(this);
        this.document.addEventListener('pointermove', move);
        this.document.addEventListener('pointerup', up);
        this.document.addEventListener('pointercancel', cancel);
        this.pointerFallbackCleanup = function () {
            this.document.removeEventListener('pointermove', move);
            this.document.removeEventListener('pointerup', up);
            this.document.removeEventListener('pointercancel', cancel);
        }.bind(this);
    };

    Workspace.prototype._releasePointerCapture = function () {
        const pointerId = this.pointerCaptureId;
        this.pointerCaptureId = null;
        if (pointerId !== null
                && this.planView
                && typeof this.planView.releasePointerCapture === 'function') {
            try {
                if (typeof this.planView.hasPointerCapture !== 'function'
                        || this.planView.hasPointerCapture(pointerId)) {
                    this.planView.releasePointerCapture(pointerId);
                }
            } catch (error) {
                // The browser may release capture automatically after pointerup.
            }
        }
        if (this.pointerFallbackCleanup) this.pointerFallbackCleanup();
        this.pointerFallbackCleanup = null;
    };

    Workspace.prototype._handleLostPointerCapture = function () {
        if (!this.pointerGesture) return;
        this.pointerCaptureId = null;
        this._cancelPointerGesture();
    };

    Workspace.prototype._handleMirrorAxisPick = function (event) {
        if (!this.patternState.open
                || this.patternState.mode !== 'mirror'
                || !this.patternState.mirrorPicking) return false;
        let world;
        try {
            world = this._eventWorld(event);
        } catch (error) {
            this.patternMessage = error.message;
            this._renderPatternDialog();
            return true;
        }
        const gridStep = Math.max(
            0.000001,
            this.gridSize || DEFAULT_PLAN_GRID_METERS
        );
        if (this.patternState.mirrorAxisMode === 'vertical') {
            this.patternState.mirrorAxisX = snapCoordinate(world.x, gridStep);
            this.patternState.mirrorPicking = false;
            this.patternMessage = 'Vertical mirror axis selected.';
        } else if (this.patternState.mirrorAxisMode === 'horizontal') {
            this.patternState.mirrorAxisZ = snapCoordinate(world.z, gridStep);
            this.patternState.mirrorPicking = false;
            this.patternMessage = 'Horizontal mirror axis selected.';
        } else {
            const step = this._activeSnapStep();
            const point = {
                x: snapCoordinate(world.x, step),
                z: snapCoordinate(world.z, step),
            };
            if (!this.patternState.mirrorPickPoints.length) {
                this.patternState.mirrorPickPoints = [point];
                this.patternState.mirrorAxisStart = point;
                this.patternMessage = 'Pick the second construction-line point.';
            } else {
                const start = this.patternState.mirrorPickPoints[0];
                if (Math.hypot(point.x - start.x, point.z - start.z) < 1e-6) {
                    this.patternMessage = 'The second point must differ from the first.';
                } else {
                    this.patternState.mirrorAxisEnd = point;
                    this.patternState.mirrorPicking = false;
                    this.patternState.mirrorPickPoints = [];
                    this.patternMessage = 'Construction-line mirror axis selected.';
                }
            }
        }
        if (!this.patternState.mirrorPicking) {
            this.root.removeAttribute('data-mirror-axis-picking');
        }
        this._renderPatternDialog();
        return true;
    };

    Workspace.prototype._handlePlanPointerDown = function (event) {
        if (this.generationPlanningView && this.generationPlanningView.activeLayout()) {
            this.pointerGesture = {kind: 'pan', clientX: finite(event.clientX, 0), clientY: finite(event.clientY, 0)};
            this._beginPointerCapture(event);
            return;
        }
        if (targetDataId(
            event.target,
            'data-plan-settings-trigger',
            this.planView
        )) return;
        if (this._handleMirrorAxisPick(event)) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            if (typeof event.stopPropagation === 'function') event.stopPropagation();
            return;
        }
        if (this.toolMode === 'pan' || finite(event && event.button, 0) === 1) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this.pointerGesture = {
                kind: 'pan',
                clientX: finite(event.clientX, 0),
                clientY: finite(event.clientY, 0),
            };
            this._beginPointerCapture(event);
            return;
        }
        const world = this._eventWorld(event);
        if (this.toolMode === 'motion-path' && this.navigationState.open) {
            const waypointValue = targetDataId(
                event.target,
                'data-navigation-waypoint-index',
                this.planView
            );
            if (waypointValue !== null && waypointValue !== undefined) {
                const waypointIndex = Number(waypointValue);
                if (Number.isInteger(waypointIndex)
                        && waypointIndex >= 0
                        && waypointIndex
                            < this.navigationState.points.length) {
                    if (typeof event.preventDefault === 'function') {
                        event.preventDefault();
                    }
                    this.navigationState.selectedPointIndex = waypointIndex;
                    this.navigationState.selectedSegmentIndex = Math.min(
                        waypointIndex,
                        Math.max(0, this.navigationState.points.length - 2)
                    );
                    this.pointerGesture = {
                        kind: 'navigation-waypoint',
                        waypointIndex: waypointIndex,
                        start: world,
                        last: world,
                    };
                    this._beginPointerCapture(event);
                    this._syncNavigationAuthoringPreview();
                    this._renderNavigationDialog();
                    return;
                }
            }
            if (this.navigationState.anchorPicking) {
                if (typeof event.preventDefault === 'function') {
                    event.preventDefault();
                }
                this._placeNavigationAnchor({ x: world.x, z: world.z });
                return;
            }
            if (this.navigationState.drawing) {
                if (typeof event.preventDefault === 'function') {
                    event.preventDefault();
                }
                this._navigationAddPoint(world);
                return;
            }
        }
        const placementId = targetDataId(
            event.target,
            'data-placement-id',
            this.planView
        );
        if (placementId && this.toolMode === 'select') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            const additive = Boolean(event && (event.ctrlKey || event.metaKey));
            const duplicateIntent = additive
                && finite(event && event.button, 0) === 0;
            const alreadySelected = this.state.selection.includes(placementId);
            if (!duplicateIntent && (additive || !alreadySelected)) {
                this.handleViewSelection(placementId, event);
            }
            const sessionState = this.session.getState();
            const placementIds = new Set(
                sessionState.layout.placements.map(function (placement) {
                    return placement.placementId;
                })
            );
            const dragSelection = sessionState.selection.filter(
                function (identifier) {
                    return placementIds.has(identifier);
                }
            );
            this.suppressAdapterSelection = placementId;
            this.pointerGesture = {
                kind: 'move',
                placementId: placementId,
                placementIds: duplicateIntent
                    ? (alreadySelected && dragSelection.length
                        ? dragSelection : [placementId])
                    : (dragSelection.length ? dragSelection : [placementId]),
                start: world,
                last: world,
                startClientX: finite(event.clientX, 0),
                startClientY: finite(event.clientY, 0),
                duplicateIntent: duplicateIntent,
                duplicateActive: false,
            };
            this._beginPointerCapture(event);
            return;
        }
        const markingId = targetDataId(
            event.target,
            'data-floor-marking-id',
            this.planView
        );
        if (markingId && this.toolMode === 'select') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            const resizeHandle = targetDataId(
                event.target,
                'data-floor-marking-resize-handle',
                this.planView
            );
            const sessionState = this.session.getState();
            const marking = (sessionState.layout.floorMarkings || []).find(
                function (item) { return item.markingId === markingId; }
            );
            if (resizeHandle !== null && resizeHandle !== undefined) {
                if (!marking || marking.positionMode === 'locked') return;
                if (!this.state.selection.includes(markingId)) {
                    this.session.select(markingId);
                }
                this.suppressAdapterSelection = markingId;
                this.pointerGesture = {
                    kind: 'resize-floor-marking',
                    markingId: markingId,
                    handleIndex: Number(resizeHandle),
                    sourceMarking: clone(marking),
                    start: world,
                    last: world,
                };
                this._beginPointerCapture(event);
                return;
            }
            const additive = Boolean(event && (event.ctrlKey || event.metaKey));
            const duplicateIntent = additive
                && finite(event && event.button, 0) === 0;
            const alreadySelected = this.state.selection.includes(markingId);
            if (!duplicateIntent && (additive || !alreadySelected)) {
                this.handleViewSelection(markingId, event);
            }
            const movableIds = new Set(
                sessionState.layout.placements.map(function (placement) {
                    return placement.placementId;
                }).concat((sessionState.layout.floorMarkings || []).map(
                    function (marking) { return marking.markingId; }
                ))
            );
            const dragSelection = sessionState.selection.filter(
                function (identifier) { return movableIds.has(identifier); }
            );
            this.suppressAdapterSelection = markingId;
            if (marking && marking.positionMode === 'locked') return;
            this.pointerGesture = {
                kind: 'move',
                placementId: markingId,
                placementIds: duplicateIntent
                    ? (alreadySelected && dragSelection.length
                        ? dragSelection : [markingId])
                    : (dragSelection.length ? dragSelection : [markingId]),
                start: world,
                last: world,
                startClientX: finite(event.clientX, 0),
                startClientY: finite(event.clientY, 0),
                duplicateIntent: duplicateIntent,
                duplicateActive: false,
            };
            this._beginPointerCapture(event);
            return;
        }
        const zoneId = targetDataId(
            event.target,
            'data-zone-id',
            this.planView
        );
        if (zoneId && this.toolMode === 'select') {
            this.handleViewSelection(zoneId, event);
            this.suppressAdapterSelection = zoneId;
            return;
        }
        const routeId = targetDataId(
            event.target,
            'data-route-id',
            this.planView
        );
        if (routeId && this.toolMode === 'select') {
            this.handleViewSelection(routeId, event);
            this.suppressAdapterSelection = routeId;
            return;
        }
        if (this.toolMode === 'aisle' && this.aisleState.drawing) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this.pointerGesture = { kind: 'aisle', start: world, last: world };
            this._setAislePreview({
                points: [world, world],
                corridorWidth: this.aisleState.corridorWidth,
                color: this.aisleState.color,
            });
            this._showGesture('Draw ' + this.aisleState.label);
            this._beginPointerCapture(event);
            return;
        }
        if (this.toolMode === 'rectangle-zone') {
            this.pointerGesture = { kind: 'rectangle-zone', start: world, last: world };
            this._setZonePreview(
                this._rectangleZonePreviewPoints(world, world),
                { kind: 'rectangle', closed: true }
            );
            this._showGesture('Zone: ' + world.x.toFixed(2) + ', ' + world.z.toFixed(2));
            this._beginPointerCapture(event);
            return;
        }
        if (this.toolMode === 'floor-marking') {
            this.pointerGesture = {
                kind: 'floor-marking',
                start: world,
                last: world,
            };
            this._setFloorMarkingPreview(
                this._floorMarkingFromGesture(world, world)
            );
            this._showGesture(
                this._floorMarkingPreset(this.floorMarkingState.type).label
            );
            this._beginPointerCapture(event);
            return;
        }
        if (this.toolMode === 'select') {
            this.pointerGesture = { kind: 'marquee', start: world, last: world };
            this._showGesture('Selection');
            this._beginPointerCapture(event);
        }
    };

    Workspace.prototype._handlePlanPointerMove = function (event) {
        if (this.pointerGesture && this.pointerGesture.kind === 'pan') {
            const clientX = finite(event.clientX, this.pointerGesture.clientX);
            const clientY = finite(event.clientY, this.pointerGesture.clientY);
            if (this.topAdapter
                    && typeof this.topAdapter.panByPixels === 'function') {
                this.topAdapter.panByPixels(
                    clientX - this.pointerGesture.clientX,
                    clientY - this.pointerGesture.clientY
                );
            }
            this.pointerGesture.clientX = clientX;
            this.pointerGesture.clientY = clientY;
            return;
        }
        let world;
        try {
            world = this._eventWorld(event);
        } catch (error) {
            return;
        }
        this._setCoordinates(world);
        if (!this.pointerGesture) {
            if (this.toolMode === 'polygon-zone' && this.polygonPoints.length) {
                this._setZonePreview(
                    this.polygonPoints.concat([world]),
                    { kind: 'polygon', closed: false }
                );
            }
            return;
        }
        this.pointerGesture.last = world;
        if (this.pointerGesture.kind === 'navigation-waypoint') {
            const snapped = this._navigationSnapPoint(world);
            const index = this.pointerGesture.waypointIndex;
            this.navigationState.points[index] = {
                x: Number(Number(snapped.point.x).toFixed(6)),
                z: Number(Number(snapped.point.z).toFixed(6)),
            };
            this.navigationState.snapRefs = this.navigationState.snapRefs
                .filter(function (item) { return item.pointIndex !== index; });
            if (snapped.refKind) {
                this.navigationState.snapRefs.push({
                    pointIndex: index,
                    refKind: snapped.refKind,
                    refId: snapped.refId,
                });
            }
            this.navigationState.validationStatus = 'pending';
            this.navigationState.validation = null;
            this.navigationState.message = 'Waypoint moved by Plan pointer.';
            this._syncNavigationAuthoringPreview();
        } else if (this.pointerGesture.kind === 'move') {
            const delta = this._worldDelta(this.pointerGesture.start, world);
            if (this.pointerGesture.duplicateIntent) {
                const distance = Math.hypot(
                    finite(event.clientX, this.pointerGesture.startClientX)
                        - this.pointerGesture.startClientX,
                    finite(event.clientY, this.pointerGesture.startClientY)
                        - this.pointerGesture.startClientY
                );
                if (!this.pointerGesture.duplicateActive
                        && distance < DUPLICATE_DRAG_THRESHOLD_PX) return;
                this.pointerGesture.duplicateActive = true;
                this._setPlacementDuplicatePreview(
                    this.pointerGesture.placementIds,
                    delta
                );
                this._showGesture(
                    this.pointerGesture.placementIds.length === 1
                        ? 'Duplicate placement'
                        : 'Duplicate '
                            + this.pointerGesture.placementIds.length
                            + ' placements'
                );
            } else {
                this._setPlacementMovePreview(
                    this.pointerGesture.placementIds,
                    delta
                );
            }
        } else if (this.pointerGesture.kind === 'rectangle-zone') {
            this._setZonePreview(
                this._rectangleZonePreviewPoints(
                    this.pointerGesture.start,
                    world
                ),
                { kind: 'rectangle', closed: true }
            );
            this._showGesture(
                'Zone ' + Math.abs(world.x - this.pointerGesture.start.x).toFixed(2)
                + ' x ' + Math.abs(world.z - this.pointerGesture.start.z).toFixed(2)
            );
        } else if (this.pointerGesture.kind === 'floor-marking') {
            const marking = this._floorMarkingFromGesture(
                this.pointerGesture.start,
                world
            );
            this._setFloorMarkingPreview(marking);
            this._showGesture(
                marking.label + '  '
                + marking.width.toFixed(2) + ' x '
                + marking.depth.toFixed(2) + ' m'
            );
        } else if (this.pointerGesture.kind === 'aisle') {
            this._setAislePreview({
                points: [this.pointerGesture.start, world],
                corridorWidth: this.aisleState.corridorWidth,
                color: this.aisleState.color,
            });
            this._showGesture(
                this.aisleState.label + '  '
                + Math.hypot(
                    world.x - this.pointerGesture.start.x,
                    world.z - this.pointerGesture.start.z
                ).toFixed(2) + ' m long'
            );
        } else if (this.pointerGesture.kind === 'resize-floor-marking') {
            const marking = resizeFloorMarkingFromHandle(
                this.pointerGesture.sourceMarking,
                this.pointerGesture.handleIndex,
                world,
                this._activeSnapStep()
            );
            this.pointerGesture.preview = marking;
            this._setFloorMarkingPreview(marking);
            this._showGesture(
                'Resize  ' + marking.width.toFixed(2) + ' x '
                + marking.depth.toFixed(2) + ' m'
            );
        } else if (this.pointerGesture.kind === 'marquee') {
            this._showGesture('Selection region');
        }
    };

    Workspace.prototype._handlePlanPointerUp = function (event) {
        const gesture = this.pointerGesture;
        this.pointerGesture = null;
        this._releasePointerCapture();
        this._hideGesture();
        if (!gesture) return;
        if (gesture.kind === 'pan') return;
        const end = this._eventWorld(event);
        if (gesture.kind === 'navigation-waypoint') {
            this.navigationState.message = (
                'Waypoint updated locally. Apply path to create one unsaved gesture.'
            );
            this._syncNavigationAuthoringPreview();
            this._renderNavigationDialog();
            return;
        }
        if (gesture.kind === 'move') {
            const delta = this._worldDelta(gesture.start, end);
            if (gesture.duplicateIntent) {
                if (!gesture.duplicateActive) {
                    this._setPlacementDuplicatePreview([], null);
                    this.handleViewSelection(gesture.placementId, {
                        ctrlKey: true,
                    });
                    return;
                }
                if (delta.x || delta.y || delta.z) {
                    this._invoke(
                        gesture.placementIds.length === 1
                            ? 'Duplicate placement' : 'Duplicate placements',
                        function () {
                            const duplicate = typeof this.session
                                .duplicateItems === 'function'
                                ? this.session.duplicateItems.bind(this.session)
                                : (typeof this.session.duplicatePlacements === 'function'
                                    ? this.session.duplicatePlacements.bind(
                                        this.session
                                    ) : null);
                            if (!duplicate) {
                                throw new Error(
                                    'Targeted item duplication is unavailable'
                                );
                            }
                            return Promise.resolve(duplicate(
                                gesture.placementIds,
                                delta
                            )).finally(function () {
                                this._setPlacementDuplicatePreview([], null);
                            }.bind(this));
                        }.bind(this)
                    );
                } else {
                    this._setPlacementDuplicatePreview([], null);
                }
                return;
            }
            if (delta.x || delta.y || delta.z) {
                this._invoke('Move selection', function () {
                    return Promise.resolve(this.session.moveSelected(delta))
                        .finally(function () {
                            this._setPlacementMovePreview([], null);
                        }.bind(this));
                }.bind(this));
            } else {
                this._setPlacementMovePreview([], null);
            }
            return;
        }
        if (gesture.kind === 'rectangle-zone') {
            this._setZonePreview([], {});
            if (gesture.start.x !== end.x || gesture.start.z !== end.z) {
                this._invoke('Create rectangle zone', function () {
                    return this.session.createRectangleZone(
                        gesture.start,
                        end,
                        { label: 'New zone', zoneType: 'workcell' }
                    );
                }.bind(this));
            }
            return;
        }
        if (gesture.kind === 'floor-marking') {
            const marking = this._floorMarkingFromGesture(gesture.start, end);
            this._setFloorMarkingPreview(null);
            this._invoke('Create floor marking', function () {
                return this.session.createFloorMarking(marking);
            }.bind(this));
            return;
        }
        if (gesture.kind === 'aisle') {
            this._setAislePreview(null);
            if (Math.hypot(end.x - gesture.start.x, end.z - gesture.start.z)
                    <= 0.001) return;
            const request = {
                label: this.aisleState.label,
                aisleKind: this.aisleState.aisleKind,
                direction: this.aisleState.direction,
                color: this.aisleState.color,
                corridorWidth: this.aisleState.corridorWidth,
                centerline: [
                    { x: gesture.start.x, y: 0, z: gesture.start.z },
                    { x: end.x, y: 0, z: end.z },
                ],
                clearanceEvidenceStatus: 'unverified',
            };
            this._invoke('Create facility aisle', function () {
                return this.session.createAisle(request);
            }.bind(this)).then(function () {
                this.aisleState.sequence += 1;
                const name = this.aisleState.aisleKind === 'forklift'
                    ? 'Forklift Aisle'
                    : (this.aisleState.aisleKind === 'pedestrian'
                        ? 'Pedestrian Aisle' : 'Material Aisle');
                this.aisleState.label = name + ' ' + this.aisleState.sequence;
                this._renderAisleDialog();
            }.bind(this));
            return;
        }
        if (gesture.kind === 'resize-floor-marking') {
            const marking = resizeFloorMarkingFromHandle(
                gesture.sourceMarking,
                gesture.handleIndex,
                end,
                this._activeSnapStep()
            );
            this._setFloorMarkingPreview(null);
            this._invoke('Resize floor marking', function () {
                return this.session.editFloorMarking(gesture.markingId, {
                    width: marking.width,
                    depth: marking.depth,
                    transform: clone(marking.transform),
                    positionMode: 'manual',
                });
            }.bind(this));
            return;
        }
        if (gesture.kind === 'marquee') {
            const resolver = this.marqueeResolver
                || (this.topAdapter
                    && typeof this.topAdapter.resolveMarquee === 'function'
                    ? this.topAdapter.resolveMarquee.bind(this.topAdapter)
                    : null);
            if (resolver) {
                const ids = resolver({
                    start: gesture.start,
                    end: end,
                    layout: clone(this.state.layout),
                    event: event,
                });
                this.applyMarqueeSelection(ids, event);
            } else if (!event.ctrlKey && !event.metaKey) {
                this.session.clearSelection();
            }
        }
    };

    Workspace.prototype._handlePlanWheel = function (event) {
        if (!this.topAdapter
                || typeof this.topAdapter.zoomAt !== 'function') return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        const delta = finite(event.deltaY, 0);
        const factor = Math.exp(-delta * 0.0015);
        this.topAdapter.zoomAt(event, factor);
        const world = this._tryEventWorld(event);
        if (world) this._setCoordinates(world);
    };

    Workspace.prototype._cancelPointerGesture = function () {
        if (this.pointerGesture && this.pointerGesture.kind === 'move') {
            this._setPlacementMovePreview([], null);
            this._setPlacementDuplicatePreview([], null);
        }
        this._setZonePreview([], {});
        this._setFloorMarkingPreview(null);
        this._setAislePreview(null);
        this.pointerGesture = null;
        this._releasePointerCapture();
        this._hideGesture();
    };

    Workspace.prototype._handlePlanClick = function (event) {
        if (this.toolMode !== 'polygon-zone') return;
        if (targetDataId(event.target, 'data-placement-id', this.planView)) return;
        const world = this._eventWorld(event);
        siteRuntime.appendPolygonVertex(this.polygonPoints, world);
        this._setZonePreview(
            this.polygonPoints,
            { kind: 'polygon', closed: false }
        );
        this._showGesture(this.polygonPoints.length + ' polygon points');
    };

    Workspace.prototype._handlePlanDoubleClick = function (event) {
        if (this.generationPlanningView && this.generationPlanningView.activeLayout()) return;
        const trigger = targetDataId(
            event.target,
            'data-plan-settings-trigger',
            this.planView
        );
        if (trigger) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            if (typeof event.stopPropagation === 'function') {
                event.stopPropagation();
            }
            this.openPlanSettingsDialog(trigger);
            return;
        }
        if (this.toolMode === 'polygon-zone') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._finishPolygon();
        }
    };

    Workspace.prototype._handlePlanOverlayKeyDown = function (event) {
        const trigger = targetDataId(
            event.target,
            'data-plan-settings-trigger',
            this.planView
        );
        if (!trigger || !['Enter', ' '].includes(String(event.key || ''))) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (typeof event.stopPropagation === 'function') event.stopPropagation();
        this.openPlanSettingsDialog(trigger);
    };

    Workspace.prototype._finishPolygon = function () {
        if (this.polygonPoints.length < 3) return false;
        const points = this.polygonPoints.slice();
        this.polygonPoints = [];
        this._setZonePreview([], {});
        this._hideGesture();
        this._invoke('Create polygon zone', function () {
            return this.session.createPolygonZone(
                points,
                { label: 'New zone', zoneType: 'workcell' }
            );
        }.bind(this));
        return true;
    };

    Workspace.prototype._showGesture = function (text) {
        this.gestureOverlay.hidden = false;
        this.gestureOverlay.textContent = text;
    };

    Workspace.prototype._hideGesture = function () {
        this.gestureOverlay.hidden = true;
        this.gestureOverlay.textContent = '';
    };

    Workspace.prototype._activeSnapStep = function () {
        if (!this.planPreferences.snapToGrid) return 0;
        return this.planPreferences.unit === 'ft'
            ? 1 / METERS_TO_FEET
            : this.gridSize;
    };

    Workspace.prototype._storePlanPreferences = function () {
        storePlanPreferences(
            this.planPreferenceStorage,
            this.planPreferenceKey,
            this.planPreferences
        );
    };

    Workspace.prototype._setPlanPreference = function (name, value) {
        const next = normalizePlanPreferences(Object.assign(
            {},
            this.planPreferences,
            { [name]: value }
        ));
        this.planPreferences = next;
        this._storePlanPreferences();
        if (this.topAdapter
                && typeof this.topAdapter.setViewPreferences === 'function') {
            this.topAdapter.setViewPreferences({
                displayUnit: next.unit,
                showGrid: next.showGrid,
            });
        } else {
            this._renderPlanSpatialOverlays();
        }
        this._renderProperties();
        this._renderPlanNavigationState();
        this._setCoordinates(this.lastPointerWorld);
        this._renderStatus();
        return clone(next);
    };

    Workspace.prototype._renderPlanRulerTick = function (
        parent,
        orientation,
        screenPosition,
        value,
        major
    ) {
        const tick = element(this.document, 'span', {
            className: 'ip-flw-plan-ruler-tick'
                + (major ? ' ip-flw-plan-ruler-tick-major' : ''),
            style: (orientation === 'x' ? 'left:' : 'top:')
                + Number(screenPosition.toFixed(2)) + 'px',
            'data-ruler-value': Number(value.toFixed(6)),
        });
        if (major) {
            tick.appendChild(element(this.document, 'span', {
                className: 'ip-flw-plan-ruler-label',
            }, formattedDistance(displayDistance(
                value,
                this.planPreferences.unit
            ))));
        }
        parent.appendChild(tick);
    };

    Workspace.prototype._renderPlanSpatialOverlays = function (snapshot) {
        if (this.destroyed) return false;
        let current = snapshot;
        if (!current && this.topAdapter
                && typeof this.topAdapter.getViewportState === 'function') {
            current = this.topAdapter.getViewportState();
        }
        const projection = current && current.projection;
        const visible = Boolean(projection && finite(projection.scale, 0) > 0);
        [
            this.planRulerCorner,
            this.planTopRuler,
            this.planLeftRuler,
            this.planScaleBar,
            this.planCompass,
            this.planNavigation,
        ].forEach(function (node) {
            if (node) node.hidden = !visible;
        });
        if (!visible) return false;

        clearElement(this.planTopRuler);
        clearElement(this.planLeftRuler);
        // The markers are children of the rulers, so they have to be put back
        // after each clear, and the projection is retained so pointer moves can
        // place them without asking the adapter for viewport state again.
        this.planTopRuler.appendChild(this.planTopRulerCursor);
        this.planLeftRuler.appendChild(this.planLeftRulerCursor);
        this.planProjection = projection;
        const width = Math.max(1, finite(projection.width, 1));
        const height = Math.max(1, finite(projection.height, 1));
        const topLeft = planWorldAtScreen(projection, 0, 0);
        const bottomRight = planWorldAtScreen(projection, width, height);
        const grid = current.grid || { spacing: 1, majorSpacing: 5 };
        let minorSpacing = Math.max(0.000001, finite(grid.spacing, 1));
        while (minorSpacing * projection.scale < 12) minorSpacing *= 2;
        const majorSpacing = Math.max(
            minorSpacing,
            finite(grid.majorSpacing, minorSpacing * 5)
        );
        const xValues = alignedValues(
            Math.min(topLeft.x, bottomRight.x),
            Math.max(topLeft.x, bottomRight.x),
            minorSpacing,
            320
        );
        const zValues = alignedValues(
            Math.min(topLeft.z, bottomRight.z),
            Math.max(topLeft.z, bottomRight.z),
            minorSpacing,
            320
        );
        const isMajor = function (value) {
            const quotient = value / majorSpacing;
            return Math.abs(quotient - Math.round(quotient)) < 0.000001;
        };
        xValues.forEach(function (value) {
            const screen = planScreenForWorld(projection, value, 0);
            this._renderPlanRulerTick(
                this.planTopRuler,
                'x',
                screen.x,
                value,
                isMajor(value)
            );
        }, this);
        zValues.forEach(function (value) {
            const screen = planScreenForWorld(projection, 0, value);
            this._renderPlanRulerTick(
                this.planLeftRuler,
                'z',
                screen.y,
                value,
                isMajor(value)
            );
        }, this);

        const scale = preferredScaleDistance(
            projection.scale,
            this.planPreferences.unit
        );
        const scaleWidth = Math.max(44, Math.min(220, scale.pixels));
        this.planScaleTrack.setAttribute(
            'style',
            'width:' + Number(scaleWidth.toFixed(2)) + 'px'
        );
        this.planScaleLabel.textContent = formattedDistance(
            scale.displayDistance
        ) + ' ' + this.planPreferences.unit;
        this.planScaleBar.setAttribute(
            'aria-label',
            'Plan scale: ' + this.planScaleLabel.textContent
        );
        this.planRulerCorner.textContent = 'X/Z ' + this.planPreferences.unit;
        this._renderPlanNavigationState();
        return true;
    };

    Workspace.prototype._renderPlanNavigationState = function () {
        if (!this.planNavigation) return;
        const state = {
            select: this.toolMode === 'select',
            pan: this.toolMode === 'pan',
            grid: this.planPreferences.showGrid,
            snap: this.planPreferences.snapToGrid,
        };
        Object.keys(state).forEach(function (command) {
            const button = this.planNavigation.querySelector(
                '[data-plan-command="' + command + '"]'
            );
            if (button) button.setAttribute(
                'aria-pressed',
                state[command] ? 'true' : 'false'
            );
        }, this);
        const unit = this.planNavigation.querySelector(
            '[data-plan-command="unit"]'
        );
        if (unit) {
            unit.textContent = this.planPreferences.unit;
            const next = this.planPreferences.unit === 'm' ? 'feet' : 'meters';
            unit.setAttribute('aria-label', 'Display distances in ' + next);
            unit.setAttribute('title', 'Display distances in ' + next);
        }
    };

    Workspace.prototype._planViewCenterEvent = function () {
        const rect = typeof this.planView.getBoundingClientRect === 'function'
            ? this.planView.getBoundingClientRect() : null;
        const width = Math.max(
            1,
            finite(rect && rect.width, this.planView.clientWidth || 1)
        );
        const height = Math.max(
            1,
            finite(rect && rect.height, this.planView.clientHeight || 1)
        );
        return {
            clientX: finite(rect && rect.left, 0) + width / 2,
            clientY: finite(rect && rect.top, 0) + height / 2,
        };
    };

    Workspace.prototype._handlePlanNavigationClick = function (event) {
        if (typeof event.stopPropagation === 'function') event.stopPropagation();
        const command = targetDataId(
            event.target,
            'data-plan-command',
            this.planNavigation
        );
        if (!command) return;
        if (command === 'select' || command === 'pan') {
            this.executeCommand(command);
        } else if (command === 'zoom-in' || command === 'zoom-out') {
            if (this.topAdapter
                    && typeof this.topAdapter.zoomAt === 'function') {
                this.topAdapter.zoomAt(
                    this._planViewCenterEvent(),
                    command === 'zoom-in' ? 1.25 : 0.8
                );
            }
        } else if (command === 'fit-facility' || command === 'reset-view') {
            this.executeCommand('fit');
        } else if (command === 'fit-layout') {
            this.executeCommand('fit-layout');
        } else if (command === 'grid') {
            this._setPlanPreference('showGrid', !this.planPreferences.showGrid);
        } else if (command === 'snap') {
            this._setPlanPreference(
                'snapToGrid',
                !this.planPreferences.snapToGrid
            );
        } else if (command === 'layers') {
            this._setLayerPanelOpen(!this.layerPanelOpen);
        } else if (command === 'unit') {
            this._setPlanPreference(
                'unit',
                this.planPreferences.unit === 'm' ? 'ft' : 'm'
            );
        }
    };

    Workspace.prototype._storeThreeViewpoints = function () {
        return storeThreeViewpoints(
            this.planPreferenceStorage,
            this.threeViewpointKey,
            this.threeViewpoints
        );
    };

    Workspace.prototype._renderThreeViewpoints = function () {
        if (!this.threeViewpointList) return;
        clearElement(this.threeViewpointList);
        if (!this.threeViewpoints.length) {
            this.threeViewpointList.appendChild(element(this.document, 'p', {
                className: 'ip-flw-three-viewpoint-empty',
            }, 'No saved viewpoints.'));
            return;
        }
        this.threeViewpoints.forEach(function (viewpoint) {
            const row = element(this.document, 'div', {
                className: 'ip-flw-three-viewpoint-row',
                role: 'listitem',
            });
            const go = element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-three-viewpoint-go',
                'data-viewpoint-action': 'apply',
                'data-viewpoint-id': viewpoint.viewpointId,
                title: 'Go to ' + viewpoint.name,
            }, viewpoint.name);
            const remove = element(this.document, 'button', {
                type: 'button',
                className: 'ip-flw-three-viewpoint-delete',
                'data-viewpoint-action': 'delete',
                'data-viewpoint-id': viewpoint.viewpointId,
                'aria-label': 'Delete ' + viewpoint.name,
                title: 'Delete ' + viewpoint.name,
            }, 'X');
            append(row, go, remove);
            this.threeViewpointList.appendChild(row);
        }, this);
    };

    Workspace.prototype._setThreeViewpointsOpen = function (open) {
        this.threeViewpointsOpen = open === true;
        if (this.threeViewpointsOpen) {
            this.layerPanelOpen = false;
            if (this.layerPanel) this.layerPanel.hidden = true;
            this.threeSettingsOpen = false;
            this.threeViewMenuOpen = false;
            if (this.threeSettingsPanel) this.threeSettingsPanel.hidden = true;
        }
        this._renderThreeNavigationState();
        if (this.threeViewpointsOpen && this.threeViewpointInput
                && typeof this.threeViewpointInput.focus === 'function') {
            this.threeViewpointInput.focus();
        }
    };

    Workspace.prototype._saveThreeViewpoint = function () {
        if (!this.threeAdapter
                || typeof this.threeAdapter.getCameraView !== 'function') {
            return false;
        }
        const camera = normalizeThreeCameraView(
            this.threeAdapter.getCameraView()
        );
        if (!camera) return false;
        const existingNames = new Set(this.threeViewpoints.map(function (item) {
            return item.name.toLowerCase();
        }));
        let name = cleanString(
            this.threeViewpointInput && this.threeViewpointInput.value,
            'Viewpoint ' + (this.threeViewpoints.length + 1)
        ).slice(0, 60);
        const baseName = name;
        let suffix = 2;
        while (existingNames.has(name.toLowerCase())) {
            name = (baseName + ' ' + suffix).slice(0, 60);
            suffix += 1;
        }
        let viewpointId = '';
        do {
            threeViewpointSequence += 1;
            viewpointId = 'viewpoint-' + threeViewpointSequence;
        } while (this.threeViewpoints.some(function (item) {
            return item.viewpointId === viewpointId;
        }));
        this.threeViewpoints.push({
            viewpointId: viewpointId,
            name: name,
            camera: camera,
        });
        this.threeViewpoints = normalizeThreeViewpoints(this.threeViewpoints);
        this._storeThreeViewpoints();
        if (this.threeViewpointInput) this.threeViewpointInput.value = '';
        this._renderThreeViewpoints();
        if (this.advisoryLiveRegion) {
            this.advisoryLiveRegion.textContent = name + ' saved.';
        }
        return true;
    };

    Workspace.prototype._applyThreeViewpoint = function (viewpointId) {
        const viewpoint = this.threeViewpoints.find(function (item) {
            return item.viewpointId === viewpointId;
        });
        if (!viewpoint || !this.threeAdapter
                || typeof this.threeAdapter.applyCameraView !== 'function') {
            return false;
        }
        const applied = this.threeAdapter.applyCameraView(viewpoint.camera);
        if (applied !== false) {
            this.threeNavigationMode = viewpoint.camera.navigationMode;
            this._setThreeViewpointsOpen(false);
            if (this.advisoryLiveRegion) {
                this.advisoryLiveRegion.textContent =
                    'Moved to ' + viewpoint.name + '.';
            }
        }
        return applied !== false;
    };

    Workspace.prototype._deleteThreeViewpoint = function (viewpointId) {
        const before = this.threeViewpoints.length;
        this.threeViewpoints = this.threeViewpoints.filter(function (item) {
            return item.viewpointId !== viewpointId;
        });
        if (this.threeViewpoints.length === before) return false;
        this._storeThreeViewpoints();
        this._renderThreeViewpoints();
        if (this.advisoryLiveRegion) {
            this.advisoryLiveRegion.textContent = 'Viewpoint deleted.';
        }
        return true;
    };

    Workspace.prototype._renderThreeNavigationState = function () {
        const appearance = this.threeNavigation.querySelector('[data-three-command="appearance"]');
        if (appearance) appearance.disabled = !this._canEditAppearance();
        if (!this.threeNavigation) return;
        ['orbit', 'pan'].forEach(function (command) {
            const button = this.threeNavigation.querySelector(
                '[data-three-command="' + command + '"]'
            );
            if (button) button.setAttribute(
                'aria-pressed',
                command === this.threeNavigationMode ? 'true' : 'false'
            );
        }, this);
        const walkthrough = this.threeNavigation.querySelector(
            '[data-three-command="walkthrough"]'
        );
        if (walkthrough) {
            walkthrough.disabled = this.threeWalkthrough.supported === false;
            walkthrough.setAttribute(
                'aria-pressed',
                this.threeWalkthrough.active ? 'true' : 'false'
            );
            const label = this.threeWalkthrough.active
                ? 'Exit walkthrough and return to overview'
                : 'Walk through facility at human height';
            walkthrough.setAttribute('aria-label', label);
            walkthrough.setAttribute('title', label);
        }
        if (this.walkCameraControl && this.threeWalkthrough.cameraSettings)
            this.walkCameraControl.sync(this.threeWalkthrough.cameraSettings);
        const avatarView = this.threeNavigation.querySelector('[data-three-command="avatar-view"]');
        if (avatarView) {
            const thirdPerson = this.threeWalkthrough.cameraMode === 'third-person';
            avatarView.disabled = this.threeWalkthrough.supported === false
                || this.threeWalkthrough.avatarSupported === false;
            avatarView.setAttribute('aria-pressed', thirdPerson ? 'true' : 'false');
            const label = thirdPerson ? 'Use first-person Walkthrough (C)' : 'Show avatar in Walkthrough (C)';
            avatarView.setAttribute('aria-label', label);
            avatarView.setAttribute('title', label);
        }
        const drone = this.threeNavigation.querySelector(
            '[data-three-command="drone"]'
        );
        if (drone) {
            drone.disabled = this.threeDrone.supported === false;
            drone.setAttribute(
                'aria-pressed',
                this.threeDrone.active ? 'true' : 'false'
            );
            const label = this.threeDrone.active
                ? 'Exit Drone mode and return to overview'
                : 'Fly through facility in assisted Drone mode';
            drone.setAttribute('aria-label', label);
            drone.setAttribute('title', label);
        }
        const switchImmersive = this.threeNavigation.querySelector(
            '[data-three-command="switch-immersive"]'
        );
        if (switchImmersive) {
            const active = this.threeWalkthrough.active
                || this.threeDrone.active;
            switchImmersive.disabled = !active
                || this.threeWalkthrough.supported === false
                || this.threeDrone.supported === false;
            const label = this.threeDrone.active
                ? 'Continue from here in Walkthrough mode (G)'
                : (this.threeWalkthrough.active
                    ? 'Continue from here in Drone mode (G)'
                    : 'Enter Walkthrough or Drone mode to switch navigation');
            switchImmersive.setAttribute('aria-label', label);
            switchImmersive.setAttribute('title', label);
        }
        const walkToSelected = this.threeNavigation.querySelector(
            '[data-three-command="walk-to-selected"]'
        );
        if (walkToSelected) {
            const selectedIds = new Set(
                this.state && Array.isArray(this.state.selection)
                    ? this.state.selection : []
            );
            const selected = this.state && this.state.layout
                && Array.isArray(this.state.layout.placements)
                ? this.state.layout.placements.filter(function (placement) {
                    return selectedIds.has(placement.placementId);
                }) : [];
            walkToSelected.disabled = this.threeWalkthrough.supported === false
                || selected.length !== 1;
        }
        if (this.threeWalkthroughHud) {
            this.threeWalkthroughHud.hidden = !this.threeWalkthrough.active;
            this.threeWalkthroughHud.setAttribute(
                'data-pointer-locked',
                this.threeWalkthrough.locked ? 'true' : 'false'
            );
        }
        if (this.threeWalkthroughTitle) {
            const route = this.threeWalkthrough.route || {};
            this.threeWalkthroughTitle.textContent = route.active
                ? 'Navigating' : 'Walkthrough';
        }
        if (this.threeDroneHud) {
            this.threeDroneHud.hidden = !this.threeDrone.active;
            this.threeDroneHud.setAttribute(
                'data-pointer-locked',
                this.threeDrone.locked ? 'true' : 'false'
            );
        }
        const unit = normalizedDistanceUnit(
            this.planPreferences && this.planPreferences.unit
        );
        if (this.threeDroneAltitude) {
            this.threeDroneAltitude.textContent = 'ALT '
                + formattedDistance(displayDistance(
                    this.threeDrone.altitude,
                    unit
                )) + ' ' + unit;
        }
        if (this.threeDroneSpeed) {
            this.threeDroneSpeed.textContent = 'SPD '
                + formattedDistance(displayDistance(
                    this.threeDrone.currentSpeed,
                    unit
                )) + ' ' + unit + '/s';
        }
        if (this.threeDroneObstacle) {
            const obstacle = Number.isFinite(Number(
                this.threeDrone.nearestObstacleDistance
            ))
                ? formattedDistance(displayDistance(
                    this.threeDrone.nearestObstacleDistance,
                    unit
                )) + ' ' + unit
                : 'clear';
            this.threeDroneObstacle.textContent = 'OBS ' + obstacle;
        }
        if (this.threeDroneAssist) {
            this.threeDroneAssist.textContent = this.threeDrone.assistedFlight
                ? 'Assisted' : 'Free flight';
            this.threeDroneAssist.setAttribute(
                'data-enabled',
                this.threeDrone.assistedFlight ? 'true' : 'false'
            );
        }
        if (this.threeWalkthroughCrosshair) {
            this.threeWalkthroughCrosshair.hidden =
                !this.threeWalkthrough.active && !this.threeDrone.active;
        }
        if (this.root) {
            this.root.setAttribute(
                'data-walkthrough-active',
                this.threeWalkthrough.active ? 'true' : 'false'
            );
            this.root.setAttribute(
                'data-drone-active',
                this.threeDrone.active ? 'true' : 'false'
            );
        }
        const grid = this.threeNavigation.querySelector(
            '[data-three-command="grid"]'
        );
        if (grid) {
            grid.setAttribute(
                'aria-pressed',
                this.threeGridVisible ? 'true' : 'false'
            );
            const label = this.threeGridVisible
                ? 'Hide floor grid' : 'Show floor grid';
            grid.setAttribute('aria-label', label);
            grid.setAttribute('title', label);
        }
        const display = this.threeNavigation.querySelector(
            '[data-three-command="display-settings"]'
        );
        if (display) {
            display.setAttribute(
                'aria-pressed',
                this.threeSettingsOpen ? 'true' : 'false'
            );
            display.setAttribute(
                'aria-expanded',
                this.threeSettingsOpen ? 'true' : 'false'
            );
        }
        if (this.threeViewOrientationTrigger) {
            this.threeViewOrientationTrigger.setAttribute(
                'aria-expanded',
                this.threeViewMenuOpen ? 'true' : 'false'
            );
            this.threeViewOrientationTrigger.setAttribute(
                'aria-pressed',
                this.threeViewMenuOpen ? 'true' : 'false'
            );
            this.threeViewOrientationTrigger.setAttribute(
                'data-selected-view',
                this.threeOrientation
            );
            const icon = this.threeViewOrientationTrigger.querySelector('img');
            if (icon) icon.setAttribute('src', threeViewIconSrc(
                this.threeOrientation
            ));
        }
        if (this.threeViewOrientationMenu) {
            this.threeViewOrientationMenu.hidden = !this.threeViewMenuOpen;
            THREE_VIEW_ORIENTATIONS.forEach(function (view) {
                const item = this.threeViewOrientationMenu.querySelector(
                    '[data-three-view="' + view.key + '"]'
                );
                if (item) item.setAttribute(
                    'aria-current',
                    view.key === this.threeOrientation ? 'true' : 'false'
                );
            }, this);
        }
        if (this.threeViewpointTrigger) {
            this.threeViewpointTrigger.setAttribute(
                'aria-expanded',
                this.threeViewpointsOpen ? 'true' : 'false'
            );
            this.threeViewpointTrigger.setAttribute(
                'aria-pressed',
                this.threeViewpointsOpen ? 'true' : 'false'
            );
        }
        if (this.threeViewpointPanel) {
            this.threeViewpointPanel.hidden = !this.threeViewpointsOpen;
        }
        this._renderWalkthroughContext();
        this._renderRecordingState();
    };

    Workspace.prototype._renderThreeCompass = function (value) {
        if (!this.threeCompass) return false;
        const orientation = compassHeading(
            value && value.headingDegrees
        );
        this.threeCompassOrientation = orientation;
        const degrees = orientation.headingDegrees.toFixed(1);
        const ringRotation = (-orientation.headingDegrees).toFixed(3) + 'deg';
        const labelRotation = orientation.headingDegrees.toFixed(3) + 'deg';
        this.threeCompass.setAttribute('data-heading-degrees', degrees);
        this.threeCompass.setAttribute(
            'data-heading-cardinal',
            orientation.cardinal
        );
        const description = (value && value.reference === 'true-north'
            ? 'Site orientation, true north. The top of the view points '
            : 'Facility orientation. North is positive Z and east is positive X. The top of the view points ')
            + orientation.cardinal + ' at ' + degrees + ' degrees from north.';
        this.threeCompass.setAttribute('aria-label', description);
        this.threeCompass.setAttribute('title', description);
        if (this.threeCompass.style
                && typeof this.threeCompass.style.setProperty === 'function') {
            this.threeCompass.style.setProperty(
                '--ip-flw-three-compass-ring-rotation',
                ringRotation
            );
            this.threeCompass.style.setProperty(
                '--ip-flw-three-compass-label-rotation',
                labelRotation
            );
        }
        return true;
    };

    Workspace.prototype._walkthroughContextPlacement = function (placementId) {
        if (!placementId || !this.state || !this.state.layout) return null;
        return (this.state.layout.placements || []).find(function (placement) {
            return placement.placementId === placementId;
        }) || null;
    };

    Workspace.prototype._walkthroughContextCatalogRecord = function (placement) {
        if (!placement) return null;
        return this.assetCatalog.find(function (record) {
            return record.assetId === placement.assetId
                && record.assetDefinitionRevision
                    === placement.assetDefinitionRevision;
        }) || catalogRecord(
            this.assetCatalog,
            placement.assetId,
            placement.assetDefinitionRevision
        );
    };

    Workspace.prototype._walkthroughContextPayload = function (
        placement,
        catalog
    ) {
        const payload = {};
        const source = catalog && catalog.source || {};
        const definition = source.definition || source.assetDefinition || {};
        const metadata = placement && placement.metadata || {};
        const candidates = [
            definition.contextCard,
            definition.walkthroughContext,
            source.contextCard,
            source.walkthroughContext,
            source.metadata && source.metadata.contextCard,
            metadata,
            metadata.contextCard,
            metadata.walkthroughContext,
        ];
        candidates.forEach(function (candidate) {
            if (!candidate || typeof candidate !== 'object'
                    || Array.isArray(candidate)) return;
            Object.keys(candidate).forEach(function (key) {
                const value = candidate[key];
                if (value !== undefined && value !== null && value !== '') {
                    payload[key] = clone(value);
                }
            });
        });
        if (!payload.capabilities && source.capabilities) {
            payload.capabilities = clone(source.capabilities);
        }
        return payload;
    };

    Workspace.prototype._walkthroughContextTargetId = function () {
        if (this.walkthroughContextState.pinned
                && this.walkthroughContextState.pinnedPlacementId) {
            return this.walkthroughContextState.pinnedPlacementId;
        }
        const focus = this.walkthroughContextState.focus;
        return focus && focus.placementId || null;
    };

    Workspace.prototype._threeImmersiveActive = function () {
        return Boolean(
            this.threeWalkthrough && this.threeWalkthrough.active
        ) || Boolean(this.threeDrone && this.threeDrone.active);
    };

    Workspace.prototype._walkthroughContextValue = function (value) {
        if (Array.isArray(value)) {
            return value.map(function (item) {
                return typeof item === 'object'
                    ? cleanString(item.label || item.name || item.id, '')
                    : cleanString(item, '');
            }).filter(Boolean).join(', ');
        }
        if (value && typeof value === 'object') {
            return cleanString(
                value.label || value.name || value.id || value.reference,
                ''
            );
        }
        return cleanString(value, '');
    };

    Workspace.prototype._renderWalkthroughContext = function () {
        if (!this.walkthroughContextPrompt || !this.walkthroughContextCard) {
            return false;
        }
        const active = this.viewMode === '3d'
            && this._threeImmersiveActive();
        const focus = active ? this.walkthroughContextState.focus : null;
        const focusPlacement = focus
            ? this._walkthroughContextPlacement(focus.placementId) : null;
        const focusCatalog = this._walkthroughContextCatalogRecord(focusPlacement);
        const focusName = focusPlacement
            ? cleanString(
                focusPlacement.metadata
                    && focusPlacement.metadata.instanceLabel,
                focusCatalog && focusCatalog.label || focusPlacement.placementId
            ) : '';
        this.walkthroughContextPrompt.hidden = !focusPlacement
            || (this.walkthroughContextState.expanded
                && this._walkthroughContextTargetId() === focus.placementId);
        if (focusPlacement) {
            this.walkthroughContextPromptName.textContent = focusName;
            this.walkthroughContextPromptHint.textContent = 'E  Details'
                + (Number.isFinite(Number(focus.distanceMeters))
                    ? '  ' + Number(focus.distanceMeters).toFixed(1) + ' m'
                    : '');
        }

        const targetId = active && this.walkthroughContextState.expanded
            ? this._walkthroughContextTargetId() : null;
        const placement = this._walkthroughContextPlacement(targetId);
        const catalog = this._walkthroughContextCatalogRecord(placement)
            || (placement ? {
                label: placement.assetId,
                category: 'Equipment',
                manufacturer: '',
                source: {},
            } : null);
        if (!placement) {
            this.walkthroughContextCard.hidden = true;
            return Boolean(focusPlacement);
        }
        this.walkthroughContextCard.hidden = false;
        const name = cleanString(
            placement.metadata && placement.metadata.instanceLabel,
            catalog.label || placement.placementId
        );
        this.walkthroughContextTitle.textContent = name;
        this.walkthroughContextMeta.textContent = catalog.category
            + (catalog.manufacturer ? ' | ' + catalog.manufacturer : '')
            + ' | ' + placement.placementId;
        this.walkthroughContextMode.value = this.walkthroughContextState.mode;
        const pin = this.walkthroughContextCard.querySelector(
            '[data-walkthrough-context-action="pin"]'
        );
        if (pin) {
            pin.setAttribute(
                'aria-pressed',
                this.walkthroughContextState.pinned ? 'true' : 'false'
            );
            pin.setAttribute(
                'title',
                this.walkthroughContextState.pinned
                    ? 'Unpin details' : 'Pin details'
            );
        }
        const payload = this._walkthroughContextPayload(placement, catalog);
        const fields = WALKTHROUGH_CONTEXT_FIELDS[
            this.walkthroughContextState.mode
        ] || [];
        clearElement(this.walkthroughContextBody);
        const facts = fields.map(function (definition) {
            return {
                label: definition[1],
                value: this._walkthroughContextValue(payload[definition[0]]),
            };
        }, this).filter(function (fact) { return fact.value; });
        if (!facts.length) {
            this.walkthroughContextBody.appendChild(element(
                this.document,
                'p',
                { className: 'ip-flw-context-empty' },
                'No ' + this.walkthroughContextState.mode
                    + ' data is attached to this equipment.'
            ));
        } else {
            const list = element(this.document, 'dl', {
                className: 'ip-flw-context-facts',
            });
            facts.forEach(function (fact) {
                append(list,
                    element(this.document, 'dt', {}, fact.label),
                    element(this.document, 'dd', {}, fact.value)
                );
            }, this);
            this.walkthroughContextBody.appendChild(list);
        }
        return true;
    };

    Workspace.prototype._setWalkthroughContextFocus = function (value) {
        this.walkthroughContextState.focus = value && value.placementId
            ? clone(value) : null;
        if (!this.walkthroughContextState.focus
                && !this.walkthroughContextState.pinned) {
            this.walkthroughContextState.expanded = false;
        }
        this._renderWalkthroughContext();
    };

    Workspace.prototype._openWalkthroughContext = function () {
        const focus = this.walkthroughContextState.focus;
        if (!focus || !focus.placementId
                || !this._threeImmersiveActive()) {
            return false;
        }
        this.walkthroughContextState.expanded = true;
        this.walkthroughContextState.pinned = false;
        this.walkthroughContextState.pinnedPlacementId = null;
        this._renderWalkthroughContext();
        return true;
    };

    Workspace.prototype._closeWalkthroughContext = function () {
        this.walkthroughContextState.expanded = false;
        this.walkthroughContextState.pinned = false;
        this.walkthroughContextState.pinnedPlacementId = null;
        this._renderWalkthroughContext();
        return true;
    };

    Workspace.prototype._handleWalkthroughContextAction = function (event) {
        const action = targetDataId(
            event.target,
            'data-walkthrough-context-action',
            this.threeView
        );
        if (!action) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (action === 'open') {
            this._openWalkthroughContext();
            return;
        }
        if (action === 'close') {
            this._closeWalkthroughContext();
            return;
        }
        const targetId = this._walkthroughContextTargetId();
        if (action === 'pin') {
            this.walkthroughContextState.pinned =
                !this.walkthroughContextState.pinned;
            this.walkthroughContextState.pinnedPlacementId =
                this.walkthroughContextState.pinned ? targetId : null;
            this._renderWalkthroughContext();
        } else if (action === 'walk-to' && targetId && this.threeAdapter
                && typeof this.threeAdapter.navigateWalkthroughToPlacement
                    === 'function') {
            this.threeAdapter.navigateWalkthroughToPlacement(targetId);
        } else if (action === 'select' && targetId) {
            if (this.threeAdapter
                    && typeof this.threeAdapter.exitWalkthrough === 'function') {
                this.threeAdapter.exitWalkthrough('context_select');
            }
            if (this.threeAdapter
                    && typeof this.threeAdapter.exitDrone === 'function') {
                this.threeAdapter.exitDrone('context_select');
            }
            this.session.select(targetId);
            this._setViewMode('plan');
            this._closeWalkthroughContext();
        }
    };

    Workspace.prototype._handleWalkthroughContextMode = function (event) {
        const value = cleanString(event && event.target && event.target.value, '');
        if (!WALKTHROUGH_CONTEXT_MODES.some(function (mode) {
            return mode.key === value;
        })) return;
        this.walkthroughContextState.mode = value;
        this._renderWalkthroughContext();
    };

    Workspace.prototype._recordingCanvas = function () {
        if (this.threeAdapter
                && typeof this.threeAdapter.getRecordingCanvas === 'function') {
            return this.threeAdapter.getRecordingCanvas();
        }
        return this.threeView && this.threeView.querySelector
            ? this.threeView.querySelector('canvas') : null;
    };

    Workspace.prototype._prepareRecordingFrame = function () {
        if (this.threeAdapter
                && typeof this.threeAdapter.renderRecordingFrame === 'function') {
            return this.threeAdapter.renderRecordingFrame();
        }
        if (this.threeAdapter && typeof this.threeAdapter.invalidate === 'function') {
            this.threeAdapter.invalidate();
        }
        return this._recordingCanvas();
    };

    Workspace.prototype._recordingBackground = function () {
        if (this.threeVisualSettings.background !== 'auto') {
            return this.threeVisualSettings.background;
        }
        const rootElement = this.document && this.document.documentElement;
        const theme = rootElement && typeof rootElement.getAttribute === 'function'
            ? rootElement.getAttribute('data-theme') : '';
        return theme === 'light' ? '#dfe6eb' : '#202b38';
    };

    Workspace.prototype._recordingFormat = function () {
        if (!this.recordingRuntime
                || typeof this.recordingRuntime.chooseRecordingFormat
                    !== 'function') return null;
        return this.recordingRuntime.chooseRecordingFormat(
            this.options.MediaRecorder || (root && root.MediaRecorder)
        );
    };

    Workspace.prototype._recordingAvailable = function () {
        const canvas = this._recordingCanvas();
        return Boolean(
            this.recordingRuntime
            && typeof this.recordingRuntime.createCanvasRecorder === 'function'
            && this._recordingFormat()
            && canvas
            && typeof canvas.captureStream === 'function'
        );
    };

    Workspace.prototype._ensureRecordingController = function () {
        if (this.recordingController) return this.recordingController;
        if (!this.recordingRuntime
                || typeof this.recordingRuntime.createCanvasRecorder
                    !== 'function') {
            throw new Error('Viewport recording is unavailable.');
        }
        this.recordingController = this.recordingRuntime.createCanvasRecorder({
            document: this.document,
            MediaRecorder: this.options.MediaRecorder,
            Blob: this.options.Blob,
            URL: this.options.URL,
            navigator: this.options.navigator,
            requestAnimationFrame: this.options.recordingRequestAnimationFrame,
            cancelAnimationFrame: this.options.recordingCancelAnimationFrame,
            setInterval: this.options.recordingSetInterval,
            clearInterval: this.options.recordingClearInterval,
            now: this.options.recordingNow,
            onStateChange: this._handleRecordingStateChange.bind(this),
        });
        return this.recordingController;
    };

    Workspace.prototype._handleRecordingStateChange = function (value) {
        const snapshot = value && typeof value === 'object' ? value : {};
        this.recordingState.status = cleanString(
            snapshot.status,
            this.recordingState.status
        );
        this.recordingState.elapsedMs = Math.max(
            0,
            finite(snapshot.elapsedMs, this.recordingState.elapsedMs)
        );
        this.recordingState.paused = snapshot.paused === true;
        this.recordingState.error = snapshot.error || null;
        this.recordingState.format = snapshot.format
            ? clone(snapshot.format) : this.recordingState.format;
        this.recordingState.filename = snapshot.filename || null;
        if (snapshot.status === 'preview') {
            this.recordingState.panelOpen = false;
            this.recordingState.previewOpen = true;
            this.recordingState.countdown = 0;
        } else if (snapshot.status === 'error') {
            this.recordingState.panelOpen = true;
            this.recordingState.previewOpen = false;
        }
        this._renderRecordingState();
    };

    Workspace.prototype._setRecordingPanelOpen = function (open) {
        const busy = ['countdown', 'preparing', 'recording', 'paused', 'stopping']
            .includes(this.recordingState.status);
        if (busy && open) return false;
        this.recordingState.panelOpen = open === true;
        if (open) {
            this.recordingState.previewOpen = false;
            this.recordingState.error = null;
        }
        this._renderRecordingState();
        return true;
    };

    Workspace.prototype._handleRecordingSetting = function (event) {
        const key = targetDataId(
            event && event.target,
            'data-recording-setting',
            this.threeRecordingPanel
        );
        if (!key || !Object.prototype.hasOwnProperty.call(
            this.recordingState.settings,
            key
        )) return;
        const input = event.target;
        if (key === 'microphone' || key === 'includeHud'
                || key === 'includeCursor') {
            this.recordingState.settings[key] = input.checked === true;
        } else if (key === 'fps') {
            this.recordingState.settings.fps = Number(input.value) === 60
                ? 60 : 30;
        } else {
            this.recordingState.settings[key] = cleanString(input.value, '');
        }
        if (key === 'presentationMode') {
            const training = this.recordingState.settings.presentationMode
                === 'training';
            this.recordingState.settings.includeHud = training;
            this.recordingState.settings.includeCursor = training;
        }
        this._renderRecordingState();
    };

    Workspace.prototype._handleRecordingPointer = function (event) {
        if (!this.threeView
                || typeof this.threeView.getBoundingClientRect !== 'function') {
            return;
        }
        const rect = this.threeView.getBoundingClientRect();
        const width = Math.max(1, finite(rect.width, 1));
        const height = Math.max(1, finite(rect.height, 1));
        this.recordingCursor = {
            x: Math.max(0, Math.min(1,
                (finite(event && event.clientX, rect.left) - rect.left) / width
            )),
            y: Math.max(0, Math.min(1,
                (finite(event && event.clientY, rect.top) - rect.top) / height
            )),
            visible: true,
        };
    };

    Workspace.prototype._drawRecordingOverlay = function (frame) {
        const context = frame && frame.context;
        const settings = frame && frame.settings || {};
        if (!context || (!settings.includeHud && !settings.includeCursor)) return;
        const width = frame.width;
        const height = frame.height;
        if (typeof context.save === 'function') context.save();
        if (settings.includeHud) {
            const barHeight = Math.max(42, Math.round(height * 0.055));
            context.fillStyle = 'rgba(15, 23, 42, 0.86)';
            context.fillRect(0, height - barHeight, width, barHeight);
            context.fillStyle = '#f8fafc';
            context.font = '600 ' + Math.max(13, Math.round(height * 0.016))
                + 'px Segoe UI, Arial, sans-serif';
            const route = this.threeWalkthrough.route || {};
            const stateLabel = route.active ? 'Guided navigation'
                : this.threeDrone.active ? 'Assisted drone flythrough'
                : this.threeWalkthrough.active ? 'Human walkthrough'
                    : 'Facility overview';
            context.fillText(
                'InspectorPro  |  ' + stateLabel,
                18,
                height - Math.max(14, Math.round(barHeight * 0.35))
            );
            const focus = this.walkthroughContextState.focus;
            const placement = focus
                ? this._walkthroughContextPlacement(focus.placementId) : null;
            if (placement) {
                const catalog = this._walkthroughContextCatalogRecord(placement);
                const name = cleanString(
                    placement.metadata && placement.metadata.instanceLabel,
                    catalog && catalog.label || placement.placementId
                );
                const textWidth = typeof context.measureText === 'function'
                    ? context.measureText(name).width : name.length * 8;
                context.fillStyle = '#f4b740';
                context.fillText(
                    name,
                    Math.max(18, width - textWidth - 18),
                    height - Math.max(14, Math.round(barHeight * 0.35))
                );
            }
        }
        if (settings.includeCursor && this.recordingCursor.visible) {
            const x = this.recordingCursor.x * width;
            const y = this.recordingCursor.y * height;
            context.strokeStyle = '#f8fafc';
            context.lineWidth = Math.max(1.5, width / 960);
            if (typeof context.beginPath === 'function') context.beginPath();
            if (typeof context.arc === 'function') {
                context.arc(x, y, Math.max(5, width / 260), 0, Math.PI * 2);
            }
            if (typeof context.stroke === 'function') context.stroke();
        }
        if (typeof context.restore === 'function') context.restore();
    };

    Workspace.prototype._recordingFilename = function () {
        const name = cleanString(
            this.state && this.state.layout && this.state.layout.displayName,
            'facility-layout'
        );
        const timestamp = new Date().toISOString()
            .replace(/[:.]/g, '-')
            .replace(/Z$/, 'Z');
        return name + '-walkthrough-' + timestamp;
    };

    Workspace.prototype._startViewportRecording = async function () {
        const controller = this._ensureRecordingController();
        const canvas = this._recordingCanvas();
        if (!canvas || typeof canvas.captureStream !== 'function') {
            throw new Error('The 3D viewport is not ready to record.');
        }
        const settings = this.recordingState.settings;
        const training = settings.presentationMode === 'training';
        this.recordingState.panelOpen = false;
        this.recordingState.previewOpen = false;
        this.recordingState.countdown = 0;
        this.recordingState.error = null;
        await controller.start({
            sourceCanvas: canvas,
            prepareSourceFrame: this._prepareRecordingFrame.bind(this),
            resolution: settings.resolution,
            fps: settings.fps,
            microphone: settings.microphone,
            includeHud: training && settings.includeHud,
            includeCursor: training && settings.includeCursor,
            overlayRenderer: training
                ? this._drawRecordingOverlay.bind(this) : null,
            filename: this._recordingFilename(),
            background: this._recordingBackground(),
            videoBitsPerSecond: (settings.resolution === '1080p'
                ? 12000000 : settings.resolution === '720p' ? 6000000 : 8000000)
                * (settings.fps === 60 ? 1.5 : 1),
        });
    };

    Workspace.prototype._cancelRecordingCountdown = function () {
        if (this.recordingCountdownTimer !== null) {
            const cancel = this.options.recordingClearTimeout
                || (root && root.clearTimeout) || clearTimeout;
            cancel(this.recordingCountdownTimer);
        }
        this.recordingCountdownTimer = null;
        if (this.recordingState.status === 'countdown') {
            this.recordingState.status = 'idle';
            this.recordingState.countdown = 0;
        }
    };

    Workspace.prototype._beginRecordingCountdown = function () {
        if (!this._recordingAvailable()) {
            this.recordingState.error = 'Viewport recording is unavailable in this browser.';
            this.recordingState.panelOpen = true;
            this._renderRecordingState();
            return false;
        }
        this._cancelRecordingCountdown();
        let remaining = this.recordingCountdownSeconds;
        this.recordingState.status = 'countdown';
        this.recordingState.panelOpen = false;
        this.recordingState.countdown = remaining;
        this._renderRecordingState();
        const schedule = this.options.recordingSetTimeout
            || (root && root.setTimeout) || setTimeout;
        const tick = function () {
            if (remaining <= 0) {
                this.recordingCountdownTimer = null;
                this._startViewportRecording().catch(function (error) {
                    this.recordingState.status = 'error';
                    this.recordingState.error = error.message;
                    this.recordingState.panelOpen = true;
                    this._renderRecordingState();
                }.bind(this));
                return;
            }
            this.recordingState.countdown = remaining;
            this._renderRecordingState();
            remaining -= 1;
            this.recordingCountdownTimer = schedule(tick, 1000);
        }.bind(this);
        tick();
        return true;
    };

    Workspace.prototype._handleRecordingAction = function (event) {
        const action = targetDataId(
            event && event.target,
            'data-recording-action',
            this.threeView
        );
        if (!action) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (typeof event.stopPropagation === 'function') event.stopPropagation();
        if (action === 'cancel') {
            this._cancelRecordingCountdown();
            this._setRecordingPanelOpen(false);
        } else if (action === 'start') {
            this._beginRecordingCountdown();
        } else if (action === 'pause' && this.recordingController) {
            if (this.recordingState.status === 'paused') {
                this.recordingController.resume();
            } else {
                this.recordingController.pause();
            }
        } else if (action === 'stop' && this.recordingController) {
            this.recordingController.stop();
        } else if (action === 'discard' && this.recordingController) {
            this.recordingController.discard();
            this.recordingState.previewOpen = false;
            this.recordingPreviewVideo.removeAttribute('src');
            this._renderRecordingState();
        } else if (action === 'download' && this.recordingController) {
            this.recordingController.download();
        }
    };

    Workspace.prototype._renderRecordingState = function () {
        if (!this.threeRecordingPanel) return;
        const state = this.recordingState;
        const settings = state.settings;
        this.recordingPresentationInput.value = settings.presentationMode;
        this.recordingResolutionInput.value = settings.resolution;
        this.recordingFpsInput.value = String(settings.fps);
        this.recordingMicrophoneInput.checked = settings.microphone;
        this.recordingHudInput.checked = settings.includeHud;
        this.recordingCursorInput.checked = settings.includeCursor;
        const training = settings.presentationMode === 'training';
        this.recordingHudInput.disabled = !training;
        this.recordingCursorInput.disabled = !training;
        const format = state.format || this._recordingFormat();
        this.recordingFormatText.textContent = format
            ? format.label + ' will be saved.'
            : 'No supported video format is available.';
        this.recordingErrorText.hidden = !state.error;
        this.recordingErrorText.textContent = state.error || '';
        this.threeRecordingPanel.hidden = !state.panelOpen;
        this.threeRecordingCountdown.hidden = state.status !== 'countdown';
        this.threeRecordingCountdown.textContent = state.countdown > 0
            ? String(state.countdown) : 'Recording';
        const monitorVisible = ['recording', 'paused', 'stopping']
            .includes(state.status);
        this.threeRecordingMonitor.hidden = !monitorVisible;
        this.recordingTimerText.textContent = recordingElapsedText(state.elapsedMs);
        const pause = this.threeRecordingMonitor.querySelector(
            '[data-recording-action="pause"]'
        );
        if (pause) pause.textContent = state.status === 'paused' ? 'Resume' : 'Pause';
        const result = this.recordingController
            && this.recordingController.getResult
            ? this.recordingController.getResult() : null;
        this.threeRecordingPreview.hidden = !state.previewOpen || !result;
        if (state.previewOpen && result) {
            if (this.recordingPreviewVideo.getAttribute('src') !== result.url) {
                this.recordingPreviewVideo.setAttribute('src', result.url || '');
                if (typeof this.recordingPreviewVideo.load === 'function') {
                    this.recordingPreviewVideo.load();
                }
            }
            this.recordingPreviewSummary.textContent = result.width + ' x '
                + result.height + ' | ' + result.fps + ' FPS | '
                + recordingElapsedText(result.durationMs) + ' | '
                + result.extension.toUpperCase();
        }
        const record = this.threeNavigation && this.threeNavigation.querySelector(
            '[data-three-command="record"]'
        );
        if (record) {
            const active = ['countdown', 'preparing', 'recording', 'paused', 'stopping']
                .includes(state.status);
            record.disabled = !this._recordingAvailable() && !active;
            record.setAttribute('aria-pressed', active ? 'true' : 'false');
            const label = active ? 'Facility view recording in progress'
                : 'Record facility view';
            record.setAttribute('aria-label', label);
            record.setAttribute('title', label);
        }
        if (this.root) {
            this.root.setAttribute('data-recording-state', state.status);
        }
    };

    Workspace.prototype._setThreeViewMenuOpen = function (open) {
        this.threeViewMenuOpen = open === true;
        if (this.threeViewMenuOpen) {
            this.layerPanelOpen = false;
            if (this.layerPanel) this.layerPanel.hidden = true;
            this.threeSettingsOpen = false;
            this.threeViewpointsOpen = false;
            if (this.threeSettingsPanel) this.threeSettingsPanel.hidden = true;
        }
        this._renderThreeNavigationState();
    };

    Workspace.prototype._applyThreeOrientation = function (view) {
        const method = {
            front: 'frontView',
            top: 'topView',
            right: 'rightView',
            iso: 'isometricView',
        }[view];
        if (!method || !this.threeAdapter
                || typeof this.threeAdapter[method] !== 'function') {
            return false;
        }
        const applied = this.threeAdapter[method]();
        if (applied !== false) this.threeOrientation = view;
        this._setThreeViewMenuOpen(false);
        return applied !== false;
    };

    Workspace.prototype._handleThreeNavigationKeyDown = function (event) {
        const key = String(event && event.key || '').toLowerCase();
        if (key === 'enter' && event.target === this.threeViewpointInput) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._saveThreeViewpoint();
            return;
        }
        if (key === 'escape' && this.threeViewpointsOpen) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._setThreeViewpointsOpen(false);
            if (this.threeViewpointTrigger
                    && typeof this.threeViewpointTrigger.focus === 'function') {
                this.threeViewpointTrigger.focus();
            }
            return;
        }
        if (key === 'escape' && this.threeViewMenuOpen) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._setThreeViewMenuOpen(false);
            if (this.threeViewOrientationTrigger
                    && typeof this.threeViewOrientationTrigger.focus
                        === 'function') {
                this.threeViewOrientationTrigger.focus();
            }
            return;
        }
        const command = targetDataId(
            event.target,
            'data-three-command',
            this.threeNavigation
        );
        if (key === 'arrowdown' && command === 'view-orientation') {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._setThreeViewMenuOpen(true);
            const first = this.threeViewOrientationMenu
                && this.threeViewOrientationMenu.querySelector(
                    '[data-three-view="front"]'
                );
            if (first && typeof first.focus === 'function') first.focus();
        }
    };

    Workspace.prototype._renderThreeVisualSettings = function () {
        if (!this.threeSettingsPanel) return;
        const settings = this.threeVisualSettings;
        Object.keys(settings).forEach(function (key) {
            const input = this.threeSettingsPanel.querySelector(
                '[data-three-setting="' + key + '"]'
            );
            if (input) {
                if (key === 'autoRotate' || key === 'wireframe') {
                    input.checked = settings[key] === true;
                } else if (key === 'background') {
                    input.value = settings[key] === 'auto'
                        ? '#dfe6eb' : settings[key];
                } else {
                    input.value = String(settings[key]);
                }
            }
            const output = this.threeSettingsPanel.querySelector(
                '[data-three-setting-value="' + key + '"]'
            );
            if (output) output.textContent = Number(settings[key]).toFixed(2);
        }, this);
    };

    Workspace.prototype._applyThreeVisualSettings = function () {
        if (this.threeAdapter
                && typeof this.threeAdapter.setVisualSettings === 'function') {
            this.threeVisualSettings = normalizeThreeVisualSettings(
                this.threeAdapter.setVisualSettings(this.threeVisualSettings)
            );
        }
        this._renderThreeVisualSettings();
        this._renderThreeNavigationState();
    };

    Workspace.prototype._handleThreeSettingsInput = function (event) {
        const key = targetDataId(
            event.target,
            'data-three-setting',
            this.threeSettingsPanel
        );
        if (!key || !Object.prototype.hasOwnProperty.call(
            this.threeVisualSettings,
            key
        )) return;
        const before = JSON.stringify(this.threeVisualSettings);
        if (key === 'autoRotate' || key === 'wireframe') {
            this.threeVisualSettings[key] = event.target.checked === true;
        } else if (key === 'background') {
            this.threeVisualSettings.background = String(event.target.value);
        } else {
            this.threeVisualSettings[key] = Number(event.target.value);
        }
        this.threeVisualSettings = normalizeThreeVisualSettings(
            this.threeVisualSettings
        );
        if (JSON.stringify(this.threeVisualSettings) === before) return;
        this._applyThreeVisualSettings();
    };

    Workspace.prototype._handleThreeSettingsClick = function (event) {
        const action = targetDataId(
            event.target,
            'data-three-settings-action',
            this.threeSettingsPanel
        );
        if (action !== 'reset') return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        this.threeVisualSettings = normalizeThreeVisualSettings(
            DEFAULT_THREE_VISUAL_SETTINGS
        );
        this._applyThreeVisualSettings();
    };

    Workspace.prototype._handleThreeNavigationClick = function (event) {
        if (typeof event.stopPropagation === 'function') event.stopPropagation();
        const viewpointAction = targetDataId(
            event.target,
            'data-viewpoint-action',
            this.threeNavigation
        );
        if (viewpointAction) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            const viewpointId = targetDataId(
                event.target,
                'data-viewpoint-id',
                this.threeNavigation
            );
            if (viewpointAction === 'save') this._saveThreeViewpoint();
            else if (viewpointAction === 'apply') {
                this._applyThreeViewpoint(viewpointId);
            } else if (viewpointAction === 'delete') {
                this._deleteThreeViewpoint(viewpointId);
            }
            return;
        }
        const view = targetDataId(
            event.target,
            'data-three-view',
            this.threeNavigation
        );
        if (view) {
            if (typeof event.preventDefault === 'function') event.preventDefault();
            this._applyThreeOrientation(view);
            return;
        }
        const command = targetDataId(
            event.target,
            'data-three-command',
            this.threeNavigation
        );
        if (!command) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        if (command === 'view-orientation') {
            this._setThreeViewMenuOpen(!this.threeViewMenuOpen);
            return;
        }
        if (command === 'viewpoints') {
            this._setThreeViewpointsOpen(!this.threeViewpointsOpen);
            return;
        }
        if (command === 'record') {
            const result = this.recordingController
                && this.recordingController.getResult
                ? this.recordingController.getResult() : null;
            if (result) {
                this.recordingState.previewOpen = true;
                this.recordingState.panelOpen = false;
                this._renderRecordingState();
            } else {
                this._setRecordingPanelOpen(!this.recordingState.panelOpen);
            }
            return;
        }
        if (!this.threeAdapter) return;
        this._setThreeViewMenuOpen(false);
        if (command === 'walkthrough') {
            if (this.threeWalkthrough.active
                    && typeof this.threeAdapter.exitWalkthrough === 'function') {
                this.threeAdapter.exitWalkthrough('toolbar_exit');
            } else if (typeof this.threeAdapter.enterWalkthrough === 'function') {
                const selected = this._selectedPlacementRecords();
                this.threeAdapter.enterWalkthrough({
                    placementId: selected.length === 1
                        ? selected[0].placementId : undefined,
                });
            }
        } else if (command === 'avatar-view') {
            if (typeof this.threeAdapter.setWalkthroughCameraMode === 'function') {
                this.threeAdapter.setWalkthroughCameraMode(
                    this.threeWalkthrough.cameraMode === 'third-person' ? 'first-person' : 'third-person');
            }
        } else if (command === 'drone') {
            if (this.threeDrone.active
                    && typeof this.threeAdapter.exitDrone === 'function') {
                this.threeAdapter.exitDrone('toolbar_exit');
            } else if (typeof this.threeAdapter.enterDrone === 'function') {
                const selected = this._selectedPlacementRecords();
                this.threeAdapter.enterDrone({
                    placementId: selected.length === 1
                        ? selected[0].placementId : undefined,
                });
            }
        } else if (command === 'switch-immersive') {
            if (typeof this.threeAdapter.switchImmersiveMode === 'function') {
                this.threeAdapter.switchImmersiveMode(
                    this.threeDrone.active ? 'walkthrough' : 'drone'
                );
            }
        } else if (command === 'walk-to-selected') {
            const selected = this._selectedPlacementRecords();
            if (selected.length === 1
                    && typeof this.threeAdapter
                        .navigateWalkthroughToPlacement === 'function') {
                this.threeAdapter.navigateWalkthroughToPlacement(
                    selected[0].placementId
                );
            }
        } else if (command === 'orbit' || command === 'pan') {
            this.threeNavigationMode = command;
            if (typeof this.threeAdapter.setNavigationMode === 'function') {
                this.threeAdapter.setNavigationMode(command);
            }
        } else if (command === 'zoom-in' || command === 'zoom-out') {
            if (typeof this.threeAdapter.zoomBy === 'function') {
                this.threeAdapter.zoomBy(command === 'zoom-in' ? 1.25 : 0.8);
            }
        } else if (command === 'fit-layout') {
            if (typeof this.threeAdapter.fitLayout === 'function') {
                this.threeAdapter.fitLayout();
            } else if (typeof this.threeAdapter.fit === 'function') {
                this.threeAdapter.fit();
            }
        } else if (command === 'fit-facility') {
            if (typeof this.threeAdapter.fitFacility === 'function') {
                this.threeAdapter.fitFacility();
            } else if (typeof this.threeAdapter.fit === 'function') {
                this.threeAdapter.fit();
            }
        } else if (command === 'appearance') {
            this.openAppearanceDialog();
        } else if (command === 'display-settings') {
            this._setLayerPanelOpen(false);
            this.threeSettingsOpen = !this.threeSettingsOpen;
            this.threeViewpointsOpen = false;
            this.threeSettingsPanel.hidden = !this.threeSettingsOpen;
        } else if (command === 'layers') {
            this._setLayerPanelOpen(!this.layerPanelOpen);
        } else if (command === 'grid') {
            this.threeGridVisible = !this.threeGridVisible;
            if (typeof this.threeAdapter.setGridVisible === 'function') {
                this.threeAdapter.setGridVisible(this.threeGridVisible);
            }
        }
        this._renderThreeNavigationState();
    };

    Workspace.prototype._setCoordinates = function (world) {
        this.lastPointerWorld = {
            x: finite(world && world.x, 0),
            y: finite(world && world.y, 0),
            z: finite(world && world.z, 0),
        };
        const unit = this.planPreferences.unit;
        this.coordinateText.textContent = 'Cursor: X '
            + formattedDistance(displayDistance(this.lastPointerWorld.x, unit))
            + ' ' + unit + '  Z '
            + formattedDistance(displayDistance(this.lastPointerWorld.z, unit))
            + ' ' + unit;
        this._setRulerCursor(this.lastPointerWorld);
    };

    // Places the ruler markers at the pointer. Passing null hides them, which is
    // what leaving the plan should do: a marker left behind would report a
    // position the pointer no longer has.
    Workspace.prototype._setRulerCursor = function (world) {
        if (!this.planTopRulerCursor || !this.planLeftRulerCursor) return;
        const projection = this.planProjection;
        const usable = Boolean(
            world && projection && finite(projection.scale, 0) > 0
        );
        if (!usable) {
            this.planTopRulerCursor.hidden = true;
            this.planLeftRulerCursor.hidden = true;
            return;
        }
        const screen = planScreenForWorld(
            projection,
            finite(world.x, 0),
            finite(world.z, 0)
        );
        const width = Math.max(1, finite(projection.width, 1));
        const height = Math.max(1, finite(projection.height, 1));
        const x = finite(screen.x, -1);
        const y = finite(screen.y, -1);
        // Clamp to the ruler rather than letting a marker ride off the end,
        // where it would point at a coordinate that is not on screen.
        this.planTopRulerCursor.hidden = !(x >= 0 && x <= width);
        this.planLeftRulerCursor.hidden = !(y >= 0 && y <= height);
        if (!this.planTopRulerCursor.hidden) {
            this.planTopRulerCursor.setAttribute(
                'style',
                'left:' + Number(x.toFixed(2)) + 'px'
            );
        }
        if (!this.planLeftRulerCursor.hidden) {
            this.planLeftRulerCursor.setAttribute(
                'style',
                'top:' + Number(y.toFixed(2)) + 'px'
            );
        }
    };

    Workspace.prototype._handleToolbarClick = function (event) {
        const command = targetDataId(event.target, 'data-command', this.toolbar);
        if (!command) return;
        this.executeCommand(command);
    };

    Workspace.prototype._rememberProposalFocus = function () {
        const active = this.document.activeElement;
        const externalCommand = active
            && typeof active.getAttribute === 'function'
            && active.getAttribute('data-facility-ribbon-command');
        this.proposalFocusReturn = active
            && (this.root.contains(active) || externalCommand)
            && typeof active.focus === 'function'
            ? active
            : this.toolbar.querySelector('[data-command="auto-arrange"]');
    };

    Workspace.prototype._restoreProposalFocus = function () {
        let target = this.proposalFocusReturn;
        const externalCommand = target
            && typeof target.getAttribute === 'function'
            && target.getAttribute('data-facility-ribbon-command');
        if (!target || target.disabled || target.hidden
                || (!this.root.contains(target) && !externalCommand)
                || typeof target.focus !== 'function') {
            target = this.toolbar.querySelector(
                '[data-command="auto-arrange"]'
            );
        }
        if (!target || target.disabled || target.hidden
                || typeof target.focus !== 'function') {
            target = this.viewMode === '3d' && !this.threeView.hidden
                ? this.threeView : this.planView;
        }
        this.proposalFocusReturn = null;
        if (target && typeof target.focus === 'function') target.focus();
    };

    // Explicit local construction boundary. Agent authorization/preview must
    // still be performed by the host; this does not grant Sage write access.
    Workspace.prototype.executeConstructionCommand = async function (request) {
        if (!this.capabilities.manualAuthoring || this.destroyed) {
            throw new Error('Manual construction is unavailable');
        }
        if (!this.constructionAdapterPromise) {
            this.constructionAdapterPromise = Promise.resolve().then(async function () {
                if (!root.InspectorProFacilityCommandAdapter) {
                    throw new Error('Construction command adapter is unavailable');
                }
                const response = await root.fetch(
                    '/static/contracts/facility-construction-commands-v1.json'
                );
                if (!response.ok) throw new Error('Construction contract could not be loaded');
                return root.InspectorProFacilityCommandAdapter.createAdapter(
                    await response.json(), this.patternRuntime, this.session,
                    function () { return this.assetCatalog; }.bind(this)
                );
            }.bind(this)).catch(function (error) {
                this.constructionAdapterPromise = null;
                throw error;
            }.bind(this));
        }
        const adapter = await this.constructionAdapterPromise;
        if (!this.capabilities.manualAuthoring || this.destroyed) {
            throw new Error('Manual construction is unavailable');
        }
        return adapter.execute(request);
    };

    Workspace.prototype.executeCommand = function (command) {
        // With the Appearances, Scenes and Decals panel available, the ribbon's
        // appearance commands open it at the matching place; the original
        // dialogs remain the fallback.
        const library = typeof this.options.onOpenAppearanceLibrary === 'function'
            ? this.options.onOpenAppearanceLibrary : null;
        if (library && command === 'appearance') return Promise.resolve(library({ node: 'appearances', scope: 'object' }));
        if (library && command === 'component-materials') return Promise.resolve(library({ node: 'appearances', scope: 'part' }));
        if (library && command === 'decals') return Promise.resolve(library({ node: 'decals' }));
        if (command === 'decals') return Promise.resolve(decalsRuntime.openDialog(this));
        if (command === 'lettering') return Promise.resolve(decalsRuntime.openDialog(this, 'lettering'));
        if (command === 'component-materials') return componentMaterialsRuntime.open(this);
        if (command === 'interior-walls') return Promise.resolve(interiorWallsRuntime.open(this));
        if (command === 'floor-surfaces') return Promise.resolve(floorSurfacesRuntime.open(this));
        if (command === 'replace-asset') return Promise.resolve(replaceAssetRuntime.open(this));
        if (command === 'appearance') return Promise.resolve(this.openAppearanceDialog());
        if (this.generationPlanningView && this.generationPlanningView.activeLayout()
                && !['pan', 'fit', 'fit-layout', 'top-view'].includes(command)) {
            return Promise.reject(new Error('Exit the isolated generation preview before editing'));
        }
        if (command === 'assets') {
            if (this.assetBrowserState.open) this.closeAssetBrowser(false);
            else this.openAssetBrowser();
            return Promise.resolve(this.getState());
        }
        if (this.assetBrowserState.open) {
            return Promise.resolve(this.getState());
        }
        if (command === 'floor-marking') {
            if (this.floorMarkingState.open) {
                this.closeFloorMarkingPalette(true);
            } else {
                this.openFloorMarkingPalette();
            }
            return Promise.resolve(this.getState());
        }
        if (command === 'aisle') {
            if (this.aisleState.open) this.closeAisleDialog(true);
            else this.openAisleDialog();
            return Promise.resolve(this.getState());
        }
        if (command === 'motion-path') {
            if (this.navigationState.open) {
                this.closeNavigationDialog(true);
            } else {
                this.openNavigationDialog();
            }
            return Promise.resolve(this.getState());
        }
        if (command === 'saved-movement') {
            this.openSavedMovementDialog();
            return Promise.resolve(this.getState());
        }
        if (PRECISION_MODES.includes(command)) {
            if (!this.capabilities.manualAuthoring) {
                return Promise.resolve(this.getState());
            }
            this.openPrecisionDialog(command);
            return Promise.resolve(this.getState());
        }
        if (PATTERN_MODES.includes(command)) {
            if (!this.capabilities.manualAuthoring) {
                return Promise.resolve(this.getState());
            }
            this.openPatternDialog(command);
            return Promise.resolve(this.getState());
        }
        if (command === 'clear-all') {
            if (!this.capabilities.manualAuthoring) {
                return Promise.resolve(this.getState());
            }
            this.openClearAllDialog();
            return Promise.resolve(this.getState());
        }
        if (command === 'bulk-zones') {
            if (!this.capabilities.manualAuthoring) {
                return Promise.resolve(this.getState());
            }
            this.openBulkZoneDialog();
            return Promise.resolve(this.getState());
        }
        if (command === 'create-cell-group') {
            if (!this.capabilities.manualAuthoring) {
                return Promise.resolve(this.getState());
            }
            this.openCellGroupDialog();
            return Promise.resolve(this.getState());
        }
        if (command === 'ungroup-cell') {
            return this._ungroupSelectedCell();
        }
        const manualCommands = [
            'rectangle-zone',
            'polygon-zone',
            'bulk-zones',
            'create-cell-group',
            'ungroup-cell',
            'aisle',
            'floor-marking',
            'motion-path',
            'rotate',
            'duplicate',
            'delete',
            'lock',
            'align',
            'distribute',
            'relative',
            'distance',
            'offset',
            'linear-pattern',
            'circular-pattern',
            'perimeter-pattern',
            'cell-layout',
            'mirror',
            'swap',
            'clear-all',
            'undo',
            'redo',
            'save',
        ];
        if (manualCommands.includes(command)
                && !this.capabilities.manualAuthoring) {
            return Promise.resolve(this.getState());
        }
        if (command === 'auto-arrange'
                && !this.capabilities.fullLayoutProposals) {
            return Promise.resolve(this.getState());
        }
        if (TOOL_MODES.includes(command)) {
            this._setToolMode(command);
            return Promise.resolve(this.getState());
        }
        if ((command === 'fit' || command === 'fit-layout') && this.viewMode === 'site' && this.siteView) {
            this.siteView.fit();
            return Promise.resolve(this.getState());
        }
        if (command === 'fit') {
            if (typeof this.controller.fitFacility === 'function') {
                this.controller.fitFacility();
            } else {
                this.controller.fit();
            }
            return Promise.resolve(this.getState());
        }
        if (command === 'fit-layout') {
            if (typeof this.controller.fitLayout === 'function') {
                this.controller.fitLayout();
            } else {
                this.controller.fit();
            }
            return Promise.resolve(this.getState());
        }
        if (command === 'top-view') {
            this._setViewMode('3d');
            if (typeof this.controller.topView === 'function') {
                this.controller.topView();
            }
            return Promise.resolve(this.getState());
        }
        const actions = {
            'auto-arrange': function () {
                if (typeof this.session.requestLayoutProposal !== 'function') {
                    throw new Error(
                        'Full-layout proposals are not available'
                    );
                }
                this._rememberProposalFocus();
                autoArrangeSequence += 1;
                const requestId = 'facility-auto-arrange-'
                    + Date.now().toString(36)
                    + '-' + autoArrangeSequence.toString(36);
                return this.session.requestLayoutProposal(
                    buildAutoArrangeRequest(
                        this.state,
                        this.assetCatalog,
                        requestId
                    )
                );
            },
            rotate: function () { return this.session.rotateSelected90(); },
            duplicate: function () {
                return this.session.duplicateSelected(DEFAULT_DUPLICATE_OFFSET);
            },
            delete: function () { return this.session.deleteSelected(); },
            undo: function () { return this.session.undo(); },
            redo: function () { return this.session.redo(); },
            save: function () { return this.session.save(); },
            // The saved layout's plan sheets (site plan, floor plan), drawn by the server, in a new tab.
            'export-pdf': function () {
                const layout = this.state.layout;
                const view = this.document.defaultView;
                if (view && typeof view.open === 'function') {
                    view.open('/api/facility-layouts/' + encodeURIComponent(layout.association.siteId) + '/'
                        + encodeURIComponent(layout.layoutId) + '/plan.pdf', '_blank', 'noopener');
                }
                return Promise.resolve(this.getState());
            },
            lock: function () {
                const placements = this.state.layout.placements.filter(function (item) {
                    return this.state.selection.includes(item.placementId);
                }, this);
                const markings = (this.state.layout.floorMarkings || []).filter(
                    function (item) {
                        return this.state.selection.includes(item.markingId);
                    },
                    this
                );
                const movable = placements.concat(markings);
                const allLocked = movable.length > 0 && movable.every(
                    function (item) { return item.positionMode === 'locked'; }
                );
                return allLocked
                    ? this.session.unlockSelected()
                    : this.session.lockSelected();
            },
        };
        const action = actions[command];
        if (!action) return Promise.resolve(this.getState());
        return this._invoke(command, action.bind(this));
    };

    Workspace.prototype._handleViewTabClick = function (event) {
        const view = targetDataId(event.target, 'data-view', this.viewTabs);
        if (VIEW_MODES.includes(view)) this._setViewMode(view);
    };

    Workspace.prototype._handleViewTabKeyDown = function (event) {
        const key = String(event && event.key || '');
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(key)) return;
        const tabs = [this.planTab, this.threeTab, this.siteTab].filter(function (tab) {
            return tab && !tab.disabled;
        });
        const current = tabs.indexOf(event.target);
        if (current < 0 || tabs.length < 2) return;
        let next = current;
        if (key === 'Home') next = 0;
        else if (key === 'End') next = tabs.length - 1;
        else if (key === 'ArrowRight') next = (current + 1) % tabs.length;
        else next = (current - 1 + tabs.length) % tabs.length;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        tabs[next].focus();
    };

    Workspace.prototype._setViewMode = function (mode) {
        if (!VIEW_MODES.includes(mode)) throw new TypeError('invalid view mode');
        if (this.walkCameraControl) this.walkCameraControl.close(false);
        if (mode === '3d' && !this.threeAdapter) mode = 'plan';
        if (mode === 'site' && !this.siteView) mode = 'plan';
        if (mode !== '3d') {
            this._cancelRecordingCountdown();
            if (this.recordingController
                    && ['recording', 'paused'].includes(
                        this.recordingState.status
                    )) {
                this.recordingController.stop();
            }
            this.recordingState.panelOpen = false;
        }
        if (mode !== '3d' && this.threeWalkthrough.active
                && this.threeAdapter
                && typeof this.threeAdapter.exitWalkthrough === 'function') {
            this.threeAdapter.exitWalkthrough('view_changed');
        }
        if (mode !== '3d' && this.threeDrone.active
                && this.threeAdapter
                && typeof this.threeAdapter.exitDrone === 'function') {
            this.threeAdapter.exitDrone('view_changed');
        }
        this.viewMode = mode;
        const plan = mode === 'plan';
        const three = mode === '3d';
        const site = mode === 'site';
        this.planView.hidden = !plan;
        this.threeView.hidden = !three;
        this.planTab.setAttribute('aria-selected', plan ? 'true' : 'false');
        this.planTab.setAttribute('tabindex', plan ? '0' : '-1');
        this.threeTab.setAttribute('aria-selected', three ? 'true' : 'false');
        this.threeTab.setAttribute('tabindex', three ? '0' : '-1');
        this.threeTab.disabled = !this.threeAdapter;
        if (this.siteView) {
            this.siteView.element.hidden = !site;
            this.siteTab.setAttribute('aria-selected', site ? 'true' : 'false');
            this.siteTab.setAttribute('tabindex', site ? '0' : '-1');
            if (site) {
                this.siteView.render(this.siteRepresentedLayout || (this.state && this.state.layout), { readOnly: this.sitePreviewReadOnly });
                this.siteView.show();
            } else {
                this.siteView.hide();
            }
        }
        this.root.setAttribute('data-view-mode', mode);
        if (this.threeAdapter && typeof this.threeAdapter.invalidate === 'function'
                && mode === '3d') {
            this.threeAdapter.invalidate();
        }
        if (mode === '3d'
                && this.lastLayoutFingerprint
                && this.threeAdapter) {
            const fitFingerprint = this.lastLayoutFitFingerprint;
            const ready = this.controller
                && typeof this.controller.ready === 'function'
                ? this.controller.ready() : Promise.resolve();
            Promise.resolve(ready).then(function () {
                if (this.destroyed || this.viewMode !== '3d'
                        || this.lastLayoutFitFingerprint !== fitFingerprint) return;
                if (this.motionState.loaded
                        && this.motionState.vehiclePresentation === 'placed_asset'
                        && this.threeAdapter.motion
                        && typeof this.threeAdapter.motion.focus === 'function') {
                    this.threeAdapter.motion.focus();
                } else if (
                    this.lastThreeFitFingerprint !== fitFingerprint
                    && typeof this.threeAdapter.fitLayout === 'function'
                ) {
                    this.threeAdapter.fitLayout();
                    this.lastThreeFitFingerprint = fitFingerprint;
                }
            }.bind(this));
        }
        this._renderThreeNavigationState();
        if (plan) this._renderPlanSpatialOverlays();
        this._renderProperties();
        this._renderStatus();
        this._syncSelectionToolbar();
        return mode;
    };

    Workspace.prototype._fitPlanToBuilding = function () {
        if (this.destroyed || this.viewMode !== 'plan' || !this.topAdapter
                || typeof this.topAdapter.fitBuilding !== 'function') return null;
        return this.topAdapter.fitBuilding();
    };

    Workspace.prototype._setToolMode = function (mode) {
        if (!TOOL_MODES.includes(mode)) throw new TypeError('invalid tool mode');
        this.toolMode = mode;
        if (mode !== 'floor-marking' && this.floorMarkingPalette) {
            this.floorMarkingState.open = false;
            this.floorMarkingPalette.hidden = true;
            this.floorMarkingPalette.setAttribute('aria-hidden', 'true');
        }
        if (mode !== 'aisle' && this.aisleState) {
            this.aisleState.drawing = false;
            this._setAislePreview(null);
            if (this.aisleState.open) this._renderAisleDialog();
        }
        if (mode !== 'motion-path' && this.navigationState) {
            this.navigationState.drawing = false;
            this.navigationState.anchorPicking = false;
            if (this.navigationState.open) {
                this._renderNavigationDialog();
            }
        }
        this.polygonPoints = [];
        this._cancelPointerGesture();
        this.root.setAttribute('data-tool-mode', mode);
        const buttons = this.toolbar.querySelectorAll
            ? this.toolbar.querySelectorAll('[data-command]')
            : [];
        Array.prototype.forEach.call(buttons, function (button) {
            const command = button.getAttribute('data-command');
            if (TOOL_MODES.includes(command)) {
                button.setAttribute(
                    'aria-pressed',
                    command === mode ? 'true' : 'false'
                );
            } else {
                button.removeAttribute('aria-pressed');
            }
        });
        this._renderToolbarState();
        this._renderPlanNavigationState();
        this._renderStatus();
        this._syncSelectionToolbar();
        return mode;
    };

    Workspace.prototype._handlePropertyChange = function (event) {
        const field = targetDataId(
            event.target,
            'data-property',
            this.propertiesBody
        );
        if (!field) return;
        if (this.state.selection.length > 1
                && ['multi-x', 'multi-y', 'multi-z', 'multi-rotation'].includes(field)) {
            const geometry = this._selectionGeometry();
            if (!geometry) return;
            const requested = finite(event.target.value, NaN);
            if (!Number.isFinite(requested)) return;
            if (field === 'multi-rotation') {
                if (!Number.isFinite(geometry.rotation)) {
                    this._setError(new Error(
                        'Selected objects must share one rotation before setting it numerically'
                    ));
                    return;
                }
                const turns = Math.round((requested - geometry.rotation) / 90);
                if (Math.abs(geometry.rotation + turns * 90 - requested) > 0.001) {
                    this._setError(new Error('Rotation must use 90-degree increments'));
                    return;
                }
                this._invoke('Rotate selection', function () {
                    return this.session.rotateSelected90(turns);
                }.bind(this));
                return;
            }
            const canonical = canonicalDistance(
                requested,
                this.planPreferences.unit
            );
            const axis = field.slice(-1);
            const current = axis === 'x'
                ? geometry.center.x
                : (axis === 'z' ? geometry.center.z : geometry.elevation);
            const delta = { x: 0, y: 0, z: 0 };
            delta[axis] = canonical - current;
            this._invoke('Move selection', function () {
                return this.session.moveSelected(delta);
            }.bind(this));
            return;
        }
        const selected = selectionRecord(this.state.layout, this.state.selection);
        if (!selected) return;
        if (selected.kind === 'zone' && field === 'label') {
            const label = String(event.target.value || '').trim();
            if (!label || label.length > 120) {
                this._setError(new Error(
                    label ? 'Zone name must be 120 characters or fewer'
                        : 'Zone name cannot be empty'
                ));
                return;
            }
            this._invoke('Rename zone', function () {
                return this.session.editZoneLabel(selected.value.zoneId, label);
            }.bind(this));
            return;
        }
        if (selected.kind === 'zone' && field === 'zoneType') {
            const zoneType = String(event.target.value || '').trim();
            if (!ZONE_PURPOSE_OPTIONS.some(function (option) {
                return option.value === zoneType;
            })) return;
            this._invoke('Change zone purpose', function () {
                return this.session.editZoneType(
                    selected.value.zoneId,
                    zoneType
                );
            }.bind(this));
            return;
        }
        if (selected.kind === 'zone'
                && ['minX', 'minZ', 'width', 'depth'].includes(field)) {
            const dimensions = zoneDimensions(selected.value);
            if (!dimensions) return;
            const read = function (name, fallback) {
                const input = this.propertiesBody.querySelector(
                    '[data-property="' + name + '"]'
                );
                if (!input) return fallback;
                return canonicalDistance(
                    finite(input.value, NaN),
                    this.planPreferences.unit
                );
            }.bind(this);
            const minX = read('minX', dimensions.minX);
            const minZ = read('minZ', dimensions.minZ);
            const width = canonicalDistance(finite(
                this.propertiesBody.querySelector('[data-property="width"]').value,
                NaN
            ), this.planPreferences.unit);
            const depth = canonicalDistance(finite(
                this.propertiesBody.querySelector('[data-property="depth"]').value,
                NaN
            ), this.planPreferences.unit);
            this._invoke('Edit zone geometry', function () {
                if (typeof this.session.editZoneGeometry === 'function') {
                    return this.session.editZoneGeometry(
                        selected.value.zoneId,
                        { minX: minX, minZ: minZ, width: width, depth: depth }
                    );
                }
                return this.session.editZoneDimensions(
                    selected.value.zoneId,
                    { width: width, depth: depth }
                );
            }.bind(this));
            return;
        }
        if (selected.kind === 'aisle') {
            const route = selected.value;
            const patch = {};
            if (field === 'label') {
                const label = String(event.target.value || '').trim();
                if (!label || label.length > 120) return;
                patch.label = label;
            } else if (field === 'corridorWidth') {
                const width = canonicalDistance(
                    finite(event.target.value, NaN),
                    this.planPreferences.unit
                );
                if (!(width > 0)) return;
                patch.corridorWidth = width;
            } else if (field === 'direction' || field === 'color') {
                patch[field] = String(event.target.value || '');
            } else {
                return;
            }
            this._invoke('Edit facility aisle', function () {
                return this.session.editAisle(route.routeId, patch);
            }.bind(this));
            return;
        }
        if (selected.kind === 'floor-marking') {
            const marking = selected.value;
            const patch = {};
            if (field === 'label') {
                const label = String(event.target.value || '').trim();
                if (!label || label.length > 120) {
                    this._setError(new Error(
                        'Floor marking name must contain 1 to 120 characters'
                    ));
                    return;
                }
                patch.label = label;
            } else if (field === 'text') {
                const text = String(event.target.value || '');
                if (text.length > 120
                        || (marking.markingType === 'floor_text' && !text)) {
                    this._setError(new Error('Floor marking text is invalid'));
                    return;
                }
                patch.text = text;
            } else if (field === 'fillColor' || field === 'strokeColor') {
                patch[field] = String(event.target.value || '');
            } else if (field === 'opacity') {
                const opacity = finite(event.target.value, NaN);
                if (!Number.isFinite(opacity) || opacity < 0 || opacity > 1) return;
                patch.opacity = opacity;
            } else if (field === 'width' || field === 'depth') {
                const value = canonicalDistance(
                    finite(event.target.value, NaN),
                    this.planPreferences.unit
                );
                if (!(value > 0)) return;
                patch[field] = value;
            } else if (['x', 'y', 'z', 'rotation'].includes(field)) {
                const transform = clone(marking.transform || {});
                transform.position = clone(transform.position || {
                    x: 0, y: 0, z: 0,
                });
                if (field === 'rotation') {
                    const rotation = finite(event.target.value, NaN);
                    if (!Number.isFinite(rotation)) return;
                    transform.rotationDegrees = rotation;
                } else {
                    const value = canonicalDistance(
                        finite(event.target.value, NaN),
                        this.planPreferences.unit
                    );
                    if (!Number.isFinite(value)) return;
                    transform.position[field] = value;
                }
                patch.transform = transform;
                patch.positionMode = 'manual';
            } else {
                return;
            }
            this._invoke('Edit floor marking', function () {
                return this.session.editFloorMarking(marking.markingId, patch);
            }.bind(this));
            return;
        }
        if (selected.kind !== 'placement') return;
        const placement = selected.value;
        if (['x', 'y', 'z'].includes(field)) {
            const current = placement.transform.position;
            const next = canonicalDistance(
                finite(event.target.value, NaN),
                this.planPreferences.unit
            );
            if (!Number.isFinite(next)) return;
            const delta = { x: 0, y: 0, z: 0 };
            delta[field] = snapCoordinate(
                next,
                field === 'y' ? 0 : this._activeSnapStep()
            )
                - finite(current[field], 0);
            this._invoke('Move selection', function () {
                return this.session.moveSelected(delta);
            }.bind(this));
        } else if (field === 'rotation') {
            const requested = finite(event.target.value, NaN);
            if (!Number.isFinite(requested)) return;
            const current = quaternionYawDegrees(placement.transform.quaternion);
            const turns = Math.round((requested - current) / 90);
            if (Math.abs(current + turns * 90 - requested) > 0.001) {
                this._setError(new Error('Rotation must use 90-degree increments'));
                return;
            }
            this._invoke('Rotate selection', function () {
                return this.session.rotateSelected90(turns);
            }.bind(this));
        }
    };

    Workspace.prototype._field = function (label, property, value, options) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-property-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        const attributes = Object.assign({
            type: 'number',
            value: Number.isFinite(value) ? String(Number(value.toFixed(4))) : '',
            'data-property': property,
            'aria-label': label,
        }, options || {});
        wrapper.appendChild(element(this.document, 'input', attributes));
        return wrapper;
    };

    Workspace.prototype._textField = function (label, property, value, options) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-property-field ip-flw-property-field-wide',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        wrapper.appendChild(element(this.document, 'input', Object.assign({
            type: 'text',
            value: String(value || ''),
            'data-property': property,
            'aria-label': label,
        }, options || {})));
        return wrapper;
    };

    Workspace.prototype._colorField = function (label, property, value) {
        const wrapper = element(this.document, 'label', {
            className: 'ip-flw-property-field',
        });
        wrapper.appendChild(element(this.document, 'span', {}, label));
        wrapper.appendChild(element(this.document, 'input', {
            type: 'color',
            value: value,
            'data-property': property,
            'aria-label': label,
        }));
        return wrapper;
    };

    Workspace.prototype._selectionGeometry = function () {
        if (!this.state.layout || !this.state.selection.length
                || !this.patternRuntime
                || typeof this.patternRuntime.collectSelection !== 'function') {
            return null;
        }
        const items = this.patternRuntime.collectSelection(
            this.state.layout,
            this.assetCatalog,
            this.state.selection,
            { expandZones: false, includeZones: true }
        );
        if (!items.length) return null;
        const bounds = this.patternRuntime.selectionBounds(items);
        const elevations = items.map(function (item) {
            return finite(item.position && item.position.y, 0);
        });
        const rotations = items.map(function (item) {
            return finite(item.rotationDegrees, 0);
        });
        const sharedRotation = rotations.every(function (value) {
            return Math.abs(value - rotations[0]) < 0.001;
        }) ? rotations[0] : NaN;
        return {
            items: items,
            center: bounds.center,
            width: bounds.width,
            depth: bounds.depth,
            elevation: elevations.reduce(function (sum, value) {
                return sum + value;
            }, 0) / elevations.length,
            rotation: sharedRotation,
        };
    };

    Workspace.prototype._renderProperties = function () {
        clearElement(this.propertiesBody);
        this.propertiesPane.hidden = !this.state.loaded
            || !this.state.selection.length
            || this.viewMode !== 'plan';
        if (!this.state.loaded) {
            this.propertiesBody.appendChild(element(this.document, 'p', {
                className: 'ip-flw-empty',
            }, 'Load a layout to begin.'));
            return;
        }
        if (!this.state.selection.length) {
            this.propertiesBody.appendChild(element(this.document, 'p', {
                className: 'ip-flw-empty',
            }, 'Select an asset or zone.'));
            return;
        }
        if (this.state.selection.length > 1) {
            const geometry = this._selectionGeometry();
            this.propertiesBody.appendChild(element(this.document, 'div', {
                className: 'ip-flw-selection-summary',
            }, this.state.selection.length + ' objects selected'));
            if (geometry) {
                const unit = this.planPreferences.unit;
                const grid = element(this.document, 'div', {
                    className: 'ip-flw-property-grid',
                });
                append(grid,
                    this._field('Group center X (' + unit + ')', 'multi-x',
                        displayDistance(geometry.center.x, unit), { step: '0.1' }),
                    this._field('Group center Z (' + unit + ')', 'multi-z',
                        displayDistance(geometry.center.z, unit), { step: '0.1' }),
                    this._field('Elevation (' + unit + ')', 'multi-y',
                        displayDistance(geometry.elevation, unit), { step: '0.1' }),
                    this._field('Rotation (degrees)', 'multi-rotation',
                        geometry.rotation, { step: '90' }),
                    this._field('Envelope width (' + unit + ')', 'multi-width',
                        displayDistance(geometry.width, unit), { readonly: 'readonly' }),
                    this._field('Envelope depth (' + unit + ')', 'multi-depth',
                        displayDistance(geometry.depth, unit), { readonly: 'readonly' })
                );
                this.propertiesBody.appendChild(grid);
                this.propertiesBody.appendChild(element(this.document, 'p', {
                    className: 'ip-flw-property-note',
                }, 'Envelope dimensions are measured from the selected footprints. '
                    + 'Equipment scaling is intentionally disabled.'));
            }
            return;
        }
        const selected = selectionRecord(this.state.layout, this.state.selection);
        if (!selected) return;
        if (selected.kind === 'placement') {
            const placement = selected.value;
            const heading = cleanString(
                placement.metadata && placement.metadata.instanceLabel,
                placement.assetId
            );
            this.propertiesBody.appendChild(element(this.document, 'h3', {}, heading));
            this.propertiesBody.appendChild(element(this.document, 'dl', {
                className: 'ip-flw-property-list',
            }));
            const list = this.propertiesBody.children[
                this.propertiesBody.children.length - 1
            ];
            [
                ['Asset', placement.assetId],
                ['Placement', placement.placementId],
                ['Position ownership', placement.positionMode],
            ].forEach(function (pair) {
                list.appendChild(element(this.document, 'dt', {}, pair[0]));
                list.appendChild(element(this.document, 'dd', {}, pair[1]));
            }, this);
            const transform = placement.transform || {};
            const position = transform.position || {};
            const unit = this.planPreferences.unit;
            const snapStep = this._activeSnapStep();
            const displayStep = snapStep > 0
                ? displayDistance(snapStep, unit) : 'any';
            const grid = element(this.document, 'div', {
                className: 'ip-flw-property-grid',
            });
            let footprint = null;
            try {
                const selectedGeometry = this._selectionGeometry();
                footprint = selectedGeometry && selectedGeometry.items[0];
            } catch (error) {
                footprint = null;
            }
            append(grid,
                this._field('X position (' + unit + ')', 'x', displayDistance(
                    finite(position.x, 0), unit
                ), {
                    step: String(displayStep),
                }),
                this._field('Y position (' + unit + ')', 'y', displayDistance(
                    finite(position.y, 0), unit
                ), {
                    step: '0.1',
                }),
                this._field('Z position (' + unit + ')', 'z', displayDistance(
                    finite(position.z, 0), unit
                ), {
                    step: String(displayStep),
                }),
                this._field(
                    'Rotation (degrees)',
                    'rotation',
                    quaternionYawDegrees(transform.quaternion),
                    { step: '90' }
                ),
                this._field('Footprint width (' + unit + ')', 'asset-width',
                    footprint ? displayDistance(footprint.width, unit) : NaN,
                    { readonly: 'readonly' }),
                this._field('Footprint depth (' + unit + ')', 'asset-depth',
                    footprint ? displayDistance(footprint.depth, unit) : NaN,
                    { readonly: 'readonly' })
            );
            this.propertiesBody.appendChild(grid);
        } else if (selected.kind === 'aisle') {
            const route = selected.value;
            const aisle = route.extensions && route.extensions.facilityAisle || {};
            const unit = this.planPreferences.unit;
            this.propertiesBody.appendChild(element(
                this.document,
                'h3',
                {},
                cleanString(route.label, route.routeId)
            ));
            this.propertiesBody.appendChild(element(
                this.document,
                'p',
                { className: 'ip-flw-property-kind' },
                cleanString(aisle.aisleKind, 'facility aisle').replace(/_/g, ' ')
            ));
            const grid = element(this.document, 'div', {
                className: 'ip-flw-property-grid',
            });
            append(
                grid,
                this._textField('Aisle name', 'label', route.label, {
                    maxlength: '120',
                }),
                this._field(
                    'Corridor width (' + unit + ')',
                    'corridorWidth',
                    displayDistance(finite(route.corridorWidth, 1), unit),
                    { min: '0.01', step: '0.1' }
                ),
                this._colorField('Display color', 'color',
                    cleanString(aisle.color, '#d9a514'))
            );
            const direction = element(this.document, 'label', {
                className: 'ip-flw-property-field',
            });
            direction.appendChild(element(this.document, 'span', {}, 'Direction'));
            const select = element(this.document, 'select', {
                'data-property': 'direction',
                'aria-label': 'Direction',
            });
            [['two_way', 'Two way'], ['one_way', 'One way']].forEach(
                function (item) {
                    select.appendChild(element(this.document, 'option', {
                        value: item[0],
                        selected: aisle.direction === item[0],
                    }, item[1]));
                },
                this
            );
            direction.appendChild(select);
            grid.appendChild(direction);
            this.propertiesBody.appendChild(grid);
            this.propertiesBody.appendChild(element(this.document, 'p', {
                className: 'ip-flw-property-note',
            }, aisle.clearanceEvidenceStatus === 'unverified'
                ? 'Clearance evidence is unverified.'
                : 'Clearance evidence: ' + aisle.clearanceEvidenceStatus + '.'));
        } else if (selected.kind === 'floor-marking') {
            const marking = selected.value;
            const position = marking.transform && marking.transform.position || {};
            const unit = this.planPreferences.unit;
            this.propertiesBody.appendChild(element(
                this.document,
                'h3',
                {},
                cleanString(marking.label, marking.markingId)
            ));
            this.propertiesBody.appendChild(element(
                this.document,
                'p',
                { className: 'ip-flw-property-kind' },
                String(marking.markingType || 'floor marking').replace(/_/g, ' ')
            ));
            const textGrid = element(this.document, 'div', {
                className: 'ip-flw-property-grid',
            });
            append(textGrid,
                this._textField('Name', 'label', marking.label, {
                    maxlength: '120',
                }),
                this._textField('Floor text', 'text', marking.text, {
                    maxlength: '120',
                })
            );
            this.propertiesBody.appendChild(textGrid);
            const geometryGrid = element(this.document, 'div', {
                className: 'ip-flw-property-grid',
            });
            append(geometryGrid,
                this._field('X position (' + unit + ')', 'x', displayDistance(
                    finite(position.x, 0), unit
                ), { step: '0.1' }),
                this._field('Z position (' + unit + ')', 'z', displayDistance(
                    finite(position.z, 0), unit
                ), { step: '0.1' }),
                this._field('Width (' + unit + ')', 'width', displayDistance(
                    finite(marking.width, 1), unit
                ), { min: '0.01', step: '0.1' }),
                this._field('Depth (' + unit + ')', 'depth', displayDistance(
                    finite(marking.depth, 1), unit
                ), { min: '0.01', step: '0.1' }),
                this._field('Rotation (degrees)', 'rotation', finite(
                    marking.transform && marking.transform.rotationDegrees, 0
                ), { step: '1' }),
                this._field('Opacity', 'opacity', finite(marking.opacity, 1), {
                    min: '0', max: '1', step: '0.05',
                }),
                this._colorField('Fill color', 'fillColor', marking.fillColor),
                this._colorField('Outline color', 'strokeColor', marking.strokeColor)
            );
            this.propertiesBody.appendChild(geometryGrid);
        } else {
            const zone = selected.value;
            const dimensions = zoneDimensions(zone);
            this.propertiesBody.appendChild(element(
                this.document,
                'h3',
                {},
                cleanString(zone.label, zone.zoneId)
            ));
            this.propertiesBody.appendChild(element(
                this.document,
                'p',
                { className: 'ip-flw-property-kind' },
                cleanString(zone.zoneType, 'zone')
            ));
            const nameGrid = element(this.document, 'div', {
                className: 'ip-flw-property-grid',
            });
            nameGrid.appendChild(this._textField(
                'Zone name',
                'label',
                cleanString(zone.label, zone.zoneId),
                { maxlength: '120' }
            ));
            const purposeField = element(this.document, 'label', {
                className: 'ip-flw-property-field ip-flw-property-field-wide',
            });
            purposeField.appendChild(element(
                this.document,
                'span',
                {},
                'Zone purpose'
            ));
            const purposeSelect = element(this.document, 'select', {
                'data-property': 'zoneType',
                'aria-label': 'Zone purpose',
            });
            ZONE_PURPOSE_OPTIONS.forEach(function (option) {
                purposeSelect.appendChild(element(this.document, 'option', {
                    value: option.value,
                    selected: option.value === zone.zoneType,
                }, option.label));
            }, this);
            purposeField.appendChild(purposeSelect);
            nameGrid.appendChild(purposeField);
            this.propertiesBody.appendChild(nameGrid);
            if (dimensions) {
                const unit = this.planPreferences.unit;
                const snapStep = this._activeSnapStep();
                const displayStep = snapStep > 0
                    ? displayDistance(snapStep, unit) : 'any';
                const grid = element(this.document, 'div', {
                    className: 'ip-flw-property-grid',
                });
                append(grid,
                    this._field('Minimum X (' + unit + ')', 'minX',
                        displayDistance(dimensions.minX, unit), {
                        step: String(displayStep),
                    }),
                    this._field('Minimum Z (' + unit + ')', 'minZ',
                        displayDistance(dimensions.minZ, unit), {
                        step: String(displayStep),
                    }),
                    this._field('Zone width (' + unit + ')', 'width',
                        displayDistance(dimensions.width, unit), {
                        min: '0.01',
                        step: String(displayStep),
                    }),
                    this._field('Zone depth (' + unit + ')', 'depth',
                        displayDistance(dimensions.depth, unit), {
                        min: '0.01',
                        step: String(displayStep),
                    })
                );
                this.propertiesBody.appendChild(grid);
            }
        }
    };

    Workspace.prototype._renderToolbarState = function () {
        const hasSelection = this.state.selection.length > 0;
        const selectedPlacements = this.state.layout
            ? this.state.layout.placements.filter(function (placement) {
                return this.state.selection.includes(placement.placementId);
            }, this)
            : [];
        const selectedMarkings = this.state.layout
            ? (this.state.layout.floorMarkings || []).filter(function (marking) {
                return this.state.selection.includes(marking.markingId);
            }, this)
            : [];
        const selectedZones = this.state.layout
            ? (this.state.layout.zones || []).filter(function (zone) {
                return this.state.selection.includes(zone.zoneId);
            }, this)
            : [];
        const selectedCellZones = selectedZones.filter(function (zone) {
            const metadata = zone.extensions && zone.extensions.cellGroup;
            return metadata && metadata.groupKind === 'manufacturing_cell';
        });
        const hasPlacement = selectedPlacements.length > 0;
        const hasMovable = hasPlacement || selectedMarkings.length > 0
            || selectedCellZones.length > 0;
        const selectedMovable = selectedPlacements.concat(selectedMarkings);
        let patternSeedCount = 0;
        let cellSeedCount = 0;
        if (this.patternRuntime
                && typeof this.patternRuntime.collectSelection === 'function'
                && this.state.layout) {
            try {
                patternSeedCount = this.patternRuntime.collectSelection(
                    this.state.layout,
                    this.assetCatalog,
                    this.state.selection,
                    { expandZones: true, includeZones: true }
                ).length;
                cellSeedCount = this.patternRuntime.collectSelection(
                    this.state.layout,
                    this.assetCatalog,
                    this.state.selection,
                    { expandZones: true, includeZones: false }
                ).length;
            } catch (error) {
                patternSeedCount = 0;
                cellSeedCount = 0;
            }
        }
        const allLocked = selectedMovable.length > 0
            && selectedMovable.every(function (item) {
                return item.positionMode === 'locked';
            });
        const generatedDraftActive = Boolean(this.state.generatedDraft);
        const manualEditingBlocked = !this.capabilities.manualAuthoring
            || generatedDraftActive;
        const states = {
            assets: !this.capabilities.assetLibrary
                || generatedDraftActive
                || Boolean(this.state.conflict)
                || Boolean(this.state.layoutProposal)
                || Boolean(this.state.placementAlternatives),
            'rectangle-zone': manualEditingBlocked,
            'polygon-zone': manualEditingBlocked,
            'bulk-zones': manualEditingBlocked
                || typeof this.session.createZones !== 'function',
            'create-cell-group': manualEditingBlocked
                || typeof this.session.createCellGroup !== 'function'
                || cellSeedCount < 1
                || selectedCellZones.length > 0,
            'ungroup-cell': manualEditingBlocked
                || typeof this.session.ungroupCell !== 'function'
                || this.state.selection.length !== 1
                || selectedCellZones.length !== 1,
            'floor-marking': manualEditingBlocked,
            aisle: manualEditingBlocked
                || typeof this.session.createAisle !== 'function',
            'motion-path': manualEditingBlocked
                || !this.navigationRuntime
                || typeof this.session.setFacilityNavigation !== 'function'
                || !this._navigationSelectedActor(),
            'saved-movement': !this.capabilities.navigationMultiActor
                || this.activityRequestPending || Boolean(this.state.conflict)
                || Boolean(activeLayoutAlternative(this.state)) || Boolean(this.constructionPreview)
                || Boolean(this.generationPlanningView && this.generationPlanningView.activeLayout())
                || !this.savedMovementChoices().length,
            // The PDF draws the saved layout, so unsaved changes must be saved first.
            'export-pdf': !this.state.layout || !this.state.layout.layoutId
                || !(this.state.layout.association && this.state.layout.association.siteId)
                || this.state.dirty,
            'auto-arrange': !this.capabilities.fullLayoutProposals
                || typeof this.session.requestLayoutProposal
                    !== 'function'
                || this.state.dirty
                || Boolean(this.state.conflict),
            'top-view': !this.threeAdapter,
            rotate: manualEditingBlocked || !hasMovable,
            duplicate: manualEditingBlocked || !hasMovable,
            delete: manualEditingBlocked || !hasSelection,
            lock: manualEditingBlocked || !hasMovable,
            appearance: typeof this.options.onOpenAppearanceLibrary === 'function'
                ? !this._canEditLibrary() : !this._canEditAppearance(),
            decals: !decalsRuntime || !wallsRuntime.canEdit(this),
            lettering: !decalsRuntime || !wallsRuntime.canEdit(this),
            'component-materials': typeof this.options.onOpenAppearanceLibrary === 'function'
                ? !this._canEditLibrary()
                : !componentMaterialsRuntime || !wallsRuntime.canEdit(this) || this._selectedPlacementRecords().length !== 1,
            'interior-walls': !interiorWallsRuntime || !wallsRuntime.canEdit(this),
            'floor-surfaces': !floorSurfacesRuntime || !wallsRuntime.canEdit(this),
            'replace-asset': !replaceAssetRuntime || !wallsRuntime.canEdit(this) || this._selectedPlacementRecords().length !== 1,
            align: manualEditingBlocked
                || selectedPlacements.length < 2,
            distribute: manualEditingBlocked
                || selectedPlacements.length < 3,
            relative: manualEditingBlocked
                || selectedPlacements.length < 2,
            distance: manualEditingBlocked
                || selectedPlacements.length !== 2,
            offset: manualEditingBlocked || !hasPlacement,
            'linear-pattern': manualEditingBlocked
                || typeof this.session.applyPattern !== 'function'
                || patternSeedCount < 1,
            'circular-pattern': manualEditingBlocked
                || typeof this.session.applyPattern !== 'function'
                || patternSeedCount < 1,
            'perimeter-pattern': manualEditingBlocked
                || typeof this.session.applyPattern !== 'function'
                || cellSeedCount < 1,
            'cell-layout': manualEditingBlocked
                || typeof this.session.applyPattern !== 'function'
                || cellSeedCount < 2,
            'vertical-stack': manualEditingBlocked
                || typeof this.session.applyPattern !== 'function'
                || selectedPlacements.length !== 1
                || selectedPlacements[0].positionMode === 'locked'
                || Boolean(selectedPlacements[0].snapRelationship
                    && selectedPlacements[0].snapRelationship.family
                        === 'vertical_stack'),
            'surface-stack': manualEditingBlocked
                || typeof this.session.applyPattern !== 'function'
                || selectedPlacements.length < 2
                || selectedPlacements.some(function (placement) {
                    return placement.positionMode === 'locked';
                }),
            mirror: manualEditingBlocked
                || typeof this.session.applyPattern !== 'function'
                || patternSeedCount < 1,
            swap: manualEditingBlocked
                || typeof this.session.applyPattern !== 'function'
                || this.state.selection.length !== 2,
            'clear-all': manualEditingBlocked
                || typeof this.session.clearLayout !== 'function'
                || this._layoutContentCount() === 0,
            undo: !this.capabilities.manualAuthoring || !this.state.canUndo,
            redo: !this.capabilities.manualAuthoring || !this.state.canRedo,
            save: !this.capabilities.manualAuthoring
                || !this.state.dirty
                || this.state.canSave === false,
        };
        Object.keys(states).forEach(function (command) {
            const button = this.toolbar.querySelector(
                '[data-command="' + command + '"]'
            );
            if (button) {
                button.disabled = Boolean(
                    states[command]
                    || this.state.busy
                    || (this.assetBrowserState.open && command !== 'assets')
                    || (this.patternState.open
                        && !PATTERN_MODES.includes(command))
                    || (this.planSettingsState.open)
                    || (this.bulkZoneState.open && command !== 'bulk-zones')
                    || (this.cellGroupState.open
                        && command !== 'create-cell-group')
                    || (this.aisleState.open && command !== 'aisle')
                    || (this.navigationState.open
                        && command !== 'motion-path')
                    || (this.clearAllState.open && command !== 'clear-all')
                );
            }
        }, this);
        const assets = this.toolbar.querySelector('[data-command="assets"]');
        if (assets) {
            assets.setAttribute(
                'aria-pressed',
                this.assetBrowserState.open ? 'true' : 'false'
            );
            assets.setAttribute(
                'title',
                this.assetBrowserState.open
                    ? 'Close asset library'
                    : 'Open asset library'
            );
            assets.setAttribute(
                'aria-label',
                this.assetBrowserState.open
                    ? 'Close asset library'
                    : 'Open asset library'
            );
        }
        const lock = this.toolbar.querySelector('[data-command="lock"]');
        if (lock) {
            lock.setAttribute('aria-label', allLocked ? 'Unlock' : 'Lock');
            lock.setAttribute('title', (allLocked ? 'Unlock' : 'Lock') + ' (L)');
            lock.setAttribute('aria-pressed', allLocked ? 'true' : 'false');
            const label = lock.querySelector('.ip-flw-command-label');
            if (label) label.textContent = allLocked ? 'Unlock' : 'Lock';
        }
        PRECISION_MODES.forEach(function (command) {
            const button = this.toolbar.querySelector(
                '[data-command="' + command + '"]'
            );
            if (button) {
                button.setAttribute(
                    'aria-pressed',
                    this.precisionState.open
                        && this.precisionState.mode === command
                        ? 'true' : 'false'
                );
            }
        }, this);
        PATTERN_MODES.forEach(function (command) {
            const button = this.toolbar.querySelector(
                '[data-command="' + command + '"]'
            );
            if (button) {
                button.setAttribute(
                    'aria-pressed',
                    this.patternState.open
                        && this.patternState.mode === command
                        ? 'true' : 'false'
                );
            }
        }, this);
        const commandStates = {};
        const commandButtons = this.toolbar.querySelectorAll
            ? this.toolbar.querySelectorAll('[data-command]')
            : [];
        Array.prototype.forEach.call(commandButtons, function (button) {
            const command = button.getAttribute('data-command');
            const label = button.querySelector('.ip-flw-command-label');
            commandStates[command] = {
                command: command,
                disabled: Boolean(button.disabled),
                active: button.getAttribute('aria-pressed') === 'true',
                label: label ? label.textContent : button.getAttribute('aria-label'),
                title: button.getAttribute('title') || button.getAttribute('aria-label'),
            };
        });
        this.commandStates = commandStates;
        if (typeof this.options.onCommandStateChange === 'function') {
            this.options.onCommandStateChange(clone(commandStates));
        }
    };

    Workspace.prototype._renderStatus = function () {
        if (!this.statusText || !this.state) return;
        const parts = [];
        if (!this.state.loaded) parts.push('No layout loaded');
        else if (this.state.busy) parts.push('Working');
        else if (this.state.conflict) parts.push('Revision conflict');
        else parts.push(this.state.dirty ? 'Unsaved changes' : 'Saved');
        parts.push(this.state.selection.length + ' selected');
        parts.push(this.viewMode === '3d' ? '3D view' : this.viewMode === 'site' ? 'Site view' : 'Plan view');
        parts.push(this.toolMode.replace(/-/g, ' '));
        if (this.lastError) parts.push('Error: ' + this.lastError.message);
        if (this.state.placementAlternatives) {
            parts.push('Authoritative placement preview');
        }
        if (this.state.layoutProposal) {
            parts.push('Full-layout preview not saved');
        }
        this.statusText.textContent = parts.join(' | ');
        this.root.setAttribute('aria-busy', this.state.busy ? 'true' : 'false');
    };

    /**
     * Subscribe to changes in what the viewport represents. Returns an
     * unsubscribe function. Used by the structure tree, which cannot rely on
     * the session broadcast alone because previews bypass it.
     */
    Workspace.prototype.subscribeStructure = function (listener) {
        if (typeof listener !== 'function') return function () {};
        this.structureListeners.push(listener);
        const self = this;
        return function () {
            const index = self.structureListeners.indexOf(listener);
            if (index >= 0) self.structureListeners.splice(index, 1);
        };
    };

    /**
     * Read-only view of what the structure tree needs, deliberately without
     * clone(): this is read on every structure notification, and cloning the
     * whole layout each time would make an observer more expensive than the
     * viewport it observes. Callers must not mutate what they get back.
     *
     * getState() nests the session under `.session`; this exposes the few
     * fields directly so a caller cannot reach for a top-level `layout` that
     * does not exist there.
     */
    Workspace.prototype.structureSource = function () {
        const state = this.state;
        if (!state) return null;
        // The session carries no top-level layoutId: it lives on the layout.
        // Reading the wrong one silently yields '', which would let two
        // different layouts share an invalidation key and an expansion
        // namespace.
        return {
            layout: state.layout || null,
            layoutId: (state.layout && state.layout.layoutId) || '',
            displayName: (state.layout && state.layout.displayName) || '',
            revision: state.draftRevision || state.baseRevision || '',
            selection: Array.isArray(state.selection) ? state.selection : [],
        };
    };

    Workspace.prototype._notifyStructure = function () {
        if (this.destroyed) return;
        for (let index = 0; index < this.structureListeners.length; index += 1) {
            try {
                this.structureListeners[index]();
            } catch (error) {
                // A tree that throws must not break the viewport it observes.
            }
        }
    };

    Workspace.prototype._syncController = function () {
        if (!this.state.layout || !this.controller) return;
        const layoutAlternative = activeLayoutAlternative(this.state);
        const construction = this.constructionPreview;
        const activeConstruction = construction && this.state.editorGenerationId === construction.frame.editorGenerationId
            && this.state.draftRevision === construction.proposal.baseRevision ? construction.proposal : null;
        const proposalPreview = activeConstruction
            ? designProposalPreviewDescriptor(this.state.layout, activeConstruction, null) : proposalPreviewDescriptor(
            this.state,
            layoutAlternative
        );
        const generationLayout = this.generationPlanningView && this.generationPlanningView.activeLayout();
        const renderedLayout = generationLayout || (activeConstruction ? activeConstruction.candidateLayout : layoutAlternative
            ? layoutAlternative.ghostPreview.layout
            : this.state.layout);
        this.siteRepresentedLayout = renderedLayout;
        this.sitePreviewReadOnly = Boolean(generationLayout || activeConstruction || layoutAlternative);
        if (this.siteView) this.siteView.render(renderedLayout, { readOnly: this.sitePreviewReadOnly });
        const layoutFingerprint = JSON.stringify(renderedLayout);
        if (layoutFingerprint !== this.lastLayoutFingerprint) {
            this.controller.setLayout(renderedLayout);
            this.lastLayoutFingerprint = layoutFingerprint;
            this.lastLayoutFitFingerprint = fitFingerprintOf(renderedLayout);
        }
        const commit = this.state.lastApprovedOperationCommit;
        if (commit && commit.directApply && commit.receiptId && commit.receiptId !== this.lastDirectApplyReceiptId) {
            this.lastDirectApplyReceiptId = commit.receiptId;
            const current = this.viewMode;
            const view = directApplyViewFor(commit.operationNames, current);
            const moves = Boolean(view && view !== current && (current === 'site' || view === 'site'));
            // A building step that ends in the 2D plan shows the building large (the user, 2026-10-24: "zoom in the
            // warehouse layout on the 2d plane so it takes much of the viewport display").
            const fitsBuilding = view === 'plan' && (moves || current === 'plan');
            if (moves || fitsBuilding) {
                const self = this;
                Promise.resolve().then(function () {
                    if (self.destroyed || self.viewMode !== current) return;
                    if (moves) self._setViewMode(view);
                    // After the plan view has its size and its own refit for a new building outline.
                    if (fitsBuilding) setTimeout(function () { self._fitPlanToBuilding(); }, 0);
                });
            }
        }
        const proposalVisualFingerprint = proposalPreview
            ? JSON.stringify(proposalPreview) : 'none';
        const proposalVisualChanged = proposalVisualFingerprint
            !== this.lastProposalVisualFingerprint;
        const hadProposalVisual =
            this.lastProposalVisualFingerprint !== 'none';
        if (proposalVisualChanged) {
            [this.topAdapter, this.threeAdapter].filter(Boolean).forEach(
                function (adapter) {
                    if (typeof adapter.setProposalPreview === 'function') {
                        adapter.setProposalPreview(proposalPreview);
                    }
                }
            );
            this.lastProposalVisualFingerprint = proposalVisualFingerprint;
            // A review fits the views to show what it adds, moves or removes. One that only repaints keeps
            // the user's view, both when it opens and when it closes.
            const repaintOnly = appearanceOnlyAlternative(layoutAlternative, this.state && this.state.layout);
            const closedRepaint = !proposalPreview && this.lastProposalRepaintOnly;
            if ((proposalPreview || hadProposalVisual) && !(proposalPreview ? repaintOnly : closedRepaint)
                    && typeof this.controller.fit === 'function') {
                this.controller.fit();
            }
            this.lastProposalRepaintOnly = Boolean(proposalPreview) && repaintOnly;
            if (proposalPreview && !hadProposalVisual) {
                // A new review opens where it can be seen: a building step in the 2D plan, not the site photo.
                const view = reviewViewFor(layoutAlternative, this.state && this.state.layout);
                const current = this.viewMode;
                if (view && view !== current && (current === 'site' || view === 'site')) {
                    const self = this;
                    Promise.resolve().then(function () {
                        if (!self.destroyed && self.viewMode === current
                                && self.lastProposalVisualFingerprint !== 'none') {
                            self._setViewMode(view);
                        }
                    });
                }
            }
        }
        const placementIds = new Set(renderedLayout.placements.map(function (item) {
            return item.placementId;
        }));
        const primary = this.state.selection.find(function (id) {
            return placementIds.has(id);
        }) || null;
        if (primary) this.controller.select(primary);
        else this.controller.clearSelection();
        if (this.topAdapter && typeof this.topAdapter.setSelections === 'function') {
            this.topAdapter.setSelections(this.state.selection);
        } else if (this.topAdapter
                && typeof this.topAdapter.setSelection === 'function') {
            this.topAdapter.setSelection(primary);
        }
        if (this.threeAdapter && typeof this.threeAdapter.setSelection === 'function') {
            this.threeAdapter.setSelection(this.state.selection.filter(function (id) {
                return placementIds.has(id);
            }));
        }
        this._notifyStructure();
    };

    Workspace.prototype._syncPlanSettingsFromLayout = function () {
        const next = planSettingsFromLayout(
            this.state && this.state.layout,
            this.planSettings
        );
        const changed = JSON.stringify(next) !== JSON.stringify(
            this.planSettings
        );
        if (!changed) return false;
        this.planSettings = next;
        this._applyPlanEnvironment(next);
        if (this.planSettingsState.open && this.planSettingsState.applying) {
            this.planSettingsState.draft = clone(next);
        }
        return true;
    };

    Workspace.prototype._handleSessionState = function (state) {
        if (this.destroyed) return;
        const nextState = state || this.session.getState();
        const previousBaseRevision = this.state && this.state.baseRevision;
        const previousSessionError = this.state && this.state.lastError;
        if (this.motionPresentation && this.motionLayoutFingerprint
                && JSON.stringify(nextState.layout || {})
                    !== this.motionLayoutFingerprint) {
            this.clearMotionPlayback('layout_changed');
        }
        if (this.activityPresentation && this.activityLayoutFingerprint
                && JSON.stringify(nextState.layout || {})
                    !== this.activityLayoutFingerprint) {
            this.clearActivityPlayback('layout_changed');
        }
        const hadLayoutProposal = Boolean(
            this.state && this.state.layoutProposal
        );
        this.state = nextState;
        if (this.state.lastError) {
            this.lastError = this.state.lastError;
        } else if (previousSessionError && this.lastError === previousSessionError) {
            // Clear the session error it just resolved, preserving a newer
            // error raised by the workspace itself.
            this.lastError = null;
        }
        if (this.navigationState.open) {
            const actorExists = (this.state.layout.placements || []).some(
                function (placement) {
                    return placement.placementId
                        === this.navigationState.actorPlacementId;
                },
                this
            );
            if (!actorExists) {
                this.closeNavigationDialog(false);
            } else if (previousBaseRevision
                    && previousBaseRevision !== this.state.baseRevision) {
                this.navigationState.drawing = false;
                this.navigationState.anchorPicking = false;
                this.navigationState.previewPlaying = false;
                this.navigationState.validationStatus = 'invalid';
                this.navigationState.validation = {
                    code: 'facility_navigation_authoring_stale',
                    expectedRevision: previousBaseRevision,
                    currentRevision: this.state.baseRevision,
                };
                this.navigationState.message = (
                    'The saved base revision changed. Reopen Motion Path before '
                    + 'editing or applying this path.'
                );
            }
        }
        if (this.state.layoutProposal) {
            this.root.setAttribute('data-full-layout-preview', 'true');
        } else {
            this.root.removeAttribute('data-full-layout-preview');
        }
        this._syncPlanSettingsFromLayout();
        this._syncController();
        if (this.state.ghostPlacement
                && this.state.ghostPlacement.worldPosition) {
            this._renderGhost(
                this.state.ghostPlacement.worldPosition,
                this.state.ghostPlacement.assetId
            );
        } else if (!this.state.ghostPlacement) {
            this._hideGhost();
        }
        this._renderProperties();
        if (this.refreshAppearanceDialog) this.refreshAppearanceDialog();
        this._renderAssetBrowser();
        if (this.precisionState.open) this._renderPrecisionDialog();
        if (this.patternState.open) this._renderPatternDialog();
        if (this.planSettingsState.open) this._renderPlanSettingsDialog();
        if (this.navigationState.open) {
            this._renderNavigationDialog();
            this._syncNavigationAuthoringPreview();
        }
        this._renderToolbarState();
        this._renderThreeNavigationState();
        this._syncSelectionToolbar();
        this._renderCandidateControls();
        this._renderDesignPanel();
        this._renderStatus();
        if (hadLayoutProposal && !this.state.layoutProposal) {
            this._restoreProposalFocus();
        }
        if (typeof this.options.onStateChange === 'function') {
            this.options.onStateChange(clone(this.state));
        }
    };

    Workspace.prototype._setError = function (error) {
        this.lastError = error instanceof Error ? error : new Error(String(error));
        this._renderStatus();
        if (typeof this.options.onError === 'function') {
            this.options.onError(this.lastError);
        }
    };

    Workspace.prototype._invoke = function (label, action) {
        const run = this.pending.then(function () {
            if (this.destroyed) throw new Error('facility workspace is destroyed');
            return action();
        }.bind(this));
        this.pending = run.then(function (result) {
            this.lastError = null;
            this._renderStatus();
            return result;
        }.bind(this), function (error) {
            this._setError(error);
            return undefined;
        }.bind(this));
        return run;
    };

    Workspace.prototype.whenIdle = function () {
        return this.pending;
    };

    Workspace.prototype._handleKeyDown = function (event) {
        if (!event || isTypingTarget(event.target)) return;
        if (this.assetBrowserState.open) return;
        const key = String(event.key || '').toLowerCase();
        const modifier = Boolean(event.ctrlKey || event.metaKey);
        if (!modifier && key === 'e' && this._threeImmersiveActive()) {
            if (this._openWalkthroughContext()) {
                if (typeof event.preventDefault === 'function') {
                    event.preventDefault();
                }
                if (typeof event.stopPropagation === 'function') {
                    event.stopPropagation();
                }
            }
            return;
        }
        if (key === 'escape' && this.walkthroughContextState.expanded) {
            if (typeof event.preventDefault === 'function') {
                event.preventDefault();
            }
            if (typeof event.stopPropagation === 'function') {
                event.stopPropagation();
            }
            this._closeWalkthroughContext();
            return;
        }
        let command = null;
        if (modifier && key === 'z' && event.shiftKey) command = 'redo';
        else if (modifier && key === 'z') command = 'undo';
        else if (modifier && key === 'y') command = 'redo';
        else if (modifier && key === 's') command = 'save';
        else if (modifier && key === 'd') command = 'duplicate';
        else if (key === 'delete' || key === 'backspace') command = 'delete';
        else if (!modifier && key === 'r') command = 'rotate';
        else if (!modifier && key === 'l') command = 'lock';
        else if (!modifier && event.shiftKey && key === 'f') {
            command = 'fit-layout';
        } else if (!modifier && key === 'f') command = 'fit';
        else if (!modifier && key === 't') command = 'top-view';
        else if (!modifier && key === 'v') command = 'select';
        else if (!modifier && key === 'h') command = 'pan';
        else if (!modifier && key === 'm') command = 'floor-marking';
        else if (!modifier && key === 'p' && event.shiftKey) {
            command = 'motion-path';
        } else if (key === 'enter' && this.toolMode === 'motion-path'
                && this.navigationState.open
                && this.navigationState.drawing) {
            this.navigationState.drawing = false;
            this.navigationState.message = 'Drawing complete.';
            this._renderNavigationDialog();
            if (typeof event.preventDefault === 'function') {
                event.preventDefault();
            }
            return;
        } else if (key === 'enter' && this.toolMode === 'polygon-zone') {
            if (this._finishPolygon() && typeof event.preventDefault === 'function') {
                event.preventDefault();
            }
            return;
        } else if (key === 'escape') {
            if (typeof event.preventDefault === 'function') {
                event.preventDefault();
            }
            if (this.navigationState.open) {
                this.closeNavigationDialog(true);
                return;
            }
            this.polygonPoints = [];
            this._cancelPointerGesture();
            if (this.state.layoutProposal
                    && typeof this.session.dismissLayoutProposal
                        === 'function') {
                this._invoke('Dismiss layout proposal', function () {
                    return this.session.dismissLayoutProposal();
                }.bind(this));
            } else if (this.state.placementAlternatives
                    && typeof this.session.dismissPlacementAlternatives
                        === 'function') {
                this.session.dismissPlacementAlternatives();
            } else {
                this._cancelGhost();
            }
            this._setToolMode('select');
            if (typeof event.preventDefault === 'function') event.preventDefault();
            return;
        }
        if (!command) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        this.executeCommand(command);
    };

    Workspace.prototype.getState = function () {
        const topDiagnostics = this.topAdapter
            && typeof this.topAdapter.getDiagnostics === 'function'
            ? this.topAdapter.getDiagnostics() : {};
        const threeDiagnostics = this.threeAdapter
            && typeof this.threeAdapter.getDiagnostics === 'function'
            ? this.threeAdapter.getDiagnostics() : {};
        return {
            apiVersion: API_VERSION,
            destroyed: this.destroyed,
            suspended: this.suspended,
            toolMode: this.toolMode,
            viewMode: this.viewMode,
            gridSize: this.gridSize,
            planPreferences: clone(this.planPreferences),
            planSettings: clone(this.planSettings),
            planSettingsEditor: clone(this.planSettingsState),
            bulkZones: clone(this.bulkZoneState),
            cellGroup: clone(this.cellGroupState),
            aisle: clone(this.aisleState),
            navigation: clone(this.navigationState),
            floorMarking: clone(this.floorMarkingState),
            layers: {
                panelOpen: this.layerPanelOpen,
                visibility: clone(this.layerVisibility),
            },
            motion: clone(this.motionState),
            activity: clone(this.activityState),
            design: clone(this.designState),
            recording: clone(this.recordingState),
            threeNavigation: {
                mode: this.threeNavigationMode,
                gridVisible: this.threeGridVisible,
                settingsOpen: this.threeSettingsOpen,
                orientationMenuOpen: this.threeViewMenuOpen,
                orientation: this.threeOrientation,
                viewpointsOpen: this.threeViewpointsOpen,
                viewpoints: clone(this.threeViewpoints),
                visualSettings: clone(this.threeVisualSettings),
                compass: clone(this.threeCompassOrientation),
                walkthrough: clone(this.threeWalkthrough),
                drone: clone(this.threeDrone),
                contextCard: clone(this.walkthroughContextState),
            },
            renderConsistency: {
                topPlan: clone(
                    topDiagnostics.placementTransformAudit || null
                ),
                three: clone(
                    threeDiagnostics.placementTransformAudit || null
                ),
            },
            session: clone(this.state),
            activeDrag: clone(this.activeDrag && this.activeDrag.payload),
            dragAdvisory: clone(this.dragAdvisory),
            polygonPointCount: this.polygonPoints.length,
            assetBrowser: clone(this.assetBrowserState),
            precisionPositioning: clone(this.precisionState),
            pattern: clone(this.patternState),
            selectionToolbar: {
                open: Boolean(this.selectionToolbarManager
                    && this.selectionToolbarManager.isOpen()),
                key: this.selectionToolbarKey,
            },
            lastError: this.lastError,
        };
    };

    Workspace.prototype.getCommandStates = function () {
        return clone(this.commandStates);
    };

    Workspace.prototype.suspend = function () {
        this.closeAppearanceDialog();
        if (this.destroyed || this.suspended) return false;
        if (this.motionState.playing && this.threeAdapter
                && this.threeAdapter.motion) {
            this.threeAdapter.motion.pause();
        }
        if (this.activityState.playing && this.threeAdapter
                && this.threeAdapter.activity) {
            this.threeAdapter.activity.pause();
        }
        if (this.navigationState.previewPlaying && this.threeAdapter
                && this.threeAdapter.navigationPreview) {
            this.threeAdapter.navigationPreview.pause();
        }
        this._cancelRecordingCountdown();
        if (this.recordingController
                && ['recording', 'paused'].includes(
                    this.recordingState.status
                )) {
            this.recordingController.stop();
        }
        if (this.threeWalkthrough.active && this.threeAdapter
                && typeof this.threeAdapter.exitWalkthrough === 'function') {
            this.threeAdapter.exitWalkthrough('workspace_suspended');
        }
        if (this.threeDrone.active && this.threeAdapter
                && typeof this.threeAdapter.exitDrone === 'function') {
            this.threeAdapter.exitDrone('workspace_suspended');
        }
        this._closeSelectionToolbar('workspace_suspended', false);
        this._releasePointerCapture();
        this._cancelAdvisoryRequest('Workspace suspended.');
        if (this.controller && typeof this.controller.suspend === 'function') {
            this.controller.suspend();
        } else {
            [this.topAdapter, this.threeAdapter].filter(Boolean).forEach(
                function (adapter) {
                    if (typeof adapter.suspend === 'function') adapter.suspend();
                }
            );
        }
        this.suspendedChildren = [
            this.toolbar,
            this.shell,
            this.assetBrowser,
            this.precisionDialog,
            this.patternDialog,
            this.planSettingsDialog,
            this.bulkZoneDialog,
            this.cellGroupDialog,
            this.aisleDialog,
            this.navigationDialog,
            this.clearAllDialog,
            this.statusBar,
        ].filter(function (child) {
            return child && child.parentNode === this.root;
        }, this);
        this.suspendedChildren.forEach(function (child) {
            this.root.removeChild(child);
        }, this);
        setClassToken(this.root, 'ip-flw-root', false);
        this.root.removeAttribute('data-facility-workspace');
        this.root.removeAttribute('data-tool-mode');
        this.root.removeAttribute('data-view-mode');
        this.root.removeAttribute('data-walkthrough-active');
        this.root.removeAttribute('data-drone-active');
        this.root.removeAttribute('data-full-layout-preview');
        this.root.removeAttribute('data-navigation-open');
        this.root.removeAttribute('data-asset-browser-open');
        this.root.removeAttribute('data-precision-open');
        this.root.removeAttribute('data-pattern-open');
        this.root.removeAttribute('data-plan-settings-open');
        this.root.removeAttribute('data-bulk-zone-open');
        this.root.removeAttribute('data-cell-group-open');
        this.root.removeAttribute('data-aisle-open');
        this.root.removeAttribute('data-clear-all-open');
        this.root.removeAttribute('data-design-pane-open');
        this.suspended = true;
        return true;
    };

    Workspace.prototype.resume = function (nextRoot) {
        if (this.destroyed || !this.suspended) return false;
        const target = nextRoot || this.root;
        if (!target || target.ownerDocument !== this.document) {
            throw new TypeError('workspace resume root must use the original document');
        }
        this.root = target;
        clearElement(this.root);
        setClassToken(this.root, 'ip-flw-root', true);
        this.root.setAttribute('data-facility-workspace', '');
        this.suspendedChildren.forEach(function (child) {
            this.root.appendChild(child);
        }, this);
        this.suspendedChildren = [];
        this.suspended = false;
        if (this.controller && typeof this.controller.resume === 'function') {
            this.controller.resume();
        } else {
            [this.topAdapter, this.threeAdapter].filter(Boolean).forEach(
                function (adapter) {
                    if (typeof adapter.resume === 'function') adapter.resume();
                }
            );
        }
        this._setToolMode(this.toolMode);
        this._setViewMode(this.viewMode);
        if (this.assetBrowserState.open) {
            this.root.setAttribute('data-asset-browser-open', 'true');
        }
        if (this.precisionState.open) {
            this.root.setAttribute('data-precision-open', 'true');
        }
        if (this.patternState.open) {
            this.root.setAttribute('data-pattern-open', 'true');
            this._renderPatternDialog();
        }
        if (this.planSettingsState.open) {
            this.root.setAttribute('data-plan-settings-open', 'true');
            this._renderPlanSettingsDialog();
        }
        if (this.bulkZoneState.open) {
            this.root.setAttribute('data-bulk-zone-open', 'true');
            this._renderBulkZoneDialog();
        }
        if (this.cellGroupState.open) {
            this.root.setAttribute('data-cell-group-open', 'true');
            this._renderCellGroupDialog();
        }
        if (this.aisleState.open) {
            this.root.setAttribute('data-aisle-open', 'true');
            this._renderAisleDialog();
        }
        if (this.navigationState.open) {
            this.root.setAttribute('data-navigation-open', 'true');
            this._renderNavigationDialog();
            this._syncNavigationAuthoringPreview();
        }
        if (this.clearAllState.open) {
            this.root.setAttribute('data-clear-all-open', 'true');
            this.clearAllDialog.hidden = false;
        }
        this._renderToolbarState();
        this._renderStatus();
        this._syncSelectionToolbar();
        return true;
    };

    Workspace.prototype.destroy = function () {
        if (decalsRuntime) decalsRuntime.closeDialog(this);
        if (authoringDialogs) authoringDialogs.close(this);
        this.closeAppearanceDialog();
        if (this.destroyed) return false;
        this.destroyed = true;
        if (this.walkCameraControl) this.walkCameraControl.dispose();
        this.walkCameraControl = null;
        this.clearMotionPlayback('workspace_destroyed');
        this.clearActivityPlayback('workspace_destroyed');
        this._finishMovableDialogDrag(null, true);
        this._cancelRecordingCountdown();
        if (this.recordingController
                && typeof this.recordingController.dispose === 'function') {
            this.recordingController.dispose();
        }
        this.recordingController = null;
        if (this.threeAdapter
                && typeof this.threeAdapter.setWalkthroughStateHandler
                    === 'function') {
            this.threeAdapter.setWalkthroughStateHandler(null);
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setDroneStateHandler
                    === 'function') {
            this.threeAdapter.setDroneStateHandler(null);
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setMotionStateHandler
                    === 'function') {
            this.threeAdapter.setMotionStateHandler(null);
        }
        if (this.threeAdapter
                && typeof this.threeAdapter
                    .setNavigationPreviewStateHandler === 'function') {
            this.threeAdapter.setNavigationPreviewStateHandler(null);
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setWalkthroughContextHandler
                    === 'function') {
            this.threeAdapter.setWalkthroughContextHandler(null);
        }
        if (this.threeAdapter
                && typeof this.threeAdapter.setCameraOrientationHandler
                    === 'function') {
            this.threeAdapter.setCameraOrientationHandler(null);
        }
        if (this.unsubscribe) this.unsubscribe();
        this.unsubscribe = null;
        this.structureListeners = [];
        if (this.selectionToolbarManager) {
            this.selectionToolbarManager.destroy();
        }
        this.selectionToolbarManager = null;
        this.selectionToolbarElement = null;
        this.selectionToolbarReference = null;
        this.selectionToolbarKey = null;
        if (this.marqueeCleanup) this.marqueeCleanup();
        this.marqueeCleanup = null;
        this._releasePointerCapture();
        this._cancelAdvisoryRequest('Workspace destroyed.');
        if (this.ownsSpatialAdvisor && this.spatialAdvisor
                && typeof this.spatialAdvisor.destroy === 'function') {
            this.spatialAdvisor.destroy();
        }
        this.spatialAdvisor = null;
        this.listeners.splice(0).forEach(function (remove) { remove(); });
        if (this.ownsController && this.controller
                && typeof this.controller.dispose === 'function') {
            this.controller.dispose();
        } else {
            if (this.createdTopAdapter && this.topAdapter
                    && typeof this.topAdapter.dispose === 'function') {
                this.topAdapter.dispose();
            }
            if (this.createdThreeAdapter && this.threeAdapter
                    && typeof this.threeAdapter.dispose === 'function') {
                this.threeAdapter.dispose();
            }
        }
        this._hideGhost();
        this.proposalFocusReturn = null;
        this.assetBrowserFocusReturn = null;
        this.precisionFocusReturn = null;
        this.patternFocusReturn = null;
        this._setPatternPreview(null);
        this.suspended = false;
        this.suspendedChildren = [];
        if (this.motionPanel
                && this.motionPanel.getAttribute('data-motion-docked') === 'true'
                && this.motionPanel.parentNode) {
            this.motionPanel.parentNode.removeChild(this.motionPanel);
        }
        clearElement(this.root);
        setClassToken(this.root, 'ip-flw-root', false);
        this.root.removeAttribute('data-facility-workspace');
        this.root.removeAttribute('data-tool-mode');
        this.root.removeAttribute('data-view-mode');
        this.root.removeAttribute('data-walkthrough-active');
        this.root.removeAttribute('data-drone-active');
        this.root.removeAttribute('data-full-layout-preview');
        this.root.removeAttribute('data-asset-browser-open');
        this.root.removeAttribute('data-precision-open');
        this.root.removeAttribute('data-pattern-open');
        this.root.removeAttribute('data-navigation-open');
        return true;
    };

    function createWorkspace(options) {
        return new Workspace(options);
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        ASSET_MIME: ASSET_MIME,
        DEFAULT_GRID_SIZE: DEFAULT_GRID_SIZE,
        TOOL_MODES: TOOL_MODES,
        VIEW_MODES: VIEW_MODES,
        PRECISION_MODES: PRECISION_MODES,
        PATTERN_MODES: PATTERN_MODES,
        CELL_LAYOUT_PRESETS: CELL_LAYOUT_PRESETS,
        selectionToolbarCommands: selectionToolbarCommands,
        Workspace: Workspace,
        createWorkspace: createWorkspace,
        createAssetDragPayload: createAssetDragPayload,
        parseAssetDragPayload: parseAssetDragPayload,
        snapWorldPoint: snapWorldPoint,
        quarterTurnQuaternion: quarterTurnQuaternion,
        normalizeCatalog: normalizeCatalog,
        buildAssetBatchPlacementRequests: buildAssetBatchPlacementRequests,
        buildAlignmentUpdates: buildAlignmentUpdates,
        buildDistributionUpdates: buildDistributionUpdates,
        buildRelativePositionUpdates: buildRelativePositionUpdates,
        measurePlacementDistance: measurePlacementDistance,
        buildDistanceUpdate: buildDistanceUpdate,
        zoneDimensions: zoneDimensions,
        buildAutoArrangeRequest: buildAutoArrangeRequest,
        buildLayoutProposalReview: buildLayoutProposalReview,
        proposalDiagnosticSummary: proposalDiagnosticSummary,
        resizeFloorMarkingFromHandle: resizeFloorMarkingFromHandle,
    });
}));
