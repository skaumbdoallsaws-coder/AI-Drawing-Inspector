"""Authored perimeter walls shared by rendering and authoritative shell checks.

Distances are meters, in the layout X/Z frame. Walls straddle the boundary.
Polygon boundaries are snapshots; plan boundaries follow facilityPlan resizing.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

KEY = "facilityPerimeterWalls"
PREFIX = "layout-perimeter-wall-"


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def compile_perimeter_walls(settings: Mapping[str, Any], layout: Mapping[str, Any]) -> dict:
    from shapely import constrained_delaunay_triangles
    from shapely.geometry import LineString, Polygon

    allowed = {"boundarySource", "boundary", "heightMeters", "thicknessMeters", "openings", "exteriorFinish", "interiorColor"}
    if not isinstance(settings, Mapping) or set(settings) - allowed:
        raise ValueError("Unsupported perimeter wall settings")
    source = settings.get("boundarySource")
    if source == "plan":
        if "boundary" in settings:
            raise ValueError("Plan walls derive their boundary from facilityPlan")
        plan = (layout.get("extensions") or {}).get("facilityPlan")
        if not isinstance(plan, Mapping):
            raise ValueError("Set the facility plan dimensions before creating walls")
        from .plan_settings import normalize_plan_settings
        plan = normalize_plan_settings(plan)
        w, d = plan["widthMeters"], plan["depthMeters"]
        points = [(0.0, 0.0), (w, 0.0), (w, d), (0.0, d)]
    elif source == "polygon":
        boundary = settings.get("boundary")
        if not isinstance(boundary, list) or not 3 <= len(boundary) <= 128:
            raise ValueError("A perimeter needs 3 to 128 distinct boundary vertices")
        points = []
        for point in boundary:
            if not isinstance(point, Mapping) or set(point) != {"x", "z"}:
                raise ValueError("Boundary vertices must contain only x and z")
            points.append((_number(point["x"], "boundary.x", -10000, 10000),
                           _number(point["z"], "boundary.z", -10000, 10000)))
    else:
        raise ValueError("boundarySource must be plan or polygon")
    polygon = Polygon(points)
    if len(set(points)) != len(points) or not polygon.is_valid or polygon.area < 0.25:
        raise ValueError("The perimeter must be a simple, nonzero-area polygon without holes")
    height = _number(settings.get("heightMeters"), "heightMeters", 0.5, 30)
    thickness = _number(settings.get("thicknessMeters"), "thicknessMeters", 0.05, 2)
    inner = polygon.buffer(-thickness / 2, join_style="mitre")
    if inner.is_empty or inner.geom_type != "Polygon":
        raise ValueError("Wall thickness closes or splits the usable interior")
    ring = polygon.buffer(thickness / 2, join_style="mitre").difference(inner)
    openings = settings.get("openings", [])
    if not isinstance(openings, list) or len(openings) > 128:
        raise ValueError("At most 128 perimeter openings are supported")
    normalized = []
    for opening in openings:
        if not isinstance(opening, Mapping) or set(opening) != {"edge", "startMeters", "endMeters"}:
            raise ValueError("An opening needs edge, startMeters and endMeters")
        edge = opening["edge"]
        if isinstance(edge, bool) or not isinstance(edge, int) or not 0 <= edge < len(points):
            raise ValueError("Opening edge is outside the perimeter")
        a, b = points[edge], points[(edge + 1) % len(points)]
        length = math.dist(a, b)
        start = _number(opening["startMeters"], "startMeters", 0, length)
        end = _number(opening["endMeters"], "endMeters", 0, length)
        if end - start < 0.1:
            raise ValueError("An opening must be at least 0.1 m wide")
        normalized.append({"edge": edge, "startMeters": start, "endMeters": end})
        def along(distance: float) -> tuple[float, float]:
            return (a[0] + (b[0] - a[0]) * distance / length,
                    a[1] + (b[1] - a[1]) * distance / length)
        ring = ring.difference(LineString([along(start), along(end)]).buffer(
            thickness * 2, cap_style="flat"))
    normalized.sort(key=lambda item: (item["edge"], item["startMeters"]))
    for left, right in zip(normalized, normalized[1:]):
        if left["edge"] == right["edge"] and left["endMeters"] > right["startMeters"]:
            raise ValueError("Openings on the same edge must not overlap")
    if ring.is_empty:
        raise ValueError("The openings remove every wall")
    # Constrained triangulation preserves concavities, openings and the inner ring.
    triangles = constrained_delaunay_triangles(ring)
    panels = []
    for triangle in triangles.geoms:
        vertices = [(round(x, 9), round(z, 9)) for x, z in list(triangle.exterior.coords)[:-1]]
        vertices.sort()
        panels.append(vertices)
    panels.sort()
    if not panels or len(panels) > 1024:
        raise ValueError("Perimeter geometry exceeds the 1024-panel budget")
    parameters = {"boundarySource": source, "heightMeters": height,
                  "thicknessMeters": thickness, "openings": normalized}
    if source == "polygon":
        parameters["boundary"] = [{"x": x, "z": z} for x, z in points]
    if 'interiorColor' in settings:
        color = settings['interiorColor']
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError('Interior wall color must be a six-digit hex value')
        parameters['interiorColor'] = color.lower()
    if 'exteriorFinish' in settings:
        from .wall_finishes import normalize_exterior_finish
        parameters['exteriorFinish'] = normalize_exterior_finish(
            settings['exteriorFinish'], points, height, normalized, layout)
    return {"version": 1, "settings": parameters,
            "panels": [[{"x": x, "z": z} for x, z in panel] for panel in panels]}


def validate_perimeter_walls(layout: Mapping[str, Any]) -> None:
    extensions = layout.get("extensions") or {}
    if KEY not in extensions:
        return
    value = extensions[KEY]
    if (not isinstance(value, Mapping) or type(value.get("version")) is not int
            or value != compile_perimeter_walls(value.get("settings"), layout)):
        raise ValueError("Perimeter wall geometry does not match its authored settings")


def append_wall_features(shell: dict, layout: Mapping[str, Any]) -> dict:
    value = (layout.get("extensions") or {}).get(KEY)
    if value is None:
        return shell
    validate_perimeter_walls(layout)
    features = shell.setdefault("features", [])
    if any(str(feature.get("featureId", "")).startswith(PREFIX) for feature in features):
        raise ValueError("Shell uses a reserved layout perimeter wall identity")
    floor_y = float((shell.get("coordinateFrame") or {}).get("floorElevation", 0))
    for index, panel in enumerate(value["panels"]):
        features.append({"featureId": PREFIX + str(index), "featureKind": "wall",
                         "geometry": {"boundary": panel, "elevation": floor_y,
                                      "height": value["settings"]["heightMeters"]},
                         "evidence": []})
    return shell
