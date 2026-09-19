"""Deterministic world-space geometry for process maps."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROCESS_MAP_SPATIAL_VERSION = 1
PROCESS_MAP_SPATIAL_CONTRACT_ID = "process-map-spatial-contract-v1"
PROCESS_MAP_CANDIDATE_POLICY_VERSION = 1
PROCESS_MAP_ROUTER_VERSION = 1
PROCESS_MAP_SPATIAL_PROPOSAL_VERSION = 1
PROCESS_MAP_ARRANGEMENT_POLICY_VERSION = 1
PLACEMENT_HARD_REJECTIONS = (
    "node_overlap",
    "insufficient_node_clearance",
    "group_containment_violation",
    "group_header_intersection",
    "edge_node_intersection",
    "invalid_topology",
    "duplicate_connection",
    "precedence_cycle",
    "locked_node_movement",
    "invalid_geometry",
)
ARRANGEMENT_HARD_PROBLEM_CODES = (
    "node_overlap",
    "insufficient_node_clearance",
    "node_group_header_intersection",
    "edge_node_intersection",
    "edge_group_header_intersection",
)
_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "static"
    / "contracts"
    / "process-map-spatial-contract-v1.json"
)


class SpatialContractError(ValueError):
    """Raised when the shared spatial contract is missing or malformed."""


class SpatialGeometryError(ValueError):
    """Raised when validated map geometry cannot be compiled."""


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _positive_number(value: Any) -> bool:
    return _finite_number(value) and float(value) > 0


def _validate_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("contractId") != PROCESS_MAP_SPATIAL_CONTRACT_ID:
        raise SpatialContractError("unsupported process-map spatial contract id")
    if contract.get("contractVersion") != 1:
        raise SpatialContractError("unsupported process-map spatial contract version")
    if contract.get("spatialVersion") != PROCESS_MAP_SPATIAL_VERSION:
        raise SpatialContractError("unsupported process-map spatial version")

    spaces = contract.get("coordinateSpaces")
    if not isinstance(spaces, Mapping) or spaces.get("persisted") != "world":
        raise SpatialContractError("the persisted coordinate space must be world")

    geometry = contract.get("geometry")
    envelopes = geometry.get("nodeEnvelopes") if isinstance(geometry, Mapping) else None
    if not isinstance(envelopes, Mapping) or "default" not in envelopes:
        raise SpatialContractError("node envelopes require a default geometry")
    for name, envelope in envelopes.items():
        if (
            not isinstance(envelope, Mapping)
            or not _positive_number(envelope.get("width"))
            or not _positive_number(envelope.get("height"))
        ):
            raise SpatialContractError(f"invalid node envelope '{name}'")

    junction = geometry.get("junction")
    if (
        not isinstance(junction, Mapping)
        or not _positive_number(junction.get("visualDiameter"))
        or not _positive_number(junction.get("hitDiameter"))
        or float(junction["visualDiameter"]) > float(junction["hitDiameter"])
    ):
        raise SpatialContractError("invalid junction geometry")
    if not _positive_number(geometry.get("groupHeaderHeight")):
        raise SpatialContractError("invalid group header height")
    if (
        not isinstance(geometry.get("legacyBezierSamplingSegments"), int)
        or isinstance(geometry.get("legacyBezierSamplingSegments"), bool)
        or not 8 <= geometry["legacyBezierSamplingSegments"] <= 128
    ):
        raise SpatialContractError("invalid legacy Bezier sampling segment count")

    diagnostics = contract.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        raise SpatialContractError("spatial diagnostics policy is required")
    for field in ("regionColumns", "regionRows"):
        if (
            not isinstance(diagnostics.get(field), int)
            or isinstance(diagnostics.get(field), bool)
            or not 1 <= diagnostics[field] <= 12
        ):
            raise SpatialContractError(f"invalid diagnostics field '{field}'")
    for field in (
        "denseOccupancyThreshold",
        "alignmentWarningThreshold",
        "detourRatioThreshold",
    ):
        if not _positive_number(diagnostics.get(field)):
            raise SpatialContractError(f"invalid diagnostics field '{field}'")
    if float(diagnostics["denseOccupancyThreshold"]) > 1:
        raise SpatialContractError("dense occupancy threshold cannot exceed one")

    flow_directions = contract.get("flowDirections")
    route_modes = contract.get("routeModes")
    if not isinstance(flow_directions, list) or "left_to_right" not in flow_directions:
        raise SpatialContractError("left_to_right must be a supported flow direction")
    if not isinstance(route_modes, list) or "bezier_legacy" not in route_modes:
        raise SpatialContractError("bezier_legacy must be a supported route mode")

    limits = contract.get("limits")
    if not isinstance(limits, Mapping):
        raise SpatialContractError("spatial limits are required")
    for field in (
        "maximumNodes",
        "maximumEdges",
        "maximumGroups",
        "maximumCandidates",
        "maximumRoutePoints",
    ):
        if not isinstance(limits.get(field), int) or isinstance(limits.get(field), bool) or limits[field] <= 0:
            raise SpatialContractError(f"invalid spatial limit '{field}'")


@lru_cache(maxsize=4)
def _load_contract(path_text: str) -> Dict[str, Any]:
    raw = Path(path_text).read_bytes()
    if any(byte > 127 for byte in raw):
        raise SpatialContractError("the process-map spatial contract must be ASCII")
    contract = json.loads(raw.decode("ascii"))
    if not isinstance(contract, dict):
        raise SpatialContractError("the process-map spatial contract must be an object")
    _validate_contract(contract)
    return contract


def load_spatial_contract(path: Optional[Path] = None) -> Dict[str, Any]:
    """Return an isolated copy of the validated shared spatial contract."""

    resolved = Path(path or _CONTRACT_PATH).resolve()
    return deepcopy(_load_contract(str(resolved)))


def spatial_contract_for_process_map(
    process_map: Mapping[str, Any],
    contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Overlay a validated map policy onto the shared deterministic contract."""

    active = deepcopy(dict(contract)) if contract is not None else load_spatial_contract()
    policy = process_map.get("layoutPolicy") if isinstance(process_map, Mapping) else None
    if isinstance(policy, Mapping):
        allowed = {
            "flowDirection",
            "gridSize",
            "nodeClearance",
            "edgeClearance",
            "portLeadLength",
            "routeMode",
        }
        if set(policy) - allowed:
            raise SpatialContractError("the process-map layout policy contains unsupported fields")
        active_policy = active.get("layoutPolicyDefaults")
        if not isinstance(active_policy, dict):
            raise SpatialContractError("spatial layout policy defaults are required")
        active_policy.update(deepcopy(dict(policy)))
    _validate_contract(active)
    return active


