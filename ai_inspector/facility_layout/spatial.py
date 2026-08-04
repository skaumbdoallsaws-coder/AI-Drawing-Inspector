"""Pure deterministic spatial reasoning for Facility Layout.

The browser may mirror coarse portions of this module for immediate feedback,
but this Python implementation is the authoritative P6 geometry boundary. It
does no I/O, reads no clock, generates no randomness, and never mutates caller
data.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import math
from threading import RLock
from typing import Any


SPATIAL_ENGINE_VERSION = 1
CANDIDATE_POLICY_VERSION = 1
DEFAULT_INDEX_CELL_SIZE_METERS = 4.0
DEFAULT_GRID_SPACING_METERS = 0.25
GEOMETRY_EPSILON = 1.0e-9
_CANDIDATE_OBSTACLE_CACHE_LIMIT = 8
_CANDIDATE_RESULT_CACHE_LIMIT = 32

_EVIDENCE_STATES = frozenset({"authored", "derived", "inferred", "unknown"})
_AUTHORITATIVE_EVIDENCE_STATES = frozenset({"authored", "derived"})
_FINDING_SEVERITY_ORDER = {
    "error": 0,
    "unverified": 1,
    "warning": 2,
    "info": 3,
}
_CANDIDATE_FAMILY_ORDER = {
    "foundation": 0,
    "bay": 1,
    "row": 2,
    "boundary": 3,
    "alignment": 4,
    "grid": 5,
}
_CLEARANCE_FINDING_CODES = {
    "safety": "safety_clearance_violation",
    "service": "service_clearance_violation",
    "maintenance": "service_clearance_violation",
    "loading": "loading_clearance_violation",
    "operator": "operator_clearance_violation",
    "operating": "safety_clearance_violation",
    "door_swing": "door_swing_obstructed",
    "egress": "egress_obstructed",
}
_NON_PLACEMENT_ZONE_TYPES = frozenset(
    {"aisle", "exclusion", "operator", "safety", "service", "utility"}
)
_SHELL_OBSTACLE_KINDS = frozenset(
    {
        "column",
        "door",
        "fixed_equipment",
        "fixed_obstacle",
        "structural_column",
        "wall",
    }
)
_SUPPORTED_POLICY_RULE_TYPES = frozenset(
    {
        "maximum_floor_load",
        "minimum_clearance_envelope",
        "minimum_egress_clearance",
        "require_authoritative_clearance",
    }
)

Point2 = tuple[float, float]
Bounds2 = tuple[float, float, float, float]
PreparedZone = tuple[Mapping[str, Any], tuple[Point2, ...], Bounds2]
PreparedSurface = tuple[
    Mapping[str, Any],
    str,
    tuple[Point2, ...] | None,
]
CancelCheck = Callable[[], None]
PreparedTransform = tuple[
    tuple[float, float, float],
    tuple[float, float, float, float],
]


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None:
        cancel_check()


def _number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    return 0.0 if abs(result) <= GEOMETRY_EPSILON else result


def _rounded(value: float, digits: int = 9) -> float:
    result = round(float(value), digits)
    return 0.0 if abs(result) <= 10.0 ** (-digits) else result


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical spatial data must be finite")
        rounded = _rounded(value, 9)
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise ValueError("spatial data must be JSON-compatible")


def canonical_spatial_bytes(value: Any) -> bytes:
    """Return deterministic ASCII JSON bytes for spatial identity."""

    return json.dumps(
        _canonical_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def spatial_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_spatial_bytes(value)).hexdigest()


def _validated_document_fingerprint(value: Any) -> str:
    """Hash an already-canonical domain document without re-normalizing it."""

    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


def stable_finding_id(
    code: str,
    *,
    subject_refs: Iterable[str] = (),
    details: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "code": str(code),
        "details": dict(details or {}),
        "subjectRefs": sorted({str(item) for item in subject_refs}),
        "spatialEngineVersion": SPATIAL_ENGINE_VERSION,
    }
    return f"fsf-{spatial_fingerprint(payload)[:24]}"


def stable_candidate_id(
    *,
    layout_fingerprint: str,
    obstacle_fingerprint: str,
    asset_id: str,
    asset_definition_revision: str,
    family: str,
    transform: Mapping[str, Any],
    snap_relationship: Mapping[str, Any] | None,
) -> str:
    payload = {
        "assetDefinitionRevision": asset_definition_revision,
        "assetId": asset_id,
        "candidatePolicyVersion": CANDIDATE_POLICY_VERSION,
        "family": family,
        "layoutFingerprint": layout_fingerprint,
        "obstacleFingerprint": obstacle_fingerprint,
        "snapRelationship": snap_relationship,
        "spatialEngineVersion": SPATIAL_ENGINE_VERSION,
        "transform": transform,
    }
    return f"fsc-{spatial_fingerprint(payload)[:24]}"


def _point2(value: Mapping[str, Any], label: str) -> Point2:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return (_number(value.get("x"), f"{label}.x"), _number(value.get("z"), f"{label}.z"))


def _point3(value: Mapping[str, Any], label: str) -> tuple[float, float, float]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return (
        _number(value.get("x"), f"{label}.x"),
        _number(value.get("y"), f"{label}.y"),
        _number(value.get("z"), f"{label}.z"),
    )


def _polygon(value: Sequence[Mapping[str, Any]], label: str) -> tuple[Point2, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be an array")
    points = tuple(_point2(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(points) < 3 or abs(polygon_area(points)) <= GEOMETRY_EPSILON:
        raise ValueError(f"{label} must contain a non-degenerate polygon")
    return points


def polygon_area(points: Sequence[Point2]) -> float:
    return 0.5 * sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )


def polygon_bounds(points: Sequence[Point2]) -> Bounds2:
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def bounds_intersect(left: Bounds2, right: Bounds2) -> bool:
    return not (
        left[2] < right[0] - GEOMETRY_EPSILON
        or right[2] < left[0] - GEOMETRY_EPSILON
        or left[3] < right[1] - GEOMETRY_EPSILON
        or right[3] < left[1] - GEOMETRY_EPSILON
    )


def bounds_union(bounds: Sequence[Bounds2]) -> Bounds2:
    if not bounds:
        raise ValueError("at least one bounds record is required")
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )


def height_intervals_intersect(
    left: tuple[float, float],
    right: tuple[float, float],
) -> bool:
    return not (
        left[1] < right[0] - GEOMETRY_EPSILON
        or right[1] < left[0] - GEOMETRY_EPSILON
    )


def _cross(origin: Point2, left: Point2, right: Point2) -> float:
    return (
        (left[0] - origin[0]) * (right[1] - origin[1])
        - (left[1] - origin[1]) * (right[0] - origin[0])
    )


def _polygon_is_convex(polygon: Sequence[Point2]) -> bool:
    direction = 0
    for index, current in enumerate(polygon):
        following = polygon[(index + 1) % len(polygon)]
        after = polygon[(index + 2) % len(polygon)]
        cross = _cross(current, following, after)
        if abs(cross) <= GEOMETRY_EPSILON:
            continue
        current_direction = 1 if cross > 0 else -1
        if direction and current_direction != direction:
            return False
        direction = current_direction
    return direction != 0


def _polygon_is_axis_aligned_rectangle(polygon: Sequence[Point2]) -> bool:
    if len(polygon) != 4 or abs(polygon_area(polygon)) <= GEOMETRY_EPSILON:
        return False
    for index, current in enumerate(polygon):
        following = polygon[(index + 1) % len(polygon)]
        horizontal = abs(current[1] - following[1]) <= GEOMETRY_EPSILON
        vertical = abs(current[0] - following[0]) <= GEOMETRY_EPSILON
        if horizontal == vertical:
            return False
    return True


def _point_on_segment(point: Point2, start: Point2, end: Point2) -> bool:
    if abs(_cross(start, end, point)) > GEOMETRY_EPSILON:
        return False
    return (
        min(start[0], end[0]) - GEOMETRY_EPSILON
        <= point[0]
        <= max(start[0], end[0]) + GEOMETRY_EPSILON
        and min(start[1], end[1]) - GEOMETRY_EPSILON
        <= point[1]
        <= max(start[1], end[1]) + GEOMETRY_EPSILON
    )


def segments_intersect(
    left_start: Point2,
    left_end: Point2,
    right_start: Point2,
    right_end: Point2,
) -> bool:
    left_a = _cross(left_start, left_end, right_start)
    left_b = _cross(left_start, left_end, right_end)
    right_a = _cross(right_start, right_end, left_start)
    right_b = _cross(right_start, right_end, left_end)
    if (
        ((left_a > GEOMETRY_EPSILON and left_b < -GEOMETRY_EPSILON)
         or (left_a < -GEOMETRY_EPSILON and left_b > GEOMETRY_EPSILON))
        and ((right_a > GEOMETRY_EPSILON and right_b < -GEOMETRY_EPSILON)
             or (right_a < -GEOMETRY_EPSILON and right_b > GEOMETRY_EPSILON))
    ):
        return True
    return (
        _point_on_segment(right_start, left_start, left_end)
        or _point_on_segment(right_end, left_start, left_end)
        or _point_on_segment(left_start, right_start, right_end)
        or _point_on_segment(left_end, right_start, right_end)
    )


def point_in_polygon(point: Point2, polygon: Sequence[Point2]) -> bool:
    """Return True for interior and boundary points."""

    inside = False
    previous = polygon[-1]
    for current in polygon:
        if _point_on_segment(point, previous, current):
            return True
        crosses = (current[1] > point[1]) != (previous[1] > point[1])
        if crosses:
            denominator = previous[1] - current[1]
            intercept = (
                (previous[0] - current[0]) * (point[1] - current[1])
                / denominator
                + current[0]
            )
            if point[0] < intercept:
                inside = not inside
        previous = current
    return inside


def polygons_intersect(left: Sequence[Point2], right: Sequence[Point2]) -> bool:
    if not bounds_intersect(polygon_bounds(left), polygon_bounds(right)):
        return False
    for index, left_start in enumerate(left):
        left_end = left[(index + 1) % len(left)]
        for other_index, right_start in enumerate(right):
            right_end = right[(other_index + 1) % len(right)]
            if segments_intersect(left_start, left_end, right_start, right_end):
                return True
    return point_in_polygon(left[0], right) or point_in_polygon(right[0], left)


def polygon_contains_polygon(
    container: Sequence[Point2],
    subject: Sequence[Point2],
) -> bool:
    if _polygon_is_axis_aligned_rectangle(container):
        container_bounds = polygon_bounds(container)
        subject_bounds = polygon_bounds(subject)
        return (
            subject_bounds[0] + GEOMETRY_EPSILON >= container_bounds[0]
            and subject_bounds[1] + GEOMETRY_EPSILON >= container_bounds[1]
            and subject_bounds[2] <= container_bounds[2] + GEOMETRY_EPSILON
            and subject_bounds[3] <= container_bounds[3] + GEOMETRY_EPSILON
        )
    if not all(point_in_polygon(point, container) for point in subject):
        return False
    if _polygon_is_convex(container):
        return True
    for index, start in enumerate(subject):
        end = subject[(index + 1) % len(subject)]
        for boundary_index, boundary_start in enumerate(container):
            boundary_end = container[(boundary_index + 1) % len(container)]
            left_a = _cross(start, end, boundary_start)
            left_b = _cross(start, end, boundary_end)
            right_a = _cross(boundary_start, boundary_end, start)
            right_b = _cross(boundary_start, boundary_end, end)
            if (
                ((left_a > GEOMETRY_EPSILON and left_b < -GEOMETRY_EPSILON)
                 or (left_a < -GEOMETRY_EPSILON and left_b > GEOMETRY_EPSILON))
                and (
                    (right_a > GEOMETRY_EPSILON and right_b < -GEOMETRY_EPSILON)
                    or (right_a < -GEOMETRY_EPSILON and right_b > GEOMETRY_EPSILON)
                )
            ):
                return False
        midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        if not point_in_polygon(midpoint, container):
            return False
    return True


def point_segment_distance(point: Point2, start: Point2, end: Point2) -> float:
    dx = end[0] - start[0]
    dz = end[1] - start[1]
    denominator = dx * dx + dz * dz
    if denominator <= GEOMETRY_EPSILON:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    factor = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dz)
            / denominator,
        ),
    )
    projection = (start[0] + factor * dx, start[1] + factor * dz)
    return math.hypot(point[0] - projection[0], point[1] - projection[1])


def polygon_boundary_distance(
    subject: Sequence[Point2],
    container: Sequence[Point2],
) -> float:
    return min(
        point_segment_distance(
            point,
            container[index],
            container[(index + 1) % len(container)],
        )
        for point in subject
        for index in range(len(container))
    )


def _convex_hull(points: Iterable[Point2]) -> tuple[Point2, ...]:
    unique = sorted(set(points))
    if len(unique) <= 2:
        return tuple(unique)

    def build(values: Sequence[Point2]) -> list[Point2]:
        result: list[Point2] = []
        for point in values:
            while (
                len(result) >= 2
                and _cross(result[-2], result[-1], point) <= GEOMETRY_EPSILON
            ):
                result.pop()
            result.append(point)
        return result

    lower = build(unique)
    upper = build(tuple(reversed(unique)))
    return tuple(lower[:-1] + upper[:-1])


def oriented_box_polygon(
    center: Point2,
    half_extents: Point2,
    yaw_radians: float,
) -> tuple[Point2, ...]:
    cosine = math.cos(yaw_radians)
    sine = math.sin(yaw_radians)
    result = []
    for x, z in (
        (-half_extents[0], -half_extents[1]),
        (half_extents[0], -half_extents[1]),
        (half_extents[0], half_extents[1]),
        (-half_extents[0], half_extents[1]),
    ):
        result.append(
            (
                center[0] + x * cosine + z * sine,
                center[1] - x * sine + z * cosine,
            )
        )
    return tuple(result)


def _quaternion(value: Mapping[str, Any]) -> tuple[float, float, float, float]:
    if not isinstance(value, Mapping):
        raise ValueError("transform.quaternion must be an object")
    result = tuple(
        _number(value.get(key), f"transform.quaternion.{key}")
        for key in ("x", "y", "z", "w")
    )
    norm = math.sqrt(sum(item * item for item in result))
    if norm <= GEOMETRY_EPSILON:
        raise ValueError("transform quaternion has zero length")
    return tuple(item / norm for item in result)  # type: ignore[return-value]


def _rotate_vector(
    point: tuple[float, float, float],
    quaternion: tuple[float, float, float, float],
) -> tuple[float, float, float]:
    x, y, z, w = quaternion
    px, py, pz = point
    tx = 2.0 * (y * pz - z * py)
    ty = 2.0 * (z * px - x * pz)
    tz = 2.0 * (x * py - y * px)
    return (
        px + w * tx + (y * tz - z * ty),
        py + w * ty + (z * tx - x * tz),
        pz + w * tz + (x * ty - y * tx),
    )


def _transform_polygon_and_interval(
    polygon: Sequence[Point2],
    local_interval: tuple[float, float],
    transform: Mapping[str, Any],
) -> tuple[tuple[Point2, ...], tuple[float, float]]:
    return _transform_polygon_and_interval_prepared(
        polygon,
        local_interval,
        _prepare_transform(transform),
    )


def _prepare_transform(transform: Mapping[str, Any]) -> PreparedTransform:
    position = _point3(transform.get("position"), "transform.position")
    quaternion = _quaternion(transform.get("quaternion"))
    scale = _number(transform.get("scale", 1), "transform.scale")
    if abs(scale - 1.0) > GEOMETRY_EPSILON:
        raise ValueError("Facility Layout spatial transforms require scale 1")
    return position, quaternion


def _transform_polygon_and_interval_prepared(
    polygon: Sequence[Point2],
    local_interval: tuple[float, float],
    prepared_transform: PreparedTransform,
) -> tuple[tuple[Point2, ...], tuple[float, float]]:
    position, quaternion = prepared_transform
    if quaternion[0] == 0.0 and quaternion[2] == 0.0:
        transformed = tuple(
            (
                rotated[0] + position[0],
                rotated[2] + position[2],
            )
            for local_x, local_z in polygon
            for rotated in (
                _rotate_vector(
                    (local_x, local_interval[0], local_z),
                    quaternion,
                ),
            )
        )
        return transformed, (
            local_interval[0] + position[1],
            local_interval[1] + position[1],
        )
    projected: list[Point2] = []
    y_values: list[float] = []
    for local_y in local_interval:
        for local_x, local_z in polygon:
            rotated = _rotate_vector((local_x, local_y, local_z), quaternion)
            projected.append((rotated[0] + position[0], rotated[2] + position[2]))
            y_values.append(rotated[1] + position[1])
    upright = abs(quaternion[0]) <= 1.0e-7 and abs(quaternion[2]) <= 1.0e-7
    if upright:
        transformed = tuple(projected[: len(polygon)])
    else:
        transformed = _convex_hull(projected)
    return transformed, (min(y_values), max(y_values))


def _geometry_definition(asset: Mapping[str, Any]) -> Mapping[str, Any]:
    definition = asset.get("definition")
    if isinstance(definition, Mapping):
        nested = definition.get("geometry")
        if isinstance(nested, Mapping):
            return nested
    geometry = asset.get("geometry")
    return geometry if isinstance(geometry, Mapping) else {}


def _collision_definition(asset: Mapping[str, Any]) -> Mapping[str, Any]:
    definition = asset.get("definition")
    if isinstance(definition, Mapping):
        nested = definition.get("collision")
        if isinstance(nested, Mapping):
            return nested
    collision = asset.get("collision")
    return collision if isinstance(collision, Mapping) else {}


def _asset_field(asset: Mapping[str, Any], field: str, default: Any = None) -> Any:
    if field in asset:
        return asset[field]
    definition = asset.get("definition")
    if isinstance(definition, Mapping) and field in definition:
        return definition[field]
    identity = asset.get("identity")
    if isinstance(identity, Mapping) and field in identity:
        return identity[field]
    return default


def _asset_catalog(
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    if isinstance(asset_definitions, Mapping):
        raw_assets = asset_definitions.get("assets")
        if isinstance(raw_assets, list):
            values = raw_assets
        elif _asset_field(asset_definitions, "assetId"):
            values = [asset_definitions]
        else:
            values = [
                value
                for _, value in sorted(asset_definitions.items(), key=lambda item: str(item[0]))
                if isinstance(value, Mapping)
            ]
    elif isinstance(asset_definitions, Sequence):
        values = list(asset_definitions)
    else:
        raise ValueError("asset_definitions must be a mapping or sequence")
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        asset_id = _asset_field(raw, "assetId")
        if isinstance(asset_id, str) and asset_id:
            revision = _asset_field(raw, "assetDefinitionRevision", "")
            result[(asset_id, str(revision or ""))] = raw
    return result


def _catalog_asset(
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
    asset_id: str,
    revision: str,
) -> Mapping[str, Any] | None:
    exact = catalog.get((asset_id, revision))
    if exact is not None:
        return exact
    matches = [
        value
        for (candidate_id, _candidate_revision), value in catalog.items()
        if candidate_id == asset_id
    ]
    return matches[0] if len(matches) == 1 else None


def _local_footprints(asset: Mapping[str, Any]) -> tuple[tuple[Point2, ...], ...]:
    geometry = _geometry_definition(asset)
    raw = geometry.get("footprintPolygons")
    if isinstance(raw, list) and raw:
        polygons = tuple(
            _polygon(value, f"geometry.footprintPolygons[{index}]")
            for index, value in enumerate(raw)
        )
    else:
        obb = geometry.get("obb")
        if not isinstance(obb, Mapping):
            raise ValueError("asset footprint geometry is missing")
        center_raw = obb.get("center")
        if not isinstance(center_raw, Mapping):
            raise ValueError("asset OBB center is missing")
        center = _point2(center_raw, "geometry.obb.center")
        half_raw = obb.get("halfExtents")
        if isinstance(half_raw, Mapping):
            half = _point2(half_raw, "geometry.obb.halfExtents")
        else:
            size_raw = obb.get("size")
            if not isinstance(size_raw, Mapping):
                raise ValueError("asset OBB halfExtents or size is missing")
            size = _point2(size_raw, "geometry.obb.size")
            half = (size[0] / 2.0, size[1] / 2.0)
        if half[0] <= 0 or half[1] <= 0:
            raise ValueError("asset OBB extents must be positive")
        yaw = _number(obb.get("yawRadians", 0), "geometry.obb.yawRadians")
        polygons = (oriented_box_polygon(center, half, yaw),)
    collision = _collision_definition(asset)
    collision_geometry = collision.get("geometry")
    if isinstance(collision_geometry, Mapping):
        footprint_index = collision_geometry.get("footprintIndex")
        if isinstance(footprint_index, int) and not isinstance(footprint_index, bool):
            if not 0 <= footprint_index < len(polygons):
                raise ValueError("collision footprintIndex is outside the geometry")
            return (polygons[footprint_index],)
    return polygons


def _local_height_interval(asset: Mapping[str, Any]) -> tuple[float, float]:
    collision = _collision_definition(asset)
    raw = collision.get("verticalInterval")
    if not isinstance(raw, Mapping):
        raw = _geometry_definition(asset).get("heightInterval")
    if not isinstance(raw, Mapping):
        obb = _geometry_definition(asset).get("obb")
        if isinstance(obb, Mapping):
            center = obb.get("center")
            half = obb.get("halfExtents")
            size = obb.get("size")
            if isinstance(center, Mapping) and (
                isinstance(half, Mapping) or isinstance(size, Mapping)
            ):
                center_y = _number(center.get("y", 0), "geometry.obb.center.y")
                if isinstance(half, Mapping):
                    half_y = _number(
                        half.get("y"),
                        "geometry.obb.halfExtents.y",
                    )
                else:
                    half_y = _number(size.get("y"), "geometry.obb.size.y") / 2.0
                raw = {
                    "minimumY": center_y - half_y,
                    "maximumY": center_y + half_y,
                }
    if not isinstance(raw, Mapping):
        raise ValueError("asset height interval is missing")
    minimum = _number(raw.get("minimumY"), "heightInterval.minimumY")
    maximum = _number(raw.get("maximumY"), "heightInterval.maximumY")
    if maximum < minimum:
        raise ValueError("asset height interval is inverted")
    return minimum, maximum


@dataclass(frozen=True)
class SpatialRecord:
    """One queryable 2.5D polygon record."""

    record_id: str
    owner_id: str
    asset_id: str
    polygon: tuple[Point2, ...]
    minimum_y: float
    maximum_y: float
    record_kind: str = "physical"
    clearance_id: str | None = None
    clearance_kind: str | None = None
    enforcement: str | None = None
    evidence_status: str = "unknown"
    authoritative: bool = False
    _bounds: Bounds2 = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_bounds", polygon_bounds(self.polygon))

    @property
    def bounds(self) -> Bounds2:
        return self._bounds

    @property
    def interval(self) -> tuple[float, float]:
        return self.minimum_y, self.maximum_y


def placement_spatial_records(
    placement: Mapping[str, Any],
    asset: Mapping[str, Any],
) -> tuple[SpatialRecord, ...]:
    placement_id = str(placement.get("placementId") or "")
    asset_id = str(placement.get("assetId") or _asset_field(asset, "assetId") or "")
    if not placement_id or not asset_id:
        raise ValueError("placement and asset identities are required")
    transform = placement.get("transform")
    if not isinstance(transform, Mapping):
        raise ValueError("placement transform is missing")
    return _placement_spatial_records_from_template(
        placement,
        asset_id,
        _local_footprints(asset),
        _local_height_interval(asset),
    )


def _placement_spatial_records_from_template(
    placement: Mapping[str, Any],
    asset_id: str,
    footprints: Sequence[Sequence[Point2]],
    interval: tuple[float, float],
    *,
    prepared_transform: PreparedTransform | None = None,
) -> tuple[SpatialRecord, ...]:
    placement_id = str(placement.get("placementId") or "")
    transform = placement.get("transform")
    if not isinstance(transform, Mapping):
        raise ValueError("placement transform is missing")
    prepared = prepared_transform or _prepare_transform(transform)
    result = []
    for index, local_polygon in enumerate(footprints):
        polygon, world_interval = _transform_polygon_and_interval_prepared(
            local_polygon,
            interval,
            prepared,
        )
        result.append(
            SpatialRecord(
                record_id=f"physical:{placement_id}:{index}",
                owner_id=placement_id,
                asset_id=asset_id,
                polygon=polygon,
                minimum_y=world_interval[0],
                maximum_y=world_interval[1],
            )
        )
    return tuple(result)


def _shell_feature_polygon(
    feature: Mapping[str, Any],
) -> tuple[Point2, ...] | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, Mapping):
        return None
    raw = (
        geometry.get("boundary")
        or geometry.get("footprint")
        or geometry.get("polygon")
    )
    if isinstance(raw, list):
        try:
            return _polygon(raw, "shell.feature.geometry.boundary")
        except (TypeError, ValueError):
            return None
    minimum = geometry.get("minimum")
    maximum = geometry.get("maximum")
    if isinstance(minimum, Mapping) and isinstance(maximum, Mapping):
        low = _point2(minimum, "shell.feature.geometry.minimum")
        high = _point2(maximum, "shell.feature.geometry.maximum")
        if high[0] > low[0] and high[1] > low[1]:
            return (
                (low[0], low[1]),
                (high[0], low[1]),
                (high[0], high[1]),
                (low[0], high[1]),
            )
    position = geometry.get("position")
    size = geometry.get("size") or geometry.get("dimensions")
    if isinstance(position, Mapping) and isinstance(size, Mapping):
        center = _point2(position, "shell.feature.geometry.position")
        width = _number(
            size.get("x", size.get("width")),
            "shell.feature.geometry.size.x",
        )
        depth = _number(
            size.get("z", size.get("depth")),
            "shell.feature.geometry.size.z",
        )
        if width > 0 and depth > 0:
            return oriented_box_polygon(
                center,
                (width / 2.0, depth / 2.0),
                _number(
                    geometry.get("yawRadians", 0),
                    "shell.feature.geometry.yawRadians",
                ),
            )
    return None


def _shell_feature_interval(
    feature: Mapping[str, Any],
) -> tuple[float, float]:
    geometry = feature.get("geometry")
    if not isinstance(geometry, Mapping):
        return (0.0, 1.0e6)
    raw = geometry.get("verticalInterval")
    if isinstance(raw, Mapping):
        minimum = _number(
            raw.get("minimumY"),
            "shell.feature.geometry.verticalInterval.minimumY",
        )
        maximum = _number(
            raw.get("maximumY"),
            "shell.feature.geometry.verticalInterval.maximumY",
        )
        return (minimum, maximum)
    minimum_raw = geometry.get("minimumY", geometry.get("elevation", 0))
    minimum = _number(minimum_raw, "shell.feature.geometry.minimumY")
    maximum_raw = geometry.get("maximumY")
    if maximum_raw is not None:
        return (
            minimum,
            _number(maximum_raw, "shell.feature.geometry.maximumY"),
        )
    height = geometry.get("height")
    size = geometry.get("size") or geometry.get("dimensions")
    if height is None and isinstance(size, Mapping):
        height = size.get("y", size.get("height"))
    if height is not None:
        return (
            minimum,
            minimum + _number(height, "shell.feature.geometry.height"),
        )
    # Missing height must not create a collision false negative.
    return (minimum, 1.0e6)


def shell_obstacle_records(
    shell: Mapping[str, Any] | None,
) -> tuple[SpatialRecord, ...]:
    if not isinstance(shell, Mapping):
        return ()
    result = []
    for feature in sorted(
        (
            item
            for item in shell.get("features", [])
            if isinstance(item, Mapping)
            and str(item.get("featureKind") or "") in _SHELL_OBSTACLE_KINDS
        ),
        key=lambda item: str(item.get("featureId") or ""),
    ):
        polygon = _shell_feature_polygon(feature)
        if polygon is None:
            continue
        minimum_y, maximum_y = _shell_feature_interval(feature)
        feature_id = str(feature.get("featureId") or "")
        result.append(
            SpatialRecord(
                record_id=f"shell:{feature_id}",
                owner_id=feature_id,
                asset_id="facility-shell",
                polygon=polygon,
                minimum_y=minimum_y,
                maximum_y=maximum_y,
                record_kind="shell_obstacle",
            )
        )
    return tuple(result)


def _clearance_polygon(clearance: Mapping[str, Any]) -> tuple[Point2, ...] | None:
    geometry = clearance.get("geometry")
    if not isinstance(geometry, Mapping):
        return None
    raw_polygon = geometry.get("polygon")
    if raw_polygon is None:
        raw_polygon = geometry.get("boundary")
    if raw_polygon is None:
        raw_polygon = geometry.get("points")
    if isinstance(raw_polygon, list):
        return _polygon(raw_polygon, "clearance.geometry.polygon")
    minimum = geometry.get("minimum")
    maximum = geometry.get("maximum")
    if isinstance(minimum, Mapping) and isinstance(maximum, Mapping):
        low = _point2(minimum, "clearance.geometry.minimum")
        high = _point2(maximum, "clearance.geometry.maximum")
        if high[0] <= low[0] or high[1] <= low[1]:
            raise ValueError("clearance rectangle is degenerate")
        return (
            (low[0], low[1]),
            (high[0], low[1]),
            (high[0], high[1]),
            (low[0], high[1]),
        )
    if geometry.get("shape") in {"obb", "oriented_rectangle"}:
        center_raw = geometry.get("center")
        half_raw = geometry.get("halfExtents")
        if isinstance(center_raw, Mapping) and isinstance(half_raw, Mapping):
            center = _point2(center_raw, "clearance.geometry.center")
            half = _point2(half_raw, "clearance.geometry.halfExtents")
            yaw = _number(geometry.get("yawRadians", 0), "clearance.geometry.yawRadians")
            return oriented_box_polygon(center, half, yaw)
    return None


def _normalized_authority(
    evidence_authority: Mapping[str, Any] | Iterable[str] | None,
) -> dict[str, str]:
    if evidence_authority is None:
        return {}
    if isinstance(evidence_authority, Mapping):
        result = {}
        for key, raw in evidence_authority.items():
            if not isinstance(raw, Mapping):
                continue
            status = raw.get("status")
            blockers = raw.get("blockers", [])
            if (
                status in _EVIDENCE_STATES
                and raw.get("current") is True
                and raw.get("authoritative") is True
                and isinstance(blockers, list)
                and not blockers
            ):
                result[str(key)] = str(status)
        return result
    # Bare IDs have no source, freshness, revocation, or derivation state.
    return {}


def _is_authoritative(
    value: Mapping[str, Any],
    evidence_authority: Mapping[str, str],
) -> bool:
    status = value.get("evidenceStatus")
    refs = value.get("evidence")
    return bool(
        status in _AUTHORITATIVE_EVIDENCE_STATES
        and isinstance(refs, list)
        and refs
        and all(
            evidence_authority.get(str(reference)) in _AUTHORITATIVE_EVIDENCE_STATES
            for reference in refs
        )
    )


def placement_clearance_records(
    placement: Mapping[str, Any],
    asset: Mapping[str, Any],
    *,
    evidence_authority: Mapping[str, Any] | Iterable[str] | None = None,
) -> tuple[SpatialRecord, ...]:
    """Compile clearances from externally validated evidence states."""

    return _placement_clearance_records(
        placement,
        asset,
        _normalized_authority(evidence_authority),
    )


def _placement_clearance_records(
    placement: Mapping[str, Any],
    asset: Mapping[str, Any],
    authority: Mapping[str, str],
) -> tuple[SpatialRecord, ...]:
    placement_id = str(placement.get("placementId") or "")
    asset_id = str(placement.get("assetId") or _asset_field(asset, "assetId") or "")
    transform = placement.get("transform")
    if not isinstance(transform, Mapping):
        raise ValueError("placement transform is missing")
    templates = _clearance_templates(asset, authority)
    return _placement_clearance_records_from_templates(
        placement,
        asset_id,
        templates,
    )


def _clearance_templates(
    asset: Mapping[str, Any],
    authority: Mapping[str, str],
) -> tuple[
    tuple[
        str,
        tuple[Point2, ...],
        tuple[float, float],
        str,
        str,
        str,
        bool,
    ],
    ...,
]:
    default_interval = _local_height_interval(asset)
    raw_clearances = _asset_field(asset, "clearances", [])
    if isinstance(raw_clearances, Mapping):
        raw_clearances = raw_clearances.get("items", [])
    if not isinstance(raw_clearances, list):
        return ()
    result = []
    for index, raw in enumerate(raw_clearances):
        if not isinstance(raw, Mapping):
            continue
        polygon = _clearance_polygon(raw)
        if polygon is None:
            continue
        geometry = raw.get("geometry")
        interval_raw = (
            geometry.get("verticalInterval")
            if isinstance(geometry, Mapping)
            else None
        )
        if not isinstance(interval_raw, Mapping):
            interval_raw = raw.get("verticalInterval")
        if isinstance(interval_raw, Mapping):
            interval = (
                _number(interval_raw.get("minimumY"), "clearance.minimumY"),
                _number(interval_raw.get("maximumY"), "clearance.maximumY"),
            )
        else:
            interval = default_interval
        clearance_id = str(raw.get("clearanceId") or f"clearance-{index}")
        evidence_status = str(raw.get("evidenceStatus") or "unknown")
        result.append(
            (
                clearance_id,
                polygon,
                interval,
                str(raw.get("clearanceKind") or "safety"),
                str(raw.get("enforcement") or "advisory"),
                evidence_status,
                _is_authoritative(raw, authority),
            )
        )
    return tuple(result)


def _placement_clearance_records_from_templates(
    placement: Mapping[str, Any],
    asset_id: str,
    templates: Sequence[
        tuple[
            str,
            tuple[Point2, ...],
            tuple[float, float],
            str,
            str,
            str,
            bool,
        ]
    ],
    *,
    prepared_transform: PreparedTransform | None = None,
) -> tuple[SpatialRecord, ...]:
    placement_id = str(placement.get("placementId") or "")
    transform = placement.get("transform")
    if not isinstance(transform, Mapping):
        raise ValueError("placement transform is missing")
    prepared = prepared_transform or _prepare_transform(transform)
    result = []
    for (
        clearance_id,
        polygon,
        interval,
        clearance_kind,
        enforcement,
        evidence_status,
        authoritative,
    ) in templates:
        world_polygon, world_interval = _transform_polygon_and_interval_prepared(
            polygon,
            interval,
            prepared,
        )
        result.append(
            SpatialRecord(
                record_id=f"clearance:{placement_id}:{clearance_id}",
                owner_id=placement_id,
                asset_id=asset_id,
                polygon=world_polygon,
                minimum_y=world_interval[0],
                maximum_y=world_interval[1],
                record_kind="clearance",
                clearance_id=clearance_id,
                clearance_kind=clearance_kind,
                enforcement=enforcement,
                evidence_status=evidence_status,
                authoritative=authoritative,
            )
        )
    return tuple(result)


class UniformGridSpatialIndex:
    """Deterministic broad phase with exact AABB filtering."""

    def __init__(
        self,
        records: Iterable[SpatialRecord],
        *,
        cell_size: float = DEFAULT_INDEX_CELL_SIZE_METERS,
    ) -> None:
        self.cell_size = _number(cell_size, "cell_size")
        if self.cell_size <= 0:
            raise ValueError("cell_size must be positive")
        ordered = tuple(sorted(records, key=lambda item: item.record_id))
        if len({item.record_id for item in ordered}) != len(ordered):
            raise ValueError("spatial record IDs must be unique")
        self._records = {item.record_id: item for item in ordered}
        cells: dict[tuple[int, int], list[str]] = {}
        for record in ordered:
            for cell in self._cells(record.bounds):
                cells.setdefault(cell, []).append(record.record_id)
        self._cells_by_key = {
            key: tuple(sorted(values))
            for key, values in sorted(cells.items())
        }

    def _cells(self, bounds: Bounds2) -> tuple[tuple[int, int], ...]:
        minimum_x = math.floor(bounds[0] / self.cell_size)
        minimum_z = math.floor(bounds[1] / self.cell_size)
        maximum_x = math.floor(bounds[2] / self.cell_size)
        maximum_z = math.floor(bounds[3] / self.cell_size)
        return tuple(
            (x, z)
            for x in range(minimum_x, maximum_x + 1)
            for z in range(minimum_z, maximum_z + 1)
        )

    def query(
        self,
        bounds: Bounds2,
        *,
        ignore_owner_ids: Iterable[str] = (),
    ) -> tuple[str, ...]:
        ignored = set(ignore_owner_ids)
        candidate_ids = {
            record_id
            for cell in self._cells(bounds)
            for record_id in self._cells_by_key.get(cell, ())
        }
        return tuple(
            record_id
            for record_id in sorted(candidate_ids)
            if self._records[record_id].owner_id not in ignored
            and bounds_intersect(self._records[record_id].bounds, bounds)
        )

    def record(self, record_id: str) -> SpatialRecord:
        return self._records[record_id]


@dataclass(frozen=True)
class _PreparedZoneScene:
    zones: tuple[PreparedZone, ...]
    zones_by_record_id: Mapping[str, PreparedZone]
    index: UniformGridSpatialIndex | None


@dataclass(frozen=True)
class _CandidateObstacleScene:
    physical_index: UniformGridSpatialIndex | None
    clearance_index: UniformGridSpatialIndex | None


_CANDIDATE_OBSTACLE_CACHE: OrderedDict[
    tuple[str, str, str, str],
    _CandidateObstacleScene,
] = OrderedDict()
_CANDIDATE_OBSTACLE_CACHE_LOCK = RLock()
_CANDIDATE_RESULT_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_CANDIDATE_RESULT_CACHE_LOCK = RLock()


def brute_force_query(
    records: Iterable[SpatialRecord],
    bounds: Bounds2,
    *,
    ignore_owner_ids: Iterable[str] = (),
) -> tuple[str, ...]:
    ignored = set(ignore_owner_ids)
    return tuple(
        record.record_id
        for record in sorted(records, key=lambda item: item.record_id)
        if record.owner_id not in ignored and bounds_intersect(record.bounds, bounds)
    )


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    subject_refs: Iterable[str],
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    refs = sorted({str(item) for item in subject_refs if item})
    normalized_details = _canonical_value(dict(details or {}))
    finding_payload = {
        "code": str(code),
        "details": normalized_details,
        "subjectRefs": refs,
        "spatialEngineVersion": SPATIAL_ENGINE_VERSION,
    }
    return {
        "findingId": (
            f"fsf-{_validated_document_fingerprint(finding_payload)[:24]}"
        ),
        "findingType": "facility_spatial",
        "severity": severity,
        "code": code,
        "message": message,
        "subjectRefs": refs,
        "details": normalized_details,
    }


def sort_findings(findings: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for raw in findings:
        finding = dict(raw)
        finding_id = str(finding.get("findingId") or "")
        if finding_id:
            unique[finding_id] = finding
    return sorted(
        unique.values(),
        key=lambda item: (
            _FINDING_SEVERITY_ORDER.get(str(item.get("severity")), 99),
            str(item.get("code") or ""),
            tuple(str(value) for value in item.get("subjectRefs") or ()),
            str(item.get("findingId") or ""),
        ),
    )


def _layout_placement_records(
    layout: Mapping[str, Any],
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[dict[str, tuple[SpatialRecord, ...]], list[dict[str, Any]]]:
    records: dict[str, tuple[SpatialRecord, ...]] = {}
    findings: list[dict[str, Any]] = []
    placements = layout.get("placements")
    if not isinstance(placements, list):
        return records, findings
    templates_by_asset: dict[
        tuple[str, str],
        tuple[tuple[tuple[Point2, ...], ...], tuple[float, float]],
    ] = {}
    for placement in sorted(
        (item for item in placements if isinstance(item, Mapping)),
        key=lambda item: str(item.get("placementId") or ""),
    ):
        placement_id = str(placement.get("placementId") or "")
        asset_id = str(placement.get("assetId") or "")
        revision = str(placement.get("assetDefinitionRevision") or "")
        asset = _catalog_asset(catalog, asset_id, revision)
        if asset is None:
            findings.append(
                _finding(
                    "asset_geometry_missing",
                    "error",
                    "Placement asset geometry is unavailable.",
                    subject_refs=(placement_id, asset_id),
                    details={"assetId": asset_id},
                )
            )
            continue
        try:
            key = (asset_id, revision)
            templates = templates_by_asset.get(key)
            if templates is None:
                templates = (
                    _local_footprints(asset),
                    _local_height_interval(asset),
                )
                templates_by_asset[key] = templates
            transform = placement.get("transform")
            if not isinstance(transform, Mapping):
                raise ValueError("placement transform is missing")
            records[placement_id] = _placement_spatial_records_from_template(
                placement,
                asset_id,
                templates[0],
                templates[1],
                prepared_transform=_prepare_transform(transform),
            )
        except (TypeError, ValueError) as exc:
            findings.append(
                _finding(
                    "asset_geometry_missing",
                    "error",
                    "Placement asset geometry cannot be evaluated.",
                    subject_refs=(placement_id, asset_id),
                    details={"reason": str(exc)},
                )
            )
    return records, findings


def _record_pair_intersects(
    left: SpatialRecord,
    right: SpatialRecord,
) -> bool:
    return (
        height_intervals_intersect(left.interval, right.interval)
        and polygons_intersect(left.polygon, right.polygon)
    )


def _placement_collisions(
    records_by_placement: Mapping[str, tuple[SpatialRecord, ...]],
) -> tuple[list[dict[str, Any]], int]:
    records = tuple(
        record
        for placement_records in records_by_placement.values()
        for record in placement_records
    )
    index = UniformGridSpatialIndex(records)
    pair_hits: set[tuple[str, str]] = set()
    for record in records:
        for other_id in index.query(
            record.bounds,
            ignore_owner_ids=(record.owner_id,),
        ):
            other = index.record(other_id)
            pair = tuple(sorted((record.owner_id, other.owner_id)))
            if pair in pair_hits:
                continue
            if _record_pair_intersects(record, other):
                pair_hits.add(pair)
    findings = [
        _finding(
            "placement_collision",
            "error",
            "Placement collision volumes overlap.",
            subject_refs=pair,
            details={"placementIds": list(pair)},
        )
        for pair in sorted(pair_hits)
    ]
    return findings, len(pair_hits)


def _shell_obstacle_collisions(
    records_by_placement: Mapping[str, tuple[SpatialRecord, ...]],
    shell: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], int]:
    obstacles = shell_obstacle_records(shell)
    if not obstacles:
        return [], 0
    index = UniformGridSpatialIndex(obstacles)
    hits: set[tuple[str, str]] = set()
    for placement_id in sorted(records_by_placement):
        for record in records_by_placement[placement_id]:
            for obstacle_id in index.query(record.bounds):
                obstacle = index.record(obstacle_id)
                pair = (placement_id, obstacle.owner_id)
                if pair in hits:
                    continue
                if _record_pair_intersects(record, obstacle):
                    hits.add(pair)
    return [
        _finding(
            "shell_obstacle_collision",
            "error",
            "Placement collision volume intersects a fixed Facility Shell obstacle.",
            subject_refs=pair,
            details={
                "placementId": pair[0],
                "shellFeatureId": pair[1],
            },
        )
        for pair in sorted(hits)
    ], len(hits)


def _placement_polygon(
    records: Sequence[SpatialRecord],
) -> tuple[Point2, ...]:
    if len(records) == 1:
        return records[0].polygon
    points = [point for record in records for point in record.polygon]
    return _convex_hull(points)


def _zone_candidates(layout: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    zones = layout.get("zones")
    return sorted(
        (zone for zone in zones if isinstance(zone, Mapping))
        if isinstance(zones, list)
        else (),
        key=lambda zone: str(zone.get("zoneId") or ""),
    )


def _prepare_zones(layout: Mapping[str, Any]) -> _PreparedZoneScene:
    prepared = []
    records = []
    for zone in _zone_candidates(layout):
        try:
            boundary = _polygon(
                zone.get("boundary"),
                f"zone[{zone.get('zoneId')}].boundary",
            )
        except (TypeError, ValueError):
            continue
        item = (zone, boundary, polygon_bounds(boundary))
        record_id = f"zone:{len(prepared):06d}"
        prepared.append(item)
        records.append(
            SpatialRecord(
                record_id=record_id,
                owner_id=record_id,
                asset_id="",
                polygon=boundary,
                minimum_y=0.0,
                maximum_y=0.0,
                record_kind="zone",
            )
        )
    zones = tuple(prepared)
    return _PreparedZoneScene(
        zones=zones,
        zones_by_record_id={
            record.record_id: item
            for record, item in zip(records, zones)
        },
        index=UniformGridSpatialIndex(records) if records else None,
    )


def _zone_checks(
    layout: Mapping[str, Any],
    placement: Mapping[str, Any],
    asset: Mapping[str, Any],
    records: Sequence[SpatialRecord],
    *,
    prepared_zones: _PreparedZoneScene | None = None,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    scene = prepared_zones or _prepare_zones(layout)
    zones = scene.zones
    if not zones:
        return [], ()
    placement_id = str(placement.get("placementId") or "")
    category = str(_asset_field(asset, "category", "") or "")
    subject = _placement_polygon(records)
    subject_bounds = polygon_bounds(subject)
    candidate_zones = (
        tuple(
            scene.zones_by_record_id[record_id]
            for record_id in scene.index.query(subject_bounds)
        )
        if scene.index is not None
        else ()
    )
    minimum_y = min(record.minimum_y for record in records)
    maximum_y = max(record.maximum_y for record in records)
    prohibited: list[Mapping[str, Any]] = []
    operational: list[PreparedZone] = []
    for zone, boundary, boundary_bounds in candidate_zones:
        zone_type = str(zone.get("zoneType") or "")
        if zone_type in _NON_PLACEMENT_ZONE_TYPES:
            if (
                bounds_intersect(boundary_bounds, subject_bounds)
                and polygons_intersect(boundary, subject)
            ):
                prohibited.append(zone)
            continue
        operational.append((zone, boundary, boundary_bounds))
    if prohibited:
        return [
            _finding(
                "exclusion_zone_violation",
                "error",
                "Placement intersects a zone that prohibits equipment placement.",
                subject_refs=(
                    placement_id,
                    *(
                        str(zone.get("zoneId") or "")
                        for zone in prohibited
                    ),
                ),
                details={
                    "assetCategory": category,
                    "reason": "prohibited_zone",
                    "zoneTypes": sorted(
                        {
                            str(zone.get("zoneType") or "")
                            for zone in prohibited
                        }
                    ),
                },
            )
        ], ()
    # Non-placement zones constrain occupancy but are never fallback
    # containment zones for equipment.
    if not any(
        str(zone.get("zoneType") or "") not in _NON_PLACEMENT_ZONE_TYPES
        for zone, _, _ in zones
    ):
        return [], ()
    contained: list[Mapping[str, Any]] = []
    for zone, boundary, boundary_bounds in operational:
        if (
            bounds_intersect(boundary_bounds, subject_bounds)
            and polygon_contains_polygon(boundary, subject)
        ):
            setback_values = zone.get("edgeSetbacks")
            setback = (
                max(
                    (
                        _number(value, "zone.edgeSetbacks")
                        for value in setback_values.values()
                    ),
                    default=0.0,
                )
                if isinstance(setback_values, Mapping)
                else 0.0
            )
            if setback <= GEOMETRY_EPSILON or polygon_boundary_distance(
                subject, boundary
            ) + GEOMETRY_EPSILON >= setback:
                contained.append(zone)
    if not contained:
        return [
            _finding(
                "zone_containment_violation",
                "error",
                "Placement footprint is not contained by an applicable zone.",
                subject_refs=(placement_id,),
                    details={"reason": "footprint_or_setback"},
            )
        ], ()

    compatible = []
    for zone in contained:
        allowed = zone.get("allowedAssetCategories")
        if not isinstance(allowed, list) or not allowed or category in allowed:
            compatible.append(zone)
    if contained and not compatible:
        return [
            _finding(
                "zone_kind_incompatible",
                "error",
                "Placement asset category is incompatible with the containing zone.",
                subject_refs=(
                    placement_id,
                    *(str(zone.get("zoneId") or "") for zone in contained),
                ),
                details={"assetCategory": category},
            )
        ], tuple(str(zone.get("zoneId")) for zone in contained)
    applicable = compatible
    height_ok = []
    for zone in applicable:
        floor_elevation = _number(
            zone.get("floorElevation", minimum_y),
            "zone.floorElevation",
        )
        height_limit = zone.get("heightLimit")
        if height_limit is None or maximum_y <= floor_elevation + _number(
            height_limit, "zone.heightLimit"
        ) + GEOMETRY_EPSILON:
            height_ok.append(zone)
    if not height_ok:
        return [
            _finding(
                "zone_containment_violation",
                "error",
                "Placement exceeds the height limit of every compatible zone.",
                subject_refs=(
                    placement_id,
                    *(str(zone.get("zoneId") or "") for zone in applicable),
                ),
                details={
                    "maximumY": _rounded(maximum_y),
                    "reason": "height_limit",
                },
            )
        ], tuple(str(zone.get("zoneId")) for zone in contained)
    return [], tuple(
        sorted(str(zone.get("zoneId")) for zone in height_ok if zone.get("zoneId"))
    )


def _mounting_reference(placement: Mapping[str, Any]) -> dict[str, Any]:
    metadata = placement.get("metadata")
    raw = None
    if isinstance(metadata, Mapping):
        raw = metadata.get("mountingSurfaceRef")
        if raw is None:
            raw = metadata.get("mountingSurface")
    snap = placement.get("snapRelationship")
    if raw is None and isinstance(snap, Mapping):
        family = snap.get("family") or snap.get("kind")
        if family in {"foundation", "mounting_surface", "floor"}:
            raw = snap
    if not isinstance(raw, Mapping):
        return {"surfaceKind": "floor", "featureId": None}
    return {
        "surfaceKind": str(
            raw.get("surfaceKind")
            or raw.get("mountingKind")
            or raw.get("kind")
            or "floor"
        ),
        "featureId": raw.get("featureId") or raw.get("surfaceId"),
    }


def _surface_kind(feature: Mapping[str, Any]) -> str:
    kind = str(feature.get("featureKind") or "")
    if kind == "floor_surface":
        return "floor"
    if kind in {"foundation", "foundation_surface"}:
        return "foundation"
    if kind == "mounting_surface":
        return str(feature.get("surfaceKind") or "mounting_surface")
    return kind


def _surface_boundary(feature: Mapping[str, Any]) -> tuple[Point2, ...] | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, Mapping):
        return None
    raw = geometry.get("boundary")
    if not isinstance(raw, list):
        return None
    try:
        return _polygon(raw, "surface.geometry.boundary")
    except (TypeError, ValueError):
        return None


def _prepare_mounting_surfaces(
    shell: Mapping[str, Any] | None,
) -> tuple[PreparedSurface, ...]:
    if not isinstance(shell, Mapping):
        return ()
    features = shell.get("features")
    if not isinstance(features, list):
        return ()
    return tuple(
        (
            feature,
            _surface_kind(feature),
            _surface_boundary(feature),
        )
        for feature in features
        if isinstance(feature, Mapping)
    )


def _mounting_checks(
    placement: Mapping[str, Any],
    asset: Mapping[str, Any],
    records: Sequence[SpatialRecord],
    shell: Mapping[str, Any] | None,
    *,
    prepared_surfaces: Sequence[PreparedSurface] | None = None,
) -> list[dict[str, Any]]:
    placement_id = str(placement.get("placementId") or "")
    reference = _mounting_reference(placement)
    requested_kind = str(reference["surfaceKind"])
    coordinate = _asset_field(asset, "coordinateFrame", {})
    allowed = (
        coordinate.get("allowedMountingSurfaces")
        if isinstance(coordinate, Mapping)
        else None
    )
    if isinstance(allowed, list) and allowed and requested_kind not in allowed:
        return [
            _finding(
                "unsupported_mounting_surface",
                "error",
                "Asset does not support the requested mounting surface.",
                subject_refs=(placement_id,),
                details={
                    "allowedMountingSurfaces": sorted(str(item) for item in allowed),
                    "requestedSurfaceKind": requested_kind,
                },
            )
        ]
    if not isinstance(shell, Mapping):
        return [
            _finding(
                "unsupported_mounting_surface",
                "unverified",
                "Facility mounting-surface geometry is unavailable.",
                subject_refs=(placement_id,),
                details={"requestedSurfaceKind": requested_kind},
            )
        ]
    surfaces = (
        tuple(prepared_surfaces)
        if prepared_surfaces is not None
        else _prepare_mounting_surfaces(shell)
    )
    matching = [
        (feature, boundary)
        for feature, surface_kind, boundary in surfaces
        if surface_kind == requested_kind
        and (
            reference["featureId"] is None
            or feature.get("featureId") == reference["featureId"]
        )
    ]
    if not matching:
        return [
            _finding(
                "unsupported_mounting_surface",
                "error",
                "Requested mounting surface does not exist in the Facility Shell.",
                subject_refs=(placement_id,),
                details={
                    "featureId": reference["featureId"],
                    "requestedSurfaceKind": requested_kind,
                },
            )
        ]
    footprint = _placement_polygon(records)
    containing = [
        feature
        for feature, boundary in matching
        if boundary is not None
        and polygon_contains_polygon(boundary, footprint)
    ]
    if not containing:
        code = "placement_outside_floor" if requested_kind == "floor" else "unsupported_mounting_surface"
        return [
            _finding(
                code,
                "error",
                "Placement footprint is outside the requested mounting surface.",
                subject_refs=(placement_id,),
                details={"requestedSurfaceKind": requested_kind},
            )
        ]
    anchor = (
        coordinate.get("floorAnchor")
        if isinstance(coordinate, Mapping)
        else None
    )
    anchor_y = (
        _number(anchor.get("y", 0), "coordinateFrame.floorAnchor.y")
        if isinstance(anchor, Mapping)
        else 0.0
    )
    position = placement.get("transform", {}).get("position")
    position_y = (
        _number(position.get("y"), "transform.position.y")
        if isinstance(position, Mapping)
        else 0.0
    )
    elevations = []
    for feature in containing:
        geometry = feature.get("geometry")
        if isinstance(geometry, Mapping):
            elevations.append(
                _number(
                    geometry.get(
                        "elevation",
                        shell.get("coordinateFrame", {}).get("floorElevation", 0),
                    ),
                    "surface.geometry.elevation",
                )
            )
    if elevations and not any(
        abs(position_y + anchor_y - elevation) <= 1.0e-6
        for elevation in elevations
    ):
        return [
            _finding(
                "unsupported_mounting_surface",
                "error",
                "Placement elevation does not coincide with its mounting surface.",
                subject_refs=(placement_id,),
                details={
                    "placementSupportY": _rounded(position_y + anchor_y),
                    "surfaceElevations": sorted(_rounded(item) for item in elevations),
                },
            )
        ]
    return []


def _authority_for_value(
    value: Mapping[str, Any],
    fallback_evidence: Sequence[str],
    evidence_authority: Mapping[str, str],
) -> bool:
    status = value.get("evidenceStatus")
    refs = value.get("evidence")
    if not isinstance(refs, list) or not refs:
        refs = list(fallback_evidence)
    return bool(
        status in _AUTHORITATIVE_EVIDENCE_STATES
        and refs
        and all(
            evidence_authority.get(str(item)) in _AUTHORITATIVE_EVIDENCE_STATES
            for item in refs
        )
    )


def _load_limit_value(limit: Mapping[str, Any]) -> float | None:
    for key in (
        "maximumKgPerSquareMeter",
        "maximumKilogramsPerSquareMeter",
        "maxKgPerSquareMeter",
    ):
        if key in limit:
            return _number(limit[key], f"loadLimit.{key}")
    if limit.get("unit") in {"kg/m2", "kg_per_m2"} and "value" in limit:
        return _number(limit["value"], "loadLimit.value")
    return None


def _mass_value(asset: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, float | None]:
    loading = _asset_field(asset, "loading", {})
    if not isinstance(loading, Mapping):
        return None, None
    for key in ("operatingMass", "installedMass"):
        value = loading.get(key)
        if (
            isinstance(value, Mapping)
            and value.get("value") is not None
            and value.get("unit") == "kg"
        ):
            return value, _number(value["value"], f"loading.{key}.value")
    return None, None


def _support_model(
    asset: Mapping[str, Any],
    evidence_authority: Mapping[str, Any],
) -> tuple[list[tuple[float, float]] | None, bool, str | None]:
    loading = _asset_field(asset, "loading", {})
    if not isinstance(loading, Mapping):
        return None, False, "loading_model_missing"
    raw = loading.get("contactLoads")
    if not isinstance(raw, list) or not raw:
        return None, False, "contact_loads_missing"
    support_points = loading.get("supportPoints")
    if not isinstance(support_points, list) or not support_points:
        return None, False, "support_geometry_missing"
    authoritative = True
    fallback = loading.get("evidence")
    fallback_refs = fallback if isinstance(fallback, list) else []
    for item in support_points:
        if not isinstance(item, Mapping):
            return None, False, "support_geometry_invalid"
        position = item.get("position") or item.get("point")
        if not isinstance(position, Mapping):
            return None, False, "support_geometry_missing"
        try:
            _point2(position, "loading.supportPoints.position")
        except (TypeError, ValueError):
            return None, False, "support_geometry_invalid"
        authoritative = authoritative and _authority_for_value(
            item,
            fallback_refs,
            evidence_authority,
        )
    contacts: list[tuple[float, float]] = []
    fractions = 0.0
    for item in raw:
        if not isinstance(item, Mapping):
            return None, False, "contact_load_invalid"
        area = item.get("areaSquareMeters")
        if area is None:
            area = item.get("contactAreaSquareMeters")
        fraction = item.get("loadFraction")
        if area is None or fraction is None:
            return None, False, "contact_distribution_missing"
        area_value = _number(
            area,
            "loading.contactLoads.areaSquareMeters",
        )
        fraction_value = _number(
            fraction,
            "loading.contactLoads.loadFraction",
        )
        if area_value <= GEOMETRY_EPSILON or fraction_value <= 0:
            return None, False, "contact_distribution_invalid"
        contacts.append((area_value, fraction_value))
        fractions += fraction_value
        authoritative = authoritative and _authority_for_value(
            item,
            fallback_refs,
            evidence_authority,
        )
    if abs(fractions - 1.0) > 1.0e-6:
        return None, False, "contact_distribution_invalid"
    dynamic = loading.get("dynamicLoadFactors")
    if not isinstance(dynamic, list) or not dynamic:
        return None, False, "dynamic_load_factor_missing"
    factors = []
    for item in dynamic:
        if not isinstance(item, Mapping):
            return None, False, "dynamic_load_factor_invalid"
        raw_factor = item.get("factor", item.get("value"))
        if raw_factor is None:
            return None, False, "dynamic_load_factor_invalid"
        factor = _number(raw_factor, "loading.dynamicLoadFactors.factor")
        if factor < 1.0:
            return None, False, "dynamic_load_factor_invalid"
        factors.append(factor)
        authoritative = authoritative and _authority_for_value(
            item,
            fallback_refs,
            evidence_authority,
        )
    dynamic_factor = max(factors)
    return [
        (area, fraction * dynamic_factor)
        for area, fraction in contacts
    ], authoritative, None


def _floor_load_checks(
    placement: Mapping[str, Any],
    asset: Mapping[str, Any],
    containing_zone_ids: Sequence[str],
    layout: Mapping[str, Any],
    evidence_authority: Mapping[str, Any],
    *,
    zone_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    placement_id = str(placement.get("placementId") or "")
    if zone_by_id is None:
        zone_by_id = {
            str(zone.get("zoneId")): zone
            for zone in _zone_candidates(layout)
            if zone.get("zoneId")
        }
    applicable = [
        zone_by_id[zone_id]
        for zone_id in containing_zone_ids
        if zone_id in zone_by_id
    ]
    load_zones = [
        zone
        for zone in applicable
        if isinstance(zone.get("loadLimit"), Mapping)
    ]
    if not load_zones:
        return [
            _finding(
                "floor_load_unverified",
                "unverified",
                "Applicable floor capacity is not established.",
                subject_refs=(placement_id, *containing_zone_ids),
                details={"reason": "floor_capacity_missing"},
            )
        ]
    mass_record, mass = _mass_value(asset)
    loading = _asset_field(asset, "loading", {})
    loading_evidence = (
        loading.get("evidence")
        if isinstance(loading, Mapping) and isinstance(loading.get("evidence"), list)
        else []
    )
    mass_authoritative = bool(
        isinstance(mass_record, Mapping)
        and _authority_for_value(
            mass_record,
            loading_evidence,
            evidence_authority,
        )
    )
    support_model, support_authoritative, support_reason = _support_model(
        asset,
        evidence_authority,
    )
    if (
        mass is None
        or support_model is None
        or not mass_authoritative
        or not support_authoritative
    ):
        reason_by_support_failure = {
            "contact_loads_missing": "asset_contact_loading_missing",
            "contact_load_invalid": "asset_contact_loading_missing",
            "support_geometry_missing": "asset_support_geometry_missing",
            "support_geometry_invalid": "asset_support_geometry_missing",
            "contact_distribution_missing": (
                "asset_contact_distribution_missing"
            ),
            "contact_distribution_invalid": (
                "asset_contact_distribution_missing"
            ),
            "dynamic_load_factor_missing": (
                "asset_dynamic_load_factor_missing"
            ),
            "dynamic_load_factor_invalid": (
                "asset_dynamic_load_factor_missing"
            ),
            "loading_model_missing": "asset_contact_loading_missing",
        }
        return [
            _finding(
                "floor_load_unverified",
                "unverified",
                "Installed load, support, contact distribution, or dynamic-load evidence is incomplete.",
                subject_refs=(placement_id,),
                details={
                    "reason": reason_by_support_failure.get(
                        str(support_reason),
                        "asset_contact_loading_missing",
                    )
                },
            )
        ]
    pressure = max(
        mass * adjusted_fraction / area
        for area, adjusted_fraction in support_model
    )
    findings = []
    authoritative_limit_seen = False
    for zone in load_zones:
        limit = zone["loadLimit"]
        if (
            not isinstance(limit.get("policyRuleRef"), str)
            or not limit.get("policyRuleRef")
            or limit.get("ruleType") != "maximum_floor_load"
        ):
            findings.append(
                _finding(
                    "policy_rule_unavailable",
                    "unverified",
                    "Applicable floor-load limit is not bound to a supported policy rule.",
                    subject_refs=(
                        placement_id,
                        str(zone.get("zoneId") or ""),
                    ),
                    details={"reason": "floor_policy_missing"},
                )
            )
            continue
        limit_value = _load_limit_value(limit)
        zone_evidence = zone.get("evidence")
        fallback_refs = zone_evidence if isinstance(zone_evidence, list) else []
        authoritative = _authority_for_value(
            limit,
            fallback_refs,
            evidence_authority,
        )
        if limit_value is None or not authoritative:
            continue
        authoritative_limit_seen = True
        if pressure > limit_value + GEOMETRY_EPSILON:
            findings.append(
                _finding(
                    "floor_load_exceeded",
                    "error",
                    "Placement contact loading exceeds the authoritative floor limit.",
                    subject_refs=(placement_id, str(zone.get("zoneId") or "")),
                    details={
                        "contactLoadKgPerSquareMeter": _rounded(pressure),
                        "limitKgPerSquareMeter": _rounded(limit_value),
                    },
                )
            )
    if not authoritative_limit_seen:
        findings.append(
            _finding(
                "floor_load_unverified",
                "unverified",
                "Applicable floor-load limits are not authoritative.",
                subject_refs=(
                    placement_id,
                    *(str(zone.get("zoneId") or "") for zone in load_zones),
                ),
                details={"reason": "floor_capacity_evidence_missing"},
            )
        )
    return findings


def _clearance_checks(
    layout: Mapping[str, Any],
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
    records_by_placement: Mapping[str, tuple[SpatialRecord, ...]],
    evidence_authority: Mapping[str, str],
) -> tuple[list[dict[str, Any]], int]:
    placement_by_id = {
        str(item.get("placementId")): item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    findings: list[dict[str, Any]] = []
    conflict_count = 0
    templates_by_asset: dict[
        tuple[str, str],
        tuple[
            tuple[
                str,
                tuple[Point2, ...],
                tuple[float, float],
                str,
                str,
                str,
                bool,
            ],
            ...,
        ],
    ] = {}
    prepared = []
    for placement_id in sorted(placement_by_id):
        placement = placement_by_id[placement_id]
        asset_id = str(placement.get("assetId") or "")
        revision = str(placement.get("assetDefinitionRevision") or "")
        asset = _catalog_asset(
            catalog,
            asset_id,
            revision,
        )
        if asset is None:
            continue
        raw_clearances = _asset_field(asset, "clearances", [])
        if isinstance(raw_clearances, Mapping):
            raw_clearances = raw_clearances.get("items", [])
        key = (asset_id, revision)
        templates = templates_by_asset.get(key)
        if templates is None:
            templates = _clearance_templates(asset, evidence_authority)
            templates_by_asset[key] = templates
        defined_count = (
            len(raw_clearances) if isinstance(raw_clearances, list) else 0
        )
        prepared.append(
            (
                placement_id,
                placement,
                asset_id,
                templates,
                defined_count,
            )
        )
    if prepared and not any(item[3] for item in prepared):
        return [
            _finding(
                "clearance_rule_unavailable",
                "unverified",
                "Authoritative safety-clearance evidence is unavailable.",
                subject_refs=(placement_id,),
                details={"definedClearanceCount": defined_count},
            )
            for placement_id, _, _, _, defined_count in prepared
        ], 0

    physical = tuple(
        record
        for records in records_by_placement.values()
        for record in records
    )
    index = UniformGridSpatialIndex(physical)
    for placement_id, placement, asset_id, templates, defined_count in prepared:
        if templates:
            transform = placement.get("transform")
            if not isinstance(transform, Mapping):
                raise ValueError("placement transform is missing")
            clearance_records = _placement_clearance_records_from_templates(
                placement,
                asset_id,
                templates,
                prepared_transform=_prepare_transform(transform),
            )
        else:
            clearance_records = ()
        safety_records = tuple(
            record
            for record in clearance_records
            if record.clearance_kind in {"safety", "operating", "egress"}
        )
        safety_evidence_complete = bool(safety_records) and all(
            record.authoritative for record in safety_records
        )
        if not safety_evidence_complete:
            findings.append(
                _finding(
                    "clearance_rule_unavailable",
                    "unverified",
                    "Authoritative safety-clearance evidence is unavailable.",
                    subject_refs=(placement_id,),
                    details={"definedClearanceCount": defined_count},
                )
            )
        for clearance in clearance_records:
            hit_owners = set()
            for physical_id in index.query(
                clearance.bounds,
                ignore_owner_ids=(placement_id,),
            ):
                obstacle = index.record(physical_id)
                if obstacle.owner_id in hit_owners:
                    continue
                if _record_pair_intersects(clearance, obstacle):
                    hit_owners.add(obstacle.owner_id)
                    conflict_count += 1
                    code = _CLEARANCE_FINDING_CODES.get(
                        str(clearance.clearance_kind),
                        "safety_clearance_violation",
                    )
                    severity = (
                        "error"
                        if clearance.enforcement == "hard" and clearance.authoritative
                        else "warning"
                    )
                    findings.append(
                        _finding(
                            code,
                            severity,
                            "Named clearance envelope intersects another placement.",
                            subject_refs=(placement_id, obstacle.owner_id),
                            details={
                                "authoritative": clearance.authoritative,
                                "clearanceId": clearance.clearance_id,
                                "clearanceKind": clearance.clearance_kind,
                                "clearanceOwnerId": placement_id,
                                "enforcement": clearance.enforcement,
                                "obstaclePlacementId": obstacle.owner_id,
                            },
                        )
                    )
                    if not clearance.authoritative:
                        findings.append(
                            _finding(
                                "clearance_rule_unavailable",
                                "unverified",
                                "Conflicting clearance is not backed by authoritative evidence.",
                                subject_refs=(placement_id, obstacle.owner_id),
                                details={
                                    "clearanceId": clearance.clearance_id,
                                    "clearanceOwnerId": placement_id,
                                    "evidenceStatus": clearance.evidence_status,
                                    "obstaclePlacementId": obstacle.owner_id,
                                },
                            )
                        )
    return findings, conflict_count


def _safety_status(findings: Sequence[Mapping[str, Any]]) -> str:
    if any(item.get("severity") == "error" for item in findings):
        return "unsafe"
    if any(item.get("severity") == "unverified" for item in findings):
        return "unverified"
    return "safe"


def _evidence_refs_authoritative(
    value: Mapping[str, Any],
    evidence_authority: Mapping[str, str],
) -> bool:
    refs = value.get("evidence")
    return bool(
        isinstance(refs, list)
        and refs
        and all(
            evidence_authority.get(str(item))
            in _AUTHORITATIVE_EVIDENCE_STATES
            for item in refs
        )
    )


def _rule_applies(
    rule: Mapping[str, Any],
    *,
    category: str,
    zone_types: frozenset[str],
) -> bool:
    applicability = rule.get("applicability")
    if not isinstance(applicability, Mapping):
        return True
    categories = applicability.get("assetCategories")
    if isinstance(categories, list) and categories and category not in {
        str(item) for item in categories
    }:
        return False
    required_zone_types = applicability.get("zoneTypes")
    if (
        isinstance(required_zone_types, list)
        and required_zone_types
        and not zone_types.intersection(
            str(item) for item in required_zone_types
        )
    ):
        return False
    return True


def _clearance_margin(
    physical: Sequence[SpatialRecord],
    clearance: SpatialRecord,
) -> float:
    physical_bounds = bounds_union([item.bounds for item in physical])
    clearance_bounds = clearance.bounds
    return min(
        physical_bounds[0] - clearance_bounds[0],
        physical_bounds[1] - clearance_bounds[1],
        clearance_bounds[2] - physical_bounds[2],
        clearance_bounds[3] - physical_bounds[3],
    )


def _policy_checks(
    layout: Mapping[str, Any],
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
    records_by_placement: Mapping[str, tuple[SpatialRecord, ...]],
    zone_membership: Mapping[str, tuple[str, ...]],
    policy_set: Mapping[str, Any] | None,
    evidence_authority: Mapping[str, str],
) -> list[dict[str, Any]]:
    placements = {
        str(item.get("placementId")): item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    if not placements:
        return []
    if not isinstance(policy_set, Mapping):
        return [
            _finding(
                "policy_rule_unavailable",
                "unverified",
                "A published applicable Facility policy is unavailable.",
                subject_refs=tuple(sorted(placements)),
                details={"reason": "policy_set_missing"},
            )
        ]
    rules = [
        item
        for item in policy_set.get("deterministicRules", [])
        if isinstance(item, Mapping)
    ]
    if not rules:
        return [
            _finding(
                "policy_rule_unavailable",
                "unverified",
                "No supported authoritative policy rule applies to this placement.",
                subject_refs=(placement_id,),
                details={"reason": "applicable_policy_missing"},
            )
            for placement_id in sorted(records_by_placement)
        ]
    zones = {
        str(item.get("zoneId")): item
        for item in layout.get("zones", [])
        if isinstance(item, Mapping) and item.get("zoneId")
    }
    findings: list[dict[str, Any]] = []
    for placement_id in sorted(placements):
        placement = placements[placement_id]
        asset = _catalog_asset(
            catalog,
            str(placement.get("assetId") or ""),
            str(placement.get("assetDefinitionRevision") or ""),
        )
        if asset is None:
            continue
        category = str(_asset_field(asset, "category", "") or "")
        zone_types = frozenset(
            str(zones[zone_id].get("zoneType") or "")
            for zone_id in zone_membership.get(placement_id, ())
            if zone_id in zones
        )
        applicable = [
            rule
            for rule in rules
            if _rule_applies(
                rule,
                category=category,
                zone_types=zone_types,
            )
        ]
        supported_authoritative = [
            rule
            for rule in applicable
            if str(rule.get("ruleType") or "") in _SUPPORTED_POLICY_RULE_TYPES
            and _evidence_refs_authoritative(rule, evidence_authority)
        ]
        for rule in applicable:
            rule_type = str(rule.get("ruleType") or "")
            rule_id = str(rule.get("ruleId") or "policy-rule")
            if rule_type not in _SUPPORTED_POLICY_RULE_TYPES:
                findings.append(
                    _finding(
                        "policy_rule_unavailable",
                        "unverified",
                        "Published policy rule has no registered deterministic evaluator.",
                        subject_refs=(placement_id, rule_id),
                        details={"ruleType": rule_type},
                    )
                )
            elif not _evidence_refs_authoritative(rule, evidence_authority):
                findings.append(
                    _finding(
                        "policy_rule_unavailable",
                        "unverified",
                        "Applicable policy rule lacks current authoritative evidence.",
                        subject_refs=(placement_id, rule_id),
                        details={
                            "reason": "policy_evidence_unavailable",
                            "ruleType": rule_type,
                        },
                    )
                )
        if not supported_authoritative:
            findings.append(
                _finding(
                    "policy_rule_unavailable",
                    "unverified",
                    "No supported authoritative policy rule applies to this placement.",
                    subject_refs=(placement_id,),
                    details={"reason": "applicable_policy_missing"},
                )
            )
            continue
        clearances = _placement_clearance_records(
            placement,
            asset,
            evidence_authority,
        )
        physical = records_by_placement.get(placement_id, ())
        for rule in supported_authoritative:
            rule_type = str(rule.get("ruleType") or "")
            rule_id = str(rule.get("ruleId") or "")
            parameters = rule.get("parameters")
            parameters = parameters if isinstance(parameters, Mapping) else {}
            if rule_type == "maximum_floor_load":
                continue
            if rule_type == "require_authoritative_clearance":
                raw_kinds = parameters.get(
                    "clearanceKinds",
                    ["safety", "operating", "egress"],
                )
                kinds = {
                    str(item)
                    for item in raw_kinds
                } if isinstance(raw_kinds, list) else {"safety"}
                available = {
                    str(item.clearance_kind)
                    for item in clearances
                    if item.authoritative
                }
                missing = sorted(kinds - available)
                if missing:
                    findings.append(
                        _finding(
                            "clearance_rule_unavailable",
                            "unverified",
                            "Applicable policy requires authoritative clearance envelopes that are unavailable.",
                            subject_refs=(placement_id, rule_id),
                            details={"missingClearanceKinds": missing},
                        )
                    )
                continue
            kind = (
                "egress"
                if rule_type == "minimum_egress_clearance"
                else str(parameters.get("clearanceKind") or "safety")
            )
            minimum = parameters.get(
                "minimumWidthMeters"
                if rule_type == "minimum_egress_clearance"
                else "minimumMeters"
            )
            if minimum is None:
                findings.append(
                    _finding(
                        "policy_rule_unavailable",
                        "unverified",
                        "Applicable minimum-clearance policy has no deterministic threshold.",
                        subject_refs=(placement_id, rule_id),
                        details={"ruleType": rule_type},
                    )
                )
                continue
            minimum_value = _number(minimum, "policy.minimumClearance")
            matching = [
                item
                for item in clearances
                if item.clearance_kind == kind and item.authoritative
            ]
            if not matching or not physical:
                findings.append(
                    _finding(
                        "clearance_rule_unavailable",
                        "unverified",
                        "Applicable minimum-clearance policy cannot be evaluated.",
                        subject_refs=(placement_id, rule_id),
                        details={"clearanceKind": kind},
                    )
                )
                continue
            actual = max(
                _clearance_margin(physical, item)
                for item in matching
            )
            if actual + GEOMETRY_EPSILON < minimum_value:
                code = _CLEARANCE_FINDING_CODES.get(
                    kind,
                    "safety_clearance_violation",
                )
                findings.append(
                    _finding(
                        code,
                        "error",
                        "Authoritative clearance envelope is smaller than the applicable policy minimum.",
                        subject_refs=(placement_id, rule_id),
                        details={
                            "actualMeters": _rounded(actual),
                            "clearanceKind": kind,
                            "minimumMeters": _rounded(minimum_value),
                        },
                    )
                )
    return findings


def _authority_gap_checks(
    layout: Mapping[str, Any],
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    shell: Mapping[str, Any] | None,
    policy_set: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for placement in layout.get("placements", []):
        if not isinstance(placement, Mapping):
            continue
        placement_id = str(placement.get("placementId") or "")
        asset = _catalog_asset(
            catalog,
            str(placement.get("assetId") or ""),
            str(placement.get("assetDefinitionRevision") or ""),
        )
        if asset is None:
            continue
        readiness = _asset_field(asset, "readiness", {})
        planning = (
            readiness.get("planningReady")
            if isinstance(readiness, Mapping)
            else None
        )
        if isinstance(planning, Mapping) and planning.get("value") is False:
            findings.append(
                _finding(
                    "asset_planning_evidence_unavailable",
                    "unverified",
                    "Asset is placement-ready but lacks reviewed planning evidence.",
                    subject_refs=(placement_id, str(placement.get("assetId") or "")),
                    details={
                        "blockers": sorted(
                            str(item)
                            for item in planning.get("blockers", [])
                            if isinstance(item, str)
                        )
                    },
                )
            )
    if isinstance(shell, Mapping):
        for index, item in enumerate(shell.get("unresolvedItems", [])):
            if not isinstance(item, Mapping):
                continue
            findings.append(
                _finding(
                    "shell_evidence_unavailable",
                    "unverified",
                    str(
                        item.get("message")
                        or "Facility Shell contains unresolved engineering evidence."
                    ),
                    subject_refs=(
                        str(shell.get("shellId") or "facility-shell"),
                        str(item.get("findingId") or f"shell-unresolved-{index}"),
                    ),
                    details={"sourceCode": str(item.get("code") or "")},
                )
            )
    if isinstance(policy_set, Mapping):
        for index, item in enumerate(policy_set.get("unresolvedItems", [])):
            if not isinstance(item, Mapping):
                continue
            findings.append(
                _finding(
                    "policy_rule_unavailable",
                    "unverified",
                    str(
                        item.get("message")
                        or "Facility policy contains an unresolved rule."
                    ),
                    subject_refs=(
                        str(policy_set.get("policySetId") or "policy-set"),
                        str(item.get("findingId") or f"policy-unresolved-{index}"),
                    ),
                    details={"sourceCode": str(item.get("code") or "")},
                )
            )
    return findings


def diagnose_layout(
    layout: Mapping[str, Any],
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    shell: Mapping[str, Any] | None = None,
    policy_set: Mapping[str, Any] | None = None,
    evidence_authority: Mapping[str, Any] | Iterable[str] | None = None,
    cancel_check: CancelCheck | None = None,
    _prepared_zones: _PreparedZoneScene | None = None,
    _prepared_surfaces: Sequence[PreparedSurface] | None = None,
) -> dict[str, Any]:
    """Return authoritative deterministic spatial findings for a layout."""

    _check_cancel(cancel_check)
    catalog = _asset_catalog(asset_definitions)
    authority = _normalized_authority(evidence_authority)
    records_by_placement, findings = _layout_placement_records(layout, catalog)
    collision_findings, collision_count = _placement_collisions(records_by_placement)
    findings.extend(collision_findings)
    shell_findings, shell_collision_count = _shell_obstacle_collisions(
        records_by_placement,
        shell,
    )
    findings.extend(shell_findings)
    placements = {
        str(item.get("placementId")): item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    prepared_zones = _prepared_zones or _prepare_zones(layout)
    zone_by_id = {
        str(zone.get("zoneId")): zone
        for zone, _, _ in prepared_zones.zones
        if zone.get("zoneId")
    }
    prepared_surfaces = (
        tuple(_prepared_surfaces)
        if _prepared_surfaces is not None
        else _prepare_mounting_surfaces(shell)
    )
    zone_membership: dict[str, tuple[str, ...]] = {}
    for placement_id in sorted(records_by_placement):
        _check_cancel(cancel_check)
        placement = placements[placement_id]
        asset = _catalog_asset(
            catalog,
            str(placement.get("assetId") or ""),
            str(placement.get("assetDefinitionRevision") or ""),
        )
        if asset is None:
            continue
        zone_findings, zone_ids = _zone_checks(
            layout,
            placement,
            asset,
            records_by_placement[placement_id],
            prepared_zones=prepared_zones,
        )
        findings.extend(zone_findings)
        zone_membership[placement_id] = zone_ids
        findings.extend(
            _mounting_checks(
                placement,
                asset,
                records_by_placement[placement_id],
                shell,
                prepared_surfaces=prepared_surfaces,
            )
        )
        findings.extend(
            _floor_load_checks(
                placement,
                asset,
                zone_ids,
                layout,
                authority,
                zone_by_id=zone_by_id,
            )
        )
    clearance_findings, clearance_count = _clearance_checks(
        layout,
        catalog,
        records_by_placement,
        authority,
    )
    _check_cancel(cancel_check)
    findings.extend(clearance_findings)
    findings.extend(
        _policy_checks(
            layout,
            catalog,
            records_by_placement,
            zone_membership,
            policy_set,
            authority,
        )
    )
    findings.extend(
        _authority_gap_checks(
            layout,
            catalog,
            shell=shell,
            policy_set=policy_set,
        )
    )
    ordered = sort_findings(findings)
    status = _safety_status(ordered)
    return {
        "spatialEngineVersion": SPATIAL_ENGINE_VERSION,
        "safetyStatus": status,
        "safe": status == "safe",
        "valid": not any(item["severity"] == "error" for item in ordered),
        "findings": ordered,
        "zoneMembership": {
            key: list(zone_membership[key]) for key in sorted(zone_membership)
        },
        "metrics": {
            "placementCount": len(placements),
            "indexedPolygonCount": sum(
                len(records) for records in records_by_placement.values()
            ),
            "placementCollisions": collision_count,
            "shellObstacleCollisions": shell_collision_count,
            "clearanceConflicts": clearance_count,
            "errorCount": sum(item["severity"] == "error" for item in ordered),
            "unverifiedCount": sum(
                item["severity"] == "unverified" for item in ordered
            ),
            "warningCount": sum(item["severity"] == "warning" for item in ordered),
        },
    }


def _polygon_centroid(polygon: Sequence[Point2]) -> Point2:
    area = polygon_area(polygon)
    if abs(area) <= GEOMETRY_EPSILON:
        return (
            sum(point[0] for point in polygon) / len(polygon),
            sum(point[1] for point in polygon) / len(polygon),
        )
    factor = 1.0 / (6.0 * area)
    x = 0.0
    z = 0.0
    for index, current in enumerate(polygon):
        following = polygon[(index + 1) % len(polygon)]
        cross = current[0] * following[1] - following[0] * current[1]
        x += (current[0] + following[0]) * cross
        z += (current[1] + following[1]) * cross
    return x * factor, z * factor


def _nearest_point_on_segment(
    point: Point2,
    start: Point2,
    end: Point2,
) -> Point2:
    dx = end[0] - start[0]
    dz = end[1] - start[1]
    denominator = dx * dx + dz * dz
    if denominator <= GEOMETRY_EPSILON:
        return start
    factor = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dz)
            / denominator,
        ),
    )
    return start[0] + factor * dx, start[1] + factor * dz


def _identity_quaternion() -> dict[str, float]:
    return {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}


def _normalized_transform(
    position: Point2,
    y: float,
    quaternion: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _quaternion(quaternion)
    return {
        "position": {
            "x": _rounded(position[0]),
            "y": _rounded(y),
            "z": _rounded(position[1]),
        },
        "quaternion": {
            "x": _rounded(normalized[0]),
            "y": _rounded(normalized[1]),
            "z": _rounded(normalized[2]),
            "w": _rounded(normalized[3]),
        },
        "scale": 1,
    }


def _candidate_layout_fingerprint(layout: Mapping[str, Any]) -> str:
    return _validated_document_fingerprint(
        {
            "coordinateFrame": layout.get("coordinateFrame"),
            "layoutId": layout.get("layoutId"),
            "placements": sorted(
                (
                    {
                        "assetDefinitionRevision": item.get("assetDefinitionRevision"),
                        "assetId": item.get("assetId"),
                        "placementId": item.get("placementId"),
                        "positionMode": item.get("positionMode"),
                        "transform": item.get("transform"),
                    }
                    for item in layout.get("placements", [])
                    if isinstance(item, Mapping)
                ),
                key=lambda item: str(item.get("placementId") or ""),
            ),
            "zones": sorted(
                (
                    {
                        "anchors": sorted(
                            (
                                anchor
                                for anchor in item.get("anchors", [])
                                if isinstance(anchor, Mapping)
                            ),
                            key=lambda anchor: str(anchor.get("anchorId") or ""),
                        ),
                        "boundary": item.get("boundary"),
                        "edgeSetbacks": item.get("edgeSetbacks"),
                        "gridSpacing": item.get("gridSpacing"),
                        "heightLimit": item.get("heightLimit"),
                        "preferredOrientation": item.get("preferredOrientation"),
                        "zoneId": item.get("zoneId"),
                    }
                    for item in layout.get("zones", [])
                    if isinstance(item, Mapping)
                ),
                key=lambda item: str(item.get("zoneId") or ""),
            ),
        }
    )


def _obstacle_fingerprint(
    layout: Mapping[str, Any],
    shell: Mapping[str, Any] | None,
) -> str:
    return _validated_document_fingerprint(
        {
            "placements": sorted(
                (
                    {
                        "assetDefinitionRevision": item.get("assetDefinitionRevision"),
                        "assetId": item.get("assetId"),
                        "placementId": item.get("placementId"),
                        "transform": item.get("transform"),
                    }
                    for item in layout.get("placements", [])
                    if isinstance(item, Mapping)
                ),
                key=lambda item: str(item.get("placementId") or ""),
            ),
            "shellFeatures": (
                sorted(
                    (
                        {
                            "featureId": item.get("featureId"),
                            "featureKind": item.get("featureKind"),
                            "geometry": item.get("geometry"),
                        }
                        for item in shell.get("features", [])
                        if isinstance(item, Mapping)
                    ),
                    key=lambda item: str(item.get("featureId") or ""),
                )
                if isinstance(shell, Mapping)
                else []
            ),
        }
    )


def _placement_for_candidate(
    *,
    target_placement_id: str,
    asset_id: str,
    asset_definition_revision: str,
    transform: Mapping[str, Any],
    snap_relationship: Mapping[str, Any] | None,
    existing_placement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    existing = existing_placement or {}
    return {
        "placementId": target_placement_id,
        "assetId": asset_id,
        "assetDefinitionRevision": asset_definition_revision,
        "transform": _canonical_value(transform),
        "positionMode": str(existing.get("positionMode") or "auto"),
        "snapRelationship": _canonical_value(snap_relationship),
        "metadata": _canonical_value(existing.get("metadata") or {}),
    }


def _layout_with_candidate(
    layout: Mapping[str, Any],
    placement: Mapping[str, Any],
    *,
    replace_placement_id: str | None,
) -> dict[str, Any]:
    result = {
        key: _canonical_value(value)
        for key, value in layout.items()
    }
    existing = [
        item
        for item in result.get("placements", [])
        if not (
            replace_placement_id is not None
            and item.get("placementId") == replace_placement_id
        )
    ]
    existing.append(_canonical_value(placement))
    result["placements"] = sorted(
        existing,
        key=lambda item: str(item.get("placementId") or ""),
    )
    return result


def _family_seed_candidates(
    layout: Mapping[str, Any],
    asset: Mapping[str, Any],
    requested: Point2,
    *,
    shell: Mapping[str, Any] | None,
    enabled_families: frozenset[str],
) -> list[tuple[str, Point2, dict[str, Any] | None]]:
    seeds: list[tuple[str, Point2, dict[str, Any] | None]] = []
    zones = _zone_candidates(layout)
    grid_values = [
        _number(zone.get("gridSpacing"), "zone.gridSpacing")
        for zone in zones
        if zone.get("gridSpacing") is not None
    ]
    grid = min(grid_values) if grid_values else DEFAULT_GRID_SPACING_METERS
    if "grid" in enabled_families:
        seeds.append(
            (
                "grid",
                (
                    round(requested[0] / grid) * grid,
                    round(requested[1] / grid) * grid,
                ),
                {"family": "grid", "gridSpacing": _rounded(grid)},
            )
        )

    local_bounds = bounds_union(
        [polygon_bounds(polygon) for polygon in _local_footprints(asset)]
    )
    local_center = (
        (local_bounds[0] + local_bounds[2]) / 2.0,
        (local_bounds[1] + local_bounds[3]) / 2.0,
    )
    inset = max(
        math.hypot(point[0] - local_center[0], point[1] - local_center[1])
        for polygon in _local_footprints(asset)
        for point in polygon
    ) + 0.01
    for zone in zones:
        zone_id = str(zone.get("zoneId") or "")
        try:
            boundary = _polygon(zone.get("boundary"), f"zone[{zone_id}].boundary")
        except (TypeError, ValueError):
            continue
        if "boundary" in enabled_families:
            for edge_index, start in enumerate(boundary):
                end = boundary[(edge_index + 1) % len(boundary)]
                nearest = _nearest_point_on_segment(requested, start, end)
                edge_x = end[0] - start[0]
                edge_z = end[1] - start[1]
                edge_length = math.hypot(edge_x, edge_z)
                if edge_length <= GEOMETRY_EPSILON:
                    continue
                orientation = 1.0 if polygon_area(boundary) > 0 else -1.0
                normal = (
                    orientation * -edge_z / edge_length,
                    orientation * edge_x / edge_length,
                )
                probe = (
                    nearest[0] + normal[0] * 0.001,
                    nearest[1] + normal[1] * 0.001,
                )
                if not point_in_polygon(probe, boundary):
                    normal = (-normal[0], -normal[1])
                position = (
                    nearest[0] + inset * normal[0],
                    nearest[1] + inset * normal[1],
                )
                seeds.append(
                    (
                        "boundary",
                        position,
                        {
                            "edgeIndex": edge_index,
                            "family": "boundary",
                            "zoneId": zone_id,
                        },
                    )
                )
        anchors = zone.get("anchors")
        if isinstance(anchors, list):
            for anchor in sorted(
                (item for item in anchors if isinstance(item, Mapping)),
                key=lambda item: str(item.get("anchorId") or ""),
            ):
                kind = str(anchor.get("anchorKind") or "")
                if kind not in enabled_families or kind not in {"row", "bay", "foundation"}:
                    continue
                position_raw = anchor.get("position")
                if not isinstance(position_raw, Mapping):
                    continue
                seeds.append(
                    (
                        kind,
                        _point2(position_raw, "zone.anchor.position"),
                        {
                            "anchorId": str(anchor.get("anchorId") or ""),
                            "family": kind,
                            **(
                                {
                                    "mountingElevation": _number(
                                        position_raw.get("y", 0),
                                        "zone.anchor.position.y",
                                    ),
                                    "surfaceKind": "foundation",
                                }
                                if kind == "foundation"
                                else {}
                            ),
                            "zoneId": zone_id,
                        },
                    )
                )

    placements = sorted(
        (
            placement
            for placement in layout.get("placements", [])
            if isinstance(placement, Mapping)
        ),
        key=lambda item: str(item.get("placementId") or ""),
    )
    alignment_x: dict[float, tuple[float, str]] = {}
    alignment_z: dict[float, tuple[float, str]] = {}
    for placement in placements:
        position = placement.get("transform", {}).get("position")
        if not isinstance(position, Mapping):
            continue
        other = _point2(position, "placement.transform.position")
        placement_id = str(placement.get("placementId") or "")
        x_key = _rounded(other[0])
        z_key = _rounded(other[1])
        x_candidate = (_rounded(abs(other[1] - requested[1])), placement_id)
        z_candidate = (_rounded(abs(other[0] - requested[0])), placement_id)
        if x_key not in alignment_x or x_candidate < alignment_x[x_key]:
            alignment_x[x_key] = x_candidate
        if z_key not in alignment_z or z_candidate < alignment_z[z_key]:
            alignment_z[z_key] = z_candidate

    nearest_x = sorted(
        alignment_x.items(),
        key=lambda item: (
            _rounded(abs(item[0] - requested[0])),
            item[1][0],
            item[0],
            item[1][1],
        ),
    )[:4]
    nearest_z = sorted(
        alignment_z.items(),
        key=lambda item: (
            _rounded(abs(item[0] - requested[1])),
            item[1][0],
            item[0],
            item[1][1],
        ),
    )[:4]
    if "alignment" in enabled_families:
        for x_value, (_, placement_id) in nearest_x:
            seeds.append(
                (
                    "alignment",
                    (x_value, requested[1]),
                    {
                        "axis": "x",
                        "family": "alignment",
                        "targetPlacementId": placement_id,
                    },
                )
            )
        for z_value, (_, placement_id) in nearest_z:
            seeds.append(
                (
                    "alignment",
                    (requested[0], z_value),
                    {
                        "axis": "z",
                        "family": "alignment",
                        "targetPlacementId": placement_id,
                    },
                )
            )
    if "row" in enabled_families:
        for z_value, (_, placement_id) in nearest_z:
            seeds.append(
                (
                    "row",
                    (requested[0], z_value),
                    {
                        "axis": "z",
                        "family": "row",
                        "targetPlacementId": placement_id,
                    },
                )
            )

    if "foundation" in enabled_families and isinstance(shell, Mapping):
        features = sorted(
            (
                feature
                for feature in shell.get("features", [])
                if isinstance(feature, Mapping)
                and _surface_kind(feature) == "foundation"
            ),
            key=lambda item: str(item.get("featureId") or ""),
        )
        for feature in features:
            geometry = feature.get("geometry")
            position = geometry.get("position") if isinstance(geometry, Mapping) else None
            if isinstance(position, Mapping):
                point = _point2(position, "foundation.geometry.position")
            else:
                boundary = _surface_boundary(feature)
                if boundary is None:
                    continue
                point = _polygon_centroid(boundary)
            seeds.append(
                (
                    "foundation",
                    point,
                    {
                        "family": "foundation",
                        "featureId": str(feature.get("featureId") or ""),
                        "mountingElevation": _number(
                            (
                                geometry.get("elevation", 0)
                                if isinstance(geometry, Mapping)
                                else 0
                            ),
                            "foundation.geometry.elevation",
                        ),
                        "surfaceKind": "foundation",
                    },
                )
            )
    return seeds


def _candidate_subject_findings(
    diagnostics: Mapping[str, Any],
    candidate_placement_id: str,
) -> list[dict[str, Any]]:
    return [
        dict(finding)
        for finding in diagnostics.get("findings", [])
        if candidate_placement_id in (finding.get("subjectRefs") or [])
    ]


def _candidate_metrics(
    findings: Sequence[Mapping[str, Any]],
    *,
    distance: float,
) -> dict[str, Any]:
    return {
        "distanceFromRequested": _rounded(distance),
        "errorCount": sum(item.get("severity") == "error" for item in findings),
        "unverifiedCount": sum(
            item.get("severity") == "unverified" for item in findings
        ),
        "warningCount": sum(item.get("severity") == "warning" for item in findings),
        "physicalCollisions": sum(
            item.get("code") == "placement_collision" for item in findings
        ),
        "clearanceConflicts": sum(
            str(item.get("code") or "").endswith("_clearance_violation")
            or item.get("code") in {"door_swing_obstructed", "egress_obstructed"}
            for item in findings
        ),
    }


def _candidate_seed_budget(
    values: Sequence[tuple[str, Point2, dict[str, Any] | None]],
    requested: Point2,
    maximum_candidates: int,
) -> tuple[tuple[str, Point2, dict[str, Any] | None], ...]:
    decorated = [
        (
            item,
            _rounded(
                math.hypot(
                    item[1][0] - requested[0],
                    item[1][1] - requested[1],
                )
            ),
            canonical_spatial_bytes(item[2]),
        )
        for item in values
    ]
    ordered = [
        item
        for item, _, _ in sorted(
            decorated,
            key=lambda value: (
                _CANDIDATE_FAMILY_ORDER[value[0][0]],
                value[1],
                _rounded(value[0][1][1]),
                _rounded(value[0][1][0]),
                value[2],
            ),
        )
    ]
    relationship_bytes = {
        id(item): encoded for item, _, encoded in decorated
    }
    distances = {id(item): distance for item, distance, _ in decorated}
    family_count = len({item[0] for item in ordered})
    budget = min(
        len(ordered),
        max(
            family_count,
            min(64, maximum_candidates),
        ),
    )
    if len(ordered) <= budget:
        return tuple(ordered)
    selected: list[tuple[str, Point2, dict[str, Any] | None]] = []
    selected_keys: set[tuple[str, float, float, bytes]] = set()
    for family in sorted(
        {item[0] for item in ordered},
        key=lambda item: _CANDIDATE_FAMILY_ORDER[item],
    ):
        item = next(value for value in ordered if value[0] == family)
        selected.append(item)
        selected_keys.add(
            (
                item[0],
                _rounded(item[1][0]),
                _rounded(item[1][1]),
                relationship_bytes[id(item)],
            )
        )
    for item in sorted(
        ordered,
        key=lambda value: (
            distances[id(value)],
            _CANDIDATE_FAMILY_ORDER[value[0]],
            _rounded(value[1][1]),
            _rounded(value[1][0]),
            relationship_bytes[id(value)],
        ),
    ):
        key = (
            item[0],
            _rounded(item[1][0]),
            _rounded(item[1][1]),
            relationship_bytes[id(item)],
        )
        if key in selected_keys:
            continue
        selected.append(item)
        selected_keys.add(key)
        if len(selected) >= budget:
            break
    return tuple(selected)


def _candidate_cross_findings(
    candidate_records: Sequence[SpatialRecord],
    candidate_clearances: Sequence[SpatialRecord],
    base_physical_index: UniformGridSpatialIndex | None,
    base_clearance_index: UniformGridSpatialIndex | None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    candidate_id = candidate_records[0].owner_id
    physical_hits: set[str] = set()
    if base_physical_index is not None:
        for record in candidate_records:
            for record_id in base_physical_index.query(record.bounds):
                obstacle = base_physical_index.record(record_id)
                if (
                    obstacle.owner_id not in physical_hits
                    and _record_pair_intersects(record, obstacle)
                ):
                    physical_hits.add(obstacle.owner_id)
    for obstacle_id in sorted(physical_hits):
        findings.append(
            _finding(
                "placement_collision",
                "error",
                "Placement collision volumes overlap.",
                subject_refs=(candidate_id, obstacle_id),
                details={
                    "placementIds": sorted((candidate_id, obstacle_id))
                },
            )
        )
    if base_physical_index is not None:
        for clearance in candidate_clearances:
            hit_owners: set[str] = set()
            for record_id in base_physical_index.query(clearance.bounds):
                obstacle = base_physical_index.record(record_id)
                if (
                    obstacle.owner_id not in hit_owners
                    and _record_pair_intersects(clearance, obstacle)
                ):
                    hit_owners.add(obstacle.owner_id)
            for obstacle_id in sorted(hit_owners):
                code = _CLEARANCE_FINDING_CODES.get(
                    str(clearance.clearance_kind),
                    "safety_clearance_violation",
                )
                findings.append(
                    _finding(
                        code,
                        (
                            "error"
                            if clearance.enforcement == "hard"
                            and clearance.authoritative
                            else "warning"
                        ),
                        "Named clearance envelope intersects another placement.",
                        subject_refs=(candidate_id, obstacle_id),
                        details={
                            "authoritative": clearance.authoritative,
                            "clearanceId": clearance.clearance_id,
                            "clearanceKind": clearance.clearance_kind,
                            "clearanceOwnerId": candidate_id,
                            "enforcement": clearance.enforcement,
                            "obstaclePlacementId": obstacle_id,
                        },
                    )
                )
                if not clearance.authoritative:
                    findings.append(
                        _finding(
                            "clearance_rule_unavailable",
                            "unverified",
                            "Conflicting clearance is not backed by authoritative evidence.",
                            subject_refs=(candidate_id, obstacle_id),
                            details={
                                "clearanceId": clearance.clearance_id,
                                "clearanceOwnerId": candidate_id,
                                "evidenceStatus": clearance.evidence_status,
                                "obstaclePlacementId": obstacle_id,
                            },
                        )
                    )
    if base_clearance_index is not None:
        seen: set[tuple[str, str]] = set()
        for record in candidate_records:
            for clearance_id in base_clearance_index.query(record.bounds):
                clearance = base_clearance_index.record(clearance_id)
                pair = (clearance.owner_id, str(clearance.clearance_id))
                if pair in seen or not _record_pair_intersects(record, clearance):
                    continue
                seen.add(pair)
                code = _CLEARANCE_FINDING_CODES.get(
                    str(clearance.clearance_kind),
                    "safety_clearance_violation",
                )
                findings.append(
                    _finding(
                        code,
                        (
                            "error"
                            if clearance.enforcement == "hard"
                            and clearance.authoritative
                            else "warning"
                        ),
                        "Placement intersects an existing named clearance envelope.",
                        subject_refs=(candidate_id, clearance.owner_id),
                        details={
                            "authoritative": clearance.authoritative,
                            "clearanceId": clearance.clearance_id,
                            "clearanceKind": clearance.clearance_kind,
                            "clearanceOwnerId": clearance.owner_id,
                            "enforcement": clearance.enforcement,
                            "obstaclePlacementId": candidate_id,
                        },
                    )
                )
                if not clearance.authoritative:
                    findings.append(
                        _finding(
                            "clearance_rule_unavailable",
                            "unverified",
                            "Existing conflicting clearance lacks authoritative evidence.",
                            subject_refs=(candidate_id, clearance.owner_id),
                            details={
                                "clearanceId": clearance.clearance_id,
                                "clearanceOwnerId": clearance.owner_id,
                                "evidenceStatus": clearance.evidence_status,
                                "obstaclePlacementId": candidate_id,
                            },
                        )
                    )
    return findings


def _candidate_asset_fingerprint(
    placements: Sequence[Mapping[str, Any]],
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
) -> str:
    assets: dict[tuple[str, str], Mapping[str, Any]] = {}
    for placement in placements:
        placement_id = str(placement.get("placementId") or "")
        asset_id = str(placement.get("assetId") or "")
        revision = str(placement.get("assetDefinitionRevision") or "")
        asset = _catalog_asset(catalog, asset_id, revision)
        if asset is None:
            raise ValueError(f"asset geometry is unavailable for {placement_id}")
        assets[(asset_id, revision)] = asset
    return spatial_fingerprint(
        [
            {
                "assetDefinition": assets[key],
                "assetDefinitionRevision": key[1],
                "assetId": key[0],
            }
            for key in sorted(assets)
        ]
    )


def _compile_candidate_obstacle_scene(
    placements: Sequence[Mapping[str, Any]],
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
    authority: Mapping[str, str],
) -> _CandidateObstacleScene:
    physical: list[SpatialRecord] = []
    clearances: list[SpatialRecord] = []
    template_cache: dict[
        tuple[str, str],
        tuple[
            tuple[tuple[Point2, ...], ...],
            tuple[float, float],
            tuple[Any, ...],
        ],
    ] = {}
    for placement in placements:
        placement_id = str(placement.get("placementId") or "")
        asset_id = str(placement.get("assetId") or "")
        revision = str(placement.get("assetDefinitionRevision") or "")
        asset = _catalog_asset(catalog, asset_id, revision)
        if asset is None:
            raise ValueError(f"asset geometry is unavailable for {placement_id}")
        cache_key = (asset_id, revision)
        template = template_cache.get(cache_key)
        if template is None:
            template = (
                _local_footprints(asset),
                _local_height_interval(asset),
                _clearance_templates(asset, authority),
            )
            template_cache[cache_key] = template
        footprints, interval, clearance_templates = template
        transform = placement.get("transform")
        if not isinstance(transform, Mapping):
            raise ValueError("placement transform is missing")
        prepared_transform = _prepare_transform(transform)
        physical.extend(
            _placement_spatial_records_from_template(
                placement,
                asset_id,
                footprints,
                interval,
                prepared_transform=prepared_transform,
            )
        )
        clearances.extend(
            _placement_clearance_records_from_templates(
                placement,
                asset_id,
                clearance_templates,
                prepared_transform=prepared_transform,
            )
        )
    return _CandidateObstacleScene(
        physical_index=UniformGridSpatialIndex(physical) if physical else None,
        clearance_index=(
            UniformGridSpatialIndex(clearances) if clearances else None
        ),
    )


def _candidate_obstacle_scene(
    *,
    placements: Sequence[Mapping[str, Any]],
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
    authority: Mapping[str, str],
    obstacle_fingerprint: str,
    target_placement_id: str | None,
    asset_fingerprint: str,
    authority_fingerprint: str,
) -> _CandidateObstacleScene:
    key = (
        obstacle_fingerprint,
        str(target_placement_id or ""),
        asset_fingerprint,
        authority_fingerprint,
    )
    with _CANDIDATE_OBSTACLE_CACHE_LOCK:
        cached = _CANDIDATE_OBSTACLE_CACHE.get(key)
        if cached is not None:
            _CANDIDATE_OBSTACLE_CACHE.move_to_end(key)
            return cached
    compiled = _compile_candidate_obstacle_scene(
        placements,
        catalog,
        authority,
    )
    with _CANDIDATE_OBSTACLE_CACHE_LOCK:
        existing = _CANDIDATE_OBSTACLE_CACHE.get(key)
        if existing is not None:
            _CANDIDATE_OBSTACLE_CACHE.move_to_end(key)
            return existing
        _CANDIDATE_OBSTACLE_CACHE[key] = compiled
        while len(_CANDIDATE_OBSTACLE_CACHE) > _CANDIDATE_OBSTACLE_CACHE_LIMIT:
            _CANDIDATE_OBSTACLE_CACHE.popitem(last=False)
    return compiled


def _candidate_result_cache_key(
    *,
    base_layout_fingerprint: str,
    obstacle_fingerprint: str,
    base_asset_fingerprint: str,
    asset_definition: Mapping[str, Any],
    zones: Any,
    shell: Mapping[str, Any] | None,
    policy_set: Mapping[str, Any] | None,
    authority: Mapping[str, str],
    requested: Point2,
    requested_y: float,
    requested_quaternion: Mapping[str, Any],
    enabled_families: frozenset[str],
    target_placement_id: str | None,
    asset_definition_revision: str,
    maximum_candidates: int,
) -> str:
    return spatial_fingerprint(
        {
            "assetDefinition": asset_definition,
            "assetDefinitionRevision": asset_definition_revision,
            "authority": authority,
            "baseAssetFingerprint": base_asset_fingerprint,
            "candidatePolicyVersion": CANDIDATE_POLICY_VERSION,
            "enabledFamilies": sorted(enabled_families),
            "layoutFingerprint": base_layout_fingerprint,
            "maximumCandidates": maximum_candidates,
            "obstacleFingerprint": obstacle_fingerprint,
            "policySet": policy_set,
            "requestedPosition": {
                "x": requested[0],
                "y": requested_y,
                "z": requested[1],
            },
            "requestedQuaternion": requested_quaternion,
            "shell": shell,
            "spatialEngineVersion": SPATIAL_ENGINE_VERSION,
            "targetPlacementId": target_placement_id,
            "zones": zones,
        }
    )


def _cached_candidate_result(key: str) -> dict[str, Any] | None:
    with _CANDIDATE_RESULT_CACHE_LOCK:
        result = _CANDIDATE_RESULT_CACHE.get(key)
        if result is None:
            return None
        _CANDIDATE_RESULT_CACHE.move_to_end(key)
        return deepcopy(result)


def _cache_candidate_result(
    key: str,
    result: Mapping[str, Any],
) -> None:
    stored = deepcopy(dict(result))
    with _CANDIDATE_RESULT_CACHE_LOCK:
        _CANDIDATE_RESULT_CACHE[key] = stored
        _CANDIDATE_RESULT_CACHE.move_to_end(key)
        while len(_CANDIDATE_RESULT_CACHE) > _CANDIDATE_RESULT_CACHE_LIMIT:
            _CANDIDATE_RESULT_CACHE.popitem(last=False)


def generate_placement_candidates(
    layout: Mapping[str, Any],
    asset_definition: Mapping[str, Any],
    requested_position: Mapping[str, Any],
    asset_definitions: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    shell: Mapping[str, Any] | None = None,
    policy_set: Mapping[str, Any] | None = None,
    evidence_authority: Mapping[str, Any] | Iterable[str] | None = None,
    enabled_families: Iterable[str] = (
        "grid",
        "boundary",
        "row",
        "bay",
        "alignment",
        "foundation",
    ),
    requested_quaternion: Mapping[str, Any] | None = None,
    target_placement_id: str | None = None,
    asset_definition_revision: str | None = None,
    maximum_candidates: int = 64,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    """Generate deterministic, validated, ranked placement alternatives."""

    _check_cancel(cancel_check)
    if isinstance(maximum_candidates, bool) or not 1 <= maximum_candidates <= 256:
        raise ValueError("maximum_candidates must be between 1 and 256")
    asset_id = str(_asset_field(asset_definition, "assetId") or "")
    if not asset_id:
        raise ValueError("asset_definition requires assetId")
    revision = (
        str(asset_definition_revision)
        if asset_definition_revision is not None
        else str(
            _asset_field(asset_definition, "assetDefinitionRevision")
            or spatial_fingerprint(asset_definition)
        )
    )
    requested = _point2(requested_position, "requested_position")
    requested_y = _number(requested_position.get("y", 0), "requested_position.y")
    quaternion = requested_quaternion or _identity_quaternion()
    family_set = frozenset(str(item) for item in enabled_families)
    unsupported = family_set - set(_CANDIDATE_FAMILY_ORDER)
    if unsupported:
        raise ValueError(f"unsupported candidate families: {sorted(unsupported)}")
    catalog = _asset_catalog(asset_definitions)
    catalog[(asset_id, revision)] = asset_definition
    authority = _normalized_authority(evidence_authority)
    existing_target = None
    if target_placement_id is not None:
        existing_target = next(
            (
                item
                for item in layout.get("placements", [])
                if isinstance(item, Mapping)
                and item.get("placementId") == target_placement_id
            ),
            None,
        )
        if existing_target is None:
            raise ValueError("target_placement_id does not resolve")
        if existing_target.get("positionMode") == "locked":
            return {
                "spatialEngineVersion": SPATIAL_ENGINE_VERSION,
                "candidatePolicyVersion": CANDIDATE_POLICY_VERSION,
                "layoutFingerprint": _candidate_layout_fingerprint(layout),
                "obstacleFingerprint": _obstacle_fingerprint(layout, shell),
                "assetId": asset_id,
                "assetDefinitionRevision": revision,
                "requestedPosition": {
                    "x": _rounded(requested[0]),
                    "y": _rounded(requested_y),
                    "z": _rounded(requested[1]),
                },
                "enabledFamilies": sorted(
                    family_set,
                    key=lambda item: _CANDIDATE_FAMILY_ORDER[item],
                ),
                "seedCount": 0,
                "evaluatedCount": 0,
                "rejectionCounts": {"locked_placement_movement": 1},
                "candidates": [],
            }
        if (
            existing_target.get("assetId") != asset_id
            or existing_target.get("assetDefinitionRevision") != revision
        ):
            raise ValueError(
                "target placement asset identity differs from the candidate asset"
            )
    candidate_placement_id = target_placement_id or "pl-spatial-candidate"
    base_layout_fingerprint = _candidate_layout_fingerprint(layout)
    obstacle_fingerprint = _obstacle_fingerprint(layout, shell)
    # The service supplies a canonical, immutable domain document. A shallow
    # working view is sufficient because this function replaces only the
    # placements list and never mutates caller-owned nested values.
    base_layout = dict(layout)
    base_layout["placements"] = [
        item
        for item in base_layout.get("placements", [])
        if item.get("placementId") != target_placement_id
    ]
    candidate_context = {
        key: value
        for key, value in base_layout.items()
        if key != "placements"
    }
    base_placements = tuple(sorted(
        (
            item
            for item in base_layout.get("placements", [])
            if isinstance(item, Mapping)
        ),
        key=lambda item: str(item.get("placementId") or ""),
    ))
    base_asset_fingerprint = _candidate_asset_fingerprint(
        base_placements,
        catalog,
    )
    authority_fingerprint = spatial_fingerprint(authority)
    result_cache_key = _candidate_result_cache_key(
        base_layout_fingerprint=base_layout_fingerprint,
        obstacle_fingerprint=obstacle_fingerprint,
        base_asset_fingerprint=base_asset_fingerprint,
        asset_definition=asset_definition,
        zones=layout.get("zones"),
        shell=shell,
        policy_set=policy_set,
        authority=authority,
        requested=requested,
        requested_y=requested_y,
        requested_quaternion=quaternion,
        enabled_families=family_set,
        target_placement_id=target_placement_id,
        asset_definition_revision=revision,
        maximum_candidates=maximum_candidates,
    )
    cached_result = _cached_candidate_result(result_cache_key)
    if cached_result is not None:
        _check_cancel(cancel_check)
        return cached_result
    obstacle_scene = _candidate_obstacle_scene(
        placements=base_placements,
        catalog=catalog,
        authority=authority,
        obstacle_fingerprint=obstacle_fingerprint,
        target_placement_id=target_placement_id,
        asset_fingerprint=base_asset_fingerprint,
        authority_fingerprint=authority_fingerprint,
    )
    base_physical_index = obstacle_scene.physical_index
    base_clearance_index = obstacle_scene.clearance_index
    seeds = _family_seed_candidates(
        layout,
        asset_definition,
        requested,
        shell=shell,
        enabled_families=family_set,
    )
    deduplicated: dict[tuple[str, float, float, bytes], tuple[str, Point2, dict[str, Any] | None]] = {}
    for family, position, relationship in seeds:
        key = (
            family,
            _rounded(position[0]),
            _rounded(position[1]),
            canonical_spatial_bytes(relationship),
        )
        deduplicated[key] = (family, position, relationship)
    selected_seeds = _candidate_seed_budget(
        tuple(deduplicated.values()),
        requested,
        maximum_candidates,
    )
    evaluated = []
    rejection_counts: dict[str, int] = {}
    baseline_metrics: dict[str, Any] | None = None
    candidate_zone_scene = _prepare_zones(candidate_context)
    candidate_surfaces = _prepare_mounting_surfaces(shell)
    candidate_footprints = _local_footprints(asset_definition)
    candidate_height_interval = _local_height_interval(asset_definition)
    candidate_clearance_templates = _clearance_templates(
        asset_definition,
        authority,
    )
    for family, position, relationship in selected_seeds:
        _check_cancel(cancel_check)
        candidate_y = (
            _number(
                relationship.get("mountingElevation"),
                "snapRelationship.mountingElevation",
            )
            if isinstance(relationship, Mapping)
            and relationship.get("mountingElevation") is not None
            else requested_y
        )
        transform = _normalized_transform(position, candidate_y, quaternion)
        candidate_id = stable_candidate_id(
            layout_fingerprint=base_layout_fingerprint,
            obstacle_fingerprint=obstacle_fingerprint,
            asset_id=asset_id,
            asset_definition_revision=revision,
            family=family,
            transform=transform,
            snap_relationship=relationship,
        )
        placement = _placement_for_candidate(
            target_placement_id=candidate_placement_id,
            asset_id=asset_id,
            asset_definition_revision=revision,
            transform=transform,
            snap_relationship=relationship,
            existing_placement=existing_target,
        )
        candidate_layout = dict(candidate_context)
        candidate_layout["placements"] = [_canonical_value(placement)]
        diagnostics = diagnose_layout(
            candidate_layout,
            [asset_definition],
            shell=shell,
            policy_set=policy_set,
            evidence_authority=evidence_authority,
            cancel_check=cancel_check,
            _prepared_zones=candidate_zone_scene,
            _prepared_surfaces=candidate_surfaces,
        )
        candidate_transform = placement.get("transform")
        if not isinstance(candidate_transform, Mapping):
            raise ValueError("placement transform is missing")
        prepared_candidate_transform = _prepare_transform(candidate_transform)
        candidate_records = _placement_spatial_records_from_template(
            placement,
            asset_id,
            candidate_footprints,
            candidate_height_interval,
            prepared_transform=prepared_candidate_transform,
        )
        candidate_clearances = _placement_clearance_records_from_templates(
            placement,
            asset_id,
            candidate_clearance_templates,
            prepared_transform=prepared_candidate_transform,
        )
        findings = list(diagnostics.get("findings", []))
        findings.extend(
            _candidate_cross_findings(
                candidate_records,
                candidate_clearances,
                base_physical_index,
                base_clearance_index,
            )
        )
        findings = sort_findings(findings)
        distance = math.hypot(position[0] - requested[0], position[1] - requested[1])
        metrics = _candidate_metrics(findings, distance=distance)
        if baseline_metrics is None and family == "grid":
            baseline_metrics = dict(metrics)
        hard_codes = sorted(
            {
                str(finding.get("code"))
                for finding in findings
                if finding.get("severity") == "error"
            }
        )
        if hard_codes:
            for code in hard_codes:
                rejection_counts[code] = rejection_counts.get(code, 0) + 1
            continue
        score = (
            metrics["physicalCollisions"],
            metrics["clearanceConflicts"],
            metrics["unverifiedCount"],
            metrics["warningCount"],
            _CANDIDATE_FAMILY_ORDER[family],
            _rounded(distance),
            candidate_id,
        )
        evaluated.append(
            (
                score,
                {
                    "candidateId": candidate_id,
                    "spatialEngineVersion": SPATIAL_ENGINE_VERSION,
                    "candidatePolicyVersion": CANDIDATE_POLICY_VERSION,
                    "layoutFingerprint": base_layout_fingerprint,
                    "obstacleFingerprint": obstacle_fingerprint,
                    "assetId": asset_id,
                    "assetDefinitionRevision": revision,
                    "family": family,
                    "transform": transform,
                    "snapRelationship": _canonical_value(relationship),
                    "safetyStatus": _safety_status(findings),
                    "safe": _safety_status(findings) == "safe",
                    "findings": findings,
                    "metrics": metrics,
                    "score": list(score[:-1]) + [candidate_id],
                },
            )
        )
    ranked = [
        candidate
        for _, candidate in sorted(evaluated, key=lambda item: item[0])[
            :maximum_candidates
        ]
    ]
    _check_cancel(cancel_check)
    baseline = baseline_metrics or {
        "distanceFromRequested": 0.0,
        "errorCount": 0,
        "unverifiedCount": 0,
        "warningCount": 0,
        "physicalCollisions": 0,
        "clearanceConflicts": 0,
    }
    for candidate in ranked:
        candidate["beforeAfterMetrics"] = {
            "before": _canonical_value(baseline),
            "after": _canonical_value(candidate["metrics"]),
        }
    result = {
        "spatialEngineVersion": SPATIAL_ENGINE_VERSION,
        "candidatePolicyVersion": CANDIDATE_POLICY_VERSION,
        "layoutFingerprint": base_layout_fingerprint,
        "obstacleFingerprint": obstacle_fingerprint,
        "assetId": asset_id,
        "assetDefinitionRevision": revision,
        "requestedPosition": {
            "x": _rounded(requested[0]),
            "y": _rounded(requested_y),
            "z": _rounded(requested[1]),
        },
        "enabledFamilies": sorted(
            family_set,
            key=lambda item: _CANDIDATE_FAMILY_ORDER[item],
        ),
        "seedCount": len(deduplicated),
        "evaluatedCount": len(selected_seeds),
        "rejectionCounts": {
            key: rejection_counts[key] for key in sorted(rejection_counts)
        },
        "candidates": ranked,
    }
    _cache_candidate_result(result_cache_key, result)
    return result


__all__ = [
    "CANDIDATE_POLICY_VERSION",
    "DEFAULT_INDEX_CELL_SIZE_METERS",
    "GEOMETRY_EPSILON",
    "SPATIAL_ENGINE_VERSION",
    "SpatialRecord",
    "UniformGridSpatialIndex",
    "bounds_intersect",
    "brute_force_query",
    "canonical_spatial_bytes",
    "diagnose_layout",
    "generate_placement_candidates",
    "height_intervals_intersect",
    "oriented_box_polygon",
    "placement_clearance_records",
    "placement_spatial_records",
    "point_in_polygon",
    "polygon_contains_polygon",
    "polygons_intersect",
    "sort_findings",
    "spatial_fingerprint",
    "stable_candidate_id",
    "stable_finding_id",
]
