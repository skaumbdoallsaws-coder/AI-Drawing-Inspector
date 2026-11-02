"""Sage shows the user an area in 3D (docs/sage-basic-shapes-plan.md, Part B): SV0's framing on the server, for the
live view of SV3b. When the user asks to see something ("show me Assembly Cell A06", "show me what you changed"),
show_facility_views frames views of it here, and the app glides the user's 3D view to the first one and keeps a Back
button (static/facility_layout_workspace.js, showSageView). No pictures yet: those are SV1 and SV2.

Framing, per the plan's rules from the hand-made shots:
- The items are grouped into areas by distance (closer than GROUP_GAP share one), up to MAX_VIEWS, largest first,
  each named after its zone.
- The camera looks at the centre of the area, a third of the way up its items, from 25-35 degrees above, with a 50
  degree field of view, as close as keeps the area's box in the frame with a margin (FILL, on a canvas ASPECT wide).
- It tries 8 compass directions, south first, and keeps the first whose sight line, in plan, crosses no item or wall
  taller than the line where it crosses (what is in the area itself never counts).
- Inside the hall the camera stays below the overhead items (the lights, trays and roof members, less a margin), so
  the roof stays on. When no such view is clear, the next tier looks down through the roof with the roof layer
  hidden (overhead items no longer block), and last a high view from the south.
The same layout revision and ids always give the same views.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping, Sequence

from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from . import layout_patterns as lp

TOOL = "show_facility_views"
FOV = 50.0                  # vertical field of view, degrees
ASPECT = 1.4                # the 3D canvas beside the chat pane: narrower than 16:9, so a wider screen only adds room
FILL = 0.85                 # the area's box fills at most 85% of the frame each way
ELEVATIONS = (30.0, 25.0, 35.0)  # degrees above the target, in the order tried
HIGH_ELEVATION = 60.0       # the last resort: from the south, from high above
HEADINGS = (("south", 180.0), ("south-east", 135.0), ("south-west", 225.0), ("east", 90.0), ("west", 270.0),
            ("north-east", 45.0), ("north-west", 315.0), ("north", 0.0))  # where the camera stands; 0 is north (+z)
NEAREST = 5.0               # metres: a camera comes no closer to its target
GROUP_GAP = 8.0             # metres: items closer than this share a view
EDGE = 0.5                  # metres round an area where its own neighbours do not block the view
WALL_HALF = 0.15            # metres: half a wall's thickness, for its line
SIGHT_HALF = 0.75           # metres: the sight line is a corridor this far each side, so it never grazes a wall
CEILING_MARGIN = 0.5        # metres below the lowest overhead item, inside the hall
LOWEST_CEILING = 3.0        # an "overhead" item lower than this is not a ceiling (a mislabelled one)
STRUCTURE = frozenset({"Building Structures"})  # columns, walls, roof members: not part of a zone's own items
MAX_VIEWS, DEFAULT_VIEWS = 6, 4
LISTED_IDS = 40


def tool_spec() -> dict:
    return {"name": TOOL, "description": (
        "Move the user's live 3D view to what they ask to see: only when the user asks to see, show, look at or go "
        "to something (\"show me Assembly Cell A06\", \"take me to the dock doors\", \"show me what you changed\"); "
        "never on your own. query: what the user named, in their words (\"R03 robot\", \"Assembly Cell A06\", "
        "\"the dock doors\"); the server matches zone, floor-marking and equipment names (the whole name first, "
        "else every word, zones first) and a zone brings what stands in it. Or targetIds: ids you already hold. Or "
        "target last_change: what the last change saved in this window made or changed (with none in this window, "
        "the layout's last saved change). Give one of the three. The tool frames up to maxViews "
        "areas (default 4), largest first, each named after its zone; the app glides the user's 3D view to the "
        "first and shows a Back button that returns to their view before. liveView says whether the view moved: "
        "say where it went in one sentence, or that nothing moved. There are no pictures: you have not seen these "
        "areas, so never describe how they look."),
        "input_schema": {"type": "object", "properties": {
            "targetIds": {"type": "array", "minItems": 1, "maxItems": 240, "uniqueItems": True,
                          "items": {"type": "string", "minLength": 1, "maxLength": 128}},
            "target": {"enum": ["last_change"]},
            "query": {"type": "string", "minLength": 1, "maxLength": 120},
            "maxViews": {"type": "integer", "minimum": 1, "maximum": MAX_VIEWS}},
            "additionalProperties": False}}


# ---------------------------------------------------------------- the layout's shapes

def _definition(record: Mapping) -> Mapping:
    value = record.get("definition")
    return value if isinstance(value, Mapping) else record


def _tags(record: Mapping | None) -> set:
    if not record:
        return set()
    return {str(tag) for tag in (_definition(record).get("tags") or record.get("tags") or [])}


def _category(record: Mapping | None) -> Any:
    return (record or {}).get("category") or _definition(record or {}).get("category")


def records_by_asset(catalog: Iterable[Mapping]) -> dict:
    """The catalog as light_positions and light_coverage read it: by assetId and by (assetId, revision)."""
    found = {}
    for record in catalog or []:
        if isinstance(record, Mapping) and isinstance(record.get("assetId"), str):
            found.setdefault(record["assetId"], record)
            found[(record["assetId"], record.get("assetDefinitionRevision"))] = record
    return found


def _record(records: Mapping, placement: Mapping) -> Mapping | None:
    """The placement's catalog record, at its own revision when the catalog has it; framing needs only its size."""
    return (records.get((placement.get("assetId"), placement.get("assetDefinitionRevision")))
            or records.get(placement.get("assetId")))


