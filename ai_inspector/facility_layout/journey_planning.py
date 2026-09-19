"""Deterministic NAV4/NAV5 journey planning over immutable snapshots."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import heapq
import json
import math
import threading
from typing import Any, Mapping, Sequence

from .errors import FacilityNotFoundError, FacilityValidationError
from .navigation_contract import (
    FACILITY_NAVIGATION_JOURNEY_QUALIFICATION,
    navigation_identity_index,
    navigation_stable_id,
    seal_journey_solution,
    validate_facility_navigation_extension,
    validate_journey_solution,
    validate_navigation_snapshot,
)
from .navigation_geometry import (
    FacilityNavigationGeometryError,
    build_triangulated_mesh,
    geometry_from_canonical_polygons,
    solve_triangulated_mesh,
    validate_centerline,
)
from .motion_lanes import FACILITY_MOTION_LANE_BINDING_VERSION
from .routing import (
    ROUTER_VERSION,
    ROUTING_ENGINE_VERSION,
    SWEPT_ENVELOPE_REVISION,
    route_traversable_corridor,
    validate_swept_volume,
)


FACILITY_PEDESTRIAN_PLANNER_VERSION = "facility-pedestrian-planner-v1"
FACILITY_VEHICLE_JOURNEY_PLANNER_VERSION = "facility-vehicle-journey-planner-v1"
FACILITY_JOURNEY_STORE_MAXIMUM = 256
FACILITY_JOURNEY_ALTERNATIVE_MAXIMUM = 3
FACILITY_JOURNEY_QUALIFICATION = FACILITY_NAVIGATION_JOURNEY_QUALIFICATION
_EPSILON = 1.0e-9


class FacilityJourneyPlanningError(FacilityValidationError):
    """A journey request cannot be represented by the closed planner."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise FacilityJourneyPlanningError(
            "facility_navigation_invalid_json",
            "Journey planning requires finite JSON inputs.",
        ) from error


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _point(value: Mapping[str, Any]) -> dict[str, float]:
    try:
        x = float(value["x"])
        z = float(value["z"])
    except (KeyError, TypeError, ValueError) as error:
        raise FacilityJourneyPlanningError(
            "facility_navigation_geometry_invalid",
            "Journey geometry contains an invalid point.",
        ) from error
    if not math.isfinite(x) or not math.isfinite(z):
        raise FacilityJourneyPlanningError(
            "facility_navigation_geometry_invalid",
            "Journey geometry contains a non-finite point.",
        )
    return {"x": round(x, 6), "z": round(z, 6)}


def _point_tuple(value: Mapping[str, Any]) -> tuple[float, float]:
    point = _point(value)
    return point["x"], point["z"]


def _distance(points: Sequence[Mapping[str, Any]]) -> float:
    return round(sum(
        math.dist(_point_tuple(left), _point_tuple(right))
        for left, right in zip(points, points[1:])
    ), 6)


def _dedupe(points: Sequence[Mapping[str, Any]]) -> list[dict[str, float]]:
    result: list[dict[str, float]] = []
    for raw in points:
        point = _point(raw)
        if not result or point != result[-1]:
            result.append(point)
    return result


def _poses(points: Sequence[Mapping[str, Any]], *, gear: str = "forward") -> list[dict[str, Any]]:
    if len(points) < 2:
        return []
    result = []
    for index, raw in enumerate(points):
        left = points[index - 1] if index == len(points) - 1 else raw
        right = raw if index == len(points) - 1 else points[index + 1]
        heading = math.atan2(
            float(right["z"]) - float(left["z"]),
            float(right["x"]) - float(left["x"]),
        )
        if gear == "reverse":
            heading = math.atan2(math.sin(heading + math.pi), math.cos(heading + math.pi))
        result.append({
            "x": round(float(raw["x"]), 6),
            "z": round(float(raw["z"]), 6),
            "heading": round(heading, 9),
            "gear": gear,
        })
    return result


def _turn_count(points: Sequence[Mapping[str, Any]]) -> int:
    headings = []
    for left, right in zip(points, points[1:]):
        dx = float(right["x"]) - float(left["x"])
        dz = float(right["z"]) - float(left["z"])
        if math.hypot(dx, dz) > _EPSILON:
            headings.append(math.atan2(dz, dx))
    return sum(
        1
        for left, right in zip(headings, headings[1:])
        if abs(math.atan2(math.sin(right - left), math.cos(right - left))) > 1.0e-6
    )


