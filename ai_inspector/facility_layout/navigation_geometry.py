"""Deterministic geometry and candidate routing used by the NAV0 benchmark."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import heapq
import json
import math
from typing import Any, Iterable, Mapping, Sequence

try:
    from shapely import BufferCapStyle, BufferJoinStyle, STRtree, set_precision
    from shapely.geometry import LineString, MultiPolygon, Point, Polygon
    from shapely.geometry.base import BaseGeometry
    from shapely.geometry.polygon import orient
    from shapely.ops import triangulate, unary_union
    from shapely.prepared import prep
except ImportError:  # pragma: no cover - exercised by the fail-closed test
    BufferCapStyle = BufferJoinStyle = STRtree = None
    BaseGeometry = LineString = MultiPolygon = Point = Polygon = None
    orient = prep = set_precision = triangulate = unary_union = None


NAVIGATION_GEOMETRY_SCHEMA = "facility-navigation-geometry-v1"
NAVIGATION_GEOMETRY_PRECISION = 6
NAVIGATION_GEOMETRY_GRID_METERS = 10 ** -NAVIGATION_GEOMETRY_PRECISION
NAVIGATION_BUFFER_QUAD_SEGS = 16
NAVIGATION_BUFFER_MITRE_LIMIT = 5.0
NAVIGATION_NUMERIC_EPSILON = 1.0e-9
NAVIGATION_MAXIMUM_VISIBILITY_CANDIDATE_PAIRS = 5_000_000


class FacilityNavigationGeometryError(RuntimeError):
    """NAV0 cannot produce deterministic candidate geometry."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def deterministic_geometry_contract() -> dict[str, Any]:
    """Return the complete revisioned NAV0/NAV1 geometry contract."""

    return {
        "schemaVersion": NAVIGATION_GEOMETRY_SCHEMA,
        "sourcePrecisionDecimalPlaces": NAVIGATION_GEOMETRY_PRECISION,
        "inputOrdering": "stable_obstacle_id_then_canonical_polygon",
        "sourceComposition": "unary_union",
        "buffer": {
            "quadSegs": NAVIGATION_BUFFER_QUAD_SEGS,
            "capStyle": "round",
            "joinStyle": "round",
            "mitreLimit": NAVIGATION_BUFFER_MITRE_LIMIT,
            "singleSided": False,
            "discDiscretization": "conservative_secant_correction",
        },
        "postBufferComposition": "unary_union",
        "exteriorOrientation": "counterclockwise",
        "holeOrientation": "clockwise",
        "startVertex": "minimum_x_then_z_lexicographic",
        "polygonOrdering": "first_vertex_then_area_then_source_id",
        "outputPrecisionDecimalPlaces": NAVIGATION_GEOMETRY_PRECISION,
        "duplicateAndCollinearHandling": "deterministic_normalization",
        "invalidResult": "fail_closed",
        "numericEpsilon": NAVIGATION_NUMERIC_EPSILON,
        "qualification": (
            "The secant correction and numeric epsilon are computational geometry "
            "controls, not engineering clearance or safety allowance."
        ),
    }


def _require_geometry_engine() -> None:
    if Polygon is None or unary_union is None or set_precision is None:
        raise FacilityNavigationGeometryError(
            "facility_navigation_geometry_engine_unavailable",
            "Deterministic navigation geometry requires the configured geometry engine.",
        )


def _rounded(value: float) -> float:
    result = round(float(value), NAVIGATION_GEOMETRY_PRECISION)
    return 0.0 if result == 0 else result


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


def _point(raw: Mapping[str, Any] | Sequence[float]) -> tuple[float, float]:
    if isinstance(raw, Mapping):
        x = raw.get("x")
        z = raw.get("z")
    else:
        if len(raw) < 2:
            raise FacilityNavigationGeometryError(
                "facility_navigation_polygon_invalid",
                "A navigation polygon point requires x and z coordinates.",
            )
        x, z = raw[0], raw[1]
    if (
        isinstance(x, bool)
        or isinstance(z, bool)
        or not isinstance(x, (int, float))
        or not isinstance(z, (int, float))
        or not math.isfinite(float(x))
        or not math.isfinite(float(z))
    ):
        raise FacilityNavigationGeometryError(
            "facility_navigation_polygon_invalid",
            "Navigation polygon coordinates must be finite numbers.",
        )
    return _rounded(float(x)), _rounded(float(z))