def _name(entity: Mapping, fallback: str) -> str:
    metadata = entity.get("metadata") if isinstance(entity.get("metadata"), Mapping) else {}
    text = metadata.get("instanceLabel") or entity.get("label") or entity.get("displayName")
    return str(text) if text else fallback


def _placement_solid(placement: Mapping, record: Mapping | None) -> dict | None:
    """The placement's plan footprint and the heights it spans: its catalog box turned, scaled and moved as placed
    (a 1 m box when the catalog has none)."""
    from .spatial import _quaternion, _rotate_vector
    transform = placement.get("transform") if isinstance(placement.get("transform"), Mapping) else {}
    position = transform.get("position") if isinstance(transform.get("position"), Mapping) else {}
    aabb = (_definition(record).get("geometry") or {}).get("aabb") if record else None
    try:
        px, py, pz = (float(position.get(key, 0) or 0) for key in ("x", "y", "z"))
        q = _quaternion(transform.get("quaternion") or {"x": 0, "y": 0, "z": 0, "w": 1})
        scale = float(transform.get("scale", 1) or 1)
        low, high = (aabb or {}).get("minimum"), (aabb or {}).get("maximum")
        if isinstance(low, Mapping) and isinstance(high, Mapping):
            xs, ys, zs = ((float(low[k]), float(high[k])) for k in ("x", "y", "z"))
        else:
            xs, ys, zs = (-0.5, 0.5), (0.0, 1.0), (-0.5, 0.5)
    except (KeyError, TypeError, ValueError):
        return None
    corners = [_rotate_vector((x * scale, y * scale, z * scale), q) for x in xs for y in ys for z in zs]
    shape = MultiPoint([(px + c[0], pz + c[2]) for c in corners]).convex_hull
    if shape.area <= 0:
        shape = shape.buffer(0.05)
    return {"shape": shape, "bottom": py + min(c[1] for c in corners), "top": py + max(c[1] for c in corners)}


def _zone_shape(zone: Mapping):
    points = [(float(p["x"]), float(p["z"])) for p in zone.get("boundary") or []
              if isinstance(p, Mapping) and "x" in p and "z" in p]
    if len(points) < 3:
        return None
    shape = Polygon(points)
    return shape if shape.is_valid else shape.buffer(0)


def _marking_shape(marking: Mapping):
    try:
        item = lp.normalized_item("floor-marking", marking, None)
    except (lp.PatternError, TypeError, ValueError, KeyError):
        return None
    return Polygon([(p["x"], p["z"]) for p in lp.item_points(item)]), float(item["position"]["y"])


