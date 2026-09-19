"""Revision-bound Facility navigation snapshot compilation.

The compiler derives traversability and graph topology from trusted facility
geometry. It never writes computed paths back into the saved layout.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from copy import deepcopy
import hashlib
import json
import math
import threading
from typing import Any, Iterable, Mapping, Sequence

from .canonical import layout_revision
from .errors import FacilityValidationError
from .motion_lanes import derive_directional_lane
from .navigation_contract import (
    FACILITY_NAVIGATION_LIMITS,
    navigation_stable_id,
    seal_navigation_snapshot,
    validate_facility_navigation_extension,
    navigation_identity_index,
)
from .navigation_geometry import (
    FacilityNavigationGeometryError,
    build_triangulated_mesh,
    canonicalize_polygon_geometry,
    deterministic_geometry_contract,
    free_space_geometry,
    geometry_from_canonical_polygons,
    union_and_expand_obstacles,
)
from .spatial import (
    placement_clearance_records,
    placement_spatial_records,
    shell_obstacle_records,
)

try:
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import nearest_points, unary_union
    from shapely.strtree import STRtree
except ImportError:  # pragma: no cover - deterministic refusal is tested.
    LineString = Point = Polygon = STRtree = nearest_points = unary_union = None


FACILITY_NAVIGATION_COMPILER_VERSION = "facility-navigation-compiler-v1"
FACILITY_NAVIGATION_PACKAGE_SCHEMA = "facility-navigation-package-v1"
FACILITY_NAVIGATION_PACKAGE_MAXIMUM_CANONICAL_BYTES = 16 * 1024 * 1024
FACILITY_NAVIGATION_MAXIMUM_INTERSECTION_COMPARISONS = 5_000_000
FACILITY_NAVIGATION_SNAPSHOT_CACHE_MAXIMUM = 64
FACILITY_NAVIGATION_COMPILER_QUALIFICATION = (
    "Derived traversability and graph topology for an exact facility, actor "
    "profile, compiler, and policy context. It is not a safety, capacity, "
    "staffing, traffic, or regulatory approval."
)


class FacilityNavigationCompilerError(FacilityValidationError):
    """The exact navigation snapshot could not be compiled."""


def _fail(code: str, message: str, **details: Any) -> None:
    raise FacilityNavigationCompilerError(code, message, details=details)


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
        _fail(
            "facility_navigation_compiler_invalid_json",
            "Navigation compiler inputs must be finite JSON data.",
        )
        raise AssertionError from error


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _point(value: Mapping[str, Any]) -> dict[str, float]:
    try:
        x = float(value["x"])
        z = float(value["z"])
    except (KeyError, TypeError, ValueError) as error:
        _fail(
            "facility_navigation_geometry_invalid",
            "Navigation geometry contains an invalid point.",
        )
        raise AssertionError from error
    if not math.isfinite(x) or not math.isfinite(z):
        _fail(
            "facility_navigation_geometry_invalid",
            "Navigation geometry contains a non-finite point.",
        )
    return {"x": round(x, 6), "z": round(z, 6)}


def _point_tuple(value: Mapping[str, Any]) -> tuple[float, float]:
    normalized = _point(value)
    return normalized["x"], normalized["z"]


def _asset_index(
    values: Mapping[tuple[str, str], Mapping[str, Any]]
    | Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    if isinstance(values, Mapping):
        return {
            (str(key[0]), str(key[1])): value
            for key, value in values.items()
            if isinstance(key, tuple)
            and len(key) == 2
            and isinstance(value, Mapping)
        }
    result = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        definition = raw.get("definition", raw)
        if not isinstance(definition, Mapping):
            continue
        asset_id = str(raw.get("assetId") or definition.get("assetId") or "")
        revision = str(
            raw.get("assetDefinitionRevision")
            or definition.get("assetDefinitionRevision")
            or ""
        )
        if asset_id and revision:
            result[(asset_id, revision)] = definition
    return result


def _floor_polygons(shell: Mapping[str, Any]) -> list[dict[str, Any]]:
    for feature in sorted(
        (
            item
            for item in shell.get("features", [])
            if isinstance(item, Mapping)
            and item.get("featureKind") in {"floor", "floor_surface"}
        ),
        key=lambda item: str(item.get("featureId") or ""),
    ):
        geometry = feature.get("geometry")
        boundary = geometry.get("boundary") if isinstance(geometry, Mapping) else None
        if isinstance(boundary, list) and len(boundary) >= 3:
            return canonicalize_polygon_geometry(
                geometry_from_canonical_polygons(
                    [{"exterior": [_point(item) for item in boundary], "holes": []}]
                )
            )
    _fail(
        "facility_navigation_floor_unavailable",
        "The exact facility floor boundary is unavailable.",
    )
    raise AssertionError


def _is_barrier(asset_id: str, definition: Mapping[str, Any]) -> bool:
    tokens = " ".join(
        str(value or "").casefold()
        for value in (
            asset_id,
            definition.get("displayName"),
            definition.get("category"),
            " ".join(str(item) for item in definition.get("tags", [])),
        )
    )
    return any(
        marker in tokens
        for marker in (
            "guard panel",
            "wire mesh guard",
            "machine guarding",
            "safety fence",
            "barrier panel",
        )
    )


def _definition_actor_class(
    asset_id: str,
    definition: Mapping[str, Any],
) -> str | None:
    identity = asset_id.casefold()
    category = str(definition.get("category") or "").casefold()
    if identity == "asset-operator" or category in {
        "people",
        "personnel",
        "operators",
    }:
        return "pedestrian"
    if (
        "forklift" in identity
        or "fork-lift" in identity
        or category == "vehicle"
        or any(
            token in identity
            for token in (
                "pallet-truck",
                "platform-truck",
                "mobile-cart",
                "tugger",
            )
        )
    ):
        return "vehicle"
    return None


def _is_protected_zone(zone: Mapping[str, Any]) -> bool:
    zone_type = str(zone.get("zoneType") or "").casefold().replace("-", "_")
    label = " ".join(str(zone.get("label") or "").casefold().split())
    return zone_type in {"exclusion", "restricted", "safety", "keep_clear"} or any(
        phrase in label
        for phrase in (
            "restricted area",
            "restricted zone",
            "keep clear",
            "no entry",
            "safety exclusion",
        )
    )


def _geometry_fingerprint(exterior: Sequence[Mapping[str, Any]]) -> str:
    geometry = geometry_from_canonical_polygons(
        [{"exterior": [_point(item) for item in exterior], "holes": []}]
    )
    return _fingerprint(canonicalize_polygon_geometry(geometry))


def _source_ref(kind: str, identity: str, revision: str) -> dict[str, str]:
    return {
        "sourceKind": kind,
        "sourceId": identity,
        "sourceRevision": revision,
    }


def _collect_obstacles(
    layout: Mapping[str, Any],
    shell: Mapping[str, Any],
    assets: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    actor_class: str,
    layout_source_revision: str,
    shell_revision: str,
    evidence_authority: Mapping[str, Any] | None,
    influence_geometry: Any | None = None,
    forbidden_zone_ids: frozenset[str] = frozenset(),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    navigation = (
        layout.get("extensions", {}).get("facilityNavigation", {})
        if isinstance(layout.get("extensions"), Mapping)
        else {}
    )
    actor_ids = {
        str(item.get("actorPlacementId"))
        for item in navigation.get("movementPrograms", [])
        if isinstance(item, Mapping) and item.get("actorClass") == actor_class
    }
    for placement in layout.get("placements", []):
        if not isinstance(placement, Mapping):
            continue
        key = (
            str(placement.get("assetId") or ""),
            str(placement.get("assetDefinitionRevision") or ""),
        )
        definition = assets.get(key)
        if isinstance(definition, Mapping) and _definition_actor_class(
            key[0], definition
        ) == actor_class:
            actor_ids.add(str(placement.get("placementId") or ""))
    service_anchors: dict[str, str] = {}
    for anchor in navigation.get("anchors", []):
        if not isinstance(anchor, Mapping):
            continue
        owner = anchor.get("ownerRef")
        if (
            isinstance(owner, Mapping)
            and owner.get("ownerKind") == "placement"
            and anchor.get("anchorKind")
            not in {"actor_home", "aisle_access", "cell_entrance"}
        ):
            service_anchors.setdefault(
                str(owner.get("ownerId") or ""),
                str(anchor.get("navigationAnchorId") or ""),
            )
    raw_obstacles: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    def add(
        *,
        obstacle_id: str,
        exterior: Sequence[Mapping[str, Any]],
        role: str,
        owner_ref: Mapping[str, str],
        evidence_status: str,
        service_anchor_id: str | None = None,
    ) -> None:
        boundary = [_point(item) for item in exterior]
        if influence_geometry is not None:
            candidate = Polygon([_point_tuple(item) for item in boundary])
            if candidate.is_empty or not candidate.is_valid:
                _fail(
                    "facility_navigation_geometry_invalid",
                    "An obstacle footprint is invalid.",
                    obstacleId=obstacle_id,
                )
            if not influence_geometry.intersects(candidate):
                return
        raw_obstacles.append({
            "obstacleId": obstacle_id,
            "exterior": boundary,
            "holes": [],
        })
        record = {
            "obstacleRecordId": obstacle_id,
            "ownerRef": dict(owner_ref),
            "role": role,
            "geometryFingerprint": _geometry_fingerprint(boundary),
            "evidenceStatus": evidence_status,
        }
        if service_anchor_id and role != "barrier":
            record["serviceAnchorId"] = service_anchor_id
        records.append(record)

    for placement in sorted(
        (
            item
            for item in layout.get("placements", [])
            if isinstance(item, Mapping)
            and str(item.get("placementId") or "") not in actor_ids
        ),
        key=lambda item: str(item.get("placementId") or ""),
    ):
        placement_id = str(placement.get("placementId") or "")
        asset_id = str(placement.get("assetId") or "")
        revision = str(placement.get("assetDefinitionRevision") or "")
        definition = assets.get((asset_id, revision))
        if definition is None:
            _fail(
                "facility_navigation_asset_geometry_unavailable",
                "A placed asset has no exact revision-bound geometry.",
                placementId=placement_id,
                assetId=asset_id,
                assetDefinitionRevision=revision,
            )
        role = "barrier" if _is_barrier(asset_id, definition) else (
            "service_target" if placement_id in service_anchors else "ordinary_obstacle"
        )
        for spatial in placement_spatial_records(placement, definition):
            add(
                obstacle_id=spatial.record_id,
                exterior=[{"x": x, "z": z} for x, z in spatial.polygon],
                role=role,
                owner_ref=_source_ref(
                    "placement", placement_id, layout_source_revision
                ),
                evidence_status="derived",
                service_anchor_id=service_anchors.get(placement_id),
            )
        for clearance in placement_clearance_records(
            placement,
            definition,
            evidence_authority=evidence_authority,
        ):
            if not clearance.authoritative:
                continue
            add(
                obstacle_id=clearance.record_id,
                exterior=[{"x": x, "z": z} for x, z in clearance.polygon],
                role="protected_region",
                owner_ref=_source_ref(
                    "placement_clearance", clearance.record_id, revision
                ),
                evidence_status=clearance.evidence_status,
            )
    for zone in sorted(
        (
            item
            for item in layout.get("zones", [])
            if isinstance(item, Mapping)
            and (
                _is_protected_zone(item)
                or str(item.get("zoneId") or "") in forbidden_zone_ids
            )
        ),
        key=lambda item: str(item.get("zoneId") or ""),
    ):
        zone_id = str(zone.get("zoneId") or "")
        add(
            obstacle_id=f"protected:{zone_id}",
            exterior=zone.get("boundary", []),
            role="protected_region",
            owner_ref=_source_ref("zone", zone_id, layout_source_revision),
            evidence_status="authored",
        )
    for spatial in shell_obstacle_records(shell):
        add(
            obstacle_id=spatial.record_id,
            exterior=[{"x": x, "z": z} for x, z in spatial.polygon],
            role="shell",
            owner_ref=_source_ref(
                "shell_feature", spatial.owner_id, shell_revision
            ),
            evidence_status="authored",
        )
    raw_obstacles.sort(key=lambda item: item["obstacleId"])
    records.sort(key=lambda item: item["obstacleRecordId"])
    return raw_obstacles, records


def _empty_obstacle_compilation(radius: float) -> dict[str, Any]:
    result = {
        "schemaVersion": deterministic_geometry_contract()["schemaVersion"],
        "contract": deterministic_geometry_contract(),
        "navigationRadiusMeters": round(radius, 6),
        "effectiveBufferRadiusMeters": round(radius, 6),
        "sourceObstacleCount": 0,
        "sourceVertexCount": 0,
        "sourceUnionPolygonCount": 0,
        "sourceUnionVertexCount": 0,
        "expandedPolygonCount": 0,
        "expandedVertexCount": 0,
        "expandedPolygons": [],
        "sourceObstacleIds": [],
    }
    result["geometryFingerprint"] = _fingerprint(result)
    return result


def _navigation_scope_polygons(
    layout: Mapping[str, Any],
    floor_polygons: Sequence[Mapping[str, Any]],
    anchors: Sequence[Mapping[str, Any]],
    required_scope_points: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    scope_points = [
        _point(item["position"])
        for item in anchors
    ]
    scope_points.extend(
        _point(item) for item in (required_scope_points or ())
    )
    if not scope_points:
        return []
    points = [Point(_point_tuple(item)) for item in scope_points]
    candidates = []
    for zone in layout.get("zones", []):
        if not isinstance(zone, Mapping) or _is_protected_zone(zone):
            continue
        boundary = zone.get("boundary")
        if not isinstance(boundary, list) or len(boundary) < 3:
            continue
        geometry = geometry_from_canonical_polygons(
            [{"exterior": [_point(item) for item in boundary], "holes": []}]
        )
        if all(geometry.covers(point) for point in points):
            candidates.append((float(geometry.area), str(zone.get("zoneId") or ""), geometry))
    if candidates:
        _, _, selected = min(candidates, key=lambda item: (item[0], item[1]))
        return canonicalize_polygon_geometry(selected)
    return list(deepcopy(floor_polygons))


def _resolve_anchor_position(
    anchor: Mapping[str, Any],
    layout: Mapping[str, Any],
) -> dict[str, float] | None:
    local = anchor.get("localPosition")
    if isinstance(local, Mapping):
        return _point(local)
    derived = anchor.get("derivedPositionRef")
    if not isinstance(derived, Mapping):
        return None
    kind = str(derived.get("sourceKind") or "")
    source_id = str(derived.get("sourceId") or "")
    if kind in {"placement_transform", "placement_access"}:
        placement = next(
            (
                item
                for item in layout.get("placements", [])
                if isinstance(item, Mapping)
                and item.get("placementId") == source_id
            ),
            None,
        )
        transform = placement.get("transform") if isinstance(placement, Mapping) else None
        position = transform.get("position") if isinstance(transform, Mapping) else None
        return _point(position) if isinstance(position, Mapping) else None
    if kind == "route_endpoint":
        route_id, _, endpoint = source_id.rpartition(":")
        route = next(
            (
                item
                for item in layout.get("routes", [])
                if isinstance(item, Mapping) and item.get("routeId") == route_id
            ),
            None,
        )
        centerline = route.get("centerline") if isinstance(route, Mapping) else None
        if isinstance(centerline, list) and len(centerline) >= 2:
            return _point(centerline[0 if endpoint == "source" else -1])
    if kind == "marking_center":
        marking = next(
            (
                item
                for item in layout.get("floorMarkings", [])
                if isinstance(item, Mapping) and item.get("markingId") == source_id
            ),
            None,
        )
        transform = marking.get("transform") if isinstance(marking, Mapping) else None
        position = transform.get("position") if isinstance(transform, Mapping) else None
        return _point(position) if isinstance(position, Mapping) else None
    if kind == "zone_anchor":
        zone_id, _, anchor_id = source_id.partition(":")
        zone = next(
            (
                item
                for item in layout.get("zones", [])
                if isinstance(item, Mapping) and item.get("zoneId") == zone_id
            ),
            None,
        )
        for item in zone.get("anchors", []) if isinstance(zone, Mapping) else []:
            if isinstance(item, Mapping) and item.get("anchorId") == anchor_id:
                position = item.get("position") or item.get("localPosition")
                return _point(position) if isinstance(position, Mapping) else None
    return None


def _route_kind_matches(route: Mapping[str, Any], actor_class: str) -> bool:
    route_kind = str(route.get("routeKind") or "").casefold()
    extension = route.get("extensions")
    aisle = extension.get("facilityAisle") if isinstance(extension, Mapping) else None
    aisle_kind = str(aisle.get("aisleKind") or "").casefold() if isinstance(aisle, Mapping) else ""
    if actor_class == "pedestrian":
        return route_kind in {"operator", "pedestrian"} or aisle_kind == "pedestrian"
    return route_kind in {"forklift", "material", "vehicle"} or aisle_kind in {
        "forklift",
        "material",
        "vehicle",
    }


def _route_direction(route: Mapping[str, Any]) -> str:
    extension = route.get("extensions")
    aisle = extension.get("facilityAisle") if isinstance(extension, Mapping) else None
    return str(aisle.get("direction") or "two_way") if isinstance(aisle, Mapping) else "two_way"


def _build_tracks(
    layout: Mapping[str, Any],
    actor_class: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tracks = []
    findings = []
    for route in sorted(
        (
            item
            for item in layout.get("routes", [])
            if isinstance(item, Mapping) and _route_kind_matches(item, actor_class)
        ),
        key=lambda item: str(item.get("routeId") or ""),
    ):
        route_id = str(route.get("routeId") or "")
        try:
            width = float(route.get("corridorWidth") or 0)
        except (TypeError, ValueError):
            width = 0
        if width <= 0:
            findings.append({
                "code": "facility_navigation_route_geometry_unavailable",
                "severity": "error",
                "sourceRefIds": [route_id],
            })
            continue
        if actor_class == "vehicle":
            directions = ["forward"]
            if _route_direction(route) == "two_way":
                directions.append("reverse")
            for travel in directions:
                try:
                    lane = derive_directional_lane(
                        layout,
                        route,
                        travel_direction=travel,
                    )
                except FacilityValidationError as error:
                    findings.append({
                        "code": error.code,
                        "severity": "error",
                        "sourceRefIds": [route_id],
                        "travelDirection": travel,
                    })
                    continue
                tracks.append({
                    "trackId": f"{route_id}:{travel}",
                    "routeId": route_id,
                    "direction": "forward",
                    "corridorWidth": width,
                    "points": [_point(item) for item in lane["laneCenterline"]],
                    "sourceRefIds": [route_id, *lane.get("sourceMarkingIds", [])],
                    "evidenceStatus": lane.get("evidenceStatus", "unknown"),
                    "laneBinding": lane,
                })
        else:
            centerline = route.get("centerline")
            if not isinstance(centerline, list) or len(centerline) < 2:
                findings.append({
                    "code": "facility_navigation_route_geometry_unavailable",
                    "severity": "error",
                    "sourceRefIds": [route_id],
                })
                continue
            tracks.append({
                "trackId": route_id,
                "routeId": route_id,
                "direction": (
                    "forward" if _route_direction(route) == "one_way" else "bidirectional"
                ),
                "corridorWidth": width,
                "points": [_point(item) for item in centerline],
                "sourceRefIds": [route_id],
                "evidenceStatus": "authored",
            })
    return tracks, findings


def _intersection_points(geometry: Any) -> list[tuple[float, float]]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [(float(geometry.x), float(geometry.y))]
    if geometry.geom_type == "LineString":
        coordinates = list(geometry.coords)
        return [tuple(coordinates[0]), tuple(coordinates[-1])]
    result = []
    for child in getattr(geometry, "geoms", []):
        result.extend(_intersection_points(child))
    return result


def _segment_projection(
    point: tuple[float, float],
    left: tuple[float, float],
    right: tuple[float, float],
) -> tuple[float, tuple[float, float], float]:
    dx = right[0] - left[0]
    dz = right[1] - left[1]
    length_sq = dx * dx + dz * dz
    if length_sq <= 1.0e-18:
        return 0.0, left, math.dist(point, left)
    ratio = max(
        0.0,
        min(1.0, ((point[0] - left[0]) * dx + (point[1] - left[1]) * dz) / length_sq),
    )
    projected = (left[0] + dx * ratio, left[1] + dz * ratio)
    return ratio, projected, math.dist(point, projected)


def _split_tracks(
    tracks: Sequence[Mapping[str, Any]],
    attachments: Sequence[Mapping[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, list[str]],
    dict[str, list[str]],
]:
    segments = []
    for track in tracks:
        points = [_point_tuple(item) for item in track["points"]]
        for index, (left, right) in enumerate(zip(points, points[1:])):
            if math.dist(left, right) <= 1.0e-9:
                continue
            segments.append({
                "track": track,
                "segmentIndex": index,
                "left": left,
                "right": right,
                "line": LineString([left, right]),
                "breaks": {left, right},
            })
    comparisons = len(segments) * max(0, len(segments) - 1) // 2
    if comparisons > FACILITY_NAVIGATION_MAXIMUM_INTERSECTION_COMPARISONS:
        _fail(
            "facility_navigation_intersection_budget_exceeded",
            "The projected route-intersection work exceeds the frozen budget.",
            projectedComparisons=comparisons,
            maximumComparisons=FACILITY_NAVIGATION_MAXIMUM_INTERSECTION_COMPARISONS,
        )
    for left_index, left in enumerate(segments):
        for right in segments[left_index + 1 :]:
            if not left["line"].bounds or not right["line"].bounds:
                continue
            intersection = left["line"].intersection(right["line"])
            for point in _intersection_points(intersection):
                normalized = (round(point[0], 6), round(point[1], 6))
                left["breaks"].add(normalized)
                right["breaks"].add(normalized)
    attachment_bindings: dict[str, list[str]] = {}
    for attachment in attachments:
        point = _point_tuple(attachment["position"])
        best_by_track: dict[str, tuple[Any, ...]] = {}
        for segment_index, segment in enumerate(segments):
            ratio, projected, distance = _segment_projection(
                point, segment["left"], segment["right"]
            )
            maximum = float(segment["track"]["corridorWidth"]) / 2.0 + 1.0e-9
            candidate = (distance, str(segment["track"]["trackId"]), segment_index)
            track_id = str(segment["track"]["trackId"])
            previous = best_by_track.get(track_id)
            if distance <= maximum and (previous is None or candidate < previous[0]):
                best_by_track[track_id] = (candidate, segment, ratio, projected)
        targets = []
        for _, segment, _, projected in (
            best_by_track[key] for key in sorted(best_by_track)
        ):
            normalized = (round(projected[0], 6), round(projected[1], 6))
            segment["breaks"].add(normalized)
            targets.append(navigation_stable_id(
                "nne", {"kind": "network", "point": normalized}
            ))
        if targets:
            attachment_bindings[str(attachment["attachmentId"])] = sorted(set(targets))
    node_sources: dict[str, set[str]] = defaultdict(set)
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges = []
    for segment in segments:
        left = segment["left"]
        right = segment["right"]
        ordered = sorted(
            segment["breaks"],
            key=lambda point: (
                _segment_projection(point, left, right)[0],
                point,
            ),
        )
        for first, second in zip(ordered, ordered[1:]):
            distance = math.dist(first, second)
            if distance <= 1.0e-9:
                continue
            source_id = navigation_stable_id(
                "nne", {"kind": "network", "point": first}
            )
            target_id = navigation_stable_id(
                "nne", {"kind": "network", "point": second}
            )
            for node_id, point in ((source_id, first), (target_id, second)):
                nodes_by_id.setdefault(node_id, {
                    "nodeId": node_id,
                    "nodeKind": "lane" if "laneBinding" in segment["track"] else "connector",
                    "position": {"x": point[0], "z": point[1]},
                })
                node_sources[node_id].update(segment["track"]["sourceRefIds"])
            edge_id = navigation_stable_id("nne", {
                "kind": "network-edge",
                "trackId": segment["track"]["trackId"],
                "source": source_id,
                "target": target_id,
            })
            edges.append({
                "edgeId": edge_id,
                "sourceNodeId": source_id,
                "targetNodeId": target_id,
                "direction": segment["track"]["direction"],
                "costMeters": round(distance, 6),
                "evidenceStatus": segment["track"]["evidenceStatus"],
                "derivationKind": "network_segment",
                "sourceRefIds": sorted(set(segment["track"]["sourceRefIds"])),
            })
    return (
        sorted(nodes_by_id.values(), key=lambda item: item["nodeId"]),
        sorted(edges, key=lambda item: item["edgeId"]),
        attachment_bindings,
        {key: sorted(value) for key, value in sorted(node_sources.items())},
    )


def _actor_anchors(
    layout: Mapping[str, Any],
    actor_class: str,
    required_anchor_ids: Iterable[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    extension = (
        layout.get("extensions", {}).get("facilityNavigation", {})
        if isinstance(layout.get("extensions"), Mapping)
        else {}
    )
    anchors = []
    findings = []
    required_ids = (
        [str(item) for item in required_anchor_ids]
        if required_anchor_ids is not None
        else None
    )
    selected = set(required_ids) if required_ids is not None else None
    available_anchor_records = [
        anchor
        for anchor in extension.get("anchors", [])
        if isinstance(anchor, Mapping)
        and actor_class in anchor.get("actorClasses", [])
    ]
    available_anchors = {
        str(anchor.get("navigationAnchorId") or ""): anchor
        for anchor in available_anchor_records
    }
    ordered_ids = (
        required_ids
        if required_ids is not None
        else [
            str(anchor.get("navigationAnchorId") or "")
            for anchor in available_anchor_records
        ]
    )
    for anchor_id in ordered_ids:
        anchor = available_anchors.get(anchor_id)
        if anchor is None:
            continue
        position = _resolve_anchor_position(anchor, layout)
        if position is None:
            findings.append({
                "code": "facility_navigation_anchor_position_unavailable",
                "severity": "error",
                "sourceRefIds": [anchor_id],
            })
            continue
        record = {
            "attachmentId": anchor_id,
            "navigationAnchorId": anchor_id,
            "anchorKind": anchor.get("anchorKind"),
            "position": position,
            "ownerRef": deepcopy(anchor.get("ownerRef")),
        }
        derived = anchor.get("derivedPositionRef")
        if (
            isinstance(derived, Mapping)
            and derived.get("sourceKind") == "placement_access"
        ):
            record["_placementAccess"] = {
                "placementId": str(derived.get("sourceId") or ""),
                "sourceRevision": str(derived.get("sourceRevision") or ""),
                "approachDirections": list(anchor.get("approachDirections") or []),
            }
        anchors.append(record)
    if selected is not None:
        available = {item["navigationAnchorId"] for item in anchors}
        for anchor_id in sorted(selected - available):
            findings.append({
                "code": "facility_navigation_anchor_unavailable",
                "severity": "error",
                "sourceRefIds": [anchor_id],
            })
    return anchors, findings


def _placement_access_candidates(
    placement: Mapping[str, Any],
    definition: Mapping[str, Any],
    free_space: Any,
    effective_radius: float,
    approach_directions: Sequence[str],
) -> list[dict[str, float]]:
    polygons = [
        Polygon(record.polygon)
        for record in placement_spatial_records(placement, definition)
        if len(record.polygon) >= 3
    ]
    if not polygons:
        return []
    geometry = unary_union(polygons)
    if geometry.is_empty or not geometry.is_valid:
        return []
    minimum_x, minimum_z, maximum_x, maximum_z = geometry.bounds
    center = geometry.centroid
    permitted = set(approach_directions or ["any"])
    directional = [
        ("west", minimum_x - effective_radius, center.y),
        (
            "northwest",
            minimum_x - effective_radius,
            maximum_z + effective_radius,
        ),
        ("north", center.x, maximum_z + effective_radius),
        (
            "northeast",
            maximum_x + effective_radius,
            maximum_z + effective_radius,
        ),
        ("east", maximum_x + effective_radius, center.y),
        (
            "southeast",
            maximum_x + effective_radius,
            minimum_z - effective_radius,
        ),
        ("south", center.x, minimum_z - effective_radius),
        (
            "southwest",
            minimum_x - effective_radius,
            minimum_z - effective_radius,
        ),
    ]
    candidates = []
    for direction, x, z in directional:
        if "any" in permitted and direction not in {
            "west", "north", "east", "south"
        }:
            continue
        if "any" not in permitted and direction not in permitted:
            continue
        point = Point(float(x), float(z))
        if free_space.covers(point):
            candidates.append({
                "x": round(float(x), 6),
                "z": round(float(z), 6),
            })
    if candidates:
        return candidates

    # A named service side is an intent constraint. Falling back to an
    # arbitrary nearest point would silently violate instructions such as
    # "walk around the table's right side".
    if "any" not in permitted:
        return []

    # Joined or irregular obstacles can block every standard approach.
    # The nearest free-space point is a deterministic geometric fallback, not
    # an authored service side or an engineering clearance.
    if nearest_points is None:
        return []
    try:
        _, free_point = nearest_points(geometry, free_space)
    except (TypeError, ValueError):
        return []
    if free_point.is_empty or not free_space.covers(free_point):
        return []
    return [{
        "x": round(float(free_point.x), 6),
        "z": round(float(free_point.y), 6),
    }]


def _resolve_placement_access_anchors(
    anchors: Sequence[Mapping[str, Any]],
    layout: Mapping[str, Any],
    assets: Mapping[tuple[str, str], Mapping[str, Any]],
    free_space: Any,
    effective_radius: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    placements = {
        str(item.get("placementId") or ""): item
        for item in layout.get("placements", [])
        if isinstance(item, Mapping) and item.get("placementId")
    }
    resolved = []
    findings = []
    previous_position: dict[str, float] | None = None
    for raw in anchors:
        anchor = deepcopy(dict(raw))
        access = anchor.pop("_placementAccess", None)
        if not isinstance(access, Mapping):
            resolved.append(anchor)
            previous_position = _point(anchor["position"])
            continue
        placement_id = str(access.get("placementId") or "")
        placement = placements.get(placement_id)
        asset_key = (
            str(placement.get("assetId") or "") if placement else "",
            str(placement.get("assetDefinitionRevision") or "") if placement else "",
        )
        definition = assets.get(asset_key)
        if (
            placement is None
            or definition is None
            or str(access.get("sourceRevision") or "") != asset_key[1]
        ):
            findings.append({
                "code": "facility_navigation_placement_access_unavailable",
                "severity": "error",
                "sourceRefIds": [anchor["navigationAnchorId"], placement_id],
            })
            continue
        candidates = _placement_access_candidates(
            placement,
            definition,
            free_space,
            float(effective_radius),
            access.get("approachDirections", []),
        )
        if not candidates:
            findings.append({
                "code": "facility_navigation_placement_access_unreachable",
                "severity": "error",
                "sourceRefIds": [anchor["navigationAnchorId"], placement_id],
            })
            continue
        reference = previous_position or _point(anchor["position"])
        selected = min(
            candidates,
            key=lambda item: (
                round(math.dist(_point_tuple(reference), _point_tuple(item)), 9),
                float(item["x"]),
                float(item["z"]),
            ),
        )
        anchor["position"] = selected
        anchor["positionDerivation"] = "nearest_feasible_placement_access"
        resolved.append(anchor)
        previous_position = selected
    return resolved, findings


def _marking_attachments(
    layout: Mapping[str, Any],
    actor_class: str,
) -> list[dict[str, Any]]:
    allowed = {"crosswalk"} if actor_class == "pedestrian" else {
        "parking_box",
        "crosswalk",
    }
    result = []
    for marking in sorted(
        (
            item
            for item in layout.get("floorMarkings", [])
            if isinstance(item, Mapping) and item.get("markingType") in allowed
        ),
        key=lambda item: str(item.get("markingId") or ""),
    ):
        transform = marking.get("transform")
        position = transform.get("position") if isinstance(transform, Mapping) else None
        marking_id = str(marking.get("markingId") or "")
        if marking_id and isinstance(position, Mapping):
            result.append({
                "attachmentId": marking_id,
                "position": _point(position),
                "markingType": marking.get("markingType"),
            })
    return result


def _add_attachment_nodes(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    attachments: Sequence[Mapping[str, Any]],
    bindings: Mapping[str, Sequence[str]],
    node_sources: dict[str, list[str]],
) -> None:
    known_nodes = {item["nodeId"] for item in nodes}
    for attachment in attachments:
        attachment_id = str(attachment["attachmentId"])
        node_id = navigation_stable_id(
            "nne", {"kind": "attachment", "id": attachment_id}
        )
        node_kind = "anchor" if "navigationAnchorId" in attachment else "connector"
        node = {
            "nodeId": node_id,
            "nodeKind": node_kind,
            "position": _point(attachment["position"]),
            "ownerRefId": attachment_id,
        }
        if node_id not in known_nodes:
            nodes.append(node)
            known_nodes.add(node_id)
        node_sources[node_id] = [attachment_id]
        for target in bindings.get(attachment_id, []):
            if target not in known_nodes:
                continue
            distance = math.dist(
                _point_tuple(node["position"]),
                _point_tuple(next(item["position"] for item in nodes if item["nodeId"] == target)),
            )
            edges.append({
                "edgeId": navigation_stable_id(
                    "nne", {"kind": "attachment-edge", "source": node_id, "target": target}
                ),
                "sourceNodeId": node_id,
                "targetNodeId": target,
                "direction": "bidirectional",
                "costMeters": round(distance, 6),
                "evidenceStatus": "derived",
                "derivationKind": "attachment_connector",
                "sourceRefIds": [attachment_id],
            })


def _add_navmesh(
    free_space: Any,
    nodes: list[dict[str, Any]],
    node_sources: dict[str, list[str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compile bounded mesh metadata without serializing the mesh as graph JSON."""

    mesh = build_triangulated_mesh(free_space)
    if (
        len(mesh.triangles) > FACILITY_NAVIGATION_LIMITS["snapshotNodes"]
        or len(mesh.adjacency) > FACILITY_NAVIGATION_LIMITS["snapshotEdges"]
    ):
        _fail(
            "facility_navigation_graph_budget_exceeded",
            "The projected navigation mesh exceeds its frozen allocation limits.",
            projectedNodes=len(mesh.triangles),
            projectedEdges=len(mesh.adjacency),
        )
    connector_findings = []
    for node in nodes:
        point = Point(_point_tuple(node["position"]))
        if not free_space.covers(point):
            connector_findings.append({
                "code": "facility_navigation_node_outside_free_space",
                "severity": "error",
                "sourceRefIds": node_sources.get(node["nodeId"], [node["nodeId"]]),
            })
    return {
        "algorithm": "triangulated_navmesh_astar_funnel",
        "triangleCount": len(mesh.triangles),
        "adjacencyEdgeCount": len(mesh.adjacency),
        "serializedAsGraph": False,
        "reconstructionSource": "freeSpacePolygons",
    }, connector_findings


