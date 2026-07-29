(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) {
        root.InspectorProFacilitySpatialWorker = api;
        if (!root.document
                && typeof root.addEventListener === 'function'
                && typeof root.postMessage === 'function') {
            api.installWorkerRuntime(root);
        }
    }
}(typeof self !== 'undefined'
    ? self
    : (typeof globalThis !== 'undefined' ? globalThis : this), function () {
    'use strict';

    const API_VERSION = 1;
    const ADVISORY_VERSION = 1;
    const DEFAULT_FOOTPRINT = Object.freeze([
        Object.freeze({ x: -0.6, z: -0.4 }),
        Object.freeze({ x: 0.6, z: -0.4 }),
        Object.freeze({ x: 0.6, z: 0.4 }),
        Object.freeze({ x: -0.6, z: 0.4 }),
    ]);
    const EPSILON = 1e-9;

    function clone(value) {
        if (value === undefined) return undefined;
        return JSON.parse(JSON.stringify(value));
    }

    function finite(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function cleanString(value, fallback) {
        return typeof value === 'string' && value.trim()
            ? value.trim()
            : fallback;
    }

    function point(value) {
        if (!value || !Number.isFinite(Number(value.x))
                || !Number.isFinite(Number(value.z))) return null;
        return { x: Number(value.x), z: Number(value.z) };
    }

    function pointList(value) {
        if (!Array.isArray(value) || value.length < 3) return null;
        const result = value.map(point);
        return result.every(Boolean) ? result : null;
    }

    function rectangle(width, depth) {
        const safeWidth = finite(width, 1.2);
        const safeDepth = finite(depth, 0.8);
        return [
            { x: -safeWidth / 2, z: -safeDepth / 2 },
            { x: safeWidth / 2, z: -safeDepth / 2 },
            { x: safeWidth / 2, z: safeDepth / 2 },
            { x: -safeWidth / 2, z: safeDepth / 2 },
        ];
    }

    function definitionFromRecord(record) {
        if (!record || typeof record !== 'object' || Array.isArray(record)) {
            return {};
        }
        return record.definition
            || record.assetDefinition
            || record.document
            || record;
    }

    function field(record, name) {
        const definition = definitionFromRecord(record);
        if (record && record[name] !== undefined) return record[name];
        if (definition[name] !== undefined) return definition[name];
        if (definition.identity && definition.identity[name] !== undefined) {
            return definition.identity[name];
        }
        return undefined;
    }

    function footprintFromValue(value) {
        const direct = pointList(value);
        if (direct) return direct;
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            return null;
        }
        const named = pointList(value.footprint)
            || pointList(value.footprintPolygon)
            || pointList(value.points);
        if (named) return named;
        const polygons = value.footprintPolygons
            || (value.geometry && value.geometry.footprintPolygons);
        if (Array.isArray(polygons) && polygons.length) {
            const first = pointList(polygons[0]);
            if (first) return first;
        }
        if (Number.isFinite(Number(value.width))
                || Number.isFinite(Number(value.depth))) {
            return rectangle(value.width, value.depth);
        }
        if (value.size && (Number.isFinite(Number(value.size.x))
                || Number.isFinite(Number(value.size.z)))) {
            return rectangle(value.size.x, value.size.z);
        }
        if (value.min && value.max
                && Number.isFinite(Number(value.min.x))
                && Number.isFinite(Number(value.max.x))
                && Number.isFinite(Number(value.min.z))
                && Number.isFinite(Number(value.max.z))) {
            return [
                { x: Number(value.min.x), z: Number(value.min.z) },
                { x: Number(value.max.x), z: Number(value.min.z) },
                { x: Number(value.max.x), z: Number(value.max.z) },
                { x: Number(value.min.x), z: Number(value.max.z) },
            ];
        }
        return null;
    }

    function catalogRecords(value) {
        if (Array.isArray(value)) return value;
        if (!value || typeof value !== 'object') return [];
        if (Array.isArray(value.entries)) return value.entries;
        if (Array.isArray(value.assets)) return value.assets;
        return Object.keys(value).sort().map(function (key) {
            const record = value[key];
            return record && typeof record === 'object'
                ? Object.assign({ assetId: key }, record)
                : null;
        }).filter(Boolean);
    }

    function catalogLookup(catalog, assetId, revision) {
        return catalogRecords(catalog).find(function (record) {
            const recordId = cleanString(field(record, 'assetId'), '');
            const recordRevision = cleanString(
                field(record, 'assetDefinitionRevision')
                || field(record, 'publishedAssetDefinitionRevision')
                || field(record, 'definitionRevision'),
                ''
            );
            return recordId === assetId
                && (!recordRevision || !revision || recordRevision === revision);
        }) || null;
    }

    function localFootprint(placement, catalog) {
        const record = catalogLookup(
            catalog,
            cleanString(placement && placement.assetId, ''),
            cleanString(placement && placement.assetDefinitionRevision, '')
        );
        const definition = definitionFromRecord(record);
        return footprintFromValue(record)
            || footprintFromValue(definition)
            || footprintFromValue(definition.geometry)
            || footprintFromValue(
                definition.geometry && definition.geometry.aabb
            )
            || footprintFromValue(placement && placement.footprint)
            || footprintFromValue(placement && placement.bounds)
            || footprintFromValue(placement && placement.metadata)
            || DEFAULT_FOOTPRINT.map(point);
    }

    function rotate(value, quaternion) {
        const q = quaternion || {};
        const qx = finite(q.x, 0);
        const qy = finite(q.y, 0);
        const qz = finite(q.z, 0);
        const qw = finite(q.w, 1);
        const ix = qw * value.x + qy * value.z;
        const iy = qz * value.x - qx * value.z;
        const iz = qw * value.z + qx * 0 - qy * value.x;
        const iw = -qx * value.x - qz * value.z;
        return {
            x: ix * qw + iw * -qx + iy * -qz - iz * -qy,
            z: iz * qw + iw * -qz + ix * -qy - iy * -qx,
        };
    }

    function worldFootprint(placement, catalog) {
        const transform = placement && placement.transform || {};
        const position = transform.position
            || placement.worldPosition
            || placement.position
            || {};
        const scale = finite(transform.scale, finite(placement.scale, 1));
        return localFootprint(placement, catalog).map(function (local) {
            const turned = rotate({
                x: local.x * scale,
                z: local.z * scale,
            }, transform.quaternion || placement.quaternion);
            return {
                x: finite(position.x, 0) + turned.x,
                z: finite(position.z, 0) + turned.z,
            };
        });
    }

    function bounds(points) {
        return points.reduce(function (result, value) {
            result.minX = Math.min(result.minX, value.x);
            result.maxX = Math.max(result.maxX, value.x);
            result.minZ = Math.min(result.minZ, value.z);
            result.maxZ = Math.max(result.maxZ, value.z);
            return result;
        }, {
            minX: Infinity,
            maxX: -Infinity,
            minZ: Infinity,
            maxZ: -Infinity,
        });
    }

    function boundsOverlap(left, right) {
        return left.minX < right.maxX - EPSILON
            && left.maxX > right.minX + EPSILON
            && left.minZ < right.maxZ - EPSILON
            && left.maxZ > right.minZ + EPSILON;
    }

    function pointOnSegment(candidate, start, end) {
        const cross = (candidate.z - start.z) * (end.x - start.x)
            - (candidate.x - start.x) * (end.z - start.z);
        if (Math.abs(cross) > EPSILON) return false;
        return candidate.x >= Math.min(start.x, end.x) - EPSILON
            && candidate.x <= Math.max(start.x, end.x) + EPSILON
            && candidate.z >= Math.min(start.z, end.z) - EPSILON
            && candidate.z <= Math.max(start.z, end.z) + EPSILON;
    }

    function pointInPolygon(candidate, polygon) {
        let inside = false;
        for (let index = 0, previous = polygon.length - 1;
                index < polygon.length;
                previous = index, index += 1) {
            const start = polygon[previous];
            const end = polygon[index];
            if (pointOnSegment(candidate, start, end)) return true;
            const intersects = ((end.z > candidate.z) !== (start.z > candidate.z))
                && candidate.x < (
                    (start.x - end.x) * (candidate.z - end.z)
                    / (start.z - end.z) + end.x
                );
            if (intersects) inside = !inside;
        }
        return inside;
    }

    function categoryForAsset(catalog, assetId, revision) {
        const record = catalogLookup(catalog, assetId, revision);
        return cleanString(
            field(record, 'category')
            || field(record, 'assetClass')
            || field(record, 'assetType'),
            ''
        );
    }

    function zoneContains(zone, footprint) {
        const polygon = pointList(zone && zone.boundary);
        return polygon && footprint.every(function (value) {
            return pointInPolygon(value, polygon);
        });
    }

    function zoneAllows(zone, category) {
        const allowed = zone && zone.allowedAssetCategories;
        return !Array.isArray(allowed)
            || !allowed.length
            || allowed.includes(category);
    }

    function evaluateAdvisory(input) {
        const payload = input || {};
        const layout = payload.layout || {};
        const placements = Array.isArray(layout.placements)
            ? layout.placements : [];
        const zones = Array.isArray(layout.zones) ? layout.zones : [];
        const catalog = payload.assetCatalog || [];
        const ghost = payload.ghost || payload.placement || {};
        const position = ghost.worldPosition
            || ghost.position
            || (ghost.transform && ghost.transform.position);
        if (!position || !Number.isFinite(Number(position.x))
                || !Number.isFinite(Number(position.z))) {
            throw new TypeError('advisory ghost requires a finite world position');
        }
        const candidate = {
            assetId: cleanString(ghost.assetId, ''),
            assetDefinitionRevision: cleanString(
                ghost.assetDefinitionRevision,
                ''
            ),
            transform: {
                position: {
                    x: Number(position.x),
                    y: finite(position.y, 0),
                    z: Number(position.z),
                },
                quaternion: clone(
                    ghost.quaternion
                    || (ghost.transform && ghost.transform.quaternion)
                    || { x: 0, y: 0, z: 0, w: 1 }
                ),
                scale: finite(
                    ghost.scale,
                    finite(ghost.transform && ghost.transform.scale, 1)
                ),
            },
            footprint: clone(ghost.footprint),
            bounds: clone(ghost.bounds),
            metadata: clone(ghost.metadata || {}),
        };
        const footprint = worldFootprint(candidate, catalog);
        const candidateBounds = bounds(footprint);
        const targetPlacementId = cleanString(payload.targetPlacementId, '');
        const overlapPlacementIds = placements.filter(function (placement) {
            return placement
                && placement.placementId !== targetPlacementId
                && boundsOverlap(
                    candidateBounds,
                    bounds(worldFootprint(placement, catalog))
                );
        }).map(function (placement) {
            return placement.placementId;
        }).filter(Boolean).sort();
        const category = categoryForAsset(
            catalog,
            candidate.assetId,
            candidate.assetDefinitionRevision
        );
        const containingZoneIds = zones.filter(function (zone) {
            return zoneContains(zone, footprint);
        }).map(function (zone) {
            return zone.zoneId;
        }).filter(Boolean).sort();
        const compatibleZoneIds = zones.filter(function (zone) {
            return containingZoneIds.includes(zone.zoneId)
                && zoneAllows(zone, category);
        }).map(function (zone) {
            return zone.zoneId;
        }).filter(Boolean).sort();
        const findings = [];
        if (overlapPlacementIds.length) {
            findings.push({
                code: 'coarse_overlap',
                level: 'attention',
                subjectRefs: overlapPlacementIds,
                message: 'Possible overlap with '
                    + overlapPlacementIds.length + ' placed object'
                    + (overlapPlacementIds.length === 1 ? '.' : 's.'),
            });
        }
        if (zones.length && !containingZoneIds.length) {
            findings.push({
                code: 'outside_authored_zones',
                level: 'attention',
                subjectRefs: [],
                message: 'The footprint is not fully inside an authored zone.',
            });
        } else if (containingZoneIds.length && !compatibleZoneIds.length) {
            findings.push({
                code: 'zone_category_mismatch',
                level: 'attention',
                subjectRefs: containingZoneIds,
                message: 'The containing zone may not allow this asset category.',
            });
        }
        const status = findings.length ? 'attention' : 'clear';
        return {
            advisoryVersion: ADVISORY_VERSION,
            authority: 'browser-advisory',
            authoritative: false,
            status: status,
            requestedPosition: clone(candidate.transform.position),
            candidateBounds: candidateBounds,
            overlapPlacementIds: overlapPlacementIds,
            containingZoneIds: containingZoneIds,
            compatibleZoneIds: compatibleZoneIds,
            findings: findings,
            summary: findings.length
                ? findings.map(function (finding) {
                    return finding.message;
                }).join(' ')
                : (
                    compatibleZoneIds.length
                        ? 'Coarse check clear inside '
                            + compatibleZoneIds.length + ' compatible zone'
                            + (compatibleZoneIds.length === 1 ? '.' : 's.')
                        : 'Coarse overlap check clear.'
                ),
        };
    }

    function installWorkerRuntime(scope, inputOptions) {
        const options = inputOptions || {};
        const schedule = typeof options.schedule === 'function'
            ? options.schedule
            : function (callback) { return setTimeout(callback, 0); };
        const canceled = new Set();
        let latestRequestId = null;

        function post(message) {
            scope.postMessage(clone(message));
        }

        function handleMessage(event) {
            const message = event && event.data || event || {};
            const requestId = cleanString(message.requestId, '');
            if (message.type === 'cancel') {
                if (requestId) canceled.add(requestId);
                if (latestRequestId === requestId) latestRequestId = null;
                return;
            }
            if (message.type !== 'analyze' || !requestId) return;
            if (latestRequestId && latestRequestId !== requestId) {
                canceled.add(latestRequestId);
            }
            latestRequestId = requestId;
            schedule(function () {
                if (canceled.has(requestId) || latestRequestId !== requestId) {
                    canceled.delete(requestId);
                    return;
                }
                try {
                    post({
                        type: 'advisory-result',
                        requestId: requestId,
                        advisory: evaluateAdvisory(message.payload),
                    });
                } catch (error) {
                    post({
                        type: 'advisory-error',
                        requestId: requestId,
                        error: {
                            code: 'facility_spatial_advisory_failed',
                            message: error && error.message
                                ? error.message
                                : 'Spatial advisory failed.',
                        },
                    });
                }
            });
        }

        scope.addEventListener('message', handleMessage);
        return function () {
            scope.removeEventListener('message', handleMessage);
            canceled.clear();
            latestRequestId = null;
        };
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        ADVISORY_VERSION: ADVISORY_VERSION,
        evaluateAdvisory: evaluateAdvisory,
        installWorkerRuntime: installWorkerRuntime,
    });
}));
