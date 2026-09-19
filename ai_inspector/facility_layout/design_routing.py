"""Deterministic route compilation and validation for Facility design loops."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping, Sequence

try:
    from shapely import set_precision
    from shapely.errors import GEOSException
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import unary_union
except ImportError:  # pragma: no cover - exercised by fail-closed deployments
    set_precision = None  # type: ignore[assignment]
    GEOSException = Exception  # type: ignore[assignment]
    LineString = Point = Polygon = box = unary_union = None  # type: ignore[assignment]

from .canonical import canonicalize_layout
from .navigation_geometry import (
    NAVIGATION_GEOMETRY_GRID_METERS,
    build_visibility_graph,
    solve_visibility_graph,
)
from .routing import resolve_endpoint
from .spatial import oriented_box_polygon, placement_spatial_records


FACILITY_DESIGN_ROUTE_VALIDATOR_VERSION = "facility-design-route-validator-v1"
FACILITY_DESIGN_ROUTE_ENDPOINT_TOLERANCE_METERS = 0.01
_EPSILON = 1.0e-9


class FacilityDesignRoutingError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = deepcopy(dict(details or {}))


def _fail(code: str, message: str, **details: Any) -> None:
    raise FacilityDesignRoutingError(code, message, details=details)


def _require_geometry() -> None:
    if any(
        value is None
        for value in (set_precision, LineString, Point, Polygon, box, unary_union)
    ):
        _fail(
            "facility_design_geometry_engine_unavailable",
            "Facility design route validation requires the configured geometry engine.",
        )


def _point2(value: Mapping[str, Any], field: str) -> tuple[float, float]:
    try:
        result = float(value["x"]), float(value["z"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FacilityDesignRoutingError(
            "facility_design_route_geometry_invalid",
            f"{field} is not a finite XZ point.",
        ) from exc
    if not all(math.isfinite(item) for item in result):
        _fail(
            "facility_design_route_geometry_invalid",
            f"{field} is not a finite XZ point.",
        )
    return result


def _point3(value: tuple[float, float]) -> dict[str, float]:
    return {
        "x": round(value[0], 6),
        "y": 0.0,
        "z": round(value[1], 6),
    }


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.dist(left, right)


def normalize_design_asset_definitions(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize repository envelopes without synthesizing identity or revision."""

    normalized = []
    for raw in records:
        if not isinstance(raw, Mapping):
            continue
        document: Mapping[str, Any] | None = None
        for field in ("definition", "document", "assetDefinition"):
            candidate = raw.get(field)
            if isinstance(candidate, Mapping):
                document = candidate
                break
        if document is None and raw.get("documentKind") == "industrial_asset_definition":
            document = raw
        if (
            not isinstance(document, Mapping)
            or document.get("documentKind") != "industrial_asset_definition"
        ):
            continue
        asset_id = str(document.get("assetId") or raw.get("assetId") or "")
        revision = str(
            raw.get("assetDefinitionRevision")
            or raw.get("revision")
            or ""
        )
        if not asset_id or not revision:
            continue
        normalized.append(
            {
                "assetId": asset_id,
                "assetDefinitionRevision": revision,
                "definition": deepcopy(dict(document)),
            }
        )
    return sorted(
        normalized,
        key=lambda item: (
            item["assetId"],
            item["assetDefinitionRevision"],
        ),
    )


