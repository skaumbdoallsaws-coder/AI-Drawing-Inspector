/**
 * Facility Layout structure derivation.
 *
 * Zone membership is not stored anywhere in a layout: a placement carries no
 * zoneId and a zone carries no placement list. The relationship exists only as
 * geometry, so this module derives it, and it is the only place containment is
 * decided.
 *
 * Pure by construction - no DOM, no session, no state. The tree renderer
 * consumes the result; it does not re-decide any of this.
 *
 * Rules are fixed by section 3.2a of docs/facility-layout-structure-tree-plan.md:
 *   1. zone parenting is whole-polygon, strictly greater area
 *   2. placement containment is by origin, boundary inclusive
 *   3. resolution is smallest area first, then zoneId ascending
 *   4. overlapping non-nesting zones resolve by rule 3; a placement appears once
 *   5. invalid geometry reports on its own row and contributes no containment
 */
(function (root, factory) {
    'use strict';

    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityStructure = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const API_VERSION = 1;

    /** Scope used for placements that fall in no zone. Deliberately not a null
     *  zoneId, so unzoned groups stay addressable and cannot collide with a
     *  zone that is missing an ID. */
    const UNZONED_SCOPE = 'unzoned';

    function finite(value, fallback) {
        const number = typeof value === 'number' ? value : Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function text(value) {
        return typeof value === 'string' ? value : '';
    }

    /**
     * Ring geometry with a cached bounding box and signed area.
     * Returns null when the ring cannot be evaluated, which rule 5 treats as
     * invalid geometry rather than as an error.
     */
    function ringOf(boundary) {
        if (!Array.isArray(boundary) || boundary.length < 3) return null;
        const points = [];
        let minX = Infinity;
        let maxX = -Infinity;
        let minZ = Infinity;
        let maxZ = -Infinity;
        for (let index = 0; index < boundary.length; index += 1) {
            const raw = boundary[index];
            if (!raw || typeof raw !== 'object') return null;
            const x = finite(raw.x, NaN);
            const z = finite(raw.z, NaN);
            if (!Number.isFinite(x) || !Number.isFinite(z)) return null;
            points.push({ x: x, z: z });
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (z < minZ) minZ = z;
            if (z > maxZ) maxZ = z;
        }
        // Shoelace. Absolute value: winding order is not our concern here.
        let twiceArea = 0;
        for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
            twiceArea += (points[j].x * points[i].z) - (points[i].x * points[j].z);
        }
        const area = Math.abs(twiceArea) / 2;
        if (!Number.isFinite(area) || area <= 0) return null;
        return {
            points: points,
            area: area,
            minX: minX, maxX: maxX, minZ: minZ, maxZ: maxZ,
        };
    }

    function inBounds(ring, x, z) {
        return x >= ring.minX && x <= ring.maxX && z >= ring.minZ && z <= ring.maxZ;
    }

    /** True when the point lies on a ring edge, within tolerance. Rule 2 makes
     *  the boundary inclusive, matching shapely's covers(). */
    function onEdge(ring, x, z, tolerance) {
        const points = ring.points;
        for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
            const ax = points[j].x;
            const az = points[j].z;
            const bx = points[i].x;
            const bz = points[i].z;
            const dx = bx - ax;
            const dz = bz - az;
            const lengthSquared = (dx * dx) + (dz * dz);
            let t = lengthSquared > 0
                ? (((x - ax) * dx) + ((z - az) * dz)) / lengthSquared
                : 0;
            if (t < 0) t = 0;
            if (t > 1) t = 1;
            const px = ax + (t * dx);
            const pz = az + (t * dz);
            const ox = x - px;
            const oz = z - pz;
            if (((ox * ox) + (oz * oz)) <= (tolerance * tolerance)) return true;
        }
        return false;
    }

    /** Ray casting, with the boundary treated as inside per rule 2. */
    function ringCovers(ring, x, z, tolerance) {
        if (!inBounds(ring, x, z)) {
            // A point outside the bounding box can still be within tolerance of
            // an edge that touches it, so only reject when clearly outside.
            if (x < ring.minX - tolerance || x > ring.maxX + tolerance
                || z < ring.minZ - tolerance || z > ring.maxZ + tolerance) {
                return false;
            }
        }
        if (onEdge(ring, x, z, tolerance)) return true;
        const points = ring.points;
        let inside = false;
        for (let i = 0, j = points.length - 1; i < points.length; j = i, i += 1) {
            const xi = points[i].x;
            const zi = points[i].z;
            const xj = points[j].x;
            const zj = points[j].z;
            if (((zi > z) !== (zj > z))
                && (x < (((xj - xi) * (z - zi)) / (zj - zi)) + xi)) {
                inside = !inside;
            }
        }
        return inside;
    }

    /** Rule 1: A covers every vertex of B, and A is strictly larger. */
    function ringContainsRing(outer, inner, tolerance) {
        if (!(outer.area > inner.area)) return false;
        if (inner.minX < outer.minX - tolerance || inner.maxX > outer.maxX + tolerance
            || inner.minZ < outer.minZ - tolerance || inner.maxZ > outer.maxZ + tolerance) {
            return false;
        }
        for (let index = 0; index < inner.points.length; index += 1) {
            const point = inner.points[index];
            if (!ringCovers(outer, point.x, point.z, tolerance)) return false;
        }
        return true;
    }

    /**
     * Rule 3, in one place so parenting and placement assignment cannot drift:
     * smallest area first, then zoneId ascending. Independent of input order.
     */
    function betterParent(candidate, current) {
        if (!current) return true;
        if (candidate.ring.area !== current.ring.area) {
            return candidate.ring.area < current.ring.area;
        }
        return candidate.zoneId < current.zoneId;
    }

    function groupKey(scopeId, assetId, assetRevision) {
        // Parent scope is part of the identity: the same asset appears in many
        // zones, so asset identity alone collides across them.
        return scopeId + '\u0000' + assetId + '\u0000' + assetRevision;
    }

    function emptyGroupBucket(scopeId, placement) {
        return {
            rowId: groupKey(
                scopeId,
                text(placement.assetId),
                text(placement.assetDefinitionRevision)
            ),
            kind: 'group',
            scopeId: scopeId,
            assetId: text(placement.assetId),
            assetDefinitionRevision: text(placement.assetDefinitionRevision),
            placementIds: [],
        };
    }

    /**
     * Build the group rows for one scope, preserving first-seen order so the
     * result does not depend on object key order.
     */
    function groupsFor(scopeId, placements) {
        const order = [];
        const byKey = Object.create(null);
        for (let index = 0; index < placements.length; index += 1) {
            const placement = placements[index];
            const key = groupKey(
                scopeId,
                text(placement.assetId),
                text(placement.assetDefinitionRevision)
            );
            let bucket = byKey[key];
            if (!bucket) {
                bucket = emptyGroupBucket(scopeId, placement);
                byKey[key] = bucket;
                order.push(bucket);
            }
            bucket.placementIds.push(text(placement.placementId));
        }
        return order;
    }

    /**
     * Derive the structure of one layout.
     *
     * @param {object} layout           a layout document
     * @param {object} [options]
     * @param {number} [options.tolerance]  boundary tolerance in metres
     * @returns {object} { roots, zones, unzoned, counts, invalidZoneIds }
     */
    function deriveStructure(layout, options) {
        const settings = options || {};
        const tolerance = finite(settings.tolerance, 1e-9);
        const source = layout && typeof layout === 'object' ? layout : {};
        const rawZones = Array.isArray(source.zones) ? source.zones : [];
        const rawPlacements = Array.isArray(source.placements) ? source.placements : [];

        const nodes = [];
        const invalidZoneIds = [];
        for (let index = 0; index < rawZones.length; index += 1) {
            const zone = rawZones[index];
            if (!zone || typeof zone !== 'object') continue;
            const zoneId = text(zone.zoneId);
            if (!zoneId) continue;
            const ring = ringOf(zone.boundary);
            if (!ring) {
                // Rule 5: reported, not thrown, and contributes no containment.
                invalidZoneIds.push(zoneId);
                nodes.push({
                    rowId: zoneId,
                    kind: 'zone',
                    zoneId: zoneId,
                    label: text(zone.label) || zoneId,
                    zoneType: text(zone.zoneType),
                    ring: null,
                    geometryValid: false,
                    parentZoneId: null,
                    childZoneIds: [],
                    groups: [],
                    directCount: 0,
                    totalCount: 0,
                });
                continue;
            }
            nodes.push({
                rowId: zoneId,
                kind: 'zone',
                zoneId: zoneId,
                label: text(zone.label) || zoneId,
                zoneType: text(zone.zoneType),
                ring: ring,
                geometryValid: true,
                parentZoneId: null,
                childZoneIds: [],
                groups: [],
                directCount: 0,
                totalCount: 0,
            });
        }

        const byId = Object.create(null);
        for (let index = 0; index < nodes.length; index += 1) {
            byId[nodes[index].zoneId] = nodes[index];
        }
        const usable = nodes.filter(function (node) { return node.geometryValid; });

        // Parenting, rule 1 resolved by rule 3.
        for (let i = 0; i < usable.length; i += 1) {
            const child = usable[i];
            let chosen = null;
            for (let j = 0; j < usable.length; j += 1) {
                const parent = usable[j];
                if (parent === child) continue;
                if (!ringContainsRing(parent.ring, child.ring, tolerance)) continue;
                if (betterParent(parent, chosen)) chosen = parent;
            }
            child.parentZoneId = chosen ? chosen.zoneId : null;
        }
        for (let i = 0; i < usable.length; i += 1) {
            const node = usable[i];
            if (node.parentZoneId) byId[node.parentZoneId].childZoneIds.push(node.zoneId);
        }

        // Placement assignment, rule 2 resolved by rule 3.
        const perZone = Object.create(null);
        const unzonedPlacements = [];
        for (let index = 0; index < rawPlacements.length; index += 1) {
            const placement = rawPlacements[index];
            if (!placement || typeof placement !== 'object') continue;
            const transform = placement.transform || {};
            const position = transform.position || {};
            const x = finite(position.x, NaN);
            const z = finite(position.z, NaN);
            let chosen = null;
            if (Number.isFinite(x) && Number.isFinite(z)) {
                for (let j = 0; j < usable.length; j += 1) {
                    const node = usable[j];
                    // Bounding-box prefilter. Cheap reject only; a concave
                    // polygon still gets the full test below.
                    if (x < node.ring.minX - tolerance || x > node.ring.maxX + tolerance
                        || z < node.ring.minZ - tolerance || z > node.ring.maxZ + tolerance) {
                        continue;
                    }
                    if (!ringCovers(node.ring, x, z, tolerance)) continue;
                    if (betterParent(node, chosen)) chosen = node;
                }
            }
            if (chosen) {
                if (!perZone[chosen.zoneId]) perZone[chosen.zoneId] = [];
                perZone[chosen.zoneId].push(placement);
            } else {
                unzonedPlacements.push(placement);
            }
        }

        for (let index = 0; index < nodes.length; index += 1) {
            const node = nodes[index];
            const held = perZone[node.zoneId] || [];
            node.groups = groupsFor(node.zoneId, held);
            node.directCount = held.length;
        }

        // Totals, deepest first, so a parent can add what its children already know.
        const depthOf = Object.create(null);
        function depth(zoneId, guard) {
            if (depthOf[zoneId] !== undefined) return depthOf[zoneId];
            const node = byId[zoneId];
            const parent = node && node.parentZoneId;
            const value = (!parent || guard > nodes.length) ? 0 : depth(parent, guard + 1) + 1;
            depthOf[zoneId] = value;
            return value;
        }
        const ordered = nodes.slice().sort(function (a, b) {
            return depth(b.zoneId, 0) - depth(a.zoneId, 0);
        });
        for (let index = 0; index < ordered.length; index += 1) {
            const node = ordered[index];
            let total = node.directCount;
            for (let c = 0; c < node.childZoneIds.length; c += 1) {
                total += byId[node.childZoneIds[c]].totalCount;
            }
            node.totalCount = total;
        }

        // Stable sibling order by label, then zoneId, so equal labels still order.
        function byLabel(a, b) {
            const left = byId[a];
            const right = byId[b];
            if (left.label !== right.label) return left.label < right.label ? -1 : 1;
            return left.zoneId < right.zoneId ? -1 : 1;
        }
        for (let index = 0; index < nodes.length; index += 1) {
            nodes[index].childZoneIds.sort(byLabel);
        }
        const roots = nodes
            .filter(function (node) { return !node.parentZoneId; })
            .map(function (node) { return node.zoneId; })
            .sort(byLabel);

        return {
            apiVersion: API_VERSION,
            roots: roots,
            zones: byId,
            zoneOrder: nodes.map(function (node) { return node.zoneId; }),
            unzoned: {
                rowId: UNZONED_SCOPE,
                kind: 'unzoned',
                scopeId: UNZONED_SCOPE,
                groups: groupsFor(UNZONED_SCOPE, unzonedPlacements),
                directCount: unzonedPlacements.length,
                totalCount: unzonedPlacements.length,
            },
            invalidZoneIds: invalidZoneIds,
            counts: {
                zones: nodes.length,
                placements: rawPlacements.length,
                assigned: rawPlacements.length - unzonedPlacements.length,
                unzoned: unzonedPlacements.length,
                invalidZones: invalidZoneIds.length,
            },
        };
    }

    return {
        API_VERSION: API_VERSION,
        UNZONED_SCOPE: UNZONED_SCOPE,
        deriveStructure: deriveStructure,
        groupKey: groupKey,
    };
}));
