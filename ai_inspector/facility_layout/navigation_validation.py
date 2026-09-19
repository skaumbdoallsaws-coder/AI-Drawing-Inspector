"""Deterministic validation for UI-authored Facility navigation paths."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

try:
    from shapely import BufferCapStyle, BufferJoinStyle, set_precision
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union
except ImportError:  # pragma: no cover - fail-closed path
    BufferCapStyle = BufferJoinStyle = None
    LineString = Polygon = None
    set_precision = unary_union = None

from .navigation_geometry import (
    NAVIGATION_BUFFER_MITRE_LIMIT,
    NAVIGATION_BUFFER_QUAD_SEGS,
    NAVIGATION_GEOMETRY_GRID_METERS,
    FacilityNavigationGeometryError,
    canonicalize_polygon_geometry,
    free_space_geometry,
    union_and_expand_obstacles,
)
from .errors import FacilityValidationError
from .routing import validate_swept_volume


MANUAL_NAVIGATION_VALIDATION_SCHEMA = "facility-navigation-manual-validation-v1"


class FacilityManualNavigationValidationError(FacilityValidationError):
    """A manual path cannot be validated from the supplied trusted context."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, details=details)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _point(value: Mapping[str, Any], index: int) -> dict[str, float]:
    try:
        x = float(value["x"])
        z = float(value["z"])
    except (KeyError, TypeError, ValueError) as error:
        raise FacilityManualNavigationValidationError(
            "facility_navigation_manual_path_invalid",
            "Every manual path point requires finite x and z coordinates.",
            details={"pointIndex": index},
        ) from error
    if not math.isfinite(x) or not math.isfinite(z):
        raise FacilityManualNavigationValidationError(
            "facility_navigation_manual_path_invalid",
            "Every manual path point requires finite x and z coordinates.",
            details={"pointIndex": index},
        )
    return {"x": round(x, 6), "z": round(z, 6)}