def _asset_records(source_bundle: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    source = source_bundle or {}
    records = source.get("assetDefinitions", [])
    if not isinstance(records, list):
        return []
    return normalize_design_asset_definitions(records)


def _asset_for_placement(
    placement: Mapping[str, Any],
    source_bundle: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    asset_id = str(placement.get("assetId") or "")
    revision = str(placement.get("assetDefinitionRevision") or "")
    exact = [
        item
        for item in _asset_records(source_bundle)
        if str(item.get("assetId") or "") == asset_id
        and str(item.get("assetDefinitionRevision") or "") == revision
    ]
    return exact[0] if len(exact) == 1 else None


def resolve_design_route_endpoint(
    layout: Mapping[str, Any],
    endpoint: Mapping[str, Any],
    *,
    route_kind: str,
    direction: str,
    source_bundle: Mapping[str, Any] | None,
) -> tuple[float, float]:
    result = resolve_endpoint(
        layout,
        endpoint,
        asset_definitions=_asset_records(source_bundle),
        route_kind=route_kind,
        direction=direction,
    )
    if result.get("resolved") is True:
        return _point2(result["position"], "resolved route endpoint")
    codes = sorted(
        str(item.get("code") or "facility_design_route_endpoint_unavailable")
        for item in result.get("findings", [])
        if isinstance(item, Mapping)
    )
    _fail(
        "facility_design_route_endpoint_unavailable",
        "A revision-bound material-route endpoint could not be resolved.",
        endpoint=deepcopy(dict(endpoint)),
        findingCodes=codes,
    )
    raise AssertionError("unreachable")


def _facility_bounds(layout: Mapping[str, Any]) -> tuple[float, float, float, float]:
    plan = (
        (layout.get("extensions") or {}).get("facilityPlan")
        if isinstance(layout.get("extensions"), Mapping)
        else None
    )
    if isinstance(plan, Mapping):
        try:
            minimum_x = float(plan.get("originX", 0.0))
            minimum_z = float(plan.get("originZ", 0.0))
            width = float(plan["widthMeters"])
            depth = float(plan["depthMeters"])
            if all(math.isfinite(item) for item in (minimum_x, minimum_z, width, depth)) and width > 0 and depth > 0:
                return minimum_x, minimum_z, minimum_x + width, minimum_z + depth
        except (KeyError, TypeError, ValueError):
            pass
    points = [
        _point2(point, "zone boundary")
        for zone in layout.get("zones", [])
        if isinstance(zone, Mapping)
        for point in zone.get("boundary", [])
        if isinstance(point, Mapping)
    ]
    if not points:
        _fail(
            "facility_design_allowed_space_unavailable",
            "The Facility design base has no bounded planning surface.",
        )
    return (
        min(item[0] for item in points),
        min(item[1] for item in points),
        max(item[0] for item in points),
        max(item[1] for item in points),
    )


def _placement_shapes(
    layout: Mapping[str, Any],
    source_bundle: Mapping[str, Any] | None,
    excluded_placement_ids: set[str],
) -> list[Any]:
    shapes = []
    missing_geometry: list[str] = []
    for placement in layout.get("placements", []):
        if not isinstance(placement, Mapping):
            continue
        placement_id = str(placement.get("placementId") or "")
        if not placement_id or placement_id in excluded_placement_ids:
            continue
        asset = _asset_for_placement(placement, source_bundle)
        if asset is None:
            missing_geometry.append(placement_id)
            continue
        try:
            records = placement_spatial_records(placement, asset)
            if not records:
                missing_geometry.append(placement_id)
                continue
            for record in records:
                shapes.append(Polygon(record.polygon))
        except (TypeError, ValueError, GEOSException):
            geometry = (
                (asset.get("definition") or {}).get("geometry")
                if isinstance(asset.get("definition"), Mapping)
                else asset.get("geometry")
            )
            obb = geometry.get("obb") if isinstance(geometry, Mapping) else None
            transform = placement.get("transform")
            position = transform.get("position") if isinstance(transform, Mapping) else None
            quaternion = transform.get("quaternion") if isinstance(transform, Mapping) else None
            if not all(isinstance(item, Mapping) for item in (obb, position, quaternion)):
                missing_geometry.append(placement_id)
                continue
            try:
                center = _point2(obb.get("center") or {}, "asset OBB center")
                half = _point2(obb.get("halfExtents") or {}, "asset OBB half extents")
                placement_center = _point2(position, "placement position")
                yaw = math.atan2(
                    2.0 * (
                        float(quaternion.get("w", 1.0)) * float(quaternion.get("y", 0.0))
                        + float(quaternion.get("x", 0.0)) * float(quaternion.get("z", 0.0))
                    ),
                    1.0
                    - 2.0
                    * (
                        float(quaternion.get("y", 0.0)) ** 2
                        + float(quaternion.get("z", 0.0)) ** 2
                    ),
                ) + float(obb.get("yawRadians", 0.0))
                local_cosine = math.cos(yaw)
                local_sine = math.sin(yaw)
                world_center = (
                    placement_center[0] + center[0] * local_cosine - center[1] * local_sine,
                    placement_center[1] + center[0] * local_sine + center[1] * local_cosine,
                )
                shapes.append(Polygon(oriented_box_polygon(world_center, half, yaw)))
            except (FacilityDesignRoutingError, KeyError, TypeError, ValueError, GEOSException):
                missing_geometry.append(placement_id)
                continue
    if missing_geometry:
        _fail(
            "facility_design_static_geometry_unavailable",
            "Exact static obstacle geometry is unavailable for the candidate route.",
            placementIds=sorted(set(missing_geometry)),
        )
    return shapes


def _protected_shapes(layout: Mapping[str, Any]) -> list[Any]:
    terms = {
        "exclusion",
        "keep_clear",
        "keep_clear_area",
        "no_entry",
        "no_entry_area",
        "restricted",
        "restricted_area",
        "restricted_zone",
        "safety_exclusion",
        "safety_exclusion_area",
    }
    shapes = []
    for zone in layout.get("zones", []):
        if not isinstance(zone, Mapping):
            continue
        values = {
            str(zone.get("zoneType") or "").casefold().replace(" ", "_"),
            str(zone.get("semanticType") or "").casefold().replace(" ", "_"),
            str(zone.get("label") or "").casefold().replace(" ", "_"),
        }
        if not values.intersection(terms):
            continue
        boundary = zone.get("boundary")
        if not isinstance(boundary, list) or len(boundary) < 3:
            continue
        try:
            shape = Polygon([_point2(item, "protected zone") for item in boundary])
        except (FacilityDesignRoutingError, GEOSException):
            continue
        if shape.is_valid and not shape.is_empty:
            shapes.append(shape)
    return shapes


def _external_shapes(source_bundle: Mapping[str, Any] | None) -> list[Any]:
    source = source_bundle or {}
    context = source.get("obstacleContext")
    obstacles = context.get("obstacles", []) if isinstance(context, Mapping) else []
    shapes = []
    for obstacle in obstacles if isinstance(obstacles, list) else []:
        boundary = obstacle.get("boundary") if isinstance(obstacle, Mapping) else None
        if not isinstance(boundary, list) or len(boundary) < 3:
            continue
        try:
            shape = Polygon([_point2(item, "source obstacle") for item in boundary])
        except (FacilityDesignRoutingError, GEOSException):
            continue
        if shape.is_valid and not shape.is_empty:
            shapes.append(shape)
    return shapes


def design_route_free_space(
    layout: Mapping[str, Any],
    *,
    corridor_width_meters: float,
    source_bundle: Mapping[str, Any] | None,
    excluded_placement_ids: Sequence[str] = (),
) -> Any:
    _require_geometry()
    width = float(corridor_width_meters)
    if not math.isfinite(width) or width <= 0:
        _fail(
            "facility_design_route_width_invalid",
            "A material route requires a positive corridor width.",
        )
    allowed = box(*_facility_bounds(layout)).buffer(
        -width / 2.0,
        cap_style=2,
        join_style=2,
    )
    obstacles = [
        *_placement_shapes(layout, source_bundle, set(excluded_placement_ids)),
        *_protected_shapes(layout),
        *_external_shapes(source_bundle),
    ]
    if obstacles:
        blocked = unary_union(obstacles).buffer(
            width / 2.0,
            cap_style=2,
            join_style=2,
        )
        allowed = allowed.difference(blocked)
    allowed = set_precision(
        allowed,
        grid_size=NAVIGATION_GEOMETRY_GRID_METERS,
        mode="valid_output",
    )
    if allowed.is_empty or not allowed.is_valid:
        _fail(
            "route_blocked",
            "Static Facility geometry leaves no valid material-route corridor.",
        )
    return allowed


def shortest_design_route_centerline(
    layout: Mapping[str, Any],
    *,
    start: tuple[float, float],
    goal: tuple[float, float],
    corridor_width_meters: float,
    source_bundle: Mapping[str, Any] | None,
    excluded_placement_ids: Sequence[str] = (),
) -> list[dict[str, float]]:
    free_space = design_route_free_space(
        layout,
        corridor_width_meters=corridor_width_meters,
        source_bundle=source_bundle,
        excluded_placement_ids=excluded_placement_ids,
    )
    if not free_space.covers(Point(start)) or not free_space.covers(Point(goal)):
        _fail(
            "route_blocked",
            "A route endpoint lies outside the candidate's obstacle-free corridor space.",
            start=_point3(start),
            goal=_point3(goal),
        )
    direct = LineString([start, goal])
    if direct.length > _EPSILON and free_space.covers(direct):
        return [_point3(start), _point3(goal)]
    try:
        graph = build_visibility_graph(free_space, start, goal)
        result = solve_visibility_graph(graph, start, goal)
    except Exception as exc:
        code = str(getattr(exc, "code", "route_blocked"))
        _fail(
            "route_blocked",
            "No deterministic obstacle-free material route connects the selected endpoints.",
            sourceCode=code,
        )
    return [_point3((float(item["x"]), float(item["z"]))) for item in result["centerline"]]


def _route_direction(route: Mapping[str, Any]) -> str:
    aisle = (
        (route.get("extensions") or {}).get("facilityAisle")
        if isinstance(route.get("extensions"), Mapping)
        else None
    )
    value = str(aisle.get("direction") or "two_way") if isinstance(aisle, Mapping) else "two_way"
    return value if value in {"one_way", "two_way"} else "two_way"


def validate_design_transfer_route_path(
    layout: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    source_bundle: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Prove ordered endpoint connectivity, direction, and corridor clearance."""

    canonical = canonicalize_layout(layout)
    routes = {
        str(item.get("routeId")): item
        for item in canonical.get("routes", [])
        if isinstance(item, Mapping) and item.get("routeId")
    }
    route_ids = [str(item) for item in snapshot["routePath"]["routeIds"]]
    missing = [item for item in route_ids if item not in routes]
    if missing:
        _fail(
            "facility_design_route_unavailable",
            "The accepted transfer route is absent from the candidate layout.",
            routeIds=missing,
        )
    transfer = snapshot["materialTransfer"]
    global_source = {
        "kind": "placement_connector",
        "placementId": transfer["sourcePlacementId"],
        "connectorId": transfer["sourceConnectorId"],
    }
    global_target = {
        "kind": "placement_connector",
        "placementId": transfer["targetPlacementId"],
        "connectorId": transfer["targetConnectorId"],
    }
    current = resolve_design_route_endpoint(
        canonical,
        global_source,
        route_kind="material",
        direction="source",
        source_bundle=source_bundle,
    )
    expected_target = resolve_design_route_endpoint(
        canonical,
        global_target,
        route_kind="material",
        direction="target",
        source_bundle=source_bundle,
    )
    excluded_ids = {
        str(transfer["sourcePlacementId"]),
        str(transfer["targetPlacementId"]),
    }
    validations = []
    total_distance = 0.0
    for route_id in route_ids:
        route = routes[route_id]
        route_kind = str(route.get("routeKind") or "")
        source = resolve_design_route_endpoint(
            canonical,
            route.get("sourceEndpoint") or {},
            route_kind=route_kind,
            direction="source",
            source_bundle=source_bundle,
        )
        target = resolve_design_route_endpoint(
            canonical,
            route.get("targetEndpoint") or {},
            route_kind=route_kind,
            direction="target",
            source_bundle=source_bundle,
        )
        centerline = route.get("centerline")
        if not isinstance(centerline, list) or len(centerline) < 2:
            _fail(
                "facility_design_route_geometry_invalid",
                "An accepted material route has no measurable centerline.",
                routeId=route_id,
            )
        points = [_point2(item, f"route[{route_id}].centerline") for item in centerline]
        tolerance = FACILITY_DESIGN_ROUTE_ENDPOINT_TOLERANCE_METERS
        if _distance(points[0], source) > tolerance or _distance(points[-1], target) > tolerance:
            _fail(
                "facility_design_route_endpoint_geometry_mismatch",
                "A candidate route centerline is disconnected from its persisted endpoints.",
                routeId=route_id,
            )
        forward = _distance(current, source) <= tolerance
        reverse = _distance(current, target) <= tolerance
        if forward:
            next_point = target
            traversal = "forward"
        elif reverse and _route_direction(route) == "two_way":
            next_point = source
            traversal = "reverse"
        else:
            code = "facility_design_route_direction_invalid" if reverse else "facility_design_route_path_disconnected"
            _fail(
                code,
                "The ordered material route does not connect the transfer endpoints in an allowed direction.",
                routeId=route_id,
                priorPosition=_point3(current),
            )
        try:
            width = float(route.get("corridorWidth"))
        except (TypeError, ValueError) as exc:
            raise FacilityDesignRoutingError(
                "facility_design_route_width_invalid",
                "An accepted material route has no positive corridor width.",
            ) from exc
        free_space = design_route_free_space(
            canonical,
            corridor_width_meters=width,
            source_bundle=source_bundle,
            excluded_placement_ids=sorted(excluded_ids),
        )
        line = LineString(points)
        if line.length <= _EPSILON or not free_space.covers(line):
            _fail(
                "route_blocked",
                "The candidate material-route corridor intersects current static geometry.",
                routeId=route_id,
            )
        distance = float(line.length)
        total_distance += distance
        validations.append(
            {
                "routeId": route_id,
                "status": "accepted",
                "traversal": traversal,
                "distanceMeters": distance,
            }
        )
        current = next_point
    if _distance(current, expected_target) > FACILITY_DESIGN_ROUTE_ENDPOINT_TOLERANCE_METERS:
        _fail(
            "facility_design_route_path_disconnected",
            "The ordered material route does not reach the transfer destination.",
            finalPosition=_point3(current),
            expectedPosition=_point3(expected_target),
        )
    return {
        "schemaVersion": "facility-design-route-validation-v1",
        "status": "accepted",
        "routeIds": route_ids,
        "routeValidations": validations,
        "distanceMeters": total_distance,
        "validatorVersion": FACILITY_DESIGN_ROUTE_VALIDATOR_VERSION,
        "qualification": (
            "Endpoint continuity, route direction, and static obstacle-free corridor geometry only; "
            "no safety, capacity, timing, or compliance claim."
        ),
    }


__all__ = [
    "FACILITY_DESIGN_ROUTE_ENDPOINT_TOLERANCE_METERS",
    "FACILITY_DESIGN_ROUTE_VALIDATOR_VERSION",
    "FacilityDesignRoutingError",
    "normalize_design_asset_definitions",
    "design_route_free_space",
    "resolve_design_route_endpoint",
    "shortest_design_route_centerline",
    "validate_design_transfer_route_path",
]
