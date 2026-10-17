"""Immutable multi-actor presentation packages for Facility Layout playback."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import math
from threading import RLock
import time
from typing import Any, Callable, Mapping, Sequence

from .errors import FacilityNotFoundError, FacilityValidationError
from .activity_visuals import (
    FACILITY_ACTIVITY_VISUAL_ALIGNMENT_AUTHORITY,
    FACILITY_ACTIVITY_VISUAL_FORWARD_AXES,
)
from .lean_motion import (
    FACILITY_LEAN_MOTION_QUALIFICATION,
    FACILITY_LEAN_MOTION_SCHEMA_VERSION,
)


FACILITY_ACTIVITY_SCENARIO_SCHEMA_VERSION = "facility-activity-scenario-v6"
FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION = (
    "facility-activity-scenario-v7"
)
FACILITY_ACTIVITY_SCENARIO_QUALIFICATION = (
    "Prototype activity playback presents independently revision-bound route "
    "results on one shared display clock. It is not a discrete-event simulation "
    "and does not establish traffic safety, throughput, utilization, staffing, "
    "machine cycles, or regulatory compliance."
)
FACILITY_NAVIGATION_ACTIVITY_QUALIFICATION = (
    "Prototype navigation playback presents accepted revision-bound actor "
    "journeys on one shared display clock. Path intersections and sampled "
    "center proximity are presentation diagnostics, not safety, capacity, "
    "staffing, timing, or regulatory findings."
)
FACILITY_NAVIGATION_PRESENTATION_SCHEMA = "facility-navigation-presentation-v1"
FACILITY_NAVIGATION_PRESENTATION_QUALIFICATION = (
    "Derived display diagnostics preserve accepted journey geometry and do not "
    "reschedule actors or alter paths to conceal visual overlap."
)
FACILITY_ACTIVITY_SCENARIO_MAXIMUM_ACTORS = 24
FACILITY_ACTIVITY_SCENARIO_MAXIMUM_CANONICAL_BYTES = 65_536
FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS = 64
FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_CANONICAL_BYTES = 524_288
FACILITY_ACTIVITY_SCENARIO_STORE_TTL_SECONDS = 900.0
FACILITY_ACTIVITY_SCENARIO_STORE_MAXIMUM_ENTRIES = 32


class FacilityActivityScenarioError(FacilityValidationError):
    """Raised when a scenario violates its closed presentation contract."""


def _validate_navigation_presentation(
    value: Any,
    actors_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    item = value if isinstance(value, Mapping) else None
    if item is None:
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "Navigation activity requires a closed presentation record.",
        )
    _exact_keys(
        item,
        {
            "schemaVersion",
            "qualification",
            "sharedClock",
            "processTimingClaimed",
            "generatedCollisionAvoidanceOffsets",
            "phaseOffsets",
            "pathBindings",
            "pathIntersections",
            "sampledProximity",
            "handoffResultIds",
        },
        "scenario.navigationPresentation",
    )
    if item["schemaVersion"] != FACILITY_NAVIGATION_PRESENTATION_SCHEMA:
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "Unsupported navigation presentation schema.",
        )
    if item["qualification"] != FACILITY_NAVIGATION_PRESENTATION_QUALIFICATION:
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "The navigation presentation qualification changed.",
        )
    if item["sharedClock"] is not True or item["processTimingClaimed"] is not False:
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "Navigation playback requires one display clock with no process-timing claim.",
        )
    if item["generatedCollisionAvoidanceOffsets"] is not False:
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_rescheduling_prohibited",
            "Generated offsets may not hide a visual path conflict.",
        )
    actor_ids = set(actors_by_id)
    phase_offsets = item["phaseOffsets"]
    if not isinstance(phase_offsets, list) or len(phase_offsets) != len(actor_ids):
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "Every actor requires one explicit presentation phase record.",
        )
    phase_actor_ids = set()
    for index, phase in enumerate(phase_offsets):
        path = f"scenario.navigationPresentation.phaseOffsets[{index}]"
        if not isinstance(phase, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                f"{path} must be an object.",
            )
        _exact_keys(phase, {"actorId", "offsetSeconds", "authority"}, path)
        actor_id = _text(phase["actorId"], f"{path}.actorId")
        if actor_id not in actor_ids or actor_id in phase_actor_ids:
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                "Presentation phase records must bind each actor exactly once.",
            )
        phase_actor_ids.add(actor_id)
        offset = _number(phase["offsetSeconds"], f"{path}.offsetSeconds")
        authority = phase["authority"]
        if authority not in {"none", "user_authored", "controlled_source"}:
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                "Unsupported presentation phase authority.",
            )
        if authority == "none" and offset != 0:
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_rescheduling_prohibited",
                "An unauthorised presentation phase offset must remain zero.",
            )
        if not math.isclose(
            offset,
            float(actors_by_id[actor_id]["startOffsetSeconds"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                "Actor timing and its authority record disagree.",
            )
    path_bindings = item["pathBindings"]
    if not isinstance(path_bindings, list) or len(path_bindings) != len(actor_ids):
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "Every actor requires one package-backed path binding.",
        )
    bound_actors = set()
    for index, binding in enumerate(path_bindings):
        path = f"scenario.navigationPresentation.pathBindings[{index}]"
        if not isinstance(binding, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                f"{path} must be an object.",
            )
        _exact_keys(
            binding,
            {
                "pathBindingId",
                "actorId",
                "actorClass",
                "journeySolutionId",
                "motionPackageId",
                "closed",
            },
            path,
        )
        actor_id = _text(binding["actorId"], f"{path}.actorId")
        actor = actors_by_id.get(actor_id)
        if actor is None or actor_id in bound_actors:
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                "Path bindings must bind every actor exactly once.",
            )
        bound_actors.add(actor_id)
        for field in ("pathBindingId", "journeySolutionId", "motionPackageId"):
            _text(binding[field], f"{path}.{field}")
        expected_class = "pedestrian" if actor["actorType"] == "operator" else "vehicle"
        if binding["actorClass"] != expected_class:
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                "Path binding actorClass does not match its activity actor.",
            )
        if binding["motionPackageId"] != actor["motionPackageId"]:
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                "Path binding and actor motion package identities differ.",
            )
        if not isinstance(binding["closed"], bool):
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                f"{path}.closed must be boolean.",
            )
    intersections = item["pathIntersections"]
    if not isinstance(intersections, list):
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "pathIntersections must be an array.",
        )
    for index, intersection in enumerate(intersections):
        path = f"scenario.navigationPresentation.pathIntersections[{index}]"
        if not isinstance(intersection, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                f"{path} must be an object.",
            )
        _exact_keys(
            intersection,
            {"conflictId", "actorIds", "position", "evidenceStatus"},
            path,
        )
        _text(intersection["conflictId"], f"{path}.conflictId")
        ids = intersection["actorIds"]
        if (
            not isinstance(ids, list)
            or len(ids) != 2
            or ids != sorted(set(ids))
            or any(actor_id not in actor_ids for actor_id in ids)
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                "Each path intersection must bind two sorted existing actors.",
            )
        position = intersection["position"]
        if not isinstance(position, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                f"{path}.position must be an object.",
            )
        _exact_keys(position, {"x", "z"}, f"{path}.position")
        _number(position["x"], f"{path}.position.x")
        _number(position["z"], f"{path}.position.z")
        if intersection["evidenceStatus"] != "derived":
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                "Path intersections remain derived presentation evidence.",
            )
    proximity = item["sampledProximity"]
    if not isinstance(proximity, Mapping):
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "sampledProximity must be an object.",
        )
    _exact_keys(
        proximity,
        {"sampleCount", "pairMinimums", "qualification"},
        "scenario.navigationPresentation.sampledProximity",
    )
    sample_count = proximity["sampleCount"]
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or not 2 <= sample_count <= 1001:
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "sampledProximity.sampleCount is outside the supported range.",
        )
    if proximity["qualification"] != (
        "Center-distance samples on the shared display clock; not a collision or safety assessment."
    ):
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "The sampled-proximity qualification changed.",
        )
    pair_minimums = proximity["pairMinimums"]
    if not isinstance(pair_minimums, list):
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "sampledProximity.pairMinimums must be an array.",
        )
    for index, pair in enumerate(pair_minimums):
        path = f"scenario.navigationPresentation.sampledProximity.pairMinimums[{index}]"
        if not isinstance(pair, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                f"{path} must be an object.",
            )
        _exact_keys(
            pair,
            {"actorIds", "centerDistanceMeters", "normalizedTime"},
            path,
        )
        ids = pair["actorIds"]
        if not isinstance(ids, list) or len(ids) != 2 or ids != sorted(set(ids)):
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                "Sampled-proximity pairs require two sorted actors.",
            )
        _number(pair["centerDistanceMeters"], f"{path}.centerDistanceMeters")
        normalized = _number(pair["normalizedTime"], f"{path}.normalizedTime")
        if normalized > 1:
            raise FacilityActivityScenarioError(
                "facility_activity_navigation_presentation_invalid",
                "sampled proximity normalizedTime must be within zero and one.",
            )
    handoff_ids = item["handoffResultIds"]
    if not isinstance(handoff_ids, list) or any(
        not isinstance(identity, str) or not identity for identity in handoff_ids
    ) or len(handoff_ids) != len(set(handoff_ids)):
        raise FacilityActivityScenarioError(
            "facility_activity_navigation_presentation_invalid",
            "handoffResultIds must contain unique stable identities.",
        )


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "The activity scenario is not canonical JSON.",
        ) from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            f"{field} must be a non-empty string.",
        )
    return value.strip()


def _number(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            f"{field} must be a number.",
        )
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            f"{field} is outside the supported range.",
        )
    return result


def _exact_keys(
    value: Mapping[str, Any],
    required: set[str],
    field: str,
) -> None:
    keys = set(value)
    if keys != required:
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            f"{field} has unsupported or missing fields.",
            details={
                "missingFields": sorted(required - keys),
                "unknownFields": sorted(keys - required),
            },
        )


def _validate_lean_motion(
    lean_motion: Any,
    actors_by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    actor_ids = set(actors_by_id)
    if not isinstance(lean_motion, Mapping):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "scenario.leanMotion must be an object.",
        )
    _exact_keys(
        lean_motion,
        {
            "schemaVersion",
            "qualification",
            "evidenceStatus",
            "operatorPaths",
            "pedestrianConnections",
            "assistanceGates",
            "materialHandoffs",
            "fifoPoints",
        },
        "scenario.leanMotion",
    )
    if lean_motion["schemaVersion"] != FACILITY_LEAN_MOTION_SCHEMA_VERSION:
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "Unsupported Facility lean-motion schema.",
        )
    if lean_motion["qualification"] != FACILITY_LEAN_MOTION_QUALIFICATION:
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "The mandatory lean-motion qualification was changed.",
        )
    if lean_motion["evidenceStatus"] != "derived":
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "Lean-motion presentation must retain derived evidence status.",
        )

    def validate_point(point: Any, field: str) -> None:
        if not isinstance(point, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field} must be an object.",
            )
        _exact_keys(point, {"x", "z"}, field)
        _number(point["x"], f"{field}.x", minimum=-10000.0)
        _number(point["z"], f"{field}.z", minimum=-10000.0)

    operator_paths = lean_motion["operatorPaths"]
    if not isinstance(operator_paths, list):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "scenario.leanMotion.operatorPaths must be an array.",
        )
    path_ids: set[str] = set()
    path_actor_ids: set[str] = set()
    path_actor_by_id: dict[str, str] = {}
    for index, path in enumerate(operator_paths):
        field = f"scenario.leanMotion.operatorPaths[{index}]"
        if not isinstance(path, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field} must be an object.",
            )
        _exact_keys(
            path,
            {
                "pathId",
                "actorId",
                "zoneId",
                "pathKind",
                "segmentIndex",
                "segmentCount",
                "assignedPlacementIds",
                "centerline",
                "closed",
                "evidenceStatus",
            },
            field,
        )
        path_id = _text(path["pathId"], f"{field}.pathId")
        actor_id = _text(path["actorId"], f"{field}.actorId")
        _text(path["zoneId"], f"{field}.zoneId")
        if path["pathKind"] not in {"cell_work_loop", "split_station_loop"}:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field}.pathKind is unsupported.",
            )
        segment_index = path["segmentIndex"]
        segment_count = path["segmentCount"]
        if (
            isinstance(segment_index, bool)
            or not isinstance(segment_index, int)
            or isinstance(segment_count, bool)
            or not isinstance(segment_count, int)
            or segment_index < 0
            or segment_count < 1
            or segment_index >= segment_count
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field} has an invalid station-segment index.",
            )
        assigned = path["assignedPlacementIds"]
        if not isinstance(assigned, list):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field}.assignedPlacementIds must be an array.",
            )
        assigned_ids = [
            _text(value, f"{field}.assignedPlacementIds[{assigned_index}]")
            for assigned_index, value in enumerate(assigned)
        ]
        if len(set(assigned_ids)) != len(assigned_ids):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field}.assignedPlacementIds must be unique.",
            )
        if (
            path_id in path_ids
            or actor_id in path_actor_ids
            or actor_id not in actor_ids
            or path["closed"] is not True
            or path["evidenceStatus"] != "derived"
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                "Lean-motion operator paths require unique actor-bound derived IDs.",
            )
        path_ids.add(path_id)
        path_actor_ids.add(actor_id)
        path_actor_by_id[path_id] = actor_id
        centerline = path["centerline"]
        if not isinstance(centerline, list) or len(centerline) < 4:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field}.centerline requires a closed path.",
            )
        for point_index, point in enumerate(centerline):
            validate_point(point, f"{field}.centerline[{point_index}]")
        if centerline[0] != centerline[-1]:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field}.centerline must close exactly.",
            )

    connections = lean_motion["pedestrianConnections"]
    if not isinstance(connections, list):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "scenario.leanMotion.pedestrianConnections must be an array.",
        )
    connection_ids: set[str] = set()
    connections_by_id: dict[str, Mapping[str, Any]] = {}
    for index, connection in enumerate(connections):
        field = f"scenario.leanMotion.pedestrianConnections[{index}]"
        if not isinstance(connection, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field} must be an object.",
            )
        _exact_keys(
            connection,
            {
                "connectionId",
                "actorId",
                "pathId",
                "zoneId",
                "fifoPointId",
                "handoffIds",
                "role",
                "motionPackageIds",
                "centerline",
                "closed",
                "evidenceStatus",
            },
            field,
        )
        connection_id = _text(
            connection["connectionId"],
            f"{field}.connectionId",
        )
        for name in ("actorId", "pathId", "zoneId", "fifoPointId"):
            _text(connection[name], f"{field}.{name}")
        handoff_ids = connection["handoffIds"]
        motion_package_ids = connection["motionPackageIds"]
        if not isinstance(handoff_ids, list) or not handoff_ids:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field}.handoffIds must contain at least one handoff ID.",
            )
        handoff_ids = [
            _text(value, f"{field}.handoffIds[{item_index}]")
            for item_index, value in enumerate(handoff_ids)
        ]
        if (
            not isinstance(motion_package_ids, list)
            or len(motion_package_ids) != 2
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field}.motionPackageIds must bind the FIFO approach and return.",
            )
        motion_package_ids = [
            _text(value, f"{field}.motionPackageIds[{item_index}]")
            for item_index, value in enumerate(motion_package_ids)
        ]
        actor_id = connection["actorId"]
        path_id = connection["pathId"]
        actor = actors_by_id.get(actor_id)
        if (
            connection_id in connection_ids
            or connection["evidenceStatus"] != "derived"
            or actor_id not in actor_ids
            or path_id not in path_ids
            or path_actor_by_id.get(path_id) != actor_id
            or connection["role"] not in {"input", "output"}
            or connection["closed"] is not True
            or len(set(handoff_ids)) != len(handoff_ids)
            or len(set(motion_package_ids)) != 2
            or not isinstance(actor, Mapping)
            or actor.get("actorType") != "operator"
            or any(
                package_id not in actor.get("cycleMotionPackageIds", [])
                for package_id in motion_package_ids
            )
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                "FIFO access paths must bind one existing operator and two cycle packages.",
            )
        connection_ids.add(connection_id)
        connections_by_id[connection_id] = connection
        centerline = connection["centerline"]
        if not isinstance(centerline, list) or len(centerline) < 3:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field}.centerline requires a closed FIFO access path.",
            )
        for point_index, point in enumerate(centerline):
            validate_point(point, f"{field}.centerline[{point_index}]")
        if centerline[0] != centerline[-1]:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field}.centerline must return the existing operator to its local path.",
            )

    gates = lean_motion["assistanceGates"]
    if not isinstance(gates, list):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "scenario.leanMotion.assistanceGates must be an array.",
        )
    gate_ids: set[str] = set()
    for index, gate in enumerate(gates):
        field = f"scenario.leanMotion.assistanceGates[{index}]"
        if not isinstance(gate, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field} must be an object.",
            )
        _exact_keys(
            gate,
            {
                "gateId",
                "zoneId",
                "participantPathIds",
                "participantActorIds",
                "position",
                "evidenceStatus",
            },
            field,
        )
        gate_id = _text(gate["gateId"], f"{field}.gateId")
        _text(gate["zoneId"], f"{field}.zoneId")
        path_participants = gate["participantPathIds"]
        actor_participants = gate["participantActorIds"]
        if (
            not isinstance(path_participants, list)
            or not isinstance(actor_participants, list)
            or len(path_participants) != 2
            or len(actor_participants) != 2
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field} must bind exactly two operator paths and actors.",
            )
        path_participants = [
            _text(value, f"{field}.participantPathIds[{item_index}]")
            for item_index, value in enumerate(path_participants)
        ]
        actor_participants = [
            _text(value, f"{field}.participantActorIds[{item_index}]")
            for item_index, value in enumerate(actor_participants)
        ]
        if (
            gate_id in gate_ids
            or len(set(path_participants)) != 2
            or len(set(actor_participants)) != 2
            or gate["evidenceStatus"] != "derived"
            or any(path_id not in path_ids for path_id in path_participants)
            or any(actor_id not in actor_ids for actor_id in actor_participants)
            or any(
                path_actor_by_id[path_id] != actor_id
                for path_id, actor_id in zip(
                    path_participants,
                    actor_participants,
                )
            )
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                "Assistance gates must bind two existing operator paths and actors.",
            )
        gate_ids.add(gate_id)
        validate_point(gate["position"], f"{field}.position")

    fifo_points = lean_motion["fifoPoints"]
    if not isinstance(fifo_points, list):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "scenario.leanMotion.fifoPoints must be an array.",
        )
    fifo_ids: set[str] = set()
    fifo_by_id: dict[str, Mapping[str, Any]] = {}
    for index, point in enumerate(fifo_points):
        field = f"scenario.leanMotion.fifoPoints[{index}]"
        if not isinstance(point, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field} must be an object.",
            )
        _exact_keys(
            point,
            {"pointId", "zoneId", "role", "position", "evidenceStatus"},
            field,
        )
        point_id = _text(point["pointId"], f"{field}.pointId")
        _text(point["zoneId"], f"{field}.zoneId")
        if (
            point["role"] not in {"input", "output"}
            or point_id in fifo_ids
            or point["evidenceStatus"] != "derived"
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                "FIFO points must retain unique derived identities.",
            )
        fifo_ids.add(point_id)
        fifo_by_id[point_id] = point
        validate_point(point["position"], f"{field}.position")

    handoffs = lean_motion["materialHandoffs"]
    if not isinstance(handoffs, list):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "scenario.leanMotion.materialHandoffs must be an array.",
        )
    handoff_ids: set[str] = set()
    for index, handoff in enumerate(handoffs):
        field = f"scenario.leanMotion.materialHandoffs[{index}]"
        if not isinstance(handoff, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field} must be an object.",
            )
        _exact_keys(
            handoff,
            {
                "handoffId",
                "fromZoneId",
                "toZoneId",
                "centerline",
                "fromPointId",
                "toPointId",
                "fromPathId",
                "toPathId",
                "fromActorId",
                "toActorId",
                "fromConnectionId",
                "toConnectionId",
                "evidenceStatus",
            },
            field,
        )
        handoff_id = _text(handoff["handoffId"], f"{field}.handoffId")
        for name in (
            "fromZoneId",
            "toZoneId",
            "fromPointId",
            "toPointId",
            "fromPathId",
            "toPathId",
            "fromActorId",
            "toActorId",
            "fromConnectionId",
            "toConnectionId",
        ):
            _text(handoff[name], f"{field}.{name}")
        from_point = fifo_by_id.get(handoff["fromPointId"])
        to_point = fifo_by_id.get(handoff["toPointId"])
        from_connection = connections_by_id.get(handoff["fromConnectionId"])
        to_connection = connections_by_id.get(handoff["toConnectionId"])
        if (
            handoff_id in handoff_ids
            or handoff["evidenceStatus"] != "derived"
            or handoff["fromPointId"] not in fifo_ids
            or handoff["toPointId"] not in fifo_ids
            or handoff["fromPathId"] not in path_ids
            or handoff["toPathId"] not in path_ids
            or handoff["fromActorId"] not in actor_ids
            or handoff["toActorId"] not in actor_ids
            or handoff["fromActorId"] == handoff["toActorId"]
            or path_actor_by_id.get(handoff["fromPathId"])
                != handoff["fromActorId"]
            or path_actor_by_id.get(handoff["toPathId"])
                != handoff["toActorId"]
            or not isinstance(from_point, Mapping)
            or not isinstance(to_point, Mapping)
            or from_point.get("zoneId") != handoff["fromZoneId"]
            or to_point.get("zoneId") != handoff["toZoneId"]
            or from_point.get("role") != "output"
            or to_point.get("role") != "input"
            or not isinstance(from_connection, Mapping)
            or not isinstance(to_connection, Mapping)
            or from_connection.get("actorId") != handoff["fromActorId"]
            or to_connection.get("actorId") != handoff["toActorId"]
            or from_connection.get("pathId") != handoff["fromPathId"]
            or to_connection.get("pathId") != handoff["toPathId"]
            or from_connection.get("fifoPointId") != handoff["fromPointId"]
            or to_connection.get("fifoPointId") != handoff["toPointId"]
            or handoff_id not in from_connection.get("handoffIds", [])
            or handoff_id not in to_connection.get("handoffIds", [])
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                "Material handoffs must bind two existing endpoint operators to derived FIFO access paths.",
            )
        handoff_ids.add(handoff_id)
        centerline = handoff["centerline"]
        if not isinstance(centerline, list) or len(centerline) < 2:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"{field}.centerline requires at least two points.",
            )
        for point_index, point in enumerate(centerline):
            validate_point(point, f"{field}.centerline[{point_index}]")
        if (
            centerline[0] != from_point["position"]
            or centerline[-1] != to_point["position"]
            or from_point["position"] not in from_connection["centerline"]
            or to_point["position"] not in to_connection["centerline"]
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                "Material handoff endpoints must be visited by both bound operators.",
                details={
                    "handoffId": handoff_id,
                    "handoffStartsAtOutputFifo": (
                        centerline[0] == from_point["position"]
                    ),
                    "handoffEndsAtInputFifo": (
                        centerline[-1] == to_point["position"]
                    ),
                    "outputOperatorVisitsFifo": (
                        from_point["position"] in from_connection["centerline"]
                    ),
                    "inputOperatorVisitsFifo": (
                        to_point["position"] in to_connection["centerline"]
                    ),
                },
            )

    for connection_id, connection in connections_by_id.items():
        point = fifo_by_id.get(connection["fifoPointId"])
        if (
            not isinstance(point, Mapping)
            or point.get("zoneId") != connection["zoneId"]
            or point.get("role") != connection["role"]
            or point.get("position") not in connection["centerline"]
            or any(
                handoff_id not in handoff_ids
                for handoff_id in connection["handoffIds"]
            )
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"FIFO access path {connection_id} is not covered by a complete handoff.",
            )


def validate_facility_activity_scenario(
    scenario: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the closed scenario schema and return a detached copy."""

    if not isinstance(scenario, Mapping):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "The activity scenario must be an object.",
        )
    value = deepcopy(dict(scenario))
    schema_version = value.get("schemaVersion")
    navigation_activity = schema_version == (
        FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION
    )
    _exact_keys(
        value,
        {
            "schemaVersion",
            "scenarioId",
            "layoutRevision",
            "label",
            "qualification",
            "prototypeMode",
            "repeat",
            "cycleDurationSeconds",
            "actors",
            "leanMotion",
            "stationaryEvidence",
            "unavailableActivity",
        } | ({"navigationPresentation"} if navigation_activity else set()),
        "scenario",
    )
    if schema_version not in {
        FACILITY_ACTIVITY_SCENARIO_SCHEMA_VERSION,
        FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION,
    }:
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_schema_unsupported",
            "Unsupported Facility activity scenario schema.",
        )
    scenario_id = _text(value["scenarioId"], "scenario.scenarioId")
    _text(value["layoutRevision"], "scenario.layoutRevision")
    _text(value["label"], "scenario.label")
    expected_qualification = (
        FACILITY_NAVIGATION_ACTIVITY_QUALIFICATION
        if navigation_activity
        else FACILITY_ACTIVITY_SCENARIO_QUALIFICATION
    )
    if value["qualification"] != expected_qualification:
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_qualification_invalid",
            "The mandatory activity qualification was changed.",
        )
    if value["prototypeMode"] is not True:
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_prototype_required",
            "Activity scenarios are currently available only in explicit prototype mode.",
        )
    if not isinstance(value["repeat"], bool):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "scenario.repeat must be a boolean.",
        )
    _number(
        value["cycleDurationSeconds"],
        "scenario.cycleDurationSeconds",
        minimum=0.001,
    )
    actors = value["actors"]
    maximum_actors = (FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS
                      if navigation_activity else FACILITY_ACTIVITY_SCENARIO_MAXIMUM_ACTORS)
    if (
        not isinstance(actors, list)
        or not actors
        or len(actors) > maximum_actors
    ):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_actor_limit",
            "The activity scenario actor count is outside the supported range.",
            details={
                "maximumActors": maximum_actors,
            },
        )
    actor_ids: set[str] = set()
    placement_ids: set[str] = set()
    for index, actor in enumerate(actors):
        if not isinstance(actor, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}] must be an object.",
            )
        _exact_keys(
            actor,
            {
                "actorId",
                "actorType",
                "label",
                "motionPackageId",
                "returnMotionPackageId",
                "endTransferMotionPackageId",
                "startTransferMotionPackageId",
                "cycleMotionPackageIds",
                "placementId",
                "assetDefinitionRef",
                "routeId",
                "departmentZoneIds",
                "startOffsetSeconds",
                "repeat",
                "loopMode",
                "endpointTurnSeconds",
                "visualAlignment",
            },
            f"scenario.actors[{index}]",
        )
        actor_id = _text(actor["actorId"], f"scenario.actors[{index}].actorId")
        placement_id = _text(
            actor["placementId"],
            f"scenario.actors[{index}].placementId",
        )
        if actor_id in actor_ids or placement_id in placement_ids:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_duplicate_actor",
                "Actor and placement identities must be unique within a scenario.",
            )
        actor_ids.add(actor_id)
        placement_ids.add(placement_id)
        if actor["actorType"] not in {"vehicle", "operator", "mobile_equipment"}:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].actorType is unsupported.",
            )
        _text(actor["label"], f"scenario.actors[{index}].label")
        _text(
            actor["motionPackageId"],
            f"scenario.actors[{index}].motionPackageId",
        )
        loop_package_ids = {
            field: actor[field]
            for field in (
                "returnMotionPackageId",
                "endTransferMotionPackageId",
                "startTransferMotionPackageId",
            )
        }
        for field, package_id in loop_package_ids.items():
            if package_id is not None:
                _text(package_id, f"scenario.actors[{index}].{field}")
        _text(actor["routeId"], f"scenario.actors[{index}].routeId")
        asset_ref = actor["assetDefinitionRef"]
        if not isinstance(asset_ref, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].assetDefinitionRef must be an object.",
            )
        _exact_keys(
            asset_ref,
            {"assetId", "assetDefinitionRevision"},
            f"scenario.actors[{index}].assetDefinitionRef",
        )
        _text(asset_ref["assetId"], f"scenario.actors[{index}].assetId")
        _text(
            asset_ref["assetDefinitionRevision"],
            f"scenario.actors[{index}].assetDefinitionRevision",
        )
        department_ids = actor["departmentZoneIds"]
        if not isinstance(department_ids, list) or any(
            not isinstance(item, str) or not item for item in department_ids
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].departmentZoneIds must contain stable IDs.",
            )
        if len(department_ids) != len(set(department_ids)):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].departmentZoneIds contains duplicates.",
            )
        _number(
            actor["startOffsetSeconds"],
            f"scenario.actors[{index}].startOffsetSeconds",
        )
        if not isinstance(actor["repeat"], bool):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].repeat must be a boolean.",
            )
        loop_mode = actor["loopMode"]
        expected_loop_modes = (
            {"ping_pong", "paired_lanes", "closed_path"}
            | ({"journey_cycle"} if navigation_activity else set())
            if actor["repeat"] else {"once"}
        )
        if loop_mode not in expected_loop_modes:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].loopMode must be "
                f"one of {sorted(expected_loop_modes)}.",
            )
        paired_package_ids = list(loop_package_ids.values())
        cycle_package_ids = actor["cycleMotionPackageIds"]
        if not isinstance(cycle_package_ids, list) or any(
            not isinstance(package_id, str) or not package_id
            for package_id in cycle_package_ids
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].cycleMotionPackageIds must contain "
                "package IDs.",
            )
        if loop_mode == "paired_lanes":
            if any(package_id is None for package_id in paired_package_ids):
                raise FacilityActivityScenarioError(
                    "facility_activity_scenario_invalid",
                    f"scenario.actors[{index}] paired_lanes requires return "
                    "and endpoint-transfer packages.",
                )
            all_package_ids = [actor["motionPackageId"], *paired_package_ids]
            if len(all_package_ids) != len(set(all_package_ids)):
                raise FacilityActivityScenarioError(
                    "facility_activity_scenario_invalid",
                    f"scenario.actors[{index}] loop package IDs must be unique.",
                )
            if cycle_package_ids:
                raise FacilityActivityScenarioError(
                    "facility_activity_scenario_invalid",
                    f"scenario.actors[{index}] paired_lanes cannot also bind a "
                    "closed-path package cycle.",
                )
        elif loop_mode == "closed_path":
            if any(package_id is not None for package_id in paired_package_ids):
                raise FacilityActivityScenarioError(
                    "facility_activity_scenario_invalid",
                    f"scenario.actors[{index}] closed_path cannot bind paired-lane "
                    "packages.",
                )
            if (
                len(cycle_package_ids) < 3
                or cycle_package_ids[0] != actor["motionPackageId"]
                or len(cycle_package_ids) != len(set(cycle_package_ids))
            ):
                raise FacilityActivityScenarioError(
                    "facility_activity_scenario_invalid",
                    f"scenario.actors[{index}] closed_path requires at least three "
                    "unique packages beginning with motionPackageId.",
                )
        elif loop_mode == "journey_cycle":
            if any(package_id is not None for package_id in paired_package_ids) or cycle_package_ids:
                raise FacilityActivityScenarioError(
                    "facility_activity_scenario_invalid",
                    f"scenario.actors[{index}] journey_cycle uses one accepted journey package.",
                )
        elif any(package_id is not None for package_id in paired_package_ids):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}] may bind lane-transfer packages only "
                "for paired_lanes playback.",
            )
        elif cycle_package_ids:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}] may bind cycle packages only for "
                "closed_path playback.",
            )
        endpoint_turn_seconds = _number(
            actor["endpointTurnSeconds"],
            f"scenario.actors[{index}].endpointTurnSeconds",
            minimum=0.1 if loop_mode in {"ping_pong", "closed_path"} else 0.0,
        )
        if (
            endpoint_turn_seconds > 10
            or (
                loop_mode not in {"ping_pong", "closed_path"}
                and endpoint_turn_seconds != 0
            )
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].endpointTurnSeconds is outside "
                "the supported range.",
            )
        visual_alignment = actor["visualAlignment"]
        if not isinstance(visual_alignment, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].visualAlignment must be an object.",
            )
        _exact_keys(
            visual_alignment,
            {"forwardAxis", "authority", "evidenceArtifact"},
            f"scenario.actors[{index}].visualAlignment",
        )
        if visual_alignment["forwardAxis"] not in (
            FACILITY_ACTIVITY_VISUAL_FORWARD_AXES
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].visualAlignment.forwardAxis is "
                "unsupported.",
            )
        if visual_alignment["authority"] != (
            FACILITY_ACTIVITY_VISUAL_ALIGNMENT_AUTHORITY
        ):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.actors[{index}].visualAlignment.authority is "
                "unsupported.",
            )
        _text(
            visual_alignment["evidenceArtifact"],
            f"scenario.actors[{index}].visualAlignment.evidenceArtifact",
        )
    _validate_lean_motion(
        value["leanMotion"],
        {actor["actorId"]: actor for actor in actors},
    )
    if navigation_activity:
        _validate_navigation_presentation(
            value["navigationPresentation"],
            {actor["actorId"]: actor for actor in actors},
        )
    stationary = value["stationaryEvidence"]
    if not isinstance(stationary, Mapping):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "scenario.stationaryEvidence must be an object.",
        )
    _exact_keys(
        stationary,
        {
            "placementCount",
            "assetTypeCount",
            "reason",
            "evidenceStatus",
        },
        "scenario.stationaryEvidence",
    )
    for field in ("placementCount", "assetTypeCount"):
        value_number = stationary[field]
        if isinstance(value_number, bool) or not isinstance(value_number, int) or value_number < 0:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.stationaryEvidence.{field} must be a non-negative integer.",
            )
    _text(stationary["reason"], "scenario.stationaryEvidence.reason")
    if stationary["evidenceStatus"] != "unknown":
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "Unsupported machine kinematics must retain unknown evidence status.",
        )
    unavailable = value["unavailableActivity"]
    if not isinstance(unavailable, list):
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_invalid",
            "scenario.unavailableActivity must be an array.",
        )
    for index, item in enumerate(unavailable):
        if not isinstance(item, Mapping):
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.unavailableActivity[{index}] must be an object.",
            )
        _exact_keys(
            item,
            {
                "actorType",
                "placementId",
                "routeId",
                "code",
                "reason",
                "evidenceStatus",
            },
            f"scenario.unavailableActivity[{index}]",
        )
        if item["actorType"] not in {
            "vehicle",
            "operator",
            "mobile_equipment",
        }:
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                f"scenario.unavailableActivity[{index}].actorType is unsupported.",
            )
        for field in ("placementId", "routeId", "code", "reason"):
            _text(
                item[field],
                f"scenario.unavailableActivity[{index}].{field}",
            )
        if item["evidenceStatus"] != "unknown":
            raise FacilityActivityScenarioError(
                "facility_activity_scenario_invalid",
                "Unavailable activity must not be promoted above unknown evidence.",
            )
    identity = deepcopy(value)
    identity.pop("scenarioId")
    expected_id = f"fas-{_hash(identity)}"
    if scenario_id != expected_id:
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_id_mismatch",
            "Facility activity scenario ID does not match its canonical content.",
        )
    encoded = _canonical_bytes(value)
    maximum_bytes = (FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_CANONICAL_BYTES
                     if navigation_activity else FACILITY_ACTIVITY_SCENARIO_MAXIMUM_CANONICAL_BYTES)
    if len(encoded) > maximum_bytes:
        raise FacilityActivityScenarioError(
            "facility_activity_scenario_too_large",
            "The activity scenario exceeds its canonical package budget.",
            details={
                "canonicalBytes": len(encoded),
                "maximumCanonicalBytes": (
                    maximum_bytes
                ),
            },
        )
    return value


