"""Cosmetic floor finishes; never replace ground levels or load-bearing geometry."""
from collections.abc import Mapping
import re
from .perimeter_walls import _number

KEY = "facilityFloorSurfaces"
FIELDS = {"surfaceId", "label", "boundary", "elevation", "material", "color", "roughness"}


def normalize_floor_surfaces(value, layout):
    from shapely.geometry import Polygon, box
    from .plan_settings import plan_settings_from_layout
    from .ground import normalize_ground, supports_footprint
    if not isinstance(value, Mapping) or set(value) != {"version", "surfaces"} or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Floor finishes require version 1 and surfaces")
    if not isinstance(value["surfaces"], list) or len(value["surfaces"]) > 128:
        raise ValueError("At most 128 floor finishes are supported")
    plan = plan_settings_from_layout(layout)
    ground = layout.get("extensions", {}).get("facilityGround")
    if ground: ground = normalize_ground(ground)
    if value["surfaces"] and not plan and not ground: raise ValueError("Set the facility plan dimensions or ground first")
    result, shapes, ids = [], [], set()
    for row in value["surfaces"]:
        if not isinstance(row, Mapping) or set(row) != FIELDS: raise ValueError("Unsupported floor finish fields")
        sid = row["surfaceId"]
        if not isinstance(sid, str) or not re.fullmatch(r"fs-[a-z0-9-]{1,76}", sid) or sid in ids: raise ValueError("Floor surfaces need unique stable IDs")
        ids.add(sid)
        if not isinstance(row["label"], str) or not row["label"].strip() or len(row["label"]) > 120: raise ValueError("Enter a floor surface name")
        if row["material"] not in ("concrete", "rubber", "turf", "paving", "wood", "solid"): raise ValueError("Unsupported floor material")
        if not isinstance(row["color"], str) or not re.fullmatch(r"#[a-fA-F0-9]{6}", row["color"]): raise ValueError("Choose a six-digit floor color")
        if not isinstance(row["boundary"], list) or not 3 <= len(row["boundary"]) <= 128: raise ValueError("A floor surface needs 3 to 128 vertices")
        points = []
        for point in row["boundary"]:
            if not isinstance(point, Mapping) or set(point) != {"x", "z"}: raise ValueError("Floor vertices require x and z")
            points.append(tuple(_number(point[k], "boundary."+k, -10000, 10000) for k in ("x", "z")))
        polygon = Polygon(points)
        if not polygon.is_valid or polygon.area < .01 or len(set(points)) != len(points): raise ValueError("Floor boundary must be a simple, nonzero-area polygon")
        if not ground and not box(0,0,plan["widthMeters"],plan["depthMeters"]).buffer(1e-8).covers(polygon): raise ValueError("Floor surface is outside the facility plan")
        elevation = _number(row["elevation"], "Floor elevation", -1000, 1000)
        if ground:
            if not supports_footprint(ground, points, elevation): raise ValueError("Floor finish must lie on flat, continuous ground at its elevation")
        elif abs(elevation-float(layout.get("coordinateFrame", {}).get("floorElevation", 0))) > 1e-6:
            raise ValueError("Floor finish elevation must match the existing floor")
        if any(polygon.intersection(shape).area > 1e-8 for shape in shapes): raise ValueError("Floor finishes must not overlap")
        shapes.append(polygon)
        result.append(dict(row,label=row["label"].strip(),boundary=[dict(x=x,z=z) for x,z in points],color=row["color"].lower(),
            elevation=elevation,roughness=_number(row["roughness"],"Roughness",0,1)))
    return dict(version=1,surfaces=result)