def _extension(layout: Mapping[str, Any]) -> dict[str, Any]:
    extension = (
        layout.get("extensions", {}).get("facilityNavigation")
        if isinstance(layout.get("extensions"), Mapping)
        else None
    )
    if not isinstance(extension, Mapping):
        raise FacilityJourneyPlanningError(
            "facility_navigation_program_unavailable",
            "The layout has no authored navigation program.",
        )
    return validate_facility_navigation_extension(
        extension,
        navigation_identity_index(layout),
    )


def _program(extension: Mapping[str, Any], program_id: str) -> dict[str, Any]:
    value = next(
        (
            item
            for item in extension.get("movementPrograms", [])
            if isinstance(item, Mapping) and item.get("movementProgramId") == program_id
        ),
        None,
    )
    if value is None:
        raise FacilityJourneyPlanningError(
            "facility_navigation_program_unavailable",
            "The requested movement program does not exist.",
            details={"movementProgramId": program_id},
        )
    return deepcopy(dict(value))


def _ordered_anchors(program: Mapping[str, Any]) -> list[str]:
    result = [str(item["navigationAnchorId"]) for item in program["orderedStops"]]
    if not result:
        return []
    loop_mode = program["loopMode"]
    if loop_mode in {"closed_loop", "task_cycle"} and result[-1] != result[0]:
        result.append(result[0])
    elif loop_mode in {"out_and_return", "paired_lane_return"} and len(result) > 1:
        result.extend(reversed(result[:-1]))
    return result


