"""Deterministic prototype lean-motion intent for Facility Layout activity."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence


FACILITY_LEAN_MOTION_SCHEMA_VERSION = "facility-lean-motion-v3"
FACILITY_LEAN_MOTION_QUALIFICATION = (
    "Derived prototype motion borrows existing placed operator identities, assigns them "
    "to nearby placed stations, and routes the responsible endpoint operators to derived "
    "FIFO handoff points. Material handoff lines show workpiece transfer relationships, "
    "not operator walking. The routes are geometrically feasible paths, not time-optimal "
    "standard work, and do not establish staffing, task frequency, synchronized transfer "
    "timing, capacity, traffic safety, or compliance."
)

_CELL = re.compile(r"^assembly\s+cell\b", re.IGNORECASE)
_LINE = re.compile(r"^assembly\s+line\b", re.IGNORECASE)
_KITTING = re.compile(r"^(?:kitting|knitting)\s+island\b", re.IGNORECASE)


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


def _point_in_polygon(
    point: tuple[float, float],
    boundary: Sequence[Mapping[str, Any]],
) -> bool:
    x, z = point
    inside = False
    points = [(float(item["x"]), float(item["z"])) for item in boundary]
    previous = points[-1]
    for current in points:
        x1, z1 = previous
        x2, z2 = current
        cross = (x2 - x1) * (z - z1) - (z2 - z1) * (x - x1)
        if (
            abs(cross) <= 1.0e-8
            and min(x1, x2) - 1.0e-9 <= x <= max(x1, x2) + 1.0e-9
            and min(z1, z2) - 1.0e-9 <= z <= max(z1, z2) + 1.0e-9
        ):
            return True
        if (z1 > z) != (z2 > z):
            intersection = x1 + (z - z1) * (x2 - x1) / (z2 - z1)
            if intersection >= x:
                inside = not inside
        previous = current
    return inside


def _zone_kind(label: str) -> str | None:
    if _CELL.search(label):
        return "assembly_cell"
    if _LINE.search(label):
        return "assembly_line"
    if _KITTING.search(label):
        return "kitting_island"
    return None


def _bounds(boundary: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    xs = [float(item["x"]) for item in boundary]
    zs = [float(item["z"]) for item in boundary]
    return {
        "minimumX": min(xs),
        "maximumX": max(xs),
        "minimumZ": min(zs),
        "maximumZ": max(zs),
        "centerX": (min(xs) + max(xs)) / 2.0,
        "centerZ": (min(zs) + max(zs)) / 2.0,
    }


def _containing_zone_boundary(
    layout: Mapping[str, Any],
    zone_id: str,
    boundary: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]] | None:
    candidates = []
    child_bounds = _bounds(boundary)
    child_area = (
        (child_bounds["maximumX"] - child_bounds["minimumX"])
        * (child_bounds["maximumZ"] - child_bounds["minimumZ"])
    )
    child_points = [
        (float(point["x"]), float(point["z"]))
        for point in boundary
    ]
    for candidate in layout.get("zones", []):
        if not isinstance(candidate, Mapping) or candidate.get("zoneId") == zone_id:
            continue
        candidate_boundary = candidate.get("boundary")
        if not isinstance(candidate_boundary, list) or len(candidate_boundary) < 3:
            continue
        if not all(
            _point_in_polygon(point, candidate_boundary)
            for point in child_points
        ):
            continue
        candidate_bounds = _bounds(candidate_boundary)
        area = (
            (candidate_bounds["maximumX"] - candidate_bounds["minimumX"])
            * (candidate_bounds["maximumZ"] - candidate_bounds["minimumZ"])
        )
        if area > child_area + 1.0e-6:
            candidates.append((area, str(candidate.get("zoneId") or ""), candidate_boundary))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return deepcopy(candidates[0][2])


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _point(x: float, z: float) -> dict[str, float]:
    return {"x": _rounded(x), "z": _rounded(z)}


def _loop_waypoints(
    bounds: Mapping[str, float],
    *,
    segment_start: float | None = None,
    segment_end: float | None = None,
) -> list[dict[str, float]]:
    width = float(bounds["maximumX"]) - float(bounds["minimumX"])
    depth = float(bounds["maximumZ"]) - float(bounds["minimumZ"])
    margin = max(0.35, min(0.7, width * 0.14, depth * 0.14))
    x0 = float(bounds["minimumX"]) + margin
    x1 = float(bounds["maximumX"]) - margin
    z0 = (
        float(segment_start) + margin
        if segment_start is not None
        else float(bounds["minimumZ"]) + margin
    )
    z1 = (
        float(segment_end) - margin
        if segment_end is not None
        else float(bounds["maximumZ"]) - margin
    )
    if x1 - x0 < 0.8 or z1 - z0 < 0.8:
        raise ValueError("lean-motion zone has insufficient loop depth")
    return [
        _point(x1, z0),
        _point(x1, z1),
        _point(x0, z1),
        _point(x0, z0),
    ]


def _placement_point(placement: Mapping[str, Any]) -> dict[str, float]:
    position = placement["transform"]["position"]
    return _point(float(position["x"]), float(position["z"]))


def _service_station_candidate(placement: Mapping[str, Any]) -> bool:
    asset_id = str(placement.get("assetId") or "").casefold()
    if not asset_id or asset_id == "asset-operator":
        return False
    return any(
        token in asset_id
        for token in (
            "workbench",
            "workstation",
            "machine",
            "table",
            "cart",
            "pallet",
            "tooling",
            "fixture",
        )
    )


def _rectangle_boundary(
    minimum_x: float,
    minimum_z: float,
    maximum_x: float,
    maximum_z: float,
) -> list[dict[str, float]]:
    return [
        _point(minimum_x, minimum_z),
        _point(maximum_x, minimum_z),
        _point(maximum_x, maximum_z),
        _point(minimum_x, maximum_z),
    ]


def _major_axis(bounds: Mapping[str, float]) -> str:
    width = float(bounds["maximumX"]) - float(bounds["minimumX"])
    depth = float(bounds["maximumZ"]) - float(bounds["minimumZ"])
    return "z" if depth >= width else "x"


def _axis_value(point: Mapping[str, float], axis: str) -> float:
    return float(point[axis])


def _operator_segment_limits(
    operator_points: Sequence[Mapping[str, float]],
    bounds: Mapping[str, float],
    axis: str,
) -> list[tuple[float, float]]:
    minimum = float(bounds["minimumZ" if axis == "z" else "minimumX"])
    maximum = float(bounds["maximumZ" if axis == "z" else "maximumX"])
    values = [_axis_value(point, axis) for point in operator_points]
    separators = [
        (values[index] + values[index + 1]) / 2.0
        for index in range(len(values) - 1)
    ]
    edges = [minimum, *separators, maximum]
    return [
        (_rounded(edges[index]), _rounded(edges[index + 1]))
        for index in range(len(values))
    ]


def _service_side(
    operator_points: Sequence[Mapping[str, float]],
    bounds: Mapping[str, float],
    axis: str,
) -> int:
    cross_axis = "x" if axis == "z" else "z"
    center = float(bounds["centerX" if cross_axis == "x" else "centerZ"])
    average = sum(_axis_value(point, cross_axis) for point in operator_points) / len(
        operator_points
    )
    return 1 if average >= center else -1


def _operator_path_anchor(
    placement_point: Mapping[str, float],
    bounds: Mapping[str, float],
    *,
    axis: str,
    service_side: int,
    segment_count: int,
) -> dict[str, float]:
    if segment_count == 1:
        return deepcopy(dict(placement_point))
    width = float(bounds["maximumX"]) - float(bounds["minimumX"])
    depth = float(bounds["maximumZ"]) - float(bounds["minimumZ"])
    margin = max(0.35, min(0.7, width * 0.14, depth * 0.14))
    if axis == "z":
        x = (
            float(bounds["maximumX"]) - margin
            if service_side > 0
            else float(bounds["minimumX"]) + margin
        )
        return _point(x, float(placement_point["z"]))
    z = (
        float(bounds["maximumZ"]) - margin
        if service_side > 0
        else float(bounds["minimumZ"]) + margin
    )
    return _point(float(placement_point["x"]), z)


def _segmented_loop_waypoints(
    bounds: Mapping[str, float],
    *,
    axis: str,
    segment_start: float,
    segment_end: float,
    segment_index: int,
    segment_count: int,
    anchor: Mapping[str, float],
    service_side: int,
) -> list[dict[str, float]]:
    width = float(bounds["maximumX"]) - float(bounds["minimumX"])
    depth = float(bounds["maximumZ"]) - float(bounds["minimumZ"])
    margin = max(0.35, min(0.7, width * 0.14, depth * 0.14))
    if axis == "z":
        if segment_count > 1 and service_side > 0:
            x1 = float(bounds["maximumX"]) - margin
            x0 = float(bounds["maximumX"]) + 0.8
        elif segment_count > 1:
            x0 = float(bounds["minimumX"]) + margin
            x1 = float(bounds["minimumX"]) - 0.8
        else:
            x0 = float(bounds["minimumX"]) + margin
            x1 = float(bounds["maximumX"]) - margin
        z0 = segment_start if segment_index else segment_start + margin
        z1 = (
            segment_end
            if segment_index < segment_count - 1
            else segment_end - margin
        )
        corners = (
            [_point(x1, z0), _point(x0, z0), _point(x0, z1), _point(x1, z1)]
            if service_side > 0
            else [_point(x0, z0), _point(x1, z0), _point(x1, z1), _point(x0, z1)]
        )
        ingress = _point(float(anchor["x"]), z0)
        egress = _point(float(anchor["x"]), z1)
    else:
        if segment_count > 1 and service_side > 0:
            z1 = float(bounds["maximumZ"]) - margin
            z0 = float(bounds["maximumZ"]) + 0.8
        elif segment_count > 1:
            z0 = float(bounds["minimumZ"]) + margin
            z1 = float(bounds["minimumZ"]) - 0.8
        else:
            z0 = float(bounds["minimumZ"]) + margin
            z1 = float(bounds["maximumZ"]) - margin
        x0 = segment_start if segment_index else segment_start + margin
        x1 = (
            segment_end
            if segment_index < segment_count - 1
            else segment_end - margin
        )
        corners = (
            [_point(x0, z1), _point(x0, z0), _point(x1, z0), _point(x1, z1)]
            if service_side > 0
            else [_point(x0, z0), _point(x0, z1), _point(x1, z1), _point(x1, z0)]
        )
        ingress = _point(x0, float(anchor["z"]))
        egress = _point(x1, float(anchor["z"]))
    if (
        max(point["x"] for point in corners) - min(point["x"] for point in corners)
        < 0.8
        or max(point["z"] for point in corners)
        - min(point["z"] for point in corners)
        < 0.8
    ):
        raise ValueError("lean-motion station segment has insufficient loop depth")
    result = [deepcopy(dict(anchor))]
    for point in [ingress, *corners, egress]:
        if point != result[-1]:
            result.append(point)
    return result


def _assistance_gate_position(
    bounds: Mapping[str, float],
    *,
    axis: str,
    separator: float,
    service_side: int,
) -> dict[str, float]:
    width = float(bounds["maximumX"]) - float(bounds["minimumX"])
    depth = float(bounds["maximumZ"]) - float(bounds["minimumZ"])
    margin = max(0.35, min(0.7, width * 0.14, depth * 0.14))
    if axis == "z":
        x = (
            float(bounds["maximumX"]) - margin
            if service_side > 0
            else float(bounds["minimumX"]) + margin
        )
        return _point(x, separator)
    z = (
        float(bounds["maximumZ"]) - margin
        if service_side > 0
        else float(bounds["minimumZ"]) + margin
    )
    return _point(separator, z)


def _local_traversable_boundary(
    layout: Mapping[str, Any],
    zone: Mapping[str, Any],
    *,
    axis: str,
    segment_start: float,
    segment_end: float,
) -> list[dict[str, float]]:
    parent = _containing_zone_boundary(
        layout,
        str(zone["zoneId"]),
        zone["boundary"],
    )
    if parent is None:
        return deepcopy(zone["boundary"])
    zone_bounds = zone["bounds"]
    parent_bounds = _bounds(parent)
    expansion = 1.2
    if axis == "z":
        candidate = _rectangle_boundary(
            max(parent_bounds["minimumX"], zone_bounds["minimumX"] - expansion),
            max(parent_bounds["minimumZ"], segment_start - expansion),
            min(parent_bounds["maximumX"], zone_bounds["maximumX"] + expansion),
            min(parent_bounds["maximumZ"], segment_end + expansion),
        )
    else:
        candidate = _rectangle_boundary(
            max(parent_bounds["minimumX"], segment_start - expansion),
            max(parent_bounds["minimumZ"], zone_bounds["minimumZ"] - expansion),
            min(parent_bounds["maximumX"], segment_end + expansion),
            min(parent_bounds["maximumZ"], zone_bounds["maximumZ"] + expansion),
        )
    if all(
        _point_in_polygon((float(point["x"]), float(point["z"])), parent)
        for point in candidate
    ):
        return candidate
    return deepcopy(zone["boundary"])


def _shared_containing_boundary(
    layout: Mapping[str, Any],
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> list[dict[str, Any]] | None:
    candidates = []
    points = [
        (float(point["x"]), float(point["z"]))
        for boundary in (first["boundary"], second["boundary"])
        for point in boundary
    ]
    for candidate in layout.get("zones", []):
        if not isinstance(candidate, Mapping):
            continue
        boundary = candidate.get("boundary")
        if not isinstance(boundary, list) or len(boundary) < 3:
            continue
        if not all(_point_in_polygon(point, boundary) for point in points):
            continue
        candidate_bounds = _bounds(boundary)
        area = (
            (candidate_bounds["maximumX"] - candidate_bounds["minimumX"])
            * (candidate_bounds["maximumZ"] - candidate_bounds["minimumZ"])
        )
        candidates.append((area, str(candidate.get("zoneId") or ""), boundary))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return deepcopy(candidates[0][2])


def _zone_interface(
    source: Mapping[str, float],
    target: Mapping[str, float],
) -> dict[str, float]:
    dx = float(target["centerX"]) - float(source["centerX"])
    dz = float(target["centerZ"]) - float(source["centerZ"])
    if abs(dz) >= abs(dx):
        return _point(
            float(source["centerX"]),
            float(source["maximumZ"] if dz >= 0 else source["minimumZ"]),
        )
    return _point(
        float(source["maximumX"] if dx >= 0 else source["minimumX"]),
        float(source["centerZ"]),
    )


def _orthogonal_handoff(
    start: Mapping[str, float],
    end: Mapping[str, float],
) -> list[dict[str, float]]:
    x0, z0 = float(start["x"]), float(start["z"])
    x1, z1 = float(end["x"]), float(end["z"])
    middle_z = (z0 + z1) / 2.0
    points = [
        _point(x0, z0),
        _point(x0, middle_z),
        _point(x1, middle_z),
        _point(x1, z1),
    ]
    result = []
    for point in points:
        if not result or point != result[-1]:
            result.append(point)
    return result


def derive_facility_lean_motion_blueprint(
    layout: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive segmented operator ownership and qualified flow topology."""

    zones = []
    for zone in layout.get("zones", []):
        if not isinstance(zone, Mapping):
            continue
        label = str(zone.get("label") or "").strip()
        kind = _zone_kind(label)
        boundary = zone.get("boundary")
        if kind is None or not isinstance(boundary, list) or len(boundary) < 3:
            continue
        zone_id = str(zone.get("zoneId") or "")
        if not zone_id:
            continue
        zones.append({
            "zoneId": zone_id,
            "label": label,
            "kind": kind,
            "boundary": deepcopy(boundary),
            "bounds": _bounds(boundary),
        })
    zones.sort(key=lambda item: (item["kind"], item["label"], item["zoneId"]))
    if not zones:
        return {
            "operatorPlans": [],
            "pedestrianLinkPlans": [],
            "assistanceGatePlans": [],
            "materialHandoffs": [],
            "fifoPoints": [],
        }

    operators = [
        placement
        for placement in layout.get("placements", [])
        if isinstance(placement, Mapping)
        and str(placement.get("assetId") or "").casefold() == "asset-operator"
        and isinstance(placement.get("transform"), Mapping)
        and isinstance(placement["transform"].get("position"), Mapping)
    ]
    station_candidates = [
        placement
        for placement in layout.get("placements", [])
        if isinstance(placement, Mapping)
        and _service_station_candidate(placement)
        and isinstance(placement.get("transform"), Mapping)
        and isinstance(placement["transform"].get("position"), Mapping)
    ]
    operator_plans: list[dict[str, Any]] = []
    assistance_gate_plans: list[dict[str, Any]] = []
    plans_by_zone: dict[str, list[dict[str, Any]]] = {}
    for zone in zones:
        boundary = zone["boundary"]
        axis = _major_axis(zone["bounds"])
        contained = []
        for placement in operators:
            position = placement["transform"]["position"]
            point = (float(position["x"]), float(position["z"]))
            if _point_in_polygon(point, boundary):
                contained.append(placement)
        cross_axis = "x" if axis == "z" else "z"
        contained.sort(key=lambda item: (
            _axis_value(_placement_point(item), axis),
            _axis_value(_placement_point(item), cross_axis),
            str(item.get("placementId") or ""),
        ))
        if not contained:
            continue
        operator_points = [_placement_point(item) for item in contained]
        segment_limits = _operator_segment_limits(
            operator_points,
            zone["bounds"],
            axis,
        )
        side = _service_side(operator_points, zone["bounds"], axis)
        zone_stations = []
        for station in station_candidates:
            point = _placement_point(station)
            if _point_in_polygon((point["x"], point["z"]), boundary):
                zone_stations.append(station)
        assignments: dict[str, list[str]] = {
            str(item.get("placementId") or ""): []
            for item in contained
        }
        for station in zone_stations:
            station_point = _placement_point(station)
            owner_index = min(
                range(len(contained)),
                key=lambda index: (
                    abs(
                        _axis_value(station_point, axis)
                        - _axis_value(operator_points[index], axis)
                    ),
                    math.hypot(
                        station_point["x"] - operator_points[index]["x"],
                        station_point["z"] - operator_points[index]["z"],
                    ),
                    str(contained[index].get("placementId") or ""),
                ),
            )
            assignments[str(contained[owner_index].get("placementId") or "")].append(
                str(station.get("placementId") or "")
            )
        zone_plans = []
        for index, placement in enumerate(contained):
            segment_start, segment_end = segment_limits[index]
            placement_position = operator_points[index]
            anchor = _operator_path_anchor(
                placement_position,
                zone["bounds"],
                axis=axis,
                service_side=side,
                segment_count=len(contained),
            )
            try:
                waypoints = _segmented_loop_waypoints(
                    zone["bounds"],
                    axis=axis,
                    segment_start=segment_start,
                    segment_end=segment_end,
                    segment_index=index,
                    segment_count=len(contained),
                    anchor=anchor,
                    service_side=side,
                )
            except ValueError:
                continue
            placement_id = str(placement.get("placementId") or "")
            seed = {
                "placementId": placement_id,
                "zoneId": zone["zoneId"],
                "segmentIndex": index,
                "segmentCount": len(contained),
                "assignedPlacementIds": sorted(assignments[placement_id]),
                "placementPosition": placement_position,
                "waypoints": waypoints,
            }
            plan = {
                "planId": _stable_id("flop", seed),
                "routeId": _stable_id("rt-local-operator", seed),
                "placementId": placement_id,
                "zoneId": zone["zoneId"],
                "zoneLabel": zone["label"],
                "segmentIndex": index,
                "segmentCount": len(contained),
                "assignedPlacementIds": sorted(assignments[placement_id]),
                "placementPosition": placement_position,
                "pathKind": (
                    "split_station_loop" if len(contained) > 1
                    else "cell_work_loop"
                ),
                "anchor": anchor,
                "waypoints": waypoints,
                "traversableBoundary": (
                    _local_traversable_boundary(
                        layout,
                        zone,
                        axis=axis,
                        segment_start=segment_start,
                        segment_end=segment_end,
                    )
                    if len(contained) > 1
                    else deepcopy(boundary)
                ),
            }
            operator_plans.append(plan)
            zone_plans.append(plan)
        zone_plans.sort(key=lambda item: (item["segmentIndex"], item["planId"]))
        plans_by_zone[zone["zoneId"]] = zone_plans
        for index in range(len(zone_plans) - 1):
            first = zone_plans[index]
            second = zone_plans[index + 1]
            separator = segment_limits[index][1]
            position = _assistance_gate_position(
                zone["bounds"],
                axis=axis,
                separator=separator,
                service_side=side,
            )
            seed = {
                "zoneId": zone["zoneId"],
                "participantPlanIds": [first["planId"], second["planId"]],
                "position": position,
            }
            assistance_gate_plans.append({
                "gatePlanId": _stable_id("assist", seed),
                **seed,
                "evidenceStatus": "derived",
            })

    by_kind = {
        kind: [zone for zone in zones if zone["kind"] == kind]
        for kind in ("kitting_island", "assembly_line", "assembly_cell")
    }
    for values in by_kind.values():
        values.sort(key=lambda item: (
            float(item["bounds"]["centerX"]),
            float(item["bounds"]["centerZ"]),
            item["zoneId"],
        ))
    links: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for target in by_kind["assembly_line"]:
        if by_kind["kitting_island"]:
            source = min(
                by_kind["kitting_island"],
                key=lambda item: (
                    abs(
                        float(item["bounds"]["centerX"])
                        - float(target["bounds"]["centerX"])
                    ),
                    item["zoneId"],
                ),
            )
            links.append((source, target))
    for target in by_kind["assembly_cell"]:
        if by_kind["assembly_line"]:
            source = min(
                by_kind["assembly_line"],
                key=lambda item: (
                    abs(
                        float(item["bounds"]["centerX"])
                        - float(target["bounds"]["centerX"])
                    ),
                    item["zoneId"],
                ),
            )
            links.append((source, target))

    fifo_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    handoffs = []
    pedestrian_link_plans = []
    visit_plans_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for source, target in links:
        source_plans = plans_by_zone.get(source["zoneId"], [])
        target_plans = plans_by_zone.get(target["zoneId"], [])
        traversable_boundary = _shared_containing_boundary(layout, source, target)
        if not source_plans or not target_plans or traversable_boundary is None:
            continue
        source_plan, target_plan = min(
            (
                (source_plan, target_plan)
                for source_plan in source_plans
                for target_plan in target_plans
            ),
            key=lambda pair: (
                math.hypot(
                    pair[0]["anchor"]["x"] - pair[1]["anchor"]["x"],
                    pair[0]["anchor"]["z"] - pair[1]["anchor"]["z"],
                ),
                pair[0]["planId"],
                pair[1]["planId"],
            ),
        )
        start = _zone_interface(source["bounds"], target["bounds"])
        end = _zone_interface(target["bounds"], source["bounds"])
        source_key = (
            source["zoneId"],
            "output",
            f"{start['x']:.6f},{start['z']:.6f}",
        )
        target_key = (
            target["zoneId"],
            "input",
            f"{end['x']:.6f},{end['z']:.6f}",
        )
        for key, zone, role, position in (
            (source_key, source, "output", start),
            (target_key, target, "input", end),
        ):
            point_seed = {
                "zoneId": zone["zoneId"],
                "role": role,
                "position": position,
            }
            fifo_by_key[key] = {
                "pointId": _stable_id("fifo", point_seed),
                "zoneId": zone["zoneId"],
                "role": role,
                "position": position,
                "evidenceStatus": "derived",
            }
        handoff_seed = {
            "fromZoneId": source["zoneId"],
            "toZoneId": target["zoneId"],
            "centerline": _orthogonal_handoff(start, end),
        }
        handoff_id = _stable_id("handoff", handoff_seed)
        endpoint_records = []
        for plan, zone, role, point_id, position in (
            (
                source_plan,
                source,
                "output",
                fifo_by_key[source_key]["pointId"],
                start,
            ),
            (
                target_plan,
                target,
                "input",
                fifo_by_key[target_key]["pointId"],
                end,
            ),
        ):
            visit_key = (str(plan["planId"]), str(point_id))
            visit = visit_plans_by_key.get(visit_key)
            if visit is None:
                visit_seed = {
                    "planId": plan["planId"],
                    "pointId": point_id,
                    "role": role,
                }
                visit = {
                    "connectionPlanId": _stable_id("ped-access", visit_seed),
                    "planId": str(plan["planId"]),
                    "zoneId": str(zone["zoneId"]),
                    "pointId": str(point_id),
                    "role": role,
                    "position": deepcopy(position),
                    "handoffIds": [],
                    "traversableBoundary": deepcopy(traversable_boundary),
                    "evidenceStatus": "derived",
                }
                visit_plans_by_key[visit_key] = visit
            if handoff_id not in visit["handoffIds"]:
                visit["handoffIds"].append(handoff_id)
                visit["handoffIds"].sort()
            endpoint_records.append(visit)
        handoffs.append({
            "handoffId": handoff_id,
            **handoff_seed,
            "fromPointId": fifo_by_key[source_key]["pointId"],
            "toPointId": fifo_by_key[target_key]["pointId"],
            "fromPlanId": str(source_plan["planId"]),
            "toPlanId": str(target_plan["planId"]),
            "fromConnectionPlanId": endpoint_records[0]["connectionPlanId"],
            "toConnectionPlanId": endpoint_records[1]["connectionPlanId"],
            "evidenceStatus": "derived",
        })
    handoffs.sort(key=lambda item: item["handoffId"])
    fifo_points = sorted(fifo_by_key.values(), key=lambda item: item["pointId"])
    pedestrian_link_plans.extend(visit_plans_by_key.values())
    pedestrian_link_plans.sort(key=lambda item: item["connectionPlanId"])
    assistance_gate_plans.sort(key=lambda item: item["gatePlanId"])
    operator_plans.sort(key=lambda item: (
        item["zoneId"],
        item["segmentIndex"],
        item["planId"],
    ))
    return {
        "operatorPlans": operator_plans,
        "pedestrianLinkPlans": pedestrian_link_plans,
        "assistanceGatePlans": assistance_gate_plans,
        "materialHandoffs": handoffs,
        "fifoPoints": fifo_points,
    }


