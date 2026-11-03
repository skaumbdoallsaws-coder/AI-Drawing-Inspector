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
MARK_FIELDS = {"markId", "label", "imagePath", "uv", "x", "z", "widthMeters", "depthMeters", "rotationDegrees"}
MAX_MARKS = 16


def normalize_ground(value):
    if (not isinstance(value, Mapping) or set(value) not in ({"schemaVersion", "surfaces"},
                                                              {"schemaVersion", "surfaces", "marks"})
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
        if not isinstance(item["slopeAxis"], str) or item["slopeAxis"] not in {"x", "z"} or not isinstance(item["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", item["color"]):
            raise ValueError("ground requires slopeAxis x/z and a hex color")
        for other in result:
            if (min(item["maxX"], other["maxX"]) - max(item["minX"], other["minX"]) > 1e-8
                    and min(item["maxZ"], other["maxZ"]) - max(item["minZ"], other["minZ"]) > 1e-8):
                raise ValueError("ground surface interiors must not overlap")
        result.append(item)
    ground = {"schemaVersion": 1, "surfaces": result}
    if "marks" in value:  # optional, so ground stored before marks existed is unchanged
        ground["marks"] = _marks(value["marks"], result)
    return ground


def _marks(rows, surfaces):
    """Images painted flat on the ground, such as a logo or a target on the yard, each centred on a level
    surface. rotationDegrees turns one about the vertical like a floor marking's yaw."""
    from .decals import IMAGE_PATH, LEGACY_IMAGE_PATH

    def number(value, key, low, high):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"ground mark {key} must be a number from {low} to {high}")
        return float(value)
    if not isinstance(rows, list) or len(rows) > MAX_MARKS:
        raise ValueError(f"ground takes at most {MAX_MARKS} marks")
    ids, marks = set(), []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != MARK_FIELDS:
            raise ValueError("ground mark fields are incomplete or unsupported")
        mark_id, label, image, uv = row["markId"], row["label"], row["imagePath"], row["uv"]
        if not isinstance(mark_id, str) or not re.fullmatch(r"gm-[a-z0-9-]{1,80}", mark_id) or mark_id in ids:
            raise ValueError("ground marks need unique gm- identifiers")
        ids.add(mark_id)
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ValueError("ground marks need a short label")
        if not isinstance(image, str) or not (IMAGE_PATH.fullmatch(image) or LEGACY_IMAGE_PATH.fullmatch(image)):
            raise ValueError("a ground mark must use a local content-addressed PNG")
        if not isinstance(uv, list) or len(uv) != 4:
            raise ValueError("ground mark uv needs four fractions")
        uv = [number(v, "uv", 0, 1) for v in uv]
        if uv[2] - uv[0] < .001 or uv[3] - uv[1] < .001:
            raise ValueError("ground mark uv is empty")
        mark = dict(markId=mark_id, label=label.strip(), imagePath=image, uv=uv,
                    x=number(row["x"], "x", -10000, 10000), z=number(row["z"], "z", -10000, 10000),
                    widthMeters=number(row["widthMeters"], "widthMeters", .3, 60),
                    depthMeters=number(row["depthMeters"], "depthMeters", .3, 60),
                    rotationDegrees=number(row["rotationDegrees"], "rotationDegrees", -360, 360))
        if not any(s["startElevation"] == s["endElevation"] and s["minX"] <= mark["x"] <= s["maxX"]
                   and s["minZ"] <= mark["z"] <= s["maxZ"] for s in surfaces):
            raise ValueError(f"ground mark {mark_id} must be centred on a level ground surface")
        marks.append(mark)
    return marks


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
