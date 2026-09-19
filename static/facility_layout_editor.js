(function (root, factory) {
    'use strict';
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityLayout = api;
}(typeof window !== 'undefined'
    ? window
    : (typeof self !== 'undefined' ? self : null), function (root) {
    'use strict';

    const API_VERSION = 1;
    const DEFAULT_VIEW_PADDING = 24;
    const DEFAULT_PLAN_GRID_SPACING = 1;
    const DEFAULT_PLAN_MAJOR_GRID_SPACING = 5;
    const METERS_TO_FEET = 3.280839895;
    const MAX_PLAN_GRID_LINES = 512;
    const DEFAULT_LAYER_VISIBILITY = Object.freeze({
        zones: true,
        cells: true,
        routes: true,
        markings: true,
        assets: true,
    });
    const DEFAULT_FALLBACK_FOOTPRINT = Object.freeze([
        Object.freeze({ x: -0.6, z: -0.4 }),
        Object.freeze({ x: 0.6, z: -0.4 }),
        Object.freeze({ x: 0.6, z: 0.4 }),
        Object.freeze({ x: -0.6, z: 0.4 }),
    ]);

    function clone(value) {
        if (value === undefined) return undefined;
        return JSON.parse(JSON.stringify(value));
    }

    function finite(value) {
        return typeof value === 'number' && Number.isFinite(value);
    }

    function finiteOr(value, fallback) {
        return finite(value) ? value : fallback;
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

    function zonePresentationLayer(zone) {
        return zone && zone.parentZoneId ? 'cells' : 'zones';
    }

    function assertLayout(layout) {
        if (!layout || typeof layout !== 'object' || Array.isArray(layout)) {
            throw new TypeError('facility layout must be an object');
        }
        if (layout.schemaVersion !== 1) {
            throw new Error('unsupported facility layout schema version');
        }
        ['zones', 'placements', 'routes'].forEach(function (key) {
            if (!Array.isArray(layout[key])) {
                throw new TypeError('facility layout ' + key + ' must be an array');
            }
        });
        const placementIds = new Set();
        layout.placements.forEach(function (placement) {
            const placementId = placement && placement.placementId;
            if (typeof placementId !== 'string' || !placementId) {
                throw new TypeError('every placement requires a stable placementId');
            }
            if (placementIds.has(placementId)) {
                throw new Error('duplicate placementId: ' + placementId);
            }
            placementIds.add(placementId);
        });
        const markingIds = new Set();
        (layout.floorMarkings || []).forEach(function (marking) {
            const markingId = marking && marking.markingId;
            if (typeof markingId !== 'string' || !markingId) {
                throw new TypeError('every floor marking requires a stable markingId');
            }
            if (markingIds.has(markingId)) {
                throw new Error('duplicate markingId: ' + markingId);
            }
            markingIds.add(markingId);
        });
        return layout;
    }

    function point(value) {
        if (!value || !finite(value.x) || !finite(value.z)) return null;
        return { x: value.x, z: value.z };
    }

    function normalizePointList(value) {
        if (!Array.isArray(value) || value.length < 3) return null;
        const result = value.map(point);
        return result.every(Boolean) ? result : null;
    }

    function rectangleFromSize(width, depth) {
        const safeWidth = finite(width) && width > 0 ? width : 1.2;
        const safeDepth = finite(depth) && depth > 0 ? depth : 0.8;
        return [
            { x: -safeWidth / 2, z: -safeDepth / 2 },
            { x: safeWidth / 2, z: -safeDepth / 2 },
            { x: safeWidth / 2, z: safeDepth / 2 },
            { x: -safeWidth / 2, z: safeDepth / 2 },
        ];
    }

    function footprintFromValue(value) {
        if (!value) return null;
        const direct = normalizePointList(value);
        if (direct) return direct;
        if (typeof value !== 'object' || Array.isArray(value)) return null;

        const named = normalizePointList(value.footprint)
            || normalizePointList(value.footprintPolygon)
            || normalizePointList(value.points);
        if (named) return named;

        const polygons = value.footprintPolygons
            || (value.geometry && value.geometry.footprintPolygons);
        if (Array.isArray(polygons) && polygons.length) {
            const polygon = normalizePointList(polygons[0]);
            if (polygon) return polygon;
        }

        if (finite(value.width) || finite(value.depth)) {
            return rectangleFromSize(value.width, value.depth);
        }
        if (value.size && (finite(value.size.x) || finite(value.size.z))) {
            return rectangleFromSize(value.size.x, value.size.z);
        }
        if (value.min && value.max
                && finite(value.min.x) && finite(value.max.x)
                && finite(value.min.z) && finite(value.max.z)
                && value.max.x > value.min.x && value.max.z > value.min.z) {
            return [
                { x: value.min.x, z: value.min.z },
                { x: value.max.x, z: value.min.z },
                { x: value.max.x, z: value.max.z },
                { x: value.min.x, z: value.max.z },
            ];
        }
        return null;
    }

    function resolveCatalogEntry(placement, options) {
        const catalog = options && options.assetCatalog;
        const catalogEntries = Array.isArray(catalog)
            ? catalog
            : (catalog && (catalog.entries || catalog.assets));
        if (!Array.isArray(catalogEntries)) return null;
        return catalogEntries.find(function (entry) {
            if (!entry || typeof entry !== 'object') return false;
            const revision = entry.assetDefinitionRevision
                || entry.publishedAssetDefinitionRevision
                || entry.definitionRevision;
            return entry.assetId === placement.assetId
                && (!revision
                    || revision === placement.assetDefinitionRevision);
        }) || null;
    }

    function resolveLocalFootprint(placement, options) {
        const resolver = options && options.resolveAssetBounds;
        if (typeof resolver === 'function') {
            const resolved = footprintFromValue(resolver(placement));
            if (resolved) return resolved;
        }

        const catalogEntry = resolveCatalogEntry(placement, options);
        if (catalogEntry) {
            const definition = catalogEntry.definition
                || catalogEntry.assetDefinition
                || {};
            const catalogFootprint = footprintFromValue(catalogEntry)
                || footprintFromValue(definition)
                || footprintFromValue(definition.geometry)
                || footprintFromValue(
                    definition.geometry && definition.geometry.aabb
                );
            if (catalogFootprint) return catalogFootprint;
        }

        const maps = options && [
            options.assetFootprints,
            options.assetBounds,
            options.assetBoundsByAssetId,
        ];
        if (maps) {
            for (let index = 0; index < maps.length; index += 1) {
                const map = maps[index];
                if (!map || typeof map !== 'object') continue;
                const value = map[placement.assetDefinitionRevision]
                    || map[placement.assetId];
                const resolved = footprintFromValue(value);
                if (resolved) return resolved;
            }
        }

        const embedded = footprintFromValue(placement.footprint)
            || footprintFromValue(placement.bounds)
            || footprintFromValue(placement.metadata);
        if (embedded) return embedded;

        const fallback = footprintFromValue(options && options.fallbackFootprint);
        return fallback || DEFAULT_FALLBACK_FOOTPRINT.map(point);
    }

    function rotatePointByQuaternion(value, quaternion) {
        const q = quaternion || {};
        const qx = finiteOr(q.x, 0);
        const qy = finiteOr(q.y, 0);
        const qz = finiteOr(q.z, 0);
        const qw = finiteOr(q.w, 1);
        const vx = value.x;
        const vy = 0;
        const vz = value.z;

        const ix = qw * vx + qy * vz - qz * vy;
        const iy = qw * vy + qz * vx - qx * vz;
        const iz = qw * vz + qx * vy - qy * vx;
        const iw = -qx * vx - qy * vy - qz * vz;

        return {
            x: ix * qw + iw * -qx + iy * -qz - iz * -qy,
            z: iz * qw + iw * -qz + ix * -qy - iy * -qx,
        };
    }

    function placementFootprint(placement, options) {
        const transform = placement && placement.transform || {};
        const position = transform.position || {};
        const origin = {
            x: finiteOr(position.x, 0),
            z: finiteOr(position.z, 0),
        };
        return resolveLocalFootprint(placement || {}, options || {}).map(function (local) {
            const rotated = rotatePointByQuaternion(local, transform.quaternion);
            return {
                x: origin.x + rotated.x,
                z: origin.z + rotated.z,
            };
        });
    }

    function floorMarkingFootprint(marking) {
        const transform = marking && marking.transform || {};
        const position = transform.position || {};
        const origin = {
            x: finiteOr(position.x, 0),
            z: finiteOr(position.z, 0),
        };
        const width = Math.max(0.01, finiteOr(marking && marking.width, 1));
        const depth = Math.max(0.01, finiteOr(marking && marking.depth, 1));
        const radians = finiteOr(transform.rotationDegrees, 0) * Math.PI / 180;
        const cosine = Math.cos(radians);
        const sine = Math.sin(radians);
        return rectangleFromSize(width, depth).map(function (local) {
            return {
                x: origin.x + local.x * cosine + local.z * sine,
                z: origin.z - local.x * sine + local.z * cosine,
            };
        });
    }

    function yawQuaternion(degrees) {
        const radians = finiteOr(degrees, 0) * Math.PI / 180;
        return {
            x: 0,
            y: Math.sin(radians / 2),
            z: 0,
            w: Math.cos(radians / 2),
        };
    }

    function collectTopPlanGeometry(layout, options) {
        assertLayout(layout);
        const geometry = {
            zones: [],
            floorMarkings: [],
            routes: [],
            placements: [],
        };
        layout.zones.forEach(function (zone) {
            const polygon = normalizePointList(zone && zone.boundary);
            if (!polygon) return;
            const knowledge = zone.extensions
                && zone.extensions.knowledgeFoundation || {};
            geometry.zones.push({
                zoneId: zone.zoneId,
                zoneType: zone.zoneType,
                label: zone.label,
                parentZoneId: knowledge.parentZoneId || null,
                entityKind: knowledge.entityKind || (
                    knowledge.parentZoneId ? 'subzone' : 'department'
                ),
                fillColor: zone.extensions && zone.extensions.style
                    && zone.extensions.style.fillColor,
                points: polygon,
            });
        });
        layout.routes.forEach(function (route) {
            const points = Array.isArray(route && route.centerline)
                ? route.centerline.map(point).filter(Boolean)
                : [];
            if (points.length < 2) return;
            geometry.routes.push({
                routeId: route.routeId,
                label: route.label || route.routeId,
                routeKind: route.routeKind,
                corridorWidth: finiteOr(route.corridorWidth, 0),
                extensions: clone(route.extensions || {}),
                points: points,
            });
        });
        (layout.floorMarkings || []).forEach(function (marking) {
            if (!marking || !marking.markingId) return;
            geometry.floorMarkings.push({
                markingId: marking.markingId,
                markingType: marking.markingType || 'solid_line',
                label: marking.label || marking.markingId,
                semanticRole: marking.semanticRole || 'decorative',
                positionMode: marking.positionMode || 'manual',
                transform: clone(marking.transform || {}),
                width: Math.max(0.01, finiteOr(marking.width, 1)),
                depth: Math.max(0.01, finiteOr(marking.depth, 1)),
                fillColor: marking.fillColor || '#facc15',
                strokeColor: marking.strokeColor || '#111827',
                opacity: Math.max(0, Math.min(1, finiteOr(marking.opacity, 1))),
                text: String(marking.text || ''),
                points: floorMarkingFootprint(marking),
            });
        });
        layout.placements.forEach(function (placement) {
            const points = placementFootprint(placement, options);
            const bounds = geometryBounds(points);
            const catalogEntry = resolveCatalogEntry(placement, options) || {};
            const definition = catalogEntry.definition
                || catalogEntry.assetDefinition
                || {};
            geometry.placements.push({
                placementId: placement.placementId,
                assetId: placement.assetId,
                positionMode: placement.positionMode,
                transform: clone(placement.transform || {}),
                position: clone(placement.transform
                    && placement.transform.position || { x: 0, y: 0, z: 0 }),
                snapRelationship: clone(placement.snapRelationship || null),
                label: placement.metadata && (
                    placement.metadata.instanceLabel || placement.metadata.label
                ) || catalogEntry.displayName || definition.displayName
                    || placement.assetId || placement.placementId,
                category: catalogEntry.category || definition.category
                    || 'Equipment',
                width: Math.max(0, bounds.maxX - bounds.minX),
                depth: Math.max(0, bounds.maxZ - bounds.minZ),
                points: points,
            });
        });
        return geometry;
    }

    function normalizedPlanWorldBounds(options) {
        const value = options && options.worldBounds;
        if (!value
                || !finite(value.minX) || !finite(value.minZ)
                || !finite(value.maxX) || !finite(value.maxZ)
                || value.maxX <= value.minX
                || value.maxZ <= value.minZ) return null;
        return {
            minX: value.minX,
            minZ: value.minZ,
            maxX: value.maxX,
            maxZ: value.maxZ,
        };
    }

    function normalizedPlanGrid(options, worldBounds) {
        if (!worldBounds) return null;
        const width = worldBounds.maxX - worldBounds.minX;
        const depth = worldBounds.maxZ - worldBounds.minZ;
        const imperial = normalizedPlanDisplayUnit(options) === 'ft';
        const requestedSpacing = Math.max(
            0.05,
            imperial
                ? finiteOr(
                    options && options.imperialGridSpacingFeet,
                    5
                ) / METERS_TO_FEET
                : finiteOr(
                    options && options.floorGridSpacing,
                    DEFAULT_PLAN_GRID_SPACING
                )
        );
        const minimumSpacing = Math.max(width, depth) / 240;
        const spacing = Math.max(
            requestedSpacing,
            Math.ceil(minimumSpacing / requestedSpacing) * requestedSpacing
        );
        const requestedMajor = Math.max(
            spacing,
            imperial
                ? finiteOr(
                    options && options.imperialMajorGridSpacingFeet,
                    25
                ) / METERS_TO_FEET
                : finiteOr(
                    options && options.floorMajorGridSpacing,
                    DEFAULT_PLAN_MAJOR_GRID_SPACING
                )
        );
        return {
            spacing: spacing,
            majorSpacing: Math.max(
                spacing,
                Math.round(requestedMajor / spacing) * spacing
            ),
        };
    }

    function planGridCoordinateValues(minimum, maximum, spacing) {
        const epsilon = spacing * 0.000001;
        const output = [];
        let value = Math.ceil((minimum - epsilon) / spacing) * spacing;
        while (value <= maximum + epsilon
                && output.length < MAX_PLAN_GRID_LINES) {
            output.push(Number(value.toFixed(6)));
            value += spacing;
        }
        return output;
    }

    function isPlanMajorGridCoordinate(value, majorSpacing) {
        const quotient = value / majorSpacing;
        return Math.abs(quotient - Math.round(quotient)) < 0.000001;
    }

    function collectTopPlanBounds(layout, options, includeWorldBounds) {
        const geometry = collectTopPlanGeometry(layout, options);
        let minX = Infinity;
        let minZ = Infinity;
        let maxX = -Infinity;
        let maxZ = -Infinity;
        function include(value) {
            minX = Math.min(minX, value.x);
            minZ = Math.min(minZ, value.z);
            maxX = Math.max(maxX, value.x);
            maxZ = Math.max(maxZ, value.z);
        }
        const worldBounds = includeWorldBounds === false
            ? null : normalizedPlanWorldBounds(options);
        if (worldBounds) {
            include({ x: worldBounds.minX, z: worldBounds.minZ });
            include({ x: worldBounds.maxX, z: worldBounds.maxZ });
        }
        geometry.zones.forEach(function (zone) { zone.points.forEach(include); });
        geometry.floorMarkings.forEach(function (marking) {
            marking.points.forEach(include);
        });
        geometry.routes.forEach(function (route) {
            const half = route.corridorWidth / 2;
            route.points.forEach(function (value) {
                include({ x: value.x - half, z: value.z - half });
                include({ x: value.x + half, z: value.z + half });
            });
        });
        geometry.placements.forEach(function (placement) {
            placement.points.forEach(include);
        });
        if (!finite(minX)) {
            minX = -1;
            minZ = -1;
            maxX = 1;
            maxZ = 1;
        }
        if (maxX === minX) {
            minX -= 0.5;
            maxX += 0.5;
        }
        if (maxZ === minZ) {
            minZ -= 0.5;
            maxZ += 0.5;
        }
        return { minX: minX, minZ: minZ, maxX: maxX, maxZ: maxZ };
    }

    function appendFloorMarkingGraphic(document, layer, marking, projection, selected) {
        const center = projectTopPlanPoint(
            marking.transform && marking.transform.position || { x: 0, z: 0 },
            projection
        );
        const width = Math.max(2, marking.width * projection.scale);
        const depth = Math.max(2, marking.depth * projection.scale);
        const halfWidth = width / 2;
        const halfDepth = depth / 2;
        const group = svgElement(document, 'g');
        setAttributes(group, {
            class: 'ip-flw-floor-marking',
            tabindex: '0',
            role: 'button',
            'aria-label': marking.label + ', floor marking',
            'aria-selected': selected ? 'true' : 'false',
            'data-floor-marking-id': marking.markingId,
            'data-floor-marking-type': marking.markingType,
            'data-position-mode': marking.positionMode,
        });
        const tooltip = svgElement(document, 'title');
        tooltip.textContent = marking.label;
        group.appendChild(tooltip);

        const hitArea = svgElement(document, 'polygon');
        setAttributes(hitArea, {
            points: pointString(marking.points, projection),
            fill: marking.fillColor,
            'fill-opacity': Math.max(0.04, marking.opacity * 0.08),
            stroke: selected ? '#0878d1' : 'transparent',
            'stroke-width': selected ? '3' : '8',
            'stroke-opacity': selected ? '1' : '0',
            'vector-effect': 'non-scaling-stroke',
            'data-floor-marking-hit': marking.markingId,
        });
        group.appendChild(hitArea);

        const visual = svgElement(document, 'g');
        setAttributes(visual, {
            transform: 'rotate('
                + -finiteOr(marking.transform.rotationDegrees, 0) + ' '
                + center.x + ' ' + center.y + ')',
            'pointer-events': 'none',
            'aria-hidden': 'true',
            opacity: marking.opacity,
        });
        const rect = function (attributes) {
            const shape = svgElement(document, 'rect');
            setAttributes(shape, Object.assign({
                x: center.x - halfWidth,
                y: center.y - halfDepth,
                width: width,
                height: depth,
            }, attributes || {}));
            visual.appendChild(shape);
            return shape;
        };
        const text = function (value, fontSize) {
            appendSvgText(document, visual, {
                x: center.x,
                y: center.y,
                fill: marking.strokeColor,
                'font-size': fontSize,
                'font-weight': '800',
                'font-family': 'Segoe UI, Arial, sans-serif',
                'text-anchor': 'middle',
                'dominant-baseline': 'central',
            }, value);
        };

        if (marking.markingType === 'direction_arrow') {
            const arrow = svgElement(document, 'polygon');
            setAttributes(arrow, {
                points: [
                    [center.x, center.y - halfDepth],
                    [center.x + halfWidth, center.y - halfDepth * 0.12],
                    [center.x + halfWidth * 0.38, center.y - halfDepth * 0.12],
                    [center.x + halfWidth * 0.38, center.y + halfDepth],
                    [center.x - halfWidth * 0.38, center.y + halfDepth],
                    [center.x - halfWidth * 0.38, center.y - halfDepth * 0.12],
                    [center.x - halfWidth, center.y - halfDepth * 0.12],
                ].map(function (point) { return point.join(','); }).join(' '),
                fill: marking.fillColor,
                stroke: marking.strokeColor,
                'stroke-width': '1.5',
                'vector-effect': 'non-scaling-stroke',
            });
            visual.appendChild(arrow);
        } else if (marking.markingType === 'dashed_line') {
            const line = svgElement(document, 'line');
            setAttributes(line, {
                x1: center.x,
                y1: center.y - halfDepth,
                x2: center.x,
                y2: center.y + halfDepth,
                stroke: marking.fillColor,
                'stroke-width': width,
                'stroke-dasharray': Math.max(4, width * 1.4) + ' '
                    + Math.max(3, width),
                'stroke-linecap': 'butt',
            });
            visual.appendChild(line);
        } else if (marking.markingType === 'crosswalk') {
            rect({ fill: marking.strokeColor, 'fill-opacity': '0.08' });
            const count = Math.max(3, Math.min(12, Math.floor(depth / 12)));
            const stripeDepth = depth / (count * 1.8);
            for (let index = 0; index < count; index += 1) {
                const stripe = svgElement(document, 'rect');
                setAttributes(stripe, {
                    x: center.x - halfWidth,
                    y: center.y - halfDepth
                        + (index + 0.4) * depth / count,
                    width: width,
                    height: stripeDepth,
                    fill: marking.fillColor,
                });
                visual.appendChild(stripe);
            }
        } else if (marking.markingType === 'hazard_stripe') {
            const patternId = 'ip-flw-hazard-'
                + String(marking.markingId).replace(/[^A-Za-z0-9_-]/g, '-');
            const defs = svgElement(document, 'defs');
            const pattern = svgElement(document, 'pattern');
            setAttributes(pattern, {
                id: patternId,
                width: '14',
                height: '14',
                patternUnits: 'userSpaceOnUse',
                patternTransform: 'rotate(45)',
            });
            const background = svgElement(document, 'rect');
            setAttributes(background, {
                width: '14', height: '14', fill: marking.fillColor,
            });
            const stripe = svgElement(document, 'rect');
            setAttributes(stripe, {
                width: '7', height: '14', fill: marking.strokeColor,
            });
            pattern.appendChild(background);
            pattern.appendChild(stripe);
            defs.appendChild(pattern);
            visual.appendChild(defs);
            rect({ fill: 'url(#' + patternId + ')' });
        } else if (marking.markingType === 'keep_clear'
                || marking.markingType === 'parking_box') {
            rect({
                fill: marking.fillColor,
                'fill-opacity': marking.markingType === 'keep_clear'
                    ? '0.10' : '0.06',
                stroke: marking.fillColor,
                'stroke-width': Math.max(2, Math.min(8, width * 0.06)),
                'vector-effect': 'non-scaling-stroke',
            });
            text(marking.text || (marking.markingType === 'keep_clear'
                ? 'KEEP CLEAR' : 'PARKING'), Math.max(7, Math.min(18, width / 7)));
        } else if (marking.markingType === 'floor_text') {
            text(marking.text, Math.max(8, Math.min(28, depth * 0.42)));
        } else {
            rect({ fill: marking.fillColor });
        }
        group.appendChild(visual);
        if (selected) {
            const handles = svgElement(document, 'g');
            setAttributes(handles, {
                class: 'ip-flw-floor-marking-resize-handles',
                'aria-label': 'Resize floor marking',
            });
            marking.points.forEach(function (worldPoint, index) {
                const handleCenter = projectTopPlanPoint(worldPoint, projection);
                const handle = svgElement(document, 'rect');
                setAttributes(handle, {
                    class: 'ip-flw-floor-marking-resize-handle',
                    x: handleCenter.x - 4.5,
                    y: handleCenter.y - 4.5,
                    width: '9',
                    height: '9',
                    rx: '1',
                    role: 'button',
                    'aria-label': 'Resize floor marking from corner '
                        + String(index + 1),
                    'data-floor-marking-id': marking.markingId,
                    'data-floor-marking-resize-handle': String(index),
                    'data-resize-axis': index % 2 === 0 ? 'nwse' : 'nesw',
                    'vector-effect': 'non-scaling-stroke',
                });
                handles.appendChild(handle);
            });
            group.appendChild(handles);
        }
        layer.appendChild(group);
        return group;
    }

    function createTopPlanProjection(bounds, viewport, padding) {
        const width = Math.max(1, finiteOr(viewport && viewport.width, 1));
        const height = Math.max(1, finiteOr(viewport && viewport.height, 1));
        const requestedPadding = Math.max(
            0,
            finiteOr(padding, DEFAULT_VIEW_PADDING)
        );
        const safePadding = Math.min(
            requestedPadding,
            Math.max(0, Math.min(width, height) / 2 - 0.5)
        );
        const spanX = Math.max(1e-9, bounds.maxX - bounds.minX);
        const spanZ = Math.max(1e-9, bounds.maxZ - bounds.minZ);
        const availableWidth = Math.max(1, width - safePadding * 2);
        const availableHeight = Math.max(1, height - safePadding * 2);
        const scale = Math.min(availableWidth / spanX, availableHeight / spanZ);
        const renderedWidth = spanX * scale;
        const renderedHeight = spanZ * scale;
        return Object.freeze({
            width: width,
            height: height,
            padding: safePadding,
            scale: scale,
            offsetX: (width - renderedWidth) / 2,
            offsetY: (height - renderedHeight) / 2,
            minX: bounds.minX,
            minZ: bounds.minZ,
            maxX: bounds.maxX,
            maxZ: bounds.maxZ,
        });
    }

    function projectTopPlanPoint(value, projection) {
        return {
            x: projection.offsetX + (value.x - projection.minX) * projection.scale,
            y: projection.offsetY + (projection.maxZ - value.z) * projection.scale,
        };
    }

    function unprojectTopPlanPoint(value, projection) {
        return {
            x: projection.minX + (value.x - projection.offsetX) / projection.scale,
            z: projection.maxZ - (value.y - projection.offsetY) / projection.scale,
        };
    }

    function svgElement(documentRef, name) {
        return documentRef.createElementNS('http://www.w3.org/2000/svg', name);
    }

    function setAttributes(element, attributes) {
        Object.keys(attributes).forEach(function (key) {
            element.setAttribute(key, String(attributes[key]));
        });
        return element;
    }

    function pointString(points, projection) {
        return points.map(function (value) {
            const projected = projectTopPlanPoint(value, projection);
            return projected.x + ',' + projected.y;
        }).join(' ');
    }

    function activityDisplayOffsetPoints(points, requestedOffset) {
        const offset = Number(requestedOffset);
        if (!Array.isArray(points) || points.length < 2
                || !Number.isFinite(offset) || Math.abs(offset) <= 1e-9) {
            return points;
        }
        return points.map(function (point, index) {
            const previous = points[Math.max(0, index - 1)];
            const next = points[Math.min(points.length - 1, index + 1)];
            let dx = Number(next.x) - Number(previous.x);
            let dz = Number(next.z) - Number(previous.z);
            if (dx < -1e-9 || (Math.abs(dx) <= 1e-9 && dz < 0)) {
                dx *= -1;
                dz *= -1;
            }
            const length = Math.hypot(dx, dz);
            if (!Number.isFinite(length) || length <= 1e-9) return point;
            return Object.assign({}, point, {
                x: Number(point.x) - (dz / length) * offset,
                z: Number(point.z) + (dx / length) * offset,
            });
        });
    }

    function motionFootprintPoints(profile, pose) {
        const footprint = profile && profile.footprint;
        if (!Array.isArray(footprint) || footprint.length < 3
                || !pose || !finite(pose.x) || !finite(pose.z)) return [];
        const heading = finiteOr(pose.heading, 0);
        const cosine = Math.cos(heading);
        const sine = Math.sin(heading);
        return footprint.map(function (point) {
            const x = finiteOr(point && point.x, 0);
            const z = finiteOr(point && point.z, 0);
            return {
                x: pose.x + cosine * x - sine * z,
                z: pose.z + sine * x + cosine * z,
            };
        });
    }

    function motionPolygonPath(polygon, projection) {
        const rings = [polygon && polygon.exterior].concat(
            Array.isArray(polygon && polygon.holes) ? polygon.holes : []
        );
        return rings.filter(function (ring) {
            return Array.isArray(ring) && ring.length >= 3;
        }).map(function (ring) {
            const points = ring.map(function (point) {
                return projectTopPlanPoint(point, projection);
            });
            return 'M ' + points.map(function (point) {
                return point.x + ' ' + point.y;
            }).join(' L ') + ' Z';
        }).join(' ');
    }

    function removeChildren(element) {
        while (element.firstChild) element.removeChild(element.firstChild);
    }

    function targetLayoutObjectId(target, boundary) {
        let cursor = target;
        while (cursor && cursor !== boundary) {
            if (typeof cursor.getAttribute === 'function') {
                const placementId = cursor.getAttribute('data-placement-id');
                if (placementId) return placementId;
                const zoneId = cursor.getAttribute('data-zone-id');
                if (zoneId) return zoneId;
                const markingId = cursor.getAttribute('data-floor-marking-id');
                if (markingId) return markingId;
                const routeId = cursor.getAttribute('data-route-id');
                if (routeId) return routeId;
            }
            cursor = cursor.parentNode;
        }
        return null;
    }

    function clientPlanPoint(input, svg, projection) {
        if (!input || !svg || !projection) return null;
        const rect = typeof svg.getBoundingClientRect === 'function'
            ? svg.getBoundingClientRect() : null;
        const left = finiteOr(rect && rect.left, 0);
        const top = finiteOr(rect && rect.top, 0);
        const width = Math.max(1, finiteOr(rect && rect.width, projection.width));
        const height = Math.max(1, finiteOr(rect && rect.height, projection.height));
        const clientX = finiteOr(input.clientX, finiteOr(input.x, left));
        const clientY = finiteOr(input.clientY, finiteOr(input.y, top));
        return {
            x: ((clientX - left) / width) * projection.width,
            y: ((clientY - top) / height) * projection.height,
        };
    }

    function geometryBounds(points) {
        let minX = Infinity;
        let minZ = Infinity;
        let maxX = -Infinity;
        let maxZ = -Infinity;
        (points || []).forEach(function (value) {
            minX = Math.min(minX, value.x);
            minZ = Math.min(minZ, value.z);
            maxX = Math.max(maxX, value.x);
            maxZ = Math.max(maxZ, value.z);
        });
        return { minX: minX, minZ: minZ, maxX: maxX, maxZ: maxZ };
    }

    function boundsTouch(left, right) {
        return left.maxX >= right.minX
            && left.minX <= right.maxX
            && left.maxZ >= right.minZ
            && left.minZ <= right.maxZ;
    }

    function projectedPointBounds(points, projection) {
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        (points || []).forEach(function (value) {
            const projected = projectTopPlanPoint(value, projection);
            minX = Math.min(minX, projected.x);
            minY = Math.min(minY, projected.y);
            maxX = Math.max(maxX, projected.x);
            maxY = Math.max(maxY, projected.y);
        });
        return {
            minX: minX,
            minY: minY,
            maxX: maxX,
            maxY: maxY,
            width: Math.max(0, maxX - minX),
            height: Math.max(0, maxY - minY),
        };
    }

    function screenRectIntersectionArea(left, right) {
        const width = Math.max(
            0,
            Math.min(left.maxX, right.maxX) - Math.max(left.minX, right.minX)
        );
        const height = Math.max(
            0,
            Math.min(left.maxY, right.maxY) - Math.max(left.minY, right.minY)
        );
        return width * height;
    }

    function zoneLabelScreenRect(zone, projection, obstacles, occupied, size) {
        const bounds = projectedPointBounds(zone.points, projection);
        const width = size.width;
        const height = size.height;
        const viewportPadding = 5;
        const minimumX = viewportPadding;
        const maximumX = Math.max(
            minimumX,
            projection.width - width - viewportPadding
        );
        const minimumY = viewportPadding;
        const maximumY = Math.max(
            minimumY,
            projection.height - height - viewportPadding
        );
        const xPositions = [
            bounds.minX + 8,
            (bounds.minX + bounds.maxX - width) / 2,
            bounds.maxX - width - 8,
        ];
        const rows = [
            { y: bounds.minY - height + 1, edge: 'top-outside' },
            { y: bounds.maxY - 1, edge: 'bottom-outside' },
            { y: bounds.minY + 5, edge: 'top-inside' },
            { y: bounds.maxY - height - 5, edge: 'bottom-inside' },
        ];
        const candidates = [];
        rows.forEach(function (row, rowIndex) {
            xPositions.forEach(function (x, columnIndex) {
                const minX = Math.max(minimumX, Math.min(maximumX, x));
                const minY = Math.max(minimumY, Math.min(maximumY, row.y));
                const rect = {
                    minX: minX,
                    minY: minY,
                    maxX: minX + width,
                    maxY: minY + height,
                    width: width,
                    height: height,
                    edge: row.edge,
                };
                const equipmentOverlap = (obstacles || []).reduce(
                    function (total, obstacle) {
                        return total + screenRectIntersectionArea(rect, obstacle);
                    },
                    0
                );
                const labelOverlap = (occupied || []).reduce(
                    function (total, labelRect) {
                        return total + screenRectIntersectionArea(rect, labelRect);
                    },
                    0
                );
                const outsideClampPenalty = rowIndex < 2
                    && Math.abs(minY - row.y) > 0.5 ? 1 : 0;
                candidates.push({
                    rect: rect,
                    equipmentOverlapArea: equipmentOverlap,
                    labelOverlapArea: labelOverlap,
                    score: [
                        labelOverlap > 0 ? 1 : 0,
                        labelOverlap,
                        equipmentOverlap > 0 ? 1 : 0,
                        equipmentOverlap,
                        outsideClampPenalty,
                        rowIndex >= 2 ? 1 : 0,
                        rowIndex,
                        columnIndex,
                    ],
                });
            });
        });
        candidates.sort(function (left, right) {
            for (let index = 0; index < left.score.length; index += 1) {
                if (left.score[index] !== right.score[index]) {
                    return left.score[index] - right.score[index];
                }
            }
            return 0;
        });
        const selected = candidates[0];
        return Object.assign({}, selected.rect, {
            equipmentOverlapArea: selected.equipmentOverlapArea,
            labelOverlapArea: selected.labelOverlapArea,
        });
    }

    function categorySymbol(value) {
        const words = String(value || 'Equipment').trim().split(/\s+/)
            .filter(Boolean);
        if (!words.length) return 'E';
        if (words.length === 1) return words[0].slice(0, 1).toUpperCase();
        return words.slice(0, 2).map(function (word) {
            return word.slice(0, 1).toUpperCase();
        }).join('');
    }

    function balancedLabelLines(value) {
        const words = String(value || '').trim().split(/\s+/).filter(Boolean);
        if (!words.length) return ['Equipment'];
        if (words.length === 1) return [words[0]];
        let bestIndex = 1;
        let bestDifference = Infinity;
        for (let index = 1; index < words.length; index += 1) {
            const left = words.slice(0, index).join(' ');
            const right = words.slice(index).join(' ');
            const difference = Math.abs(left.length - right.length);
            if (difference < bestDifference) {
                bestDifference = difference;
                bestIndex = index;
            }
        }
        return [
            words.slice(0, bestIndex).join(' '),
            words.slice(bestIndex).join(' '),
        ];
    }

    function metricDimension(value) {
        const rounded = Math.round(finiteOr(value, 0) * 10) / 10;
        return String(rounded).replace(/\.0$/, '');
    }

    function normalizedPlanDisplayUnit(options) {
        return options && options.displayUnit === 'ft' ? 'ft' : 'm';
    }

    function planDisplayDistance(value, options) {
        const meters = finiteOr(value, 0);
        return normalizedPlanDisplayUnit(options) === 'ft'
            ? meters * METERS_TO_FEET
            : meters;
    }

    function planDisplayDimension(value, options) {
        return metricDimension(planDisplayDistance(value, options));
    }

    function planDisplayUnitWord(options) {
        return normalizedPlanDisplayUnit(options) === 'ft' ? 'feet' : 'metres';
    }

    function appendSvgText(documentRef, parent, attributes, value) {
        const text = svgElement(documentRef, 'text');
        setAttributes(text, attributes);
        text.textContent = String(value || '');
        parent.appendChild(text);
        return text;
    }

    function appendPlanPath(documentRef, parent, className, segments) {
        if (!segments.length) return null;
        const path = svgElement(documentRef, 'path');
        setAttributes(path, {
            class: className,
            d: segments.join(' '),
            fill: 'none',
            'pointer-events': 'none',
            'aria-hidden': 'true',
        });
        parent.appendChild(path);
        return path;
    }

    function appendPlanEnvironment(documentRef, parent, projection, options) {
        const bounds = normalizedPlanWorldBounds(options);
        const grid = normalizedPlanGrid(options, bounds);
        if (!bounds || !grid) return null;
        const topLeft = projectTopPlanPoint({
            x: bounds.minX,
            z: bounds.maxZ,
        }, projection);
        const bottomRight = projectTopPlanPoint({
            x: bounds.maxX,
            z: bounds.minZ,
        }, projection);
        const width = Math.max(0, bottomRight.x - topLeft.x);
        const height = Math.max(0, bottomRight.y - topLeft.y);
        const floor = svgElement(documentRef, 'rect');
        setAttributes(floor, {
            class: 'ip-flw-plan-floor',
            x: topLeft.x,
            y: topLeft.y,
            width: width,
            height: height,
            'pointer-events': 'none',
            'aria-hidden': 'true',
            'data-facility-floor': 'true',
        });
        parent.appendChild(floor);

        const minorSegments = [];
        const majorSegments = [];
        const xValues = planGridCoordinateValues(
            bounds.minX,
            bounds.maxX,
            grid.spacing
        );
        const zValues = planGridCoordinateValues(
            bounds.minZ,
            bounds.maxZ,
            grid.spacing
        );
        xValues.forEach(function (x) {
            const start = projectTopPlanPoint({ x: x, z: bounds.minZ }, projection);
            const end = projectTopPlanPoint({ x: x, z: bounds.maxZ }, projection);
            const target = isPlanMajorGridCoordinate(x, grid.majorSpacing)
                ? majorSegments : minorSegments;
            target.push('M ' + start.x + ' ' + start.y
                + ' L ' + end.x + ' ' + end.y);
        });
        zValues.forEach(function (z) {
            const start = projectTopPlanPoint({ x: bounds.minX, z: z }, projection);
            const end = projectTopPlanPoint({ x: bounds.maxX, z: z }, projection);
            const target = isPlanMajorGridCoordinate(z, grid.majorSpacing)
                ? majorSegments : minorSegments;
            target.push('M ' + start.x + ' ' + start.y
                + ' L ' + end.x + ' ' + end.y);
        });
        const gridVisible = !options || options.showGrid !== false;
        if (gridVisible) {
            appendPlanPath(
                documentRef,
                parent,
                'ip-flw-plan-grid ip-flw-plan-grid-minor',
                minorSegments
            );
            appendPlanPath(
                documentRef,
                parent,
                'ip-flw-plan-grid ip-flw-plan-grid-major',
                majorSegments
            );
        }

        const center = {
            x: (bounds.minX + bounds.maxX) / 2,
            z: (bounds.minZ + bounds.maxZ) / 2,
        };
        const origin = options && options.originMode === 'center'
            ? center : { x: bounds.minX, z: bounds.minZ };
        const axisLength = Math.min(
            bounds.maxX - bounds.minX,
            bounds.maxZ - bounds.minZ,
            grid.majorSpacing * 2
        );
        const originPoint = projectTopPlanPoint(origin, projection);
        const xEnd = projectTopPlanPoint({
            x: Math.min(bounds.maxX, origin.x + axisLength),
            z: origin.z,
        }, projection);
        const zEnd = projectTopPlanPoint({
            x: origin.x,
            z: Math.min(bounds.maxZ, origin.z + axisLength),
        }, projection);
        appendPlanPath(documentRef, parent, 'ip-flw-plan-axis ip-flw-plan-axis-x', [
            'M ' + originPoint.x + ' ' + originPoint.y
                + ' L ' + xEnd.x + ' ' + xEnd.y,
        ]);
        appendPlanPath(documentRef, parent, 'ip-flw-plan-axis ip-flw-plan-axis-z', [
            'M ' + originPoint.x + ' ' + originPoint.y
                + ' L ' + zEnd.x + ' ' + zEnd.y,
        ]);

        const originMarker = svgElement(documentRef, 'circle');
        setAttributes(originMarker, {
            class: 'ip-flw-plan-origin',
            cx: originPoint.x,
            cy: originPoint.y,
            r: '3.5',
            'pointer-events': 'none',
            'aria-hidden': 'true',
            'data-facility-origin': 'true',
        });
        parent.appendChild(originMarker);
        const centerPoint = projectTopPlanPoint(center, projection);
        const centerSize = 5;
        appendPlanPath(documentRef, parent, 'ip-flw-plan-center', [
            'M ' + (centerPoint.x - centerSize) + ' ' + centerPoint.y
                + ' L ' + (centerPoint.x + centerSize) + ' ' + centerPoint.y,
            'M ' + centerPoint.x + ' ' + (centerPoint.y - centerSize)
                + ' L ' + centerPoint.x + ' ' + (centerPoint.y + centerSize),
        ]);

        const labelClass = 'ip-flw-plan-coordinate-label';
        if (gridVisible) {
            xValues.filter(function (value) {
                return isPlanMajorGridCoordinate(value, grid.majorSpacing);
            }).forEach(function (x) {
                const at = projectTopPlanPoint({ x: x, z: bounds.minZ }, projection);
                appendSvgText(documentRef, parent, {
                    class: labelClass,
                    x: at.x,
                    y: at.y + 15,
                    'text-anchor': 'middle',
                    'pointer-events': 'none',
                    'aria-hidden': 'true',
                }, planDisplayDimension(x, options));
            });
            zValues.filter(function (value) {
                return isPlanMajorGridCoordinate(value, grid.majorSpacing);
            }).forEach(function (z) {
                const at = projectTopPlanPoint({ x: bounds.minX, z: z }, projection);
                appendSvgText(documentRef, parent, {
                    class: labelClass,
                    x: at.x - 7,
                    y: at.y + 3,
                    'text-anchor': 'end',
                    'pointer-events': 'none',
                    'aria-hidden': 'true',
                }, planDisplayDimension(z, options));
            });
        }
        appendSvgText(documentRef, parent, {
            class: 'ip-flw-plan-axis-label ip-flw-plan-axis-label-x',
            x: xEnd.x + 5,
            y: xEnd.y + 3,
            'text-anchor': 'start',
            'pointer-events': 'none',
            'aria-hidden': 'true',
        }, '+X');
        appendSvgText(documentRef, parent, {
            class: 'ip-flw-plan-axis-label ip-flw-plan-axis-label-z',
            x: zEnd.x,
            y: zEnd.y - 6,
            'text-anchor': 'middle',
            'pointer-events': 'none',
            'aria-hidden': 'true',
        }, '+Z');
        appendSvgText(documentRef, parent, {
            class: 'ip-flw-plan-grid-caption',
            x: topLeft.x + 7,
            y: topLeft.y + 14,
            'text-anchor': 'start',
            'pointer-events': 'auto',
            role: 'button',
            tabindex: '0',
            'data-plan-settings-trigger': 'dimensions',
            'aria-label': 'Edit facility dimensions and grid spacing',
        }, planDisplayDimension(bounds.maxX - bounds.minX, options) + ' x '
            + planDisplayDimension(bounds.maxZ - bounds.minZ, options) + ' '
            + normalizedPlanDisplayUnit(options) + (gridVisible
                ? ' | Grid ' + planDisplayDimension(grid.spacing, options)
                    + ' ' + normalizedPlanDisplayUnit(options)
                : ' | Grid hidden'));
        return {
            bounds: Object.assign({}, bounds),
            spacing: grid.spacing,
            majorSpacing: grid.majorSpacing,
            minorLineCount: gridVisible ? minorSegments.length : 0,
            majorLineCount: gridVisible ? majorSegments.length : 0,
            origin: origin,
            center: center,
        };
    }

    function planCardDetailLevel(width, height, scale) {
        const currentWidth = Math.max(0, width * scale);
        const currentHeight = Math.max(0, height * scale);
        const shortest = Math.min(currentWidth, currentHeight);
        const longest = Math.max(currentWidth, currentHeight);
        if (shortest >= 42 && longest >= 58) return 'full';
        if (shortest >= 14 && longest >= 18) return 'compact';
        return 'body';
    }

    function applyPlanCardContentVisibility(card, detailLevel) {
        if (!card || !card.children) return;
        Array.prototype.forEach.call(card.children, function (child) {
            if (!child || typeof child.getAttribute !== 'function') return;
            const className = child.getAttribute('class');
            let visible = null;
            if (className === 'ip-flw-plan-card-compact') {
                visible = detailLevel === 'compact';
            } else if (className === 'ip-flw-plan-card-detail') {
                visible = detailLevel === 'full';
            }
            if (visible === null) return;
            child.setAttribute('display', visible ? 'inline' : 'none');
            child.setAttribute(
                'style',
                'display:' + (visible ? 'inline' : 'none')
            );
        });
    }

    function updatePlanCardDetailLevels(svg, scale) {
        if (!svg || !svg.children) return;
        let placementLayer = null;
        Array.prototype.forEach.call(svg.children, function (layer) {
            if (layer && typeof layer.getAttribute === 'function'
                    && layer.getAttribute('data-layer') === 'placements') {
                placementLayer = layer;
            }
        });
        if (!placementLayer || !placementLayer.children) return;
        Array.prototype.forEach.call(placementLayer.children, function (card) {
            if (!card || typeof card.getAttribute !== 'function') return;
            const width = Number(card.getAttribute('data-card-width'));
            const height = Number(card.getAttribute('data-card-height'));
            if (!Number.isFinite(width) || !Number.isFinite(height)) return;
            const detailLevel = planCardDetailLevel(width, height, scale);
            card.setAttribute('data-card-detail-level', detailLevel);
            applyPlanCardContentVisibility(card, detailLevel);
        });
    }

    function proposalReviewBounds(
        layout,
        proposalPreview,
        options,
        includeWorldBounds
    ) {
        const bounds = collectTopPlanBounds(
            layout,
            options,
            includeWorldBounds
        );
        const beforePlacements = proposalPreview
            && Array.isArray(proposalPreview.beforePlacements)
            ? proposalPreview.beforePlacements : [];
        beforePlacements.forEach(function (placement) {
            placementFootprint(placement, options).forEach(function (value) {
                bounds.minX = Math.min(bounds.minX, value.x);
                bounds.minZ = Math.min(bounds.minZ, value.z);
                bounds.maxX = Math.max(bounds.maxX, value.x);
                bounds.maxZ = Math.max(bounds.maxZ, value.z);
            });
        });
        return bounds;
    }

    function normalizeProposalPreview(value) {
        if (!value || value.active !== true) return null;
        function identifiers(name) {
            return Array.from(new Set(
                (Array.isArray(value[name]) ? value[name] : []).filter(
                    function (identifier) {
                        return typeof identifier === 'string' && identifier;
                    }
                )
            )).sort();
        }
        function placements(name) {
            return (Array.isArray(value[name]) ? value[name] : []).filter(
                function (placement) {
                    return placement
                        && typeof placement.placementId === 'string'
                        && placement.placementId;
                }
            ).map(clone).sort(function (left, right) {
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
                ? value.beforeRoutes : []).map(clone),
            proposedRoutes: (Array.isArray(value.proposedRoutes)
                ? value.proposedRoutes : []).map(clone),
        };
    }

    function TopPlanAdapter(host, options) {
        if (!(this instanceof TopPlanAdapter)) {
            return new TopPlanAdapter(host, options);
        }
        if (!host || typeof host.appendChild !== 'function') {
            throw new TypeError('top-plan host must be a DOM element');
        }
        this.options = options || {};
        this.host = host;
        this.document = this.options.document || host.ownerDocument
            || (root && root.document);
        if (!this.document || typeof this.document.createElementNS !== 'function') {
            throw new Error('top-plan adapter requires SVG DOM support');
        }
        this.id = String(this.options.id || 'top-plan');
        this.type = 'top-plan';
        this.layout = null;
        this.geometry = null;
        this.environmentDiagnostics = null;
        this.projection = null;
        this.renderProjection = null;
        this.ghostPlacement = null;
        this.proposalPreview = null;
        this.transientPlacementMove = null;
        this.transientPlacementDuplicate = null;
        this.transientZonePreview = null;
        this.transientFloorMarkingPreview = null;
        this.transientAislePreview = null;
        this.transientPatternPreview = null;
        this.navigationAuthoringPreview = null;
        this.navigationPathsVisible = true;
        this.navigationMarker = null;
        this.motionPresentation = null;
        this.motionSnapshot = null;
        this.motionMarker = null;
        this.activityPresentation = null;
        this.activitySnapshot = null;
        this.activityMarkers = new Map();
        this.activityPathsVisible = true;
        this.activityPathTypesVisible = {
            vehicle: true,
            operator: true,
            mobile_equipment: true,
        };
        this.selection = null;
        this.selections = new Set();
        this.selectionHandler = null;
        this.viewportChangeHandler = null;
        this.renderCount = 0;
        this.observerCount = 0;
        this.semanticBaseScale = null;
        this.zoneLabelDiagnostics = null;
        this.layerVisibility = normalizeLayerVisibility(
            this.options.layerVisibility
        );
        this.disposed = false;
        this.suspended = false;

        this.svg = svgElement(this.document, 'svg');
        setAttributes(this.svg, {
            'aria-label': this.options.ariaLabel || 'Facility top plan',
            role: 'img',
            width: '100%',
            height: '100%',
            preserveAspectRatio: 'none',
            'data-facility-layout-view': this.id,
        });
        this._handlePick = this._handlePick.bind(this);
        this._handleKeyPick = this._handleKeyPick.bind(this);
        this.svg.addEventListener('click', this._handlePick);
        this.svg.addEventListener('keydown', this._handleKeyPick);
        this.host.appendChild(this.svg);

        this.ResizeObserverCtor = this.options.ResizeObserver
            || (root && root.ResizeObserver);
        this.resizeObserver = null;
        this.resizeObserverActive = false;
        this._observeHost();
    }

    TopPlanAdapter.prototype._observeHost = function () {
        if (this.disposed || this.suspended || this.resizeObserverActive
                || typeof this.ResizeObserverCtor !== 'function') return;
        if (!this.resizeObserver) {
            this.resizeObserver = new this.ResizeObserverCtor(function () {
                if (!this.disposed) this.fit();
            }.bind(this));
        }
        this.resizeObserver.observe(this.host);
        this.resizeObserverActive = true;
        this.observerCount = 1;
    };

    TopPlanAdapter.prototype._measure = function () {
        if (typeof this.options.getSize === 'function') {
            const size = this.options.getSize(this.host) || {};
            return {
                width: Math.max(1, finiteOr(size.width, 1)),
                height: Math.max(1, finiteOr(size.height, 1)),
            };
        }
        return {
            width: Math.max(
                1,
                finiteOr(this.host.clientWidth, finiteOr(this.options.width, 1))
            ),
            height: Math.max(
                1,
                finiteOr(this.host.clientHeight, finiteOr(this.options.height, 1))
            ),
        };
    };

    TopPlanAdapter.prototype._appendMotionOverlay = function () {
        this.motionMarker = null;
        const packageValue = this.motionPresentation
            && this.motionPresentation.package;
        const profile = this.motionPresentation
            && this.motionPresentation.vehicleProfile;
        const movement = packageValue && packageValue.movement;
        if (!movement || movement.outcome === 'unroutable'
                || !this.projection) return false;
        const layer = svgElement(this.document, 'g');
        setAttributes(layer, {
            'data-layer': 'motion-playback',
            'data-motion-package-id': packageValue.packageId || '',
            'data-motion-outcome': movement.outcome,
            'pointer-events': 'none',
            'aria-hidden': 'true',
        });
        const geometry = movement.sweptEnvelope
            && movement.sweptEnvelope.geometry;
        (geometry && Array.isArray(geometry.polygons)
            ? geometry.polygons : []).forEach(function (polygon) {
            const pathValue = motionPolygonPath(polygon, this.projection);
            if (!pathValue) return;
            const path = svgElement(this.document, 'path');
            setAttributes(path, {
                d: pathValue,
                fill: movement.outcome === 'envelope_refused'
                    ? '#d14343' : '#16a085',
                'fill-opacity': movement.outcome === 'envelope_refused'
                    ? '0.26' : '0.18',
                stroke: movement.outcome === 'envelope_refused'
                    ? '#b4232c' : '#087f71',
                'stroke-width': '1.5',
                'stroke-opacity': '0.9',
                'fill-rule': 'evenodd',
                'vector-effect': 'non-scaling-stroke',
                'data-motion-ribbon': 'true',
            });
            layer.appendChild(path);
        }, this);
        const marker = svgElement(this.document, 'polygon');
        setAttributes(marker, {
            fill: movement.outcome === 'envelope_refused'
                ? '#e04b4b' : '#00a6d6',
            'fill-opacity': '0.96',
            stroke: '#ffffff',
            'stroke-width': '2',
            'vector-effect': 'non-scaling-stroke',
            'data-motion-vehicle': 'true',
            'data-vehicle-profile-id': movement.vehicleProfileRef
                && movement.vehicleProfileRef.vehicleProfileId || '',
        });
        layer.appendChild(marker);
        this.motionMarker = marker;
        this.svg.appendChild(layer);
        this._updateMotionMarker();
        return true;
    };

    TopPlanAdapter.prototype._appendNavigationOverlay = function () {
        this.navigationMarker = null;
        if (!this.projection) return false;
        const pathsVisible = this.navigationPathsVisible !== false;
        const navigation = this.layout && this.layout.extensions
            && this.layout.extensions.facilityNavigation;
        const durable = navigation
            && Array.isArray(navigation.manualPathConstraints)
            ? navigation.manualPathConstraints : [];
        const preview = this.navigationAuthoringPreview;
        if (!durable.length && (!preview || !Array.isArray(preview.points))) {
            return false;
        }
        const layer = svgElement(this.document, 'g');
        setAttributes(layer, {
            'data-layer': 'facility-navigation',
            'data-navigation-paths-visible': pathsVisible ? 'true' : 'false',
        });
        if (pathsVisible) {
        durable.forEach(function (constraint) {
            if (!constraint || !Array.isArray(constraint.authoredPolyline)
                    || constraint.authoredPolyline.length < 2) return;
            const path = svgElement(this.document, 'polyline');
            const status = constraint.reviewStatus === 'confirmed'
                ? 'validated' : constraint.reviewStatus === 'rejected'
                    ? 'invalid' : 'pending';
            setAttributes(path, {
                points: pointString(
                    constraint.authoredPolyline,
                    this.projection
                ),
                fill: 'none',
                stroke: status === 'validated' ? '#0f8f62'
                    : status === 'invalid' ? '#c9363e' : '#d97706',
                'stroke-width': status === 'validated' ? '3.5' : '3',
                'stroke-opacity': '0.92',
                'stroke-dasharray': status === 'pending' ? '9 5'
                    : status === 'invalid' ? '4 4' : 'none',
                'stroke-linejoin': 'round',
                'stroke-linecap': 'round',
                'vector-effect': 'non-scaling-stroke',
                'pointer-events': 'none',
                'data-navigation-constraint-id':
                    constraint.manualPathConstraintId || '',
                'data-navigation-status': status,
                'data-navigation-authority':
                    constraint.positionAuthority || '',
            });
            layer.appendChild(path);
        }, this);
        }
        if (preview && Array.isArray(preview.points)
                && preview.points.length >= 2) {
            const status = preview.validationStatus || 'pending';
            if (pathsVisible) {
            const path = svgElement(this.document, 'polyline');
            setAttributes(path, {
                points: pointString(preview.points, this.projection),
                fill: 'none',
                stroke: status === 'validated' ? '#0f8f62'
                    : status === 'invalid' ? '#c9363e' : '#0878d1',
                'stroke-width': '4',
                'stroke-opacity': '0.98',
                'stroke-dasharray': status === 'pending' ? '10 5'
                    : status === 'invalid' ? '4 4' : 'none',
                'stroke-linejoin': 'round',
                'stroke-linecap': 'round',
                'vector-effect': 'non-scaling-stroke',
                'data-navigation-authoring-path': 'true',
                'data-navigation-status': status,
                'data-navigation-authority': 'ui_authored',
            });
            layer.appendChild(path);
            const invalidSegments = preview.validation
                && Array.isArray(preview.validation.invalidSegmentIndexes)
                ? new Set(preview.validation.invalidSegmentIndexes) : new Set();
            invalidSegments.forEach(function (segmentIndex) {
                const left = preview.points[segmentIndex];
                const right = preview.points[segmentIndex + 1];
                if (!left || !right) return;
                const segment = svgElement(this.document, 'polyline');
                setAttributes(segment, {
                    points: pointString([left, right], this.projection),
                    fill: 'none',
                    stroke: '#c9363e',
                    'stroke-width': '6',
                    'stroke-opacity': '1',
                    'stroke-dasharray': '4 3',
                    'stroke-linejoin': 'round',
                    'stroke-linecap': 'round',
                    'vector-effect': 'non-scaling-stroke',
                    'pointer-events': 'none',
                    'data-navigation-invalid-segment': String(segmentIndex),
                });
                layer.appendChild(segment);
            }, this);
            preview.points.forEach(function (value, index) {
                const center = projectTopPlanPoint(value, this.projection);
                const handle = svgElement(this.document, 'circle');
                setAttributes(handle, {
                    cx: center.x,
                    cy: center.y,
                    r: index === preview.selectedPointIndex ? '7' : '5',
                    fill: index === preview.selectedPointIndex
                        ? '#ffffff' : '#0878d1',
                    stroke: status === 'invalid' ? '#c9363e' : '#075b9e',
                    'stroke-width': '2',
                    'vector-effect': 'non-scaling-stroke',
                    tabindex: '0',
                    role: 'button',
                    'aria-label': 'Motion path waypoint ' + (index + 1),
                    'data-navigation-waypoint-index': String(index),
                    'data-navigation-waypoint-authority': 'ui_authored',
                });
                layer.appendChild(handle);
            }, this);
            }
            if (preview.pose && Number.isFinite(Number(preview.pose.x))
                    && Number.isFinite(Number(preview.pose.z))) {
                const placement = this.layout
                    && (this.layout.placements || []).find(function (item) {
                        return item.placementId === preview.actorPlacementId;
                    });
                const width = Math.max(0.3, finiteOr(
                    placement && placement.width,
                    preview.actorClass === 'vehicle' ? 1.8 : 0.6
                ));
                const depth = Math.max(0.3, finiteOr(
                    placement && placement.depth,
                    preview.actorClass === 'vehicle' ? 3.2 : 0.6
                ));
                const halfWidth = width / 2;
                const halfDepth = depth / 2;
                const cosine = Math.cos(finiteOr(preview.pose.heading, 0));
                const sine = Math.sin(finiteOr(preview.pose.heading, 0));
                const points = [
                    { x: halfDepth, z: -halfWidth },
                    { x: halfDepth, z: halfWidth },
                    { x: -halfDepth, z: halfWidth },
                    { x: -halfDepth, z: -halfWidth },
                ].map(function (local) {
                    return {
                        x: preview.pose.x
                            + local.x * cosine - local.z * sine,
                        z: preview.pose.z
                            + local.x * sine + local.z * cosine,
                    };
                });
                const marker = svgElement(this.document, 'polygon');
                setAttributes(marker, {
                    points: pointString(points, this.projection),
                    fill: preview.actorClass === 'vehicle'
                        ? '#d97706' : '#2563eb',
                    'fill-opacity': '0.96',
                    stroke: '#ffffff',
                    'stroke-width': '2',
                    'vector-effect': 'non-scaling-stroke',
                    'pointer-events': 'none',
                    'data-navigation-preview-actor':
                        preview.actorPlacementId || '',
                    'data-navigation-preview-time': finiteOr(
                        preview.pose.normalizedTime,
                        0
                    ),
                    'data-navigation-preview-heading': finiteOr(
                        preview.pose.heading,
                        0
                    ),
                });
                layer.appendChild(marker);
                this.navigationMarker = marker;
                const source = this.svg.querySelector
                    ? this.svg.querySelector(
                        '[data-placement-id="'
                            + preview.actorPlacementId + '"]'
                    ) : null;
                if (source) {
                    source.setAttribute('display', 'none');
                    source.setAttribute(
                        'data-navigation-source-suppressed',
                        'true'
                    );
                }
            }
        }
        this.svg.appendChild(layer);
        return true;
    };

    TopPlanAdapter.prototype.setNavigationAuthoringPreview = function (value) {
        if (this.disposed) return false;
        this.navigationAuthoringPreview = value ? clone(value) : null;
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.setNavigationPathsVisible = function (requested) {
        if (this.disposed) return false;
        this.navigationPathsVisible = requested !== false;
        this._render();
        return this.navigationPathsVisible;
    };

    TopPlanAdapter.prototype._updateMotionMarker = function () {
        if (!this.motionMarker || !this.projection
                || !this.motionPresentation || !this.motionSnapshot
                || !this.motionSnapshot.pose) return false;
        const points = motionFootprintPoints(
            this.motionPresentation.vehicleProfile,
            this.motionSnapshot.pose
        );
        if (points.length < 3) return false;
        setAttributes(this.motionMarker, {
            points: pointString(points, this.projection),
            'data-motion-distance-meters': finiteOr(
                this.motionSnapshot.distanceMeters,
                this.motionSnapshot.pose.distanceMeters || 0
            ),
            'data-motion-heading-radians': finiteOr(
                this.motionSnapshot.pose.heading,
                0
            ),
        });
        return true;
    };

    TopPlanAdapter.prototype.setMotionPresentation = function (value) {
        if (this.disposed) return false;
        if (!value) {
            this.motionPresentation = null;
            this.motionSnapshot = null;
            this.motionMarker = null;
            this._render();
            return true;
        }
        this.activityPresentation = null;
        this.activitySnapshot = null;
        this.activityMarkers.clear();
        if (!value.package || !value.package.movement
                || !value.package.packageId) {
            throw new TypeError('Facility motion presentation is incomplete.');
        }
        this.motionPresentation = clone(value);
        this.motionSnapshot = null;
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.updateMotionSnapshot = function (value) {
        if (this.disposed || !this.motionPresentation) return false;
        const snapshot = value && typeof value === 'object' ? clone(value) : null;
        if (!snapshot || snapshot.packageId
                !== this.motionPresentation.package.packageId) return false;
        this.motionSnapshot = snapshot;
        if (!this._updateMotionMarker()) this._render();
        return true;
    };

    TopPlanAdapter.prototype.clearMotionPresentation = function () {
        return this.setMotionPresentation(null);
    };

    TopPlanAdapter.prototype._appendActivityOverlay = function () {
        this.activityMarkers.clear();
        const scenario = this.activityPresentation
            && this.activityPresentation.scenario;
        const payloads = this.activityPresentation
            && this.activityPresentation.actorPayloads;
        if (!scenario || !Array.isArray(scenario.actors)
                || !payloads || !this.projection) return false;
        const layer = svgElement(this.document, 'g');
        setAttributes(layer, {
            'data-layer': 'activity-playback',
            'data-activity-scenario-id': scenario.scenarioId || '',
            'pointer-events': 'none',
            'aria-hidden': 'true',
        });
        const leanMotion = scenario.leanMotion;
        if (leanMotion && this.activityPathsVisible !== false) {
            (leanMotion.operatorPaths || []).forEach(function (path) {
                const line = svgElement(this.document, 'polyline');
                setAttributes(line, {
                    points: pointString(path.centerline, this.projection),
                    fill: 'none',
                    stroke: '#2563eb',
                    'stroke-width': '3.25',
                    'stroke-opacity': '0.96',
                    'stroke-linejoin': 'round',
                    'stroke-linecap': 'round',
                    'vector-effect': 'non-scaling-stroke',
                    'data-lean-motion-path-id': path.pathId,
                    'data-lean-motion-kind': 'operator_path',
                });
                layer.appendChild(line);
            }, this);
            (leanMotion.pedestrianConnections || []).forEach(function (connection) {
                const line = svgElement(this.document, 'polyline');
                setAttributes(line, {
                    points: pointString(connection.centerline, this.projection),
                    fill: 'none',
                    stroke: '#0891b2',
                    'stroke-width': '3',
                    'stroke-opacity': '0.96',
                    'stroke-dasharray': '8 5',
                    'stroke-linejoin': 'round',
                    'stroke-linecap': 'round',
                    'vector-effect': 'non-scaling-stroke',
                    'data-lean-motion-connection-id': connection.connectionId,
                    'data-lean-motion-kind': 'pedestrian_connection',
                });
                layer.appendChild(line);
            }, this);
            (leanMotion.assistanceGates || []).forEach(function (gate) {
                const center = projectTopPlanPoint(gate.position, this.projection);
                const edge = projectTopPlanPoint({
                    x: Number(gate.position.x) + 0.5,
                    z: Number(gate.position.z),
                }, this.projection);
                const marker = svgElement(this.document, 'circle');
                setAttributes(marker, {
                    cx: center.x,
                    cy: center.y,
                    r: Math.max(3, Math.abs(edge.x - center.x)),
                    fill: '#ecfeff',
                    'fill-opacity': '0.9',
                    stroke: '#06b6d4',
                    'stroke-width': '2.5',
                    'vector-effect': 'non-scaling-stroke',
                    'data-lean-motion-gate-id': gate.gateId,
                    'data-lean-motion-kind': 'assistance_gate',
                });
                layer.appendChild(marker);
            }, this);
            (leanMotion.materialHandoffs || []).forEach(function (handoff) {
                const line = svgElement(this.document, 'polyline');
                setAttributes(line, {
                    points: pointString(handoff.centerline, this.projection),
                    fill: 'none',
                    stroke: '#059669',
                    'stroke-width': '3',
                    'stroke-opacity': '0.94',
                    'stroke-linejoin': 'round',
                    'stroke-linecap': 'round',
                    'vector-effect': 'non-scaling-stroke',
                    'data-lean-motion-handoff-id': handoff.handoffId,
                    'data-lean-motion-kind': 'material_handoff',
                });
                layer.appendChild(line);
            }, this);
            (leanMotion.fifoPoints || []).forEach(function (point) {
                const radius = 0.42;
                const position = point.position;
                const diamond = svgElement(this.document, 'polygon');
                setAttributes(diamond, {
                    points: pointString([
                        { x: position.x, z: position.z - radius },
                        { x: position.x + radius, z: position.z },
                        { x: position.x, z: position.z + radius },
                        { x: position.x - radius, z: position.z },
                    ], this.projection),
                    fill: '#f59e0b',
                    stroke: '#92400e',
                    'stroke-width': '1.5',
                    'vector-effect': 'non-scaling-stroke',
                    'data-lean-motion-fifo-id': point.pointId,
                    'data-lean-motion-kind': 'fifo_point',
                });
                layer.appendChild(diamond);
            }, this);
        }
        const candidatePresentation = this.activityPresentation
            && this.activityPresentation.candidatePresentation;
        if (candidatePresentation && this.activityPathsVisible !== false) {
            const endpointKeys = new Set();
            (candidatePresentation.handoffs || []).forEach(function (handoff) {
                const line = svgElement(this.document, 'polyline');
                setAttributes(line, {
                    points: pointString(handoff.centerline, this.projection),
                    fill: 'none',
                    stroke: '#059669',
                    'stroke-width': '3',
                    'stroke-opacity': '0.9',
                    'stroke-dasharray': '9 6',
                    'stroke-linejoin': 'round',
                    'stroke-linecap': 'round',
                    'vector-effect': 'non-scaling-stroke',
                    'data-navigation-candidate-handoff-id': handoff.candidateId,
                    'data-navigation-candidate-review-status': handoff.reviewStatus,
                });
                layer.appendChild(line);
                [
                    handoff.centerline[0],
                    handoff.centerline[handoff.centerline.length - 1],
                ].forEach(function (position) {
                    const key = Number(position.x).toFixed(6)
                        + ':' + Number(position.z).toFixed(6);
                    if (endpointKeys.has(key)) return;
                    endpointKeys.add(key);
                    const radius = 0.42;
                    const diamond = svgElement(this.document, 'polygon');
                    setAttributes(diamond, {
                        points: pointString([
                            { x: position.x, z: position.z - radius },
                            { x: position.x + radius, z: position.z },
                            { x: position.x, z: position.z + radius },
                            { x: position.x - radius, z: position.z },
                        ], this.projection),
                        fill: '#f59e0b',
                        stroke: '#92400e',
                        'stroke-width': '1.5',
                        'vector-effect': 'non-scaling-stroke',
                        'data-navigation-candidate-handoff-endpoint': key,
                    });
                    layer.appendChild(diamond);
                }, this);
            }, this);
        }
        if ((scenario.schemaVersion === 'facility-activity-scenario-v7'
                || candidatePresentation)
                && this.activityPathsVisible !== false) {
            const evidenceByPlacement = new Map(
                candidatePresentation
                    && Array.isArray(candidatePresentation.programEvidence)
                    ? candidatePresentation.programEvidence.map(function (item) {
                        return [item.actorPlacementId, item];
                    }) : []
            );
            scenario.actors.forEach(function (actor) {
                if (this.activityPathTypesVisible[actor.actorType] === false) {
                    return;
                }
                const evidence = evidenceByPlacement.get(actor.placementId);
                const segmentByPackage = new Map(
                    evidence && Array.isArray(evidence.pathSegments)
                        ? evidence.pathSegments.map(function (segment) {
                            return [segment.motionPackageId, segment];
                        }) : []
                );
                const packageIds = actor.loopMode === 'closed_path'
                    && Array.isArray(actor.cycleMotionPackageIds)
                    && actor.cycleMotionPackageIds.length
                    ? actor.cycleMotionPackageIds : [actor.motionPackageId];
                packageIds.forEach(function (packageId) {
                    const payload = payloads[packageId];
                    const movement = payload && payload.package
                        && payload.package.movement;
                    const poses = movement && movement.poses;
                    if (!Array.isArray(poses) || poses.length < 2) return;
                    const segment = segmentByPackage.get(packageId);
                    const phase = segment && segment.phase;
                    const line = svgElement(this.document, 'polyline');
                    const loadedPhase = [
                        'carry_out',
                        'loaded_putaway',
                        'loaded_dispatch',
                    ].includes(phase);
                    const emptyPhase = [
                        'return_empty',
                        'empty_to_rack',
                    ].includes(phase);
                    const color = loadedPhase
                        ? '#d97706' : emptyPhase
                            ? '#059669' : [
                                'finished_goods_pick',
                                'receiving_pick',
                            ].includes(phase)
                                ? '#2563eb' : actor.actorType === 'operator'
                                ? '#2563eb'
                                : actor.actorType === 'mobile_equipment'
                                    ? '#0f8f62' : '#d97706';
                    const displayPoses = activityDisplayOffsetPoints(
                        poses,
                        segment && segment.displayOffsetMeters
                    );
                    const attributes = {
                        points: pointString(displayPoses, this.projection),
                        fill: 'none',
                        stroke: color,
                        'stroke-width': '3.25',
                        'stroke-opacity': '0.96',
                        'stroke-linejoin': 'round',
                        'stroke-linecap': 'round',
                        'vector-effect': 'non-scaling-stroke',
                        'data-navigation-activity-actor-id': actor.actorId,
                        'data-navigation-activity-actor-type': actor.actorType,
                        'data-navigation-activity-journey-id':
                            movement.journeySolutionId || '',
                        'data-navigation-activity-package-id': packageId,
                        'data-navigation-activity-path-phase': phase || '',
                        'data-navigation-activity-display-offset-meters':
                            segment && Number.isFinite(Number(
                                segment.displayOffsetMeters
                            )) ? Number(segment.displayOffsetMeters) : 0,
                    };
                    if (emptyPhase) {
                        attributes['stroke-dasharray'] = '9 6';
                    }
                    setAttributes(line, attributes);
                    layer.appendChild(line);
                }, this);
            }, this);
        }
        scenario.actors.forEach(function (actor) {
            const payload = payloads[actor.motionPackageId];
            const marker = svgElement(this.document, 'polygon');
            const color = actor.actorType === 'operator'
                ? '#2563eb' : actor.actorType === 'mobile_equipment'
                    ? '#0f8f62' : '#d97706';
            setAttributes(marker, {
                fill: color,
                'fill-opacity': '0.94',
                stroke: '#ffffff',
                'stroke-width': '1.5',
                'vector-effect': 'non-scaling-stroke',
                'data-activity-actor-id': actor.actorId,
                'data-activity-actor-type': actor.actorType,
                'data-activity-placement-id': actor.placementId,
                'data-activity-borrowed-placement': 'true',
                display: 'none',
            });
            marker._facilityActivityProfile = payload
                ? (payload.actorProfile || payload.vehicleProfile || null)
                : null;
            layer.appendChild(marker);
            this.activityMarkers.set(actor.actorId, marker);
        }, this);
        this.svg.appendChild(layer);
        this._updateActivityMarkers();
        return true;
    };

    TopPlanAdapter.prototype._updateActivityMarkers = function () {
        if (!this.projection || !this.activitySnapshot
                || !Array.isArray(this.activitySnapshot.actors)) return false;
        let updated = false;
        this.activitySnapshot.actors.forEach(function (actor) {
            const marker = this.activityMarkers.get(actor.actorId);
            if (!marker) return;
            if (!actor.visible || !actor.pose) {
                marker.setAttribute('display', 'none');
                return;
            }
            const points = motionFootprintPoints(
                marker._facilityActivityProfile,
                actor.pose
            );
            if (points.length < 3) {
                marker.setAttribute('display', 'none');
                return;
            }
            setAttributes(marker, {
                points: pointString(points, this.projection),
                display: 'inline',
                'data-activity-distance-meters': finiteOr(
                    actor.pose.distanceMeters,
                    0
                ),
                'data-activity-heading-radians': finiteOr(
                    actor.pose.heading,
                    0
                ),
            });
            updated = true;
        }, this);
        return updated;
    };

    TopPlanAdapter.prototype.setActivityPresentation = function (value) {
        if (this.disposed) return false;
        if (!value) {
            this.activityPresentation = null;
            this.activitySnapshot = null;
            this.activityMarkers.clear();
            this._render();
            return true;
        }
        if (!value.scenario || !value.scenario.scenarioId
                || !value.actorPayloads) {
            throw new TypeError('Facility activity presentation is incomplete.');
        }
        this.motionPresentation = null;
        this.motionSnapshot = null;
        this.motionMarker = null;
        this.activityPresentation = clone(value);
        this.activitySnapshot = null;
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.updateActivitySnapshot = function (value) {
        if (this.disposed || !this.activityPresentation) return false;
        const snapshot = value && typeof value === 'object'
            ? clone(value) : null;
        if (!snapshot || snapshot.scenarioId
                !== this.activityPresentation.scenario.scenarioId) {
            return false;
        }
        this.activitySnapshot = snapshot;
        if (!this._updateActivityMarkers()) this._render();
        return true;
    };

    TopPlanAdapter.prototype.clearActivityPresentation = function () {
        return this.setActivityPresentation(null);
    };

    TopPlanAdapter.prototype.setActivityPathsVisible = function (requested) {
        if (this.disposed) return false;
        this.activityPathsVisible = requested !== false;
        this._render();
        return this.activityPathsVisible;
    };

    TopPlanAdapter.prototype.setActivityPathTypeVisible = function (
        actorType,
        requested
    ) {
        if (!['vehicle', 'operator', 'mobile_equipment'].includes(actorType)) {
            return false;
        }
        this.activityPathTypesVisible[actorType] = requested !== false;
        this._render();
        return this.activityPathTypesVisible[actorType];
    };

    TopPlanAdapter.prototype._render = function () {
        if (this.disposed || this.suspended || !this.svg) return;
        const size = this._measure();
        setAttributes(this.svg, {
            viewBox: '0 0 ' + size.width + ' ' + size.height,
        });
        removeChildren(this.svg);
        this.renderProjection = null;
        this.motionMarker = null;
        this.activityMarkers.clear();
        this.environmentDiagnostics = null;
        this.renderCount += 1;
        if (!this.layout) {
            this._notifyViewportChange();
            return;
        }

        this.geometry = collectTopPlanGeometry(this.layout, this.options);
        if (!this.projection
                || this.projection.width !== size.width
                || this.projection.height !== size.height) {
            this.projection = createTopPlanProjection(
                proposalReviewBounds(
                    this.layout,
                    this.proposalPreview,
                    this.options
                ),
                size,
                this.options.padding
            );
            this.semanticBaseScale = this.projection.scale;
        }

        const environmentLayer = svgElement(this.document, 'g');
        environmentLayer.setAttribute('data-layer', 'environment');
        environmentLayer.setAttribute('pointer-events', 'none');
        environmentLayer.setAttribute('aria-hidden', 'true');
        this.environmentDiagnostics = appendPlanEnvironment(
            this.document,
            environmentLayer,
            this.projection,
            this.options
        );
        this.svg.appendChild(environmentLayer);

        const zoneLayer = svgElement(this.document, 'g');
        zoneLayer.setAttribute('data-layer', 'zones');
        this.geometry.zones.filter(function (zone) {
            return this.layerVisibility[zonePresentationLayer(zone)] !== false;
        }, this).forEach(function (zone) {
            const selected = this.selections.has(zone.zoneId);
            const polygon = svgElement(this.document, 'polygon');
            setAttributes(polygon, {
                points: pointString(zone.points, this.projection),
                fill: selected ? '#bfe3ff' : (zone.fillColor || '#dcecf3'),
                'fill-opacity': '0.38',
                stroke: selected ? '#0878d1' : '#4d7c8a',
                'stroke-width': selected ? '3' : '1.5',
                'vector-effect': 'non-scaling-stroke',
                tabindex: '0',
                role: 'button',
                'aria-label': zone.label,
                'aria-selected': selected ? 'true' : 'false',
                'data-zone-id': zone.zoneId,
                'data-zone-presentation-layer': zonePresentationLayer(zone),
            });
            zoneLayer.appendChild(polygon);
        }, this);
        this.svg.appendChild(zoneLayer);

        const routeLayer = svgElement(this.document, 'g');
        routeLayer.setAttribute('data-layer', 'routes');
        const proposalChangedRoutes = new Set(
            this.proposalPreview
                ? this.proposalPreview.changedRouteIds : []
        );
        const proposalRemovedRoutes = new Set(
            this.proposalPreview
                ? this.proposalPreview.removedRouteIds : []
        );
        const proposalPreservedRoutes = new Set(
            this.proposalPreview
                ? this.proposalPreview.preservedRouteIds : []
        );
        this.geometry.routes.filter(function () {
            return this.layerVisibility.routes !== false;
        }, this).forEach(function (route) {
            const selected = this.selections.has(route.routeId);
            const aisle = route.extensions && route.extensions.facilityAisle;
            const polyline = svgElement(this.document, 'polyline');
            const proposalRouteState = proposalRemovedRoutes.has(route.routeId)
                ? 'removed'
                : proposalChangedRoutes.has(route.routeId)
                    ? 'changed'
                    : proposalPreservedRoutes.has(route.routeId)
                        ? 'preserved' : '';
            const routeColor = proposalRouteState === 'removed'
                ? '#dc2626'
                : proposalRouteState === 'changed'
                    ? '#d97706'
                    : proposalRouteState === 'preserved'
                        ? '#087f5b'
                        : aisle && aisle.color
                            ? aisle.color
                            : (route.routeKind === 'forklift'
                                ? '#d97706'
                                : (route.routeKind === 'operator'
                                    ? '#2563eb' : '#5b6472'));
            setAttributes(polyline, {
                points: pointString(route.points, this.projection),
                fill: 'none',
                stroke: routeColor,
                'stroke-width': Math.max(
                    2,
                    route.corridorWidth * this.projection.scale
                ),
                'stroke-opacity': selected ? '0.82' : '0.58',
                'stroke-linejoin': 'round',
                'stroke-linecap': 'round',
                tabindex: '0',
                role: 'button',
                'aria-label': route.label + ', facility aisle',
                'aria-selected': selected ? 'true' : 'false',
                'data-route-id': route.routeId,
                'data-proposal-route-state': proposalRouteState,
            });
            routeLayer.appendChild(polyline);
            const centerline = svgElement(this.document, 'polyline');
            setAttributes(centerline, {
                points: pointString(route.points, this.projection),
                fill: 'none',
                stroke: selected ? '#0878d1' : routeColor,
                'stroke-width': selected ? '3' : '1.5',
                'stroke-opacity': '0.95',
                'stroke-dasharray': aisle && aisle.direction === 'one_way'
                    ? '10 6' : 'none',
                'vector-effect': 'non-scaling-stroke',
                'pointer-events': 'none',
                'aria-hidden': 'true',
            });
            routeLayer.appendChild(centerline);
        }, this);
        if (this.proposalPreview && this.layerVisibility.routes !== false) {
            this.proposalPreview.proposedRoutes.forEach(function (route) {
                const points = (Array.isArray(route.centerline)
                    ? route.centerline
                    : Array.isArray(route.points) ? route.points : []).filter(
                    function (point) {
                        return point && Number.isFinite(Number(point.x))
                            && Number.isFinite(Number(point.z));
                    }
                );
                if (points.length < 2) return;
                const proposed = svgElement(this.document, 'polyline');
                setAttributes(proposed, {
                    points: pointString(points, this.projection),
                    fill: 'none',
                    stroke: '#7c3aed',
                    'stroke-width': Math.max(
                        3,
                        Number(route.corridorWidth || 1)
                            * this.projection.scale
                    ),
                    'stroke-opacity': '0.68',
                    'stroke-dasharray': '8 5',
                    'stroke-linejoin': 'round',
                    'stroke-linecap': 'round',
                    'vector-effect': 'non-scaling-stroke',
                    'pointer-events': 'none',
                    'aria-hidden': 'true',
                    'data-proposal-route-id': route.routeId || '',
                    'data-proposal-route-state': 'proposed',
                });
                routeLayer.appendChild(proposed);
            }, this);
        }
        if (this.layerVisibility.routes !== false
                && this.transientAislePreview
                && this.transientAislePreview.points.length >= 2) {
            const preview = this.transientAislePreview;
            const polyline = svgElement(this.document, 'polyline');
            setAttributes(polyline, {
                points: pointString(preview.points, this.projection),
                fill: 'none',
                stroke: preview.color,
                'stroke-width': Math.max(
                    2,
                    preview.corridorWidth * this.projection.scale
                ),
                'stroke-opacity': '0.42',
                'stroke-dasharray': '10 6',
                'stroke-linejoin': 'round',
                'stroke-linecap': 'round',
                'pointer-events': 'none',
                'data-aisle-preview': 'true',
            });
            routeLayer.appendChild(polyline);
        }
        this.svg.appendChild(routeLayer);

        const markingLayer = svgElement(this.document, 'g');
        markingLayer.setAttribute('data-layer', 'floor-markings');
        this.geometry.floorMarkings.filter(function () {
            return this.layerVisibility.markings !== false;
        }, this).forEach(function (marking) {
            appendFloorMarkingGraphic(
                this.document,
                markingLayer,
                marking,
                this.projection,
                this.selections.has(marking.markingId)
            );
        }, this);
        this.svg.appendChild(markingLayer);

        const newProposalIds = new Set(
            this.proposalPreview
                ? this.proposalPreview.newPlacementIds : []
        );
        const movedProposalIds = new Set(
            this.proposalPreview
                ? this.proposalPreview.movedPlacementIds : []
        );
        const removedProposalIds = new Set(
            this.proposalPreview
                ? this.proposalPreview.removedPlacementIds : []
        );
        const preservedProposalIds = new Set(
            this.proposalPreview
                ? this.proposalPreview.preservedPlacementIds : []
        );
        const proposedById = new Map(
            (this.proposalPreview
                ? this.proposalPreview.proposedPlacements : []).map(
                function (placement) {
                    return [placement.placementId, placement];
                }
            )
        );
        if (this.proposalPreview) {
            const beforeLayer = svgElement(this.document, 'g');
            beforeLayer.setAttribute('data-layer', 'proposal-before');
            this.proposalPreview.beforePlacements.forEach(function (placement) {
                const proposed = proposedById.get(placement.placementId);
                if (proposed && placement.transform && proposed.transform) {
                    const start = projectTopPlanPoint(
                        placement.transform.position || { x: 0, z: 0 },
                        this.projection
                    );
                    const end = projectTopPlanPoint(
                        proposed.transform.position || { x: 0, z: 0 },
                        this.projection
                    );
                    const movement = svgElement(this.document, 'line');
                    setAttributes(movement, {
                        x1: start.x,
                        y1: start.y,
                        x2: end.x,
                        y2: end.y,
                        stroke: '#d97706',
                        'stroke-width': '1.5',
                        'stroke-dasharray': '3 4',
                        'vector-effect': 'non-scaling-stroke',
                        'pointer-events': 'none',
                        'data-proposal-move-id': placement.placementId,
                    });
                    beforeLayer.appendChild(movement);
                }
                const before = svgElement(this.document, 'polygon');
                setAttributes(before, {
                    points: pointString(
                        placementFootprint(placement, this.options),
                        this.projection
                    ),
                    fill: '#d97706',
                    'fill-opacity': '0.06',
                    stroke: '#d97706',
                    'stroke-width': '2',
                    'stroke-dasharray': '4 4',
                    'vector-effect': 'non-scaling-stroke',
                    'pointer-events': 'none',
                    'aria-hidden': 'true',
                    'data-proposal-before-id': placement.placementId,
                    'data-proposal-before-state':
                        removedProposalIds.has(placement.placementId)
                            ? 'removed' : 'moved',
                });
                beforeLayer.appendChild(before);
            }, this);
            this.svg.appendChild(beforeLayer);
        }

        const placementLayer = svgElement(this.document, 'g');
        placementLayer.setAttribute('data-layer', 'placements');
        const stackGroups = new Map();
        this.geometry.placements.forEach(function (placement) {
            const relationship = placement.snapRelationship;
            if (!relationship || relationship.family !== 'vertical_stack'
                    || typeof relationship.stackId !== 'string') return;
            if (!stackGroups.has(relationship.stackId)) {
                stackGroups.set(relationship.stackId, []);
            }
            stackGroups.get(relationship.stackId).push(placement);
        });
        const stackInfoByPlacement = new Map();
        stackGroups.forEach(function (members, stackId) {
            members.sort(function (left, right) {
                return finiteOr(
                    left.snapRelationship && left.snapRelationship.level, 0
                ) - finiteOr(
                    right.snapRelationship && right.snapRelationship.level, 0
                );
            });
            const base = members[0];
            const relationship = base.snapRelationship || {};
            const count = Math.max(
                members.length,
                Math.floor(finiteOr(relationship.count, members.length))
            );
            const itemHeight = Math.max(
                0,
                finiteOr(relationship.itemHeightMeters, 0)
            );
            const gap = Math.max(0, finiteOr(relationship.gapMeters, 0));
            const info = {
                stackId: stackId,
                baseId: base.placementId,
                memberIds: members.map(function (member) {
                    return member.placementId;
                }),
                count: count,
                totalHeight: itemHeight * count + gap * Math.max(0, count - 1),
            };
            members.forEach(function (member) {
                stackInfoByPlacement.set(member.placementId, info);
            });
        });
        const activityPlacementIds = new Set(
            this.activityPresentation
            && this.activityPresentation.scenario
            && Array.isArray(this.activityPresentation.scenario.actors)
                ? this.activityPresentation.scenario.actors.map(function (actor) {
                    return actor.placementId;
                }).filter(Boolean)
                : []
        );
        this.geometry.placements.filter(function (placement) {
            if (this.layerVisibility.assets === false) return false;
            if (activityPlacementIds.has(placement.placementId)) return false;
            const info = stackInfoByPlacement.get(placement.placementId);
            return !info || info.baseId === placement.placementId;
        }, this).forEach(function (placement) {
            const stackInfo = stackInfoByPlacement.get(placement.placementId);
            const selected = stackInfo
                ? stackInfo.memberIds.some(function (placementId) {
                    return this.selections.has(placementId);
                }, this)
                : this.selections.has(placement.placementId);
            const proposalState = newProposalIds.has(placement.placementId)
                ? 'new'
                : (movedProposalIds.has(placement.placementId)
                    ? 'moved'
                    : (preservedProposalIds.has(placement.placementId)
                        ? 'preserved' : ''));
            const screenBounds = projectedPointBounds(
                placement.points,
                this.projection
            );
            const detailLevel = planCardDetailLevel(
                screenBounds.width,
                screenBounds.height,
                1
            );
            const card = svgElement(this.document, 'g');
            const displayUnitWord = planDisplayUnitWord(this.options);
            let cardAriaLabel = placement.label + ', '
                + planDisplayDimension(placement.width, this.options) + ' by '
                + planDisplayDimension(placement.depth, this.options) + ' '
                + displayUnitWord;
            if (stackInfo) {
                cardAriaLabel += ', stack of ' + stackInfo.count + ' items, '
                    + planDisplayDimension(
                        stackInfo.totalHeight, this.options
                    ) + ' ' + displayUnitWord + ' high';
            }
            if (proposalState) {
                cardAriaLabel += ' (' + proposalState + ' proposal)';
            }
            const cardAttributes = {
                class: 'ip-flw-plan-card',
                tabindex: proposalState ? '-1' : '0',
                role: proposalState ? 'img' : 'button',
                'aria-label': cardAriaLabel,
                'aria-selected': selected ? 'true' : 'false',
                'data-placement-id': placement.placementId,
                'data-asset-id': placement.assetId || '',
                'data-card-width': screenBounds.width,
                'data-card-height': screenBounds.height,
                'data-card-world-width': placement.width,
                'data-card-world-depth': placement.depth,
                'data-card-detail-level': detailLevel,
            };
            if (stackInfo) {
                cardAttributes['data-stack-id'] = stackInfo.stackId;
                cardAttributes['data-stack-count'] = stackInfo.count;
            }
            if (proposalState && proposalState !== 'preserved') {
                cardAttributes['pointer-events'] = 'none';
                cardAttributes['data-proposal-state'] = proposalState;
            } else if (proposalState) {
                cardAttributes['data-proposal-state'] = proposalState;
            }
            setAttributes(card, cardAttributes);
            const tooltip = svgElement(this.document, 'title');
            tooltip.textContent = placement.label + ' - '
                + planDisplayDimension(placement.width, this.options) + ' x '
                + planDisplayDimension(placement.depth, this.options) + ' '
                + normalizedPlanDisplayUnit(this.options);
            card.appendChild(tooltip);

            const polygon = svgElement(this.document, 'polygon');
            const attributes = {
                class: 'ip-flw-plan-card-body',
                points: pointString(placement.points, this.projection),
                fill: proposalState === 'new'
                    ? '#0ea5e9'
                    : (proposalState === 'moved'
                        ? '#8b5cf6'
                        : (proposalState === 'preserved'
                            ? '#b7ead8'
                            : (selected ? '#bfe3ff' : '#e8edf2'))),
                stroke: proposalState === 'new'
                    ? '#0284c7'
                    : (proposalState === 'moved'
                        ? '#7c3aed'
                        : (proposalState === 'preserved'
                            ? '#087f5b'
                            : (selected ? '#0878d1' : '#526273'))),
                'stroke-width': selected ? '3' : '1.5',
                'vector-effect': 'non-scaling-stroke',
                'aria-hidden': 'true',
            };
            if (proposalState && proposalState !== 'preserved') {
                attributes['fill-opacity'] = '0.24';
                attributes['stroke-width'] = '2';
                attributes['stroke-dasharray'] = '7 4';
            } else if (proposalState === 'preserved') {
                attributes['fill-opacity'] = '0.18';
                attributes['stroke-width'] = '2';
                attributes['stroke-dasharray'] = '3 3';
            }
            setAttributes(polygon, attributes);
            card.appendChild(polygon);

            if (stackInfo) {
                const badgeWidth = Math.max(24, Math.min(42, screenBounds.width * 0.34));
                const badgeHeight = Math.max(14, Math.min(20, screenBounds.height * 0.28));
                const badge = svgElement(this.document, 'rect');
                setAttributes(badge, {
                    x: screenBounds.maxX - badgeWidth - 3,
                    y: screenBounds.minY + 3,
                    width: badgeWidth,
                    height: badgeHeight,
                    rx: 3,
                    fill: '#0878d1',
                    stroke: '#ffffff',
                    'stroke-width': '1',
                    'vector-effect': 'non-scaling-stroke',
                    'pointer-events': 'none',
                    'data-stack-badge': stackInfo.stackId,
                });
                card.appendChild(badge);
                appendSvgText(this.document, card, {
                    x: screenBounds.maxX - badgeWidth / 2 - 3,
                    y: screenBounds.minY + badgeHeight / 2 + 3,
                    fill: '#ffffff',
                    'font-size': Math.max(8, Math.min(12, badgeHeight * 0.58)),
                    'font-weight': '700',
                    'text-anchor': 'middle',
                    'dominant-baseline': 'central',
                    'pointer-events': 'none',
                }, 'x' + stackInfo.count);
            }

            const accent = svgElement(this.document, 'line');
            setAttributes(accent, {
                class: 'ip-flw-plan-card-accent',
                x1: screenBounds.minX + 2,
                y1: screenBounds.minY + 3,
                x2: screenBounds.minX + 2,
                y2: screenBounds.maxY - 3,
                'stroke-width': Math.max(1.5, Math.min(3, screenBounds.width / 8)),
                'stroke-linecap': 'round',
                'pointer-events': 'none',
                'aria-hidden': 'true',
            });
            card.appendChild(accent);

            const compact = svgElement(this.document, 'g');
            setAttributes(compact, {
                class: 'ip-flw-plan-card-compact',
                'data-card-content': 'compact',
                'pointer-events': 'none',
                'aria-hidden': 'true',
            });
            const compactSize = Math.max(
                8,
                Math.min(16, Math.min(screenBounds.width, screenBounds.height) * 0.52)
            );
            const compactX = (screenBounds.minX + screenBounds.maxX) / 2;
            const compactY = (screenBounds.minY + screenBounds.maxY) / 2;
            const compactTile = svgElement(this.document, 'rect');
            setAttributes(compactTile, {
                class: 'ip-flw-plan-card-symbol',
                x: compactX - compactSize / 2,
                y: compactY - compactSize / 2,
                width: compactSize,
                height: compactSize,
                rx: Math.min(3, compactSize / 5),
                fill: '#dceeff',
                stroke: '#0878d1',
            });
            compact.appendChild(compactTile);
            appendSvgText(this.document, compact, {
                class: 'ip-flw-plan-card-symbol-text',
                x: compactX,
                y: compactY,
                'font-size': Math.max(4, compactSize * 0.42),
                'text-anchor': 'middle',
                'dominant-baseline': 'central',
            }, categorySymbol(placement.category));
            card.appendChild(compact);

            const full = svgElement(this.document, 'g');
            setAttributes(full, {
                class: 'ip-flw-plan-card-detail',
                'data-card-content': 'full',
                'pointer-events': 'none',
                'aria-hidden': 'true',
            });
            const centerX = (screenBounds.minX + screenBounds.maxX) / 2;
            const centerY = (screenBounds.minY + screenBounds.maxY) / 2;
            const shortest = Math.min(screenBounds.width, screenBounds.height);
            const fontSize = Math.max(4, Math.min(8, shortest * 0.14));
            appendSvgText(this.document, full, {
                class: 'ip-flw-plan-card-category',
                x: centerX,
                y: screenBounds.minY + Math.max(6, fontSize * 1.05),
                'font-size': Math.max(3.5, fontSize * 0.64),
                'text-anchor': 'middle',
            }, String(placement.category || 'Equipment').toUpperCase());
            const labelLines = balancedLabelLines(placement.label);
            const labelStartY = centerY
                - ((labelLines.length - 1) * fontSize * 0.55);
            labelLines.forEach(function (line, lineIndex) {
                const estimatedWidth = line.length * fontSize * 0.56;
                const availableWidth = Math.max(4, screenBounds.width - 12);
                const textAttributes = {
                    class: 'ip-flw-plan-card-title',
                    x: centerX,
                    y: labelStartY + lineIndex * fontSize * 1.1,
                    'font-size': fontSize,
                    'font-weight': '700',
                    'text-anchor': 'middle',
                    'dominant-baseline': 'central',
                };
                if (estimatedWidth > availableWidth) {
                    textAttributes.textLength = availableWidth;
                    textAttributes.lengthAdjust = 'spacingAndGlyphs';
                }
                appendSvgText(
                    this.document,
                    full,
                    textAttributes,
                    line
                );
            }, this);
            appendSvgText(this.document, full, {
                class: 'ip-flw-plan-card-dimensions',
                x: centerX,
                y: screenBounds.maxY - Math.max(4, fontSize * 0.55),
                'font-size': Math.max(3.5, fontSize * 0.62),
                'text-anchor': 'middle',
            }, planDisplayDimension(placement.width, this.options) + ' x '
                + planDisplayDimension(placement.depth, this.options) + ' '
                + normalizedPlanDisplayUnit(this.options));
            card.appendChild(full);
            applyPlanCardContentVisibility(card, detailLevel);
            placementLayer.appendChild(card);
        }, this);
        this.svg.appendChild(placementLayer);

        const zoneLabelLayer = svgElement(this.document, 'g');
        zoneLabelLayer.setAttribute('data-layer', 'zone-labels');
        zoneLabelLayer.setAttribute('pointer-events', 'none');
        zoneLabelLayer.setAttribute('aria-hidden', 'true');
        const labelObstacles = (this.layerVisibility.assets === false
            ? [] : this.geometry.placements).map(function (placement) {
            const bounds = projectedPointBounds(placement.points, this.projection);
            return {
                minX: bounds.minX - 3,
                minY: bounds.minY - 3,
                maxX: bounds.maxX + 3,
                maxY: bounds.maxY + 3,
            };
        }, this);
        const occupiedLabels = [];
        const suppressedZoneIds = [];
        const childZones = this.geometry.zones.filter(function (zone) {
            return Boolean(zone.parentZoneId);
        });
        const zoomRatio = this.projection.scale / Math.max(
            1e-6,
            finiteOr(this.semanticBaseScale, this.projection.scale)
        );
        const semanticLevel = childZones.length && zoomRatio >= 1.6
            ? 'detail' : 'overview';
        const labelZones = this.geometry.zones.filter(function (zone) {
            if (this.layerVisibility[zonePresentationLayer(zone)] === false) {
                return false;
            }
            if (this.selections.has(zone.zoneId)) return true;
            if (!childZones.length) return true;
            return semanticLevel === 'overview'
                ? !zone.parentZoneId : Boolean(zone.parentZoneId);
        }, this).sort(function (left, right) {
            const leftSelected = this.selections.has(left.zoneId) ? 1 : 0;
            const rightSelected = this.selections.has(right.zoneId) ? 1 : 0;
            if (leftSelected !== rightSelected) return rightSelected - leftSelected;
            const leftBounds = geometryBounds(left.points);
            const rightBounds = geometryBounds(right.points);
            const leftArea = (leftBounds.maxX - leftBounds.minX)
                * (leftBounds.maxZ - leftBounds.minZ);
            const rightArea = (rightBounds.maxX - rightBounds.minX)
                * (rightBounds.maxZ - rightBounds.minZ);
            return rightArea - leftArea || left.zoneId.localeCompare(right.zoneId);
        }.bind(this));
        labelZones.forEach(function (zone) {
            const selected = this.selections.has(zone.zoneId);
            const fullLabel = String(zone.label || zone.zoneId || 'Zone');
            const displayLabel = fullLabel.length > 42
                ? fullLabel.slice(0, 39) + '...' : fullLabel;
            const labelSize = {
                width: Math.max(
                    72,
                    Math.min(236, displayLabel.length * 6.5 + 22)
                ),
                height: 23,
            };
            const labelRect = zoneLabelScreenRect(
                zone,
                this.projection,
                labelObstacles,
                occupiedLabels,
                labelSize
            );
            if (!selected && labelRect.labelOverlapArea > 1) {
                suppressedZoneIds.push(zone.zoneId);
                return;
            }
            occupiedLabels.push(labelRect);
            const labelGroup = svgElement(this.document, 'g');
            setAttributes(labelGroup, {
                'data-zone-label-for': zone.zoneId,
                'data-zone-label-edge': labelRect.edge,
                'data-zone-presentation-layer': zonePresentationLayer(zone),
            });
            const labelBackground = svgElement(this.document, 'rect');
            setAttributes(labelBackground, {
                'data-zone-label-box-for': zone.zoneId,
                x: labelRect.minX,
                y: labelRect.minY,
                width: labelRect.width,
                height: labelRect.height,
                rx: 3,
                fill: selected ? '#0878d1' : '#f7fafc',
                'fill-opacity': selected ? '0.97' : '0.95',
                stroke: selected ? '#0878d1' : '#4d7c8a',
                'stroke-width': '1',
                'vector-effect': 'non-scaling-stroke',
            });
            const labelText = svgElement(this.document, 'text');
            setAttributes(labelText, {
                x: labelRect.minX + 11,
                y: labelRect.minY + 15.5,
                fill: selected ? '#ffffff' : '#173042',
                'font-family': 'Segoe UI, Arial, sans-serif',
                'font-size': '11',
                'font-weight': '700',
            });
            labelText.textContent = displayLabel;
            labelGroup.appendChild(labelBackground);
            labelGroup.appendChild(labelText);
            zoneLabelLayer.appendChild(labelGroup);
        }, this);
        zoneLabelLayer.setAttribute('data-semantic-zoom-level', semanticLevel);
        zoneLabelLayer.setAttribute(
            'data-visible-zone-label-count',
            String(occupiedLabels.length)
        );
        zoneLabelLayer.setAttribute(
            'data-suppressed-zone-label-count',
            String(suppressedZoneIds.length)
        );
        this.zoneLabelDiagnostics = {
            semanticLevel: semanticLevel,
            zoomRatio: zoomRatio,
            visibleZoneIds: labelZones.map(function (zone) {
                return zone.zoneId;
            }).filter(function (zoneId) {
                return !suppressedZoneIds.includes(zoneId);
            }),
            suppressedZoneIds: suppressedZoneIds,
            labelOverlapArea: occupiedLabels.reduce(
                function (total, item) {
                    return total + finiteOr(item.labelOverlapArea, 0);
                },
                0
            ),
        };
        this.svg.appendChild(zoneLabelLayer);
        this._applyTransientPlacementMove();
        this._applyTransientPlacementDuplicate();
        this._applyTransientZonePreview();
        this._applyTransientFloorMarkingPreview();
        this._applyTransientPatternPreview();

        if (this.ghostPlacement) {
            const ghostLayer = svgElement(this.document, 'g');
            ghostLayer.setAttribute('data-layer', 'ghost');
            const ghost = svgElement(this.document, 'polygon');
            setAttributes(ghost, {
                points: pointString(
                    placementFootprint(this.ghostPlacement, this.options),
                    this.projection
                ),
                fill: this.ghostPlacement.valid === false ? '#ef4444' : '#8b5cf6',
                'fill-opacity': '0.22',
                stroke: this.ghostPlacement.valid === false ? '#b91c1c' : '#6d28d9',
                'stroke-width': '2',
                'stroke-dasharray': '6 4',
                'vector-effect': 'non-scaling-stroke',
                'pointer-events': 'none',
                'data-facility-ghost': this.ghostPlacement.assetId || '',
            });
            ghostLayer.appendChild(ghost);
            this.svg.appendChild(ghostLayer);
        }
        this._appendNavigationOverlay();
        this._appendMotionOverlay();
        this._appendActivityOverlay();
        this.renderProjection = Object.freeze(Object.assign(
            {},
            this.projection
        ));
        this._notifyViewportChange();
    };

    TopPlanAdapter.prototype._applyProjectionTransform = function () {
        if (this.disposed || this.suspended || !this.svg
                || !this.projection || !this.renderProjection) return false;
        const current = this.projection;
        const rendered = this.renderProjection;
        if (current.minX !== rendered.minX
                || current.maxZ !== rendered.maxZ
                || !finite(current.scale)
                || !finite(rendered.scale)
                || rendered.scale <= 0) return false;
        const scale = current.scale / rendered.scale;
        const translateX = current.offsetX - rendered.offsetX * scale;
        const translateY = current.offsetY - rendered.offsetY * scale;
        if (!finite(scale) || !finite(translateX) || !finite(translateY)) {
            return false;
        }
        const transform = 'matrix(' + scale + ' 0 0 ' + scale + ' '
            + translateX + ' ' + translateY + ')';
        Array.prototype.forEach.call(this.svg.children, function (layer) {
            if (layer && typeof layer.setAttribute === 'function') {
                layer.setAttribute('transform', transform);
            }
        });
        updatePlanCardDetailLevels(this.svg, scale);
        this.renderCount += 1;
        return true;
    };

    TopPlanAdapter.prototype._applyTransientPlacementMove = function () {
        if (!this.svg || !this.svg.children) return false;
        const movableLayers = [];
        Array.prototype.forEach.call(this.svg.children, function (layer) {
            if (layer && typeof layer.getAttribute === 'function'
                    && ['placements', 'floor-markings'].includes(
                        layer.getAttribute('data-layer')
                    )) {
                movableLayers.push(layer);
            }
        });
        if (!movableLayers.length) return false;
        const preview = this.transientPlacementMove;
        const identifiers = new Set(preview ? preview.placementIds : []);
        const projection = this.renderProjection || this.projection;
        const scale = projection && finite(projection.scale)
            ? projection.scale : 1;
        const delta = preview ? preview.delta : { x: 0, z: 0 };
        const transform = 'translate('
            + finiteOr(delta.x, 0) * scale + ' '
            + -finiteOr(delta.z, 0) * scale + ')';
        movableLayers.forEach(function (movableLayer) {
            Array.prototype.forEach.call(movableLayer.children, function (card) {
                if (!card || typeof card.getAttribute !== 'function') return;
                const identifier = card.getAttribute('data-placement-id')
                    || card.getAttribute('data-floor-marking-id');
                const active = identifiers.has(identifier);
                card.setAttribute('transform', active ? transform : '');
                card.setAttribute('data-drag-preview', active ? 'true' : 'false');
            });
        });
        return true;
    };

    TopPlanAdapter.prototype._removeTransientFloorMarkingPreview = function () {
        if (!this.svg || !this.svg.children) return false;
        let removed = false;
        Array.prototype.slice.call(this.svg.children).forEach(function (layer) {
            if (layer && typeof layer.getAttribute === 'function'
                    && layer.getAttribute('data-layer')
                        === 'transient-floor-marking-preview') {
                this.svg.removeChild(layer);
                removed = true;
            }
        }, this);
        return removed;
    };

    TopPlanAdapter.prototype._applyTransientFloorMarkingPreview = function () {
        this._removeTransientFloorMarkingPreview();
        const marking = this.transientFloorMarkingPreview;
        const projection = this.renderProjection || this.projection;
        if (!marking || !projection) return true;
        const layer = svgElement(this.document, 'g');
        setAttributes(layer, {
            'data-layer': 'transient-floor-marking-preview',
            'pointer-events': 'none',
            'aria-hidden': 'true',
            opacity: '0.72',
        });
        let referenceLayer = null;
        Array.prototype.forEach.call(this.svg.children, function (candidate) {
            if (candidate && typeof candidate.getAttribute === 'function'
                    && candidate.getAttribute('data-layer')
                        === 'floor-markings') {
                referenceLayer = candidate;
            }
        });
        const projectionTransform = referenceLayer
            && referenceLayer.getAttribute('transform');
        if (projectionTransform) layer.setAttribute(
            'transform',
            projectionTransform
        );
        appendFloorMarkingGraphic(
            this.document,
            layer,
            marking,
            projection,
            true
        );
        this.svg.appendChild(layer);
        return true;
    };

    TopPlanAdapter.prototype._removeTransientZonePreview = function () {
        if (!this.svg || !this.svg.children) return false;
        let removed = false;
        Array.prototype.slice.call(this.svg.children).forEach(function (layer) {
            if (layer && typeof layer.getAttribute === 'function'
                    && layer.getAttribute('data-layer')
                        === 'transient-zone-preview') {
                this.svg.removeChild(layer);
                removed = true;
            }
        }, this);
        return removed;
    };

    TopPlanAdapter.prototype._applyTransientZonePreview = function () {
        this._removeTransientZonePreview();
        const preview = this.transientZonePreview;
        const projection = this.renderProjection || this.projection;
        if (!preview || !preview.points.length || !projection) return true;
        const layer = svgElement(this.document, 'g');
        setAttributes(layer, {
            'data-layer': 'transient-zone-preview',
            'pointer-events': 'none',
            'aria-hidden': 'true',
        });
        let referenceLayer = null;
        Array.prototype.forEach.call(this.svg.children, function (candidate) {
            if (candidate && typeof candidate.getAttribute === 'function'
                    && candidate.getAttribute('data-layer') === 'zones') {
                referenceLayer = candidate;
            }
        });
        const projectionTransform = referenceLayer
            && referenceLayer.getAttribute('transform');
        if (projectionTransform) layer.setAttribute(
            'transform',
            projectionTransform
        );

        const shape = svgElement(
            this.document,
            preview.closed && preview.points.length >= 3
                ? 'polygon' : 'polyline'
        );
        setAttributes(shape, {
            points: pointString(preview.points, projection),
            fill: preview.closed ? '#38a3db' : 'none',
            'fill-opacity': preview.closed ? '0.16' : '0',
            stroke: '#0878d1',
            'stroke-width': '2',
            'stroke-dasharray': '7 4',
            'stroke-linejoin': 'round',
            'stroke-linecap': 'round',
            'vector-effect': 'non-scaling-stroke',
            'data-facility-zone-preview': preview.kind,
        });
        layer.appendChild(shape);
        preview.points.forEach(function (point, index) {
            const screen = projectTopPlanPoint(point, projection);
            const vertex = svgElement(this.document, 'circle');
            setAttributes(vertex, {
                cx: screen.x,
                cy: screen.y,
                r: '3.5',
                fill: '#ffffff',
                stroke: '#0878d1',
                'stroke-width': '1.5',
                'vector-effect': 'non-scaling-stroke',
                'data-zone-preview-vertex': String(index),
            });
            layer.appendChild(vertex);
        }, this);
        this.svg.appendChild(layer);
        return true;
    };

    TopPlanAdapter.prototype._removeTransientPlacementDuplicate = function () {
        if (!this.svg || !this.svg.children) return false;
        let removed = false;
        Array.prototype.slice.call(this.svg.children).forEach(function (layer) {
            if (layer && typeof layer.getAttribute === 'function'
                    && layer.getAttribute('data-layer')
                        === 'placement-duplicate-preview') {
                this.svg.removeChild(layer);
                removed = true;
            }
        }, this);
        return removed;
    };

    TopPlanAdapter.prototype._applyTransientPlacementDuplicate = function () {
        this._removeTransientPlacementDuplicate();
        const preview = this.transientPlacementDuplicate;
        if (!preview || !preview.placementIds.length || !this.geometry) return true;
        const projection = this.renderProjection || this.projection;
        if (!projection) return false;
        const identifiers = new Set(preview.placementIds);
        const scale = finiteOr(projection.scale, 1);
        const transform = 'translate('
            + finiteOr(preview.delta.x, 0) * scale + ' '
            + -finiteOr(preview.delta.z, 0) * scale + ')';
        const layer = svgElement(this.document, 'g');
        setAttributes(layer, {
            'data-layer': 'placement-duplicate-preview',
            'pointer-events': 'none',
            'aria-hidden': 'true',
        });
        let placementLayer = null;
        Array.prototype.forEach.call(this.svg.children, function (candidate) {
            if (candidate && typeof candidate.getAttribute === 'function'
                    && ['placements', 'floor-markings'].includes(
                        candidate.getAttribute('data-layer')
                    )) {
                placementLayer = candidate;
            }
        });
        const projectionTransform = placementLayer
            && placementLayer.getAttribute('transform');
        if (projectionTransform) layer.setAttribute('transform', projectionTransform);
        this.geometry.placements.forEach(function (placement) {
            if (!identifiers.has(placement.placementId)) return;
            const copy = svgElement(this.document, 'g');
            setAttributes(copy, {
                transform: transform,
                'data-duplicate-preview-id': placement.placementId,
            });
            const footprint = svgElement(this.document, 'polygon');
            setAttributes(footprint, {
                class: 'ip-flw-plan-duplicate-preview',
                points: pointString(placement.points, projection),
                'vector-effect': 'non-scaling-stroke',
            });
            copy.appendChild(footprint);
            const bounds = projectedPointBounds(placement.points, projection);
            appendSvgText(this.document, copy, {
                class: 'ip-flw-plan-duplicate-preview-mark',
                x: (bounds.minX + bounds.maxX) / 2,
                y: (bounds.minY + bounds.maxY) / 2,
                'font-size': Math.max(8, Math.min(14, bounds.height * 0.28)),
                'font-weight': '700',
                'text-anchor': 'middle',
                'dominant-baseline': 'central',
            }, '+');
            layer.appendChild(copy);
        }, this);
        this.geometry.floorMarkings.forEach(function (marking) {
            if (!identifiers.has(marking.markingId)) return;
            const copy = svgElement(this.document, 'g');
            setAttributes(copy, {
                transform: transform,
                opacity: '0.72',
                'data-duplicate-preview-id': marking.markingId,
            });
            appendFloorMarkingGraphic(
                this.document,
                copy,
                marking,
                projection,
                false
            );
            layer.appendChild(copy);
        }, this);
        this.svg.appendChild(layer);
        return true;
    };

    TopPlanAdapter.prototype._removeTransientPatternPreview = function () {
        if (!this.svg || !this.svg.children) return false;
        let removed = false;
        Array.prototype.slice.call(this.svg.children).forEach(function (layer) {
            if (layer && typeof layer.getAttribute === 'function'
                    && layer.getAttribute('data-layer')
                        === 'pattern-preview') {
                this.svg.removeChild(layer);
                removed = true;
            }
        }, this);
        return removed;
    };

    TopPlanAdapter.prototype._applyTransientPatternPreview = function () {
        this._removeTransientPatternPreview();
        const preview = this.transientPatternPreview;
        const projection = this.renderProjection || this.projection;
        if (!preview || !projection || !this.layout) return true;
        const layer = svgElement(this.document, 'g');
        setAttributes(layer, {
            'data-layer': 'pattern-preview',
            'pointer-events': 'none',
            'aria-hidden': 'true',
        });
        let referenceLayer = null;
        Array.prototype.forEach.call(this.svg.children, function (candidate) {
            if (candidate && typeof candidate.getAttribute === 'function'
                    && candidate.getAttribute('data-layer') === 'placements') {
                referenceLayer = candidate;
            }
        });
        const projectionTransform = referenceLayer
            && referenceLayer.getAttribute('transform');
        if (projectionTransform) layer.setAttribute(
            'transform', projectionTransform
        );

        const targets = preview.mode === 'vertical-stack'
            ? []
            : (preview.copies || []).concat(preview.moves || []);
        targets.forEach(function (target, index) {
            const sourceId = target && target.sourceId;
            const placement = this.layout.placements.find(function (item) {
                return item.placementId === sourceId;
            });
            const marking = (this.layout.floorMarkings || []).find(
                function (item) { return item.markingId === sourceId; }
            );
            const zone = this.layout.zones.find(function (item) {
                return item.zoneId === sourceId;
            });
            if (placement && target.kind === 'placement') {
                const value = clone(placement);
                value.transform = clone(value.transform || {});
                value.transform.position = clone(target.position || {});
                value.transform.quaternion = yawQuaternion(
                    target.rotationDegrees
                );
                const polygon = svgElement(this.document, 'polygon');
                setAttributes(polygon, {
                    class: 'ip-flw-plan-pattern-preview',
                    points: pointString(
                        placementFootprint(value, this.options),
                        projection
                    ),
                    fill: preview.mode === 'cell-layout'
                        ? '#0ea5e9' : '#8b5cf6',
                    'fill-opacity': '0.2',
                    stroke: preview.mode === 'cell-layout'
                        ? '#0284c7' : '#7c3aed',
                    'stroke-width': '2',
                    'stroke-dasharray': '7 4',
                    'vector-effect': 'non-scaling-stroke',
                    'data-pattern-preview-source': sourceId,
                    'data-pattern-preview-index': String(index),
                });
                layer.appendChild(polygon);
                return;
            }
            if (marking && target.kind === 'floor-marking') {
                const value = clone(marking);
                value.transform = {
                    position: clone(target.position || {}),
                    rotationDegrees: finiteOr(target.rotationDegrees, 0),
                };
                value.points = floorMarkingFootprint(value);
                const group = svgElement(this.document, 'g');
                setAttributes(group, {
                    opacity: '0.64',
                    'data-pattern-preview-source': sourceId,
                    'data-pattern-preview-index': String(index),
                });
                appendFloorMarkingGraphic(
                    this.document,
                    group,
                    value,
                    projection,
                    false
                );
                layer.appendChild(group);
                return;
            }
            if (zone && target.kind === 'zone'
                    && Array.isArray(target.boundary)) {
                const polygon = svgElement(this.document, 'polygon');
                setAttributes(polygon, {
                    points: pointString(target.boundary, projection),
                    fill: '#8b5cf6',
                    'fill-opacity': '0.08',
                    stroke: '#7c3aed',
                    'stroke-width': '2',
                    'stroke-dasharray': '7 4',
                    'vector-effect': 'non-scaling-stroke',
                    'data-pattern-preview-source': sourceId,
                    'data-pattern-preview-index': String(index),
                });
                layer.appendChild(polygon);
            }
        }, this);

        const guide = preview.guide || {};
        if (guide.kind === 'vertical-stack' && guide.position) {
            const sourceId = preview.relationships
                && preview.relationships[0]
                && preview.relationships[0].sourceId;
            const placement = this.layout.placements.find(function (item) {
                return item.placementId === sourceId;
            });
            if (placement) {
                const points = placementFootprint(placement, this.options);
                const outline = svgElement(this.document, 'polygon');
                setAttributes(outline, {
                    points: pointString(points, projection),
                    fill: '#8b5cf6',
                    'fill-opacity': '0.18',
                    stroke: '#7c3aed',
                    'stroke-width': '2',
                    'stroke-dasharray': '7 4',
                    'vector-effect': 'non-scaling-stroke',
                    'data-pattern-guide': 'vertical-stack',
                });
                layer.appendChild(outline);
                const bounds = projectedPointBounds(points, projection);
                const badgeWidth = Math.max(
                    24, Math.min(42, bounds.width * 0.34)
                );
                const badgeHeight = Math.max(
                    14, Math.min(20, bounds.height * 0.28)
                );
                const badge = svgElement(this.document, 'rect');
                setAttributes(badge, {
                    x: bounds.maxX - badgeWidth - 3,
                    y: bounds.minY + 3,
                    width: badgeWidth,
                    height: badgeHeight,
                    rx: 3,
                    fill: '#7c3aed',
                    stroke: '#ffffff',
                    'stroke-width': '1',
                    'vector-effect': 'non-scaling-stroke',
                    'pointer-events': 'none',
                    'aria-hidden': 'true',
                });
                layer.appendChild(badge);
                appendSvgText(this.document, layer, {
                    x: bounds.maxX - badgeWidth / 2 - 3,
                    y: bounds.minY + badgeHeight / 2 + 3,
                    fill: '#ffffff',
                    'font-size': Math.max(
                        8, Math.min(12, badgeHeight * 0.58)
                    ),
                    'font-weight': '700',
                    'text-anchor': 'middle',
                    'dominant-baseline': 'central',
                    'pointer-events': 'none',
                }, 'x' + Math.max(2, finiteOr(guide.count, 2)));
            }
        } else if (guide.kind === 'linear' && guide.start && guide.end) {
            const start = projectTopPlanPoint(guide.start, projection);
            const end = projectTopPlanPoint(guide.end, projection);
            const line = svgElement(this.document, 'line');
            setAttributes(line, {
                x1: start.x,
                y1: start.y,
                x2: end.x,
                y2: end.y,
                stroke: '#7c3aed',
                'stroke-width': '1.5',
                'stroke-dasharray': '3 4',
                'vector-effect': 'non-scaling-stroke',
                'data-pattern-guide': 'linear',
            });
            layer.appendChild(line);
        } else if (guide.kind === 'perimeter'
                && Array.isArray(guide.points)
                && guide.points.length >= 4) {
            const outline = svgElement(this.document, 'polygon');
            setAttributes(outline, {
                points: pointString(guide.points, projection),
                fill: 'none',
                stroke: '#7c3aed',
                'stroke-width': '1.5',
                'stroke-dasharray': '5 4',
                'vector-effect': 'non-scaling-stroke',
                'data-pattern-guide': 'perimeter',
            });
            layer.appendChild(outline);
        } else if (guide.kind === 'swap' && guide.start && guide.end) {
            const start = projectTopPlanPoint(guide.start, projection);
            const end = projectTopPlanPoint(guide.end, projection);
            const line = svgElement(this.document, 'line');
            setAttributes(line, {
                x1: start.x,
                y1: start.y,
                x2: end.x,
                y2: end.y,
                stroke: '#0891b2',
                'stroke-width': '2',
                'stroke-dasharray': '6 4',
                'vector-effect': 'non-scaling-stroke',
                'data-pattern-guide': 'swap',
            });
            layer.appendChild(line);
            [start, end].forEach(function (point) {
                const marker = svgElement(this.document, 'circle');
                setAttributes(marker, {
                    cx: point.x,
                    cy: point.y,
                    r: 4,
                    fill: '#ecfeff',
                    stroke: '#0891b2',
                    'stroke-width': '2',
                    'vector-effect': 'non-scaling-stroke',
                });
                layer.appendChild(marker);
            }, this);
        } else if (guide.kind === 'mirror' && guide.start && guide.end) {
            const start = projectTopPlanPoint(guide.start, projection);
            const end = projectTopPlanPoint(guide.end, projection);
            const line = svgElement(this.document, 'line');
            setAttributes(line, {
                x1: start.x,
                y1: start.y,
                x2: end.x,
                y2: end.y,
                stroke: '#0891b2',
                'stroke-width': '2',
                'stroke-dasharray': '10 5 2 5',
                'vector-effect': 'non-scaling-stroke',
                'data-pattern-guide': 'mirror',
            });
            layer.appendChild(line);
        } else if (guide.kind === 'circular' && guide.center) {
            const center = projectTopPlanPoint(guide.center, projection);
            const circle = svgElement(this.document, 'circle');
            setAttributes(circle, {
                cx: center.x,
                cy: center.y,
                r: Math.max(1, finiteOr(guide.radius, 0) * projection.scale),
                fill: 'none',
                stroke: '#7c3aed',
                'stroke-width': '1.5',
                'stroke-dasharray': '3 4',
                'vector-effect': 'non-scaling-stroke',
                'data-pattern-guide': 'circular',
            });
            layer.appendChild(circle);
        } else if (guide.kind === 'cell-layout' && guide.center) {
            const halfWidth = finiteOr(guide.width, 0) / 2;
            const halfDepth = finiteOr(guide.depth, 0) / 2;
            const radians = finiteOr(guide.angleDegrees, 0) * Math.PI / 180;
            const cosine = Math.cos(radians);
            const sine = Math.sin(radians);
            const points = [
                { x: -halfWidth, z: -halfDepth },
                { x: halfWidth, z: -halfDepth },
                { x: halfWidth, z: halfDepth },
                { x: -halfWidth, z: halfDepth },
            ].map(function (point) {
                return {
                    x: guide.center.x + point.x * cosine + point.z * sine,
                    z: guide.center.z - point.x * sine + point.z * cosine,
                };
            });
            const outline = svgElement(this.document, 'polygon');
            setAttributes(outline, {
                points: pointString(points, projection),
                fill: 'none',
                stroke: '#0284c7',
                'stroke-width': '1.5',
                'stroke-dasharray': '3 4',
                'vector-effect': 'non-scaling-stroke',
                'data-pattern-guide': 'cell-layout',
            });
            layer.appendChild(outline);
        }
        this.svg.appendChild(layer);
        return true;
    };

    TopPlanAdapter.prototype._handlePick = function (event) {
        const identifier = targetLayoutObjectId(event && event.target, this.svg);
        if (identifier) this.pick(identifier);
    };

    TopPlanAdapter.prototype._handleKeyPick = function (event) {
        const key = String(event && event.key || '').toLowerCase();
        if (key !== 'enter' && key !== ' ') return;
        const identifier = targetLayoutObjectId(event && event.target, this.svg);
        if (!identifier) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        this.pick(identifier);
    };

    TopPlanAdapter.prototype.setSelectionHandler = function (handler) {
        this.selectionHandler = typeof handler === 'function' ? handler : null;
    };

    TopPlanAdapter.prototype.getViewportState = function () {
        if (this.disposed || !this.projection) return null;
        const bounds = normalizedPlanWorldBounds(this.options);
        const grid = normalizedPlanGrid(this.options, bounds);
        return {
            projection: clone(this.projection),
            worldBounds: bounds ? clone(bounds) : null,
            grid: grid ? clone(grid) : null,
            displayUnit: normalizedPlanDisplayUnit(this.options),
            showGrid: this.options.showGrid !== false,
        };
    };

    TopPlanAdapter.prototype._notifyViewportChange = function () {
        if (!this.viewportChangeHandler) return;
        this.viewportChangeHandler(this.getViewportState(), this);
    };

    TopPlanAdapter.prototype.setViewportChangeHandler = function (handler) {
        this.viewportChangeHandler = typeof handler === 'function'
            ? handler : null;
        this._notifyViewportChange();
    };

    TopPlanAdapter.prototype.setViewPreferences = function (preferences) {
        if (this.disposed) return false;
        const source = preferences && typeof preferences === 'object'
            ? preferences : {};
        let changed = false;
        if (source.displayUnit === 'm' || source.displayUnit === 'ft') {
            if (this.options.displayUnit !== source.displayUnit) {
                this.options.displayUnit = source.displayUnit;
                changed = true;
            }
        }
        if (typeof source.showGrid === 'boolean'
                && this.options.showGrid !== source.showGrid) {
            this.options.showGrid = source.showGrid;
            changed = true;
        }
        if (changed) this._render();
        else this._notifyViewportChange();
        return true;
    };

    TopPlanAdapter.prototype.setLayerVisibility = function (visibility) {
        if (this.disposed) return false;
        const next = normalizeLayerVisibility(
            visibility,
            this.layerVisibility
        );
        if (JSON.stringify(next) === JSON.stringify(this.layerVisibility)) {
            return clone(this.layerVisibility);
        }
        this.layerVisibility = next;
        this._render();
        return clone(this.layerVisibility);
    };

    TopPlanAdapter.prototype.getLayerVisibility = function () {
        return clone(this.layerVisibility);
    };

    TopPlanAdapter.prototype.setEnvironmentSettings = function (settings) {
        if (this.disposed) return false;
        const source = settings && typeof settings === 'object' ? settings : {};
        const previousBounds = JSON.stringify(
            normalizedPlanWorldBounds(this.options)
        );
        if (source.worldBounds) this.options.worldBounds = clone(source.worldBounds);
        if (finite(source.floorGridSpacing)) {
            this.options.floorGridSpacing = Number(source.floorGridSpacing);
        }
        if (finite(source.floorMajorGridSpacing)) {
            this.options.floorMajorGridSpacing = Number(
                source.floorMajorGridSpacing
            );
        }
        const nextBounds = JSON.stringify(normalizedPlanWorldBounds(this.options));
        if (this.layout && previousBounds !== nextBounds) {
            this.fitFacility();
        } else if (this.layout) {
            this._render();
        } else {
            this._notifyViewportChange();
        }
        return true;
    };

    TopPlanAdapter.prototype.setLayout = function (layout) {
        if (this.disposed) return false;
        const hadLayout = Boolean(this.layout);
        this.motionPresentation = null;
        this.motionSnapshot = null;
        this.motionMarker = null;
        this.activityPresentation = null;
        this.activitySnapshot = null;
        this.activityMarkers.clear();
        this.transientPlacementMove = null;
        this.transientPlacementDuplicate = null;
        this.transientFloorMarkingPreview = null;
        this.transientAislePreview = null;
        this.transientPatternPreview = null;
        this.layout = layout ? clone(assertLayout(layout)) : null;
        if (this.selection && this.layout) {
            const selectedExists = this.layout.placements.some(
                function (placement) {
                    return placement.placementId === this.selection;
                },
                this
            ) || this.layout.zones.some(
                function (zone) { return zone.zoneId === this.selection; },
                this
            ) || (this.layout.floorMarkings || []).some(
                function (marking) {
                    return marking.markingId === this.selection;
                },
                this
            ) || (this.layout.routes || []).some(
                function (route) { return route.routeId === this.selection; },
                this
            );
            if (!selectedExists) this.selection = null;
        }
        if (this.layout) {
            const available = new Set(
                this.layout.placements.map(function (placement) {
                    return placement.placementId;
                }).concat(this.layout.zones.map(function (zone) {
                    return zone.zoneId;
                })).concat((this.layout.floorMarkings || []).map(function (marking) {
                    return marking.markingId;
                })).concat((this.layout.routes || []).map(function (route) {
                    return route.routeId;
                }))
            );
            this.selections = new Set(Array.from(this.selections).filter(
                function (identifier) { return available.has(identifier); }
            ));
        } else {
            this.selections.clear();
        }
        if (!hadLayout || !this.layout) this.projection = null;
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.setGhostPlacement = function (ghost) {
        if (this.disposed) return false;
        if (!ghost) {
            this.ghostPlacement = null;
            this._render();
            return true;
        }
        const position = ghost.worldPosition || ghost.position;
        if (!position || !finite(position.x) || !finite(position.z)) return false;
        this.ghostPlacement = {
            assetId: ghost.assetId || '',
            assetDefinitionRevision: ghost.assetDefinitionRevision || '',
            transform: {
                position: {
                    x: position.x,
                    y: finiteOr(position.y, 0),
                    z: position.z,
                },
                quaternion: ghost.quaternion
                    || { x: 0, y: 0, z: 0, w: 1 },
                scale: finiteOr(ghost.scale, 1),
            },
            valid: ghost.valid !== false,
            metadata: clone(ghost.metadata || {}),
        };
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.setProposalPreview = function (preview) {
        if (this.disposed) return false;
        this.transientPlacementMove = null;
        this.transientPlacementDuplicate = null;
        this.proposalPreview = normalizeProposalPreview(preview);
        this.projection = null;
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.setTransientPlacementMove = function (
        placementIds,
        delta
    ) {
        if (this.disposed || this.suspended) return false;
        this.transientPlacementDuplicate = null;
        this._removeTransientPlacementDuplicate();
        const identifiers = Array.from(new Set(
            (Array.isArray(placementIds) ? placementIds : []).filter(
                function (identifier) {
                    return typeof identifier === 'string' && identifier;
                }
            )
        ));
        if (!identifiers.length || !delta) {
            this.transientPlacementMove = null;
        } else {
            this.transientPlacementMove = {
                placementIds: identifiers,
                delta: {
                    x: finiteOr(delta.x, 0),
                    y: finiteOr(delta.y, 0),
                    z: finiteOr(delta.z, 0),
                },
            };
        }
        const applied = this._applyTransientPlacementMove();
        if (applied) this.renderCount += 1;
        return applied;
    };

    TopPlanAdapter.prototype.setTransientPlacementDuplicate = function (
        placementIds,
        delta
    ) {
        if (this.disposed || this.suspended) return false;
        this.transientPlacementMove = null;
        this._applyTransientPlacementMove();
        const identifiers = Array.from(new Set(
            (Array.isArray(placementIds) ? placementIds : []).filter(
                function (identifier) {
                    return typeof identifier === 'string' && identifier;
                }
            )
        ));
        if (!identifiers.length || !delta) {
            this.transientPlacementDuplicate = null;
        } else {
            this.transientPlacementDuplicate = {
                placementIds: identifiers,
                delta: {
                    x: finiteOr(delta.x, 0),
                    y: finiteOr(delta.y, 0),
                    z: finiteOr(delta.z, 0),
                },
            };
        }
        const applied = this._applyTransientPlacementDuplicate();
        if (applied) this.renderCount += 1;
        return applied;
    };

    TopPlanAdapter.prototype.setTransientZonePreview = function (
        points,
        options
    ) {
        if (this.disposed || this.suspended) return false;
        const normalized = (Array.isArray(points) ? points : []).filter(
            function (point) {
                return point && finite(point.x) && finite(point.z);
            }
        ).map(function (point) {
            return { x: point.x, z: point.z };
        });
        if (!normalized.length) {
            this.transientZonePreview = null;
        } else {
            const source = options && typeof options === 'object'
                ? options : {};
            this.transientZonePreview = {
                points: normalized,
                closed: source.closed === true,
                kind: source.kind === 'polygon' ? 'polygon' : 'rectangle',
            };
        }
        const applied = this._applyTransientZonePreview();
        if (applied) this.renderCount += 1;
        return applied;
    };

    TopPlanAdapter.prototype.setTransientFloorMarkingPreview = function (marking) {
        if (this.disposed || this.suspended) return false;
        if (!marking) {
            this.transientFloorMarkingPreview = null;
        } else {
            const normalized = clone(marking);
            normalized.markingId = normalized.markingId
                || 'fm-transient-preview';
            normalized.transform = normalized.transform || {};
            normalized.transform.position = normalized.transform.position || {
                x: 0, y: 0, z: 0,
            };
            normalized.points = floorMarkingFootprint(normalized);
            this.transientFloorMarkingPreview = normalized;
        }
        const applied = this._applyTransientFloorMarkingPreview();
        if (applied) this.renderCount += 1;
        return applied;
    };

    TopPlanAdapter.prototype.setTransientAislePreview = function (preview) {
        if (this.disposed || this.suspended) return false;
        if (!preview) {
            this.transientAislePreview = null;
        } else {
            const points = Array.isArray(preview.points)
                ? preview.points.filter(function (point) {
                    return point && finite(point.x) && finite(point.z);
                }).map(function (point) {
                    return { x: point.x, z: point.z };
                }) : [];
            this.transientAislePreview = {
                points: points,
                corridorWidth: Math.max(
                    0.01,
                    finiteOr(preview.corridorWidth, 1)
                ),
                color: preview.color || '#d9a514',
            };
        }
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.setTransientPatternPreview = function (preview) {
        if (this.disposed || this.suspended) return false;
        this.transientPatternPreview = preview ? clone(preview) : null;
        const applied = this._applyTransientPatternPreview();
        if (applied) this.renderCount += 1;
        return applied;
    };

    TopPlanAdapter.prototype.setSelection = function (placementId) {
        if (this.disposed) return false;
        const next = placementId || null;
        if (this.selection === next
                && this.selections.size === (next ? 1 : 0)
                && (!next || this.selections.has(next))) return true;
        this.selection = next;
        this.selections = new Set(next ? [next] : []);
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.setSelections = function (identifiers) {
        if (this.disposed) return false;
        const requested = Array.isArray(identifiers) ? identifiers : [];
        this.selections = new Set(requested.filter(function (identifier) {
            return typeof identifier === 'string' && identifier;
        }));
        this.selection = requested.length ? requested[0] : null;
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.pick = function (identifier) {
        if (this.disposed || !this.layout) return false;
        const exists = this.layout.placements.some(function (placement) {
            return placement.placementId === identifier;
        }) || this.layout.zones.some(function (zone) {
            return zone.zoneId === identifier;
        }) || (this.layout.floorMarkings || []).some(function (marking) {
            return marking.markingId === identifier;
        }) || (this.layout.routes || []).some(function (route) {
            return route.routeId === identifier;
        });
        if (!exists) return false;
        if (this.selectionHandler) this.selectionHandler(identifier, this);
        else this.setSelection(identifier);
        return true;
    };

    TopPlanAdapter.prototype._fit = function (includeWorldBounds) {
        if (this.disposed || !this.layout) return null;
        const hasLayoutContent = Boolean(
            this.layout.placements.length
            || this.layout.zones.length
            || this.layout.routes.length
            || (this.proposalPreview
                && this.proposalPreview.beforePlacements.length)
        );
        const viewport = this._measure();
        const fitPadding = includeWorldBounds === false && hasLayoutContent
            ? Math.max(
                finiteOr(this.options.padding, DEFAULT_VIEW_PADDING),
                Math.min(viewport.width, viewport.height) * 0.055
            )
            : this.options.padding;
        this.projection = createTopPlanProjection(
            proposalReviewBounds(
                this.layout,
                this.proposalPreview,
                this.options,
                includeWorldBounds !== false || !hasLayoutContent
            ),
            viewport,
            fitPadding
        );
        this.semanticBaseScale = this.projection.scale;
        this._render();
        return clone(this.projection);
    };

    TopPlanAdapter.prototype.fitFacility = function () {
        return this._fit(true);
    };

    TopPlanAdapter.prototype.fitLayout = function () {
        return this._fit(false);
    };

    TopPlanAdapter.prototype.fit = function () {
        return this.fitFacility();
    };

    TopPlanAdapter.prototype.clientToWorld = function (input) {
        if (this.disposed || !this.layout) return null;
        if (!this.projection) this.fit();
        const planPoint = clientPlanPoint(input, this.svg, this.projection);
        if (!planPoint) return null;
        const world = unprojectTopPlanPoint(planPoint, this.projection);
        return { x: world.x, y: finiteOr(input && input.floorY, 0), z: world.z };
    };

    TopPlanAdapter.prototype.worldToClient = function (input) {
        if (this.disposed || !this.layout || !input) return null;
        if (!this.projection) this.fit();
        const planPoint = projectTopPlanPoint(input, this.projection);
        const rect = typeof this.svg.getBoundingClientRect === 'function'
            ? this.svg.getBoundingClientRect() : null;
        const left = finiteOr(rect && rect.left, 0);
        const top = finiteOr(rect && rect.top, 0);
        const width = Math.max(1, finiteOr(rect && rect.width, this.projection.width));
        const height = Math.max(1, finiteOr(rect && rect.height, this.projection.height));
        return {
            x: left + (planPoint.x / this.projection.width) * width,
            y: top + (planPoint.y / this.projection.height) * height,
        };
    };

    TopPlanAdapter.prototype.panByPixels = function (deltaX, deltaY) {
        if (this.disposed || !this.layout) return false;
        if (!this.projection) this.fit();
        this.projection = Object.freeze(Object.assign({}, this.projection, {
            offsetX: this.projection.offsetX + finiteOr(deltaX, 0),
            offsetY: this.projection.offsetY + finiteOr(deltaY, 0),
        }));
        if (!this._applyProjectionTransform()) this._render();
        else this._notifyViewportChange();
        return true;
    };

    TopPlanAdapter.prototype.zoomAt = function (input, requestedFactor) {
        if (this.disposed || !this.layout) return false;
        if (!this.projection) this.fit();
        const factor = Math.max(0.25, Math.min(4, finiteOr(requestedFactor, 1)));
        if (factor === 1) return true;
        const hasChildZones = Boolean(this.geometry && this.geometry.zones.some(
            function (zone) { return Boolean(zone.parentZoneId); }
        ));
        const previousSemanticLevel = hasChildZones
            && this.projection.scale / Math.max(
                1e-6,
                finiteOr(this.semanticBaseScale, this.projection.scale)
            ) >= 1.6 ? 'detail' : 'overview';
        const planPoint = clientPlanPoint(input, this.svg, this.projection);
        if (!planPoint) return false;
        const world = unprojectTopPlanPoint(planPoint, this.projection);
        const scale = Math.max(
            1e-6,
            Math.min(1e6, this.projection.scale * factor)
        );
        this.projection = Object.freeze(Object.assign({}, this.projection, {
            scale: scale,
            offsetX: planPoint.x - (world.x - this.projection.minX) * scale,
            offsetY: planPoint.y - (this.projection.maxZ - world.z) * scale,
        }));
        const nextSemanticLevel = hasChildZones
            && this.projection.scale / Math.max(
                1e-6,
                finiteOr(this.semanticBaseScale, this.projection.scale)
            ) >= 1.6 ? 'detail' : 'overview';
        if (nextSemanticLevel !== previousSemanticLevel) this._render();
        else if (!this._applyProjectionTransform()) this._render();
        else this._notifyViewportChange();
        return true;
    };

    TopPlanAdapter.prototype.setScaleAt = function (input, requestedScale) {
        if (this.disposed || !this.layout) return false;
        if (!this.projection) this.fit();
        const hasChildZones = Boolean(this.geometry && this.geometry.zones.some(
            function (zone) { return Boolean(zone.parentZoneId); }
        ));
        const previousSemanticLevel = hasChildZones
            && this.projection.scale / Math.max(
                1e-6,
                finiteOr(this.semanticBaseScale, this.projection.scale)
            ) >= 1.6 ? 'detail' : 'overview';
        const scale = Math.max(1e-6, Math.min(1e6,
            finiteOr(requestedScale, this.projection.scale)
        ));
        const planPoint = clientPlanPoint(input, this.svg, this.projection);
        if (!planPoint) return false;
        const world = unprojectTopPlanPoint(planPoint, this.projection);
        this.projection = Object.freeze(Object.assign({}, this.projection, {
            scale: scale,
            offsetX: planPoint.x - (world.x - this.projection.minX) * scale,
            offsetY: planPoint.y - (this.projection.maxZ - world.z) * scale,
        }));
        const nextSemanticLevel = hasChildZones
            && this.projection.scale / Math.max(
                1e-6,
                finiteOr(this.semanticBaseScale, this.projection.scale)
            ) >= 1.6 ? 'detail' : 'overview';
        if (nextSemanticLevel !== previousSemanticLevel) this._render();
        else if (!this._applyProjectionTransform()) this._render();
        else this._notifyViewportChange();
        return true;
    };

    TopPlanAdapter.prototype.resolveMarquee = function (input) {
        if (this.disposed || !this.layout || !input) return [];
        const start = input.start;
        const end = input.end;
        if (!start || !end) return [];
        const query = {
            minX: Math.min(start.x, end.x),
            minZ: Math.min(start.z, end.z),
            maxX: Math.max(start.x, end.x),
            maxZ: Math.max(start.z, end.z),
        };
        const geometry = this.geometry || collectTopPlanGeometry(
            this.layout,
            this.options
        );
        const ids = [];
        geometry.placements.forEach(function (placement) {
            if (boundsTouch(query, geometryBounds(placement.points))) {
                ids.push(placement.placementId);
            }
        });
        geometry.zones.forEach(function (zone) {
            if (boundsTouch(query, geometryBounds(zone.points))) {
                ids.push(zone.zoneId);
            }
        });
        geometry.floorMarkings.forEach(function (marking) {
            if (boundsTouch(query, geometryBounds(marking.points))) {
                ids.push(marking.markingId);
            }
        });
        return ids.sort();
    };

    TopPlanAdapter.prototype.getDiagnostics = function () {
        const expectedById = new Map(
            (this.layout && this.layout.placements || []).map(
                function (placement) {
                    return [placement.placementId, placement.transform || {}];
                }
            )
        );
        const geometryById = new Map(
            (this.geometry && this.geometry.placements || []).map(
                function (placement) {
                    return [placement.placementId, placement.transform || {}];
                }
            )
        );
        const transformMismatchIds = [];
        expectedById.forEach(function (expected, placementId) {
            const actual = geometryById.get(placementId);
            if (!actual || JSON.stringify(actual) !== JSON.stringify(expected)) {
                transformMismatchIds.push(placementId);
            }
        });
        const unexpectedPlacementIds = Array.from(geometryById.keys()).filter(
            function (placementId) { return !expectedById.has(placementId); }
        ).sort();
        const missingPlacementIds = Array.from(expectedById.keys()).filter(
            function (placementId) { return !geometryById.has(placementId); }
        ).sort();
        return {
            id: this.id,
            type: this.type,
            mounted: !this.disposed && !this.suspended
                && !!this.svg && this.svg.parentNode === this.host,
            suspended: this.suspended,
            observerCount: this.observerCount,
            renderCount: this.renderCount,
            selection: this.selection,
            selections: Array.from(this.selections).sort(),
            ghostActive: Boolean(this.ghostPlacement),
            proposalPreviewActive: Boolean(this.proposalPreview),
            proposalBeforeCount: this.proposalPreview
                ? this.proposalPreview.beforePlacements.length : 0,
            proposalNewCount: this.proposalPreview
                ? this.proposalPreview.newPlacementIds.length : 0,
            proposalMovedCount: this.proposalPreview
                ? this.proposalPreview.movedPlacementIds.length : 0,
            transientPlacementMove: this.transientPlacementMove
                ? clone(this.transientPlacementMove) : null,
            transientPlacementDuplicate: this.transientPlacementDuplicate
                ? clone(this.transientPlacementDuplicate) : null,
            transientZonePreview: this.transientZonePreview
                ? clone(this.transientZonePreview) : null,
            transientFloorMarkingPreview: this.transientFloorMarkingPreview
                ? clone(this.transientFloorMarkingPreview) : null,
            transientPatternPreview: this.transientPatternPreview
                ? clone(this.transientPatternPreview) : null,
            navigation: {
                authoring: this.navigationAuthoringPreview
                    ? clone(this.navigationAuthoringPreview) : null,
                pathsVisible: this.navigationPathsVisible !== false,
                markerVisible: Boolean(this.navigationMarker),
                durableConstraintCount: this.layout
                    && this.layout.extensions
                    && this.layout.extensions.facilityNavigation
                    && Array.isArray(
                        this.layout.extensions.facilityNavigation
                            .manualPathConstraints
                    )
                    ? this.layout.extensions.facilityNavigation
                        .manualPathConstraints.length : 0,
            },
            environment: this.environmentDiagnostics
                ? clone(this.environmentDiagnostics) : null,
            layerVisibility: clone(this.layerVisibility),
            motion: {
                loaded: Boolean(this.motionPresentation),
                packageId: this.motionPresentation
                    ? this.motionPresentation.package.packageId : null,
                pose: this.motionSnapshot && this.motionSnapshot.pose
                    ? clone(this.motionSnapshot.pose) : null,
                markerVisible: Boolean(
                    this.motionMarker && this.motionSnapshot
                        && this.motionSnapshot.pose
                ),
            },
            activity: {
                loaded: Boolean(this.activityPresentation),
                scenarioId: this.activityPresentation
                    ? this.activityPresentation.scenario.scenarioId : null,
                actorCount: this.activitySnapshot
                    && Array.isArray(this.activitySnapshot.actors)
                    ? this.activitySnapshot.actors.length : 0,
                visibleMarkerCount: Array.from(
                    this.activityMarkers.values()
                ).filter(function (marker) {
                    return marker.getAttribute('display') !== 'none';
                }).length,
            },
            zoneLabels: this.zoneLabelDiagnostics
                ? clone(this.zoneLabelDiagnostics) : null,
            projection: this.projection ? clone(this.projection) : null,
            placementIds: this.layout
                ? this.layout.placements.map(function (placement) {
                    return placement.placementId;
                })
                : [],
            floorMarkingIds: this.layout
                ? (this.layout.floorMarkings || []).map(function (marking) {
                    return marking.markingId;
                })
                : [],
            placementTransformAudit: {
                adapter: 'top_plan',
                status: (
                    !this.layout || !this.geometry
                        ? 'unavailable'
                        : transformMismatchIds.length
                            || missingPlacementIds.length
                            || unexpectedPlacementIds.length
                            ? 'mismatch' : 'match'
                ),
                expectedPlacementCount: expectedById.size,
                auditedPlacementCount: geometryById.size,
                transformMismatchCount: transformMismatchIds.length,
                transformMismatchIds: transformMismatchIds.sort().slice(0, 20),
                missingPlacementCount: missingPlacementIds.length,
                missingPlacementIds: missingPlacementIds.slice(0, 20),
                unexpectedPlacementCount: unexpectedPlacementIds.length,
                unexpectedPlacementIds: unexpectedPlacementIds.slice(0, 20),
                evidenceStatus: this.layout && this.geometry
                    ? 'derived' : 'unknown',
                qualification: (
                    'Compares persisted placement transforms with the world-space '
                    + 'geometry backing the rendered 2D plan.'
                ),
            },
        };
    };

    TopPlanAdapter.prototype.suspend = function () {
        if (this.disposed || this.suspended) return false;
        this.suspended = true;
        if (this.resizeObserver) this.resizeObserver.disconnect();
        this.resizeObserverActive = false;
        this.observerCount = 0;
        return true;
    };

    TopPlanAdapter.prototype.resume = function () {
        if (this.disposed || !this.suspended) return false;
        this.suspended = false;
        this._observeHost();
        this._render();
        return true;
    };

    TopPlanAdapter.prototype.dispose = function () {
        if (this.disposed) return;
        this.disposed = true;
        this.suspended = false;
        if (this.resizeObserver) this.resizeObserver.disconnect();
        this.resizeObserver = null;
        this.resizeObserverActive = false;
        this.observerCount = 0;
        if (this.svg) {
            this.svg.removeEventListener('click', this._handlePick);
            this.svg.removeEventListener('keydown', this._handleKeyPick);
            if (this.svg.parentNode) this.svg.parentNode.removeChild(this.svg);
        }
        this.selectionHandler = null;
        this.viewportChangeHandler = null;
        this.selections.clear();
        this.layout = null;
        this.geometry = null;
        this.environmentDiagnostics = null;
        this.projection = null;
        this.renderProjection = null;
        this.ghostPlacement = null;
        this.proposalPreview = null;
        this.transientPlacementMove = null;
        this.transientPlacementDuplicate = null;
        this.transientZonePreview = null;
        this.transientPatternPreview = null;
        this.navigationAuthoringPreview = null;
        this.navigationMarker = null;
        this.transientFloorMarkingPreview = null;
        this.transientAislePreview = null;
        this.motionPresentation = null;
        this.motionSnapshot = null;
        this.motionMarker = null;
        this.activityPresentation = null;
        this.activitySnapshot = null;
        this.activityMarkers.clear();
    };

    function parseControllerArguments(layoutOrOptions, maybeOptions) {
        if (layoutOrOptions && layoutOrOptions.schemaVersion === 1) {
            return {
                layout: layoutOrOptions,
                options: maybeOptions || {},
            };
        }
        const options = layoutOrOptions || {};
        return {
            layout: options.layout || null,
            options: options,
        };
    }

    function FacilityLayoutEditorController(layoutOrOptions, maybeOptions) {
        if (!(this instanceof FacilityLayoutEditorController)) {
            return new FacilityLayoutEditorController(layoutOrOptions, maybeOptions);
        }
        const parsed = parseControllerArguments(layoutOrOptions, maybeOptions);
        this.layout = null;
        this.assetCatalog = clone(parsed.options.assetCatalog || []);
        this.selection = null;
        this.views = [];
        this.pendingViewUpdates = [];
        this.viewUpdateGeneration = 0;
        this.disposed = false;
        this.suspended = false;
        const adapters = parsed.options.adapters || parsed.options.views || [];
        if (!Array.isArray(adapters)) {
            throw new TypeError('facility layout adapters must be an array');
        }
        adapters.forEach(this._attachView.bind(this));
        if (parsed.layout) this.setLayout(parsed.layout);
    }

    FacilityLayoutEditorController.prototype._assertActive = function () {
        if (this.disposed) throw new Error('facility layout editor is disposed');
    };

    FacilityLayoutEditorController.prototype._attachView = function (adapter) {
        if (!adapter || typeof adapter !== 'object') {
            throw new TypeError('facility layout adapter must be an object');
        }
        const handler = function (placementId) {
            if (!this.disposed) this.select(placementId);
        }.bind(this);
        let detach = null;
        if (typeof adapter.setSelectionHandler === 'function') {
            adapter.setSelectionHandler(handler);
            detach = function () { adapter.setSelectionHandler(null); };
        } else if (typeof adapter.subscribeSelection === 'function') {
            detach = adapter.subscribeSelection(handler);
        }
        this.views.push({
            adapter: adapter,
            detach: typeof detach === 'function' ? detach : null,
        });
    };

    FacilityLayoutEditorController.prototype._placementExists = function (placementId) {
        return !!this.layout && this.layout.placements.some(function (placement) {
            return placement.placementId === placementId;
        });
    };

    FacilityLayoutEditorController.prototype._notifyLayout = function () {
        const generation = this.viewUpdateGeneration + 1;
        this.viewUpdateGeneration = generation;
        const pending = [];
        this.views.forEach(function (entry) {
            if (typeof entry.adapter.setLayout === 'function') {
                entry.adapter.setLayout(clone(this.layout));
            } else if (typeof entry.adapter.setScene === 'function') {
                const result = entry.adapter.setScene({
                    layout: clone(this.layout),
                    assetCatalog: clone(this.assetCatalog),
                });
                if (result && typeof result.then === 'function') {
                    pending.push(Promise.resolve(result));
                }
            }
        }, this);
        this.pendingViewUpdates = pending;
        if (pending.length) {
            Promise.allSettled(pending).then(function () {
                if (!this.disposed
                        && this.viewUpdateGeneration === generation) {
                    this.pendingViewUpdates = [];
                }
            }.bind(this));
        }
    };

    FacilityLayoutEditorController.prototype._notifySelection = function () {
        this.views.forEach(function (entry) {
            if (typeof entry.adapter.setSelection === 'function') {
                entry.adapter.setSelection(this.selection);
            }
        }, this);
    };

    FacilityLayoutEditorController.prototype.setLayout = function (layout) {
        this._assertActive();
        this.layout = clone(assertLayout(layout));
        if (this.selection && !this._placementExists(this.selection)) {
            this.selection = null;
        }
        this._notifyLayout();
        this._notifySelection();
        return this.getState();
    };

    FacilityLayoutEditorController.prototype.setAssetCatalog = function (catalog) {
        this._assertActive();
        this.assetCatalog = clone(catalog || []);
        if (this.layout) this._notifyLayout();
        return this.getState();
    };

    FacilityLayoutEditorController.prototype.ready = function () {
        this._assertActive();
        const generation = this.viewUpdateGeneration;
        return Promise.all(this.pendingViewUpdates.slice()).then(function () {
            if (!this.disposed && this.viewUpdateGeneration === generation) {
                this.pendingViewUpdates = [];
            }
            return this.getState();
        }.bind(this));
    };

    FacilityLayoutEditorController.prototype.select = function (placementId) {
        this._assertActive();
        if (typeof placementId !== 'string' || !this._placementExists(placementId)) {
            return false;
        }
        if (this.selection === placementId) return true;
        this.selection = placementId;
        this._notifySelection();
        return true;
    };

    FacilityLayoutEditorController.prototype.clearSelection = function () {
        this._assertActive();
        if (this.selection === null) return false;
        this.selection = null;
        this._notifySelection();
        return true;
    };

    FacilityLayoutEditorController.prototype._invokeViewCommand = function (
        command,
        fallback
    ) {
        this._assertActive();
        if (this.suspended) return [];
        const results = [];
        this.views.forEach(function (entry) {
            let action = entry.adapter[command];
            if (typeof action !== 'function' && fallback) {
                action = entry.adapter[fallback];
            }
            if (typeof action === 'function') {
                results.push(action.call(entry.adapter));
            }
        });
        return results;
    };

    FacilityLayoutEditorController.prototype.fitFacility = function () {
        return this._invokeViewCommand('fitFacility', 'fit');
    };

    FacilityLayoutEditorController.prototype.fitLayout = function () {
        return this._invokeViewCommand('fitLayout', 'fit');
    };

    FacilityLayoutEditorController.prototype.topView = function () {
        return this._invokeViewCommand('topView');
    };

    FacilityLayoutEditorController.prototype.fit = function () {
        return this.fitFacility();
    };

    FacilityLayoutEditorController.prototype.suspend = function () {
        this._assertActive();
        if (this.suspended) return false;
        this.suspended = true;
        this.views.forEach(function (entry) {
            if (typeof entry.adapter.suspend === 'function') {
                entry.adapter.suspend();
            }
        });
        return true;
    };

    FacilityLayoutEditorController.prototype.resume = function () {
        this._assertActive();
        if (!this.suspended) return false;
        this.suspended = false;
        this.views.forEach(function (entry) {
            if (typeof entry.adapter.resume === 'function') {
                entry.adapter.resume();
            }
        });
        this._notifySelection();
        return true;
    };

    FacilityLayoutEditorController.prototype.getState = function () {
        const viewDiagnostics = this.views.map(function (entry, index) {
            const adapter = entry.adapter;
            const diagnostics = typeof adapter.getDiagnostics === 'function'
                ? adapter.getDiagnostics()
                : {};
            return Object.assign({
                id: String(adapter.id || adapter.viewId || ('view-' + index)),
                type: String(adapter.type || 'view'),
                mounted: !this.disposed,
                observerCount: 0,
                renderCount: 0,
                selection: this.selection,
            }, diagnostics);
        }, this);
        const observerCount = viewDiagnostics.reduce(function (total, item) {
            return total + finiteOr(item.observerCount, 0);
        }, 0);
        const renderCount = viewDiagnostics.reduce(function (total, item) {
            return total + finiteOr(item.renderCount, 0);
        }, 0);
        return {
            apiVersion: API_VERSION,
            disposed: this.disposed,
            suspended: this.suspended,
            layout: clone(this.layout),
            layoutId: this.layout && this.layout.layoutId || null,
            selectedPlacementId: this.selection,
            selection: this.selection
                ? { kind: 'placement', placementId: this.selection }
                : null,
            diagnostics: {
                mountedViews: viewDiagnostics.filter(function (item) {
                    return item.mounted;
                }).length,
                pendingViewUpdates: this.pendingViewUpdates.length,
                observerCount: observerCount,
                renderCount: renderCount,
                selection: this.selection,
                views: viewDiagnostics,
            },
        };
    };

    FacilityLayoutEditorController.prototype.dispose = function () {
        if (this.disposed) return;
        this.views.forEach(function (entry) {
            if (entry.detach) entry.detach();
            if (typeof entry.adapter.dispose === 'function') {
                entry.adapter.dispose();
            }
        });
        this.views = [];
        this.pendingViewUpdates = [];
        this.viewUpdateGeneration += 1;
        this.assetCatalog = [];
        this.selection = null;
        this.suspended = false;
        this.disposed = true;
    };

    function createEditor(layoutOrOptions, maybeOptions) {
        return new FacilityLayoutEditorController(layoutOrOptions, maybeOptions);
    }

    function createTopPlanAdapter(host, options) {
        return new TopPlanAdapter(host, options);
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        DEFAULT_FALLBACK_FOOTPRINT: DEFAULT_FALLBACK_FOOTPRINT,
        FacilityLayoutEditorController: FacilityLayoutEditorController,
        TopPlanAdapter: TopPlanAdapter,
        createEditor: createEditor,
        createTopPlanAdapter: createTopPlanAdapter,
        collectTopPlanBounds: collectTopPlanBounds,
        collectTopPlanGeometry: collectTopPlanGeometry,
        createTopPlanProjection: createTopPlanProjection,
        placementFootprint: placementFootprint,
        projectTopPlanPoint: projectTopPlanPoint,
        unprojectTopPlanPoint: unprojectTopPlanPoint,
    });
}));
