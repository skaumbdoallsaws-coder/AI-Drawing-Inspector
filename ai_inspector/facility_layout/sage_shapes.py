"""Sage's basic-shape tools (docs/sage-basic-shapes-plan.md, BS3).

author_shape_asset makes one model from a shape family (industrial_assets/shape_families.py), adds it to the shared
library of authored assets (LocalFacilityLayoutHost.register_authored_asset) and returns a picture of it for Sage.
The planners make the models they need the same way and return a summary and operations, which the gateway keeps as
a package for preview_planned_design: one review, the usual validation, Apply directly respected, as with the
ribbon tools' planners (sage_patterns.py). A grid or a roof frame is hundreds of operations, more than a batch Sage
writes itself may hold.
- place_along_line: barriers, beams, trays or pipes along straight lines, one model per distinct length (rule 11).
- place_grid: one item on every point of a grid of lines, steel columns by default. Lines A, B, ... run east-west
  from south to north and lines 1, 2, ... north-south from west to east; points are named "A-1", as Factory 02's
  columns are. Points are left out by name.
- roof_frame: girders on lines and joists across them at a spacing, each layer 2 mm above the one below (rule 1).
The plan's rules from the hand-built runs, as these tools keep them:
- Floor items must stand in an operational zone (rule 3), once the layout has one (the engine asks for it then).
  An item an existing zone already holds stays in it; an item in unzoned floor gets a thin floor-coloured workcell
  strip (#a9adab) that the planner adds itself (decision 2), and the summary says which. An item that would stand in
  a zone whose rules it breaks (its categories, height limit or edge setback) is refused with the zone and the rule:
  a strip of its own would get it past them.
- A package is one apply (operations.MAX_OPERATION_BATCH, 500 operations); a bigger plan is refused, to be split. The
  summary stays well inside what one tool result may hold; the package keeps every operation.
- A floor run stops 5 cm short of a zone that takes no placements (aisle, walkway, exclusion, safety, ...) and goes
  on after it; the summary lists the gaps. A grid places every point it is given; one standing in such a zone is
  named in the summary (BS4 adds the obstacle map that leaves such points out).
- Overhead items (lowest point 4.5 m up or more) skip the floor checks and need no strip (rule 2). Nothing is put
  between the floor and 4.5 m, where it would need something to stand on.
- Yaw-only, unit, unrounded quaternions (rule 6); building structure is placed locked, as Factory 02's was.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import string
from typing import Callable, Mapping, Sequence

from shapely.geometry import Polygon

from ai_inspector.industrial_assets import shape_families as families
from ai_inspector.industrial_assets.primitives import size_of

from .asset_orientation import yaw_quaternion
from .operations import MAX_OPERATION_BATCH
from .spatial import (_NON_PLACEMENT_ZONE_TYPES, OVERHEAD_MINIMUM_CLEARANCE, polygon_boundary_distance,
                      polygon_contains_polygon, polygons_intersect)

AUTHOR_TOOL, LINE_TOOL, GRID_TOOL, ROOF_TOOL = "author_shape_asset", "place_along_line", "place_grid", "roof_frame"
PLANNERS = (LINE_TOOL, GRID_TOOL, ROOF_TOOL)
NAMES = (AUTHOR_TOOL, *PLANNERS)
PREFIXES = {LINE_TOOL: "line", GRID_TOOL: "grid", ROOF_TOOL: "roof"}
LINE_FAMILIES = ("pedestrian_barrier", "low_traffic_barrier", "guard_rail", "i_beam", "open_web_joist", "cable_tray",
                 "pipe_run", "sprinkler_line", "roof_fascia")
POINT_FAMILIES = ("steel_column", "bollard", "tank", "bin", "pallet_stack", "workbench", "high_bay_lights")
OVERHEAD = OVERHEAD_MINIMUM_CLEARANCE
STRIP_COLOR = "#a9adab"
STRIP_MARGIN = 0.03   # a strip reaches 3 cm past its item on every side
CLEARANCE = 0.05      # a floor run stops 5 cm short of a zone that takes no placements
LAYER_GAP = 0.002     # touching volumes collide: each layer 2 mm above the one below (rule 1)
MAX_OPERATIONS = MAX_OPERATION_BATCH   # what one apply takes (500): a bigger package could be staged but not applied
MAX_LINES = 200
LISTED = 60
MODELS_LISTED = 12
RESULT_BUDGET = 48_000   # bytes of summary JSON; the gateway refuses results over 65,536 (codex_result_too_large)
TRIMMED = ("pieces", "gaps", "dropped", "items", "models")   # lists shortened, longest first, when a summary is big
HELD_LISTED = 8       # zones named in "already inside ...", then "and N more"
METHOD = "sage-basic-shapes"
STRUCTURE = "Building Structures"
SIDES = ("center", "left", "right")
NUMBER = {"type": "number", "minimum": -100000, "maximum": 100000}
POINT = {"type": "object", "additionalProperties": False, "required": ["x", "z"],
         "properties": {"x": NUMBER, "z": NUMBER}}
LABEL = {"type": "string", "minLength": 1, "maxLength": 60}
ELEVATION = {"type": "number", "minimum": 0, "maximum": 60}
AXIS_PROPERTIES = {
    "at": {"type": "array", "items": NUMBER, "minItems": 1, "maxItems": MAX_LINES},
    "from": NUMBER, "to": NUMBER, "every": {"type": "number", "minimum": 0.1, "maximum": 500},
    "names": {"type": "array", "items": {"type": "string", "pattern": "^[A-Za-z0-9.]{1,8}$"}, "maxItems": MAX_LINES}}


class ShapeError(ValueError):
    """A shape tool that cannot do what was asked says why; Sage tells the user."""


def _round(value: float, digits: int = 4) -> float:
    result = round(float(value), digits)
    return 0.0 if result == 0 else result


def _point(x: float, z: float) -> dict:
    return {"x": _round(x, 3), "z": _round(z, 3)}


def _namespace(tool: str, arguments: Mapping, revision: str) -> str:
    """Stable per plan: the same request on the same revision gives the same ids (as sage_patterns does)."""
    text = json.dumps({"tool": tool, "arguments": arguments, "revision": revision}, sort_keys=True, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _lettered(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name, index = "", index + 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = string.ascii_uppercase[rest] + name
    return name


def _yaw(along: tuple[float, float]) -> float:
    """The turn that lays a model's length (its x) along `along`: the engine turns x to (cos, -sin)."""
    return math.degrees(math.atan2(-along[1], along[0])) % 360