def _points(values: Sequence[Mapping[str, Any]]) -> list[dict[str, float]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise FacilityManualNavigationValidationError(
            "facility_navigation_manual_path_invalid",
            "A manual path requires a point array.",
        )
    points = [_point(value, index) for index, value in enumerate(values)]
    if len(points) < 2 or len(points) > 2_048:
        raise FacilityManualNavigationValidationError(
            "facility_navigation_manual_path_invalid",
            "A manual path requires between 2 and 2,048 points.",
        )
    if any(left == right for left, right in zip(points, points[1:])):
        raise FacilityManualNavigationValidationError(
            "facility_navigation_manual_path_invalid",
            "Consecutive manual path points must differ.",
        )
    return points


def _floor_boundaries(shell: Mapping[str, Any]) -> list[list[dict[str, float]]]:
    result: list[list[dict[str, float]]] = []
    for feature in shell.get("features", []):
        if not isinstance(feature, Mapping) or feature.get("featureKind") not in {
            "floor_surface",
            "floor",
        }:
            continue
        geometry = feature.get("geometry")
        boundary = geometry.get("boundary") if isinstance(geometry, Mapping) else None
        if isinstance(boundary, list) and len(boundary) >= 3:
            result.append([_point(value, index) for index, value in enumerate(boundary)])
    if not result:
        raise FacilityManualNavigationValidationError(
            "facility_navigation_allowed_geometry_unavailable",
            "The published shell has no traversable floor boundary.",
        )
    return result


def _actor_radius(asset: Mapping[str, Any]) -> float:
    geometry = asset.get("geometry")
    polygons = geometry.get("footprintPolygons") if isinstance(geometry, Mapping) else None
    vertices: list[tuple[float, float]] = []
    if isinstance(polygons, list):
        for polygon in polygons:
            if not isinstance(polygon, list):
                continue
            for raw in polygon:
                if isinstance(raw, Mapping):
                    value = _point(raw, len(vertices))
                    vertices.append((value["x"], value["z"]))
    if len(vertices) < 3:
        raise FacilityManualNavigationValidationError(
            "facility_navigation_actor_envelope_unavailable",
            "The exact actor catalog footprint is unavailable.",
        )
    return round(max(math.hypot(x, z) for x, z in vertices), 9)


def _pedestrian_free_space(
    floor_boundaries: Sequence[Sequence[Mapping[str, Any]]],
    obstacles: Sequence[Mapping[str, Any]],
    radius: float,
) -> Any:
    if Polygon is None or unary_union is None or set_precision is None:
        raise FacilityManualNavigationValidationError(
            "facility_navigation_geometry_engine_unavailable",
            "Deterministic manual-path validation requires the configured geometry engine.",
        )
    allowed = unary_union([
        Polygon([(float(point["x"]), float(point["z"])) for point in boundary])
        for boundary in floor_boundaries
    ])
    effective_radius = (
        radius / math.cos(math.pi / (4.0 * NAVIGATION_BUFFER_QUAD_SEGS))
        if radius > 0 else 0.0
    )
    if effective_radius > 0:
        allowed = allowed.buffer(
            -effective_radius,
            quad_segs=NAVIGATION_BUFFER_QUAD_SEGS,
            cap_style=BufferCapStyle.round,
            join_style=BufferJoinStyle.round,
            mitre_limit=NAVIGATION_BUFFER_MITRE_LIMIT,
            single_sided=False,
        )
    allowed = set_precision(
        allowed,
        grid_size=NAVIGATION_GEOMETRY_GRID_METERS,
        mode="valid_output",
    )
    if allowed.is_empty or not allowed.is_valid:
        raise FacilityManualNavigationValidationError(
            "facility_navigation_free_space_empty",
            "The actor envelope leaves no traversable floor geometry.",
        )
    if not obstacles:
        return allowed
    expansion = union_and_expand_obstacles(
        [
            {
                "obstacleId": str(item["obstacleId"]),
                "exterior": item["boundary"],
                "holes": [],
            }
            for item in obstacles
        ],
        navigation_radius_meters=radius,
    )
    return free_space_geometry(
        canonicalize_polygon_geometry(allowed),
        expansion["expandedPolygons"],
    )


def _segment_findings(free_space: Any, points: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for index, (left, right) in enumerate(zip(points, points[1:])):
        segment = LineString([
            (float(left["x"]), float(left["z"])),
            (float(right["x"]), float(right["z"])),
        ])
        if not free_space.covers(segment):
            findings.append({
                "code": "facility_navigation_manual_segment_blocked",
                "severity": "error",
                "segmentIndex": index,
                "message": (
                    "The actor envelope leaves the allowed floor or intersects "
                    "trusted obstacle geometry on this segment."
                ),
            })
    return findings


def _vehicle_poses(
    points: Sequence[Mapping[str, Any]],
    direction: str,
) -> list[dict[str, Any]]:
    poses = []
    for index, point in enumerate(points):
        left = points[index - 1] if index == len(points) - 1 else point
        right = point if index == len(points) - 1 else points[index + 1]
        heading = math.atan2(
            float(right["z"]) - float(left["z"]),
            float(right["x"]) - float(left["x"]),
        )
        if direction == "reverse":
            heading = math.atan2(math.sin(heading + math.pi), math.cos(heading + math.pi))
        poses.append({
            "x": float(point["x"]),
            "z": float(point["z"]),
            "heading": heading,
            "gear": "reverse" if direction == "reverse" else "forward",
        })
    return poses


def _segment_index_at_distance(
    points: Sequence[Mapping[str, Any]],
    distance_meters: float,
) -> int:
    target = max(0.0, float(distance_meters))
    cumulative = 0.0
    for index, (left, right) in enumerate(zip(points, points[1:])):
        cumulative += math.dist(
            (float(left["x"]), float(left["z"])),
            (float(right["x"]), float(right["z"])),
        )
        if target <= cumulative + 1.0e-9:
            return index
    return max(0, len(points) - 2)


def validate_manual_navigation_path(
    *,
    points: Sequence[Mapping[str, Any]],
    actor_class: str,
    actor_asset_definition: Mapping[str, Any],
    shell: Mapping[str, Any],
    obstacles: Sequence[Mapping[str, Any]],
    direction: str = "forward",
    vehicle_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one complete UI-authored override without adding authority."""

    normalized = _points(points)
    floors = _floor_boundaries(shell)
    if actor_class == "pedestrian":
        radius = _actor_radius(actor_asset_definition)
        try:
            free_space = _pedestrian_free_space(floors, obstacles, radius)
            findings = _segment_findings(free_space, normalized)
        except FacilityNavigationGeometryError as error:
            raise FacilityManualNavigationValidationError(
                error.code,
                str(error),
                details=error.details,
            ) from error
        result = {
            "schemaVersion": MANUAL_NAVIGATION_VALIDATION_SCHEMA,
            "actorClass": "pedestrian",
            "valid": not findings,
            "validationMethod": "rotation_invariant_actor_envelope",
            "navigationRadiusMeters": radius,
            "pointCount": len(normalized),
            "segmentCount": len(normalized) - 1,
            "invalidSegmentIndexes": [
                item["segmentIndex"] for item in findings
            ],
            "findings": findings,
            "evidenceStatus": "derived",
            "reviewStatus": "pending",
            "qualification": (
                "Validates the exact catalog-derived actor envelope against "
                "published shell and asset geometry. It does not establish "
                "safety, capacity, timing, or regulatory compliance."
            ),
        }
    elif actor_class == "vehicle":
        if not isinstance(vehicle_profile, Mapping):
            raise FacilityManualNavigationValidationError(
                "facility_navigation_vehicle_profile_unavailable",
                "Vehicle path validation requires an exact published profile revision.",
            )
        swept = validate_swept_volume(
            _vehicle_poses(normalized, direction),
            vehicle_profile,
            traversable_polygons=floors,
            obstacles=obstacles,
        )
        invalid_segments = sorted({
            _segment_index_at_distance(
                normalized,
                float(location["distanceMeters"]),
            )
            for item in swept.get("findings", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("location"), Mapping)
            and (location := item["location"]).get("localized") is True
            and isinstance(location.get("distanceMeters"), (int, float))
        })
        result = {
            "schemaVersion": MANUAL_NAVIGATION_VALIDATION_SCHEMA,
            "actorClass": "vehicle",
            "valid": bool(swept.get("valid")),
            "validationMethod": "published_vehicle_swept_volume",
            "pointCount": len(normalized),
            "segmentCount": len(normalized) - 1,
            "invalidSegmentIndexes": invalid_segments,
            "findings": list(swept.get("findings", [])),
            "sweptVolume": swept,
            "evidenceStatus": "derived",
            "reviewStatus": "pending",
            "qualification": (
                "Validates sampled swept geometry against the exact published "
                "vehicle profile and trusted static geometry. It does not "
                "establish safety, capacity, timing, or regulatory compliance."
            ),
        }
    else:
        raise FacilityManualNavigationValidationError(
            "facility_navigation_actor_class_invalid",
            "Manual path validation supports pedestrian or vehicle actors.",
        )
    result["validationFingerprint"] = _fingerprint(result)
    return result


__all__ = [
    "MANUAL_NAVIGATION_VALIDATION_SCHEMA",
    "FacilityManualNavigationValidationError",
    "validate_manual_navigation_path",
]