def _cross(
    left: tuple[float, float],
    middle: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return (
        (middle[0] - left[0]) * (right[1] - middle[1])
        - (middle[1] - left[1]) * (right[0] - middle[0])
    )


def _signed_area(points: Sequence[tuple[float, float]]) -> float:
    return sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, (*points[1:], points[0]))
    ) / 2.0


def _remove_redundant_vertices(
    values: Iterable[tuple[float, float]],
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for value in values:
        point = (_rounded(value[0]), _rounded(value[1]))
        if not points or point != points[-1]:
            points.append(point)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    changed = True
    while changed and len(points) >= 3:
        changed = False
        result: list[tuple[float, float]] = []
        count = len(points)
        for index, point in enumerate(points):
            previous = points[(index - 1) % count]
            following = points[(index + 1) % count]
            if abs(_cross(previous, point, following)) <= NAVIGATION_NUMERIC_EPSILON:
                if (
                    min(previous[0], following[0]) - NAVIGATION_NUMERIC_EPSILON
                    <= point[0]
                    <= max(previous[0], following[0]) + NAVIGATION_NUMERIC_EPSILON
                    and min(previous[1], following[1]) - NAVIGATION_NUMERIC_EPSILON
                    <= point[1]
                    <= max(previous[1], following[1]) + NAVIGATION_NUMERIC_EPSILON
                ):
                    changed = True
                    continue
            result.append(point)
        points = result
    if len(points) < 3 or abs(_signed_area(points)) <= NAVIGATION_NUMERIC_EPSILON:
        raise FacilityNavigationGeometryError(
            "facility_navigation_polygon_invalid",
            "Navigation polygon normalization produced a degenerate ring.",
        )
    return points


def _canonical_ring(
    values: Iterable[tuple[float, float]],
    *,
    counterclockwise: bool,
) -> list[dict[str, float]]:
    points = _remove_redundant_vertices(values)
    is_counterclockwise = _signed_area(points) > 0
    if is_counterclockwise is not counterclockwise:
        points.reverse()
    start = min(range(len(points)), key=lambda index: points[index])
    points = points[start:] + points[:start]
    return [{"x": point[0], "z": point[1]} for point in points]


def _polygon_from_points(
    exterior: Sequence[Mapping[str, Any] | Sequence[float]],
    holes: Sequence[Sequence[Mapping[str, Any] | Sequence[float]]] = (),
) -> Any:
    _require_geometry_engine()
    shell = [_point(value) for value in exterior]
    interiors = [[_point(value) for value in ring] for ring in holes]
    if len(shell) < 3 or any(len(ring) < 3 for ring in interiors):
        raise FacilityNavigationGeometryError(
            "facility_navigation_polygon_invalid",
            "Navigation polygons require at least three points per ring.",
        )
    polygon = Polygon(shell, interiors)
    polygon = set_precision(
        polygon,
        grid_size=NAVIGATION_GEOMETRY_GRID_METERS,
        mode="valid_output",
    )
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        raise FacilityNavigationGeometryError(
            "facility_navigation_polygon_invalid",
            "Navigation polygon geometry is empty or invalid.",
        )
    return polygon


def _polygons(geometry: Any) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    values = []
    for item in getattr(geometry, "geoms", ()):
        values.extend(_polygons(item))
    return values


def _canonical_polygon_record(raw: Any) -> dict[str, Any]:
    polygon = orient(raw, sign=1.0)
    exterior = _canonical_ring(
        list(polygon.exterior.coords)[:-1],
        counterclockwise=True,
    )
    holes = sorted(
        (
            _canonical_ring(list(ring.coords)[:-1], counterclockwise=False)
            for ring in polygon.interiors
        ),
        key=_canonical_bytes,
    )
    return {
        "exterior": exterior,
        "holes": holes,
        "areaSquareMeters": _rounded(polygon.area),
    }


def _polygon_record_sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    exterior = item["exterior"]
    first = exterior[0]
    return (
        float(first["x"]),
        float(first["z"]),
        float(item["areaSquareMeters"]),
        tuple(str(value) for value in item.get("sourceObstacleIds", [])),
        _canonical_bytes(exterior),
        _canonical_bytes(item["holes"]),
    )


def canonicalize_polygon_geometry(geometry: Any) -> list[dict[str, Any]]:
    """Canonicalize Polygon or MultiPolygon geometry into stable JSON data."""

    _require_geometry_engine()
    if geometry is None or geometry.is_empty or not geometry.is_valid:
        raise FacilityNavigationGeometryError(
            "facility_navigation_geometry_invalid",
            "Canonical navigation geometry must be valid and non-empty.",
        )
    records = [_canonical_polygon_record(raw) for raw in _polygons(geometry)]
    records.sort(key=_polygon_record_sort_key)
    return records


def _canonicalize_obstacle_geometry(
    geometry: Any,
    sources: Sequence[tuple[str, Any]],
) -> list[dict[str, Any]]:
    source_ids = tuple(obstacle_id for obstacle_id, _ in sources)
    source_points = tuple(
        source.representative_point() for _, source in sources
    )
    source_index = STRtree(source_points)
    records = []
    for raw in _polygons(geometry):
        record = _canonical_polygon_record(raw)
        record["sourceObstacleIds"] = sorted(
            source_ids[int(index)]
            for index in source_index.query(raw, predicate="covers")
        )
        if not record["sourceObstacleIds"]:
            raise FacilityNavigationGeometryError(
                "facility_navigation_source_lineage_unavailable",
                "A canonical obstacle polygon has no contributing source identity.",
            )
        records.append(record)
    records.sort(key=_polygon_record_sort_key)
    return records


def geometry_from_canonical_polygons(values: Sequence[Mapping[str, Any]]) -> Any:
    _require_geometry_engine()
    polygons = [
        _polygon_from_points(item["exterior"], item.get("holes", []))
        for item in values
    ]
    geometry = unary_union(polygons)
    geometry = set_precision(
        geometry,
        grid_size=NAVIGATION_GEOMETRY_GRID_METERS,
        mode="valid_output",
    )
    if geometry.is_empty or not geometry.is_valid:
        raise FacilityNavigationGeometryError(
            "facility_navigation_geometry_invalid",
            "Canonical navigation polygons could not be reconstructed.",
        )
    return geometry


def _vertex_count(records: Sequence[Mapping[str, Any]]) -> int:
    return sum(
        len(item["exterior"]) + sum(len(hole) for hole in item["holes"])
        for item in records
    )


def union_and_expand_obstacles(
    obstacles: Sequence[Mapping[str, Any]],
    *,
    navigation_radius_meters: float,
) -> dict[str, Any]:
    """Union source footprints, apply the frozen envelope, then union again."""

    _require_geometry_engine()
    if (
        isinstance(navigation_radius_meters, bool)
        or not isinstance(navigation_radius_meters, (int, float))
        or not math.isfinite(float(navigation_radius_meters))
        or navigation_radius_meters < 0
    ):
        raise FacilityNavigationGeometryError(
            "facility_navigation_envelope_invalid",
            "The navigation radius must be a finite non-negative value.",
        )
    ordered = sorted(
        obstacles,
        key=lambda item: (
            str(item.get("obstacleId") or ""),
            _canonical_bytes(item.get("exterior")),
        ),
    )
    if not ordered or any(not str(item.get("obstacleId") or "") for item in ordered):
        raise FacilityNavigationGeometryError(
            "facility_navigation_obstacles_invalid",
            "At least one identified obstacle is required.",
        )
    if len({str(item["obstacleId"]) for item in ordered}) != len(ordered):
        raise FacilityNavigationGeometryError(
            "facility_navigation_obstacles_invalid",
            "Obstacle identities must be unique.",
        )
    source_polygons = [
        _polygon_from_points(item["exterior"], item.get("holes", []))
        for item in ordered
    ]
    source_union = unary_union(source_polygons)
    source_union = set_precision(
        source_union,
        grid_size=NAVIGATION_GEOMETRY_GRID_METERS,
        mode="valid_output",
    )
    if source_union.is_empty or not source_union.is_valid:
        raise FacilityNavigationGeometryError(
            "facility_navigation_union_invalid",
            "Source obstacle union is invalid.",
        )
    radius = float(navigation_radius_meters)
    effective_radius = (
        radius
        / math.cos(math.pi / (4.0 * NAVIGATION_BUFFER_QUAD_SEGS))
        if radius > 0
        else 0.0
    )
    expanded = (
        source_union.buffer(
            effective_radius,
            quad_segs=NAVIGATION_BUFFER_QUAD_SEGS,
            cap_style=BufferCapStyle.round,
            join_style=BufferJoinStyle.round,
            mitre_limit=NAVIGATION_BUFFER_MITRE_LIMIT,
            single_sided=False,
        )
        if effective_radius > 0
        else source_union
    )
    expanded = unary_union(_polygons(expanded))
    expanded = set_precision(
        expanded,
        grid_size=NAVIGATION_GEOMETRY_GRID_METERS,
        mode="valid_output",
    )
    if expanded.is_empty or not expanded.is_valid:
        raise FacilityNavigationGeometryError(
            "facility_navigation_expansion_invalid",
            "Expanded obstacle geometry is invalid.",
        )
    identified_sources = [
        (str(item["obstacleId"]), polygon)
        for item, polygon in zip(ordered, source_polygons)
    ]
    source_records = _canonicalize_obstacle_geometry(
        source_union,
        identified_sources,
    )
    expanded_records = _canonicalize_obstacle_geometry(
        expanded,
        identified_sources,
    )
    result = {
        "schemaVersion": NAVIGATION_GEOMETRY_SCHEMA,
        "contract": deterministic_geometry_contract(),
        "navigationRadiusMeters": _rounded(radius),
        "effectiveBufferRadiusMeters": _rounded(effective_radius),
        "sourceObstacleCount": len(ordered),
        "sourceVertexCount": sum(
            len(item["exterior"])
            + sum(len(hole) for hole in item.get("holes", []))
            for item in ordered
        ),
        "sourceUnionPolygonCount": len(source_records),
        "sourceUnionVertexCount": _vertex_count(source_records),
        "expandedPolygonCount": len(expanded_records),
        "expandedVertexCount": _vertex_count(expanded_records),
        "expandedPolygons": expanded_records,
        "sourceObstacleIds": [str(item["obstacleId"]) for item in ordered],
    }
    result["geometryFingerprint"] = _fingerprint(result)
    return result


def free_space_geometry(
    allowed_polygons: Sequence[Mapping[str, Any]],
    expanded_obstacles: Sequence[Mapping[str, Any]],
) -> Any:
    _require_geometry_engine()
    allowed = geometry_from_canonical_polygons(allowed_polygons)
    blocked = geometry_from_canonical_polygons(expanded_obstacles)
    result = allowed.difference(blocked)
    result = set_precision(
        result,
        grid_size=NAVIGATION_GEOMETRY_GRID_METERS,
        mode="valid_output",
    )
    polygons = _polygons(result)
    if not polygons:
        raise FacilityNavigationGeometryError(
            "facility_navigation_free_space_empty",
            "Obstacle expansion leaves no traversable free space.",
        )
    result = unary_union(polygons)
    if result.is_empty or not result.is_valid:
        raise FacilityNavigationGeometryError(
            "facility_navigation_free_space_invalid",
            "Traversable free space is invalid.",
        )
    return result


def deterministic_query_points(free_space: Any) -> tuple[tuple[float, float], tuple[float, float]]:
    """Choose stable separated points inside the largest connected component."""

    _require_geometry_engine()
    component = max(_polygons(free_space), key=lambda item: (item.area, item.bounds))
    minimum_x, minimum_z, maximum_x, maximum_z = component.bounds
    step = max(
        NAVIGATION_GEOMETRY_GRID_METERS,
        min(maximum_x - minimum_x, maximum_z - minimum_z) / 40.0,
    )
    candidates: list[tuple[float, float]] = []
    x = minimum_x + step / 2.0
    while x < maximum_x:
        z = minimum_z + step / 2.0
        while z < maximum_z:
            candidate = (_rounded(x), _rounded(z))
            if component.contains(Point(candidate)):
                candidates.append(candidate)
            z += step
        x += step
    if len(candidates) < 2:
        point = component.representative_point()
        raise FacilityNavigationGeometryError(
            "facility_navigation_query_points_unavailable",
            f"Free space near ({point.x:.6f}, {point.y:.6f}) has too few benchmark points.",
        )
    start = min(candidates, key=lambda point: (point[0] + point[1], point))
    goal = max(
        candidates,
        key=lambda point: (
            math.dist(start, point),
            point[0] + point[1],
            point,
        ),
    )
    return start, goal


def _node_id(kind: str, point: tuple[float, float]) -> str:
    x = f"{point[0]:.{NAVIGATION_GEOMETRY_PRECISION}f}"
    z = f"{point[1]:.{NAVIGATION_GEOMETRY_PRECISION}f}"
    return f"{kind}:{x}:{z}"


def _geometry_vertices(geometry: Any) -> list[tuple[float, float]]:
    values: set[tuple[float, float]] = set()
    for polygon in _polygons(geometry):
        values.update(_point(item) for item in list(polygon.exterior.coords)[:-1])
        for ring in polygon.interiors:
            values.update(_point(item) for item in list(ring.coords)[:-1])
    return sorted(values)


@dataclass(frozen=True)
class NavigationGraph:
    nodes: tuple[tuple[str, tuple[float, float]], ...]
    edges: tuple[tuple[str, str, float], ...]
    candidate_pair_count: int


def _visibility_nodes(
    free_space: Any,
    start: tuple[float, float],
    goal: tuple[float, float],
) -> tuple[tuple[str, tuple[float, float]], ...]:
    node_points = [("start", _point(start)), ("goal", _point(goal))]
    node_points.extend(("vertex", point) for point in _geometry_vertices(free_space))
    unique: dict[tuple[float, float], str] = {}
    for kind, point in node_points:
        unique.setdefault(point, _node_id(kind, point))
    if start in unique:
        unique[start] = _node_id("start", start)
    if goal in unique:
        unique[goal] = _node_id("goal", goal)
    return tuple(sorted(((node_id, point) for point, node_id in unique.items())))


def visibility_graph_projection(
    free_space: Any,
    start: tuple[float, float],
    goal: tuple[float, float],
) -> dict[str, int]:
    """Project graph allocation before any visibility comparisons are made."""

    _require_geometry_engine()
    nodes = _visibility_nodes(free_space, start, goal)
    return {
        "nodeCount": len(nodes),
        "candidatePairCount": len(nodes) * (len(nodes) - 1) // 2,
        "maximumCandidatePairCount": (
            NAVIGATION_MAXIMUM_VISIBILITY_CANDIDATE_PAIRS
        ),
    }


def build_visibility_graph(
    free_space: Any,
    start: tuple[float, float],
    goal: tuple[float, float],
) -> NavigationGraph:
    _require_geometry_engine()
    if not free_space.covers(Point(start)) or not free_space.covers(Point(goal)):
        raise FacilityNavigationGeometryError(
            "facility_navigation_query_outside_free_space",
            "Visibility-graph query endpoints must lie in traversable free space.",
        )
    nodes = _visibility_nodes(free_space, start, goal)
    prepared = prep(free_space)
    edges = []
    candidate_pairs = len(nodes) * (len(nodes) - 1) // 2
    if candidate_pairs > NAVIGATION_MAXIMUM_VISIBILITY_CANDIDATE_PAIRS:
        raise FacilityNavigationGeometryError(
            "facility_navigation_visibility_budget_exceeded",
            "The projected visibility graph exceeds the frozen comparison budget.",
            details={
                "nodeCount": len(nodes),
                "projectedCandidatePairCount": candidate_pairs,
                "maximumCandidatePairCount": (
                    NAVIGATION_MAXIMUM_VISIBILITY_CANDIDATE_PAIRS
                ),
            },
        )
    for index, (left_id, left) in enumerate(nodes):
        for right_id, right in nodes[index + 1 :]:
            line = LineString([left, right])
            if line.length <= NAVIGATION_NUMERIC_EPSILON:
                continue
            if prepared.covers(line):
                edges.append((left_id, right_id, _rounded(line.length)))
    return NavigationGraph(
        nodes=nodes,
        edges=tuple(edges),
        candidate_pair_count=candidate_pairs,
    )


def _shortest_node_path(
    graph: NavigationGraph,
    start_id: str,
    goal_id: str,
) -> tuple[list[str], float]:
    adjacency: dict[str, list[tuple[str, float]]] = {
        node_id: [] for node_id, _ in graph.nodes
    }
    points = dict(graph.nodes)
    for left, right, distance in graph.edges:
        adjacency[left].append((right, distance))
        adjacency[right].append((left, distance))
    for values in adjacency.values():
        values.sort()
    queue: list[tuple[float, float, str]] = [(0.0, 0.0, start_id)]
    previous: dict[str, str] = {}
    cost = {start_id: 0.0}
    while queue:
        _, current_cost, node_id = heapq.heappop(queue)
        if current_cost > cost.get(node_id, math.inf) + NAVIGATION_NUMERIC_EPSILON:
            continue
        if node_id == goal_id:
            break
        for neighbor, distance in adjacency.get(node_id, []):
            candidate = current_cost + distance
            if candidate + NAVIGATION_NUMERIC_EPSILON < cost.get(neighbor, math.inf):
                cost[neighbor] = candidate
                previous[neighbor] = node_id
                heuristic = math.dist(points[neighbor], points[goal_id])
                heapq.heappush(
                    queue,
                    (candidate + heuristic, candidate, neighbor),
                )
    if goal_id not in cost:
        raise FacilityNavigationGeometryError(
            "facility_navigation_route_unreachable",
            "No route connects the selected benchmark endpoints.",
        )
    node_ids = [goal_id]
    while node_ids[-1] != start_id:
        node_ids.append(previous[node_ids[-1]])
    node_ids.reverse()
    return node_ids, cost[goal_id]


def solve_visibility_graph(
    graph: NavigationGraph,
    start: tuple[float, float],
    goal: tuple[float, float],
) -> dict[str, Any]:
    start_id = _node_id("start", _point(start))
    goal_id = _node_id("goal", _point(goal))
    node_ids, distance = _shortest_node_path(graph, start_id, goal_id)
    points = dict(graph.nodes)
    centerline = [
        {"x": points[node_id][0], "z": points[node_id][1]}
        for node_id in node_ids
    ]
    result = {
        "algorithm": "visibility_graph_astar",
        "nodeCount": len(graph.nodes),
        "candidatePairCount": graph.candidate_pair_count,
        "acceptedEdgeCount": len(graph.edges),
        "graphCanonicalBytes": len(
            _canonical_bytes({"nodes": graph.nodes, "edges": graph.edges})
        ),
        "distanceMeters": _rounded(distance),
        "centerline": centerline,
    }
    result["routeFingerprint"] = _fingerprint(result)
    return result


@dataclass(frozen=True)
class TriangulatedMesh:
    triangles: tuple[Any, ...]
    adjacency: tuple[tuple[int, int], ...]
    portals: Mapping[tuple[int, int], tuple[tuple[float, float], tuple[float, float]]]


def _edge_key(
    left: tuple[float, float],
    right: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    return tuple(sorted((_point(left), _point(right))))  # type: ignore[return-value]


def _triangle_sort_key(raw: Any) -> bytes:
    """Return the general canonical key without re-validating a known triangle."""

    record = {
        "exterior": _canonical_ring(
            (_point(value) for value in list(raw.exterior.coords)[:-1]),
            counterclockwise=True,
        ),
        "holes": [],
        "areaSquareMeters": _rounded(raw.area),
    }
    return _canonical_bytes([record])


def build_triangulated_mesh(free_space: Any) -> TriangulatedMesh:
    _require_geometry_engine()
    triangles = []
    for component in _polygons(free_space):
        for candidate in triangulate(component):
            candidate = set_precision(
                candidate,
                grid_size=NAVIGATION_GEOMETRY_GRID_METERS,
                mode="valid_output",
            )
            if (
                candidate.geom_type == "Polygon"
                and candidate.area > NAVIGATION_NUMERIC_EPSILON
                and component.covers(candidate)
            ):
                triangles.append(candidate)
    triangles.sort(key=_triangle_sort_key)
    edge_owners: dict[
        tuple[tuple[float, float], tuple[float, float]], list[int]
    ] = {}
    for index, triangle in enumerate(triangles):
        points = [_point(value) for value in list(triangle.exterior.coords)[:-1]]
        for left, right in zip(points, (*points[1:], points[0])):
            edge_owners.setdefault(_edge_key(left, right), []).append(index)
    adjacency = []
    portals = {}
    for edge, owners in sorted(edge_owners.items()):
        if len(owners) == 2:
            left, right = sorted(owners)
            adjacency.append((left, right))
            portals[(left, right)] = edge
            portals[(right, left)] = edge
        elif len(owners) > 2:
            raise FacilityNavigationGeometryError(
                "facility_navigation_mesh_non_manifold",
                "Triangulated free space contains a non-manifold edge.",
            )
    return TriangulatedMesh(
        triangles=tuple(triangles),
        adjacency=tuple(adjacency),
        portals=portals,
    )


def _triangle_index(mesh: TriangulatedMesh, point: tuple[float, float]) -> int:
    candidate = Point(point)
    matches = [
        index for index, triangle in enumerate(mesh.triangles) if triangle.covers(candidate)
    ]
    if not matches:
        raise FacilityNavigationGeometryError(
            "facility_navigation_query_outside_mesh",
            "A benchmark endpoint is outside the triangulated free space.",
        )
    return min(matches)


def _triangle_path(
    mesh: TriangulatedMesh,
    start_index: int,
    goal_index: int,
) -> list[int]:
    if start_index == goal_index:
        return [start_index]
    centers = [
        (float(item.centroid.x), float(item.centroid.y)) for item in mesh.triangles
    ]
    adjacency: dict[int, list[int]] = {index: [] for index in range(len(centers))}
    for left, right in mesh.adjacency:
        adjacency[left].append(right)
        adjacency[right].append(left)
    for values in adjacency.values():
        values.sort()
    queue = [(0.0, 0.0, start_index)]
    previous: dict[int, int] = {}
    cost = {start_index: 0.0}
    while queue:
        _, current_cost, index = heapq.heappop(queue)
        if current_cost > cost.get(index, math.inf) + NAVIGATION_NUMERIC_EPSILON:
            continue
        if index == goal_index:
            break
        for neighbor in adjacency[index]:
            distance = math.dist(centers[index], centers[neighbor])
            candidate = current_cost + distance
            if candidate + NAVIGATION_NUMERIC_EPSILON < cost.get(neighbor, math.inf):
                cost[neighbor] = candidate
                previous[neighbor] = index
                heuristic = math.dist(centers[neighbor], centers[goal_index])
                heapq.heappush(
                    queue,
                    (candidate + heuristic, candidate, neighbor),
                )
    if goal_index not in cost:
        raise FacilityNavigationGeometryError(
            "facility_navigation_route_unreachable",
            "No triangulated route connects the benchmark endpoints.",
        )
    result = [goal_index]
    while result[-1] != start_index:
        result.append(previous[result[-1]])
    result.reverse()
    return result


def _triarea2(
    apex: tuple[float, float],
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return (
        (right[0] - apex[0]) * (left[1] - apex[1])
        - (left[0] - apex[0]) * (right[1] - apex[1])
    )


def _funnel(
    start: tuple[float, float],
    goal: tuple[float, float],
    triangle_path: Sequence[int],
    mesh: TriangulatedMesh,
) -> list[tuple[float, float]]:
    portals = [(start, start)]
    for current, following in zip(triangle_path, triangle_path[1:]):
        first, second = mesh.portals[(current, following)]
        current_center = mesh.triangles[current].centroid
        following_center = mesh.triangles[following].centroid
        direction = (
            float(following_center.x - current_center.x),
            float(following_center.y - current_center.y),
        )
        first_side = direction[0] * (first[1] - current_center.y) - direction[1] * (
            first[0] - current_center.x
        )
        if first_side >= 0:
            portals.append((first, second))
        else:
            portals.append((second, first))
    portals.append((goal, goal))

    path = [start]
    apex = start
    left = portals[0][0]
    right = portals[0][1]
    apex_index = left_index = right_index = 0
    index = 1
    while index < len(portals):
        new_left, new_right = portals[index]
        if _triarea2(apex, right, new_right) <= 0:
            if apex == right or _triarea2(apex, left, new_right) > 0:
                right = new_right
                right_index = index
            else:
                path.append(left)
                apex = left
                apex_index = left_index
                left = right = apex
                left_index = right_index = apex_index
                index = apex_index + 1
                continue
        if _triarea2(apex, left, new_left) >= 0:
            if apex == left or _triarea2(apex, right, new_left) < 0:
                left = new_left
                left_index = index
            else:
                path.append(right)
                apex = right
                apex_index = right_index
                left = right = apex
                left_index = right_index = apex_index
                index = apex_index + 1
                continue
        index += 1
    if path[-1] != goal:
        path.append(goal)
    return [_point(value) for value in path]


def solve_triangulated_mesh(
    mesh: TriangulatedMesh,
    free_space: Any,
    start: tuple[float, float],
    goal: tuple[float, float],
) -> dict[str, Any]:
    start_index = _triangle_index(mesh, start)
    goal_index = _triangle_index(mesh, goal)
    triangle_path = _triangle_path(mesh, start_index, goal_index)
    centerline = _funnel(start, goal, triangle_path, mesh)
    line = LineString(centerline)
    if (
        not free_space.covers(line)
        or not line.is_simple
        or len(centerline) != len(set(centerline))
    ):
        raise FacilityNavigationGeometryError(
            "facility_navigation_mesh_path_invalid",
            "The triangulated funnel path must be simple and remain inside "
            "traversable free space.",
        )
    payload = {
        "triangles": [
            canonicalize_polygon_geometry(item) for item in mesh.triangles
        ],
        "adjacency": mesh.adjacency,
    }
    result = {
        "algorithm": "triangulated_navmesh_astar_funnel",
        "triangleCount": len(mesh.triangles),
        "adjacencyEdgeCount": len(mesh.adjacency),
        "graphCanonicalBytes": len(_canonical_bytes(payload)),
        "distanceMeters": _rounded(line.length),
        "centerline": [
            {"x": _rounded(point[0]), "z": _rounded(point[1])}
            for point in centerline
        ],
    }
    result["routeFingerprint"] = _fingerprint(result)
    return result


def validate_centerline(free_space: Any, centerline: Sequence[Mapping[str, Any]]) -> bool:
    _require_geometry_engine()
    if len(centerline) < 2:
        return False
    line = LineString([_point(item) for item in centerline])
    return line.length > NAVIGATION_NUMERIC_EPSILON and free_space.covers(line)


__all__ = [
    "NAVIGATION_BUFFER_MITRE_LIMIT",
    "NAVIGATION_BUFFER_QUAD_SEGS",
    "NAVIGATION_GEOMETRY_GRID_METERS",
    "NAVIGATION_GEOMETRY_PRECISION",
    "NAVIGATION_GEOMETRY_SCHEMA",
    "NAVIGATION_MAXIMUM_VISIBILITY_CANDIDATE_PAIRS",
    "FacilityNavigationGeometryError",
    "NavigationGraph",
    "TriangulatedMesh",
    "build_triangulated_mesh",
    "build_visibility_graph",
    "canonicalize_polygon_geometry",
    "deterministic_geometry_contract",
    "deterministic_query_points",
    "free_space_geometry",
    "geometry_from_canonical_polygons",
    "solve_triangulated_mesh",
    "solve_visibility_graph",
    "union_and_expand_obstacles",
    "validate_centerline",
    "visibility_graph_projection",
]