def _anchor_nodes(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result = {}
    for node in package["snapshot"]["nodes"]:
        owner = node.get("ownerRefId")
        if isinstance(owner, str) and owner.startswith("na-"):
            result[owner] = node
    return result


def _network_adjacency(
    package: Mapping[str, Any],
    *,
    forbidden_route_ids: set[str],
) -> dict[str, list[tuple[str, float, str, frozenset[str]]]]:
    result: dict[str, list[tuple[str, float, str, frozenset[str]]]] = {
        str(item["nodeId"]): [] for item in package["snapshot"]["nodes"]
    }
    for edge in package["snapshot"]["edges"]:
        sources = frozenset(str(item) for item in edge.get("sourceRefIds", []))
        if sources & forbidden_route_ids:
            continue
        source = str(edge["sourceNodeId"])
        target = str(edge["targetNodeId"])
        cost = float(edge["costMeters"])
        edge_id = str(edge["edgeId"])
        direction = edge["direction"]
        if direction in {"forward", "bidirectional"}:
            result[source].append((target, cost, edge_id, sources))
        if direction in {"reverse", "bidirectional"}:
            result[target].append((source, cost, edge_id, sources))
    for values in result.values():
        values.sort(key=lambda item: (item[0], item[2]))
    return result


def _network_path(
    package: Mapping[str, Any],
    start_id: str,
    goal_id: str,
    *,
    required_route_ids: set[str],
    forbidden_route_ids: set[str],
) -> tuple[list[dict[str, float]], list[str], set[str]] | None:
    adjacency = _network_adjacency(
        package,
        forbidden_route_ids=forbidden_route_ids,
    )
    positions = {
        str(item["nodeId"]): _point(item["position"])
        for item in package["snapshot"]["nodes"]
    }
    if start_id not in positions or goal_id not in positions:
        return None
    required = sorted(required_route_ids)
    bits = {route_id: 1 << index for index, route_id in enumerate(required)}
    full_mask = (1 << len(required)) - 1
    queue = [(0.0, 0.0, start_id, 0)]
    costs = {(start_id, 0): 0.0}
    previous: dict[tuple[str, int], tuple[tuple[str, int], str, frozenset[str]]] = {}
    final = None
    while queue:
        _, cost, node_id, mask = heapq.heappop(queue)
        state = (node_id, mask)
        if cost > costs.get(state, math.inf) + _EPSILON:
            continue
        if node_id == goal_id and mask == full_mask:
            final = state
            break
        for neighbor, edge_cost, edge_id, source_refs in adjacency.get(node_id, []):
            new_mask = mask
            for route_id in source_refs:
                new_mask |= bits.get(route_id, 0)
            candidate = cost + edge_cost
            next_state = (neighbor, new_mask)
            if candidate + _EPSILON < costs.get(next_state, math.inf):
                costs[next_state] = candidate
                previous[next_state] = (state, edge_id, source_refs)
                heuristic = math.dist(
                    _point_tuple(positions[neighbor]),
                    _point_tuple(positions[goal_id]),
                )
                heapq.heappush(
                    queue,
                    (candidate + heuristic, candidate, neighbor, new_mask),
                )
    if final is None:
        return None
    states = [final]
    edge_ids = []
    used_sources: set[str] = set()
    while states[-1] != (start_id, 0):
        prior, edge_id, source_refs = previous[states[-1]]
        edge_ids.append(edge_id)
        used_sources.update(source_refs)
        states.append(prior)
    states.reverse()
    edge_ids.reverse()
    return [positions[state[0]] for state in states], edge_ids, used_sources


def _manual_constraints(
    extension: Mapping[str, Any],
    program: Mapping[str, Any],
) -> list[dict[str, Any]]:
    selected = set(program["manualPathConstraintIds"])
    return sorted(
        (
            deepcopy(dict(item))
            for item in extension.get("manualPathConstraints", [])
            if isinstance(item, Mapping)
            and item.get("manualPathConstraintId") in selected
        ),
        key=lambda item: item["manualPathConstraintId"],
    )


def _manual_override(
    constraints: Sequence[Mapping[str, Any]],
    ordered_anchor_ids: Sequence[str],
    anchors: Mapping[str, Mapping[str, Any]],
    free_space: Any,
) -> list[dict[str, float]] | None:
    complete = [item for item in constraints if item["constraintMode"] == "complete_override"]
    if not complete:
        return None
    if len(complete) != 1:
        raise FacilityJourneyPlanningError(
            "facility_navigation_constraint_conflict",
            "A movement program may bind only one complete path override.",
        )
    points = _dedupe(complete[0]["authoredPolyline"])
    if len(points) < 2 or not validate_centerline(free_space, points):
        raise FacilityJourneyPlanningError(
            "facility_navigation_constraint_conflict",
            "The complete authored path does not remain in traversable free space.",
        )
    if ordered_anchor_ids:
        start = _point(anchors[ordered_anchor_ids[0]]["position"])
        goal = _point(anchors[ordered_anchor_ids[-1]]["position"])
        if points[0] != start or points[-1] != goal:
            raise FacilityJourneyPlanningError(
                "facility_navigation_constraint_conflict",
                "The complete override endpoints do not match the required anchors.",
            )
    return points


def _waypoints(
    ordered_anchor_ids: Sequence[str],
    anchors: Mapping[str, Mapping[str, Any]],
    constraints: Sequence[Mapping[str, Any]],
) -> list[tuple[str | None, dict[str, float]]]:
    values: list[tuple[str | None, dict[str, float]]] = []
    for index, anchor_id in enumerate(ordered_anchor_ids):
        values.append((anchor_id, _point(anchors[anchor_id]["position"])))
        if index == 0:
            for constraint in constraints:
                if constraint["constraintMode"] in {"guide", "locked_segment"}:
                    values.extend((None, _point(point)) for point in constraint["authoredPolyline"])
    result = []
    for identity, point in values:
        if not result or point != result[-1][1]:
            result.append((identity, point))
    return result


def _refusal(
    *,
    program: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    outcome: str,
    ordered_anchor_ids: Sequence[str],
    context_fingerprint: str,
    topology: str = "refused",
    authority: str = "pass",
) -> dict[str, Any]:
    validation = {
        "identity": "pass",
        "topology": topology,
        "direction": "not_applicable",
        "physical": "not_applicable",
        "authority": authority,
        "stale": "pass",
    }
    return seal_journey_solution({
        "movementProgramId": program["movementProgramId"],
        "navigationSnapshotId": snapshot["navigationSnapshotId"],
        "actorPlacementId": program["actorPlacementId"],
        "generationLayoutRevision": snapshot["layoutRevision"],
        "validationContextFingerprint": context_fingerprint,
        "outcome": outcome,
        "orderedAnchorIds": list(ordered_anchor_ids),
        "networkEdgeIds": [],
        "centerline": [],
        "poses": [],
        "distanceMeters": 0,
        "turnCount": 0,
        "reverseUsed": False,
        "validation": validation,
        "sourceRevisions": dict(snapshot["sourceRevisions"]),
        "plannerVersions": {
            "pedestrian": FACILITY_PEDESTRIAN_PLANNER_VERSION,
        },
    })


def plan_pedestrian_journey(
    layout: Mapping[str, Any],
    navigation_package: Mapping[str, Any],
    movement_program_id: str,
) -> dict[str, Any]:
    """Plan one identity-bound pedestrian journey without mutating the layout."""

    snapshot = validate_navigation_snapshot(navigation_package["snapshot"])
    extension = _extension(layout)
    program = _program(extension, movement_program_id)
    if program["actorClass"] != "pedestrian" or snapshot["actorClass"] != "pedestrian":
        raise FacilityJourneyPlanningError(
            "facility_navigation_actor_class_mismatch",
            "The pedestrian planner requires a pedestrian program and snapshot.",
        )
    if program["actorProfileRef"]["profileRevision"] != snapshot["actorProfileRevision"]:
        raise FacilityJourneyPlanningError(
            "facility_navigation_actor_profile_mismatch",
            "The movement program and snapshot profile revisions differ.",
        )
    constraints = _manual_constraints(extension, program)
    ordered_anchor_ids = _ordered_anchors(program)
    context_fingerprint = _fingerprint({
        "geometryContextFingerprint": snapshot["geometryContextFingerprint"],
        "program": program,
        "constraints": constraints,
        "plannerVersion": FACILITY_PEDESTRIAN_PLANNER_VERSION,
    })
    if not ordered_anchor_ids:
        return _refusal(
            program=program,
            snapshot=snapshot,
            outcome="authority_missing",
            ordered_anchor_ids=[],
            context_fingerprint=context_fingerprint,
            authority="unknown",
        )
    anchors = _anchor_nodes(navigation_package)
    if any(anchor_id not in anchors for anchor_id in ordered_anchor_ids):
        return _refusal(
            program=program,
            snapshot=snapshot,
            outcome="unreachable",
            ordered_anchor_ids=ordered_anchor_ids,
            context_fingerprint=context_fingerprint,
        )
    free_records = navigation_package.get("freeSpacePolygons")
    if not isinstance(free_records, list) or not free_records:
        return _refusal(
            program=program,
            snapshot=snapshot,
            outcome="physical_validation_refused",
            ordered_anchor_ids=ordered_anchor_ids,
            context_fingerprint=context_fingerprint,
            topology="unknown",
        )
    free_space = geometry_from_canonical_polygons(free_records)
    try:
        override = _manual_override(
            constraints,
            ordered_anchor_ids,
            anchors,
            free_space,
        )
    except FacilityJourneyPlanningError:
        return _refusal(
            program=program,
            snapshot=snapshot,
            outcome="constraint_conflict",
            ordered_anchor_ids=ordered_anchor_ids,
            context_fingerprint=context_fingerprint,
        )
    network_edge_ids: list[str] = []
    if override is not None:
        centerline = override
    else:
        waypoints = _waypoints(ordered_anchor_ids, anchors, constraints)
        mesh = build_triangulated_mesh(free_space)
        centerline: list[dict[str, float]] = []
        required_routes = set(program["requiredRouteIds"])
        forbidden_routes = set(program["forbiddenRouteIds"])
        remaining_routes = set(required_routes)
        network_mandatory = bool(required_routes)
        for leg_index, ((left_id, left), (right_id, right)) in enumerate(
            zip(waypoints, waypoints[1:])
        ):
            network = None
            if left_id is not None and right_id is not None:
                network = _network_path(
                    navigation_package,
                    str(anchors[left_id]["nodeId"]),
                    str(anchors[right_id]["nodeId"]),
                    required_route_ids=(remaining_routes if leg_index == len(waypoints) - 2 else set()),
                    forbidden_route_ids=forbidden_routes,
                )
                if network is not None and not validate_centerline(free_space, network[0]):
                    network = None
            if network is not None:
                leg_points, leg_edges, used_sources = network
                network_edge_ids.extend(leg_edges)
                remaining_routes.difference_update(used_sources)
            else:
                if network_mandatory or (
                    remaining_routes and leg_index == len(waypoints) - 2
                ):
                    return _refusal(
                        program=program,
                        snapshot=snapshot,
                        outcome="constraint_conflict",
                        ordered_anchor_ids=ordered_anchor_ids,
                        context_fingerprint=context_fingerprint,
                    )
                try:
                    leg = solve_triangulated_mesh(
                        mesh,
                        free_space,
                        _point_tuple(left),
                        _point_tuple(right),
                    )
                except FacilityNavigationGeometryError:
                    return _refusal(
                        program=program,
                        snapshot=snapshot,
                        outcome="unreachable",
                        ordered_anchor_ids=ordered_anchor_ids,
                        context_fingerprint=context_fingerprint,
                    )
                leg_points = leg["centerline"]
            if centerline and leg_points and centerline[-1] == leg_points[0]:
                leg_points = leg_points[1:]
            centerline.extend(_point(item) for item in leg_points)
        centerline = _dedupe(centerline)
    if len(centerline) < 2 or not validate_centerline(free_space, centerline):
        return _refusal(
            program=program,
            snapshot=snapshot,
            outcome="unreachable",
            ordered_anchor_ids=ordered_anchor_ids,
            context_fingerprint=context_fingerprint,
        )
    journey = seal_journey_solution({
        "movementProgramId": program["movementProgramId"],
        "navigationSnapshotId": snapshot["navigationSnapshotId"],
        "actorPlacementId": program["actorPlacementId"],
        "generationLayoutRevision": snapshot["layoutRevision"],
        "validationContextFingerprint": context_fingerprint,
        "outcome": "accepted",
        "orderedAnchorIds": ordered_anchor_ids,
        "networkEdgeIds": list(dict.fromkeys(network_edge_ids)),
        "centerline": centerline,
        "poses": _poses(centerline),
        "distanceMeters": _distance(centerline),
        "turnCount": _turn_count(centerline),
        "reverseUsed": False,
        "validation": {
            "identity": "pass",
            "topology": "pass",
            "direction": "pass",
            "physical": "pass",
            "authority": "pass",
            "stale": "pass",
        },
        "sourceRevisions": dict(snapshot["sourceRevisions"]),
        "plannerVersions": {
            "pedestrian": FACILITY_PEDESTRIAN_PLANNER_VERSION,
        },
    })
    return validate_journey_solution(journey)


def plan_vehicle_journey(
    layout: Mapping[str, Any],
    navigation_package: Mapping[str, Any],
    movement_program_id: str,
    *,
    vehicle_profile: Mapping[str, Any],
    load: Mapping[str, Any] | None = None,
    allow_reverse: bool | None = None,
) -> dict[str, Any]:
    """Plan one directed-lane vehicle journey and validate its full sweep."""

    snapshot = validate_navigation_snapshot(navigation_package["snapshot"])
    extension = _extension(layout)
    program = _program(extension, movement_program_id)
    if program["actorClass"] != "vehicle" or snapshot["actorClass"] != "vehicle":
        raise FacilityJourneyPlanningError(
            "facility_navigation_actor_class_mismatch",
            "The vehicle planner requires a vehicle program and snapshot.",
        )
    profile_revision = str(
        vehicle_profile.get("vehicleProfileRevision")
        or vehicle_profile.get("revision")
        or program["actorProfileRef"]["profileRevision"]
    )
    if (
        program["actorProfileRef"]["profileRevision"]
        != snapshot["actorProfileRevision"]
        or profile_revision != snapshot["actorProfileRevision"]
    ):
        raise FacilityJourneyPlanningError(
            "facility_navigation_actor_profile_mismatch",
            "The movement program, snapshot, and vehicle profile revisions differ.",
        )
    ordered_anchor_ids = _ordered_anchors(program)
    context_fingerprint = _fingerprint({
        "geometryContextFingerprint": snapshot["geometryContextFingerprint"],
        "program": program,
        "vehicleProfile": vehicle_profile,
        "load": load,
        "allowReverse": allow_reverse,
        "plannerVersion": FACILITY_VEHICLE_JOURNEY_PLANNER_VERSION,
    })
    anchors = _anchor_nodes(navigation_package)
    if not ordered_anchor_ids or any(
        anchor_id not in anchors for anchor_id in ordered_anchor_ids
    ):
        return _refusal(
            program=program,
            snapshot=snapshot,
            outcome="unreachable",
            ordered_anchor_ids=ordered_anchor_ids,
            context_fingerprint=context_fingerprint,
        )
    if not navigation_package.get("tracks"):
        return _refusal(
            program=program,
            snapshot=snapshot,
            outcome="authority_missing",
            ordered_anchor_ids=ordered_anchor_ids,
            context_fingerprint=context_fingerprint,
            authority="unknown",
        )
    if program["loopMode"] == "paired_lane_return":
        destination_id = ordered_anchor_ids[len(program["orderedStops"]) - 1]
        anchor_records = {
            str(item.get("navigationAnchorId")): item
            for item in navigation_package.get("anchorRecords", [])
            if isinstance(item, Mapping)
        }
        if anchor_records.get(destination_id, {}).get("anchorKind") != "vehicle_turnaround":
            return _refusal(
                program=program,
                snapshot=snapshot,
                outcome="authority_missing",
                ordered_anchor_ids=ordered_anchor_ids,
                context_fingerprint=context_fingerprint,
                authority="unknown",
            )
        directional_tracks = [
            item
            for item in navigation_package["tracks"]
            if isinstance(item.get("laneBinding"), Mapping)
            and item["laneBinding"].get("status") == "direction_markings"
        ]
        if len(directional_tracks) < 2:
            return _refusal(
                program=program,
                snapshot=snapshot,
                outcome="authority_missing",
                ordered_anchor_ids=ordered_anchor_ids,
                context_fingerprint=context_fingerprint,
                authority="unknown",
            )

    centerline: list[dict[str, float]] = []
    network_edge_ids: list[str] = []
    used_sources_by_leg: list[set[str]] = []
    remaining_routes = set(program["requiredRouteIds"])
    forbidden_routes = set(program["forbiddenRouteIds"])
    for leg_index, (left_anchor, right_anchor) in enumerate(
        zip(ordered_anchor_ids, ordered_anchor_ids[1:])
    ):
        network = _network_path(
            navigation_package,
            str(anchors[left_anchor]["nodeId"]),
            str(anchors[right_anchor]["nodeId"]),
            required_route_ids=(
                remaining_routes
                if leg_index == len(ordered_anchor_ids) - 2
                else set()
            ),
            forbidden_route_ids=forbidden_routes,
        )
        if network is None:
            return _refusal(
                program=program,
                snapshot=snapshot,
                outcome="unreachable",
                ordered_anchor_ids=ordered_anchor_ids,
                context_fingerprint=context_fingerprint,
            )
        leg_points, leg_edges, used_sources = network
        if centerline and leg_points and centerline[-1] == leg_points[0]:
            leg_points = leg_points[1:]
        centerline.extend(_point(item) for item in leg_points)
        network_edge_ids.extend(leg_edges)
        used_sources_by_leg.append(set(used_sources))
        remaining_routes.difference_update(used_sources)
    centerline = _dedupe(centerline)
    if remaining_routes:
        return _refusal(
            program=program,
            snapshot=snapshot,
            outcome="constraint_conflict",
            ordered_anchor_ids=ordered_anchor_ids,
            context_fingerprint=context_fingerprint,
        )
    if program["loopMode"] == "paired_lane_return" and len(used_sources_by_leg) >= 2:
        route_ids = set(program["requiredRouteIds"])
        outbound_marks = used_sources_by_leg[0] - route_ids
        return_marks = used_sources_by_leg[-1] - route_ids
        if not outbound_marks or not return_marks or outbound_marks == return_marks:
            return _refusal(
                program=program,
                snapshot=snapshot,
                outcome="constraint_conflict",
                ordered_anchor_ids=ordered_anchor_ids,
                context_fingerprint=context_fingerprint,
            )

    route_index = {
        str(item.get("routeId")): item
        for item in layout.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    }
    used_route_ids = sorted(
        {
            source
            for sources in used_sources_by_leg
            for source in sources
            if source in route_index
        }
    )
    traversable = [
        polygon
        for route_id in used_route_ids
        for polygon in route_traversable_corridor(route_index[route_id])
    ]
    poses = _poses(centerline)
    swept = validate_swept_volume(
        poses,
        vehicle_profile,
        traversable_polygons=traversable,
        obstacles=[
            {
                "obstacleId": item["obstacleId"],
                "boundary": item["exterior"],
            }
            for item in navigation_package.get("sourceObstaclePolygons", [])
        ],
        load=load,
        allow_reverse=allow_reverse,
    )
    accepted = bool(swept.get("valid"))
    journey = seal_journey_solution({
        "movementProgramId": program["movementProgramId"],
        "navigationSnapshotId": snapshot["navigationSnapshotId"],
        "actorPlacementId": program["actorPlacementId"],
        "generationLayoutRevision": snapshot["layoutRevision"],
        "validationContextFingerprint": context_fingerprint,
        "outcome": "accepted" if accepted else "physical_validation_refused",
        "orderedAnchorIds": ordered_anchor_ids,
        "networkEdgeIds": list(dict.fromkeys(network_edge_ids)),
        "centerline": centerline,
        "poses": poses,
        "distanceMeters": _distance(centerline),
        "turnCount": _turn_count(centerline),
        "reverseUsed": any(item.get("gear") == "reverse" for item in poses),
        "validation": {
            "identity": "pass",
            "topology": "pass",
            "direction": "pass",
            "physical": "pass" if accepted else "refused",
            "authority": "pass",
            "stale": "pass",
        },
        "sourceRevisions": dict(snapshot["sourceRevisions"]),
        "plannerVersions": {
            "vehicle": FACILITY_VEHICLE_JOURNEY_PLANNER_VERSION,
            "lane_binding": FACILITY_MOTION_LANE_BINDING_VERSION,
            "router": ROUTER_VERSION,
            "routing_engine": ROUTING_ENGINE_VERSION,
            "swept_envelope": SWEPT_ENVELOPE_REVISION,
        },
    })
    return validate_journey_solution(journey)


def journey_solution_summary(journey: Mapping[str, Any]) -> dict[str, Any]:
    value = validate_journey_solution(journey)
    return {
        "schemaVersion": "facility-navigation-journey-summary-v1",
        "journeySolutionId": value["journeySolutionId"],
        "movementProgramId": value["movementProgramId"],
        "actorPlacementId": value["actorPlacementId"],
        "outcome": value["outcome"],
        "distanceMeters": value["distanceMeters"],
        "turnCount": value["turnCount"],
        "orderedAnchorIds": list(value["orderedAnchorIds"]),
        "validation": deepcopy(value["validation"]),
        "solutionFingerprint": value["solutionFingerprint"],
        "qualification": FACILITY_JOURNEY_QUALIFICATION,
    }


class FacilityJourneySolutionStore:
    """Bounded immutable process-local cache for derived journey solutions."""

    def __init__(self, maximum_items: int = FACILITY_JOURNEY_STORE_MAXIMUM) -> None:
        self.maximum_items = int(maximum_items)
        if self.maximum_items < 1:
            raise ValueError("maximum_items must be positive")
        self._lock = threading.RLock()
        self._values: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def put(self, journey: Mapping[str, Any]) -> dict[str, Any]:
        value = validate_journey_solution(journey)
        identity = str(value["journeySolutionId"])
        with self._lock:
            self._values[identity] = deepcopy(value)
            self._values.move_to_end(identity)
            while len(self._values) > self.maximum_items:
                self._values.popitem(last=False)
        return deepcopy(value)

    def get(self, journey_solution_id: str) -> dict[str, Any]:
        with self._lock:
            value = self._values.get(str(journey_solution_id))
            if value is None:
                raise FacilityNotFoundError(
                    "facility_navigation_journey_unavailable",
                    "The requested journey solution is unavailable.",
                )
            self._values.move_to_end(str(journey_solution_id))
            return deepcopy(value)


__all__ = [
    "FACILITY_JOURNEY_ALTERNATIVE_MAXIMUM",
    "FACILITY_JOURNEY_STORE_MAXIMUM",
    "FACILITY_PEDESTRIAN_PLANNER_VERSION",
    "FACILITY_VEHICLE_JOURNEY_PLANNER_VERSION",
    "FacilityJourneyPlanningError",
    "FacilityJourneySolutionStore",
    "journey_solution_summary",
    "plan_pedestrian_journey",
    "plan_vehicle_journey",
]