def build_facility_lean_motion(
    blueprint: Mapping[str, Any],
    operator_paths: Sequence[Mapping[str, Any]],
    *,
    pedestrian_connections: Sequence[Mapping[str, Any]] = (),
    assistance_gates: Sequence[Mapping[str, Any]] = (),
    material_handoffs: Sequence[Mapping[str, Any]] | None = None,
    fifo_points: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the browser-facing layer after operator plans are validated."""

    return {
        "schemaVersion": FACILITY_LEAN_MOTION_SCHEMA_VERSION,
        "qualification": FACILITY_LEAN_MOTION_QUALIFICATION,
        "evidenceStatus": "derived",
        "operatorPaths": deepcopy(list(operator_paths)),
        "pedestrianConnections": deepcopy(list(pedestrian_connections)),
        "assistanceGates": deepcopy(list(assistance_gates)),
        "materialHandoffs": deepcopy(list(
            blueprint.get("materialHandoffs", [])
            if material_handoffs is None
            else material_handoffs
        )),
        "fifoPoints": deepcopy(list(
            blueprint.get("fifoPoints", [])
            if fifo_points is None
            else fifo_points
        )),
    }


__all__ = [
    "FACILITY_LEAN_MOTION_QUALIFICATION",
    "FACILITY_LEAN_MOTION_SCHEMA_VERSION",
    "build_facility_lean_motion",
    "derive_facility_lean_motion_blueprint",
]