class _Scene:
    """Everything framing reads from one layout: solids, obstacles, zones, the building and its ceiling."""

    def __init__(self, layout: Mapping, catalog: Iterable[Mapping], shell: Mapping | None = None):
        from .light_coverage import blocking_walls, building_footprint
        self.layout = layout
        self.records = records_by_asset(catalog)
        self.placements, self.solids, self.obstacles = {}, {}, []
        lowest = math.inf
        for placement in layout.get("placements") or []:
            identifier = placement.get("placementId") if isinstance(placement, Mapping) else None
            if not isinstance(identifier, str):
                continue
            record = _record(self.records, placement)
            solid = _placement_solid(placement, record)
            if solid is None:
                continue
            tags = _tags(record)
            overhead = bool(tags & {"overhead", "roof-sheeting"})
            solid.update(id=identifier, overhead=overhead,
                         structure=overhead or _category(record) in STRUCTURE or bool(tags & {"roof", "wall"}))
            self.placements[identifier], self.solids[identifier] = placement, solid
            self.obstacles.append(solid)
            if overhead and solid["bottom"] >= LOWEST_CEILING:
                lowest = min(lowest, solid["bottom"])
        try:
            walls = blocking_walls(layout, self.records, shell)
        except (KeyError, TypeError, ValueError):
            walls = []
        for ax, az, bx, bz, bottom, top in walls:
            line = LineString([(ax, az), (bx, bz)])
            if line.length > 0:
                self.obstacles.append({"id": None, "shape": line.buffer(WALL_HALF, cap_style="flat"),
                                       "bottom": float(bottom), "top": float(top), "overhead": False})
        self.tree = STRtree([item["shape"] for item in self.obstacles]) if self.obstacles else None
        self.ceiling = lowest - CEILING_MARGIN if math.isfinite(lowest) else None
        try:
            self.building = building_footprint(layout, self.records)
        except (KeyError, TypeError, ValueError):
            self.building = None
        self.zones = {zone["zoneId"]: zone for zone in layout.get("zones") or []
                      if isinstance(zone, Mapping) and isinstance(zone.get("zoneId"), str)}
        self.zone_shapes = {key: _zone_shape(zone) for key, zone in self.zones.items()}
        self.markings = {mark["markingId"]: mark for mark in layout.get("floorMarkings") or []
                         if isinstance(mark, Mapping) and isinstance(mark.get("markingId"), str)}

    # -- what the user asked for

    def target(self, identifier: str) -> dict | None:
        if identifier in self.solids:
            solid = self.solids[identifier]
            return {"id": identifier, "zone": False, "label": _name(self.placements[identifier], identifier),
                    "shape": solid["shape"], "bottom": solid["bottom"], "top": solid["top"], "ids": [identifier]}
        if identifier in self.markings:
            found = _marking_shape(self.markings[identifier])
            if found is None:
                return None
            shape, floor = found
            return {"id": identifier, "zone": False, "label": _name(self.markings[identifier], identifier),
                    "shape": shape, "bottom": floor, "top": floor + 0.05, "ids": [identifier]}
        if identifier in self.zones and self.zone_shapes.get(identifier) is not None:
            shape, zone = self.zone_shapes[identifier], self.zones[identifier]
            floor = float(zone.get("floorElevation") or 0)
            inside = [key for key, placement in self.placements.items() if not self.solids[key]["structure"]
                      and lp.point_in_polygon((placement.get("transform") or {}).get("position"), zone["boundary"])]
            inside += [key for key, mark in self.markings.items()
                       if lp.point_in_polygon((mark.get("transform") or {}).get("position"), zone["boundary"])]
            heights = [self.solids[key] for key in inside if key in self.solids]
            return {"id": identifier, "zone": True, "label": _name(zone, identifier), "shape": shape,
                    "bottom": min([floor, *(s["bottom"] for s in heights)]),
                    "top": max([floor + 0.1, *(s["top"] for s in heights)]), "ids": [identifier, *inside]}
        return None

    def zone_label(self, point: Point) -> str | None:
        """The smallest zone that holds the point."""
        holding = [(shape.area, key) for key, shape in self.zone_shapes.items()
                   if shape is not None and shape.covers(point)]
        return _name(self.zones[min(holding)[1]], min(holding)[1]) if holding else None

    # -- sight lines

    def looks_through_roof(self, camera: Sequence[float], target: Sequence[float]) -> bool:
        """Whether the line from the camera to the target passes over the building above the ceiling."""
        if self.building is None or self.ceiling is None:
            return False
        line = LineString([(camera[0], camera[2]), (target[0], target[2])])
        if line.length <= 0:
            return self.building.covers(Point(camera[0], camera[2])) and camera[1] > self.ceiling
        part = line.intersection(self.building)
        if part.is_empty:
            return False
        enter = min(line.project(Point(c)) for c in _coordinates(part)) / line.length
        return camera[1] + enter * (target[1] - camera[1]) > self.ceiling

    def clear(self, camera: Sequence[float], target: Sequence[float], area, skip: set, roof_hidden: bool) -> bool:
        """Whether the sight line, in plan (a corridor SIGHT_HALF each side), crosses no obstacle taller than the
        line where it crosses, before it reaches the area."""
        if self.tree is None:
            return True
        line = LineString([(camera[0], camera[2]), (target[0], target[2])])
        length = line.length
        if length <= 0:
            return True
        inside = line.intersection(area)
        enter = min(line.project(Point(c)) for c in _coordinates(inside)) / length if not inside.is_empty else 1.0
        corridor = line.buffer(SIGHT_HALF)
        for index in sorted(int(i) for i in self.tree.query(corridor)):
            item = self.obstacles[index]
            if item["id"] in skip or (roof_hidden and item["overhead"]):
                continue
            cut = corridor.intersection(item["shape"])
            if cut.is_empty:
                continue
            spans = [line.project(Point(c)) / length for c in _coordinates(cut)]
            first, last = min(spans), min(max(spans), enter)
            if first >= enter:
                continue
            high = camera[1] + first * (target[1] - camera[1])
            low = camera[1] + last * (target[1] - camera[1])
            if low <= item["top"] and high >= item["bottom"]:
                return False
        return True