def build_facility_activity_scenario(
    *,
    layout_revision: str,
    label: str,
    actors: Sequence[Mapping[str, Any]],
    cycle_duration_seconds: float,
    stationary_evidence: Mapping[str, Any],
    unavailable_activity: Sequence[Mapping[str, Any]] = (),
    lean_motion: Mapping[str, Any] | None = None,
    repeat: bool = True,
) -> dict[str, Any]:
    """Build one content-addressed scenario from existing package identities."""

    without_id = {
        "schemaVersion": FACILITY_ACTIVITY_SCENARIO_SCHEMA_VERSION,
        "layoutRevision": _text(layout_revision, "layoutRevision"),
        "label": _text(label, "label"),
        "qualification": FACILITY_ACTIVITY_SCENARIO_QUALIFICATION,
        "prototypeMode": True,
        "repeat": bool(repeat),
        "cycleDurationSeconds": round(
            _number(cycle_duration_seconds, "cycleDurationSeconds", minimum=0.001),
            6,
        ),
        "actors": deepcopy(list(actors)),
        "leanMotion": deepcopy(dict(lean_motion or {
            "schemaVersion": FACILITY_LEAN_MOTION_SCHEMA_VERSION,
            "qualification": FACILITY_LEAN_MOTION_QUALIFICATION,
            "evidenceStatus": "derived",
            "operatorPaths": [],
            "pedestrianConnections": [],
            "assistanceGates": [],
            "materialHandoffs": [],
            "fifoPoints": [],
        })),
        "stationaryEvidence": deepcopy(dict(stationary_evidence)),
        "unavailableActivity": deepcopy(list(unavailable_activity)),
    }
    scenario = {
        "scenarioId": f"fas-{_hash(without_id)}",
        **without_id,
    }
    return validate_facility_activity_scenario(scenario)


