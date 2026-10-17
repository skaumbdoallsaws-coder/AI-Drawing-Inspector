"""NAV7 shared-clock presentation diagnostics for accepted actor journeys."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from shapely.geometry import LineString

from .activity_scenario import (
    FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS,
    FACILITY_NAVIGATION_PRESENTATION_QUALIFICATION,
    FACILITY_NAVIGATION_PRESENTATION_SCHEMA,
)
from .errors import FacilityValidationError
from .motion_package import (
    FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1,
    FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2,
    FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3,
    sample_motion_at_distance,
    validate_facility_motion_package,
)


FACILITY_NAVIGATION_ACTIVITY_DIAGNOSTIC_VERSION = (
    "facility-navigation-activity-diagnostics-v1"
)
FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_INTERSECTIONS = 256
FACILITY_NAVIGATION_ACTIVITY_DEFAULT_SAMPLES = 101
FACILITY_NAVIGATION_PROXIMITY_QUALIFICATION = (
    "Center-distance samples on the shared display clock; not a collision or "
    "safety assessment."
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{hashlib.sha256(_canonical_bytes(value)).hexdigest()[:24]}"


def _trajectory(package: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    canonical = validate_facility_motion_package(package)
    if canonical["schemaVersion"] not in {
        FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V1,
        FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2,
        FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V3,
    }:
        raise FacilityValidationError(
            "facility_navigation_activity_package_invalid",
            "Navigation activity accepts only validated motion packages.",
        )
    movement = canonical["movement"]
    if movement["outcome"] != "accepted":
        raise FacilityValidationError(
            "facility_navigation_activity_package_invalid",
            "Navigation activity accepts only accepted journey packages.",
        )
    return canonical, movement["poses"]


def _presentation_duration(movement: Mapping[str, Any]) -> float:
    value = movement.get(
        "presentationDurationSeconds",
        movement.get("plannerDurationEstimateSeconds"),
    )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FacilityValidationError(
            "facility_navigation_activity_package_invalid",
            "An activity motion package has no presentation duration.",
        )
    duration = float(value)
    if not math.isfinite(duration) or duration <= 0:
        raise FacilityValidationError(
            "facility_navigation_activity_package_invalid",
            "An activity motion package has an invalid presentation duration.",
        )
    return duration


def _journey_identity(movement: Mapping[str, Any]) -> str:
    identity = movement.get("journeySolutionId") or movement.get("movementId")
    if not isinstance(identity, str) or not identity:
        raise FacilityValidationError(
            "facility_navigation_activity_package_invalid",
            "An activity motion package has no stable journey identity.",
        )
    return identity


def _intersection_points(geometry: Any) -> list[tuple[float, float]]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [(float(geometry.x), float(geometry.y))]
    if geometry.geom_type in {"LineString", "LinearRing"}:
        coordinates = list(geometry.coords)
        return [tuple(coordinates[0]), tuple(coordinates[-1])]
    result: list[tuple[float, float]] = []
    for child in getattr(geometry, "geoms", []):
        result.extend(_intersection_points(child))
    return result


def _static_intersections(
    records: Sequence[Mapping[str, Any]],
    *,
    maximum_per_actor_pair: int | None = None,
) -> list[dict[str, Any]]:
    result = []
    for left_index, left in enumerate(records):
        left_line = LineString([(item["x"], item["z"]) for item in left["poses"]])
        for right in records[left_index + 1:]:
            right_line = LineString([(item["x"], item["z"]) for item in right["poses"]])
            points = sorted({
                (round(x, 6), round(z, 6))
                for x, z in _intersection_points(left_line.intersection(right_line))
            })
            if maximum_per_actor_pair is not None:
                points = points[:maximum_per_actor_pair]
            actor_ids = sorted([left["actorId"], right["actorId"]])
            for x, z in points:
                seed = {
                    "actors": actor_ids,
                    "position": {"x": x, "z": z},
                    "packages": sorted([left["packageId"], right["packageId"]]),
                    "diagnosticVersion": FACILITY_NAVIGATION_ACTIVITY_DIAGNOSTIC_VERSION,
                }
                result.append({
                    "conflictId": _stable_id("nvc", seed),
                    "actorIds": actor_ids,
                    "position": {"x": x, "z": z},
                    "evidenceStatus": "derived",
                })
                if len(result) > FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_INTERSECTIONS:
                    raise FacilityValidationError(
                        "facility_navigation_activity_diagnostic_budget_exceeded",
                        "Static path intersections exceed the bounded presentation budget.",
                    )
    result.sort(key=lambda item: (item["actorIds"], item["position"]["x"], item["position"]["z"]))
    return result


def _sample_pose(
    record: Mapping[str, Any],
    scenario_time: float,
) -> dict[str, Any]:
    movement = record["package"]["movement"]
    duration = _presentation_duration(movement)
    shifted = max(0.0, scenario_time - float(record["offsetSeconds"]))
    if record["repeat"]:
        elapsed = shifted % duration
    else:
        elapsed = min(shifted, duration)
    distance = float(movement["distanceMeters"]) * elapsed / duration
    return sample_motion_at_distance(movement, distance)


def _sampled_pair_minimums(
    records: Sequence[Mapping[str, Any]],
    *,
    cycle_duration_seconds: float,
    sample_count: int,
) -> list[dict[str, Any]]:
    if isinstance(sample_count, bool) or not 2 <= int(sample_count) <= 1001:
        raise FacilityValidationError(
            "facility_navigation_activity_sample_budget_invalid",
            "Sample count must be between 2 and 1001.",
        )
    result = []
    # Each actor has one pose per shared-clock sample, independent of its pair.
    poses = [
        [_sample_pose(record, cycle_duration_seconds * (index / (sample_count - 1)))
         for index in range(sample_count)]
        for record in records
    ] if len(records) > 1 else []
    for left_index, left in enumerate(records):
        for right_index in range(left_index + 1, len(records)):
            right = records[right_index]
            minimum: tuple[float, float] | None = None
            for index in range(sample_count):
                normalized = index / (sample_count - 1)
                left_pose = poses[left_index][index]
                right_pose = poses[right_index][index]
                distance = math.hypot(
                    float(left_pose["x"]) - float(right_pose["x"]),
                    float(left_pose["z"]) - float(right_pose["z"]),
                )
                candidate = (distance, normalized)
                if minimum is None or candidate < minimum:
                    minimum = candidate
            assert minimum is not None
            result.append({
                "actorIds": sorted([left["actorId"], right["actorId"]]),
                "centerDistanceMeters": round(minimum[0], 6),
                "normalizedTime": round(minimum[1], 6),
            })
    result.sort(key=lambda item: item["actorIds"])
    return result


def build_navigation_activity_presentation(
    actors: Sequence[Mapping[str, Any]],
    actor_payloads: Mapping[str, Mapping[str, Any]],
    *,
    cycle_duration_seconds: float,
    phase_authorities: Mapping[str, str] | None = None,
    handoff_result_ids: Sequence[str] = (),
    sample_count: int = FACILITY_NAVIGATION_ACTIVITY_DEFAULT_SAMPLES,
    maximum_static_intersections_per_actor_pair: int | None = None,
) -> dict[str, Any]:
    """Build bounded diagnostics without changing actor paths or start phases."""

    if not actors or len(actors) > FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS:
        raise FacilityValidationError(
            "facility_activity_scenario_actor_limit",
            "The navigation activity actor count is outside the supported range.",
        )
    if (
        maximum_static_intersections_per_actor_pair is not None
        and (
            isinstance(maximum_static_intersections_per_actor_pair, bool)
            or not isinstance(
                maximum_static_intersections_per_actor_pair, int
            )
            or not 1 <= maximum_static_intersections_per_actor_pair <= 16
        )
    ):
        raise FacilityValidationError(
            "facility_navigation_activity_diagnostic_budget_invalid",
            "The per-pair static-intersection limit must be from 1 to 16.",
        )
    authorities = dict(phase_authorities or {})
    records = []
    phases = []
    bindings = []
    for actor in actors:
        actor_id = str(actor["actorId"])
        package_id = str(actor["motionPackageId"])
        payload = actor_payloads.get(package_id)
        if not isinstance(payload, Mapping):
            raise FacilityValidationError(
                "facility_navigation_activity_package_unavailable",
                "An activity actor has no journey-backed motion payload.",
            )
        package, poses = _trajectory(payload["package"])
        movement = package["movement"]
        movement_placement_id = movement.get("actorPlacementId") or movement.get(
            "vehiclePlacementId"
        )
        if movement_placement_id != actor["placementId"]:
            raise FacilityValidationError(
                "facility_navigation_activity_actor_mismatch",
                "The journey package does not bind the selected existing actor.",
            )
        offset = round(float(actor["startOffsetSeconds"]), 6)
        authority = authorities.get(actor_id, "none")
        if authority == "none" and offset != 0:
            raise FacilityValidationError(
                "facility_activity_navigation_rescheduling_prohibited",
                "Generated collision-avoidance phase offsets are prohibited.",
            )
        closed = math.hypot(
            float(poses[0]["x"]) - float(poses[-1]["x"]),
            float(poses[0]["z"]) - float(poses[-1]["z"]),
        ) <= 1e-6
        records.append({
            "actorId": actor_id,
            "packageId": package_id,
            "package": package,
            "poses": poses,
            "offsetSeconds": offset,
            "repeat": actor["repeat"] is True,
        })
        phases.append({
            "actorId": actor_id,
            "offsetSeconds": offset,
            "authority": authority,
        })
        journey_identity = _journey_identity(movement)
        actor_class = (
            str(movement.get("actorClass") or "")
            or ("pedestrian" if actor["actorType"] == "operator" else "vehicle")
        )
        bindings.append({
            "pathBindingId": _stable_id("npb", {
                "actorId": actor_id,
                "journeySolutionId": journey_identity,
                "motionPackageId": package_id,
            }),
            "actorId": actor_id,
            "actorClass": actor_class,
            "journeySolutionId": journey_identity,
            "motionPackageId": package_id,
            "closed": closed,
        })
    records.sort(key=lambda item: item["actorId"])
    phases.sort(key=lambda item: item["actorId"])
    bindings.sort(key=lambda item: item["actorId"])
    return {
        "schemaVersion": FACILITY_NAVIGATION_PRESENTATION_SCHEMA,
        "qualification": FACILITY_NAVIGATION_PRESENTATION_QUALIFICATION,
        "sharedClock": True,
        "processTimingClaimed": False,
        "generatedCollisionAvoidanceOffsets": False,
        "phaseOffsets": phases,
        "pathBindings": bindings,
        "pathIntersections": _static_intersections(
            records,
            maximum_per_actor_pair=(
                maximum_static_intersections_per_actor_pair
            ),
        ),
        "sampledProximity": {
            "sampleCount": int(sample_count),
            "pairMinimums": _sampled_pair_minimums(
                records,
                cycle_duration_seconds=float(cycle_duration_seconds),
                sample_count=int(sample_count),
            ),
            "qualification": FACILITY_NAVIGATION_PROXIMITY_QUALIFICATION,
        },
        "handoffResultIds": sorted(set(str(item) for item in handoff_result_ids)),
    }


__all__ = [
    "FACILITY_NAVIGATION_ACTIVITY_DEFAULT_SAMPLES",
    "FACILITY_NAVIGATION_ACTIVITY_DIAGNOSTIC_VERSION",
    "FACILITY_NAVIGATION_PROXIMITY_QUALIFICATION",
    "build_navigation_activity_presentation",
]