def _pedestrian_components(
    nodes: Sequence[Mapping[str, Any]],
    free_space: Any,
) -> list[dict[str, Any]]:
    polygons = list(getattr(free_space, "geoms", [free_space]))
    assigned: set[str] = set()
    components = []
    for polygon_index, polygon in enumerate(polygons):
        members = sorted(
            str(node["nodeId"])
            for node in nodes
            if polygon.covers(Point(_point_tuple(node["position"])))
        )
        if not members:
            continue
        assigned.update(members)
        components.append({
            "componentId": navigation_stable_id(
                "nne",
                {
                    "kind": "free-space-component",
                    "polygonIndex": polygon_index,
                    "nodes": members,
                },
            ),
            "nodeIds": members,
        })
    for node_id in sorted(
        str(node["nodeId"]) for node in nodes if str(node["nodeId"]) not in assigned
    ):
        components.append({
            "componentId": navigation_stable_id(
                "nne", {"kind": "isolated-component", "node": node_id}
            ),
            "nodeIds": [node_id],
        })
    return sorted(components, key=lambda item: item["componentId"])


def _components(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    node_ids = sorted(str(item["nodeId"]) for item in nodes)
    undirected: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    directed: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    reverse: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        source = str(edge["sourceNodeId"])
        target = str(edge["targetNodeId"])
        undirected[source].add(target)
        undirected[target].add(source)
        direction = edge["direction"]
        if direction in {"forward", "bidirectional"}:
            directed[source].add(target)
            reverse[target].add(source)
        if direction in {"reverse", "bidirectional"}:
            directed[target].add(source)
            reverse[source].add(target)
    components = []
    unseen = set(node_ids)
    while unseen:
        start = min(unseen)
        members = []
        pending = [start]
        unseen.remove(start)
        while pending:
            current = pending.pop()
            members.append(current)
            for neighbor in sorted(undirected[current], reverse=True):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    pending.append(neighbor)
        members.sort()
        components.append({
            "componentId": navigation_stable_id("nne", {"kind": "component", "nodes": members}),
            "nodeIds": members,
        })

    def finishing_order() -> list[str]:
        visited = set()
        order = []
        for start in node_ids:
            if start in visited:
                continue
            stack = [(start, False)]
            while stack:
                current, expanded = stack.pop()
                if expanded:
                    order.append(current)
                    continue
                if current in visited:
                    continue
                visited.add(current)
                stack.append((current, True))
                for neighbor in sorted(directed[current], reverse=True):
                    if neighbor not in visited:
                        stack.append((neighbor, False))
        return order

    assigned = set()
    strong_components = []
    for start in reversed(finishing_order()):
        if start in assigned:
            continue
        members = []
        pending = [start]
        assigned.add(start)
        while pending:
            current = pending.pop()
            members.append(current)
            for neighbor in sorted(reverse[current], reverse=True):
                if neighbor not in assigned:
                    assigned.add(neighbor)
                    pending.append(neighbor)
        strong_components.append(sorted(members))
    strong_components.sort(key=lambda item: item[0])
    direction_facts = {
        "strongComponentCount": len(strong_components),
        "strongComponents": [
            {
                "strongComponentId": navigation_stable_id(
                    "nne", {"kind": "strong-component", "nodes": members}
                ),
                "nodeIds": members,
            }
            for members in strong_components
        ],
        "oneWayEdgeCount": sum(
            1 for item in edges if item["direction"] != "bidirectional"
        ),
    }
    return sorted(components, key=lambda item: item["componentId"]), direction_facts


def _walkable_records(
    free_space_records: Sequence[Mapping[str, Any]],
    source_ref_ids: Sequence[str],
) -> list[dict[str, Any]]:
    result = []
    for polygon in free_space_records:
        fingerprint = _fingerprint(polygon)
        result.append({
            "walkableRegionId": navigation_stable_id(
                "nne", {"kind": "walkable-region", "geometry": polygon}
            ),
            "geometryFingerprint": fingerprint,
            "sourceRefIds": sorted(set(source_ref_ids)),
        })
    return sorted(result, key=lambda item: item["walkableRegionId"])


def compile_navigation_snapshot(
    layout: Mapping[str, Any],
    *,
    shell: Mapping[str, Any],
    asset_definitions: Mapping[tuple[str, str], Mapping[str, Any]]
    | Sequence[Mapping[str, Any]],
    actor_class: str,
    actor_profile_revision: str,
    navigation_radius_meters: float,
    shell_revision: str,
    policy_revision: str,
    evidence_authority: Mapping[str, Any] | None = None,
    required_anchor_ids: Iterable[str] | None = None,
    required_scope_points: Sequence[Mapping[str, Any]] | None = None,
    forbidden_zone_ids: Iterable[str] | None = None,
    compiler_version: str = FACILITY_NAVIGATION_COMPILER_VERSION,
) -> dict[str, Any]:
    """Compile one immutable, revision-bound navigation package."""

    if LineString is None or Point is None or STRtree is None:
        _fail(
            "facility_navigation_geometry_engine_unavailable",
            "Navigation compilation requires the deterministic geometry engine.",
        )
    if actor_class not in {"pedestrian", "vehicle"}:
        _fail(
            "facility_navigation_actor_class_invalid",
            "Navigation actor class must be pedestrian or vehicle.",
        )
    try:
        radius = float(navigation_radius_meters)
    except (TypeError, ValueError) as error:
        _fail(
            "facility_navigation_envelope_invalid",
            "The exact actor navigation radius is unavailable.",
        )
        raise AssertionError from error
    if not math.isfinite(radius) or radius < 0:
        _fail(
            "facility_navigation_envelope_invalid",
            "The exact actor navigation radius is invalid.",
        )
    identities = navigation_identity_index(layout)
    extension = (
        layout.get("extensions", {}).get("facilityNavigation")
        if isinstance(layout.get("extensions"), Mapping)
        else None
    )
    if extension is not None:
        validate_facility_navigation_extension(extension, identities)
    source_layout_revision = layout_revision(layout)
    assets = _asset_index(asset_definitions)
    forbidden_zones = frozenset(str(item) for item in (forbidden_zone_ids or ()))
    unknown_forbidden = forbidden_zones - identities.zone_ids
    if unknown_forbidden:
        _fail(
            "facility_navigation_forbidden_zone_unavailable",
            "A required forbidden zone does not exist in the source layout.",
            forbiddenZoneIds=sorted(unknown_forbidden),
        )
    floor_polygons = _floor_polygons(shell)
    anchors, findings = _actor_anchors(
        layout,
        actor_class,
        required_anchor_ids,
    )
    allowed_polygons = _navigation_scope_polygons(
        layout,
        floor_polygons,
        anchors,
        required_scope_points,
    )
    allowed_geometry = (
        geometry_from_canonical_polygons(allowed_polygons)
        if allowed_polygons
        else None
    )
    influence_geometry = (
        allowed_geometry.buffer(radius)
        if allowed_geometry is not None and radius > 0
        else allowed_geometry
    )
    if allowed_geometry is None:
        raw_obstacles, obstacle_records = [], []
    else:
        raw_obstacles, obstacle_records = _collect_obstacles(
            layout,
            shell,
            assets,
            actor_class=actor_class,
            layout_source_revision=source_layout_revision,
            shell_revision=shell_revision,
            evidence_authority=evidence_authority,
            influence_geometry=influence_geometry,
            forbidden_zone_ids=forbidden_zones,
        )
    obstacle_compilation = (
        union_and_expand_obstacles(
            raw_obstacles,
            navigation_radius_meters=radius,
        )
        if raw_obstacles
        else _empty_obstacle_compilation(radius)
    )
    free_space = (
        (
            free_space_geometry(
                allowed_polygons,
                obstacle_compilation["expandedPolygons"],
            )
            if obstacle_compilation["expandedPolygons"]
            else allowed_geometry
        )
        if allowed_geometry is not None
        else None
    )
    free_space_records = (
        canonicalize_polygon_geometry(free_space)
        if free_space is not None
        else []
    )
    if free_space is not None:
        anchors, access_findings = _resolve_placement_access_anchors(
            anchors,
            layout,
            assets,
            free_space,
            float(obstacle_compilation["effectiveBufferRadiusMeters"]),
        )
        findings.extend(access_findings)
    else:
        anchors = [
            {
                key: deepcopy(value)
                for key, value in anchor.items()
                if key != "_placementAccess"
            }
            for anchor in anchors
        ]
    markings = _marking_attachments(layout, actor_class)
    attachments = [*anchors, *markings]
    tracks, track_findings = _build_tracks(layout, actor_class)
    findings.extend(track_findings)
    nodes, edges, bindings, node_sources = _split_tracks(tracks, attachments)
    _add_attachment_nodes(nodes, edges, attachments, bindings, node_sources)
    navmesh_package = None
    if actor_class == "pedestrian" and free_space is not None:
        navmesh_package, navmesh_findings = _add_navmesh(
            free_space,
            nodes,
            node_sources,
        )
        findings.extend(navmesh_findings)
    edge_components, direction_facts = _components(nodes, edges)
    components = (
        _pedestrian_components(nodes, free_space)
        if actor_class == "pedestrian" and free_space is not None
        else edge_components
    )
    degrees = defaultdict(int)
    for edge in edges:
        degrees[edge["sourceNodeId"]] += 1
        degrees[edge["targetNodeId"]] += 1
    for anchor in anchors:
        node_id = navigation_stable_id(
            "nne", {"kind": "attachment", "id": anchor["navigationAnchorId"]}
        )
        position = next(
            (
                item["position"]
                for item in nodes
                if item["nodeId"] == node_id
            ),
            None,
        )
        reachable = (
            isinstance(position, Mapping)
            and free_space is not None
            and free_space.covers(Point(_point_tuple(position)))
            if actor_class == "pedestrian"
            else degrees[node_id] > 0
        )
        if not reachable:
            findings.append({
                "code": "facility_navigation_anchor_unreachable",
                "severity": "error",
                "sourceRefIds": [anchor["navigationAnchorId"]],
            })
    findings.sort(
        key=lambda item: (
            item.get("severity", ""),
            item.get("code", ""),
            item.get("sourceRefIds", []),
        )
    )
    geometry_projection = {
        "shellRevision": shell_revision,
        "policyRevision": policy_revision,
        "actorClass": actor_class,
        "actorProfileRevision": actor_profile_revision,
        "navigationRadiusMeters": round(radius, 6),
        "compilerVersion": compiler_version,
        "allowedPolygons": allowed_polygons,
        "obstacleGeometryFingerprint": obstacle_compilation["geometryFingerprint"],
        "freeSpacePolygons": free_space_records,
        "tracks": tracks,
        "anchors": anchors,
        "forbiddenZoneIds": sorted(forbidden_zones),
    }
    geometry_context_fingerprint = _fingerprint(geometry_projection)
    source_revisions = {
        "layout": source_layout_revision,
        "shell": shell_revision,
        "policy": policy_revision,
        "actor_profile": actor_profile_revision,
    }
    source_ref_ids = [
        str(item.get("featureId") or "")
        for item in shell.get("features", [])
        if isinstance(item, Mapping) and item.get("featureKind") in {"floor", "floor_surface"}
    ]
    snapshot = seal_navigation_snapshot({
        "layoutRevision": source_layout_revision,
        "compilerVersion": compiler_version,
        "actorClass": actor_class,
        "actorProfileRevision": actor_profile_revision,
        "walkableRegions": _walkable_records(free_space_records, source_ref_ids),
        "obstacleRecords": obstacle_records,
        "nodes": sorted(nodes, key=lambda item: item["nodeId"]),
        "edges": sorted(edges, key=lambda item: item["edgeId"]),
        "connectedComponents": components,
        "sourceRevisions": source_revisions,
        "geometryContextFingerprint": geometry_context_fingerprint,
    })
    package = {
        "schemaVersion": FACILITY_NAVIGATION_PACKAGE_SCHEMA,
        "snapshot": snapshot,
        "allowedPolygons": allowed_polygons,
        "expandedObstaclePolygons": obstacle_compilation["expandedPolygons"],
        "sourceObstaclePolygons": raw_obstacles,
        "freeSpacePolygons": free_space_records,
        "navmesh": navmesh_package,
        "tracks": tracks,
        "anchorRecords": anchors,
        "nodeSources": node_sources,
        "directionFacts": direction_facts,
        "findings": findings,
        "metrics": {
            "sourceObstacleCount": obstacle_compilation["sourceObstacleCount"],
            "sourceVertexCount": obstacle_compilation["sourceVertexCount"],
            "sourceUnionVertexCount": obstacle_compilation["sourceUnionVertexCount"],
            "postUnionExpandedVertexCount": obstacle_compilation["expandedVertexCount"],
            "walkableRegionCount": len(snapshot["walkableRegions"]),
            "nodeCount": len(snapshot["nodes"]),
            "edgeCount": len(snapshot["edges"]),
            "componentCount": len(snapshot["connectedComponents"]),
            "danglingAnchorCount": sum(
                1 for item in findings if item["code"] == "facility_navigation_anchor_unreachable"
            ),
        },
        "qualification": FACILITY_NAVIGATION_COMPILER_QUALIFICATION,
    }
    package["packageFingerprint"] = _fingerprint(package)
    package["navigationPackageId"] = f"nsp-{package['packageFingerprint'][:24]}"
    # canonicalBytes describes the complete wire package, including the field
    # itself. Iterate to the fixed point because adding the decimal count can
    # change the serialized length at a digit boundary.
    size = 0
    for _ in range(4):
        package["canonicalBytes"] = size
        measured = len(_canonical_bytes(package))
        if measured == size:
            break
        size = measured
    package["canonicalBytes"] = len(_canonical_bytes(package))
    size = package["canonicalBytes"]
    if size > FACILITY_NAVIGATION_PACKAGE_MAXIMUM_CANONICAL_BYTES:
        _fail(
            "facility_navigation_package_budget_exceeded",
            "The full navigation package exceeds its canonical byte ceiling.",
            canonicalBytes=size,
            maximumCanonicalBytes=FACILITY_NAVIGATION_PACKAGE_MAXIMUM_CANONICAL_BYTES,
        )
    return json.loads(_canonical_bytes(package).decode("ascii"))


def navigation_snapshot_summary(package: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = package["snapshot"]
    findings = package.get("findings", [])
    summary = {
        "schemaVersion": "facility-navigation-snapshot-summary-v1",
        "navigationPackageId": package["navigationPackageId"],
        "navigationSnapshotId": snapshot["navigationSnapshotId"],
        "snapshotFingerprint": snapshot["snapshotFingerprint"],
        "geometryContextFingerprint": snapshot["geometryContextFingerprint"],
        "actorClass": snapshot["actorClass"],
        "actorProfileRevision": snapshot["actorProfileRevision"],
        "metrics": deepcopy(package["metrics"]),
        "findingCounts": dict(sorted(
            (code, sum(1 for item in findings if item.get("code") == code))
            for code in sorted({str(item.get("code")) for item in findings})
        )),
        "qualification": FACILITY_NAVIGATION_COMPILER_QUALIFICATION,
    }
    size = len(_canonical_bytes(summary))
    if size > FACILITY_NAVIGATION_LIMITS["sageSummaryBytes"]:
        _fail(
            "facility_navigation_summary_budget_exceeded",
            "The compact navigation summary exceeds the Sage response budget.",
            canonicalBytes=size,
        )
    summary["canonicalBytes"] = size
    return summary


class FacilityNavigationSnapshotStore:
    """Bounded process-local cache for immutable derived packages."""

    def __init__(self, maximum_items: int = FACILITY_NAVIGATION_SNAPSHOT_CACHE_MAXIMUM) -> None:
        self.maximum_items = int(maximum_items)
        if self.maximum_items < 1:
            raise ValueError("maximum_items must be positive")
        self._lock = threading.RLock()
        self._by_package_id: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._by_context: dict[tuple[str, str, str, str, str], str] = {}

    @staticmethod
    def cache_key(package: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
        snapshot = package["snapshot"]
        revisions = snapshot["sourceRevisions"]
        return (
            snapshot["geometryContextFingerprint"],
            snapshot["actorClass"],
            snapshot["actorProfileRevision"],
            snapshot["compilerVersion"],
            revisions["policy"],
        )

    def put(self, package: Mapping[str, Any]) -> dict[str, Any]:
        value = deepcopy(dict(package))
        package_id = str(value["navigationPackageId"])
        key = self.cache_key(value)
        with self._lock:
            previous = self._by_context.get(key)
            if previous and previous != package_id:
                self._by_package_id.pop(previous, None)
            self._by_package_id[package_id] = value
            self._by_package_id.move_to_end(package_id)
            self._by_context[key] = package_id
            while len(self._by_package_id) > self.maximum_items:
                removed_id, removed = self._by_package_id.popitem(last=False)
                self._by_context.pop(self.cache_key(removed), None)
        return deepcopy(value)

    def get(self, package_id: str) -> dict[str, Any]:
        with self._lock:
            value = self._by_package_id.get(str(package_id))
            if value is None:
                _fail(
                    "facility_navigation_package_unavailable",
                    "The requested navigation package is unavailable.",
                    navigationPackageId=package_id,
                )
            self._by_package_id.move_to_end(str(package_id))
            return deepcopy(value)

    def get_by_context(
        self,
        key: tuple[str, str, str, str, str],
    ) -> dict[str, Any] | None:
        with self._lock:
            package_id = self._by_context.get(key)
            if package_id is None:
                return None
            value = self._by_package_id.get(package_id)
            if value is None:
                return None
            self._by_package_id.move_to_end(package_id)
            return deepcopy(value)


__all__ = [
    "FACILITY_NAVIGATION_COMPILER_QUALIFICATION",
    "FACILITY_NAVIGATION_COMPILER_VERSION",
    "FACILITY_NAVIGATION_MAXIMUM_INTERSECTION_COMPARISONS",
    "FACILITY_NAVIGATION_PACKAGE_MAXIMUM_CANONICAL_BYTES",
    "FACILITY_NAVIGATION_PACKAGE_SCHEMA",
    "FacilityNavigationCompilerError",
    "FacilityNavigationSnapshotStore",
    "compile_navigation_snapshot",
    "navigation_snapshot_summary",
]