def _coordinates(geometry) -> list:
    if geometry.is_empty:
        return []
    if hasattr(geometry, "geoms"):
        return [c for part in geometry.geoms for c in _coordinates(part)]
    if geometry.geom_type == "Polygon":
        return list(geometry.exterior.coords)
    return list(geometry.coords)


# ---------------------------------------------------------------- the camera

def _direction(heading: float, elevation: float) -> tuple:
    """The unit vector from the target toward a camera at HEADING (0 north, 90 east) and ELEVATION degrees up."""
    h, e = math.radians(heading), math.radians(elevation)
    return (math.sin(h) * math.cos(e), math.sin(e), math.cos(h) * math.cos(e))


def _fit(target: Sequence[float], corners: Sequence[Sequence[float]], back: Sequence[float]) -> float:
    """The nearest distance (at least NEAREST) at which every corner is inside the frame, with FILL's margin."""
    forward = tuple(-v for v in back)
    across = math.hypot(forward[2], forward[0]) or 1.0
    right = (-forward[2] / across, 0.0, forward[0] / across)
    up = (right[1] * forward[2] - right[2] * forward[1], right[2] * forward[0] - right[0] * forward[2],
          right[0] * forward[1] - right[1] * forward[0])
    vertical = math.tan(math.radians(FOV / 2)) * FILL
    horizontal = vertical * ASPECT

    def fits(distance):
        camera = [target[i] + back[i] * distance for i in range(3)]
        for corner in corners:
            v = [corner[i] - camera[i] for i in range(3)]
            depth = sum(v[i] * forward[i] for i in range(3))
            if depth <= 0.1:
                return False
            if (abs(sum(v[i] * right[i] for i in range(3))) > horizontal * depth
                    or abs(sum(v[i] * up[i] for i in range(3))) > vertical * depth):
                return False
        return True

    low = NEAREST
    if fits(low):
        return low
    high = low * 2
    while not fits(high) and high < 20000:
        high *= 2
    for _ in range(40):
        middle = (low + high) / 2
        low, high = (low, middle) if fits(middle) else (middle, high)
    return high


def _round(value: float) -> float:
    return round(float(value), 2) + 0.0


def _point(values: Sequence[float]) -> dict:
    return {"x": _round(values[0]), "y": _round(values[1]), "z": _round(values[2])}


