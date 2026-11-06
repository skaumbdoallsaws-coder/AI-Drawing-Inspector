"""Straight, measured interior partitions with full-height door openings."""
from collections.abc import Mapping
import math
import re

from .perimeter_walls import _number

KEY = "facilityInteriorWalls"
PREFIX = "layout-interior-wall-"
FIELDS = {"wallId", "label", "start", "end", "heightMeters", "thicknessMeters", "baseElevation", "color", "openings"}


def compile_interior_walls(value, layout, footing=None):
    """VALUE (version 1 and its walls, without panels) checked against LAYOUT and given its panels. FOOTING is
    LAYOUT's (ground.layout_footing), given by a caller that checks many values against one layout."""
    from shapely.geometry import LineString
    from .ground import layout_footing
    if not isinstance(value, Mapping) or set(value) != {"version", "walls"} or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Interior walls require version 1 and walls")
    if not isinstance(value["walls"], list) or len(value["walls"]) > 128:
        raise ValueError("At most 128 interior walls are supported")
    footing = footing or layout_footing(layout)
    plan, stands = footing["plan"], footing["stands"]
    if value["walls"] and not plan:
        raise ValueError("Set plan dimensions before adding interior walls")
    result, ids = [], set()
    for wall in value["walls"]:
        if not isinstance(wall, Mapping) or set(wall) != FIELDS:
            raise ValueError("Unsupported interior wall fields")
        wid = wall["wallId"]
        if not isinstance(wid, str) or not re.fullmatch(r"iw-[a-z0-9-]{1,76}", wid) or wid in ids:
            raise ValueError("Interior walls need unique stable IDs")
        ids.add(wid)
        if not isinstance(wall["label"], str) or not wall["label"].strip() or len(wall["label"]) > 120:
            raise ValueError("Wall name must contain 1 to 120 characters")
        points = []
        for key in ("start", "end"):
            point = wall[key]
            if not isinstance(point, Mapping) or set(point) != {"x", "z"}:
                raise ValueError("Wall endpoints require x and z")
            points.append(tuple(_number(point[k], key+"."+k, -10000, 10000) for k in ("x", "z")))
        a, b = points
        length = math.dist(a, b)
        if length < .1: raise ValueError("Wall must be at least 0.1 m long")
        height = _number(wall["heightMeters"], "Wall height", .5, 30)
        thickness = _number(wall["thicknessMeters"], "Wall thickness", .05, 2)
        base = _number(wall["baseElevation"], "Wall elevation", -1000, 1000)
        if not isinstance(wall["color"], str) or not re.fullmatch(r"#[a-fA-F0-9]{6}", wall["color"]):
            raise ValueError("Wall color must be a six-digit color")
        openings = wall["openings"]
        if not isinstance(openings, list) or len(openings) > 32:
            raise ValueError("At most 32 openings per wall are supported")
        normalized = []
        for opening in openings:
            if not isinstance(opening, Mapping) or set(opening) != {"startMeters", "endMeters"}:
                raise ValueError("An opening needs startMeters and endMeters")
            start = _number(opening["startMeters"], "Opening start", 0, length)
            end = _number(opening["endMeters"], "Opening end", 0, length)
            if end-start < .1: raise ValueError("Opening must be at least 0.1 m wide")
            normalized.append(dict(startMeters=start, endMeters=end))
        normalized.sort(key=lambda o: o["startMeters"])
        spans, cursor = [], 0
        for opening in normalized:
            if opening["startMeters"] < cursor: raise ValueError("Wall openings must not overlap")
            if opening["startMeters"] > cursor: spans.append((cursor, opening["startMeters"]))
            cursor = opening["endMeters"]
        if cursor < length: spans.append((cursor, length))
        if not spans: raise ValueError("The openings remove the entire wall")
        panels = []
        for start, end in spans:
            def along(t): return (a[0]+(b[0]-a[0])*t/length, a[1]+(b[1]-a[1])*t/length)
            shape = LineString([along(start), along(end)]).buffer(thickness/2, cap_style="flat")
            if not footing["area"].covers(shape):
                raise ValueError("Interior wall thickness extends outside the facility plan")
            vertices = list(shape.exterior.coords)[:-1]
            if stands and not stands(vertices, base):
                raise ValueError("Interior wall must rest on a flat ground surface at its base elevation")
            if not stands and abs(base-float(footing["floor"])) > 1e-6:
                raise ValueError("Interior wall base must match the floor elevation")
            panels.append([dict(x=round(x,9), z=round(z,9)) for x,z in vertices])
        result.append(dict(wall, label=wall["label"].strip(), start=dict(x=a[0],z=a[1]),end=dict(x=b[0],z=b[1]),
            heightMeters=height, thicknessMeters=thickness, baseElevation=base, color=wall["color"].lower(),openings=normalized,panels=panels))
    return dict(version=1, walls=result)


def validate_interior_walls(layout):
    value = layout.get("extensions", {}).get(KEY)
    if value is None: return
    if not isinstance(value, Mapping) or not isinstance(value.get("walls"), list):
        raise ValueError("Invalid interior walls")
    authored = dict(value, walls=[{k:v for k,v in w.items() if k != "panels"} for w in value["walls"] if isinstance(w, Mapping)])
    if compile_interior_walls(authored, layout) != value:
        raise ValueError("Interior wall geometry does not match its settings")


def append_interior_features(shell, layout):
    validate_interior_walls(layout)
    features = shell.setdefault("features", [])
    if any(str(f.get("featureId", "")).startswith(PREFIX) for f in features):
        raise ValueError("Shell uses a reserved interior wall identity")
    for wall in layout.get("extensions", {}).get(KEY, {}).get("walls", []):
        for index, panel in enumerate(wall["panels"]):
            features.append(dict(featureId=PREFIX+wall["wallId"]+"-"+str(index),featureKind="wall",evidence=[],
                geometry=dict(boundary=panel,elevation=wall["baseElevation"],height=wall["heightMeters"])))
