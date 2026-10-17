"""Authored, non-overlapping rectangular ground levels and straight ramps.

These are geometric surfaces, not structural, drainage, or accessibility ratings.
Sloping surfaces support navigation; parking rigid assets on slopes is unsupported.
"""
from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
import json
import math
import re

KEY = "facilityGround"
FIELDS = {"surfaceId", "minX", "maxX", "minZ", "maxZ", "startElevation",
          "endElevation", "slopeAxis", "color"}


def normalize_ground(value):
    if (not isinstance(value, Mapping) or set(value) != {"schemaVersion", "surfaces"}
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1):
        raise ValueError("ground requires schemaVersion 1 and surfaces")
    rows = value["surfaces"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise ValueError("ground requires 1..256 surfaces")
    ids, result = set(), []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != FIELDS:
            raise ValueError("ground surface fields are incomplete or unsupported")
        sid = row["surfaceId"]
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", sid) or sid in ids:
            raise ValueError("ground surface IDs must be unique stable identifiers")
        ids.add(sid)
        item = dict(row)
        for key in FIELDS - {"surfaceId", "color", "slopeAxis"}:
            number = row[key]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or abs(number) > 10000:
                raise ValueError(f"ground {key} must be a bounded finite number")
            item[key] = float(number)
        if item["maxX"] <= item["minX"] or item["maxZ"] <= item["minZ"]:
            raise ValueError("ground rectangle must have positive dimensions")
        if item["slopeAxis"] not in {"x", "z"} or not isinstance(item["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", item["color"]):
            raise ValueError("ground requires slopeAxis x/z and a hex color")
        for other in result:
            if (min(item["maxX"], other["maxX"]) - max(item["minX"], other["minX"]) > 1e-8
                    and min(item["maxZ"], other["maxZ"]) - max(item["minZ"], other["minZ"]) > 1e-8):
                raise ValueError("ground surface interiors must not overlap")
        result.append(item)
    return {"schemaVersion": 1, "surfaces": result}


def apply_ground_to_shell(shell, layout):
    value = layout.get("extensions", {}).get(KEY)
    if value is None:
        return
    ground = normalize_ground(value)
    shell.setdefault("extensions", {})[KEY] = ground
    features = [f for f in shell.get("features", []) if f.get("featureKind") not in {"floor", "floor_surface"}]
    for s in ground["surfaces"]:
        if s["startElevation"] != s["endElevation"]:
            continue
        features.append(dict(featureId=s["surfaceId"], featureKind="floor_surface", evidence=[],
            geometry=dict(elevation=s["startElevation"], boundary=[
                dict(x=s["minX"], z=s["minZ"]), dict(x=s["maxX"], z=s["minZ"]),
                dict(x=s["maxX"], z=s["maxZ"]), dict(x=s["minX"], z=s["maxZ"])])))
    shell["features"] = features


@lru_cache(maxsize=8)
def _support_regions(serialized):
    from shapely.geometry import box
    from shapely.ops import unary_union
    groups = {}
    for s in json.loads(serialized)["surfaces"]:
        if s["startElevation"] == s["endElevation"]:
            groups.setdefault(s["startElevation"], []).append(box(s["minX"], s["minZ"], s["maxX"], s["maxZ"]))
    return {y: unary_union(polygons) for y, polygons in groups.items()}


def supports_footprint(ground, points, elevation, feature_id=None):
    """Allow crossing adjacent coplanar tiles, never a gap, slope or level step."""
    for s in ground["surfaces"]:
        if (s["startElevation"] == s["endElevation"] and abs(s["startElevation"]-elevation) <= 1e-6
                and (not feature_id or s["surfaceId"] == feature_id)
                and all(s["minX"]-1e-8 <= x <= s["maxX"]+1e-8
                        and s["minZ"]-1e-8 <= z <= s["maxZ"]+1e-8 for x,z in points)):
            return True
    from shapely.geometry import Polygon
    value = ground
    if feature_id:
        value = deepcopy(ground)
        value["surfaces"] = [s for s in value["surfaces"] if s["surfaceId"] == feature_id]
    regions = _support_regions(json.dumps(value, sort_keys=True))
    footprint = Polygon(points)
    return any(abs(y - elevation) <= 1e-6 and shape.buffer(1e-8).covers(footprint)
               for y, shape in regions.items())