def _defaults_text(name: str, skip: Sequence[str] = ()) -> str:
    family = families.FAMILIES[name]
    shown = []
    for key, param in family.params.items():
        if key in skip:
            continue
        default = param.default if param.kind != "length" else f"{param.default:g}"
        shown.append(f"{key} {default}")
    return f"{name} ({family.label.lower()}): " + ", ".join(shown)


def tool_specs() -> list[dict]:
    every = "; ".join(_defaults_text(name) for name in families.FAMILIES)
    lines = "; ".join(_defaults_text(name, ("lengthMeters",)) for name in LINE_FAMILIES)
    points = ", ".join(POINT_FAMILIES)
    return [
        {"name": AUTHOR_TOOL, "description": (
            "Make one model from basic shapes and add it to the shared library of authored assets (tagged authored, "
            "reusable in every layout). Use it for structure or simple equipment the library lacks. Returns its "
            "assetId, assetDefinitionRevision, size, the full parameters and a picture of it. The same family and "
            "parameters give the same asset; nothing new is added. Never changes the layout: place a single item "
            "with preview_facility_operations (place_asset; the model's length runs along its x). For runs, grids "
            "and roof frames use place_along_line, place_grid and roof_frame instead: they make their own models. "
            "Models are illustrative only (no structural, impact, fire or load rating). Families, with each "
            "parameter's default (all optional; sizes in metres, colours '#rrggbb'): " + every + "."),
         "input_schema": {"type": "object", "additionalProperties": False, "required": ["family"], "properties": {
             "family": {"enum": list(families.FAMILIES)},
             "parameters": {"type": "object", "description": "Only what differs from the defaults."}}}},
        {"name": LINE_TOOL, "description": (
            "Plan items along straight lines: barriers, guard rails, beams, cable trays, pipes, sprinkler lines. "
            "Each line gets one piece of its exact length (one model per distinct length, made and added to the "
            "library here). lines: from and to in plan metres (x east, z north); label names the run. side: where "
            "the item stands, seen walking from 'from' to 'to': center (on the line, the default), left or right "
            "(the line is an edge, a walkway's say, and the item stands just beside it, 5 cm clear). Barriers along "
            "a walkway: give each edge of the walkway zone as a line, side away from the walkway. elevationMeters: "
            "0 (the default) stands on the floor; overhead items go 4.5 m up or more, 0.002 above whatever they "
            "rest on (touching items collide). On the floor, a run stops short of aisles, walkways and other zones "
            "that take no placements and goes on after them (its gaps are listed), and items on unzoned floor get thin "
            "floor-coloured workcell strips; a plan that puts an item in a zone whose rules it breaks is refused. "
            "Read-only: stage the returned packageId with "
            "preview_planned_design. Families, with their defaults (lengthMeters comes from each line): "
            + lines + "."),
         "input_schema": {"type": "object", "additionalProperties": False, "required": ["family", "lines"],
                          "properties": {
                              "family": {"enum": list(LINE_FAMILIES)},
                              "parameters": {"type": "object"},
                              "lines": {"type": "array", "minItems": 1, "maxItems": MAX_LINES, "items": {
                                  "type": "object", "additionalProperties": False, "required": ["from", "to"],
                                  "properties": {"from": POINT, "to": POINT, "side": {"enum": list(SIDES)},
                                                 "label": LABEL}}},
                              "elevationMeters": ELEVATION}}},
        {"name": GRID_TOOL, "description": (
            "Plan one item on every point of a grid of lines: steel columns by default (family steel_column, 10 m "
            "high). x: the lines running north-south, by their x (named 1, 2, ... from west to east); z: the lines "
            "running east-west, by their z (named A, B, ... from south to north). Give each as at (the positions) "
            "or as from, to and every; names replaces the default names. Points are named like A-1; skip leaves "
            "points out by name. The model is made and added to the library here. elevationMeters: 0 (the default) "
            "stands on the floor, or 4.5 m up or more for overhead items. Floor items on unzoned floor get thin "
            "floor-coloured workcell strips, and a point in a zone whose rules it breaks is refused; points that "
            "stand in an aisle, walkway or other zone that "
            "takes no placements are named in the summary (skip them). Read-only: stage the returned packageId "
            "with preview_planned_design. Families: " + points + "; their parameters are author_shape_asset's."),
         "input_schema": {"type": "object", "additionalProperties": False, "required": ["x", "z"], "properties": {
             "family": {"enum": list(POINT_FAMILIES)}, "parameters": {"type": "object"},
             "x": {"type": "object", "additionalProperties": False, "properties": AXIS_PROPERTIES},
             "z": {"type": "object", "additionalProperties": False, "properties": AXIS_PROPERTIES},
             "skip": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 20},
                      "maxItems": 2000},
             "yawDegrees": {"type": "number", "minimum": -360, "maximum": 360},
             "elevationMeters": ELEVATION, "labelPrefix": LABEL}}},
        {"name": ROOF_TOOL, "description": (
            "Plan a roof frame over an area: steel girders (I-beams) on lines and open-web joists across them at a "
            "spacing, centred in the area. area: its west, east, south and north edges in plan metres. "
            "supportTopMeters: the top of the columns or walls the frame rests on (at least 4.5 m); the girders "
            "sit 2 mm above it and the joists 2 mm above the girders, as touching items collide. girders: along x "
            "(the default: girders run east-west, on z lines named A, B, ... from south to north) or z (north-south, "
            "on x lines named 1, 2, ...), and their lines as at or as from, to and every; use the column lines. "
            "Girders span the area along their direction; joists span it across. joistSpacingMeters: 3 by "
            "default. girder and joist: the I-beam's and the joist's parameters besides their length (depthMeters "
            "and so on, as author_shape_asset lists). Read-only: stage the returned packageId with "
            "preview_planned_design."),
         "input_schema": {"type": "object", "additionalProperties": False,
                          "required": ["area", "supportTopMeters", "girders"], "properties": {
                              "area": {"type": "object", "additionalProperties": False,
                                       "required": ["west", "east", "south", "north"],
                                       "properties": {side: NUMBER for side in ("west", "east", "south", "north")}},
                              "supportTopMeters": {"type": "number", "minimum": 1, "maximum": 60},
                              "girders": {"type": "object", "additionalProperties": False, "properties": {
                                  "along": {"enum": ["x", "z"]}, **AXIS_PROPERTIES}},
                              "joistSpacingMeters": {"type": "number", "minimum": 0.5, "maximum": 20},
                              "girder": {"type": "object"}, "joist": {"type": "object"}}}},
    ]


