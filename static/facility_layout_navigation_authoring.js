(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.InspectorProFacilityNavigationAuthoring = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const API_VERSION = 1;
    const SCHEMA_VERSION = 1;
    const POSITION_PRECISION = 6;
    const MAXIMUM_POINTS = 2048;
    const LOOP_MODES = Object.freeze([
        'one_way',
        'closed_loop',
        'out_and_return',
        'paired_lane_return',
        'task_cycle',
    ]);
    const DIRECTIONS = Object.freeze(['forward', 'reverse', 'bidirectional']);
    const CONSTRAINT_MODES = Object.freeze([
        'guide',
        'locked_segment',
        'complete_override',
        'avoid_region',
        'preferred_corridor',
    ]);
    const ANCHOR_KINDS = Object.freeze([
        'actor_home',
        'station_operate',
        'station_load',
        'station_unload',
        'station_inspect',
        'fifo_input',
        'fifo_output',
        'cell_entrance',
        'aisle_access',
        'crossing',
        'vehicle_parking',
        'vehicle_turnaround',
        'handoff_endpoint',
    ]);
    const INTERACTION_BY_ANCHOR = Object.freeze({
        actor_home: 'none',
        station_operate: 'operate',
        station_load: 'load',
        station_unload: 'unload',
        station_inspect: 'inspect',
        fifo_input: 'handoff',
        fifo_output: 'handoff',
        cell_entrance: 'enter',
        aisle_access: 'enter',
        crossing: 'none',
        vehicle_parking: 'park',
        vehicle_turnaround: 'turnaround',
        handoff_endpoint: 'handoff',
    });

    function clone(value) {
        return value === undefined ? undefined
            : JSON.parse(JSON.stringify(value));
    }

    function cleanText(value, label) {
        const result = String(value || '').trim();
        if (!result) throw new TypeError(label + ' is required');
        return result;
    }

    function finite(value, label) {
        const result = Number(value);
        if (!Number.isFinite(result)) {
            throw new TypeError(label + ' must be a finite number');
        }
        return result;
    }

    function rounded(value) {
        const result = Number(finite(value, 'coordinate').toFixed(
            POSITION_PRECISION
        ));
        return Object.is(result, -0) ? 0 : result;
    }

    function point(value, label) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            throw new TypeError(label + ' must be a point');
        }
        return { x: rounded(value.x), z: rounded(value.z) };
    }

    function samePoint(left, right) {
        return Boolean(left && right
            && Math.abs(finite(left.x, 'left.x') - finite(right.x, 'right.x'))
                <= 1e-6
            && Math.abs(finite(left.z, 'left.z') - finite(right.z, 'right.z'))
                <= 1e-6);
    }

    function hashText(value) {
        const text = String(value);
        let left = 2166136261;
        let right = 2246822507;
        for (let index = 0; index < text.length; index += 1) {
            const code = text.charCodeAt(index);
            left ^= code;
            left = Math.imul(left, 16777619) >>> 0;
            right ^= code + index;
            right = Math.imul(right, 3266489909) >>> 0;
        }
        return left.toString(16).padStart(8, '0')
            + right.toString(16).padStart(8, '0');
    }

    function stableId(prefix, seed) {
        return cleanText(prefix, 'identity prefix') + '-' + hashText(
            JSON.stringify(seed)
        );
    }

    function emptyNavigation() {
        return {
            schemaVersion: SCHEMA_VERSION,
            anchors: [],
            movementPrograms: [],
            manualPathConstraints: [],
            handoffPrograms: [],
        };
    }

    function navigationFromLayout(layout) {
        const extensions = layout && layout.extensions;
        const navigation = extensions && extensions.facilityNavigation;
        return navigation && typeof navigation === 'object'
            ? clone(navigation) : emptyNavigation();
    }

    function placementById(layout, placementId) {
        const id = cleanText(placementId, 'placementId');
        const placements = Array.isArray(layout && layout.placements)
            ? layout.placements : [];
        const placement = placements.find(function (item) {
            return item && item.placementId === id;
        });
        if (!placement) throw new Error("Unknown placement '" + id + "'");
        return placement;
    }

    function detectActorClass(placement, requested) {
        if (requested === 'pedestrian' || requested === 'vehicle') {
            return requested;
        }
        const tokens = [
            placement && placement.assetId,
            placement && placement.metadata && placement.metadata.instanceLabel,
            placement && placement.metadata && placement.metadata.displayName,
        ].filter(Boolean).join(' ').toLowerCase();
        if (/operator|person|worker|pedestrian/.test(tokens)) return 'pedestrian';
        if (/forklift|vehicle|truck|tugger|agv|cart/.test(tokens)) return 'vehicle';
        throw new Error(
            'The selected placement is not identified as a pedestrian or vehicle actor.'
        );
    }

    function profileRef(placement, actorClass, requested) {
        const supplied = requested && typeof requested === 'object'
            ? requested : null;
        const metadata = placement && placement.metadata;
        const embedded = metadata && metadata.navigationProfileRef;
        const source = supplied || (embedded && typeof embedded === 'object'
            ? embedded : null);
        if (source) {
            const kind = source.profileKind || actorClass;
            const id = source.profileId || source.vehicleProfileId;
            const revision = source.profileRevision
                || source.vehicleProfileRevision;
            if (kind !== actorClass || !id || !/^[0-9a-f]{64}$/.test(
                String(revision || '')
            )) {
                throw new Error('The exact actor profile ID and revision are required.');
            }
            return {
                profileKind: actorClass,
                profileId: String(id),
                profileRevision: String(revision),
            };
        }
        if (actorClass === 'vehicle') {
            throw new Error(
                'Vehicle path authoring requires an exact published vehicle-profile ID and revision.'
            );
        }
        const revision = String(
            placement && placement.assetDefinitionRevision || ''
        );
        if (!/^[0-9a-f]{64}$/.test(revision)) {
            throw new Error(
                'Pedestrian path authoring requires an exact catalog actor revision.'
            );
        }
        return {
            profileKind: 'pedestrian',
            profileId: 'pedestrian-profile:' + cleanText(
                placement.assetId,
                'actor assetId'
            ),
            profileRevision: revision,
        };
    }

    function normalizedPoints(values, loopMode) {
        if (!Array.isArray(values) || values.length < 2
                || values.length > MAXIMUM_POINTS) {
            throw new RangeError(
                'A motion path requires between 2 and '
                    + MAXIMUM_POINTS + ' points.'
            );
        }
        const points = values.map(function (value, index) {
            return point(value, 'path point ' + index);
        });
        for (let index = 1; index < points.length; index += 1) {
            if (samePoint(points[index - 1], points[index])) {
                throw new Error('Consecutive path points must differ.');
            }
        }
        if (loopMode === 'closed_loop' || loopMode === 'task_cycle') {
            if (!samePoint(points[0], points[points.length - 1])) {
                points.push(clone(points[0]));
            }
            if (points.length < 4) {
                throw new Error('A closed motion path requires three distinct points.');
            }
        }
        return points;
    }

    function ensureEnum(value, allowed, label, fallback) {
        const result = value || fallback;
        if (!allowed.includes(result)) {
            throw new TypeError(label + ' is unsupported');
        }
        return result;
    }

    function sourceRevision(value) {
        const revision = cleanText(value, 'layout revision');
        if (!/^[0-9a-f]{64}$/.test(revision)) {
            throw new Error('Manual path authoring requires a SHA-256 base revision.');
        }
        return revision;
    }

    function upsertById(values, identityField, record) {
        const result = (Array.isArray(values) ? values : []).filter(
            function (item) {
                return item && item[identityField] !== record[identityField];
            }
        );
        result.push(record);
        return result;
    }

    function buildManualPathIntent(layout, request) {
        const input = request && typeof request === 'object' ? request : {};
        const placement = placementById(layout, input.actorPlacementId);
        const actorClass = detectActorClass(placement, input.actorClass);
        const actorProfileRef = profileRef(
            placement,
            actorClass,
            input.actorProfileRef
        );
        const loopMode = ensureEnum(
            input.loopMode,
            LOOP_MODES,
            'loopMode',
            'closed_loop'
        );
        const direction = ensureEnum(
            input.direction,
            DIRECTIONS,
            'direction',
            'forward'
        );
        const constraintMode = ensureEnum(
            input.constraintMode,
            CONSTRAINT_MODES,
            'constraintMode',
            'complete_override'
        );
        const points = normalizedPoints(input.points, loopMode);
        const revision = sourceRevision(input.baseRevision);
        const pathSeed = input.pathSeed || {
            actorPlacementId: placement.placementId,
            sequence: Number.isInteger(input.sequence) ? input.sequence : 1,
        };
        const anchorId = input.homeAnchorId || stableId('na', {
            kind: 'actor_home',
            pathSeed: pathSeed,
        });
        const programId = input.movementProgramId || stableId('nmp', pathSeed);
        const constraintId = input.manualPathConstraintId
            || stableId('nmc', pathSeed);
        const stopId = stableId('nst', {
            movementProgramId: programId,
            anchorId: anchorId,
        });
        const evidenceId = 'evidence:ui-plan-pointer';
        const locked = Array.isArray(input.lockedSegmentIndexes)
            ? Array.from(new Set(input.lockedSegmentIndexes.map(Number)))
                .sort(function (left, right) { return left - right; })
            : [];
        if (locked.some(function (index) {
            return !Number.isInteger(index)
                || index < 0 || index >= points.length - 1;
        })) throw new Error('A locked segment index is outside the path.');
        const navigation = navigationFromLayout(layout);
        const anchor = {
            navigationAnchorId: anchorId,
            anchorKind: 'actor_home',
            ownerRef: {
                ownerKind: 'placement',
                ownerId: placement.placementId,
            },
            interactionKind: 'none',
            positionAuthority: 'ui_authored',
            localPosition: clone(points[0]),
            derivedPositionRef: null,
            approachDirections: ['any'],
            actorClasses: [actorClass],
            evidenceStatus: 'authored',
            evidence: [evidenceId],
            reviewStatus: 'pending',
        };
        const constraint = {
            manualPathConstraintId: constraintId,
            movementProgramId: programId,
            constraintMode: constraintMode,
            authoredPolyline: points,
            snapRefs: [{
                pointIndex: 0,
                refKind: 'navigation_anchor',
                refId: anchorId,
            }].concat((Array.isArray(input.snapRefs) ? input.snapRefs : [])
                .filter(function (item) { return item && item.pointIndex !== 0; })
                .map(clone)),
            lockedSegmentIndexes: locked,
            direction: direction,
            positionAuthority: 'ui_authored',
            evidenceStatus: 'authored',
            evidence: [evidenceId],
            reviewStatus: 'pending',
        };
        const program = {
            movementProgramId: programId,
            actorPlacementId: placement.placementId,
            actorClass: actorClass,
            actorProfileRef: actorProfileRef,
            orderedStops: [{
                stopId: stopId,
                navigationAnchorId: anchorId,
                interactionKind: 'none',
                required: true,
            }],
            loopMode: loopMode,
            requiredRouteIds: Array.isArray(input.requiredRouteIds)
                ? input.requiredRouteIds.slice() : [],
            requiredAnchorIds: [anchorId],
            forbiddenZoneIds: Array.isArray(input.forbiddenZoneIds)
                ? input.forbiddenZoneIds.slice() : [],
            forbiddenRouteIds: Array.isArray(input.forbiddenRouteIds)
                ? input.forbiddenRouteIds.slice() : [],
            manualPathConstraintIds: [constraintId],
            handoffProgramIds: [],
            sourceRevisions: {
                layout: revision,
                actor_profile: actorProfileRef.profileRevision,
            },
            evidenceStatus: 'authored',
            evidence: [evidenceId],
            reviewStatus: 'pending',
        };
        navigation.anchors = upsertById(
            navigation.anchors,
            'navigationAnchorId',
            anchor
        );
        navigation.movementPrograms = upsertById(
            navigation.movementPrograms,
            'movementProgramId',
            program
        );
        navigation.manualPathConstraints = upsertById(
            navigation.manualPathConstraints,
            'manualPathConstraintId',
            constraint
        );
        return {
            facilityNavigation: navigation,
            actorPlacementId: placement.placementId,
            actorClass: actorClass,
            actorProfileRef: actorProfileRef,
            movementProgramId: programId,
            manualPathConstraintId: constraintId,
            homeAnchorId: anchorId,
            points: clone(points),
            loopMode: loopMode,
            direction: direction,
            constraintMode: constraintMode,
        };
    }

    function addNavigationAnchor(layout, request) {
        const input = request && typeof request === 'object' ? request : {};
        const placement = placementById(layout, input.ownerPlacementId);
        const actorClass = detectActorClass(placement, input.actorClass);
        const anchorKind = ensureEnum(
            input.anchorKind,
            ANCHOR_KINDS,
            'anchorKind',
            'station_operate'
        );
        const position = point(input.position, 'anchor position');
        const navigation = navigationFromLayout(layout);
        const navigationAnchorId = input.navigationAnchorId || stableId('na', {
            ownerPlacementId: placement.placementId,
            anchorKind: anchorKind,
            position: position,
            sequence: Number.isInteger(input.sequence) ? input.sequence : 1,
        });
        navigation.anchors = upsertById(
            navigation.anchors,
            'navigationAnchorId',
            {
                navigationAnchorId: navigationAnchorId,
                anchorKind: anchorKind,
                ownerRef: {
                    ownerKind: 'placement',
                    ownerId: placement.placementId,
                },
                interactionKind: INTERACTION_BY_ANCHOR[anchorKind],
                positionAuthority: 'ui_authored',
                localPosition: position,
                derivedPositionRef: null,
                approachDirections: ['any'],
                actorClasses: [actorClass],
                evidenceStatus: 'authored',
                evidence: ['evidence:ui-plan-pointer'],
                reviewStatus: 'pending',
            }
        );
        return {
            facilityNavigation: navigation,
            navigationAnchorId: navigationAnchorId,
        };
    }

    function buildAutomaticProgramIntent(layout, request) {
        const input = request && typeof request === 'object' ? request : {};
        const actor = placementById(layout, input.actorPlacementId);
        const actorClass = detectActorClass(actor, input.actorClass);
        if (actorClass !== 'pedestrian') {
            throw new Error(
                'Automatic placement-to-placement routing currently supports existing operators.'
            );
        }
        const targetIds = Array.isArray(input.orderedTargetPlacementIds)
            ? input.orderedTargetPlacementIds.map(function (value) {
                return cleanText(value, 'target placementId');
            }) : [];
        if (!targetIds.length || targetIds.length > 20) {
            throw new Error('Automatic routing requires between 1 and 20 destinations.');
        }
        if (targetIds.length !== new Set(targetIds).size) {
            throw new Error('Automatic route destinations must be unique.');
        }
        if (targetIds.includes(actor.placementId)) {
            throw new Error('The selected operator cannot also be a destination.');
        }
        const targets = targetIds.map(function (placementId) {
            const target = placementById(layout, placementId);
            try {
                detectActorClass(target);
            } catch (_error) {
                return target;
            }
            throw new Error('A mobile actor cannot be used as a station destination.');
        });
        const navigation = navigationFromLayout(layout);
        const evidence = ['evidence:deterministic-placement-access-v1'];
        function revisionOf(placement) {
            const revision = String(placement.assetDefinitionRevision || '');
            if (!/^[0-9a-f]{64}$/.test(revision)) {
                throw new Error(
                    'Automatic routing requires exact catalog revisions for every destination.'
                );
            }
            return revision;
        }
        function derivedAnchor(owner, anchorKind, sourceKind, sequence) {
            const anchorId = stableId('na', {
                actorPlacementId: actor.placementId,
                ownerPlacementId: owner.placementId,
                anchorKind: anchorKind,
                sourceKind: sourceKind,
            });
            navigation.anchors = upsertById(
                navigation.anchors,
                'navigationAnchorId',
                {
                    navigationAnchorId: anchorId,
                    anchorKind: anchorKind,
                    ownerRef: {
                        ownerKind: 'placement',
                        ownerId: owner.placementId,
                    },
                    interactionKind: INTERACTION_BY_ANCHOR[anchorKind],
                    positionAuthority: 'derived',
                    localPosition: null,
                    derivedPositionRef: {
                        sourceKind: sourceKind,
                        sourceId: owner.placementId,
                        sourceRevision: revisionOf(owner),
                    },
                    approachDirections: ['any'],
                    actorClasses: [actorClass],
                    evidenceStatus: 'derived',
                    evidence: evidence.slice(),
                    reviewStatus: 'pending',
                }
            );
            return { anchorId: anchorId, sequence: sequence };
        }
        const home = derivedAnchor(actor, 'actor_home', 'placement_transform', 0);
        const targetAnchors = targets.map(function (target, index) {
            return derivedAnchor(
                target,
                'station_operate',
                'placement_access',
                index + 1
            );
        });
        const draftLayout = clone(layout);
        draftLayout.extensions = Object.assign({}, draftLayout.extensions || {}, {
            facilityNavigation: navigation,
        });
        const built = buildSemanticProgramIntent(draftLayout, {
            actorPlacementId: actor.placementId,
            movementProgramId: input.movementProgramId || null,
            orderedAnchorIds: [home.anchorId].concat(
                targetAnchors.map(function (item) { return item.anchorId; })
            ),
            loopMode: input.loopMode || 'one_way',
            requiredRouteIds: input.requiredRouteIds || [],
            forbiddenZoneIds: input.forbiddenZoneIds || [],
            forbiddenRouteIds: input.forbiddenRouteIds || [],
            baseRevision: input.baseRevision,
        });
        const program = built.facilityNavigation.movementPrograms.find(
            function (item) {
                return item.movementProgramId === built.movementProgramId;
            }
        );
        if (program) program.manualPathConstraintIds = [];
        built.orderedTargetPlacementIds = targetIds.slice();
        built.homeAnchorId = home.anchorId;
        built.destinationAnchorIds = targetAnchors.map(function (item) {
            return item.anchorId;
        });
        built.semanticDiff.orderedTargetPlacementIds = targetIds.slice();
        built.semanticDiff.approachPolicy = 'nearest_feasible_placement_access';
        built.semanticDiff.manualOverridesPreserved = false;
        return built;
    }

    function buildSemanticProgramIntent(layout, request) {
        const input = request && typeof request === 'object' ? request : {};
        const placement = placementById(layout, input.actorPlacementId);
        const navigation = navigationFromLayout(layout);
        const existing = navigation.movementPrograms.find(function (item) {
            return item && (
                input.movementProgramId
                    ? item.movementProgramId === input.movementProgramId
                    : item.actorPlacementId === placement.placementId
            );
        }) || null;
        const actorClass = detectActorClass(
            placement,
            existing && existing.actorClass
        );
        const actorProfileRef = profileRef(
            placement,
            actorClass,
            existing && existing.actorProfileRef
        );
        const loopMode = ensureEnum(
            input.loopMode,
            LOOP_MODES,
            'loopMode',
            existing && existing.loopMode || 'task_cycle'
        );
        const revision = sourceRevision(input.baseRevision);
        const anchorIndex = new Map(navigation.anchors.map(function (item) {
            return [item && item.navigationAnchorId, item];
        }));
        const orderedAnchorIds = Array.isArray(input.orderedAnchorIds)
            ? Array.from(new Set(input.orderedAnchorIds.map(function (value) {
                return cleanText(value, 'navigationAnchorId');
            }))) : [];
        if (!orderedAnchorIds.length) {
            throw new Error('At least one existing navigation anchor is required.');
        }
        orderedAnchorIds.forEach(function (anchorId) {
            const anchor = anchorIndex.get(anchorId);
            if (!anchor) throw new Error("Unknown navigation anchor '" + anchorId + "'");
            if (!Array.isArray(anchor.actorClasses)
                    || !anchor.actorClasses.includes(actorClass)) {
                throw new Error(
                    "Navigation anchor '" + anchorId
                        + "' does not support the selected actor class."
                );
            }
        });
        function existingIds(values, collection, identityField, label) {
            const index = new Set((layout[collection] || []).map(function (item) {
                return item && item[identityField];
            }));
            return Array.from(new Set((Array.isArray(values) ? values : [])
                .map(function (value) { return cleanText(value, label); })))
                .map(function (value) {
                    if (!index.has(value)) throw new Error("Unknown " + label + " '" + value + "'");
                    return value;
                });
        }
        const requiredRouteIds = existingIds(
            input.requiredRouteIds,
            'routes',
            'routeId',
            'routeId'
        );
        const forbiddenRouteIds = existingIds(
            input.forbiddenRouteIds,
            'routes',
            'routeId',
            'routeId'
        );
        if (requiredRouteIds.some(function (id) {
            return forbiddenRouteIds.includes(id);
        })) throw new Error('A route cannot be both required and forbidden.');
        const forbiddenZoneIds = existingIds(
            input.forbiddenZoneIds,
            'zones',
            'zoneId',
            'zoneId'
        );
        const programId = input.movementProgramId
            || existing && existing.movementProgramId
            || stableId('nmp', {
                actorPlacementId: placement.placementId,
                authority: 'sage-semantic-proposal',
            });
        const stops = orderedAnchorIds.map(function (anchorId, index) {
            const anchor = anchorIndex.get(anchorId);
            return {
                stopId: stableId('nst', {
                    movementProgramId: programId,
                    navigationAnchorId: anchorId,
                    sequence: index,
                }),
                navigationAnchorId: anchorId,
                interactionKind: anchor.interactionKind || 'none',
                required: true,
            };
        });
        const program = {
            movementProgramId: programId,
            actorPlacementId: placement.placementId,
            actorClass: actorClass,
            actorProfileRef: actorProfileRef,
            orderedStops: stops,
            loopMode: loopMode,
            requiredRouteIds: requiredRouteIds,
            requiredAnchorIds: orderedAnchorIds.slice(),
            forbiddenZoneIds: forbiddenZoneIds,
            forbiddenRouteIds: forbiddenRouteIds,
            manualPathConstraintIds: existing
                ? clone(existing.manualPathConstraintIds || []) : [],
            handoffProgramIds: existing
                ? clone(existing.handoffProgramIds || []) : [],
            sourceRevisions: {
                layout: revision,
                actor_profile: actorProfileRef.profileRevision,
            },
            evidenceStatus: 'inferred',
            evidence: ['evidence:sage-semantic-proposal'],
            reviewStatus: 'pending',
        };
        navigation.movementPrograms = upsertById(
            navigation.movementPrograms,
            'movementProgramId',
            program
        );
        return {
            facilityNavigation: navigation,
            movementProgramId: programId,
            actorPlacementId: placement.placementId,
            actorClass: actorClass,
            orderedAnchorIds: orderedAnchorIds,
            semanticDiff: {
                loopMode: loopMode,
                orderedAnchorIds: orderedAnchorIds,
                requiredRouteIds: requiredRouteIds,
                forbiddenZoneIds: forbiddenZoneIds,
                forbiddenRouteIds: forbiddenRouteIds,
                manualOverridesPreserved: Boolean(
                    existing && (existing.manualPathConstraintIds || []).length
                ),
            },
        };
    }

    function pathLength(points) {
        return (points || []).slice(1).reduce(function (total, value, index) {
            const previous = points[index];
            return total + Math.hypot(
                finite(value.x, 'point.x') - finite(previous.x, 'point.x'),
                finite(value.z, 'point.z') - finite(previous.z, 'point.z')
            );
        }, 0);
    }

    function samplePathAtNormalizedTime(values, requestedTime) {
        const points = normalizedPoints(values, 'one_way');
        const totalDistance = pathLength(points);
        if (!(totalDistance > 0)) throw new Error('Motion path has zero length.');
        const normalizedTime = Math.min(1, Math.max(0, finite(
            requestedTime,
            'normalized time'
        )));
        const target = totalDistance * normalizedTime;
        let cumulative = 0;
        for (let index = 0; index < points.length - 1; index += 1) {
            const left = points[index];
            const right = points[index + 1];
            const distance = Math.hypot(
                right.x - left.x,
                right.z - left.z
            );
            if (target <= cumulative + distance || index === points.length - 2) {
                const ratio = distance <= 0 ? 0
                    : Math.min(1, Math.max(0, (target - cumulative) / distance));
                return {
                    x: rounded(left.x + (right.x - left.x) * ratio),
                    z: rounded(left.z + (right.z - left.z) * ratio),
                    heading: Math.atan2(right.z - left.z, right.x - left.x),
                    distanceMeters: rounded(target),
                    totalDistanceMeters: rounded(totalDistance),
                    segmentIndex: index,
                    interpolationRatio: ratio,
                    normalizedTime: normalizedTime,
                };
            }
            cumulative += distance;
        }
        throw new Error('Motion path could not be sampled.');
    }

    function reversePath(values) {
        return (values || []).slice().reverse().map(function (value) {
            return point(value, 'path point');
        });
    }

    function insertWaypoint(values, segmentIndex, value) {
        const points = (values || []).map(function (item) {
            return point(item, 'path point');
        });
        const index = Number(segmentIndex);
        if (!Number.isInteger(index) || index < 0 || index >= points.length - 1) {
            throw new RangeError('segmentIndex is outside the path');
        }
        points.splice(index + 1, 0, point(value, 'waypoint'));
        return points;
    }

    function deleteWaypoint(values, pointIndex) {
        const points = (values || []).map(function (item) {
            return point(item, 'path point');
        });
        const index = Number(pointIndex);
        if (!Number.isInteger(index) || index < 0 || index >= points.length) {
            throw new RangeError('pointIndex is outside the path');
        }
        if (points.length <= 2) throw new Error('A path requires two points.');
        points.splice(index, 1);
        return points;
    }

    function goldArtifact(layout, constraintId, validation) {
        const navigation = navigationFromLayout(layout);
        const constraint = navigation.manualPathConstraints.find(
            function (item) {
                return item && item.manualPathConstraintId === constraintId;
            }
        );
        if (!constraint) throw new Error('The selected path is unavailable.');
        const program = navigation.movementPrograms.find(function (item) {
            return item && item.movementProgramId === constraint.movementProgramId;
        });
        return {
            schemaVersion: 'facility-navigation-nav2-gold-v1',
            productionEligible: false,
            authorityBoundary: (
                'UI-authored navigation intent for evaluation. Geometry validation '
                + 'does not establish safety, capacity, timing, or regulatory compliance.'
            ),
            movementProgram: clone(program),
            manualPathConstraint: clone(constraint),
            validation: validation ? clone(validation) : null,
        };
    }

    return Object.freeze({
        API_VERSION: API_VERSION,
        SCHEMA_VERSION: SCHEMA_VERSION,
        LOOP_MODES: LOOP_MODES,
        DIRECTIONS: DIRECTIONS,
        CONSTRAINT_MODES: CONSTRAINT_MODES,
        ANCHOR_KINDS: ANCHOR_KINDS,
        emptyNavigation: emptyNavigation,
        navigationFromLayout: navigationFromLayout,
        detectActorClass: detectActorClass,
        buildManualPathIntent: buildManualPathIntent,
        buildSemanticProgramIntent: buildSemanticProgramIntent,
        buildAutomaticProgramIntent: buildAutomaticProgramIntent,
        addNavigationAnchor: addNavigationAnchor,
        samplePathAtNormalizedTime: samplePathAtNormalizedTime,
        pathLength: pathLength,
        reversePath: reversePath,
        insertWaypoint: insertWaypoint,
        deleteWaypoint: deleteWaypoint,
        goldArtifact: goldArtifact,
        stableId: stableId,
        samePoint: samePoint,
    });
}));