def _spatial_contract_for_scene(
    scene: Mapping[str, Any],
    contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    active = deepcopy(dict(contract)) if contract is not None else load_spatial_contract()
    policy = scene.get("layoutPolicy") if isinstance(scene, Mapping) else None
    if isinstance(policy, Mapping):
        active["layoutPolicyDefaults"].update(deepcopy(dict(policy)))
    _validate_contract(active)
    return active


def reset_spatial_contract_cache_for_tests() -> None:
    _load_contract.cache_clear()


def _point(value: Mapping[str, Any], field: str) -> Dict[str, float]:
    if not isinstance(value, Mapping) or not _finite_number(value.get("x")) or not _finite_number(value.get("y")):
        raise SpatialGeometryError(f"{field} requires finite x and y values")
    return {"x": float(value["x"]), "y": float(value["y"])}


def _rect(value: Mapping[str, Any], field: str) -> Dict[str, float]:
    point = _point(value, field)
    if not _finite_number(value.get("width")) or not _finite_number(value.get("height")):
        raise SpatialGeometryError(f"{field} requires finite width and height values")
    width = float(value["width"])
    height = float(value["height"])
    if width < 0 or height < 0:
        raise SpatialGeometryError(f"{field} width and height cannot be negative")
    return {**point, "width": width, "height": height}


def _transform(value: Mapping[str, Any]) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        raise SpatialGeometryError("transform must be an object")
    x = value.get("x")
    y = value.get("y")
    scale = value.get("scale")
    if not _finite_number(x) or not _finite_number(y) or not _positive_number(scale):
        raise SpatialGeometryError("transform requires finite x/y and a positive scale")
    return {"x": float(x), "y": float(y), "scale": float(scale)}


def world_to_viewport(point: Mapping[str, Any], transform: Mapping[str, Any]) -> Dict[str, float]:
    source = _point(point, "point")
    view = _transform(transform)
    return {
        "x": source["x"] * view["scale"] + view["x"],
        "y": source["y"] * view["scale"] + view["y"],
    }


def viewport_to_world(point: Mapping[str, Any], transform: Mapping[str, Any]) -> Dict[str, float]:
    source = _point(point, "point")
    view = _transform(transform)
    return {
        "x": (source["x"] - view["x"]) / view["scale"],
        "y": (source["y"] - view["y"]) / view["scale"],
    }


def world_rect_to_viewport(rect: Mapping[str, Any], transform: Mapping[str, Any]) -> Dict[str, float]:
    source = _rect(rect, "rect")
    view = _transform(transform)
    origin = world_to_viewport(source, view)
    return {
        **origin,
        "width": source["width"] * view["scale"],
        "height": source["height"] * view["scale"],
    }


def viewport_rect_to_world(rect: Mapping[str, Any], transform: Mapping[str, Any]) -> Dict[str, float]:
    source = _rect(rect, "rect")
    view = _transform(transform)
    origin = viewport_to_world(source, view)
    return {
        **origin,
        "width": source["width"] / view["scale"],
        "height": source["height"] / view["scale"],
    }


def world_to_normalized(point: Mapping[str, Any], world_bounds: Mapping[str, Any]) -> Dict[str, float]:
    source = _point(point, "point")
    bounds = _rect(world_bounds, "worldBounds")
    if bounds["width"] <= 0 or bounds["height"] <= 0:
        raise SpatialGeometryError("worldBounds must have positive width and height")
    return {
        "x": (source["x"] - bounds["x"]) / bounds["width"],
        "y": (source["y"] - bounds["y"]) / bounds["height"],
    }


def _node_orientation(node: Mapping[str, Any]) -> str:
    return "vertical" if node.get("portOrientation") == "vertical" else "horizontal"


def _node_order(node: Mapping[str, Any]) -> str:
    return "output_first" if node.get("portOrder") == "output_first" else "input_first"


def _port_direction(orientation: str, order: str, side: str) -> Dict[str, float]:
    leading = side == "out" if order == "output_first" else side == "in"
    if orientation == "vertical":
        return {"x": 0.0, "y": -1.0 if leading else 1.0}
    return {"x": -1.0 if leading else 1.0, "y": 0.0}


def _port_anchor(rect: Mapping[str, float], orientation: str, order: str, side: str) -> Dict[str, float]:
    leading = side == "out" if order == "output_first" else side == "in"
    if orientation == "vertical":
        return {
            "x": rect["x"] + rect["width"] / 2.0,
            "y": rect["y"] if leading else rect["y"] + rect["height"],
        }
    return {
        "x": rect["x"] if leading else rect["x"] + rect["width"],
        "y": rect["y"] + rect["height"] / 2.0,
    }


def _bounds(rectangles: Iterable[Mapping[str, float]]) -> Dict[str, float]:
    values = list(rectangles)
    if not values:
        return {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
    minimum_x = min(value["x"] for value in values)
    minimum_y = min(value["y"] for value in values)
    maximum_x = max(value["x"] + value["width"] for value in values)
    maximum_y = max(value["y"] + value["height"] for value in values)
    return {
        "x": minimum_x,
        "y": minimum_y,
        "width": maximum_x - minimum_x,
        "height": maximum_y - minimum_y,
    }


def _point_bounds(points: Iterable[Mapping[str, float]]) -> Dict[str, float]:
    values = list(points)
    if not values:
        return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
    minimum_x = min(point["x"] for point in values)
    minimum_y = min(point["y"] for point in values)
    maximum_x = max(point["x"] for point in values)
    maximum_y = max(point["y"] for point in values)
    return {
        "x": minimum_x,
        "y": minimum_y,
        "width": maximum_x - minimum_x,
        "height": maximum_y - minimum_y,
    }


def _sorted_records(values: Iterable[Any], id_field: str) -> list[Any]:
    return sorted(
        values,
        key=lambda item: str(item.get(id_field, "")) if isinstance(item, Mapping) else "",
    )


def _rounded(value: float) -> float:
    rounded = float(f"{float(value):.6f}")
    return 0.0 if rounded == 0 else rounded


def _rect_intersection(
    left: Mapping[str, float],
    right: Mapping[str, float],
) -> Optional[Dict[str, float]]:
    x = max(left["x"], right["x"])
    y = max(left["y"], right["y"])
    maximum_x = min(left["x"] + left["width"], right["x"] + right["width"])
    maximum_y = min(left["y"] + left["height"], right["y"] + right["height"])
    if maximum_x <= x or maximum_y <= y:
        return None
    return {"x": x, "y": y, "width": maximum_x - x, "height": maximum_y - y}


def _rect_distance(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    dx = max(
        left["x"] - (right["x"] + right["width"]),
        right["x"] - (left["x"] + left["width"]),
        0.0,
    )
    dy = max(
        left["y"] - (right["y"] + right["height"]),
        right["y"] - (left["y"] + left["height"]),
        0.0,
    )
    return math.hypot(dx, dy)


def _expanded_rect(rectangle: Mapping[str, float], amount: float) -> Dict[str, float]:
    return {
        "x": rectangle["x"] - amount,
        "y": rectangle["y"] - amount,
        "width": rectangle["width"] + amount * 2.0,
        "height": rectangle["height"] + amount * 2.0,
    }


class _SpatialGridIndex:
    """Small deterministic broad-phase index for rectangle queries."""

    def __init__(self, cell_size: float) -> None:
        self.cell_size = max(float(cell_size), 1.0)
        self._cells: Dict[tuple[int, int], set[str]] = {}

    def _keys(self, rectangle: Mapping[str, float]) -> Iterable[tuple[int, int]]:
        minimum_x = math.floor(rectangle["x"] / self.cell_size)
        minimum_y = math.floor(rectangle["y"] / self.cell_size)
        maximum_x = math.floor(
            (rectangle["x"] + max(rectangle["width"], 0.0)) / self.cell_size
        )
        maximum_y = math.floor(
            (rectangle["y"] + max(rectangle["height"], 0.0)) / self.cell_size
        )
        for row in range(minimum_y, maximum_y + 1):
            for column in range(minimum_x, maximum_x + 1):
                yield column, row

    def insert(self, record_id: str, rectangle: Mapping[str, float]) -> None:
        for key in self._keys(rectangle):
            self._cells.setdefault(key, set()).add(record_id)

    def query(self, rectangle: Mapping[str, float]) -> list[str]:
        matches: set[str] = set()
        for key in self._keys(rectangle):
            matches.update(self._cells.get(key, ()))
        return sorted(matches)


def _legacy_bezier_controls(
    start: Mapping[str, float],
    end: Mapping[str, float],
    source_direction: Mapping[str, float],
    target_direction: Mapping[str, float],
) -> tuple[Dict[str, float], Dict[str, float]]:
    default_horizontal = (
        source_direction["x"] == 1
        and source_direction["y"] == 0
        and target_direction["x"] == -1
        and target_direction["y"] == 0
    )
    if default_horizontal:
        control = max(88.0, abs(end["x"] - start["x"]) * 0.48)
        return (
            {"x": start["x"] + control, "y": start["y"]},
            {"x": end["x"] - control, "y": end["y"]},
        )
    control = max(
        88.0,
        math.hypot(end["x"] - start["x"], end["y"] - start["y"]) * 0.38,
    )
    return (
        {
            "x": start["x"] + source_direction["x"] * control,
            "y": start["y"] + source_direction["y"] * control,
        },
        {
            "x": end["x"] + target_direction["x"] * control,
            "y": end["y"] + target_direction["y"] * control,
        },
    )


def _sample_cubic_bezier(
    start: Mapping[str, float],
    first: Mapping[str, float],
    second: Mapping[str, float],
    end: Mapping[str, float],
    segments: int,
) -> list[Dict[str, float]]:
    values = []
    for index in range(segments + 1):
        t = index / segments
        inverse = 1.0 - t
        values.append(
            {
                "x": (
                    inverse**3 * start["x"]
                    + 3.0 * inverse**2 * t * first["x"]
                    + 3.0 * inverse * t**2 * second["x"]
                    + t**3 * end["x"]
                ),
                "y": (
                    inverse**3 * start["y"]
                    + 3.0 * inverse**2 * t * first["y"]
                    + 3.0 * inverse * t**2 * second["y"]
                    + t**3 * end["y"]
                ),
            }
        )
    return values


def _edge_path_points(
    edge: Mapping[str, Any],
    node_by_id: Mapping[str, Mapping[str, Any]],
    segments: int,
) -> list[Dict[str, float]]:
    points = [dict(point) for point in edge.get("points") or []]
    if len(points) < 2:
        return points
    if edge.get("routeMode") != "bezier_legacy":
        return points
    source = node_by_id.get(str(edge.get("fromNodeId") or "")) or {}
    target = node_by_id.get(str(edge.get("toNodeId") or "")) or {}
    source_direction = ((source.get("ports") or {}).get("output") or {}).get("direction")
    target_direction = ((target.get("ports") or {}).get("input") or {}).get("direction")
    if not isinstance(source_direction, Mapping) or not isinstance(target_direction, Mapping):
        return points
    first, second = _legacy_bezier_controls(
        points[0], points[-1], source_direction, target_direction
    )
    return _sample_cubic_bezier(points[0], first, second, points[-1], segments)


def _segments(points: Sequence[Mapping[str, float]]) -> Iterable[tuple[Mapping[str, float], Mapping[str, float]]]:
    for index in range(len(points) - 1):
        yield points[index], points[index + 1]


def _bounded_segments(
    points: Sequence[Mapping[str, float]],
) -> list[tuple[Mapping[str, float], Mapping[str, float], float, float, float, float]]:
    return [
        (
            start,
            end,
            min(start["x"], end["x"]),
            min(start["y"], end["y"]),
            max(start["x"], end["x"]),
            max(start["y"], end["y"]),
        )
        for start, end in _segments(points)
    ]


def _bounded_polyline_intersects_rect(
    segments: Sequence[
        tuple[Mapping[str, float], Mapping[str, float], float, float, float, float]
    ],
    rectangle: Mapping[str, float],
) -> bool:
    minimum_x = rectangle["x"]
    minimum_y = rectangle["y"]
    maximum_x = minimum_x + rectangle["width"]
    maximum_y = minimum_y + rectangle["height"]
    epsilon = 1e-9
    for start, end, segment_min_x, segment_min_y, segment_max_x, segment_max_y in segments:
        if (
            segment_max_x < minimum_x - epsilon
            or segment_min_x > maximum_x + epsilon
            or segment_max_y < minimum_y - epsilon
            or segment_min_y > maximum_y + epsilon
        ):
            continue
        if _segment_intersects_rect(start, end, rectangle):
            return True
    return False


def _point_in_rect(point: Mapping[str, float], rectangle: Mapping[str, float]) -> bool:
    epsilon = 1e-9
    return (
        rectangle["x"] - epsilon <= point["x"] <= rectangle["x"] + rectangle["width"] + epsilon
        and rectangle["y"] - epsilon <= point["y"] <= rectangle["y"] + rectangle["height"] + epsilon
    )


def _segment_intersects_rect(
    start: Mapping[str, float],
    end: Mapping[str, float],
    rectangle: Mapping[str, float],
) -> bool:
    if _point_in_rect(start, rectangle) or _point_in_rect(end, rectangle):
        return True
    dx = end["x"] - start["x"]
    dy = end["y"] - start["y"]
    p = (-dx, dx, -dy, dy)
    q = (
        start["x"] - rectangle["x"],
        rectangle["x"] + rectangle["width"] - start["x"],
        start["y"] - rectangle["y"],
        rectangle["y"] + rectangle["height"] - start["y"],
    )
    minimum = 0.0
    maximum = 1.0
    for coefficient, distance in zip(p, q):
        if abs(coefficient) <= 1e-12:
            if distance < 0:
                return False
            continue
        ratio = distance / coefficient
        if coefficient < 0:
            minimum = max(minimum, ratio)
        else:
            maximum = min(maximum, ratio)
        if minimum > maximum:
            return False
    return True


def _polyline_intersects_rect(
    points: Sequence[Mapping[str, float]],
    rectangle: Mapping[str, float],
) -> bool:
    return any(_segment_intersects_rect(start, end, rectangle) for start, end in _segments(points))


def _segment_crossing(
    first_start: Mapping[str, float],
    first_end: Mapping[str, float],
    second_start: Mapping[str, float],
    second_end: Mapping[str, float],
) -> Optional[Dict[str, float]]:
    first_dx = first_end["x"] - first_start["x"]
    first_dy = first_end["y"] - first_start["y"]
    second_dx = second_end["x"] - second_start["x"]
    second_dy = second_end["y"] - second_start["y"]
    denominator = first_dx * second_dy - first_dy * second_dx
    if abs(denominator) <= 1e-9:
        return None
    offset_x = second_start["x"] - first_start["x"]
    offset_y = second_start["y"] - first_start["y"]
    first_ratio = (offset_x * second_dy - offset_y * second_dx) / denominator
    second_ratio = (offset_x * first_dy - offset_y * first_dx) / denominator
    epsilon = 1e-8
    if not (-epsilon <= first_ratio <= 1.0 + epsilon and -epsilon <= second_ratio <= 1.0 + epsilon):
        return None
    return {
        "x": first_start["x"] + first_ratio * first_dx,
        "y": first_start["y"] + first_ratio * first_dy,
    }


def _polyline_crossing(
    first: Sequence[Mapping[str, float]],
    second: Sequence[Mapping[str, float]],
) -> Optional[Dict[str, float]]:
    # Segment bounds are computed once per polyline. The previous code rebuilt
    # two dictionaries for every segment pair, which dominated diagnostics on
    # large maps even after the edge-level spatial-index prune.
    first_segments = _bounded_segments(first)
    second_segments = _bounded_segments(second)
    padding = 2e-7
    for first_start, first_end, first_min_x, first_min_y, first_max_x, first_max_y in first_segments:
        for second_start, second_end, second_min_x, second_min_y, second_max_x, second_max_y in second_segments:
            if (
                first_max_x + padding <= second_min_x
                or second_max_x + padding <= first_min_x
                or first_max_y + padding <= second_min_y
                or second_max_y + padding <= first_min_y
            ):
                continue
            crossing = _segment_crossing(first_start, first_end, second_start, second_end)
            if crossing is not None:
                return crossing
    return None


def _polyline_length(points: Sequence[Mapping[str, float]]) -> float:
    return sum(
        math.hypot(end["x"] - start["x"], end["y"] - start["y"])
        for start, end in _segments(points)
    )


def _route_bends(edge: Mapping[str, Any]) -> int:
    if edge.get("routeMode") == "bezier_legacy":
        return 0
    points = edge.get("points") or []
    bends = 0
    for index in range(1, len(points) - 1):
        left = points[index - 1]
        middle = points[index]
        right = points[index + 1]
        cross = (
            (middle["x"] - left["x"]) * (right["y"] - middle["y"])
            - (middle["y"] - left["y"]) * (right["x"] - middle["x"])
        )
        if abs(cross) > 1e-8:
            bends += 1
    return bends


def _problem(
    code: str,
    severity: str,
    record_ids: Sequence[str],
    **details: Any,
) -> Dict[str, Any]:
    return {
        "problemId": ":".join((code, *record_ids)),
        "severity": severity,
        "code": code,
        **details,
    }


def _region_location(row: int, column: int, rows: int, columns: int) -> str:
    vertical = {
        1: ["center"],
        2: ["upper", "lower"],
        3: ["upper", "middle", "lower"],
    }
    horizontal = {
        1: ["center"],
        2: ["left", "right"],
        3: ["left", "center", "right"],
        4: ["left", "center-left", "center-right", "right"],
    }
    row_name = vertical.get(rows, [])[row] if rows in vertical else f"row-{row + 1}"
    column_name = (
        horizontal.get(columns, [])[column]
        if columns in horizontal
        else f"column-{column + 1}"
    )
    return f"{row_name}-{column_name}"


def compile_spatial_scene(
    process_map: Mapping[str, Any],
    *,
    revision: Optional[str] = None,
    contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile stable canonical geometry from a validated placement map."""

    if not isinstance(process_map, Mapping):
        raise SpatialGeometryError("process_map must be an object")
    active_contract = spatial_contract_for_process_map(process_map, contract)
    geometry = active_contract["geometry"]
    limits = active_contract["limits"]
    raw_nodes = process_map.get("canvasNodes", [])
    raw_edges = process_map.get("canvasEdges", [])
    raw_groups = process_map.get("canvasGroups", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list) or not isinstance(raw_groups, list):
        raise SpatialGeometryError("canvasNodes, canvasEdges, and canvasGroups must be arrays")
    if len(raw_nodes) > limits["maximumNodes"]:
        raise SpatialGeometryError("process map exceeds the spatial node limit")
    if len(raw_edges) > limits["maximumEdges"]:
        raise SpatialGeometryError("process map exceeds the spatial edge limit")
    if len(raw_groups) > limits["maximumGroups"]:
        raise SpatialGeometryError("process map exceeds the spatial group limit")

    membership: Dict[str, str] = {}
    groups = []
    header_height = float(geometry["groupHeaderHeight"])
    for group in _sorted_records(raw_groups, "groupId"):
        if not isinstance(group, Mapping) or not isinstance(group.get("groupId"), str) or not group["groupId"]:
            raise SpatialGeometryError("each canvas group requires a groupId")
        group_id = group["groupId"]
        position = _point(group.get("position"), f"group '{group_id}' position")
        size_value = group.get("size")
        if not isinstance(size_value, Mapping):
            raise SpatialGeometryError(f"group '{group_id}' requires a positive size")
        size = _rect(
            {
                **position,
                "width": size_value.get("width"),
                "height": size_value.get("height"),
            },
            f"group '{group_id}' size",
        )
        if size["width"] <= 0 or size["height"] <= 0:
            raise SpatialGeometryError(f"group '{group_id}' requires a positive size")
        members = group.get("memberNodeIds", [])
        if not isinstance(members, list) or any(not isinstance(node_id, str) or not node_id for node_id in members):
            raise SpatialGeometryError(f"group '{group_id}' has invalid members")
        for node_id in members:
            if node_id in membership:
                raise SpatialGeometryError(f"node '{node_id}' belongs to multiple groups")
            membership[node_id] = group_id
        groups.append(
            {
                "groupId": group_id,
                "rect": size,
                "headerRect": {
                    "x": size["x"],
                    "y": size["y"] - header_height,
                    "width": size["width"],
                    "height": header_height,
                },
                "memberNodeIds": sorted(members),
            }
        )

    nodes = []
    node_by_id: Dict[str, Dict[str, Any]] = {}
    envelopes = geometry["nodeEnvelopes"]
    for node in _sorted_records(raw_nodes, "nodeId"):
        if not isinstance(node, Mapping) or not isinstance(node.get("nodeId"), str) or not node["nodeId"]:
            raise SpatialGeometryError("each canvas node requires a nodeId")
        node_id = node["nodeId"]
        if node_id in node_by_id:
            raise SpatialGeometryError(f"duplicate canvas node '{node_id}'")
        position = _point(node.get("position"), f"node '{node_id}' position")
        node_kind = str(node.get("nodeKind") or "product_occurrence")
        junction = node_kind == "junction"
        if junction:
            diameter = float(geometry["junction"]["hitDiameter"])
            rect = {
                "x": position["x"] - diameter / 2.0,
                "y": position["y"] - diameter / 2.0,
                "width": diameter,
                "height": diameter,
            }
            center = position
            orientation = "horizontal"
            order = "input_first"
            input_anchor = center
            output_anchor = center
        else:
            envelope = envelopes.get(node_kind, envelopes["default"])
            rect = {
                "x": position["x"],
                "y": position["y"],
                "width": float(envelope["width"]),
                "height": float(envelope["height"]),
            }
            center = {
                "x": rect["x"] + rect["width"] / 2.0,
                "y": rect["y"] + rect["height"] / 2.0,
            }
            orientation = _node_orientation(node)
            order = _node_order(node)
            input_anchor = _port_anchor(rect, orientation, order, "in")
            output_anchor = _port_anchor(rect, orientation, order, "out")
        compiled = {
            "nodeId": node_id,
            "kind": node_kind,
            "rect": rect,
            "center": center,
            "portOrientation": orientation,
            "portOrder": order,
            "ports": {
                "input": {
                    **input_anchor,
                    "direction": _port_direction(orientation, order, "in"),
                },
                "output": {
                    **output_anchor,
                    "direction": _port_direction(orientation, order, "out"),
                },
            },
            "groupId": membership.get(node_id),
            "locked": node.get("locked") is True,
            "positionMode": (
                node.get("positionMode")
                if node.get("positionMode") in {"auto", "manual", "locked"}
                else ("locked" if node.get("locked") is True else "auto")
            ),
        }
        nodes.append(compiled)
        node_by_id[node_id] = compiled

    dangling_members = sorted(set(membership) - set(node_by_id))
    if dangling_members:
        raise SpatialGeometryError(f"group references unknown node '{dangling_members[0]}'")

    route_modes = set(active_contract["routeModes"])
    edges = []
    for edge in _sorted_records(raw_edges, "edgeId"):
        if not isinstance(edge, Mapping) or not isinstance(edge.get("edgeId"), str) or not edge["edgeId"]:
            raise SpatialGeometryError("each canvas edge requires an edgeId")
        source_id = (edge.get("from") or {}).get("nodeId") if isinstance(edge.get("from"), Mapping) else None
        target_id = (edge.get("to") or {}).get("nodeId") if isinstance(edge.get("to"), Mapping) else None
        if source_id not in node_by_id or target_id not in node_by_id:
            raise SpatialGeometryError(f"edge '{edge['edgeId']}' has a dangling endpoint")
        routing = edge.get("routing") if isinstance(edge.get("routing"), Mapping) else {}
        route_mode = str(routing.get("mode") or "bezier_legacy")
        if route_mode not in route_modes:
            raise SpatialGeometryError(f"edge '{edge['edgeId']}' has an unsupported route mode")
        start = deepcopy(node_by_id[source_id]["ports"]["output"])
        start.pop("direction", None)
        end = deepcopy(node_by_id[target_id]["ports"]["input"])
        end.pop("direction", None)
        waypoints = []
        if route_mode != "bezier_legacy":
            raw_waypoints = routing.get("waypoints", [])
            if not isinstance(raw_waypoints, list) or len(raw_waypoints) > limits["maximumRoutePoints"]:
                raise SpatialGeometryError(f"edge '{edge['edgeId']}' has invalid route waypoints")
            waypoints = [
                _point(waypoint, f"edge '{edge['edgeId']}' waypoint")
                for waypoint in raw_waypoints
            ]
        points = [start, *waypoints, end]
        edges.append(
            {
                "edgeId": edge["edgeId"],
                "logicalConnectionId": str(edge.get("logicalConnectionId") or edge["edgeId"]),
                "kind": str(edge.get("kind") or "precedence"),
                "fromNodeId": source_id,
                "toNodeId": target_id,
                "routeMode": route_mode,
                "points": points,
                "bounds": _point_bounds(points),
                "boundsApproximate": route_mode == "bezier_legacy",
            }
        )

    world_rectangles = [node["rect"] for node in nodes]
    world_rectangles.extend(group["rect"] for group in groups)
    world_rectangles.extend(group["headerRect"] for group in groups)
    world_rectangles.extend(edge["bounds"] for edge in edges)
    identity = {
        "productId": str(process_map.get("productId") or ""),
        "mapId": str(process_map.get("mapId") or ""),
        "layoutVersion": process_map.get("layoutVersion"),
    }
    if revision is not None:
        identity["revision"] = str(revision)
    scene = {
        "spatialVersion": PROCESS_MAP_SPATIAL_VERSION,
        "contractId": PROCESS_MAP_SPATIAL_CONTRACT_ID,
        "identity": identity,
        "worldBounds": _bounds(world_rectangles),
        "nodes": nodes,
        "groups": groups,
        "edges": edges,
    }
    if isinstance(process_map.get("layoutPolicy"), Mapping):
        scene["layoutPolicy"] = deepcopy(active_contract["layoutPolicyDefaults"])
    return scene


def diagnose_spatial_scene(
    scene: Mapping[str, Any],
    *,
    contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return deterministic, read-only layout diagnostics for a compiled scene."""

    if not isinstance(scene, Mapping):
        raise SpatialGeometryError("scene must be an object")
    if scene.get("spatialVersion") != PROCESS_MAP_SPATIAL_VERSION:
        raise SpatialGeometryError("scene has an unsupported spatial version")
    if scene.get("contractId") != PROCESS_MAP_SPATIAL_CONTRACT_ID:
        raise SpatialGeometryError("scene has an unsupported spatial contract")
    active_contract = _spatial_contract_for_scene(scene, contract)
    policy = active_contract["layoutPolicyDefaults"]
    diagnostics_policy = active_contract["diagnostics"]
    geometry = active_contract["geometry"]
    limits = active_contract["limits"]
    nodes = _sorted_records(scene.get("nodes") or [], "nodeId")
    groups = _sorted_records(scene.get("groups") or [], "groupId")
    edges = _sorted_records(scene.get("edges") or [], "edgeId")
    node_by_id = {str(node.get("nodeId") or ""): node for node in nodes}
    authored_nodes = [node for node in nodes if node.get("kind") != "junction"]
    node_by_id_authored = {str(node["nodeId"]): node for node in authored_nodes}
    node_clearance = float(policy["nodeClearance"])
    grid_size = float(policy["gridSize"])
    broad_phase_size = max(
        grid_size * 8.0,
        float(geometry["nodeEnvelopes"]["default"]["width"]),
    )
    node_index = _SpatialGridIndex(broad_phase_size)
    for node in authored_nodes:
        node_index.insert(str(node["nodeId"]), node["rect"])

    problems: list[Dict[str, Any]] = []
    node_overlap_count = 0
    clearance_violation_count = 0
    minimum_clearance: Optional[float] = None
    for index, node in enumerate(authored_nodes):
        for other in authored_nodes[index + 1 :]:
            clearance = _rect_distance(node["rect"], other["rect"])
            minimum_clearance = (
                clearance
                if minimum_clearance is None
                else min(minimum_clearance, clearance)
            )
    for node in authored_nodes:
        node_id = str(node["nodeId"])
        for other_id in node_index.query(_expanded_rect(node["rect"], node_clearance)):
            if other_id <= node_id:
                continue
            other = node_by_id_authored[other_id]
            overlap = _rect_intersection(node["rect"], other["rect"])
            clearance = 0.0 if overlap else _rect_distance(node["rect"], other["rect"])
            pair = [node_id, other_id]
            if overlap:
                node_overlap_count += 1
                problems.append(
                    _problem(
                        "node_overlap",
                        "warning",
                        pair,
                        nodeIds=pair,
                        overlapArea=_rounded(overlap["width"] * overlap["height"]),
                    )
                )
            elif clearance < node_clearance:
                clearance_violation_count += 1
                problems.append(
                    _problem(
                        "insufficient_node_clearance",
                        "warning",
                        pair,
                        nodeIds=pair,
                        clearance=_rounded(clearance),
                    )
                )

    node_group_header_count = 0
    for group in groups:
        group_id = str(group.get("groupId") or "")
        for node_id in node_index.query(group["headerRect"]):
            node = node_by_id_authored[node_id]
            if _rect_intersection(node["rect"], group["headerRect"]) is None:
                continue
            node_group_header_count += 1
            problems.append(
                _problem(
                    "node_group_header_intersection",
                    "warning",
                    [group_id, node_id],
                    nodeIds=[node_id],
                    groupIds=[group_id],
                )
            )

    sampled_edges = []
    route_length = 0.0
    route_bends = 0
    detour_ratios: list[float] = []
    backward_count = 0
    detour_count = 0
    sampling_segments = int(geometry["legacyBezierSamplingSegments"])
    flow_direction = str(policy["flowDirection"])
    backward_tolerance = grid_size / 2.0
    for edge in edges:
        path_points = _edge_path_points(edge, node_by_id, sampling_segments)
        path_bounds = _point_bounds(path_points)
        length = _polyline_length(path_points)
        direct = (
            math.hypot(
                path_points[-1]["x"] - path_points[0]["x"],
                path_points[-1]["y"] - path_points[0]["y"],
            )
            if len(path_points) >= 2
            else 0.0
        )
        ratio = length / direct if direct > 1e-9 else 1.0
        edge_id = str(edge.get("edgeId") or "")
        compiled = {
            "edge": edge,
            "edgeId": edge_id,
            "points": path_points,
            "segments": _bounded_segments(path_points),
            "bounds": path_bounds,
            "length": length,
            "detourRatio": ratio,
        }
        sampled_edges.append(compiled)
        route_length += length
        route_bends += _route_bends(edge)
        detour_ratios.append(ratio)
        if ratio > float(diagnostics_policy["detourRatioThreshold"]):
            detour_count += 1
            problems.append(
                _problem(
                    "route_detour",
                    "information",
                    [edge_id],
                    edgeIds=[edge_id],
                    detourRatio=_rounded(ratio),
                )
            )
        source = node_by_id.get(str(edge.get("fromNodeId") or "")) or {}
        target = node_by_id.get(str(edge.get("toNodeId") or "")) or {}
        source_center = source.get("center") or (path_points[0] if path_points else {"x": 0, "y": 0})
        target_center = target.get("center") or (path_points[-1] if path_points else {"x": 0, "y": 0})
        backward = (
            flow_direction == "left_to_right"
            and target_center["x"] < source_center["x"] - backward_tolerance
        ) or (
            flow_direction == "right_to_left"
            and target_center["x"] > source_center["x"] + backward_tolerance
        ) or (
            flow_direction == "top_to_bottom"
            and target_center["y"] < source_center["y"] - backward_tolerance
        ) or (
            flow_direction == "bottom_to_top"
            and target_center["y"] > source_center["y"] + backward_tolerance
        )
        if backward:
            backward_count += 1
            problems.append(
                _problem(
                    "backward_flow_edge",
                    "information",
                    [edge_id],
                    edgeIds=[edge_id],
                    nodeIds=[str(edge.get("fromNodeId") or ""), str(edge.get("toNodeId") or "")],
                )
            )

    edge_node_count = 0
    edge_group_header_count = 0
    for sampled in sampled_edges:
        edge = sampled["edge"]
        edge_id = sampled["edgeId"]
        endpoint_ids = {
            str(edge.get("fromNodeId") or ""),
            str(edge.get("toNodeId") or ""),
        }
        for node_id in node_index.query(sampled["bounds"]):
            if node_id in endpoint_ids:
                continue
            node = node_by_id_authored[node_id]
            if not _bounded_polyline_intersects_rect(sampled["segments"], node["rect"]):
                continue
            edge_node_count += 1
            problems.append(
                _problem(
                    "edge_node_intersection",
                    "warning",
                    [edge_id, node_id],
                    edgeIds=[edge_id],
                    nodeIds=[node_id],
                )
            )
        for group in groups:
            group_id = str(group.get("groupId") or "")
            if not _bounded_polyline_intersects_rect(
                sampled["segments"], group["headerRect"]
            ):
                continue
            edge_group_header_count += 1
            problems.append(
                _problem(
                    "edge_group_header_intersection",
                    "warning",
                    [edge_id, group_id],
                    edgeIds=[edge_id],
                    groupIds=[group_id],
                )
            )

    segment_cell_size = max(grid_size * 4.0, float(policy["edgeClearance"]) * 4.0)
    segment_index = _SpatialGridIndex(segment_cell_size)
    segment_by_key: Dict[
        str,
        tuple[
            str,
            Mapping[str, Any],
            Mapping[str, float],
            Mapping[str, float],
            Dict[str, float],
        ],
    ] = {}
    for edge_order, sampled in enumerate(sampled_edges):
        for segment_order, segment in enumerate(sampled["segments"]):
            start, end, minimum_x, minimum_y, maximum_x, maximum_y = segment
            segment_key = f"{edge_order:04d}:{segment_order:04d}"
            segment_bounds = {
                "x": minimum_x,
                "y": minimum_y,
                "width": maximum_x - minimum_x,
                "height": maximum_y - minimum_y,
            }
            segment_by_key[segment_key] = (
                sampled["edgeId"],
                sampled["edge"],
                start,
                end,
                segment_bounds,
            )
            segment_index.insert(segment_key, segment_bounds)

    edge_crossing_count = 0
    crossed_pairs: set[tuple[str, str]] = set()
    ineligible_pairs: set[tuple[str, str]] = set()
    for edge_order, sampled in enumerate(sampled_edges):
        edge = sampled["edge"]
        edge_id = sampled["edgeId"]
        endpoint_ids = {
            str(edge.get("fromNodeId") or ""),
            str(edge.get("toNodeId") or ""),
        }
        for segment_order, segment in enumerate(sampled["segments"]):
            start, end, minimum_x, minimum_y, maximum_x, maximum_y = segment
            segment_key = f"{edge_order:04d}:{segment_order:04d}"
            query_bounds = {
                "x": minimum_x - 1e-7,
                "y": minimum_y - 1e-7,
                "width": maximum_x - minimum_x + 2e-7,
                "height": maximum_y - minimum_y + 2e-7,
            }
            for other_key in segment_index.query(query_bounds):
                if other_key <= segment_key:
                    continue
                other_id, other_edge, other_start, other_end, _other_bounds = segment_by_key[
                    other_key
                ]
                if other_id <= edge_id:
                    continue
                pair = (edge_id, other_id)
                if pair in crossed_pairs or pair in ineligible_pairs:
                    continue
                if str(edge.get("logicalConnectionId") or edge_id) == str(
                    other_edge.get("logicalConnectionId") or other_id
                ):
                    ineligible_pairs.add(pair)
                    continue
                other_endpoints = {
                    str(other_edge.get("fromNodeId") or ""),
                    str(other_edge.get("toNodeId") or ""),
                }
                if endpoint_ids & other_endpoints:
                    ineligible_pairs.add(pair)
                    continue
                crossing = _segment_crossing(start, end, other_start, other_end)
                if crossing is None:
                    continue
                crossed_pairs.add(pair)
                edge_crossing_count += 1
                problems.append(
                    _problem(
                        "edge_crossing",
                        "information",
                        [edge_id, other_id],
                        edgeIds=[edge_id, other_id],
                        point={
                            "x": _rounded(crossing["x"]),
                            "y": _rounded(crossing["y"]),
                        },
                    )
                )

    alignment_values = []
    alignment_warning_count = 0
    alignment_threshold = float(diagnostics_policy["alignmentWarningThreshold"])
    for node in authored_nodes:
        remainder_x = abs(node["rect"]["x"]) % grid_size
        remainder_y = abs(node["rect"]["y"]) % grid_size
        dx = min(remainder_x, grid_size - remainder_x)
        dy = min(remainder_y, grid_size - remainder_y)
        deviation = (dx + dy) / 2.0
        alignment_values.append(deviation)
        if deviation > alignment_threshold:
            alignment_warning_count += 1

    diagnostic_rectangles = [node["rect"] for node in nodes]
    diagnostic_rectangles.extend(group["rect"] for group in groups)
    diagnostic_rectangles.extend(group["headerRect"] for group in groups)
    diagnostic_rectangles.extend(sampled["bounds"] for sampled in sampled_edges)
    world_bounds = _bounds(diagnostic_rectangles)
    columns = int(diagnostics_policy["regionColumns"])
    rows = int(diagnostics_policy["regionRows"])
    region_width = world_bounds["width"] / columns if world_bounds["width"] > 0 else 1.0
    region_height = world_bounds["height"] / rows if world_bounds["height"] > 0 else 1.0
    dense_threshold = float(diagnostics_policy["denseOccupancyThreshold"])
    regions = []
    dense_region_count = 0
    open_region_count = 0
    for row in range(rows):
        for column in range(columns):
            region_rect = {
                "x": world_bounds["x"] + column * region_width,
                "y": world_bounds["y"] + row * region_height,
                "width": region_width,
                "height": region_height,
            }
            occupied_area = 0.0
            intersecting_ids = []
            for node in authored_nodes:
                overlap = _rect_intersection(region_rect, node["rect"])
                if overlap is None:
                    continue
                intersecting_ids.append(str(node["nodeId"]))
                occupied_area += overlap["width"] * overlap["height"]
            area = max(region_rect["width"] * region_rect["height"], 1.0)
            occupancy = min(1.0, occupied_area / area)
            if not intersecting_ids:
                classification = "open"
                open_region_count += 1
            elif occupancy >= dense_threshold or len(intersecting_ids) >= 3:
                classification = "dense"
                dense_region_count += 1
            else:
                classification = "balanced"
            regions.append(
                {
                    "regionId": f"region-r{row + 1}-c{column + 1}",
                    "relativeLocation": _region_location(row, column, rows, columns),
                    "normalizedBounds": {
                        "x": _rounded(column / columns),
                        "y": _rounded(row / rows),
                        "width": _rounded(1.0 / columns),
                        "height": _rounded(1.0 / rows),
                    },
                    "nodeIds": sorted(intersecting_ids),
                    "occupancy": _rounded(occupancy),
                    "classification": classification,
                }
            )

    severity_order = {"error": 0, "warning": 1, "information": 2}
    problems.sort(
        key=lambda item: (
            severity_order.get(str(item.get("severity") or ""), 9),
            str(item.get("code") or ""),
            str(item.get("problemId") or ""),
        )
    )
    problem_count = len(problems)
    problems = problems[: int(limits["maximumCandidates"])]
    return {
        "spatialVersion": PROCESS_MAP_SPATIAL_VERSION,
        "layoutPolicy": {
            "flowDirection": flow_direction,
            "gridSize": _rounded(grid_size),
            "nodeClearance": _rounded(node_clearance),
            "edgeClearance": _rounded(float(policy["edgeClearance"])),
        },
        "metrics": {
            "nodeOverlaps": node_overlap_count,
            "nodeClearanceViolations": clearance_violation_count,
            "minimumNodeClearance": (
                _rounded(minimum_clearance) if minimum_clearance is not None else None
            ),
            "nodeGroupHeaderIntersections": node_group_header_count,
            "edgeNodeIntersections": edge_node_count,
            "edgeGroupHeaderIntersections": edge_group_header_count,
            "edgeCrossings": edge_crossing_count,
            "backwardEdges": backward_count,
            "routeLength": _rounded(route_length),
            "routeBends": route_bends,
            "routeDetourOpportunities": detour_count,
            "meanDetourRatio": _rounded(
                sum(detour_ratios) / len(detour_ratios) if detour_ratios else 0.0
            ),
            "alignmentDeviation": _rounded(
                sum(alignment_values) / len(alignment_values) if alignment_values else 0.0
            ),
            "alignmentWarnings": alignment_warning_count,
            "denseRegions": dense_region_count,
            "openRegions": open_region_count,
            "worldRegionCount": len(regions),
        },
        "problems": problems,
        "problemCount": problem_count,
        "truncatedProblems": max(0, problem_count - len(problems)),
        "regions": regions,
    }


def _fingerprint_stable(value: Any) -> Any:
    """Recursively replace floats/ints with a fixed-decimal string.

    json.dumps renders a whole-number float differently across languages
    (Python: "50.0", JavaScript JSON.stringify: "50"). Stringifying every
    number to a fixed 6-decimal form before hashing removes that
    language-specific formatting from the fingerprint entirely.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        as_float = float(value)
        if as_float == 0.0:
            as_float = 0.0
        return f"{as_float:.6f}"
    if isinstance(value, dict):
        return {key: _fingerprint_stable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_fingerprint_stable(item) for item in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    stable = _fingerprint_stable(value)
    return json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


_FNV64_OFFSET_BASIS = 14695981039346656037
_FNV64_PRIME = 1099511628211
_FNV64_MASK = (1 << 64) - 1


def _fnv1a64_hex(payload: bytes) -> str:
    """Deterministic 64-bit fingerprint, identical to the JS mirror.

    Not a security boundary: staleness authority comes from the existing
    sha256 map revision. This only needs to be stable and collision-safe
    enough to detect geometry drift, and exact bit-for-bit parity between
    Python and JavaScript without depending on a hand-rolled cross-language
    cryptographic hash implementation.
    """

    value = _FNV64_OFFSET_BASIS
    for byte in payload:
        value ^= byte
        value = (value * _FNV64_PRIME) & _FNV64_MASK
    return format(value, "016x")


def _obstacle_fingerprint(scene: Mapping[str, Any]) -> str:
    payload = {
        "nodes": [
            {"id": node["nodeId"], "rect": node["rect"], "locked": node.get("locked", False)}
            for node in _sorted_records(scene.get("nodes") or [], "nodeId")
        ],
        "groups": [
            {"id": group["groupId"], "rect": group["rect"]}
            for group in _sorted_records(scene.get("groups") or [], "groupId")
        ],
        "edges": [
            {"id": edge["edgeId"], "kind": edge["kind"], "points": edge["points"]}
            for edge in _sorted_records(scene.get("edges") or [], "edgeId")
        ],
    }
    return _fnv1a64_hex(_canonical_bytes(payload))


def spatial_obstacle_fingerprint(scene: Mapping[str, Any]) -> str:
    """Return the stable geometry fingerprint used by placement proposals."""

    if (
        not isinstance(scene, Mapping)
        or scene.get("spatialVersion") != PROCESS_MAP_SPATIAL_VERSION
    ):
        raise SpatialGeometryError("scene has an unsupported spatial version")
    return _obstacle_fingerprint(scene)


def _route_obstacle_fingerprint(scene: Mapping[str, Any], edge_id: str) -> str:
    """Fingerprint only geometry that can invalidate one routed edge.

    The routed edge itself is deliberately excluded. Including its accepted
    waypoints would make the fingerprint change as a consequence of accepting
    the route and would mark a fresh route stale immediately.
    """

    payload = {
        "nodes": [
            {
                "id": node["nodeId"],
                "rect": node["rect"],
                "ports": node.get("ports") or {},
            }
            for node in _sorted_records(scene.get("nodes") or [], "nodeId")
        ],
        "groupHeaders": [
            {"id": group["groupId"], "rect": group["headerRect"]}
            for group in _sorted_records(scene.get("groups") or [], "groupId")
        ],
        "edges": [
            {
                "id": edge["edgeId"],
                "from": edge.get("fromNodeId"),
                "to": edge.get("toNodeId"),
                "points": edge.get("points") or [],
            }
            for edge in _sorted_records(scene.get("edges") or [], "edgeId")
            if edge.get("edgeId") != edge_id
            and edge.get("routeMode") != "orthogonal_auto"
        ],
    }
    return _fnv1a64_hex(_canonical_bytes(payload))


def _normalize_orthogonal_points(
    points: Sequence[Mapping[str, float]],
) -> list[Dict[str, float]]:
    normalized: list[Dict[str, float]] = []
    for raw in points:
        point = {"x": _rounded(float(raw["x"])), "y": _rounded(float(raw["y"]))}
        if normalized and point == normalized[-1]:
            continue
        normalized.append(point)
    changed = True
    while changed and len(normalized) >= 3:
        changed = False
        compacted = [normalized[0]]
        for index in range(1, len(normalized) - 1):
            left = compacted[-1]
            middle = normalized[index]
            right = normalized[index + 1]
            same_x = abs(left["x"] - middle["x"]) <= 1e-8 and abs(middle["x"] - right["x"]) <= 1e-8
            same_y = abs(left["y"] - middle["y"]) <= 1e-8 and abs(middle["y"] - right["y"]) <= 1e-8
            if same_x or same_y:
                changed = True
                continue
            compacted.append(middle)
        compacted.append(normalized[-1])
        normalized = compacted
    return normalized


def _orthogonal_path(points: Sequence[Mapping[str, float]]) -> bool:
    return all(
        abs(start["x"] - end["x"]) <= 1e-8
        or abs(start["y"] - end["y"]) <= 1e-8
        for start, end in _segments(points)
    )


def _route_intersects_obstacles(
    points: Sequence[Mapping[str, float]],
    obstacles: Sequence[Mapping[str, Any]],
) -> bool:
    path_bounds = _point_bounds(points)
    for obstacle in obstacles:
        rectangle = obstacle["rect"]
        if _rect_intersection(_expanded_rect(path_bounds, 1e-7), rectangle) is None:
            continue
        if _polyline_intersects_rect(points, rectangle):
            return True
    return False


def _select_route_lanes(values: Iterable[float], midpoint: float, limit: int = 32) -> list[float]:
    unique = sorted({_rounded(float(value)) for value in values})
    if len(unique) <= limit:
        return unique
    chosen = {unique[0], unique[-1]}
    for value in sorted(unique, key=lambda item: (abs(item - midpoint), item)):
        chosen.add(value)
        if len(chosen) >= limit:
            break
    return sorted(chosen)


def _route_bend_count(points: Sequence[Mapping[str, float]]) -> int:
    bends = 0
    for index in range(1, len(points) - 1):
        left = points[index - 1]
        middle = points[index]
        right = points[index + 1]
        left_horizontal = abs(left["y"] - middle["y"]) <= 1e-8
        right_horizontal = abs(middle["y"] - right["y"]) <= 1e-8
        if left_horizontal != right_horizontal:
            bends += 1
    return bends


def _prepare_route_crossings(
    scene: Mapping[str, Any],
    routed_edge: Mapping[str, Any],
    node_by_id: Mapping[str, Mapping[str, Any]],
    sampling_segments: int,
    cell_size: float,
) -> Tuple[_SpatialGridIndex, Dict[str, Tuple[str, Mapping[str, float], Mapping[str, float]]]]:
    endpoint_ids = {
        str(routed_edge.get("fromNodeId") or ""),
        str(routed_edge.get("toNodeId") or ""),
    }
    index = _SpatialGridIndex(cell_size)
    records: Dict[str, Tuple[str, Mapping[str, float], Mapping[str, float]]] = {}
    for other in scene.get("edges") or []:
        if other.get("edgeId") == routed_edge.get("edgeId"):
            continue
        other_endpoints = {
            str(other.get("fromNodeId") or ""),
            str(other.get("toNodeId") or ""),
        }
        if endpoint_ids & other_endpoints:
            continue
        other_points = _edge_path_points(other, node_by_id, sampling_segments)
        if len(other_points) < 2:
            continue
        for segment_index, bounded in enumerate(_bounded_segments(other_points)):
            start, end, minimum_x, minimum_y, maximum_x, maximum_y = bounded
            record_id = f"{str(other.get('edgeId') or '')}:{segment_index}"
            records[record_id] = (str(other.get("edgeId") or ""), start, end)
            index.insert(
                record_id,
                _expanded_rect(
                    {
                        "x": minimum_x,
                        "y": minimum_y,
                        "width": maximum_x - minimum_x,
                        "height": maximum_y - minimum_y,
                    },
                    1e-7,
                ),
            )
    return index, records


def _route_crossing_count(
    points: Sequence[Mapping[str, float]],
    prepared: Tuple[
        _SpatialGridIndex,
        Mapping[str, Tuple[str, Mapping[str, float], Mapping[str, float]]],
    ],
) -> int:
    index, records = prepared
    crossed_edges: set[str] = set()
    for bounded in _bounded_segments(points):
        start, end, minimum_x, minimum_y, maximum_x, maximum_y = bounded
        bounds = _expanded_rect(
            {
                "x": minimum_x,
                "y": minimum_y,
                "width": maximum_x - minimum_x,
                "height": maximum_y - minimum_y,
            },
            1e-7,
        )
        for record_id in index.query(bounds):
            record = records.get(record_id)
            if record is None or record[0] in crossed_edges:
                continue
            if _segment_crossing(start, end, record[1], record[2]) is not None:
                crossed_edges.add(record[0])
    return len(crossed_edges)


def route_orthogonal_edge(
    scene: Mapping[str, Any],
    edge_id: str,
    *,
    contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return one deterministic obstacle-aware route without mutating the map."""

    if not isinstance(scene, Mapping) or scene.get("spatialVersion") != PROCESS_MAP_SPATIAL_VERSION:
        raise SpatialGeometryError("scene has an unsupported spatial version")
    active_contract = _spatial_contract_for_scene(scene, contract)
    policy = active_contract["layoutPolicyDefaults"]
    geometry = active_contract["geometry"]
    edge = next(
        (item for item in scene.get("edges") or [] if item.get("edgeId") == edge_id),
        None,
    )
    if edge is None:
        raise SpatialGeometryError(f"unknown edge '{edge_id}'")
    node_by_id = {
        str(node.get("nodeId") or ""): node for node in scene.get("nodes") or []
    }
    source = node_by_id.get(str(edge.get("fromNodeId") or ""))
    target = node_by_id.get(str(edge.get("toNodeId") or ""))
    if source is None or target is None:
        raise SpatialGeometryError(f"edge '{edge_id}' has a dangling endpoint")

    start_port = source["ports"]["output"]
    end_port = target["ports"]["input"]
    start = {"x": float(start_port["x"]), "y": float(start_port["y"])}
    end = {"x": float(end_port["x"]), "y": float(end_port["y"])}
    lead_length = float(policy["portLeadLength"])
    start_direction = start_port["direction"]
    end_direction = end_port["direction"]
    start_lead = {
        "x": start["x"] + float(start_direction["x"]) * lead_length,
        "y": start["y"] + float(start_direction["y"]) * lead_length,
    }
    end_lead = {
        "x": end["x"] + float(end_direction["x"]) * lead_length,
        "y": end["y"] + float(end_direction["y"]) * lead_length,
    }

    clearance = float(policy["edgeClearance"])
    endpoint_ids = {source["nodeId"], target["nodeId"]}
    obstacles: list[Dict[str, Any]] = []
    for node in _sorted_records(scene.get("nodes") or [], "nodeId"):
        if node.get("nodeId") in endpoint_ids:
            continue
        obstacles.append(
            {"id": f"node:{node['nodeId']}", "rect": _expanded_rect(node["rect"], clearance)}
        )
    for group in _sorted_records(scene.get("groups") or [], "groupId"):
        obstacles.append(
            {
                "id": f"group-header:{group['groupId']}",
                "rect": _expanded_rect(group["headerRect"], clearance),
            }
        )

    world = scene.get("worldBounds") or _point_bounds((start, end))
    grid = float(policy["gridSize"])
    lane_offset = 1.0
    x_values = [
        start_lead["x"],
        end_lead["x"],
        float(world["x"]) - clearance - grid,
        float(world["x"]) + float(world["width"]) + clearance + grid,
    ]
    y_values = [
        start_lead["y"],
        end_lead["y"],
        float(world["y"]) - clearance - grid,
        float(world["y"]) + float(world["height"]) + clearance + grid,
    ]
    for obstacle in obstacles:
        rectangle = obstacle["rect"]
        x_values.extend((rectangle["x"] - lane_offset, rectangle["x"] + rectangle["width"] + lane_offset))
        y_values.extend((rectangle["y"] - lane_offset, rectangle["y"] + rectangle["height"] + lane_offset))
    midpoint_x = (start_lead["x"] + end_lead["x"]) / 2.0
    midpoint_y = (start_lead["y"] + end_lead["y"]) / 2.0
    x_lanes = _select_route_lanes(x_values, midpoint_x)
    y_lanes = _select_route_lanes(y_values, midpoint_y)

    middle_candidates: list[list[Dict[str, float]]] = [
        [start_lead, end_lead],
        [start_lead, {"x": end_lead["x"], "y": start_lead["y"]}, end_lead],
        [start_lead, {"x": start_lead["x"], "y": end_lead["y"]}, end_lead],
    ]
    middle_candidates.extend(
        [
            start_lead,
            {"x": lane, "y": start_lead["y"]},
            {"x": lane, "y": end_lead["y"]},
            end_lead,
        ]
        for lane in x_lanes
    )
    middle_candidates.extend(
        [
            start_lead,
            {"x": start_lead["x"], "y": lane},
            {"x": end_lead["x"], "y": lane},
            end_lead,
        ]
        for lane in y_lanes
    )
    near_x = sorted(x_lanes, key=lambda value: (abs(value - midpoint_x), value))[:8]
    near_y = sorted(y_lanes, key=lambda value: (abs(value - midpoint_y), value))[:8]
    for x_lane in near_x:
        for y_lane in near_y:
            middle_candidates.append(
                [
                    start_lead,
                    {"x": x_lane, "y": start_lead["y"]},
                    {"x": x_lane, "y": y_lane},
                    {"x": end_lead["x"], "y": y_lane},
                    end_lead,
                ]
            )
            middle_candidates.append(
                [
                    start_lead,
                    {"x": start_lead["x"], "y": y_lane},
                    {"x": x_lane, "y": y_lane},
                    {"x": x_lane, "y": end_lead["y"]},
                    end_lead,
                ]
            )

    sampling_segments = int(geometry["legacyBezierSamplingSegments"])
    crossing_data = _prepare_route_crossings(
        scene,
        edge,
        node_by_id,
        sampling_segments,
        max(grid * 8.0, 160.0),
    )
    seen: set[bytes] = set()
    ranked: list[Tuple[Tuple[Any, ...], list[Dict[str, float]], Dict[str, Any]]] = []
    for middle in middle_candidates:
        points = _normalize_orthogonal_points([start, *middle, end])
        if len(points) < 2 or not _orthogonal_path(points):
            continue
        identity = _canonical_bytes(points)
        if identity in seen:
            continue
        seen.add(identity)
        if _route_intersects_obstacles(points, obstacles):
            continue
        crossings = _route_crossing_count(points, crossing_data)
        bends = _route_bend_count(points)
        length = _rounded(_polyline_length(points))
        point_key = identity.decode("ascii")
        ranked.append(((crossings, bends, length, point_key), points, {
            "crossings": crossings,
            "bends": bends,
            "length": length,
        }))

    obstacle_fingerprint = _route_obstacle_fingerprint(scene, edge_id)
    result_base = {
        "routerVersion": PROCESS_MAP_ROUTER_VERSION,
        "edgeId": edge_id,
        "mode": "orthogonal_auto",
        "obstacleFingerprint": obstacle_fingerprint,
        "evaluatedCount": len(seen),
    }
    if not ranked:
        return {
            **result_base,
            "accepted": False,
            "failureReason": "no_obstacle_free_orthogonal_route",
            "points": [],
            "waypoints": [],
        }
    ranked.sort(key=lambda item: item[0])
    _, points, metrics = ranked[0]
    route_id = _fnv1a64_hex(
        _canonical_bytes({"edgeId": edge_id, "obstacles": obstacle_fingerprint, "points": points})
    )
    return {
        **result_base,
        "accepted": True,
        "failureReason": None,
        "routeId": route_id,
        "points": points,
        "waypoints": points[1:-1],
        "bounds": _point_bounds(points),
        "metrics": metrics,
    }


def _suggested_node_id(suggestion_id: str) -> str:
    suffix = suggestion_id.removeprefix("pms-")[:20]
    return f"pm-node-suggest-{suffix or 'target'}"


def _spatial_proposal(
    suggestion: Mapping[str, Any],
    *,
    edge: Mapping[str, Any],
    route: Mapping[str, Any],
    placement: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    suggestion_id = str(suggestion.get("suggestionId") or "")
    evidence_fingerprint = str(suggestion.get("evidenceFingerprint") or "")
    identity = {
        "proposalVersion": PROCESS_MAP_SPATIAL_PROPOSAL_VERSION,
        "semanticSuggestionId": suggestion_id,
        "semanticEvidenceFingerprint": evidence_fingerprint,
        "edge": edge,
        "routeId": route.get("routeId"),
        "obstacleFingerprint": route.get("obstacleFingerprint"),
        "placement": placement,
    }
    proposal_id = "pm-sp-" + _fnv1a64_hex(_canonical_bytes(identity))
    proposal: Dict[str, Any] = {
        "proposalVersion": PROCESS_MAP_SPATIAL_PROPOSAL_VERSION,
        "proposalId": proposal_id,
        "semanticSuggestionId": suggestion_id,
        "semanticEvidenceFingerprint": evidence_fingerprint,
        "spatialEngineVersion": PROCESS_MAP_SPATIAL_VERSION,
        "routerVersion": PROCESS_MAP_ROUTER_VERSION,
        "accepted": bool(route.get("accepted")),
        "failureReason": route.get("failureReason"),
        "obstacleFingerprint": route.get("obstacleFingerprint"),
        "edge": deepcopy(dict(edge)),
        "route": {
            "routeId": route.get("routeId"),
            "mode": route.get("mode"),
            "points": deepcopy(list(route.get("points") or [])),
            "waypoints": deepcopy(list(route.get("waypoints") or [])),
            "bounds": deepcopy(route.get("bounds")),
            "metrics": deepcopy(route.get("metrics")),
        },
    }
    if placement is not None:
        proposal["placement"] = deepcopy(dict(placement))
    return proposal


def _append_suggestion_edge(
    process_map: Mapping[str, Any], edge: Mapping[str, Any]
) -> Dict[str, Any]:
    next_map = deepcopy(dict(process_map))
    edges = next_map.setdefault("canvasEdges", [])
    if not isinstance(edges, list):
        raise SpatialGeometryError("canvasEdges must be an array")
    edges.append(deepcopy(dict(edge)))
    return next_map


def spatialize_semantic_suggestions(
    process_map: Mapping[str, Any],
    suggestions: Sequence[Mapping[str, Any]],
    *,
    contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach non-authoritative geometry to evidence-backed suggestions.

    Semantic suggestion IDs and evidence remain untouched. Every geometry
    proposal is independently reproducible from the current map and can be
    discarded without changing dismissal identity or authored topology.
    """

    active_contract = spatial_contract_for_process_map(process_map, contract)
    original = deepcopy(dict(process_map))
    node_ids = {
        str(node.get("nodeId") or "")
        for node in original.get("canvasNodes") or []
        if isinstance(node, Mapping)
    }
    result: list[Dict[str, Any]] = []
    routed = 0
    placed = 0
    unavailable = 0

    for raw in suggestions:
        suggestion = deepcopy(dict(raw))
        suggestion.pop("spatialProposal", None)
        if suggestion.get("validation", {}).get("wouldCreateCycle"):
            result.append(suggestion)
            continue

        edge = suggestion.get("edge")
        placement_request = suggestion.get("placement")
        placement: Optional[Dict[str, Any]] = None
        transient = original

        if isinstance(placement_request, Mapping):
            anchor_id = str(placement_request.get("anchorNodeId") or "")
            occurrence_id = str(placement_request.get("sourceOccurrenceId") or "")
            direction = str(placement_request.get("connectionDirection") or "outgoing")
            if not anchor_id or anchor_id not in node_ids or not occurrence_id:
                result.append(suggestion)
                unavailable += 1
                continue
            scene = compile_spatial_scene(original, contract=active_contract)
            candidates = generate_placement_candidates(
                scene,
                target_kind="product_occurrence",
                anchor_node_id=anchor_id,
                connection_direction=direction,
                contract=active_contract,
                limit=1,
            )
            if not candidates["candidates"]:
                result.append(suggestion)
                unavailable += 1
                continue
            candidate = candidates["candidates"][0]
            node_id = str(placement_request.get("nodeId") or _suggested_node_id(
                str(suggestion.get("suggestionId") or "")
            ))
            if node_id in node_ids:
                result.append(suggestion)
                unavailable += 1
                continue
            node = {
                "nodeId": node_id,
                "nodeKind": "product_occurrence",
                "sourceOccurrenceId": occurrence_id,
                "nameSnapshot": str(placement_request.get("nameSnapshot") or occurrence_id),
                "itemIdSnapshot": placement_request.get("itemIdSnapshot"),
                "position": deepcopy(candidate["position"]),
                "portOrientation": candidate["portOrientation"],
                "portOrder": candidate["portOrder"],
            }
            transient = deepcopy(original)
            transient.setdefault("canvasNodes", []).append(node)
            edge_id = str(
                placement_request.get("edgeId")
                or f"pm-e-suggest-{str(suggestion.get('suggestionId') or '')[4:20]}"
            )
            if direction == "incoming":
                from_id, to_id = node_id, anchor_id
            else:
                from_id, to_id = anchor_id, node_id
            edge = {
                "edgeId": edge_id,
                "from": {"nodeId": from_id, "port": "out"},
                "to": {"nodeId": to_id, "port": "in"},
                "kind": str(placement_request.get("edgeKind") or "precedence"),
                "logicalConnectionId": edge_id,
            }
            placement = {
                "node": node,
                "candidateId": candidate["candidateId"],
                "obstacleFingerprint": candidates["obstacleFingerprint"],
                "metricsAfter": deepcopy(candidate.get("metricsAfter") or {}),
            }
            placed += 1

        if not isinstance(edge, Mapping):
            result.append(suggestion)
            continue
        from_value = edge.get("from")
        to_value = edge.get("to")
        from_id = str(from_value.get("nodeId") or "") if isinstance(from_value, Mapping) else ""
        to_id = str(to_value.get("nodeId") or "") if isinstance(to_value, Mapping) else ""
        transient_node_ids = {
            str(node.get("nodeId") or "")
            for node in transient.get("canvasNodes") or []
            if isinstance(node, Mapping)
        }
        if not from_id or not to_id or from_id not in transient_node_ids or to_id not in transient_node_ids:
            result.append(suggestion)
            unavailable += 1
            continue
        transient = _append_suggestion_edge(transient, edge)
        try:
            scene = compile_spatial_scene(transient, contract=active_contract)
            route = route_orthogonal_edge(
                scene,
                str(edge.get("edgeId") or ""),
                contract=active_contract,
            )
        except SpatialGeometryError:
            result.append(suggestion)
            unavailable += 1
            continue
        proposal = _spatial_proposal(
            suggestion,
            edge=edge,
            route=route,
            placement=placement,
        )
        suggestion["spatialProposal"] = proposal
        if proposal["accepted"]:
            routed += 1
        else:
            unavailable += 1
        result.append(suggestion)

    return {
        "proposalVersion": PROCESS_MAP_SPATIAL_PROPOSAL_VERSION,
        "suggestions": result,
        "summary": {
            "spatialized": routed,
            "placementProposals": placed,
            "unavailable": unavailable,
        },
    }


def apply_orthogonal_route(
    process_map: Mapping[str, Any],
    edge_id: str,
    *,
    contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Apply a freshly generated route to a cloned map."""

    active_contract = spatial_contract_for_process_map(process_map, contract)
    scene = compile_spatial_scene(process_map, contract=active_contract)
    proposal = route_orthogonal_edge(scene, edge_id, contract=active_contract)
    next_map = deepcopy(dict(process_map))
    if not proposal["accepted"]:
        return {"map": next_map, "route": proposal, "accepted": False}
    matched = False
    for edge in next_map.get("canvasEdges") or []:
        if isinstance(edge, dict) and edge.get("edgeId") == edge_id:
            edge["routing"] = {
                "mode": "orthogonal_auto",
                "routerVersion": PROCESS_MAP_ROUTER_VERSION,
                "waypoints": deepcopy(proposal["waypoints"]),
                "obstacleFingerprint": proposal["obstacleFingerprint"],
            }
            matched = True
            break
    if not matched:
        raise SpatialGeometryError(f"unknown edge '{edge_id}'")
    layout_version = next_map.get("layoutVersion")
    next_map["layoutVersion"] = max(
        3,
        layout_version if isinstance(layout_version, int) and not isinstance(layout_version, bool) else 0,
    )
    return {"map": next_map, "route": proposal, "accepted": True}


def refresh_orthogonal_auto_routes(
    process_map: Mapping[str, Any],
    *,
    contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Recompute every accepted auto route in stable edge-id order."""

    active_contract = spatial_contract_for_process_map(process_map, contract)
    next_map = deepcopy(dict(process_map))
    failures = []
    edge_ids = sorted(
        str(edge.get("edgeId"))
        for edge in next_map.get("canvasEdges") or []
        if isinstance(edge, Mapping)
        and isinstance(edge.get("routing"), Mapping)
        and edge["routing"].get("mode") == "orthogonal_auto"
        and edge.get("edgeId")
    )
    scene = compile_spatial_scene(next_map, contract=active_contract)
    proposals = {
        edge_id: route_orthogonal_edge(scene, edge_id, contract=active_contract)
        for edge_id in edge_ids
    }
    edge_by_id = {
        str(edge.get("edgeId")): edge
        for edge in next_map.get("canvasEdges") or []
        if isinstance(edge, dict) and edge.get("edgeId")
    }
    for edge_id in edge_ids:
        proposal = proposals[edge_id]
        if not proposal["accepted"]:
            failures.append(
                {"edgeId": edge_id, "failureReason": proposal["failureReason"]}
            )
            continue
        edge_by_id[edge_id]["routing"] = {
            "mode": "orthogonal_auto",
            "routerVersion": PROCESS_MAP_ROUTER_VERSION,
            "waypoints": deepcopy(proposal["waypoints"]),
            "obstacleFingerprint": proposal["obstacleFingerprint"],
        }
    if edge_ids:
        next_map["layoutVersion"] = max(
            3,
            next_map.get("layoutVersion")
            if isinstance(next_map.get("layoutVersion"), int)
            and not isinstance(next_map.get("layoutVersion"), bool)
            else 0,
        )
    return {"map": next_map, "failures": failures}


_FLOW_AXES = {
    "left_to_right": ({"x": 1.0, "y": 0.0}, {"x": 0.0, "y": 1.0}),
    "right_to_left": ({"x": -1.0, "y": 0.0}, {"x": 0.0, "y": 1.0}),
    "top_to_bottom": ({"x": 0.0, "y": 1.0}, {"x": 1.0, "y": 0.0}),
    "bottom_to_top": ({"x": 0.0, "y": -1.0}, {"x": 1.0, "y": 0.0}),
}


def _flow_axes(direction: str) -> Tuple[Dict[str, float], Dict[str, float]]:
    return _FLOW_AXES.get(direction, _FLOW_AXES["left_to_right"])


def _rounded_coarse(value: float) -> float:
    """Ranking-key rounding, coarser than the reported-value rounding.

    Two of the score terms that feed this (route length, via the
    pre-existing _polyline_length/_legacy_bezier_controls path, and
    clearance, via the pre-existing _rect_distance path) depend on
    math.hypot(), whose exact low-order bits are implementation-defined
    and can differ by roughly 1e-6 from JavaScript's Math.hypot() for the
    same inputs. Comparing at 3 decimals instead of 6 for ranking absorbs
    that noise -- geometry in this application is never engineered to
    depend on sub-millimeter tie-breaks -- while the reported score value
    keeps full 6-decimal precision.
    """

    rounded = float(f"{float(value):.3f}")
    return 0.0 if rounded == 0 else rounded


def _snap(value: float, grid: float) -> float:
    # Explicit round-half-away-from-zero: Python's round() uses banker's
    # rounding (round-half-to-even) while JavaScript's Math.round() rounds
    # half toward positive infinity. The two diverge exactly at .5
    # boundaries, which grid snapping hits constantly, so both languages
    # implement this same explicit rule instead of relying on native round().
    scaled = value / grid
    magnitude = math.floor(abs(scaled) + 0.5)
    snapped = magnitude if scaled >= 0 else -magnitude
    return _rounded(snapped * grid)


def _candidate_id(prefix: str, lane: int, row: int, orientation: str, order: str) -> str:
    return f"cand-{prefix}-L{lane}-R{row}-{orientation[:1]}-{order[:1]}"


def _ring_offsets(max_ring: int) -> List[Tuple[int, int]]:
    """Deterministic (lane, row) offsets expanding outward, forward-biased."""

    seen: set[Tuple[int, int]] = set()
    ordered: List[Tuple[int, int]] = []
    for ring in range(max_ring + 1):
        candidates = []
        for row in range(-ring, ring + 1):
            for lane in range(-ring, ring + 1):
                if max(abs(lane), abs(row)) != ring:
                    continue
                candidates.append((lane, row))
        candidates.sort(key=lambda item: (abs(item[1]), -item[0], item[0], item[1]))
        for item in candidates:
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
    return ordered


def _least_dense_region_point(
    scene: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> Dict[str, float]:
    world_bounds = scene.get("worldBounds") or {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
    if not (world_bounds["width"] > 0 and world_bounds["height"] > 0):
        return {"x": 0.0, "y": 0.0}
    diagnostics_policy = contract["diagnostics"]
    columns = max(1, int(diagnostics_policy["regionColumns"]))
    rows = max(1, int(diagnostics_policy["regionRows"]))
    region_width = world_bounds["width"] / columns
    region_height = world_bounds["height"] / rows
    dense_threshold = float(diagnostics_policy["denseOccupancyThreshold"])
    authored_nodes = [
        node for node in scene.get("nodes") or [] if node.get("kind") != "junction"
    ]
    ranked = []
    for row in range(rows):
        for column in range(columns):
            region_rect = {
                "x": world_bounds["x"] + column * region_width,
                "y": world_bounds["y"] + row * region_height,
                "width": region_width,
                "height": region_height,
            }
            occupied_area = 0.0
            intersecting_count = 0
            for node in authored_nodes:
                overlap = _rect_intersection(region_rect, node["rect"])
                if overlap is None:
                    continue
                intersecting_count += 1
                occupied_area += overlap["width"] * overlap["height"]
            area = max(region_width * region_height, 1.0)
            occupancy = _rounded(min(1.0, occupied_area / area))
            classification_rank = (
                0
                if intersecting_count == 0
                else (2 if occupancy >= dense_threshold or intersecting_count >= 3 else 1)
            )
            ranked.append(
                (
                    classification_rank,
                    occupancy,
                    f"region-r{row + 1}-c{column + 1}",
                    {
                        "x": region_rect["x"] + region_width / 2.0,
                        "y": region_rect["y"] + region_height / 2.0,
                    },
                )
            )
    ranked.sort(key=lambda item: item[:3])
    return ranked[0][3]


def _least_dense_visible_region_point(
    scene: Mapping[str, Any],
    visible_world_rect: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> Dict[str, float]:
    """Choose a deterministic open cell inside the user's visible world rect."""

    visible = _rect(visible_world_rect, "visibleWorldRect")
    columns = max(1, int(contract["diagnostics"]["regionColumns"]))
    rows = max(1, int(contract["diagnostics"]["regionRows"]))
    cell_width = visible["width"] / columns
    cell_height = visible["height"] / rows
    authored_centers = [
        node["center"] for node in scene.get("nodes") or [] if node.get("kind") != "junction"
    ]
    ranked = []
    for row in range(rows):
        for column in range(columns):
            left = visible["x"] + column * cell_width
            top = visible["y"] + row * cell_height
            right = left + cell_width
            bottom = top + cell_height
            occupancy = sum(
                1
                for center in authored_centers
                if center["x"] >= left
                and center["x"] <= right
                and center["y"] >= top
                and center["y"] <= bottom
            )
            ranked.append(
                (
                    occupancy,
                    row,
                    column,
                    {
                        "x": left + cell_width / 2.0,
                        "y": top + cell_height / 2.0,
                    },
                )
            )
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return ranked[0][3]


def _candidate_compiled_node(
    source: Mapping[str, Any],
    rectangle: Mapping[str, float],
    orientation: str,
    order: str,
) -> Dict[str, Any]:
    compiled = deepcopy(dict(source))
    rect = dict(rectangle)
    center = {
        "x": rect["x"] + rect["width"] / 2.0,
        "y": rect["y"] + rect["height"] / 2.0,
    }
    input_anchor = _port_anchor(rect, orientation, order, "in")
    output_anchor = _port_anchor(rect, orientation, order, "out")
    compiled.update(
        {
            "rect": rect,
            "center": center,
            "portOrientation": orientation,
            "portOrder": order,
            "ports": {
                "input": {
                    **input_anchor,
                    "direction": _port_direction(orientation, order, "in"),
                },
                "output": {
                    **output_anchor,
                    "direction": _port_direction(orientation, order, "out"),
                },
            },
        }
    )
    return compiled


def _edge_with_candidate_endpoints(
    edge: Mapping[str, Any],
    node_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    source = node_by_id[str(edge.get("fromNodeId") or "")]
    target = node_by_id[str(edge.get("toNodeId") or "")]
    start = deepcopy(source["ports"]["output"])
    end = deepcopy(target["ports"]["input"])
    start.pop("direction", None)
    end.pop("direction", None)
    updated = deepcopy(dict(edge))
    existing = [dict(point) for point in edge.get("points") or []]
    updated["points"] = [start, *existing[1:-1], end] if len(existing) >= 2 else [start, end]
    return updated


def generate_placement_candidates(
    scene: Mapping[str, Any],
    *,
    target_kind: str,
    target_node_id: Optional[str] = None,
    anchor_node_id: Optional[str] = None,
    connection_direction: Optional[str] = None,
    required_group_id: Optional[str] = None,
    preferred_flow_direction: str = "left_to_right",
    visible_world_rect: Optional[Mapping[str, Any]] = None,
    contract: Optional[Mapping[str, Any]] = None,
    limit: int = 3,
) -> Dict[str, Any]:
    """Return deterministic, ranked, non-mutating placement candidates."""

    if not isinstance(scene, Mapping) or scene.get("spatialVersion") != PROCESS_MAP_SPATIAL_VERSION:
        raise SpatialGeometryError("scene has an unsupported spatial version")
    active_contract = _spatial_contract_for_scene(scene, contract)
    geometry = active_contract["geometry"]
    policy = active_contract["layoutPolicyDefaults"]
    limits = active_contract["limits"]
    envelopes = geometry["nodeEnvelopes"]

    nodes = list(scene.get("nodes") or [])
    node_by_id = {str(node.get("nodeId") or ""): node for node in nodes}
    authored_by_id = {
        node_id: node for node_id, node in node_by_id.items() if node.get("kind") != "junction"
    }
    groups = {str(group.get("groupId") or ""): group for group in scene.get("groups") or []}
    edges = list(scene.get("edges") or [])

    safe_limit = max(1, min(int(limit), 3))
    max_evaluated = min(int(limits["maximumCandidates"]), 96)
    fingerprint = _obstacle_fingerprint(scene)
    rejection_counts: Dict[str, int] = {}

    def reject(code: str) -> None:
        rejection_counts[code] = rejection_counts.get(code, 0) + 1

    result_base = {
        "spatialEngineVersion": PROCESS_MAP_SPATIAL_VERSION,
        "candidatePolicyVersion": PROCESS_MAP_CANDIDATE_POLICY_VERSION,
        "identity": deepcopy(dict(scene.get("identity") or {})),
        "obstacleFingerprint": fingerprint,
        "target": {"kind": target_kind, "nodeId": target_node_id},
        "anchorNodeId": anchor_node_id,
        "requiredGroupId": required_group_id,
    }

    if target_kind not in envelopes and target_kind != "default":
        return {**result_base, "candidates": [], "evaluatedCount": 0, "rejectionCounts": {"invalid_geometry": 1}}

    moving_node = None
    if target_node_id is not None:
        moving_node = node_by_id.get(target_node_id)
        if moving_node is None or moving_node.get("kind") == "junction":
            return {**result_base, "candidates": [], "evaluatedCount": 0, "rejectionCounts": {"invalid_topology": 1}}
        if moving_node.get("positionMode") == "locked" or moving_node.get("locked") is True:
            return {**result_base, "candidates": [], "evaluatedCount": 0, "rejectionCounts": {"locked_node_movement": 1}}

    anchor = node_by_id.get(anchor_node_id) if anchor_node_id else None
    if anchor_node_id and anchor is None:
        return {**result_base, "candidates": [], "evaluatedCount": 0, "rejectionCounts": {"invalid_topology": 1}}
    if anchor is not None and target_node_id is not None and anchor_node_id == target_node_id:
        return {**result_base, "candidates": [], "evaluatedCount": 0, "rejectionCounts": {"invalid_topology": 1}}

    if required_group_id is not None and required_group_id not in groups:
        return {**result_base, "candidates": [], "evaluatedCount": 0, "rejectionCounts": {"group_containment_violation": 1}}

    envelope = envelopes.get(target_kind, envelopes["default"])
    width = float(envelope["width"])
    height = float(envelope["height"])
    if not (_positive_number(width) and _positive_number(height)):
        return {**result_base, "candidates": [], "evaluatedCount": 0, "rejectionCounts": {"invalid_geometry": 1}}

    node_clearance = float(policy["nodeClearance"])
    grid_size = float(policy["gridSize"])
    flow_direction = preferred_flow_direction if preferred_flow_direction in _FLOW_AXES else "left_to_right"
    forward, perpendicular = _flow_axes(flow_direction)
    horizontal_flow = abs(forward["x"]) == 1.0
    lane_step = (width if horizontal_flow else height) + node_clearance
    row_step = (height if horizontal_flow else width) + node_clearance

    if anchor is not None:
        origin = anchor["center"]
        origin_kind = "anchor"
    else:
        origin = (
            _least_dense_visible_region_point(scene, visible_world_rect, active_contract)
            if visible_world_rect is not None
            else _least_dense_region_point(scene, active_contract)
        )
        origin_kind = "region"

    broad_phase_size = max(grid_size * 8.0, width, height)
    obstacle_index = _SpatialGridIndex(broad_phase_size)
    for node_id, node in authored_by_id.items():
        if target_node_id is not None and node_id == target_node_id:
            continue
        obstacle_index.insert(node_id, node["rect"])

    header_rects = [(group_id, group["headerRect"]) for group_id, group in groups.items()]
    edge_index = _SpatialGridIndex(broad_phase_size)
    sampling_segments = int(geometry["legacyBezierSamplingSegments"])
    sampled_edges = []
    for edge in edges:
        if target_node_id is not None and (
            edge.get("fromNodeId") == target_node_id or edge.get("toNodeId") == target_node_id
        ):
            continue
        points = _edge_path_points(edge, node_by_id, sampling_segments)
        bounds = _point_bounds(points)
        edge_id = str(edge.get("edgeId") or "")
        sampled_edges.append({"edge": edge, "edgeId": edge_id, "points": points, "bounds": bounds})
        edge_index.insert(edge_id, bounds)
    sampled_by_edge_id = {item["edgeId"]: item for item in sampled_edges}

    precedence_adjacency: Dict[str, set] = {}
    for edge in edges:
        if edge.get("kind") != "precedence":
            continue
        precedence_adjacency.setdefault(str(edge.get("fromNodeId") or ""), set()).add(
            str(edge.get("toNodeId") or "")
        )

    def would_create_cycle(from_id: str, to_id: str) -> bool:
        if from_id == to_id:
            return True
        stack = [to_id]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == from_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(precedence_adjacency.get(current, ()))
        return False

    existing_precedence_pairs = {
        (edge.get("fromNodeId"), edge.get("toNodeId"))
        for edge in edges
        if edge.get("kind") == "precedence"
    }

    orientation_orders = (
        ("horizontal", "input_first"),
        ("horizontal", "output_first"),
        ("vertical", "input_first"),
        ("vertical", "output_first"),
    )

    evaluated = 0
    scored: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    for lane, row in _ring_offsets(4):
        if evaluated >= max_evaluated:
            break
        center = {
            "x": origin["x"] + lane * lane_step * forward["x"] + row * row_step * perpendicular["x"],
            "y": origin["y"] + lane * lane_step * forward["y"] + row * row_step * perpendicular["y"],
        }
        for orientation, order in orientation_orders:
            if evaluated >= max_evaluated:
                break
            evaluated += 1
            rect = {
                "x": _snap(center["x"] - width / 2.0, grid_size),
                "y": _snap(center["y"] - height / 2.0, grid_size),
                "width": width,
                "height": height,
            }
            if not (
                _finite_number(rect["x"]) and _finite_number(rect["y"])
                and math.isfinite(rect["x"]) and math.isfinite(rect["y"])
            ):
                reject("invalid_geometry")
                continue

            overlap_found = False
            clearance_ok = True
            minimum_clearance = None
            for other_id in obstacle_index.query(_expanded_rect(rect, node_clearance)):
                other = authored_by_id[other_id]
                if _rect_intersection(rect, other["rect"]) is not None:
                    overlap_found = True
                    break
                distance = _rect_distance(rect, other["rect"])
                minimum_clearance = distance if minimum_clearance is None else min(minimum_clearance, distance)
                if distance < node_clearance:
                    clearance_ok = False
            if overlap_found:
                reject("node_overlap")
                continue
            if not clearance_ok:
                reject("insufficient_node_clearance")
                continue

            if required_group_id is not None:
                group_rect = groups[required_group_id]["rect"]
                if not (
                    rect["x"] >= group_rect["x"]
                    and rect["y"] >= group_rect["y"]
                    and rect["x"] + rect["width"] <= group_rect["x"] + group_rect["width"]
                    and rect["y"] + rect["height"] <= group_rect["y"] + group_rect["height"]
                ):
                    reject("group_containment_violation")
                    continue

            header_hit = False
            for _group_id, header_rect in header_rects:
                if _rect_intersection(rect, header_rect) is not None:
                    header_hit = True
                    break
            if header_hit:
                reject("group_header_intersection")
                continue

            input_anchor = _port_anchor(rect, orientation, order, "in")
            output_anchor = _port_anchor(rect, orientation, order, "out")

            candidate_incident_routes = []
            incident_blocked = False
            if moving_node is not None:
                candidate_nodes = dict(node_by_id)
                candidate_nodes[target_node_id] = _candidate_compiled_node(
                    moving_node, rect, orientation, order
                )
                for edge in edges:
                    if target_node_id not in (edge.get("fromNodeId"), edge.get("toNodeId")):
                        continue
                    candidate_edge = _edge_with_candidate_endpoints(edge, candidate_nodes)
                    points = _edge_path_points(candidate_edge, candidate_nodes, sampling_segments)
                    bounds = _point_bounds(points)
                    endpoint_ids = {
                        str(edge.get("fromNodeId") or ""),
                        str(edge.get("toNodeId") or ""),
                    }
                    for other_id in obstacle_index.query(bounds):
                        if other_id in endpoint_ids:
                            continue
                        if _polyline_intersects_rect(points, authored_by_id[other_id]["rect"]):
                            incident_blocked = True
                            break
                    if incident_blocked:
                        break
                    candidate_incident_routes.append(
                        {
                            "points": points,
                            "bounds": bounds,
                            "endpointIds": endpoint_ids,
                        }
                    )
            if incident_blocked:
                reject("edge_node_intersection")
                continue

            requested_edge_points = None
            requested_bounds = None
            if anchor is not None and connection_direction in ("outgoing", "incoming"):
                if connection_direction == "outgoing":
                    from_id, to_id = anchor_node_id, (target_node_id or "__candidate__")
                    start = dict(anchor["ports"]["output"])
                    start_direction = start.pop("direction")
                    end = dict(input_anchor)
                    end_direction = _port_direction(orientation, order, "in")
                else:
                    from_id, to_id = (target_node_id or "__candidate__"), anchor_node_id
                    start = dict(output_anchor)
                    start_direction = _port_direction(orientation, order, "out")
                    end = dict(anchor["ports"]["input"])
                    end_direction = end.pop("direction")

                if from_id == to_id:
                    reject("invalid_topology")
                    continue
                if (from_id, to_id) in existing_precedence_pairs:
                    reject("duplicate_connection")
                    continue
                if would_create_cycle(from_id, to_id):
                    reject("precedence_cycle")
                    continue

                first, second = _legacy_bezier_controls(start, end, start_direction, end_direction)
                requested_edge_points = _sample_cubic_bezier(start, first, second, end, sampling_segments)
                requested_bounds = _point_bounds(requested_edge_points)
                blocked = False
                for other_id in obstacle_index.query(requested_bounds):
                    if other_id == anchor_node_id:
                        continue
                    other = authored_by_id[other_id]
                    if _polyline_intersects_rect(requested_edge_points, other["rect"]):
                        blocked = True
                        break
                if blocked:
                    reject("edge_node_intersection")
                    continue

            unrelated_edge_intersections = 0
            wire_crossings = 0
            probe_routes = list(candidate_incident_routes)
            if requested_edge_points is not None:
                probe_routes.append(
                    {
                        "points": requested_edge_points,
                        "bounds": requested_bounds,
                        "endpointIds": {str(from_id), str(to_id)},
                    }
                )
            # Broad-phase prune via edge_index before the exact (and
            # relatively expensive) polyline checks: an edge whose overall
            # bounds do not overlap the query rect/bounds cannot possibly
            # intersect or cross it, so this cannot change the result, only
            # how many pairs get the exact check. Without this, every
            # evaluated candidate re-scanned every edge in the map, which is
            # the dominant cost on maps with many edges.
            for edge_id in edge_index.query(rect):
                sampled = sampled_by_edge_id[edge_id]
                if _polyline_intersects_rect(sampled["points"], rect):
                    unrelated_edge_intersections += 1
            for probe in probe_routes:
                for edge_id in edge_index.query(probe["bounds"]):
                    sampled = sampled_by_edge_id[edge_id]
                    sampled_endpoints = {
                        str(sampled["edge"].get("fromNodeId") or ""),
                        str(sampled["edge"].get("toNodeId") or ""),
                    }
                    if probe["endpointIds"] & sampled_endpoints:
                        continue
                    if _polyline_crossing(probe["points"], sampled["points"]) is not None:
                        wire_crossings += 1

            forward_violation = 0
            if anchor is not None:
                delta = (
                    (center["x"] - anchor["center"]["x"]) * forward["x"]
                    + (center["y"] - anchor["center"]["y"]) * forward["y"]
                )
                is_outgoing = connection_direction != "incoming"
                if is_outgoing and delta < -(grid_size / 2.0):
                    forward_violation = 1
                elif not is_outgoing and delta > (grid_size / 2.0):
                    forward_violation = 1

            route_length = sum(_polyline_length(probe["points"]) for probe in probe_routes)
            clearance_value = minimum_clearance if minimum_clearance is not None else (node_clearance * 4.0)
            remainder_x = abs(rect["x"]) % grid_size
            remainder_y = abs(rect["y"]) % grid_size
            alignment_deviation = (
                min(remainder_x, grid_size - remainder_x) + min(remainder_y, grid_size - remainder_y)
            ) / 2.0
            if anchor is not None:
                anchor_dx = center["x"] - anchor["center"]["x"]
                anchor_dy = center["y"] - anchor["center"]["y"]
                # Explicit sqrt(dx*dx+dy*dy) rather than math.hypot(): plain
                # IEEE-754 multiply/add/sqrt is bit-identical across
                # compliant runtimes, whereas hypot()'s internal overflow-
                # safe algorithm is implementation-defined and can differ
                # from JavaScript's Math.hypot() in the low bits. This
                # candidate-scoring term is new to Phase 3, so it can use
                # the deterministic form without touching the pre-existing,
                # already frozen-tested Phase 1/2 hypot call sites shared
                # with the live digest/diagnostics path.
                anchor_distance = math.sqrt(anchor_dx * anchor_dx + anchor_dy * anchor_dy)
            else:
                anchor_distance = 0.0
            movement_distance = 0.0
            if moving_node is not None:
                movement_dx = rect["x"] - moving_node["rect"]["x"]
                movement_dy = rect["y"] - moving_node["rect"]["y"]
                movement_distance = math.sqrt(
                    movement_dx * movement_dx + movement_dy * movement_dy
                )
            region_violation = 0
            if visible_world_rect is not None:
                visible = _rect(visible_world_rect, "visibleWorldRect")
                if not (
                    rect["x"] >= visible["x"]
                    and rect["y"] >= visible["y"]
                    and rect["x"] + rect["width"] <= visible["x"] + visible["width"]
                    and rect["y"] + rect["height"] <= visible["y"] + visible["height"]
                ):
                    region_violation = 1

            candidate_id = _candidate_id(origin_kind, lane, row, orientation, order)
            score_key = (
                unrelated_edge_intersections,
                wire_crossings,
                forward_violation,
                _rounded_coarse(route_length),
                _rounded_coarse(-clearance_value),
                _rounded_coarse(alignment_deviation),
                _rounded_coarse(anchor_distance),
                _rounded_coarse(movement_distance),
                region_violation,
                candidate_id,
                _snap(rect["y"], grid_size),
                _snap(rect["x"], grid_size),
            )
            candidate = {
                "candidateId": candidate_id,
                "position": {"x": rect["x"], "y": rect["y"]},
                "portOrientation": orientation,
                "portOrder": order,
                "score": {
                    "edgeCrossings": wire_crossings,
                    "backwardEdges": forward_violation,
                    "routeBends": 0,
                    "routeLength": _rounded_coarse(route_length),
                    "minimumClearance": _rounded_coarse(clearance_value),
                    "alignmentDeviation": _rounded(alignment_deviation),
                    "existingNodeMovement": _rounded_coarse(movement_distance),
                    "anchorProximity": _rounded(anchor_distance),
                    "regionPreference": 0 if region_violation == 0 else 1,
                    "edgeCardIntersections": unrelated_edge_intersections,
                },
                "metricsAfter": {
                    "nodeOverlaps": 0,
                    "edgeCardIntersections": unrelated_edge_intersections,
                    "edgeCrossings": wire_crossings,
                    "minimumClearance": _rounded_coarse(clearance_value),
                },
            }
            scored.append((score_key, candidate))

    scored.sort(key=lambda item: item[0])
    ranked = [candidate for _key, candidate in scored[:safe_limit]]
    return {
        **result_base,
        "evaluatedCount": evaluated,
        "rejectionCounts": rejection_counts,
        "candidates": ranked,
    }


def _arrangement_ranks(scene: Mapping[str, Any]) -> Dict[str, int]:
    node_ids = sorted(
        str(node.get("nodeId") or "")
        for node in scene.get("nodes") or []
        if node.get("nodeId")
    )
    incoming = {node_id: 0 for node_id in node_ids}
    adjacency = {node_id: [] for node_id in node_ids}
    for edge in _sorted_records(scene.get("edges") or [], "edgeId"):
        if edge.get("kind") != "precedence":
            continue
        source = str(edge.get("fromNodeId") or "")
        target = str(edge.get("toNodeId") or "")
        if source not in incoming or target not in incoming or source == target:
            continue
        adjacency[source].append(target)
        incoming[target] += 1
    for targets in adjacency.values():
        targets.sort()
    queue = sorted(node_id for node_id in node_ids if incoming[node_id] == 0)
    ranks = {node_id: 0 for node_id in queue}
    while queue:
        node_id = queue.pop(0)
        next_rank = ranks.get(node_id, 0) + 1
        for target in adjacency[node_id]:
            ranks[target] = max(ranks.get(target, 0), next_rank)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
                queue.sort()
    for node_id in node_ids:
        ranks.setdefault(node_id, 0)
    return ranks


def _arrangement_metrics(diagnostics: Mapping[str, Any]) -> Dict[str, Any]:
    metrics = diagnostics.get("metrics") or {}
    hard_ids = sorted(
        str(problem.get("problemId") or "")
        for problem in diagnostics.get("problems") or []
        if problem.get("code") in ARRANGEMENT_HARD_PROBLEM_CODES
    )
    return {
        "hardViolationCount": len(hard_ids),
        "hardViolationIds": hard_ids,
        "nodeOverlaps": int(metrics.get("nodeOverlaps") or 0),
        "nodeClearanceViolations": int(metrics.get("nodeClearanceViolations") or 0),
        "nodeGroupHeaderIntersections": int(metrics.get("nodeGroupHeaderIntersections") or 0),
        "edgeNodeIntersections": int(metrics.get("edgeNodeIntersections") or 0),
        "edgeGroupHeaderIntersections": int(metrics.get("edgeGroupHeaderIntersections") or 0),
        "edgeCrossings": int(metrics.get("edgeCrossings") or 0),
        "backwardEdges": int(metrics.get("backwardEdges") or 0),
        "routeBends": int(metrics.get("routeBends") or 0),
        "routeLength": _rounded_coarse(float(metrics.get("routeLength") or 0.0)),
        "alignmentDeviation": _rounded_coarse(float(metrics.get("alignmentDeviation") or 0.0)),
    }


def _arrangement_quality(metrics: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        int(metrics.get("hardViolationCount") or 0),
        int(metrics.get("edgeCrossings") or 0),
        int(metrics.get("backwardEdges") or 0),
        int(metrics.get("routeBends") or 0),
        float(metrics.get("routeLength") or 0.0),
        float(metrics.get("alignmentDeviation") or 0.0),
    )


def _arrangement_port_layout(flow_direction: str) -> Tuple[str, str]:
    if flow_direction == "right_to_left":
        return "horizontal", "output_first"
    if flow_direction == "top_to_bottom":
        return "vertical", "input_first"
    if flow_direction == "bottom_to_top":
        return "vertical", "output_first"
    return "horizontal", "input_first"


def _rect_inside(inner: Mapping[str, float], outer: Mapping[str, float]) -> bool:
    return (
        inner["x"] >= outer["x"]
        and inner["y"] >= outer["y"]
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"]
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"]
    )


def _arrangement_position(node: Mapping[str, Any], rect: Mapping[str, float]) -> Dict[str, float]:
    if node.get("kind") == "junction":
        return {
            "x": _rounded(rect["x"] + rect["width"] / 2.0),
            "y": _rounded(rect["y"] + rect["height"] / 2.0),
        }
    return {"x": _rounded(rect["x"]), "y": _rounded(rect["y"])}


def _arrangement_plan_base(
    scene: Mapping[str, Any],
    scope_kind: str,
    scope_node_ids: Sequence[str],
    group_id: Optional[str],
    pinned_node_ids: Sequence[str],
    pinned_group_ids: Sequence[str],
) -> Dict[str, Any]:
    return {
        "spatialEngineVersion": PROCESS_MAP_SPATIAL_VERSION,
        "arrangementPolicyVersion": PROCESS_MAP_ARRANGEMENT_POLICY_VERSION,
        "identity": deepcopy(dict(scene.get("identity") or {})),
        "obstacleFingerprint": _obstacle_fingerprint(scene),
        "scope": {
            "kind": scope_kind,
            "nodeIds": sorted(set(scope_node_ids)),
            "groupId": group_id,
        },
        "pinnedNodeIds": sorted(set(pinned_node_ids)),
        "pinnedGroupIds": sorted(set(pinned_group_ids)),
    }


def generate_arrangement_plan(
    process_map: Mapping[str, Any],
    *,
    scope: str = "full_map",
    node_ids: Optional[Sequence[str]] = None,
    group_id: Optional[str] = None,
    pinned_node_ids: Optional[Sequence[str]] = None,
    pinned_group_ids: Optional[Sequence[str]] = None,
    preserve_manual: bool = True,
    revision: Optional[str] = None,
    contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a deterministic, non-mutating arrangement preview.

    Group frames are authored anchors. By default only auto-positioned nodes
    move; manual and locked nodes remain constraints. The returned map is
    acceptable only when it improves the
    configured lexicographic metric without adding a hard spatial problem.
    """

    if scope not in ("selection", "group", "full_map"):
        raise SpatialGeometryError("unsupported arrangement scope")
    active_contract = spatial_contract_for_process_map(process_map, contract)
    scene = compile_spatial_scene(
        process_map,
        revision=revision,
        contract=active_contract,
    )
    node_by_id = {
        str(node.get("nodeId") or ""): node for node in scene.get("nodes") or []
    }
    group_by_id = {
        str(group.get("groupId") or ""): group for group in scene.get("groups") or []
    }
    all_group_ids = sorted(group_by_id)
    explicit_pinned = {
        str(node_id) for node_id in (pinned_node_ids or ()) if str(node_id) in node_by_id
    }
    requested_pinned_groups = {
        str(value) for value in (pinned_group_ids or ()) if str(value) in group_by_id
    }

    if scope == "selection":
        scoped_ids = {
            str(node_id) for node_id in (node_ids or ()) if str(node_id) in node_by_id
        }
    elif scope == "group":
        if not group_id or group_id not in group_by_id:
            raise SpatialGeometryError("group arrangement requires a known groupId")
        scoped_ids = set(group_by_id[group_id].get("memberNodeIds") or [])
    else:
        scoped_ids = set(node_by_id)

    pinned = explicit_pinned | {
        node_id for node_id in scoped_ids
        if node_by_id[node_id].get("positionMode") == "locked"
        or node_by_id[node_id].get("locked") is True
        or (
            preserve_manual
            and node_by_id[node_id].get("positionMode") == "manual"
        )
    }
    movable_ids = scoped_ids - pinned
    base = _arrangement_plan_base(
        scene,
        scope,
        sorted(scoped_ids),
        group_id,
        sorted(pinned),
        sorted(set(all_group_ids) | requested_pinned_groups),
    )
    if not movable_ids:
        return {
            **base,
            "accepted": False,
            "failureReason": "no_movable_nodes",
            "planId": None,
            "moves": [],
        }

    policy = active_contract["layoutPolicyDefaults"]
    flow_direction = str(policy.get("flowDirection") or "left_to_right")
    if flow_direction not in _FLOW_AXES:
        flow_direction = "left_to_right"
    grid = float(policy["gridSize"])
    clearance = float(policy["nodeClearance"])
    edge_clearance = float(policy["edgeClearance"])
    horizontal = flow_direction in ("left_to_right", "right_to_left")
    orientation, order = _arrangement_port_layout(flow_direction)
    ranks = _arrangement_ranks(scene)

    partitions: Dict[str, list[Dict[str, Any]]] = {}
    for node_id in sorted(movable_ids):
        node = node_by_id[node_id]
        partition_key = str(node.get("groupId") or "")
        partitions.setdefault(partition_key, []).append(node)

    placed: Dict[str, Dict[str, Any]] = {
        node_id: {
            "rect": deepcopy(node["rect"]),
            "junction": node.get("kind") == "junction",
        }
        for node_id, node in node_by_id.items()
        if node_id not in movable_ids
    }
    proposed_rects: Dict[str, Dict[str, float]] = {}

    def candidate_allowed(
        node_id: str,
        candidate: Mapping[str, float],
        partition_group_id: str,
    ) -> bool:
        own_group = group_by_id.get(partition_group_id)
        if own_group is not None:
            if not _rect_inside(candidate, own_group["rect"]):
                return False
        else:
            for group in group_by_id.values():
                if _rect_intersection(candidate, group["rect"]) is not None:
                    return False
        for group in group_by_id.values():
            if _rect_intersection(candidate, group["headerRect"]) is not None:
                return False
        for other_id, obstacle in placed.items():
            if other_id == node_id:
                continue
            obstacle_rect = obstacle["rect"]
            if _rect_intersection(candidate, obstacle_rect) is not None:
                return False
            minimum = edge_clearance if obstacle["junction"] else clearance
            if _rect_distance(candidate, obstacle_rect) < minimum:
                return False
        return True

    partition_keys = sorted(partitions, key=lambda value: (value == "", value))
    for partition_key in partition_keys:
        partition_nodes = partitions[partition_key]
        rank_values = sorted({ranks.get(str(node["nodeId"]), 0) for node in partition_nodes})
        compact_rank = {value: index for index, value in enumerate(rank_values)}
        columns: Dict[int, list[Dict[str, Any]]] = {}
        for node in partition_nodes:
            columns.setdefault(compact_rank[ranks.get(str(node["nodeId"]), 0)], []).append(node)
        for values in columns.values():
            values.sort(
                key=lambda node: (
                    node["center"]["y"] if horizontal else node["center"]["x"],
                    str(node["nodeId"]),
                )
            )
        maximum_width = max(float(node["rect"]["width"]) for node in partition_nodes)
        maximum_height = max(float(node["rect"]["height"]) for node in partition_nodes)
        rank_count = max(1, len(rank_values))
        lane_count = max(len(values) for values in columns.values())
        if horizontal:
            layout_width = rank_count * maximum_width + (rank_count - 1) * clearance
            layout_height = lane_count * maximum_height + (lane_count - 1) * clearance
        else:
            layout_width = lane_count * maximum_width + (lane_count - 1) * clearance
            layout_height = rank_count * maximum_height + (rank_count - 1) * clearance

        current_bounds = _bounds([node["rect"] for node in partition_nodes])
        target_group = group_by_id.get(partition_key)
        if target_group is not None:
            available = target_group["rect"]
            padding = grid
            if (
                layout_width > available["width"] - 2.0 * padding
                or layout_height > available["height"] - 2.0 * padding
            ):
                return {
                    **base,
                    "accepted": False,
                    "failureReason": "group_capacity_exceeded",
                    "planId": None,
                    "moves": [],
                }
            origin_x = available["x"] + (available["width"] - layout_width) / 2.0
            origin_y = available["y"] + (available["height"] - layout_height) / 2.0
        else:
            origin_x = current_bounds["x"] + (current_bounds["width"] - layout_width) / 2.0
            origin_y = current_bounds["y"] + (current_bounds["height"] - layout_height) / 2.0

        for rank_index in sorted(columns):
            values = columns[rank_index]
            lane_offset = (lane_count - len(values)) / 2.0
            display_rank = rank_index
            if flow_direction in ("right_to_left", "bottom_to_top"):
                display_rank = rank_count - rank_index - 1
            for lane_index, node in enumerate(values):
                if horizontal:
                    slot_x = origin_x + display_rank * (maximum_width + clearance)
                    slot_y = origin_y + (lane_index + lane_offset) * (maximum_height + clearance)
                else:
                    slot_x = origin_x + (lane_index + lane_offset) * (maximum_width + clearance)
                    slot_y = origin_y + display_rank * (maximum_height + clearance)
                base_rect = {
                    "x": _snap(slot_x + (maximum_width - node["rect"]["width"]) / 2.0, grid),
                    "y": _snap(slot_y + (maximum_height - node["rect"]["height"]) / 2.0, grid),
                    "width": float(node["rect"]["width"]),
                    "height": float(node["rect"]["height"]),
                }
                selected_candidate = None
                selected_key = None
                selected_ring = None
                for lane_delta, row_delta in _ring_offsets(12):
                    ring = max(abs(lane_delta), abs(row_delta))
                    if selected_ring is not None and ring > selected_ring:
                        break
                    candidate = {
                        **base_rect,
                        "x": _rounded(base_rect["x"] + lane_delta * grid),
                        "y": _rounded(base_rect["y"] + row_delta * grid),
                    }
                    if not candidate_allowed(str(node["nodeId"]), candidate, partition_key):
                        continue
                    dx = candidate["x"] - node["rect"]["x"]
                    dy = candidate["y"] - node["rect"]["y"]
                    key = (dx * dx + dy * dy, candidate["y"], candidate["x"])
                    if selected_key is None or key < selected_key:
                        selected_candidate = candidate
                        selected_key = key
                        selected_ring = ring
                if selected_candidate is None:
                    return {
                        **base,
                        "accepted": False,
                        "failureReason": "no_collision_free_arrangement",
                        "planId": None,
                        "moves": [],
                    }
                node_id = str(node["nodeId"])
                proposed_rects[node_id] = selected_candidate
                placed[node_id] = {
                    "rect": selected_candidate,
                    "junction": node.get("kind") == "junction",
                }

    next_map = deepcopy(dict(process_map))
    raw_node_by_id = {
        str(node.get("nodeId") or ""): node
        for node in next_map.get("canvasNodes") or []
        if isinstance(node, dict)
    }
    moves = []
    movement_distance = 0.0
    for node_id in sorted(proposed_rects):
        compiled = node_by_id[node_id]
        raw = raw_node_by_id[node_id]
        position = _arrangement_position(compiled, proposed_rects[node_id])
        before_position = deepcopy(raw.get("position") or {})
        before_orientation = str(raw.get("portOrientation") or "horizontal")
        before_order = str(raw.get("portOrder") or "input_first")
        raw["position"] = position
        if raw.get("nodeKind") != "junction":
            raw["portOrientation"] = orientation
            raw["portOrder"] = order
        dx = float(position["x"]) - float(before_position.get("x") or 0.0)
        dy = float(position["y"]) - float(before_position.get("y") or 0.0)
        movement_distance += math.sqrt(dx * dx + dy * dy)
        if (
            position != before_position
            or orientation != before_orientation
            or order != before_order
        ):
            moves.append(
                {
                    "nodeId": node_id,
                    "from": {
                        "position": before_position,
                        "portOrientation": before_orientation,
                        "portOrder": before_order,
                    },
                    "to": {
                        "position": position,
                        "portOrientation": orientation,
                        "portOrder": order,
                    },
                }
            )
    if not moves:
        return {
            **base,
            "accepted": False,
            "failureReason": "layout_already_clean",
            "planId": None,
            "moves": [],
        }

    refreshed = refresh_orthogonal_auto_routes(next_map, contract=active_contract)
    if refreshed["failures"]:
        return {
            **base,
            "accepted": False,
            "failureReason": "automatic_route_update_failed",
            "planId": None,
            "moves": [],
            "routeFailures": refreshed["failures"],
        }
    next_map = refreshed["map"]
    before_diagnostics = diagnose_spatial_scene(scene, contract=active_contract)
    after_scene = compile_spatial_scene(next_map, revision=revision, contract=active_contract)
    after_diagnostics = diagnose_spatial_scene(after_scene, contract=active_contract)
    before_metrics = _arrangement_metrics(before_diagnostics)
    after_metrics = _arrangement_metrics(after_diagnostics)
    added_hard = sorted(
        set(after_metrics["hardViolationIds"]) - set(before_metrics["hardViolationIds"])
    )
    if added_hard:
        return {
            **base,
            "accepted": False,
            "failureReason": "hard_violation_introduced",
            "planId": None,
            "moves": [],
            "hardViolationsAdded": added_hard,
        }
    quality_before = _arrangement_quality(before_metrics)
    quality_after = _arrangement_quality(after_metrics)
    if quality_after >= quality_before:
        return {
            **base,
            "accepted": False,
            "failureReason": "configured_metric_not_improved",
            "planId": None,
            "moves": [],
            "metricsBefore": before_metrics,
            "metricsAfter": after_metrics,
        }

    changed_routes = []
    original_edges = {
        str(edge.get("edgeId") or ""): edge
        for edge in process_map.get("canvasEdges") or []
        if isinstance(edge, Mapping)
    }
    for edge in _sorted_records(next_map.get("canvasEdges") or [], "edgeId"):
        edge_id = str(edge.get("edgeId") or "")
        if (edge.get("routing") or {}) != (original_edges.get(edge_id, {}).get("routing") or {}):
            changed_routes.append(
                {"edgeId": edge_id, "routing": deepcopy(edge.get("routing") or {})}
            )
    proposal_identity = {
        "policyVersion": PROCESS_MAP_ARRANGEMENT_POLICY_VERSION,
        "obstacleFingerprint": base["obstacleFingerprint"],
        "scope": base["scope"],
        "moves": moves,
        "routes": changed_routes,
        "metricsBefore": before_metrics,
        "metricsAfter": after_metrics,
    }
    plan_id = "pm-arr-" + _fnv1a64_hex(_canonical_bytes(proposal_identity))
    return {
        **base,
        "accepted": True,
        "failureReason": None,
        "planId": plan_id,
        "moves": moves,
        "routes": changed_routes,
        "movementDistance": _rounded_coarse(movement_distance),
        "metricsBefore": before_metrics,
        "metricsAfter": after_metrics,
        "hardViolationsAdded": [],
        "proposedMap": next_map,
    }