# --- the layout's zones ---

class _Zones:
    """The layout's zones as polygons: which take no placements, which already hold an item, and whether the engine
    asks floor items for a zone at all (only once the layout has an operational zone: spatial._zone_checks)."""

    def __init__(self, layout: Mapping):
        self.items = []
        for zone in layout.get("zones") or []:
            if not isinstance(zone, Mapping):
                continue
            try:
                polygon = tuple((float(point["x"]), float(point["z"])) for point in zone["boundary"])
            except (KeyError, TypeError, ValueError):
                continue
            if len(polygon) < 3:
                continue
            xs, zs = [p[0] for p in polygon], [p[1] for p in polygon]
            closed = str(zone.get("zoneType") or "") in _NON_PLACEMENT_ZONE_TYPES
            self.items.append((zone, polygon, (min(xs), min(zs), max(xs), max(zs)), closed))
        self.required = any(not closed for *_, closed in self.items)

    @staticmethod
    def name(zone: Mapping) -> str:
        return str(zone.get("label") or zone.get("zoneId") or "a zone")

    def closed(self):
        return [(zone, polygon, box) for zone, polygon, box, closed in self.items if closed]

    def touching(self, polygon) -> list[Mapping]:
        box = _box(polygon)
        return [zone for zone, boundary, bounds, _ in self.items
                if _boxes_meet(box, bounds) and polygons_intersect(boundary, polygon)]

    def closed_touching(self, polygon) -> list[Mapping]:
        box = _box(polygon)
        return [zone for zone, boundary, bounds, closed in self.items
                if closed and _boxes_meet(box, bounds) and polygons_intersect(boundary, polygon)]

    def holding(self, polygon, category: str, top: float) -> Mapping | None:
        """An operational zone that holds this footprint as the engine checks it: inside, past its edge setback,
        open to the category and under its height limit."""
        box = _box(polygon)
        for zone, boundary, bounds, closed in self.items:
            if closed or not (bounds[0] <= box[0] and bounds[1] <= box[1] and box[2] <= bounds[2]
                              and box[3] <= bounds[3]):
                continue
            if not polygon_contains_polygon(boundary, polygon):
                continue
            setbacks = zone.get("edgeSetbacks")
            setback = max((float(v) for v in setbacks.values()), default=0.0) if isinstance(setbacks, Mapping) else 0
            if setback > 1e-9 and polygon_boundary_distance(polygon, boundary) + 1e-9 < setback:
                continue
            allowed = zone.get("allowedAssetCategories")
            if isinstance(allowed, list) and allowed and category not in allowed:
                continue
            limit = zone.get("heightLimit")
            if limit is not None and top > float(zone.get("floorElevation", 0) or 0) + float(limit) + 1e-9:
                continue
            return zone
        return None

    def breaking(self, polygon, category: str, top: float) -> list[str]:
        """The rules this footprint breaks of the operational zones it stands in, wholly or partly: an item there
        gets no strip of its own, which would get it past them."""
        shape, box = Polygon(polygon), _box(polygon)
        broken = []
        for zone, boundary, bounds, closed in self.items:
            if closed or not _boxes_meet(box, bounds) or Polygon(boundary).intersection(shape).area <= 1e-9:
                continue
            name = f"zone '{self.name(zone)}'"
            allowed = zone.get("allowedAssetCategories")
            if isinstance(allowed, list) and allowed and category not in allowed:
                broken.append(f"{name} takes only {', '.join(str(item) for item in allowed)}, not {category}")
            limit = zone.get("heightLimit")
            if limit is not None and top > float(zone.get("floorElevation", 0) or 0) + float(limit) + 1e-9:
                broken.append(f"{name} has a {float(limit):g} m height limit; the item is {top:g} m high")
            setbacks = zone.get("edgeSetbacks")
            setback = max((float(v) for v in setbacks.values()), default=0.0) if isinstance(setbacks, Mapping) else 0
            if setback > 1e-9 and (not polygon_contains_polygon(boundary, polygon)
                                   or polygon_boundary_distance(polygon, boundary) + 1e-9 < setback):
                broken.append(f"{name} keeps items {setback:g} m inside its edges")
        return broken


def _box(polygon) -> tuple[float, float, float, float]:
    xs, zs = [p[0] for p in polygon], [p[1] for p in polygon]
    return min(xs), min(zs), max(xs), max(zs)