def build_navigation_activity_scenario(
    *,
    layout_revision: str,
    label: str,
    actors: Sequence[Mapping[str, Any]],
    cycle_duration_seconds: float,
    navigation_presentation: Mapping[str, Any],
    stationary_evidence: Mapping[str, Any],
    unavailable_activity: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build one bounded shared-clock scenario from journey package IDs."""

    without_id = {
        "schemaVersion": FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION,
        "layoutRevision": _text(layout_revision, "layoutRevision"),
        "label": _text(label, "label"),
        "qualification": FACILITY_NAVIGATION_ACTIVITY_QUALIFICATION,
        "prototypeMode": True,
        "repeat": True,
        "cycleDurationSeconds": round(
            _number(cycle_duration_seconds, "cycleDurationSeconds", minimum=0.001),
            6,
        ),
        "actors": deepcopy(list(actors)),
        "leanMotion": {
            "schemaVersion": FACILITY_LEAN_MOTION_SCHEMA_VERSION,
            "qualification": FACILITY_LEAN_MOTION_QUALIFICATION,
            "evidenceStatus": "derived",
            "operatorPaths": [],
            "pedestrianConnections": [],
            "assistanceGates": [],
            "materialHandoffs": [],
            "fifoPoints": [],
        },
        "navigationPresentation": deepcopy(dict(navigation_presentation)),
        "stationaryEvidence": deepcopy(dict(stationary_evidence)),
        "unavailableActivity": deepcopy(list(unavailable_activity)),
    }
    scenario = {
        "scenarioId": f"fas-{_hash(without_id)}",
        **without_id,
    }
    return validate_facility_activity_scenario(scenario)


def facility_activity_scenario_summary(
    scenario: Mapping[str, Any],
) -> dict[str, Any]:
    value = validate_facility_activity_scenario(scenario)
    actors = value["actors"]
    result = {
        "scenarioId": value["scenarioId"],
        "layoutRevision": value["layoutRevision"],
        "label": value["label"],
        "prototypeMode": True,
        "actorCount": len(actors),
        "actorTypeCounts": {
            actor_type: sum(
                actor["actorType"] == actor_type for actor in actors
            )
            for actor_type in ("vehicle", "operator", "mobile_equipment")
        },
        "routeCount": len({actor["routeId"] for actor in actors}),
        "leanMotionCounts": {
            "operatorPaths": len(value["leanMotion"]["operatorPaths"]),
            "pedestrianConnections": len(
                value["leanMotion"]["pedestrianConnections"]
            ),
            "assistanceGates": len(value["leanMotion"]["assistanceGates"]),
            "materialHandoffs": len(value["leanMotion"]["materialHandoffs"]),
            "fifoPoints": len(value["leanMotion"]["fifoPoints"]),
        },
        "departmentCount": len({
            zone_id
            for actor in actors
            for zone_id in actor["departmentZoneIds"]
        }),
        "cycleDurationSeconds": value["cycleDurationSeconds"],
        "stationaryEvidence": deepcopy(value["stationaryEvidence"]),
        "unavailableActivityCount": len(value["unavailableActivity"]),
        "qualification": value["qualification"],
    }
    navigation = value.get("navigationPresentation")
    if isinstance(navigation, Mapping):
        result["navigationDiagnostics"] = {
            "pathBindingCount": len(navigation["pathBindings"]),
            "pathIntersectionCount": len(navigation["pathIntersections"]),
            "sampledPairCount": len(
                navigation["sampledProximity"]["pairMinimums"]
            ),
            "handoffResultCount": len(navigation["handoffResultIds"]),
            "generatedCollisionAvoidanceOffsets": False,
        }
    return result


class FacilityActivityScenarioStore:
    """Bounded in-memory cache for browser-only activity packages."""

    def __init__(
        self,
        *,
        ttl_seconds: float = FACILITY_ACTIVITY_SCENARIO_STORE_TTL_SECONDS,
        maximum_entries: int = FACILITY_ACTIVITY_SCENARIO_STORE_MAXIMUM_ENTRIES,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or maximum_entries < 1:
            raise ValueError("activity scenario store limits must be positive")
        self.ttl_seconds = float(ttl_seconds)
        self.maximum_entries = int(maximum_entries)
        self._clock = clock or time.monotonic
        self._lock = RLock()
        self._entries: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()

    def _prune(self, now: float) -> None:
        expired = [
            scenario_id
            for scenario_id, (_, expires_at) in self._entries.items()
            if expires_at <= now
        ]
        for scenario_id in expired:
            self._entries.pop(scenario_id, None)
        while len(self._entries) > self.maximum_entries:
            self._entries.popitem(last=False)

    def put(self, scenario_id: str, payload: Mapping[str, Any]) -> None:
        scenario_id = _text(scenario_id, "scenarioId")
        detached = deepcopy(dict(payload))
        now = self._clock()
        with self._lock:
            self._prune(now)
            self._entries.pop(scenario_id, None)
            self._entries[scenario_id] = (
                detached,
                now + self.ttl_seconds,
            )
            self._prune(now)

    def get(self, scenario_id: str) -> dict[str, Any]:
        scenario_id = _text(scenario_id, "scenarioId")
        now = self._clock()
        with self._lock:
            self._prune(now)
            entry = self._entries.get(scenario_id)
            if entry is None:
                raise FacilityNotFoundError(
                    "facility_activity_scenario_not_found",
                    "The Facility activity scenario is unavailable or expired.",
                    details={"scenarioId": scenario_id},
                )
            self._entries.move_to_end(scenario_id)
            return deepcopy(entry[0])


__all__ = [
    "FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS",
    "FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_CANONICAL_BYTES",
    "FACILITY_ACTIVITY_SCENARIO_MAXIMUM_ACTORS",
    "FACILITY_ACTIVITY_SCENARIO_QUALIFICATION",
    "FACILITY_ACTIVITY_SCENARIO_SCHEMA_VERSION",
    "FACILITY_NAVIGATION_ACTIVITY_QUALIFICATION",
    "FACILITY_NAVIGATION_ACTIVITY_SCENARIO_SCHEMA_VERSION",
    "FACILITY_NAVIGATION_PRESENTATION_QUALIFICATION",
    "FACILITY_NAVIGATION_PRESENTATION_SCHEMA",
    "FacilityActivityScenarioError",
    "FacilityActivityScenarioStore",
    "build_facility_activity_scenario",
    "build_navigation_activity_scenario",
    "facility_activity_scenario_summary",
    "validate_facility_activity_scenario",
]