def _frame(scene: _Scene, area: Mapping) -> dict:
    minx, minz, maxx, maxz = area["shape"].bounds
    bottom, top = area["bottom"], max(area["top"], area["bottom"] + 0.1)
    target = ((minx + maxx) / 2, bottom + (top - bottom) / 3, (minz + maxz) / 2)
    corners = [(x, y, z) for x in (minx, maxx) for y in (bottom, top) for z in (minz, maxz)]
    near = box(minx - EDGE, minz - EDGE, maxx + EDGE, maxz + EDGE)
    skip = set(area["ids"])
    chosen = None
    for roof_hidden in (False, True):
        for name, heading in HEADINGS:
            for elevation in ELEVATIONS:
                back = _direction(heading, elevation)
                distance = _fit(target, corners, back)
                camera = tuple(target[i] + back[i] * distance for i in range(3))
                if scene.looks_through_roof(camera, target) != roof_hidden:
                    continue  # first the views under the roof, then the ones that look down through it
                if scene.clear(camera, target, near, skip, roof_hidden):
                    chosen = (name, elevation, camera, roof_hidden, False)
                    break
            if chosen:
                break
        if chosen:
            break
    if chosen is None:  # nothing clear: from the south, high above
        back = _direction(180.0, HIGH_ELEVATION)
        distance = _fit(target, corners, back)
        camera = tuple(target[i] + back[i] * distance for i in range(3))
        chosen = ("south", HIGH_ELEVATION, camera, scene.looks_through_roof(camera, target), True)
    name, elevation, camera, roof_hidden, high = chosen
    return {"label": area["label"],
            "camera": {"position": _point(camera), "target": _point(target), "fov": FOV},
            "from": name, "elevationDegrees": elevation, "roofHidden": roof_hidden, "highView": high,
            "size": {"width": _round(maxx - minx), "depth": _round(maxz - minz), "height": _round(top - bottom)},
            "ids": list(area["ids"][:LISTED_IDS]), "idCount": len(area["ids"])}


# ---------------------------------------------------------------- areas