def _boxes_meet(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _rectangle(center, along, half_length: float, half_depth: float) -> tuple:
    """Corners counter-clockwise on the plan (x east, z north) of a rectangle turned to `along`."""
    (cx, cz), (dx, dz) = center, along
    lx, lz = -dz, dx
    return tuple((cx + dx * a + lx * b, cz + dz * a + lz * b) for a, b in
                 ((-half_length, -half_depth), (half_length, -half_depth), (half_length, half_depth),
                  (-half_length, half_depth)))


def _clip(points, value):
    """The part of a polygon where value(point) <= 0 (one Sutherland-Hodgman pass)."""
    kept = []
    for index, current in enumerate(points):
        previous = points[index - 1]
        a, b = value(previous), value(current)
        if (a <= 0) != (b <= 0):
            share = a / (a - b)
            kept.append((previous[0] + (current[0] - previous[0]) * share,
                         previous[1] + (current[1] - previous[1]) * share))
        if b <= 0:
            kept.append(current)
    return kept


def _strip(zone_id: str, label: str, corners) -> dict:
    return {"op": "add_zone", "zone": {
        "zoneId": zone_id, "label": label, "zoneType": "workcell", "floorElevation": 0.0, "anchors": [],
        "evidence": [], "boundary": [{"x": _round(x), "z": _round(z)} for x, z in corners],
        "extensions": {"style": {"fillColor": STRIP_COLOR}}}}


def _place(placement_id: str, asset: Mapping, position: Mapping, yaw: float, label: str) -> dict:
    return {"op": "place_asset", "placement": {
        "placementId": placement_id, "assetId": asset["assetId"],
        "assetDefinitionRevision": asset["assetDefinitionRevision"],
        "transform": {"position": {"x": _round(position["x"]), "y": _round(position["y"]),
                                   "z": _round(position["z"])},
                      "quaternion": yaw_quaternion(yaw), "scale": 1},
        "positionMode": "locked" if asset.get("category") == STRUCTURE else "manual", "snapRelationship": None,
        "metadata": {"instanceLabel": label, "inputMethod": METHOD}}}


def _asset_summary(asset: Mapping) -> dict:
    return {"assetId": asset["assetId"], "assetDefinitionRevision": asset["assetDefinitionRevision"],
            "displayName": asset["displayName"], "dimensions": dict(asset["dimensions"]),
            "library": "added" if asset.get("added") else "already there"}


def _parameters(arguments: Mapping, key: str = "parameters", *, without: str | None = None) -> dict:
    value = arguments.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ShapeError(f"{key} must be an object")
    if without and without in value:
        raise ShapeError(f"Leave {without} out of {key}: it comes from the "
                         + ("lines" if key == "parameters" else "area") + ".")
    return dict(value)


def _elevation(arguments: Mapping) -> float:
    value = float(arguments.get("elevationMeters", 0) or 0)
    if 0 < value < OVERHEAD:
        raise ShapeError(f"elevationMeters {value:g}: an item between the floor and {OVERHEAD:g} m up would need "
                         f"something to stand on. Give 0 for the floor, or {OVERHEAD:g} m or more for items hung "
                         "from the roof (0.002 above whatever they rest on).")
    return value


def _validated(family: str, parameters: Mapping) -> dict:
    try:
        return families.resolve(family, dict(parameters))[1]
    except ValueError as error:
        raise ShapeError(f"{family}: {error}") from None


def _containment(zones: _Zones, floor: bool) -> str:
    if not floor:
        return "overhead: no floor zone needed"
    if not zones.required:
        return "this layout has no workcell or other operational zone yet, so floor items need none"
    return "strips"


# --- author_shape_asset ---

def author(make: Callable[[str, dict], Mapping], arguments: Mapping) -> dict:
    """One model into the library. `make` is the host's register_authored_asset. The picture rides along as
    '_image' (the gateway hands it out beside the JSON)."""
    from ai_inspector.industrial_assets.shape_preview import preview

    family = arguments["family"]
    parameters = _parameters(arguments)
    values = _validated(family, parameters)
    asset = make(family, parameters)
    picture, shown = preview(family, parameters)
    record = families.FAMILIES[family]
    length = asset["dimensions"]["width"]
    seen = shown["view"] + (f"; the first {shown['shownLengthMeters']:g} m of its {length:g} m, close up"
                            if "shownLengthMeters" in shown else "")
    return {
        "assetId": asset["assetId"], "assetDefinitionRevision": asset["assetDefinitionRevision"],
        "displayName": asset["displayName"], "family": family, "category": asset["category"],
        "parameters": values, "dimensions": dict(asset["dimensions"]), "triangles": asset["triangles"],
        "overhead": "overhead" in record.tags,
        "library": ("added to the shared library of authored assets" if asset["added"] else
                    "already in the shared library (the same family and parameters): nothing new was added"),
        "picture": f"attached, {seen}",
        "illustrative": record.disclaimer,
        "placing": ("A floor item stands at y 0 inside a workcell or other operational zone (on unzoned floor, add "
                    f"a thin workcell strip zone, fill {STRIP_COLOR}, around it in the same batch; never one around "
                    "an item a zone's rules refuse); an overhead "
                    f"item goes {OVERHEAD:g} m up or more. Its length runs along its x; turn it with yawDegrees."),
        "_image": {"mimeType": "image/jpeg", "data": base64.b64encode(picture).decode("ascii")},
    }


# --- place_along_line ---

def _blocked(zones: _Zones, origin, along, length: float, half_width: float) -> list[tuple[float, float, str]]:
    """Where along a run (0 to length) its band of half_width meets a zone that takes no placements, widened by
    CLEARANCE at both ends: (start, end, zone name)."""
    left = (-along[1], along[0])
    band = _rectangle((origin[0] + along[0] * length / 2, origin[1] + along[1] * length / 2), along,
                      length / 2 + CLEARANCE, half_width)
    box = _box(band)
    found = []
    for zone, polygon, bounds in zones.closed():
        if not _boxes_meet(box, bounds) or not polygons_intersect(polygon, band):
            continue
        local = [((x - origin[0]) * along[0] + (z - origin[1]) * along[1],
                  (x - origin[0]) * left[0] + (z - origin[1]) * left[1]) for x, z in polygon]
        local = _clip(local, lambda p: p[1] - half_width)
        local = _clip(local, lambda p: -p[1] - half_width) if local else local
        if not local:
            continue
        start, end = min(p[0] for p in local) - CLEARANCE, max(p[0] for p in local) + CLEARANCE
        if end >= 0 and start <= length:
            found.append((max(start, 0.0), min(end, length), _Zones.name(zone)))
    return found


def _free(length: float, blocked) -> tuple[list[tuple[float, float]], list[tuple[float, float, list[str]]]]:
    """The stretches of 0..length left between the blocked ones, and the merged gaps with the zones in each."""
    gaps = []
    for start, end, name in sorted(blocked):
        if gaps and start <= gaps[-1][1]:
            gaps[-1] = (gaps[-1][0], max(gaps[-1][1], end), gaps[-1][2] + ([name] if name not in gaps[-1][2] else []))
        else:
            gaps.append((start, end, [name]))
    free, cursor = [], 0.0
    for start, end, _ in gaps:
        if start > cursor + 1e-9:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < length - 1e-9:
        free.append((cursor, length))
    return free, gaps


def plan_line(layout: Mapping, arguments: Mapping, *, revision: str, author: Callable) -> dict:
    family = arguments["family"]
    if family not in LINE_FAMILIES:
        raise ShapeError(f"place_along_line takes {', '.join(LINE_FAMILIES)}; for {family} use place_grid or "
                         "author_shape_asset")
    record = families.FAMILIES[family]
    parameters = _parameters(arguments, without="lengthMeters")
    elevation = _elevation(arguments)
    floor = elevation < OVERHEAD
    shortest, longest = float(record.params["lengthMeters"].low), float(record.params["lengthMeters"].high)
    _validated(family, {**parameters, "lengthMeters": record.params["lengthMeters"].default})
    size = size_of(families.model(family, {**parameters, "lengthMeters": record.params["lengthMeters"].default}))
    depth, height = size["depth"], size["height"]
    zones = _Zones(layout)
    containment = _containment(zones, floor)
    runs, refused = [], []
    for number, line in enumerate(arguments["lines"], start=1):
        start = (float(line["from"]["x"]), float(line["from"]["z"]))
        end = (float(line["to"]["x"]), float(line["to"]["z"]))
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        label = line.get("label") or f"{record.label} {number}"
        if length > longest + 1e-9:
            refused.append(f"line {number} ({label}) is {length:.2f} m long; a piece is at most {longest:g} m: "
                           "split it into shorter lines")
            continue
        if length < shortest - 1e-9:
            refused.append(f"line {number} ({label}) is {length:.3f} m long; a {record.label.lower()} is at least "
                           f"{shortest:g} m")
            continue
        along = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
        side = line.get("side", "center")
        shift = 0.0 if side == "center" else (depth / 2 + CLEARANCE) * (1 if side == "left" else -1)
        origin = (start[0] - along[1] * shift, start[1] + along[0] * shift)
        runs.append((number, label, side, origin, along, length))
    if refused:
        raise ShapeError("; ".join(refused))
    namespace = _namespace(LINE_TOOL, arguments, revision)
    pieces, gaps, dropped = [], [], []
    for number, label, side, origin, along, length in runs:
        stretches, line_gaps = ([(0.0, length)], []) if not floor else _free(
            length, _blocked(zones, origin, along, length, depth / 2 + STRIP_MARGIN))
        for start, end, names in line_gaps:
            gaps.append({"line": label, "from": _point(origin[0] + along[0] * start, origin[1] + along[1] * start),
                         "to": _point(origin[0] + along[0] * end, origin[1] + along[1] * end),
                         "meters": _round(end - start, 2), "zones": names})
        kept = [(start, end) for start, end in stretches if round(end - start, 3) >= shortest]
        for start, end in stretches:
            if round(end - start, 3) < shortest:
                dropped.append({"line": label, "meters": _round(end - start, 3),
                                "reason": f"shorter than the shortest {record.label.lower()} ({shortest:g} m)"})
        if not kept and not any(d["line"] == label for d in dropped):
            dropped.append({"line": label, "meters": _round(length, 3), "reason": "it runs inside "
                            + ", ".join(sorted({name for gap in line_gaps for name in gap[2]})) + " all along"})
        for part, (start, end) in enumerate(kept, start=1):
            piece_label = label if len(kept) == 1 else f"{label} (part {part} of {len(kept)})"
            middle = (start + end) / 2
            pieces.append({"label": piece_label, "length": round(end - start, 3), "along": along,
                           "center": (origin[0] + along[0] * middle, origin[1] + along[1] * middle)})
    if not pieces:
        raise ShapeError("Nothing to place: " + "; ".join(f"{d['line']}: {d['reason']}" for d in dropped))
    assets = {}
    for piece in pieces:
        if piece["length"] not in assets:
            assets[piece["length"]] = author(family, {**parameters, "lengthMeters": piece["length"]})
    strips, placements, held, listed, in_rule_zones = [], [], {}, [], []
    for index, piece in enumerate(pieces, start=1):
        asset = assets[piece["length"]]
        placement_id = f"pl-line-{namespace}-{index}"
        position = {"x": piece["center"][0], "y": elevation, "z": piece["center"][1]}
        placements.append(_place(placement_id, asset, position, _yaw(piece["along"]), piece["label"]))
        stands = None
        if containment == "strips":
            footprint = _rectangle(piece["center"], piece["along"], piece["length"] / 2, depth / 2)
            zone = zones.holding(footprint, asset["category"], elevation + height)
            broken = zones.breaking(footprint, asset["category"], elevation + height) if zone is None else []
            if zone is not None:
                stands = _Zones.name(zone)
                held[stands] = held.get(stands, 0) + 1
            elif broken:
                in_rule_zones.append(f"{piece['label']}: {broken[0]}")
            else:
                corners = _rectangle(piece["center"], piece["along"], piece["length"] / 2 + STRIP_MARGIN,
                                     depth / 2 + STRIP_MARGIN)
                strips.append(_strip(f"zn-line-{namespace}-{len(strips) + 1}", f"Strip - {piece['label']}",
                                     corners))
                stands = "its own strip"
        half = piece["length"] / 2
        if len(listed) < LISTED:
            listed.append({"label": piece["label"], "placementId": placement_id, "lengthMeters": piece["length"],
                           "from": _point(piece["center"][0] - piece["along"][0] * half,
                                          piece["center"][1] - piece["along"][1] * half),
                           "to": _point(piece["center"][0] + piece["along"][0] * half,
                                        piece["center"][1] + piece["along"][1] * half),
                           **({"standsIn": stands} if stands else {})})
    _refuse_breaking(in_rule_zones)
    operations = [*strips, *placements]
    _within_review(operations)
    models = [_asset_summary(asset) for asset in assets.values()]
    return _fit({
        "available": True, "family": family, "elevationMeters": _round(elevation, 3),
        "placed": len(placements), "pieces": listed,
        **({"morePieces": len(placements) - len(listed)} if len(placements) > len(listed) else {}),
        "models": models[:MODELS_LISTED],
        **({"moreModels": len(models) - MODELS_LISTED} if len(models) > MODELS_LISTED else {}),
        "gaps": gaps[:LISTED], **({"moreGaps": len(gaps) - LISTED} if len(gaps) > LISTED else {}),
        "dropped": dropped[:LISTED], **({"moreDropped": len(dropped) - LISTED} if len(dropped) > LISTED else {}),
        "zones": _zones_said(containment, len(strips), held),
        "illustrative": record.disclaimer,
        "operations": operations,
    })


def _refuse_breaking(refused: Sequence[str]) -> None:
    if refused:
        raise ShapeError("These would stand in zones whose rules they break, and a strip of their own would get "
                         "them past those rules: " + "; ".join(refused[:6])
                         + (f"; and {len(refused) - 6} more" if len(refused) > 6 else "")
                         + ". Leave them out (skip, or shorter lines), or choose an item the zone takes.")


def _fit(result: dict) -> dict:
    """The summary within RESULT_BUDGET: the longest of its lists is halved until it fits, its "more..." count
    raised to match. The operations (the package) are never shortened."""
    def size() -> int:
        return len(json.dumps({key: value for key, value in result.items() if key not in ("operations", "_image")}))
    while size() > RESULT_BUDGET:
        lists = [key for key in TRIMMED if isinstance(result.get(key), list) and result[key]]
        if not lists:
            break
        key = max(lists, key=lambda name: len(json.dumps(result[name])))
        keep = len(result[key]) // 2
        more = "more" + key[0].upper() + key[1:]
        result[more] = result.get(more, 0) + len(result[key]) - keep
        result[key] = result[key][:keep]
    return result


def _zones_said(containment: str, strips: int, held: Mapping[str, int]) -> str:
    if containment != "strips":
        return containment
    said = []
    if strips:
        said.append(f"{strips} thin floor-coloured workcell strip{'s' if strips != 1 else ''} added "
                    f"({STRIP_COLOR}), as no zone held {'those items' if strips != 1 else 'that item'}")
    if held:
        named = list(held.items())
        shown = ", ".join(f"{name} ({count})" for name, count in named[:HELD_LISTED])
        if len(named) > HELD_LISTED:
            rest = named[HELD_LISTED:]
            shown += f" and {len(rest)} more zones ({sum(count for _, count in rest)} items)"
        said.append("already inside " + shown)
    return "; ".join(said) or "no floor items"


def _within_review(operations: Sequence) -> None:
    if len(operations) > MAX_OPERATIONS:
        raise ShapeError(f"That is {len(operations)} operations; one apply takes at most {MAX_OPERATIONS}. Split it "
                         "into parts (fewer lines, or the grid area by area) and stage each.")


# --- place_grid ---

def _axis(spec: Mapping, axis: str, *, lettered: bool) -> list[tuple[str, float]]:
    """Named grid lines (name, position) from west to east or south to north."""
    if not isinstance(spec, Mapping):
        raise ShapeError(f"{axis} must be an object")
    stepped = [key for key in ("from", "to", "every") if key in spec]
    if "at" in spec:
        if stepped:
            raise ShapeError(f"{axis}: give at, or from, to and every, not both")
        positions = [float(value) for value in spec["at"]]
    elif len(stepped) == 3:
        start, stop, every = float(spec["from"]), float(spec["to"]), float(spec["every"])
        if stop < start:
            raise ShapeError(f"{axis}: to ({stop:g}) is before from ({start:g})")
        count = int(math.floor((stop - start) / every + 1e-9)) + 1
        if count > MAX_LINES:
            raise ShapeError(f"{axis}: that is {count} lines; at most {MAX_LINES}")
        positions = [start + step * every for step in range(count)]
    else:
        raise ShapeError(f"{axis}: give at (the line positions) or from, to and every")
    names = spec.get("names")
    if names is not None and len(names) != len(positions):
        raise ShapeError(f"{axis}: {len(names)} names for {len(positions)} lines")
    pairs = sorted(zip(names or [None] * len(positions), positions), key=lambda pair: pair[1])
    for (_, first), (_, second) in zip(pairs, pairs[1:]):
        if second - first < 0.01:
            raise ShapeError(f"{axis}: two lines at {first:g} and {second:g}")
    named = [(name if name is not None else (_lettered(index) if lettered else str(index + 1)), position)
             for index, (name, position) in enumerate(pairs)]
    if len({name for name, _ in named}) != len(named):
        raise ShapeError(f"{axis}: the names must differ")
    seen = {}
    for name, _ in named:                       # placement ids take the names in lower case
        if name.lower() in seen:
            raise ShapeError(f"{axis}: the names {seen[name.lower()]!r} and {name!r} differ only in case; "
                             "give names that differ otherwise")
        seen[name.lower()] = name
    return [(name, _round(position)) for name, position in named]


def _key(name: str) -> str:
    return re.sub(r"[\s-]+", "", str(name)).upper()


def _skipped(points: Sequence[tuple[str, float, float]], skip: Sequence[str]) -> set[str]:
    exact = {name for name, _, _ in points}
    loose = {}
    for name, _, _ in points:
        loose.setdefault(_key(name), []).append(name)
    chosen, unknown = set(), []
    for wanted in skip:
        if wanted in exact:
            chosen.add(wanted)
        elif len(loose.get(_key(wanted), [])) == 1:
            chosen.add(loose[_key(wanted)][0])
        else:
            unknown.append(wanted)
    if unknown:
        raise ShapeError(f"No grid point {', '.join(repr(name) for name in unknown[:10])}; the points run from "
                         f"{points[0][0]} to {points[-1][0]} (row letter, then the line number)")
    return chosen


def plan_grid(layout: Mapping, arguments: Mapping, *, revision: str, author: Callable) -> dict:
    family = arguments.get("family", "steel_column")
    if family not in POINT_FAMILIES:
        raise ShapeError(f"place_grid takes {', '.join(POINT_FAMILIES)}; for {family} use place_along_line")
    record = families.FAMILIES[family]
    parameters = _parameters(arguments)
    _validated(family, parameters)
    elevation = _elevation(arguments)
    floor = elevation < OVERHEAD
    columns = _axis(arguments["x"], "x", lettered=False)
    rows = _axis(arguments["z"], "z", lettered=True)
    points = [(f"{row}-{column}", x, z) for row, z in rows for column, x in columns]
    skipped = _skipped(points, arguments.get("skip") or [])
    kept = [point for point in points if point[0] not in skipped]
    if not kept:
        raise ShapeError("Every grid point is skipped; nothing to place")
    zones = _Zones(layout)
    containment = _containment(zones, floor)
    if len(kept) > MAX_OPERATIONS:
        _within_review(kept)
    asset = author(family, parameters)
    width, depth, height = (asset["dimensions"][key] for key in ("width", "depth", "height"))
    yaw = float(arguments.get("yawDegrees", 0) or 0) % 360
    turn = math.radians(yaw)
    along = (math.cos(turn), -math.sin(turn))       # where the model's x points
    reach_x = abs(along[0]) * width / 2 + abs(along[1]) * depth / 2
    reach_z = abs(along[1]) * width / 2 + abs(along[0]) * depth / 2
    namespace = _namespace(GRID_TOOL, arguments, revision)
    prefix = arguments.get("labelPrefix") or ("Column" if family == "steel_column" else record.label)
    placements, inside, held = [], [], {}
    for name, x, z in kept:
        footprint = _rectangle((x, z), along, width / 2, depth / 2)
        placements.append(_place(f"pl-grid-{namespace}-{name.lower()}", asset, {"x": x, "y": elevation, "z": z},
                                 yaw, f"{prefix} {name}"))
        if floor:
            for zone in zones.closed_touching(footprint):
                inside.append({"point": name, "zone": _Zones.name(zone)})
    strips, refused = [], []
    if containment == "strips":
        by_row = len(columns) >= len(rows)     # strips run along the lines with the most points
        lines = rows if by_row else columns
        for line_name, line_at in lines:
            run, count = [], 0
            members = [p for p in kept if (p[2] == line_at if by_row else p[1] == line_at)]
            members.sort(key=lambda p: p[1] if by_row else p[2])
            for point in members + [None]:
                if point is not None:
                    footprint = _rectangle((point[1], point[2]), along, width / 2, depth / 2)
                    zone = zones.holding(footprint, asset["category"], elevation + height)
                    if zone is not None:
                        held[_Zones.name(zone)] = held.get(_Zones.name(zone), 0) + 1
                        point = "held"
                    else:
                        broken = zones.breaking(footprint, asset["category"], elevation + height)
                        if broken:
                            refused.append(f"{prefix} {point[0]}: {broken[0]}")
                            point = "held"           # no strip; the plan is refused below
                if point not in (None, "held") and (not run or not zones.touching(
                        _box_corners(_grid_box(run[0], point, reach_x, reach_z)))):
                    run.append(point)
                    continue
                if run:
                    count += 1
                    strips.append((line_name, count, _grid_box(run[0], run[-1], reach_x, reach_z)))
                run = [point] if point not in (None, "held") else []
        named = {}
        for line_name, _, _ in strips:
            named[line_name] = named.get(line_name, 0) + 1
        strips = [_strip(f"zn-grid-{namespace}-{index}",
                         f"{prefix} strip {line_name}" + (f" ({count})" if named[line_name] > 1 else ""),
                         _box_corners(box))
                  for index, (line_name, count, box) in enumerate(strips, start=1)]
    _refuse_breaking(refused)
    operations = [*strips, *placements]
    _within_review(operations)
    return _fit({
        "available": True, "family": family, "model": _asset_summary(asset),
        "elevationMeters": _round(elevation, 3), "yawDegrees": _round(yaw, 3),
        "lines": {"x": [{"name": name, "x": at} for name, at in columns],
                  "z": [{"name": name, "z": at} for name, at in rows]},
        "points": len(points), "placed": len(placements), "skipped": sorted(skipped),
        "items": [{"name": name, **_point(x, z)} for name, x, z in kept[:LISTED]],
        **({"moreItems": len(kept) - LISTED} if len(kept) > LISTED else {}),
        **({"standInNoPlacementZones": inside[:LISTED],
            "note": "The preview refuses an item standing in an aisle, walkway or other zone that takes no "
                    "placements: plan again with those points in skip."} if inside else {}),
        "zones": _zones_said(containment, len(strips), held),
        "illustrative": record.disclaimer,
        "operations": operations,
    })


def _grid_box(first, last, reach_x: float, reach_z: float) -> tuple[float, float, float, float]:
    xs, zs = (first[1], last[1]), (first[2], last[2])
    return (min(xs) - reach_x - STRIP_MARGIN, min(zs) - reach_z - STRIP_MARGIN,
            max(xs) + reach_x + STRIP_MARGIN, max(zs) + reach_z + STRIP_MARGIN)


def _box_corners(box) -> tuple:
    west, south, east, north = box
    return ((west, south), (east, south), (east, north), (west, north))


# --- roof_frame ---

def plan_roof(layout: Mapping, arguments: Mapping, *, revision: str, author: Callable) -> dict:
    area = {side: float(arguments["area"][side]) for side in ("west", "east", "south", "north")}
    if area["east"] - area["west"] < 1 or area["north"] - area["south"] < 1:
        raise ShapeError("area: east must be at least 1 m past west and north at least 1 m past south")
    support = float(arguments["supportTopMeters"])
    base = support + LAYER_GAP
    if base < OVERHEAD:
        raise ShapeError(f"supportTopMeters {support:g}: a roof frame rests on columns or walls at least "
                         f"{OVERHEAD:g} m high")
    girders = arguments["girders"]
    along_x = girders.get("along", "x") == "x"
    span = (area["west"], area["east"]) if along_x else (area["south"], area["north"])
    across = (area["south"], area["north"]) if along_x else (area["west"], area["east"])
    lines = _axis({key: value for key, value in girders.items() if key != "along"}, "girders", lettered=along_x)
    outside = [f"{name} at {at:g}" for name, at in lines if not across[0] - 1e-6 <= at <= across[1] + 1e-6]
    if outside:
        raise ShapeError(f"girders: {', '.join(outside)} lie outside the area ({across[0]:g} to {across[1]:g})")
    girder_parameters = _parameters(arguments, "girder", without="lengthMeters")
    joist_parameters = _parameters(arguments, "joist", without="lengthMeters")
    girder_length, joist_length = round(span[1] - span[0], 3), round(across[1] - across[0], 3)
    for family, parameters, length in (("i_beam", girder_parameters, girder_length),
                                       ("open_web_joist", joist_parameters, joist_length)):
        if length > 400:
            raise ShapeError(f"The area is {length:g} m across for a {families.FAMILIES[family].label.lower()}; "
                             "one piece is at most 400 m: split the area")
        _validated(family, {**parameters, "lengthMeters": length})
    spacing = float(arguments.get("joistSpacingMeters", 3.0) or 3.0)
    extent = span[1] - span[0]
    count = max(1, int(math.floor(extent / spacing + 1e-9)))
    first = span[0] + (extent - (count - 1) * spacing) / 2
    positions = [first + step * spacing for step in range(count)]
    if len(lines) + count > MAX_OPERATIONS:
        _within_review(range(len(lines) + count))
    girder = author("i_beam", {**girder_parameters, "lengthMeters": girder_length})
    joist = author("open_web_joist", {**joist_parameters, "lengthMeters": joist_length})
    girder_top = base + girder["dimensions"]["height"]
    joist_base = girder_top + LAYER_GAP
    joist_top = joist_base + joist["dimensions"]["height"]
    namespace = _namespace(ROOF_TOOL, arguments, revision)
    girder_way = (1.0, 0.0) if along_x else (0.0, 1.0)
    joist_way = (0.0, 1.0) if along_x else (1.0, 0.0)
    middle_span, middle_across = (span[0] + span[1]) / 2, (across[0] + across[1]) / 2
    operations = []
    for name, at in lines:
        position = ({"x": middle_span, "y": base, "z": at} if along_x else {"x": at, "y": base, "z": middle_span})
        operations.append(_place(f"pl-roof-{namespace}-girder-{name.lower()}", girder, position, _yaw(girder_way),
                                 f"Roof girder {name}"))
    for number, at in enumerate(positions, start=1):
        position = ({"x": at, "y": joist_base, "z": middle_across} if along_x else
                    {"x": middle_across, "y": joist_base, "z": at})
        operations.append(_place(f"pl-roof-{namespace}-joist-{number:03d}", joist, position, _yaw(joist_way),
                                 f"Roof joist {number}"))
    return {
        "available": True,
        "area": {key: _round(value, 3) for key, value in area.items()},
        "girders": {"count": len(lines), "run": "east-west" if along_x else "north-south",
                    "lines": [{"name": name, ("z" if along_x else "x"): at} for name, at in lines],
                    "model": _asset_summary(girder), "bottomMeters": _round(base, 4),
                    "topMeters": _round(girder_top, 4)},
        "joists": {"count": count, "run": "north-south" if along_x else "east-west",
                   "spacingMeters": _round(spacing, 3),
                   ("firstX" if along_x else "firstZ"): _round(positions[0], 3),
                   ("lastX" if along_x else "lastZ"): _round(positions[-1], 3),
                   "model": _asset_summary(joist), "bottomMeters": _round(joist_base, 4),
                   "topMeters": _round(joist_top, 4)},
        "layers": (f"supports to {support:g} m; girders {base:.3f}-{girder_top:.3f} m; joists "
                   f"{joist_base:.3f}-{joist_top:.3f} m (2 mm between layers)"),
        "placed": len(operations),
        "illustrative": families.STRUCTURAL,
        "operations": operations,
    }


def plan(name: str, layout: Mapping, arguments: Mapping, *, revision: str, author: Callable) -> dict:
    if name == LINE_TOOL:
        return plan_line(layout, arguments, revision=revision, author=author)
    if name == GRID_TOOL:
        return plan_grid(layout, arguments, revision=revision, author=author)
    if name == ROOF_TOOL:
        return plan_roof(layout, arguments, revision=revision, author=author)
    raise ShapeError(f"unknown shape planner {name}")

