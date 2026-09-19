"""Deterministic directional-lane binding for Facility motion playback."""

from __future__ import annotations

from copy import deepcopy
import math
from statistics import median
from typing import Any, Mapping, Sequence

from .errors import FacilityValidationError


FACILITY_MOTION_LANE_BINDING_VERSION = "facility-motion-lane-binding-v1"
FACILITY_MOTION_LANE_QUALIFICATION = (
    "The playback lane is derived from authored direction-arrow geometry inside "
    "the selected route corridor. It does not establish traffic safety, lane "
    "capacity, regulatory compliance, or right-of-way."
)
FACILITY_MOTION_ADJUSTED_LANE_QUALIFICATION = (
    "The lane direction is derived from authored direction-arrow geometry. "
    "The execution centerline is shifted inward by one planner grid interval "
    "and revalidated against the exact actor envelope and authored route "
    "corridor. It does not establish traffic safety, lane capacity, regulatory "
    "compliance, or right-of-way."
)
_ARROW_ALIGNMENT_MINIMUM = math.cos(math.radians(30.0))
_LANE_CLUSTER_TOLERANCE_METERS = 0.25
_EPSILON = 1.0e-9


def _point(item: Mapping[str, Any]) -> tuple[float, float]:
    try:
        x = float(item["x"])
        z = float(item["z"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FacilityValidationError(
            "facility_motion_route_geometry_unavailable",
            "The selected route contains an invalid centerline point.",
        ) from exc
    if not math.isfinite(x) or not math.isfinite(z):
        raise FacilityValidationError(
            "facility_motion_route_geometry_unavailable",
            "The selected route contains a non-finite centerline point.",
        )
    return x, z


def _route_points(route: Mapping[str, Any]) -> list[dict[str, float]]:
    raw = route.get("centerline")
    if not isinstance(raw, list):
        raw = []
    result = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        x, z = _point(item)
        result.append({
            "x": x,
            "y": float(item.get("y", 0.0)),
            "z": z,
        })
    if len(result) < 2:
        raise FacilityValidationError(
            "facility_motion_route_geometry_unavailable",
            "The selected route has no replayable centerline.",
        )
    return result


def _closest_segment(
    point: tuple[float, float],
    centerline: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    travelled = 0.0
    for index, (left_raw, right_raw) in enumerate(
        zip(centerline, centerline[1:])
    ):
        left = _point(left_raw)
        right = _point(right_raw)
        dx = right[0] - left[0]
        dz = right[1] - left[1]
        length = math.hypot(dx, dz)
        if length <= _EPSILON:
            continue
        ratio = max(
            0.0,
            min(
                1.0,
                ((point[0] - left[0]) * dx + (point[1] - left[1]) * dz)
                / (length * length),
            ),
        )
        projected = (left[0] + dx * ratio, left[1] + dz * ratio)
        tangent = (dx / length, dz / length)
        delta = (point[0] - projected[0], point[1] - projected[1])
        distance = math.hypot(delta[0], delta[1])
        candidate = {
            "segmentIndex": index,
            "distance": distance,
            "distanceAlongRoute": travelled + ratio * length,
            "projected": projected,
            "tangent": tangent,
            "lateralOffset": delta[0] * -tangent[1]
            + delta[1] * tangent[0],
        }
        if best is None or (
            candidate["distance"],
            candidate["distanceAlongRoute"],
            candidate["segmentIndex"],
        ) < (
            best["distance"],
            best["distanceAlongRoute"],
            best["segmentIndex"],
        ):
            best = candidate
        travelled += length
    if best is None:
        raise FacilityValidationError(
            "facility_motion_route_geometry_unavailable",
            "The selected route has no non-degenerate centerline segment.",
        )
    return best


def _arrow_direction(rotation_degrees: float) -> tuple[float, float]:
    """Return the world direction of the renderer's local +Z arrow tip."""

    radians = math.radians(rotation_degrees)
    return math.sin(radians), math.cos(radians)


def _clusters(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    ordered = sorted(
        records,
        key=lambda item: (
            item["lateralOffsetMeters"],
            item["markingId"],
        ),
    )
    result: list[list[dict[str, Any]]] = []
    for item in ordered:
        if not result:
            result.append([item])
            continue
        center = median(
            value["lateralOffsetMeters"] for value in result[-1]
        )
        if abs(item["lateralOffsetMeters"] - center) <= (
            _LANE_CLUSTER_TOLERANCE_METERS
        ):
            result[-1].append(item)
        else:
            result.append([item])
    return result


def _offset_centerline(
    centerline: Sequence[Mapping[str, Any]],
    offset: float,
) -> list[dict[str, float]]:
    points = [_point(item) for item in centerline]
    segment_normals: list[tuple[float, float]] = []
    for left, right in zip(points, points[1:]):
        dx = right[0] - left[0]
        dz = right[1] - left[1]
        length = math.hypot(dx, dz)
        if length <= _EPSILON:
            segment_normals.append((0.0, 0.0))
        else:
            segment_normals.append((-dz / length, dx / length))
    result = []
    for index, (x, z) in enumerate(points):
        if index == 0:
            normal = segment_normals[0]
            scale = offset
        elif index == len(points) - 1:
            normal = segment_normals[-1]
            scale = offset
        else:
            previous = segment_normals[index - 1]
            following = segment_normals[index]
            summed = (previous[0] + following[0], previous[1] + following[1])
            magnitude = math.hypot(summed[0], summed[1])
            if magnitude <= _EPSILON:
                normal = following
                scale = offset
            else:
                normal = (summed[0] / magnitude, summed[1] / magnitude)
                denominator = normal[0] * previous[0] + normal[1] * previous[1]
                if abs(denominator) <= 0.25:
                    normal = following
                    scale = offset
                else:
                    scale = max(-4 * abs(offset), min(4 * abs(offset), offset / denominator))
        result.append({
            "x": round(x + normal[0] * scale, 6),
            "y": round(float(centerline[index].get("y", 0.0)), 6),
            "z": round(z + normal[1] * scale, 6),
        })
    return result


def inset_lane_endpoints(
    centerline: Sequence[Mapping[str, Any]],
    inset_meters: float,
) -> list[dict[str, float]]:
    """Trim both lane ends so a finite actor envelope remains inside its route."""

    inset = float(inset_meters)
    if not math.isfinite(inset) or inset < 0:
        raise FacilityValidationError(
            "facility_motion_route_geometry_unavailable",
            "The motion endpoint inset must be a finite non-negative distance.",
        )
    result = [
        {
            "x": float(item["x"]),
            "y": float(item.get("y", 0.0)),
            "z": float(item["z"]),
        }
        for item in centerline
    ]
    if inset <= _EPSILON:
        return result

    def trim_start(
        points: list[dict[str, float]],
        distance: float,
    ) -> list[dict[str, float]]:
        remaining = distance
        index = 0
        while index < len(points) - 1:
            left = points[index]
            right = points[index + 1]
            dx = right["x"] - left["x"]
            dz = right["z"] - left["z"]
            dy = right["y"] - left["y"]
            length = math.hypot(dx, dz)
            if length <= _EPSILON:
                index += 1
                continue
            if remaining < length - _EPSILON:
                ratio = remaining / length
                return [{
                    "x": round(left["x"] + dx * ratio, 6),
                    "y": round(left["y"] + dy * ratio, 6),
                    "z": round(left["z"] + dz * ratio, 6),
                }, *points[index + 1:]]
            remaining -= length
            index += 1
        raise FacilityValidationError(
            "facility_motion_route_too_short",
            "The selected route is too short for the exact actor envelope.",
            details={"endpointInsetMeters": inset},
        )

    result = trim_start(result, inset)
    reversed_result = [dict(item) for item in reversed(result)]
    reversed_result = trim_start(reversed_result, inset)
    return [dict(item) for item in reversed(reversed_result)]


def inward_lane_binding_candidate(
    route: Mapping[str, Any],
    lane_binding: Mapping[str, Any],
    *,
    adjustment_meters: float,
) -> dict[str, Any] | None:
    """Return the nearest inward marked-lane candidate for envelope validation."""

    if lane_binding.get("status") != "direction_markings":
        return None
    source_offset = float(lane_binding.get("lateralOffsetMeters", 0.0))
    adjustment = float(adjustment_meters)
    if (
        not math.isfinite(source_offset)
        or not math.isfinite(adjustment)
        or adjustment <= 0
        or abs(source_offset) <= _EPSILON
    ):
        return None
    applied = min(abs(source_offset), adjustment)
    execution_offset = source_offset - math.copysign(applied, source_offset)
    centerline = _route_points(route)
    if lane_binding.get("travelDirection") == "reverse":
        centerline.reverse()
    result = deepcopy(dict(lane_binding))
    result.update({
        "sourceLateralOffsetMeters": round(source_offset, 6),
        "executionAdjustmentMeters": round(execution_offset - source_offset, 6),
        "lateralOffsetMeters": round(execution_offset, 6),
        "laneCenterline": _offset_centerline(centerline, execution_offset),
        "qualification": FACILITY_MOTION_ADJUSTED_LANE_QUALIFICATION,
    })
    return result


def derive_directional_lane(
    layout: Mapping[str, Any],
    route: Mapping[str, Any],
    *,
    travel_direction: str,
) -> dict[str, Any]:
    """Resolve one marked directional lane or retain the route centerline."""

    if travel_direction not in {"forward", "reverse"}:
        raise FacilityValidationError(
            "facility_motion_request_invalid",
            "travelDirection must be forward or reverse.",
        )
    centerline = _route_points(route)
    if travel_direction == "reverse":
        centerline.reverse()
    try:
        corridor_width = float(route.get("corridorWidth"))
    except (TypeError, ValueError) as exc:
        raise FacilityValidationError(
            "facility_motion_route_geometry_unavailable",
            "The selected route requires a positive corridor width.",
        ) from exc
    if not math.isfinite(corridor_width) or corridor_width <= 0:
        raise FacilityValidationError(
            "facility_motion_route_geometry_unavailable",
            "The selected route requires a positive corridor width.",
        )
    candidates = []
    for marking in layout.get("floorMarkings", []):
        if not isinstance(marking, Mapping):
            continue
        if marking.get("markingType") != "direction_arrow" or (
            marking.get("semanticRole") != "material_flow"
        ):
            continue
        transform = marking.get("transform")
        position = (
            transform.get("position")
            if isinstance(transform, Mapping)
            and isinstance(transform.get("position"), Mapping)
            else None
        )
        if not isinstance(position, Mapping):
            continue
        try:
            point = (float(position["x"]), float(position["z"]))
            rotation = float(transform.get("rotationDegrees", 0.0))
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (*point, rotation)):
            continue
        projection = _closest_segment(point, centerline)
        if projection["distance"] > corridor_width / 2.0 + _EPSILON:
            continue
        arrow = _arrow_direction(rotation)
        tangent = projection["tangent"]
        alignment = arrow[0] * tangent[0] + arrow[1] * tangent[1]
        if alignment < _ARROW_ALIGNMENT_MINIMUM:
            continue
        marking_id = marking.get("markingId")
        if not isinstance(marking_id, str) or not marking_id:
            continue
        candidates.append({
            "markingId": marking_id,
            "lateralOffsetMeters": projection["lateralOffset"],
            "alignment": alignment,
            "distanceAlongRoute": projection["distanceAlongRoute"],
        })
    route_id = str(route.get("routeId") or "")
    if not candidates:
        return {
            "schemaVersion": 1,
            "bindingVersion": FACILITY_MOTION_LANE_BINDING_VERSION,
            "status": "centerline_unmarked",
            "travelDirection": travel_direction,
            "routeId": route_id,
            "sourceMarkingIds": [],
            "lateralOffsetMeters": 0.0,
            "laneCenterline": deepcopy(centerline),
            "evidenceStatus": "unknown",
            "qualification": (
                "No authored direction-arrow lane was resolved; playback uses "
                "the authored route centerline without claiming lane assignment."
            ),
        }
    groups = _clusters(candidates)
    if len(groups) != 1:
        raise FacilityValidationError(
            "facility_motion_lane_binding_ambiguous",
            "More than one marked lane matches the requested travel direction.",
            details={
                "routeId": route_id,
                "travelDirection": travel_direction,
                "candidateLaneCount": len(groups),
                "candidateMarkingIds": [
                    sorted(item["markingId"] for item in group)
                    for group in groups
                ],
            },
        )
    selected = groups[0]
    lateral_offset = float(median(
        item["lateralOffsetMeters"] for item in selected
    ))
    return {
        "schemaVersion": 1,
        "bindingVersion": FACILITY_MOTION_LANE_BINDING_VERSION,
        "status": "direction_markings",
        "travelDirection": travel_direction,
        "routeId": route_id,
        "sourceMarkingIds": sorted(
            item["markingId"] for item in selected
        ),
        "lateralOffsetMeters": round(lateral_offset, 6),
        "laneCenterline": _offset_centerline(centerline, lateral_offset),
        "evidenceStatus": "derived",
        "qualification": FACILITY_MOTION_LANE_QUALIFICATION,
    }


__all__ = [
    "FACILITY_MOTION_ADJUSTED_LANE_QUALIFICATION",
    "FACILITY_MOTION_LANE_BINDING_VERSION",
    "FACILITY_MOTION_LANE_QUALIFICATION",
    "derive_directional_lane",
    "inward_lane_binding_candidate",
    "inset_lane_endpoints",
]