def _areas(scene: _Scene, targets: Sequence[Mapping]) -> list:
    """The targets grouped by distance (closer than GROUP_GAP), largest first, each named after its zone."""
    parent = list(range(len(targets)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            if targets[i]["shape"].distance(targets[j]["shape"]) <= GROUP_GAP:
                parent[root(j)] = root(i)
    groups = {}
    for i, item in enumerate(targets):
        groups.setdefault(root(i), []).append(item)
    areas = []
    for members in groups.values():
        shape = unary_union([item["shape"] for item in members])
        minx, minz, maxx, maxz = shape.bounds
        zones = sorted((item for item in members if item["zone"]), key=lambda item: (-item["shape"].area, item["id"]))
        label = (zones[0]["label"] if zones
                 else scene.zone_label(Point((minx + maxx) / 2, (minz + maxz) / 2)) or members[0]["label"])
        ids = list(dict.fromkeys(identifier for item in members for identifier in item["ids"]))
        areas.append({"shape": shape, "label": label, "ids": ids, "size": (maxx - minx) * (maxz - minz),
                      "bottom": min(item["bottom"] for item in members), "top": max(item["top"] for item in members)})
    areas.sort(key=lambda area: (-round(area["size"], 6), area["label"], area["ids"][0]))
    seen = {}
    for area in areas:  # two areas in one zone: "Shipping Docks", "Shipping Docks (2)"
        seen[area["label"]] = seen.get(area["label"], 0) + 1
        if seen[area["label"]] > 1:
            area["label"] = f"{area['label']} ({seen[area['label']]})"
    return areas


def frame_views(layout: Mapping, catalog: Iterable[Mapping], ids: Sequence[str], *, max_views: int = DEFAULT_VIEWS,
                shell: Mapping | None = None) -> dict:
    """SV0: views of the items, zones and floor markings IDS name, the main (largest) one first. ValueError when
    none of them is in the layout."""
    scene = _Scene(layout, catalog, shell)
    wanted = sorted(dict.fromkeys(identifier for identifier in ids if isinstance(identifier, str)))
    targets, missing = [], []
    for identifier in wanted:
        found = scene.target(identifier)
        (targets.append(found) if found else missing.append(identifier))
    if not targets:
        raise ValueError("None of those ids is a placement, zone or floor marking in the saved layout"
                         + (f" ({', '.join(missing[:10])})" if missing else "")
                         + ". Find the ids with inspect_facility_context or inspect_facility_semantics.")
    count = max(1, min(MAX_VIEWS, int(max_views or DEFAULT_VIEWS)))
    areas = _areas(scene, targets)
    result = {"views": [_frame(scene, area) for area in areas[:count]]}
    if areas[count:]:
        result["notShown"] = [area["label"] for area in areas[count:]]
    if missing:
        result["notFound"] = missing[:LISTED_IDS]
    return result


# ---------------------------------------------------------------- the last change

# ---------------------------------------------------------------- a name the user said

QUERY_IDS = 240   # as targetIds


def _words(text: Any) -> list:
    """Lower-case words, plurals as singulars ("doors" -> "door", "assemblies" -> "assembly", "boxes" -> "box")."""
    words = []
    for word in re.findall(r"[a-z0-9]+", str(text or "").casefold()):
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith(("xes", "ches", "shes", "sses")):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(word)
    return words


def resolve_query(layout: Mapping, query: str) -> tuple:
    """The ids QUERY names ("R03 robot", "Assembly Cell A06", "the dock doors"): zones, floor markings and placements
    whose name is the query (ignoring case, spacing, plurals and a leading "the"), else whose name holds every word
    of it, zones only when a zone matches (a zone brings what stands in it). Returns (ids, "name" or "words");
    raises ValueError when nothing or too much matches."""
    wanted = _words(query)
    if wanted[:1] == ["the"]:
        wanted = wanted[1:]
    if not wanted:
        raise ValueError("Give the name of what the user asked to see.")
    named = []                                                           # (kind, id, name words)
    for item in layout.get("zones") or []:
        named.append(("zone", item.get("zoneId"), _words(item.get("label"))))
    for item in layout.get("floorMarkings") or []:
        named.append(("marking", item.get("markingId"), _words(item.get("label"))))
    for item in layout.get("placements") or []:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        for label in {metadata.get("instanceLabel"), item.get("label"), item.get("displayName")}:
            named.append(("placement", item.get("placementId"), _words(label)))
    how, matches = "name", [(kind, key) for kind, key, words in named if words and words == wanted]
    if not matches:
        how = "words"
        matches = [(kind, key) for kind, key, words in named if words and set(wanted) <= set(words)]
        if any(kind == "zone" for kind, _ in matches):
            matches = [(kind, key) for kind, key in matches if kind == "zone"]
    ids = sorted({key for _, key in matches if isinstance(key, str) and key})
    if not ids:
        raise ValueError(f'Nothing in the saved layout is named like "{query}". Find it with inspect_facility_context '
                         "or inspect_facility_semantics, then give targetIds, or ask the user what they meant.")
    if len(ids) > QUERY_IDS:
        raise ValueError(f'{len(ids)} items match "{query}". Ask the user which ones, or name them more exactly.')
    return ids, how


def changed_ids(receipt: Mapping) -> list:
    """The ids a saved change's receipt says it created or changed, in order."""
    payload = receipt.get("payload") if isinstance(receipt.get("payload"), Mapping) else {}
    result = payload.get("operationResult") if isinstance(payload.get("operationResult"), Mapping) else payload
    ids = [*(result.get("createdIds") or []), *(result.get("affectedIds") or [])]
    return list(dict.fromkeys(item for item in ids if isinstance(item, str)))


def shown_ids(layout: Mapping, ids: Iterable[str]) -> list:
    """Of IDS, the placements, zones and floor markings still in the layout (a removed item has nothing to show)."""
    present = {item.get(key) for collection, key in (("placements", "placementId"), ("zones", "zoneId"),
                                                     ("floorMarkings", "markingId"))
               for item in layout.get(collection) or [] if isinstance(item, Mapping)}
    return [identifier for identifier in ids if identifier in present]


def live_view(views: Sequence[Mapping], window_open: bool) -> dict:
    """What happens in the user's app window, for Sage to say."""
    if not window_open:
        return {"moves": False, "say": "No app window has this layout open, so nothing moved. Tell the user."}
    main = views[0]
    roof = " The roof is hidden for this view; Back brings it back." if main["roofHidden"] else ""
    return {"moves": True, "to": main["label"],
            "say": (f"The user's 3D view glides to {main['label']}, seen from the {main['from']}; the Back button "
                    f"on the 3D view returns to their view before.{roof} Say so in one short sentence.")}
