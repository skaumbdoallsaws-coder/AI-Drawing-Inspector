(function (root, factory) {
    'use strict';

    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityPatterns = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const API_VERSION = 1;
    const EPSILON = 1e-9;
    const PERIMETER_JOIN_TOLERANCE = 0.001;
    const MAX_PATTERN_COUNT = 50;
    const MAX_PATTERN_OBJECTS = 240;
    const CELL_SHAPES = Object.freeze([
        'line',
        'l',
        'u',
        'grid',
        'parallel',
        'serpentine',
        'loop',
        'spine',
        'herringbone',
        'cluster',
    ]);

    function clone(value) {
        if (value === undefined) return undefined;
        return JSON.parse(JSON.stringify(value));
    }

    function finite(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function positive(value, fallback, label) {
        const number = finite(value, fallback);
        if (!(number > 0)) {
            throw new RangeError((label || 'value') + ' must be greater than zero');
        }
        return number;
    }

    function nonnegative(value, fallback, label) {
        const number = finite(value, fallback);
        if (!(number >= 0)) {
            throw new RangeError((label || 'value') + ' must not be negative');
        }
        return number;
    }

    function integer(value, fallback, minimum, maximum, label) {
        const number = Math.round(finite(value, fallback));
        if (number < minimum || number > maximum) {
            throw new RangeError(
                (label || 'value') + ' must be between '
                + minimum + ' and ' + maximum
            );
        }
        return number;
    }

    function cleanId(value) {
        return typeof value === 'string' ? value.trim() : '';
    }

    function normalizeDegrees(value) {
        let result = finite(value, 0) % 360;
        if (result < 0) result += 360;
        return Number(result.toFixed(6));
    }

    function yawDegrees(quaternion) {
        const q = quaternion || {};
        const x = finite(q.x, 0);
        const y = finite(q.y, 0);
        const z = finite(q.z, 0);
        const w = finite(q.w, 1);
        return normalizeDegrees(Math.atan2(
            2 * (w * y + x * z),
            1 - 2 * (y * y + z * z)
        ) * 180 / Math.PI);
    }

    function rotateVector(point, angleDegrees) {
        const radians = finite(angleDegrees, 0) * Math.PI / 180;
        const cosine = Math.cos(radians);
        const sine = Math.sin(radians);
        return {
            x: finite(point && point.x, 0) * cosine
                + finite(point && point.z, 0) * sine,
            z: -finite(point && point.x, 0) * sine
                + finite(point && point.z, 0) * cosine,
        };
    }

    function transformPoint(point, origin, target, angleDegrees) {
        const offset = rotateVector({
            x: finite(point && point.x, 0) - finite(origin && origin.x, 0),
            z: finite(point && point.z, 0) - finite(origin && origin.z, 0),
        }, angleDegrees);
        return {
            x: finite(target && target.x, 0) + offset.x,
            z: finite(target && target.z, 0) + offset.z,
        };
    }

    function normalizedMirrorAxis(start, end) {
        const axisStart = {
            x: finite(start && start.x, NaN),
            z: finite(start && start.z, NaN),
        };
        const axisEnd = {
            x: finite(end && end.x, NaN),
            z: finite(end && end.z, NaN),
        };
        if (![axisStart.x, axisStart.z, axisEnd.x, axisEnd.z].every(
            Number.isFinite
        )) {
            throw new TypeError('mirror axis requires two finite floor points');
        }
        const dx = axisEnd.x - axisStart.x;
        const dz = axisEnd.z - axisStart.z;
        const length = Math.hypot(dx, dz);
        if (!(length > EPSILON)) {
            throw new RangeError('mirror axis points must be different');
        }
        return {
            start: axisStart,
            end: axisEnd,
            unit: { x: dx / length, z: dz / length },
        };
    }

    function mirrorVector(vector, start, end) {
        const axis = normalizedMirrorAxis(start, end);
        const x = finite(vector && vector.x, 0);
        const z = finite(vector && vector.z, 0);
        const projection = x * axis.unit.x + z * axis.unit.z;
        return {
            x: 2 * projection * axis.unit.x - x,
            z: 2 * projection * axis.unit.z - z,
        };
    }

    function mirrorPoint(point, start, end) {
        const axis = normalizedMirrorAxis(start, end);
        const offset = {
            x: finite(point && point.x, 0) - axis.start.x,
            z: finite(point && point.z, 0) - axis.start.z,
        };
        const projection = offset.x * axis.unit.x
            + offset.z * axis.unit.z;
        return {
            x: axis.start.x + 2 * projection * axis.unit.x - offset.x,
            z: axis.start.z + 2 * projection * axis.unit.z - offset.z,
        };
    }

    function mirrorRotationDegrees(rotationDegrees, start, end) {
        const direction = rotateVector({ x: 1, z: 0 }, rotationDegrees);
        const reflected = mirrorVector(direction, start, end);
        return normalizeDegrees(
            Math.atan2(-reflected.z, reflected.x) * 180 / Math.PI
        );
    }

    function pointInPolygon(point, boundary) {
        if (!point || !Array.isArray(boundary) || boundary.length < 3) {
            return false;
        }
        const x = finite(point.x, NaN);
        const z = finite(point.z, NaN);
        if (!Number.isFinite(x) || !Number.isFinite(z)) return false;
        let inside = false;
        for (let index = 0, previous = boundary.length - 1;
                index < boundary.length; previous = index, index += 1) {
            const a = boundary[index] || {};
            const b = boundary[previous] || {};
            const ax = finite(a.x, NaN);
            const az = finite(a.z, NaN);
            const bx = finite(b.x, NaN);
            const bz = finite(b.z, NaN);
            if (![ax, az, bx, bz].every(Number.isFinite)) continue;
            const crosses = (az > z) !== (bz > z)
                && x < (bx - ax) * (z - az) / (bz - az) + ax;
            if (crosses) inside = !inside;
        }
        return inside;
    }

    function boundsFromPoints(points) {
        const values = Array.isArray(points) ? points : [];
        if (!values.length) return null;
        const result = values.reduce(function (bounds, point) {
            const x = finite(point && point.x, NaN);
            const z = finite(point && point.z, NaN);
            if (!Number.isFinite(x) || !Number.isFinite(z)) return bounds;
            bounds.minX = Math.min(bounds.minX, x);
            bounds.maxX = Math.max(bounds.maxX, x);
            bounds.minZ = Math.min(bounds.minZ, z);
            bounds.maxZ = Math.max(bounds.maxZ, z);
            return bounds;
        }, {
            minX: Infinity,
            maxX: -Infinity,
            minZ: Infinity,
            maxZ: -Infinity,
        });
        if (!Number.isFinite(result.minX)) return null;
        result.width = result.maxX - result.minX;
        result.depth = result.maxZ - result.minZ;
        result.center = {
            x: (result.minX + result.maxX) / 2,
            z: (result.minZ + result.maxZ) / 2,
        };
        return result;
    }

    function catalogRecord(catalog, placement) {
        const values = Array.isArray(catalog) ? catalog : [];
        return values.find(function (record) {
            return record && record.assetId === placement.assetId
                && (!placement.assetDefinitionRevision
                    || !record.assetDefinitionRevision
                    || record.assetDefinitionRevision
                        === placement.assetDefinitionRevision);
        }) || values.find(function (record) {
            return record && record.assetId === placement.assetId;
        }) || null;
    }

    function catalogDimensions(record, strict) {
        const source = record && typeof record === 'object' ? record : {};
        const dimensions = source.dimensions
            && typeof source.dimensions === 'object'
            ? source.dimensions
            : {};
        let width = finite(source.width, finite(dimensions.width, NaN));
        let depth = finite(source.depth, finite(dimensions.depth, NaN));
        let height = finite(source.height, finite(dimensions.height, NaN));
        const definition = source.definition
            && typeof source.definition === 'object'
            ? source.definition
            : source;
        const geometry = definition.geometry
            && typeof definition.geometry === 'object'
            ? definition.geometry
            : {};
        const aabbValue = geometry.aabb || geometry.axisAlignedBoundingBox;
        const aabb = aabbValue && typeof aabbValue === 'object'
            ? aabbValue
            : {};
        const minimum = aabb.minimum && typeof aabb.minimum === 'object'
            ? aabb.minimum
            : {};
        const maximum = aabb.maximum && typeof aabb.maximum === 'object'
            ? aabb.maximum
            : {};
        if (!(width > EPSILON)) {
            width = finite(maximum.x, NaN) - finite(minimum.x, NaN);
        }
        if (!(depth > EPSILON)) {
            depth = finite(maximum.z, NaN) - finite(minimum.z, NaN);
        }
        const interval = geometry.heightInterval
            && typeof geometry.heightInterval === 'object'
            ? geometry.heightInterval
            : {};
        if (!(height > EPSILON)) {
            height = finite(interval.maximumY, NaN)
                - finite(interval.minimumY, NaN);
        }
        if (!(height > EPSILON)) {
            height = finite(maximum.y, NaN) - finite(minimum.y, NaN);
        }
        if (strict && (!(width > EPSILON) || !(depth > EPSILON)
                || !(height > EPSILON) || ![width, depth, height].every(Number.isFinite))) {
            throw new TypeError('Published asset dimensions are unavailable');
        }
        return {
            width: width > EPSILON ? width : 1.2,
            depth: depth > EPSILON ? depth : 0.8,
            height: height > EPSILON ? height : NaN,
        };
    }

    function catalogFootprint(record) {
        const dimensions = catalogDimensions(record);
        return { width: dimensions.width, depth: dimensions.depth };
    }

    function normalizedItem(kind, value, catalog, strict) {
        if (kind === 'placement') {
            const record = catalogRecord(catalog, value) || {};
            if (strict && (!value.assetDefinitionRevision
                    || record.assetDefinitionRevision !== value.assetDefinitionRevision)) {
                throw new TypeError('Exact asset revision is unavailable');
            }
            const dimensions = catalogDimensions(record, strict);
            const transform = value.transform || {};
            const position = transform.position || {};
            const scale = Math.max(EPSILON, finite(transform.scale, 1));
            return {
                id: value.placementId,
                kind: kind,
                assetId: value.assetId,
                assetDefinitionRevision: value.assetDefinitionRevision,
                positionMode: value.positionMode || 'manual',
                position: {
                    x: finite(position.x, 0),
                    y: finite(position.y, 0),
                    z: finite(position.z, 0),
                },
                rotationDegrees: yawDegrees(transform.quaternion),
                width: dimensions.width * scale,
                depth: dimensions.depth * scale,
                height: dimensions.height * scale,
                snapRelationship: clone(value.snapRelationship || null),
                supportSurfaces: clone(
                    record.supportSurfaces
                    || (record.definition && record.definition.supportSurfaces)
                    || []
                ),
            };
        }
        if (kind === 'floor-marking') {
            const transform = value.transform || {};
            const position = transform.position || {};
            return {
                id: value.markingId,
                kind: kind,
                positionMode: value.positionMode || 'manual',
                position: {
                    x: finite(position.x, 0),
                    y: finite(position.y, 0),
                    z: finite(position.z, 0),
                },
                rotationDegrees: normalizeDegrees(transform.rotationDegrees),
                width: positive(value.width, 1, 'floor marking width'),
                depth: positive(value.depth, 1, 'floor marking depth'),
            };
        }
        const boundary = clone(value.boundary || []);
        const bounds = boundsFromPoints(boundary);
        if (!bounds) throw new TypeError("zone '" + value.zoneId + "' is invalid");
        return {
            id: value.zoneId,
            kind: 'zone',
            positionMode: 'manual',
            position: {
                x: bounds.center.x,
                y: finite(value.floorElevation, 0),
                z: bounds.center.z,
            },
            rotationDegrees: 0,
            width: Math.max(EPSILON, bounds.width),
            depth: Math.max(EPSILON, bounds.depth),
            boundary: boundary,
        };
    }

    function itemPoints(item) {
        if (item.kind === 'zone') return item.boundary;
        const halfWidth = item.width / 2;
        const halfDepth = item.depth / 2;
        return [
            { x: -halfWidth, z: -halfDepth },
            { x: halfWidth, z: -halfDepth },
            { x: halfWidth, z: halfDepth },
            { x: -halfWidth, z: halfDepth },
        ].map(function (point) {
            const rotated = rotateVector(point, item.rotationDegrees);
            return {
                x: item.position.x + rotated.x,
                z: item.position.z + rotated.z,
            };
        });
    }

    function selectionBounds(items) {
        const values = Array.isArray(items) ? items : [];
        const points = [];
        values.forEach(function (item) {
            itemPoints(item).forEach(function (point) { points.push(point); });
        });
        const result = boundsFromPoints(points);
        if (!result) throw new TypeError('pattern seed must contain at least one item');
        return result;
    }

    function orientedSelectionBounds(items, angleDegrees) {
        const values = Array.isArray(items) ? items : [];
        if (!values.length) {
            throw new TypeError('pattern seed must contain at least one item');
        }
        const axisX = rotateVector({ x: 1, z: 0 }, angleDegrees);
        const axisZ = rotateVector({ x: 0, z: 1 }, angleDegrees);
        const projected = [];
        values.forEach(function (item) {
            itemPoints(item).forEach(function (point) {
                projected.push({
                    x: point.x * axisX.x + point.z * axisX.z,
                    z: point.x * axisZ.x + point.z * axisZ.z,
                });
            });
        });
        const bounds = boundsFromPoints(projected);
        if (!bounds) {
            throw new TypeError('pattern seed has no measurable footprint');
        }
        return {
            center: {
                x: axisX.x * bounds.center.x + axisZ.x * bounds.center.z,
                z: axisX.z * bounds.center.x + axisZ.z * bounds.center.z,
            },
            width: Math.max(EPSILON, bounds.width),
            depth: Math.max(EPSILON, bounds.depth),
            axisX: axisX,
            axisZ: axisZ,
        };
    }

    function collectSelection(layout, catalog, selectedIds, options) {
        const source = layout && typeof layout === 'object' ? layout : {};
        const selection = Array.isArray(selectedIds) ? selectedIds : [];
        const settings = options || {};
        const placements = new Map((source.placements || []).map(function (item) {
            return [item.placementId, item];
        }));
        const markings = new Map((source.floorMarkings || []).map(function (item) {
            return [item.markingId, item];
        }));
        const zones = new Map((source.zones || []).map(function (item) {
            return [item.zoneId, item];
        }));
        const identifiers = [];
        const seen = new Set();
        function add(identifier) {
            if (!identifier || seen.has(identifier)) return;
            seen.add(identifier);
            identifiers.push(identifier);
        }
        selection.forEach(function (identifier) { add(cleanId(identifier)); });
        if (settings.expandZones !== false) {
            selection.forEach(function (identifier) {
                const zone = zones.get(identifier);
                if (!zone || !Array.isArray(zone.boundary)) return;
                placements.forEach(function (placement) {
                    const position = placement.transform
                        && placement.transform.position;
                    if (pointInPolygon(position, zone.boundary)) {
                        add(placement.placementId);
                    }
                });
                markings.forEach(function (marking) {
                    const position = marking.transform
                        && marking.transform.position;
                    if (pointInPolygon(position, zone.boundary)) {
                        add(marking.markingId);
                    }
                });
            });
        }
        return identifiers.map(function (identifier) {
            if (placements.has(identifier)) {
                return normalizedItem('placement', placements.get(identifier), catalog,
                    settings.strictGeometry === true);
            }
            if (markings.has(identifier)) {
                return normalizedItem(
                    'floor-marking', markings.get(identifier), catalog
                );
            }
            if (zones.has(identifier) && settings.includeZones !== false) {
                return normalizedItem('zone', zones.get(identifier), catalog);
            }
            return null;
        }).filter(Boolean);
    }

    function transformedCopy(item, sourceAnchor, targetAnchor, angleDegrees, index) {
        const position2d = transformPoint(
            item.position,
            sourceAnchor,
            targetAnchor,
            angleDegrees
        );
        const copy = {
            sourceId: item.id,
            kind: item.kind,
            instanceIndex: index,
            position: {
                x: position2d.x,
                y: item.position.y,
                z: position2d.z,
            },
            rotationDegrees: normalizeDegrees(
                item.rotationDegrees + angleDegrees
            ),
            rotationDeltaDegrees: normalizeDegrees(angleDegrees),
            sourceAnchor: clone(sourceAnchor),
            targetAnchor: clone(targetAnchor),
        };
        if (item.boundary) {
            copy.boundary = item.boundary.map(function (point) {
                return transformPoint(
                    point,
                    sourceAnchor,
                    targetAnchor,
                    angleDegrees
                );
            });
        }
        return copy;
    }

    function assertPatternCapacity(seedCount, instanceCount) {
        if (seedCount * Math.max(0, instanceCount - 1) > MAX_PATTERN_OBJECTS) {
            throw new RangeError(
                'pattern would create more than '
                + MAX_PATTERN_OBJECTS + ' layout objects'
            );
        }
    }

    function buildLinearPattern(items, options) {
        const seed = Array.isArray(items) ? items : [];
        const settings = options || {};
        const count = integer(
            settings.count, 3, 2, MAX_PATTERN_COUNT, 'pattern count'
        );
        const pitch = positive(settings.pitch, 3, 'pattern pitch');
        assertPatternCapacity(seed.length, count);
        const bounds = selectionBounds(seed);
        const angle = finite(settings.angleDegrees, 0);
        const direction = rotateVector({ x: 1, z: 0 }, angle);
        const copies = [];
        for (let instance = 1; instance < count; instance += 1) {
            const target = {
                x: bounds.center.x + direction.x * pitch * instance,
                z: bounds.center.z + direction.z * pitch * instance,
            };
            seed.forEach(function (item) {
                copies.push(transformedCopy(
                    item, bounds.center, target, 0, instance
                ));
            });
        }
        return {
            mode: 'linear',
            seedCount: seed.length,
            count: count,
            copies: copies,
            moves: [],
            guide: {
                kind: 'linear',
                start: clone(bounds.center),
                end: {
                    x: bounds.center.x + direction.x * pitch * (count - 1),
                    z: bounds.center.z + direction.z * pitch * (count - 1),
                },
                pitch: pitch,
            },
        };
    }

    function buildCircularPattern(items, options) {
        const seed = Array.isArray(items) ? items : [];
        const settings = options || {};
        const count = integer(
            settings.count, 4, 2, MAX_PATTERN_COUNT, 'pattern count'
        );
        const sweep = positive(settings.sweepDegrees, 360, 'total angle');
        if (sweep > 360 + EPSILON) {
            throw new RangeError('total angle must not exceed 360 degrees');
        }
        assertPatternCapacity(seed.length, count);
        const bounds = selectionBounds(seed);
        const center = {
            x: finite(settings.centerX, bounds.center.x - Math.max(
                bounds.width, bounds.depth, 1
            ) * 1.5),
            z: finite(settings.centerZ, bounds.center.z),
        };
        const fullCircle = Math.abs(sweep - 360) <= EPSILON;
        const step = sweep / (fullCircle ? count : count - 1);
        const copies = [];
        for (let instance = 1; instance < count; instance += 1) {
            const angle = step * instance;
            const target = transformPoint(
                bounds.center,
                center,
                center,
                angle
            );
            seed.forEach(function (item) {
                copies.push(transformedCopy(
                    item,
                    bounds.center,
                    target,
                    settings.rotateWithPattern === true ? angle : 0,
                    instance
                ));
            });
        }
        return {
            mode: 'circular',
            seedCount: seed.length,
            count: count,
            copies: copies,
            moves: [],
            guide: {
                kind: 'circular',
                center: center,
                radius: Math.hypot(
                    bounds.center.x - center.x,
                    bounds.center.z - center.z
                ),
                sweepDegrees: sweep,
                stepDegrees: step,
            },
        };
    }

    function buildVerticalStack(items, options) {
        const seed = Array.isArray(items) ? items : [];
        if (seed.length !== 1 || seed[0].kind !== 'placement') {
            throw new TypeError(
                'vertical stack requires exactly one equipment placement'
            );
        }
        const source = seed[0];
        if (source.snapRelationship
                && source.snapRelationship.family === 'vertical_stack') {
            throw new TypeError('selected equipment is already part of a stack');
        }
        const settings = options || {};
        const count = integer(
            settings.count, 3, 2, MAX_PATTERN_COUNT, 'stack count'
        );
        const gap = Math.max(0, finite(settings.gap, 0));
        const itemHeight = positive(
            source.height, NaN, 'verified equipment height'
        );
        assertPatternCapacity(1, count);
        const stackId = String(settings.stackId || (
            'stack:' + source.id + ':' + count + ':' + gap.toFixed(6)
        ));
        const relationship = function (level) {
            return {
                family: 'vertical_stack',
                stackId: stackId,
                level: level,
                count: count,
                gapMeters: gap,
                itemHeightMeters: itemHeight,
                evidenceStatus: 'unverified',
            };
        };
        const copies = [];
        for (let level = 1; level < count; level += 1) {
            const copy = transformedCopy(
                source,
                { x: source.position.x, z: source.position.z },
                { x: source.position.x, z: source.position.z },
                0,
                level
            );
            copy.position.y = source.position.y
                + level * (itemHeight + gap);
            copy.snapRelationship = relationship(level);
            copies.push(copy);
        }
        return {
            mode: 'vertical-stack',
            seedCount: 1,
            count: count,
            copies: copies,
            moves: [],
            relationships: [{
                sourceId: source.id,
                kind: 'placement',
                snapRelationship: relationship(0),
            }],
            guide: {
                kind: 'vertical-stack',
                position: clone(source.position),
                count: count,
                itemHeightMeters: itemHeight,
                gapMeters: gap,
                totalHeightMeters: itemHeight * count + gap * (count - 1),
            },
        };
    }

    function buildSurfaceStack(items, options) {
        const seed = (Array.isArray(items) ? items : []).filter(function (item) {
            return item && item.kind === 'placement';
        });
        if (seed.length < 2) {
            throw new TypeError(
                'surface stack requires one support and at least one child placement'
            );
        }
        const settings = options || {};
        const requestedSupportId = cleanId(settings.supportPlacementId);
        const support = requestedSupportId
            ? seed.find(function (item) { return item.id === requestedSupportId; })
            : seed.slice().sort(function (left, right) {
                const areaDelta = right.width * right.depth - left.width * left.depth;
                return Math.abs(areaDelta) > EPSILON
                    ? areaDelta : String(left.id).localeCompare(String(right.id));
            })[0];
        if (!support) {
            throw new TypeError('selected surface support is unavailable');
        }
        if (support.positionMode === 'locked') {
            throw new TypeError('locked equipment cannot become a surface stack support');
        }
        const children = seed.filter(function (item) {
            return item.id !== support.id;
        }).sort(function (left, right) {
            return String(left.id).localeCompare(String(right.id));
        });
        if (children.some(function (item) {
            return item.positionMode === 'locked';
        })) {
            throw new TypeError('locked equipment cannot be moved onto a support surface');
        }
        if (children.some(function (item) {
            return item.snapRelationship
                && item.snapRelationship.family === 'vertical_stack';
        })) {
            throw new TypeError('vertical stack members cannot be surface-attached');
        }
        const side = settings.side === 'below' ? 'below' : 'above';
        const gap = nonnegative(settings.gap, 0, 'surface gap');
        const itemGap = nonnegative(settings.itemGap, 0.05, 'item gap');
        const inset = nonnegative(settings.inset, 0.05, 'surface inset');
        const explicitSurface = (support.supportSurfaces || []).find(
            function (surface) {
                return surface && surface.surfaceId === settings.surfaceId;
            }
        );
        if (explicitSurface
                && Array.isArray(explicitSurface.allowedSides)
                && !explicitSurface.allowedSides.includes(side)) {
            throw new RangeError(
                "support surface does not allow placement on its '" + side + "' side"
            );
        }
        const surfaceBounds = explicitSurface && explicitSurface.bounds || {};
        const frameOrigin = explicitSurface
            && explicitSurface.localFrame
            && explicitSurface.localFrame.origin || {};
        const frameXAxis = explicitSurface
            && explicitSurface.localFrame
            && explicitSurface.localFrame.xAxis || { x: 1, y: 0, z: 0 };
        const frameZAxis = explicitSurface
            && explicitSurface.localFrame
            && explicitSurface.localFrame.zAxis || { x: 0, y: 0, z: 1 };
        const frameNormal = explicitSurface
            && explicitSurface.localFrame
            && explicitSurface.localFrame.normal || { x: 0, y: 1, z: 0 };
        if (explicitSurface) {
            const xLength = Math.hypot(
                finite(frameXAxis.x, NaN),
                finite(frameXAxis.y, NaN),
                finite(frameXAxis.z, NaN)
            );
            const zLength = Math.hypot(
                finite(frameZAxis.x, NaN),
                finite(frameZAxis.y, NaN),
                finite(frameZAxis.z, NaN)
            );
            const dot = finite(frameXAxis.x, NaN) * finite(frameZAxis.x, NaN)
                + finite(frameXAxis.z, NaN) * finite(frameZAxis.z, NaN);
            const upwardCross = finite(frameZAxis.z, NaN)
                * finite(frameXAxis.x, NaN)
                - finite(frameZAxis.x, NaN) * finite(frameXAxis.z, NaN);
            if (Math.abs(finite(frameXAxis.y, NaN)) > EPSILON
                    || Math.abs(finite(frameZAxis.y, NaN)) > EPSILON
                    || Math.abs(finite(frameNormal.x, NaN)) > EPSILON
                    || Math.abs(finite(frameNormal.z, NaN)) > EPSILON
                    || finite(frameNormal.y, NaN) < 1 - EPSILON
                    || Math.abs(xLength - 1) > EPSILON
                    || Math.abs(zLength - 1) > EPSILON
                    || Math.abs(dot) > EPSILON
                    || upwardCross < 1 - EPSILON) {
                throw new RangeError(
                    'support surface requires a horizontal orthonormal local frame'
                );
            }
        }
        const minimumX = finite(
            surfaceBounds.minimumX,
            -support.width / 2
        );
        const maximumX = finite(
            surfaceBounds.maximumX,
            support.width / 2
        );
        const minimumZ = finite(
            surfaceBounds.minimumZ,
            -support.depth / 2
        );
        const maximumZ = finite(
            surfaceBounds.maximumZ,
            support.depth / 2
        );
        const availableWidth = maximumX - minimumX - inset * 2;
        const availableDepth = maximumZ - minimumZ - inset * 2;
        if (!(availableWidth > EPSILON) || !(availableDepth > EPSILON)) {
            throw new RangeError('support surface is too small after edge inset');
        }
        const surfaceId = cleanId(settings.surfaceId)
            || (explicitSurface && cleanId(explicitSurface.surfaceId))
            || 'derived-top';
        const surfaceSource = explicitSurface ? 'asset_definition' : 'derived_aabb';
        const evidenceStatus = explicitSurface
            && cleanId(explicitSurface.evidenceStatus)
            || 'unverified';
        const attachmentId = cleanId(settings.attachmentId) || (
            'surface:' + support.id + ':' + surfaceId + ':' + side
        );
        let cursorX = minimumX + inset;
        let cursorZ = minimumZ + inset;
        let rowDepth = 0;
        const positions = [];
        children.forEach(function (child) {
            const width = positive(child.width, NaN, 'child width');
            const depth = positive(child.depth, NaN, 'child depth');
            const height = positive(child.height, NaN, 'child height');
            if (width > availableWidth + EPSILON
                    || depth > availableDepth + EPSILON) {
                throw new RangeError(
                    "'" + child.id + "' does not fit on the selected support surface"
                );
            }
            if (cursorX + width > maximumX - inset + EPSILON) {
                cursorX = minimumX + inset;
                cursorZ += rowDepth + itemGap;
                rowDepth = 0;
            }
            if (cursorZ + depth > maximumZ - inset + EPSILON) {
                throw new RangeError(
                    'selected items do not fit on the support surface; reduce the '
                    + 'selection or spacing'
                );
            }
            const surfaceLocal = {
                x: cursorX + width / 2,
                z: cursorZ + depth / 2,
            };
            positions.push({
                child: child,
                height: height,
                local: {
                    x: finite(frameOrigin.x, 0)
                        + finite(frameXAxis.x, 1) * surfaceLocal.x
                        + finite(frameZAxis.x, 0) * surfaceLocal.z,
                    z: finite(frameOrigin.z, 0)
                        + finite(frameXAxis.z, 0) * surfaceLocal.x
                        + finite(frameZAxis.z, 1) * surfaceLocal.z,
                },
            });
            cursorX += width + itemGap;
            rowDepth = Math.max(rowDepth, depth);
        });
        const surfaceElevation = explicitSurface
            ? finite(frameOrigin.y, support.height)
            : positive(support.height, NaN, 'support height');
        const supportPlane = support.position.y + surfaceElevation;
        const surfaceRotationDegrees = explicitSurface
            ? normalizeDegrees(Math.atan2(
                -finite(frameXAxis.z, 0),
                finite(frameXAxis.x, 1)
            ) * 180 / Math.PI)
            : 0;
        const moves = [];
        const relationships = [];
        positions.forEach(function (entry) {
            const rotated = rotateVector(entry.local, support.rotationDegrees);
            const childY = side === 'above'
                ? supportPlane + gap
                : supportPlane - gap - entry.height;
            const relationship = {
                family: 'surface_attachment',
                attachmentId: attachmentId,
                supportPlacementId: support.id,
                surfaceId: surfaceId,
                side: side,
                localPosition: clone(entry.local),
                localRotationDegrees: surfaceRotationDegrees,
                normalOffsetMeters: gap,
                surfaceSource: surfaceSource,
                evidenceStatus: evidenceStatus,
            };
            moves.push({
                sourceId: entry.child.id,
                kind: 'placement',
                position: {
                    x: support.position.x + rotated.x,
                    y: childY,
                    z: support.position.z + rotated.z,
                },
                rotationDegrees: normalizeDegrees(
                    support.rotationDegrees + surfaceRotationDegrees
                ),
            });
            relationships.push({
                sourceId: entry.child.id,
                kind: 'placement',
                snapRelationship: relationship,
            });
        });
        return {
            mode: 'surface-stack',
            seedCount: seed.length,
            count: children.length,
            copies: [],
            moves: moves,
            relationships: relationships,
            guide: {
                kind: 'surface-stack',
                supportPlacementId: support.id,
                attachmentId: attachmentId,
                side: side,
                surfaceId: surfaceId,
                itemCount: children.length,
                supportPosition: clone(support.position),
                supportWidth: support.width,
                supportDepth: support.depth,
            },
        };
    }

    function buildRectangularPerimeter(items, options) {
        const seed = Array.isArray(items) ? items : [];
        if (!seed.length) {
            throw new TypeError('perimeter seed must contain at least one item');
        }
        const settings = options || {};
        const square = settings.shape === 'square';
        const widthCount = integer(
            settings.widthCount, 6, 1, MAX_PATTERN_COUNT, 'width-side count'
        );
        const depthCount = square ? widthCount : integer(
            settings.depthCount, 4, 1, MAX_PATTERN_COUNT, 'depth-side count'
        );
        const clearGap = nonnegative(
            settings.clearGap, 0, 'perimeter clear gap'
        );
        const effectiveGap = clearGap > 0
            ? clearGap
            : PERIMETER_JOIN_TOLERANCE;
        const angle = finite(settings.angleDegrees, 0);
        let effectiveAngle = angle;
        let oriented = orientedSelectionBounds(seed, effectiveAngle);
        if (oriented.depth > oriented.width + EPSILON) {
            effectiveAngle += 90;
            oriented = orientedSelectionBounds(seed, effectiveAngle);
        }
        const span = oriented.width;
        const thickness = oriented.depth;
        const widthPitch = span + effectiveGap;
        const depthPitch = span + effectiveGap;
        const width = widthCount * span
            + Math.max(0, widthCount - 1) * effectiveGap;
        const depth = depthCount * span
            + Math.max(0, depthCount - 1) * effectiveGap;
        const instanceCount = 2 * (widthCount + depthCount);
        assertPatternCapacity(seed.length, instanceCount);

        function translated(point, alongX, alongZ) {
            return {
                x: point.x + oriented.axisX.x * alongX
                    + oriented.axisZ.x * alongZ,
                z: point.z + oriented.axisX.z * alongX
                    + oriented.axisZ.z * alongZ,
            };
        }

        const anchor = oriented.center;
        const leftEndpoint = translated(anchor, -span / 2, 0);
        const rightEndpoint = translated(leftEndpoint, width, 0);
        const targets = [];
        let instanceIndex = 0;
        for (let index = 0; index < widthCount; index += 1) {
            targets.push({
                anchor: translated(anchor, widthPitch * index, 0),
                rotationDeltaDegrees: 0,
                instanceIndex: instanceIndex,
                side: 'south',
                original: index === 0,
            });
            instanceIndex += 1;
        }
        for (let index = 0; index < depthCount; index += 1) {
            targets.push({
                anchor: translated(rightEndpoint,
                    thickness / 2 + effectiveGap, span / 2
                    + depthPitch * index),
                rotationDeltaDegrees: -90,
                instanceIndex: instanceIndex,
                side: 'east',
            });
            instanceIndex += 1;
        }
        for (let index = 0; index < widthCount; index += 1) {
            targets.push({
                anchor: translated(rightEndpoint, -span / 2
                    - widthPitch * index,
                depth + thickness / 2 + effectiveGap),
                rotationDeltaDegrees: 180,
                instanceIndex: instanceIndex,
                side: 'north',
            });
            instanceIndex += 1;
        }
        for (let index = 0; index < depthCount; index += 1) {
            targets.push({
                anchor: translated(leftEndpoint,
                    -thickness / 2 - effectiveGap,
                    depth - span / 2
                    - depthPitch * index),
                rotationDeltaDegrees: 90,
                instanceIndex: instanceIndex,
                side: 'west',
            });
            instanceIndex += 1;
        }

        const copies = [];
        targets.filter(function (target) {
            return target.original !== true;
        }).forEach(function (target) {
            seed.forEach(function (item) {
                const copy = transformedCopy(
                    item,
                    anchor,
                    target.anchor,
                    target.rotationDeltaDegrees,
                    target.instanceIndex
                );
                copy.perimeterSide = target.side;
                copies.push(copy);
            });
        });
        return {
            mode: 'perimeter',
            shape: square ? 'square' : 'rectangle',
            seedCount: seed.length,
            count: instanceCount,
            copies: copies,
            moves: [],
            guide: {
                kind: 'perimeter',
                points: [
                    clone(leftEndpoint),
                    clone(rightEndpoint),
                    translated(rightEndpoint, 0, depth),
                    translated(leftEndpoint, 0, depth),
                ],
                width: width,
                depth: depth,
                widthCount: widthCount,
                depthCount: depthCount,
                clearGap: clearGap,
                effectiveClearGap: effectiveGap,
                angleDegrees: effectiveAngle,
                requestedAngleDegrees: angle,
            },
        };
    }

    function buildMirror(items, options) {
        const seed = Array.isArray(items) ? items : [];
        if (!seed.length) {
            throw new TypeError('mirror seed must contain at least one item');
        }
        assertPatternCapacity(seed.length, 2);
        const settings = options || {};
        const axis = normalizedMirrorAxis(
            settings.axisStart,
            settings.axisEnd
        );
        const copies = seed.map(function (item) {
            const position2d = mirrorPoint(
                item.position,
                axis.start,
                axis.end
            );
            const rotationDegrees = mirrorRotationDegrees(
                item.rotationDegrees,
                axis.start,
                axis.end
            );
            const copy = {
                sourceId: item.id,
                kind: item.kind,
                instanceIndex: 1,
                position: {
                    x: position2d.x,
                    y: item.position.y,
                    z: position2d.z,
                },
                rotationDegrees: rotationDegrees,
                rotationDeltaDegrees: normalizeDegrees(
                    rotationDegrees - item.rotationDegrees
                ),
                mirrored: true,
                mirrorAxis: {
                    start: clone(axis.start),
                    end: clone(axis.end),
                },
            };
            if (item.boundary) {
                copy.boundary = item.boundary.map(function (point) {
                    return mirrorPoint(point, axis.start, axis.end);
                }).reverse();
            }
            return copy;
        });
        return {
            mode: 'mirror',
            seedCount: seed.length,
            count: 2,
            copies: copies,
            moves: [],
            guide: {
                kind: 'mirror',
                start: clone(axis.start),
                end: clone(axis.end),
            },
        };
    }

    function buildSwap(layout, catalog, selectedIds) {
        const identifiers = Array.from(new Set(
            (Array.isArray(selectedIds) ? selectedIds : [])
                .map(cleanId)
                .filter(Boolean)
        ));
        if (identifiers.length !== 2) {
            throw new TypeError('select exactly two objects or cell zones to swap');
        }
        const source = layout && typeof layout === 'object' ? layout : {};
        const zones = new Map((source.zones || []).map(function (zone) {
            return [zone.zoneId, zone];
        }));
        const groups = identifiers.map(function (identifier) {
            const zone = zones.get(identifier);
            const items = collectSelection(
                source,
                catalog,
                [identifier],
                {
                    expandZones: Boolean(zone),
                    includeZones: Boolean(zone),
                }
            );
            if (!items.length) {
                throw new TypeError("swap source '" + identifier + "' is invalid");
            }
            const anchorItem = zone
                ? items.find(function (item) {
                    return item.kind === 'zone' && item.id === identifier;
                })
                : items[0];
            if (!anchorItem) {
                throw new TypeError("swap source '" + identifier + "' has no anchor");
            }
            return {
                id: identifier,
                items: items,
                anchor: clone(anchorItem.position),
            };
        });
        const seen = new Set();
        groups.forEach(function (group) {
            group.items.forEach(function (item) {
                if (seen.has(item.id)) {
                    throw new Error(
                        'selected swap cells overlap or share layout objects'
                    );
                }
                seen.add(item.id);
                if (item.positionMode === 'locked') {
                    throw new Error("unlock '" + item.id + "' before swapping");
                }
            });
        });

        function translatedMove(item, sourceAnchor, targetAnchor) {
            const move = {
                sourceId: item.id,
                kind: item.kind,
                position: {
                    x: item.position.x + targetAnchor.x - sourceAnchor.x,
                    y: item.position.y,
                    z: item.position.z + targetAnchor.z - sourceAnchor.z,
                },
                rotationDegrees: item.rotationDegrees,
                sourceAnchor: clone(sourceAnchor),
                targetAnchor: clone(targetAnchor),
            };
            if (item.boundary) {
                move.boundary = item.boundary.map(function (point) {
                    return transformPoint(
                        point, sourceAnchor, targetAnchor, 0
                    );
                });
            }
            return move;
        }

        const moves = [];
        groups[0].items.forEach(function (item) {
            moves.push(translatedMove(item, groups[0].anchor, groups[1].anchor));
        });
        groups[1].items.forEach(function (item) {
            moves.push(translatedMove(item, groups[1].anchor, groups[0].anchor));
        });
        return {
            mode: 'swap',
            seedCount: moves.length,
            count: 2,
            copies: [],
            moves: moves,
            guide: {
                kind: 'swap',
                start: clone(groups[0].anchor),
                end: clone(groups[1].anchor),
                sourceIds: identifiers,
            },
        };
    }

    function pathLength(points, closed) {
        let total = 0;
        for (let index = 1; index < points.length; index += 1) {
            total += Math.hypot(
                points[index].x - points[index - 1].x,
                points[index].z - points[index - 1].z
            );
        }
        if (closed && points.length > 1) {
            total += Math.hypot(
                points[0].x - points[points.length - 1].x,
                points[0].z - points[points.length - 1].z
            );
        }
        return total;
    }

    function pointAtPathDistance(points, closed, requestedDistance) {
        const segments = [];
        for (let index = 1; index < points.length; index += 1) {
            segments.push([points[index - 1], points[index]]);
        }
        if (closed && points.length > 1) {
            segments.push([points[points.length - 1], points[0]]);
        }
        let remaining = Math.max(0, requestedDistance);
        for (let index = 0; index < segments.length; index += 1) {
            const start = segments[index][0];
            const end = segments[index][1];
            const length = Math.hypot(end.x - start.x, end.z - start.z);
            if (remaining <= length || index === segments.length - 1) {
                const ratio = length > EPSILON
                    ? Math.min(1, remaining / length) : 0;
                return {
                    point: {
                        x: start.x + (end.x - start.x) * ratio,
                        z: start.z + (end.z - start.z) * ratio,
                    },
                    tangent: {
                        x: end.x - start.x,
                        z: end.z - start.z,
                    },
                };
            }
            remaining -= length;
        }
        return {
            point: clone(points[0] || { x: 0, z: 0 }),
            tangent: { x: 1, z: 0 },
        };
    }

    function pathSamples(points, count, closed) {
        if (count === 1) {
            return [{
                point: clone(points[0] || { x: 0, z: 0 }),
                tangent: points.length > 1 ? {
                    x: points[1].x - points[0].x,
                    z: points[1].z - points[0].z,
                } : { x: 1, z: 0 },
            }];
        }
        const total = pathLength(points, closed);
        const divisor = closed ? count : count - 1;
        return Array.from({ length: count }, function (_, index) {
            return pointAtPathDistance(
                points,
                closed,
                total * index / divisor
            );
        });
    }

    function cellPath(shape, count, width, depth, rows) {
        const halfWidth = width / 2;
        const halfDepth = depth / 2;
        if (shape === 'line' || shape === 'herringbone') {
            return {
                points: [
                    { x: -halfWidth, z: 0 },
                    { x: halfWidth, z: 0 },
                ],
                closed: false,
            };
        }
        if (shape === 'l') {
            return {
                points: [
                    { x: -halfWidth, z: -halfDepth },
                    { x: -halfWidth, z: halfDepth },
                    { x: halfWidth, z: halfDepth },
                ],
                closed: false,
            };
        }
        if (shape === 'u') {
            return {
                points: [
                    { x: -halfWidth, z: -halfDepth },
                    { x: -halfWidth, z: halfDepth },
                    { x: halfWidth, z: halfDepth },
                    { x: halfWidth, z: -halfDepth },
                ],
                closed: false,
            };
        }
        if (shape === 'loop') {
            return {
                points: [
                    { x: -halfWidth, z: -halfDepth },
                    { x: -halfWidth, z: halfDepth },
                    { x: halfWidth, z: halfDepth },
                    { x: halfWidth, z: -halfDepth },
                ],
                closed: true,
            };
        }
        if (shape === 'cluster') {
            return {
                points: Array.from({ length: Math.max(3, count) }, function (_, index) {
                    const angle = index * Math.PI * 2 / Math.max(3, count);
                    return {
                        x: Math.cos(angle) * halfWidth,
                        z: Math.sin(angle) * halfDepth,
                    };
                }),
                closed: true,
            };
        }
        if (shape === 'spine') {
            const points = [];
            for (let index = 0; index < count; index += 1) {
                const ratio = count > 1 ? index / (count - 1) : 0.5;
                points.push({
                    x: -halfWidth + width * ratio,
                    z: index % 2 ? halfDepth : -halfDepth,
                });
            }
            return { direct: points };
        }
        const rowCount = Math.max(2, Math.min(count, rows));
        const columnCount = Math.ceil(count / rowCount);
        const points = [];
        for (let row = 0; row < rowCount; row += 1) {
            const z = rowCount > 1
                ? halfDepth - depth * row / (rowCount - 1) : 0;
            for (let column = 0; column < columnCount; column += 1) {
                const logicalColumn = shape === 'serpentine' && row % 2
                    ? columnCount - 1 - column : column;
                const x = columnCount > 1
                    ? -halfWidth + width * logicalColumn / (columnCount - 1) : 0;
                points.push({ x: x, z: z });
                if (points.length === count) break;
            }
            if (points.length === count) break;
        }
        return { direct: points };
    }

    function tangentHeading(tangent) {
        return normalizeDegrees(Math.atan2(
            finite(tangent && tangent.x, 0),
            finite(tangent && tangent.z, 1)
        ) * 180 / Math.PI);
    }

    function buildCellLayout(items, options) {
        const seed = (Array.isArray(items) ? items : []).filter(function (item) {
            return item.kind !== 'zone';
        });
        if (seed.length < 2) {
            throw new TypeError('select at least two cell items to arrange');
        }
        const locked = seed.find(function (item) {
            return item.positionMode === 'locked';
        });
        if (locked) {
            throw new Error("unlock '" + locked.id + "' before arranging the cell");
        }
        const settings = options || {};
        const shape = CELL_SHAPES.includes(settings.shape)
            ? settings.shape : 'u';
        const bounds = selectionBounds(seed);
        const maxWidth = Math.max.apply(null, seed.map(function (item) {
            return item.width;
        }));
        const maxDepth = Math.max.apply(null, seed.map(function (item) {
            return item.depth;
        }));
        const maxFootprintRadius = Math.max.apply(null, seed.map(function (item) {
            return Math.hypot(item.width, item.depth) / 2;
        }));
        const gap = Math.max(0, finite(settings.gap, 1));
        const pitch = Math.max(maxWidth, maxDepth) + gap;
        const width = positive(
            settings.width,
            Math.max(bounds.width, pitch * Math.max(2, Math.ceil(seed.length / 2))),
            'cell width'
        );
        const depth = positive(
            settings.depth,
            Math.max(bounds.depth, pitch * 2),
            'cell depth'
        );
        const rows = integer(
            settings.rows,
            shape === 'parallel' ? 2 : Math.max(2, Math.round(Math.sqrt(seed.length))),
            1,
            Math.max(1, seed.length),
            'row count'
        );
        const boundaryInset = maxFootprintRadius + gap / 2;
        const usableWidth = width - boundaryInset * 2;
        const usableDepth = depth - boundaryInset * 2;
        if (!(usableWidth > EPSILON) || !(usableDepth > EPSILON)) {
            throw new RangeError(
                'cell width and depth must contain the selected equipment '
                + 'footprints and preferred clear gap'
            );
        }
        const path = cellPath(
            shape,
            seed.length,
            usableWidth,
            usableDepth,
            rows
        );
        let samples = path.direct
            ? path.direct.map(function (point, index) {
                const previous = path.direct[Math.max(0, index - 1)];
                const next = path.direct[Math.min(path.direct.length - 1, index + 1)];
                return {
                    point: point,
                    tangent: {
                        x: next.x - previous.x,
                        z: next.z - previous.z,
                    },
                };
            })
            : pathSamples(path.points, seed.length, path.closed);
        const inverted = shape === 'u' && settings.invertU === true;
        if (inverted) {
            samples = samples.map(function (sample) {
                return {
                    point: {
                        x: sample.point.x,
                        z: -sample.point.z,
                    },
                    tangent: {
                        x: sample.tangent.x,
                        z: -sample.tangent.z,
                    },
                };
            });
        }
        const layoutAngle = finite(settings.angleDegrees, 0);
        const orientation = [
            'preserve', 'follow-path', 'face-center', 'face-outward',
        ].includes(settings.orientation) ? settings.orientation : 'preserve';
        const moves = seed.map(function (item, index) {
            const sample = samples[index];
            const offset = rotateVector(sample.point, layoutAngle);
            let rotation = item.rotationDegrees;
            if (orientation === 'follow-path') {
                rotation = tangentHeading(rotateVector(
                    sample.tangent, layoutAngle
                ));
            } else if (orientation === 'face-center'
                    || orientation === 'face-outward') {
                rotation = tangentHeading({
                    x: -offset.x,
                    z: -offset.z,
                });
                if (orientation === 'face-outward') rotation += 180;
            }
            if (shape === 'herringbone') {
                rotation = normalizeDegrees(
                    layoutAngle + (index % 2 ? -35 : 35)
                );
            }
            return {
                sourceId: item.id,
                kind: item.kind,
                position: {
                    x: bounds.center.x + offset.x,
                    y: item.position.y,
                    z: bounds.center.z + offset.z,
                },
                rotationDegrees: normalizeDegrees(rotation),
            };
        });
        return {
            mode: 'cell-layout',
            shape: shape,
            inverted: inverted,
            seedCount: seed.length,
            count: seed.length,
            copies: [],
            moves: moves,
            guide: {
                kind: 'cell-layout',
                shape: shape,
                center: clone(bounds.center),
                width: width,
                depth: depth,
                boundaryInset: boundaryInset,
                usableWidth: usableWidth,
                usableDepth: usableDepth,
                angleDegrees: layoutAngle,
                inverted: inverted,
            },
        };
    }

    return Object.freeze({
        apiVersion: API_VERSION,
        cellShapes: CELL_SHAPES,
        collectSelection: collectSelection,
        selectionBounds: selectionBounds,
        pointInPolygon: pointInPolygon,
        transformPoint: transformPoint,
        mirrorPoint: mirrorPoint,
        mirrorVector: mirrorVector,
        mirrorRotationDegrees: mirrorRotationDegrees,
        buildLinearPattern: buildLinearPattern,
        buildCircularPattern: buildCircularPattern,
        buildVerticalStack: buildVerticalStack,
        buildSurfaceStack: buildSurfaceStack,
        buildRectangularPerimeter: buildRectangularPerimeter,
        buildMirror: buildMirror,
        buildSwap: buildSwap,
        buildCellLayout: buildCellLayout,
    });
}));
