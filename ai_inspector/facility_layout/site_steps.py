"""The warehouse built step by step (docs/facility-site-step-build-plan.md, approved 2026-10-24).

Each step adds one layer to the saved layout with the numbers the user gave, and never re-plans an earlier step:
  building  the user's size, position and dock wall: plan, pose, plain walls, slab, the traced lot paved
  zones     receiving and shipping along the dock wall, storage behind, a forklift charging bay at the back
  markings  staging lanes at the dock-door pitch, the cross-aisle edge lines and the walkway
  layout    rack-row outlines and the aisles between them (no models yet)
  docks     door openings lined up with the staging lanes, the truck court, the truck drive and entrance
  parking   the employee car park, its own drive and entrance, the employee door and the walk to it
  contents  racks in the outlined rows, forklifts in the charging bay, trucks at doors, cars in stalls
Paint is site_paint.py, its own review (now the walls too). A step that cannot do what was asked says why
(StepError) instead of changing the request. Frames: property metres (x east, z north); the building's turned
frame (u, w) = site_plan._to_plan; the plan (x 0..width, z 0..depth) = (u - u0, w - w0).
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .site_access import circle_around
from .site_context import KEY, normalize_site_context
from .site_plan import (APRON_METERS, DEFAULTS, PAVING_COLORS, PAVING_GRID_METERS, MAX_GROUND_TILES,
                        MIN_PAVING_TILE_SIDE_METERS, MIN_PAVING_TILE_SQUARE_METERS, SIDES, STREET_EDGE_METERS,
                        _drive_to_frontage, _drive_to_road, _frontages, _largest_rectangle, _outward_bearing, _ring,
                        _slab, _to_plan, _to_property, KIND_RANK)

STEPS = ("building", "zones", "markings", "layout", "docks", "parking", "contents")
COMPASS_BEARING = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}
STEP_DEFAULTS = {"heightMeters": DEFAULTS["wallHeightMeters"], "stagingDepthMeters": 15.0, "chargingDepthMeters": 4.0,
                 "chargingLengthMeters": 20.0, "walkwayWidthMeters": 1.0, "aisleWidthMeters": 3.7,
                 "truckCourtDepthMeters": DEFAULTS["truckCourtDepthMeters"], "driveWidthMeters": DEFAULTS["driveWidthMeters"]}
DOOR_WIDTH, DOOR_PITCH = DEFAULTS["dockDoorWidthMeters"], DEFAULTS["dockDoorSpacingMeters"]
DOOR_END_CLEARANCE = 5.0      # the first and last door keep this far from the building's corners
CAR_CLEARANCE_METERS = 10.0   # the car park and its drive keep this far from the truck court and truck drive
CAR_ENTRANCE_GAP_METERS = 40.0  # and the car entrance this far from the truck entrance
ZONE_IDS = {"receiving": "zn-receiving", "shipping": "zn-shipping", "storage": "zn-storage",
            "charging": "zn-forklift-charging", "court": "zn-truck-court", "parking": "zn-employee-parking"}
SITE_AREAS = ("area-truck-court", "area-truck-drive", "area-employee-parking", "area-car-drive")
STEP_ENTRANCES = ("entrance-truck", "entrance-cars")
MARKING_PREFIXES = ("fm-interior-", "fm-truck-court-", "fm-car-park-")
ROUTE_PREFIXES = ("rt-interior-", "rt-car-park-")
PLACEMENT_PREFIXES = ("pl-truck-court-", "pl-car-park-", "pl-forklift-")
ROW_PREFIX = "fm-interior-row-"  # rack-row outlines; the contents step fills them with racks
LANE_PREFIX = "fm-interior-door-"
YELLOW, WHITE, GREEN = "#facc15", "#ffffff", "#22c55e"
BAY_GAP = 0.02  # between rack bays along a row: real bays share uprights; exact contact would read as a collision
DOOR_HEIGHT_METERS = 3.05          # a 10 ft dock door: the wall closes above it
EMPLOYEE_DOOR_HEIGHT_METERS = 2.4
CLOSED_DOOR_PREFIX = "iw-dock-door-"  # a closed door panel in a dock door with no truck at it (contents step)
CLOSED_DOOR_COLOR = "#d5dadf"


class StepError(ValueError):
    """What the step could not do as asked, and why, in words for the user."""


# ---------------------------------------------------------------- shared reading

def _site(layout: dict) -> dict:
    raw = (layout.get("extensions") or {}).get(KEY)
    if raw is None:
        raise StepError("Place the layout on its site first (Site tab).")
    return normalize_site_context(raw, layout)


def _number(args: dict, key: str, low: float, high: float, default=None) -> float:
    value = args.get(key, STEP_DEFAULTS.get(key, default))
    if value is None:
        raise StepError(f"Give {key}.")
    value = float(value)
    if not low <= value <= high:
        raise StepError(f"{key} must be between {low:g} and {high:g}.")
    return value


def _lot(site: dict):
    """The lot and the part of it clear of each edge's setback (shapely polygons), or (None, None)."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union
    prop = site.get("property")
    if not prop:
        return None, None
    ring = [(p["x"], p["z"]) for p in prop["boundary"]]
    lot = Polygon(ring)
    kind = lambda i: "street" if i in prop["streetEdges"] else "rear" if i in prop["rearEdges"] else "side"  # noqa: E731
    strips = [LineString([ring[i], ring[(i + 1) % len(ring)]]).buffer(prop["setbacksMeters"][kind(i)])
              for i in range(len(ring)) if prop["setbacksMeters"][kind(i)] > 0]
    return lot, (lot.difference(unary_union(strips)) if strips else lot)


def _outline(site: dict, area_id: str | None = None):
    """The traced pavement the warehouse replaces: the named area, else the first existing_pavement area."""
    from shapely.geometry import Polygon
    areas = site.get("areas") or []
    area = next((a for a in areas if a["areaId"] == area_id), None) if area_id else \
        next((a for a in areas if a.get("kind") == "existing_pavement"), None)
    if area_id and area is None:
        raise StepError(f"No outdoor area has the id {area_id}.")
    return Polygon([(p["x"], p["z"]) for p in area["boundary"]]) if area else None


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).casefold())


def _roads(site: dict) -> list[dict]:
    return [road for road in (site.get("roads") or {}).get("items", []) if road.get("kind") in KIND_RANK]


def _road_named(site: dict, name: str) -> dict:
    roads = _roads(site)
    road = next((r for r in roads if _key(r.get("label", "")) == _key(name)), None) or \
        next((r for r in roads if _key(name) and _key(name) in _key(r.get("label", ""))), None)
    if road is None:
        names = sorted({r.get("label", "") for r in roads if r.get("label")})
        raise StepError(f"No mapped street is called {name}. Streets near the site: {', '.join(names) or 'none'}.")
    return road


def _segment_near(road: dict, point) -> tuple[tuple[float, float], tuple[float, float]]:
    from shapely.geometry import LineString, Point
    points = [(p["x"], p["z"]) for p in road["line"]]
    segments = list(zip(points, points[1:]))
    return min(segments, key=lambda s: LineString(s).distance(Point(point)))


def _compass_of(dx: float, dz: float) -> float:
    return math.degrees(math.atan2(dx, dz)) % 360


def _bearing_for_long_side(direction: float) -> float:
    """The building bearing that runs plan +x along `direction` (a compass bearing, either way), choosing the
    one that keeps plan north nearest true north. Plan +x points to bearing + 90 (site_plan._to_property)."""
    options = [(direction - 90) % 360, (direction + 90) % 360]
    return min(options, key=lambda b: min(b, 360 - b))


class Building:
    """The saved building, read back: its size, pose and walls, and the frames every step shares."""

    def __init__(self, layout: dict, site: dict):
        extensions = layout.get("extensions") or {}
        plan = extensions.get("facilityPlan") or {}
        self.walls = (extensions.get("facilityPerimeterWalls") or {}).get("settings")
        if not self.walls or not plan.get("widthMeters") or not site.get("buildingPose"):
            raise StepError("Build the warehouse first: its size, position and dock wall (the building step).")
        self.width, self.depth = float(plan["widthMeters"]), float(plan["depthMeters"])
        pose = site["buildingPose"]
        self.bearing = float(pose["bearingDegrees"])
        self.origin = (float(pose["x"]), float(pose["z"]))
        self.u0, self.w0 = _to_plan(self.bearing, *self.origin)
        self.height = float(self.walls.get("heightMeters", STEP_DEFAULTS["heightMeters"]))

    def property_point(self, x: float, z: float) -> tuple[float, float]:
        dx, dz = _to_property(self.bearing, x, z)
        return self.origin[0] + dx, self.origin[1] + dz

    def plan_point(self, x: float, z: float) -> tuple[float, float]:
        u, w = _to_plan(self.bearing, x, z)
        return u - self.u0, w - self.w0

    def polygon(self):
        from shapely.geometry import Polygon
        return Polygon([self.property_point(x, z) for x, z in
                        ((0, 0), (self.width, 0), (self.width, self.depth), (0, self.depth))])

    def rect(self) -> tuple[float, float, float, float]:
        return (self.u0, self.w0, self.u0 + self.width, self.w0 + self.depth)

    def side_for(self, compass: str) -> str:
        if compass not in COMPASS_BEARING:
            raise StepError("The dock wall is north, east, south or west.")
        target = COMPASS_BEARING[compass]
        return min(SIDES, key=lambda side: min(abs(_outward_bearing(self.bearing, side) - target),
                                               360 - abs(_outward_bearing(self.bearing, side) - target)))

    def frame(self, side: str):
        """(a, d) -> plan (x, z), a along the `side` wall (counter-clockwise), d inward; the wall's length and the
        depth inward; the unit directions of growing a and d (site_interior._frame)."""
        from .site_interior import _frame
        return _frame(side, self.width, self.depth)

    def wall_length(self, side: str) -> float:
        return self.width if side in ("south", "north") else self.depth


def _dock_side(layout: dict, building: Building, given: str | None) -> str:
    """The dock wall: as given, else where the dock doors are, else where the receiving zone meets a wall. A given
    wall that differs from where earlier steps put the doors or receiving is refused, not silently used."""
    if given:
        side = building.side_for(given)
        built = _built_dock_side(layout, building)
        if built and built != side:
            raise StepError(f"The docks are on the {_compass_name(building, built)} wall: the earlier steps put "
                            f"receiving or the doors there. Use that wall, or redo the zones step on the {given} wall.")
        return side
    built = _built_dock_side(layout, building)
    if built:
        return built
    raise StepError("Say which wall the docks are on: north, east, south or west.")


def _built_dock_side(layout: dict, building: Building) -> str | None:
    """Where earlier steps put the docks: the wall with the dock doors, else the one the receiving zone meets."""
    doors = Counter(o["edge"] for o in building.walls.get("openings") or []
                    if abs(o["endMeters"] - o["startMeters"] - DOOR_WIDTH) < 0.05)
    if doors:
        return SIDES[doors.most_common(1)[0][0]]
    zone = next((z for z in layout.get("zones") or [] if z.get("zoneId") == ZONE_IDS["receiving"]), None)
    if zone:
        xs, zs = [p["x"] for p in zone["boundary"]], [p["z"] for p in zone["boundary"]]
        gaps = {"south": min(zs), "north": building.depth - max(zs), "west": min(xs), "east": building.width - max(xs)}
        span = {"south": max(xs) - min(xs), "north": max(xs) - min(xs), "west": max(zs) - min(zs), "east": max(zs) - min(zs)}
        touching = [side for side, gap in gaps.items() if gap < 0.05]
        if touching:
            return max(touching, key=lambda side: span[side])
    return None


def _compass_name(building: Building, side: str) -> str:
    facing = _outward_bearing(building.bearing, side)
    return min(COMPASS_BEARING, key=lambda name: min(abs(COMPASS_BEARING[name] - facing),
                                                    360 - abs(COMPASS_BEARING[name] - facing)))


def door_slots(wall: float, count: int) -> list[tuple[float, float]]:
    """`count` dock doors (or their staging lanes) centred on a wall at the standard pitch: (start, end) metres
    along it. Lanes and doors use the same slots, so doors line up with lanes of the same count."""
    most = max(0, int((wall - 2 * DOOR_END_CLEARANCE - DOOR_WIDTH) // DOOR_PITCH) + 1)
    if count < 1:
        raise StepError("Ask for at least one door.")
    if count > most:
        raise StepError(f"The {wall:.0f} m dock wall takes at most {most} doors at {DOOR_PITCH} m centres.")
    used = (count - 1) * DOOR_PITCH + DOOR_WIDTH
    first = (wall - used) / 2
    return [(round(first + i * DOOR_PITCH, 3), round(first + i * DOOR_PITCH + DOOR_WIDTH, 3)) for i in range(count)]


def max_doors(wall: float) -> int:
    return max(0, int((wall - 2 * DOOR_END_CLEARANCE - DOOR_WIDTH) // DOOR_PITCH) + 1)


def _zone(zone_id: str, zone_type: str, label: str, points) -> dict:
    return {"op": "add_zone", "zone": {"zoneId": zone_id, "zoneType": zone_type, "label": label,
            "boundary": [{"x": round(x, 3) + 0.0, "z": round(z, 3) + 0.0} for x, z in points],
            "floorElevation": 0, "anchors": [], "evidence": []}}


def _zone_rows(layout: dict) -> dict:
    return {z["zoneId"]: z for z in layout.get("zones") or []}


def _delete(layout: dict, *, zones=(), marking_prefixes=(), route_prefixes=(), placement_prefixes=(),
            arrays=False) -> list[dict]:
    """Delete operations for earlier rows of a step, so running a step again replaces its layer."""
    ops = []
    if arrays:
        rows = sorted({str(p["placementId"])[3:].rsplit("-", 1)[0] for p in layout.get("placements") or []
                       if str(p.get("placementId", "")).startswith("pl-racks-")})
        ops += [{"op": "delete_asset_array", "arrayId": row} for row in rows]
    ops += [{"op": "delete_placement", "placementId": p["placementId"]} for p in layout.get("placements") or []
            if str(p.get("placementId", "")).startswith(tuple(placement_prefixes)) and placement_prefixes]
    ops += [{"op": "delete_floor_marking", "markingId": m["markingId"]} for m in layout.get("floorMarkings") or []
            if marking_prefixes and str(m.get("markingId", "")).startswith(tuple(marking_prefixes))]
    ops += [{"op": "delete_route", "routeId": r["routeId"]} for r in layout.get("routes") or []
            if route_prefixes and str(r.get("routeId", "")).startswith(tuple(route_prefixes))]
    present = _zone_rows(layout)
    ops += [{"op": "delete_zone", "zoneId": zone_id} for zone_id in zones if zone_id in present]
    return ops


def _marking(key: str, kind: str, x: float, z: float, width: float, depth: float, rotation: float, color: str,
             role: str, text: str = "", opacity: float = 1.0, label: str | None = None) -> dict:
    return {"op": "add_floor_marking", "floorMarking": {
        "markingId": key, "markingType": kind, "label": (label or key.split("-", 2)[-1].replace("-", " ").title())[:120],
        "semanticRole": role, "transform": {"position": {"x": round(x, 3), "y": 0.008, "z": round(z, 3)},
                                            "rotationDegrees": round(rotation, 3)},
        "width": round(width, 3), "depth": round(depth, 3), "fillColor": color, "strokeColor": color,
        "opacity": opacity, "text": text, "positionMode": "manual", "metadata": {"authoredIn": "site_steps"},
        "evidence": []}}


def _yaw(direction) -> float:
    return math.degrees(math.atan2(direction[0], direction[1]))


def _rack_size(record: dict | None) -> tuple[float, float, float]:
    """A rack bay's length (along its row), depth, and the yaw that turns its long axis along the row.
    The library model runs its bay along z; a prototype box may run it along x (then turn it -90 degrees)."""
    from .site_interior import BAY_LENGTH, RACK_DEPTH, _size
    across, along = _size(record, (RACK_DEPTH, BAY_LENGTH))
    return (along, across, 0.0) if along >= across else (across, along, -90.0)


def _quaternion(yaw_degrees: float) -> dict:
    half = math.radians(yaw_degrees) / 2
    return {"x": 0, "y": round(math.sin(half), 9), "z": 0, "w": round(math.cos(half), 9)}


def _placement(placement_id: str, record: dict, x: float, z: float, yaw: float, label: str, method: str) -> dict:
    return {"op": "place_asset", "placement": {
        "placementId": placement_id, "assetId": record["assetId"],
        "assetDefinitionRevision": record["assetDefinitionRevision"],
        "transform": {"position": {"x": round(x, 3), "y": 0, "z": round(z, 3)}, "quaternion": _quaternion(yaw),
                      "scale": 1},
        "positionMode": "manual", "snapRelationship": None,
        "metadata": {"instanceLabel": label, "inputMethod": method}}}


def _site_context_with(site: dict, entrances_kept: list[dict], entrances_new: list[dict]) -> dict:
    """set_site_context replacing the step entrances; the areas list rides along unchanged."""
    prop = dict(site["property"])
    context = {key: value for key, value in site.items() if key in (
        "version", "georeference", "buildingPose", "imagery", "property", "areas")}  # the proposal keeps the rest
    context["property"] = {key: value for key, value in {**prop, "entrances": entrances_kept + entrances_new}.items()
                           if key in ("boundary", "source", "sourceLabel", "setbacksMeters", "streetEdges",
                                      "rearEdges", "entrances")}
    return {"op": "set_site_context", "siteContext": context}


# ---------------------------------------------------------------- ground (paving), shared by the outdoor steps

def _ground(layout: dict, building: Building, site: dict, features: list[tuple], drop_existing=()) -> dict:
    """The whole paved ground again, square to the building (plan frame), without overlaps.

    features: (polygon in the turned frame, kind) rows a step adds, kind slab | apron | asphalt; earlier steps'
    tiles are kept (except ids in drop_existing), and the traced pavement inside the setbacks becomes yard where
    nothing else is, in PAVING_GRID_METERS steps; crooked leftovers stay green (site_plan._paving)."""
    import numpy as np
    from shapely import contains_xy
    from shapely.geometry import Polygon, box
    kinds = ["slab", "apron", "asphalt", "yard"]
    rows = [(box(*building.rect()), "slab")] + list(features)
    ground = (layout.get("extensions") or {}).get("facilityGround") or {}
    for tile in ground.get("surfaces") or []:
        kind = str(tile.get("surfaceId", "")).split("-")[1] if str(tile.get("surfaceId", "")).startswith("gr-") else None
        if kind in ("apron", "asphalt") and tile["surfaceId"] not in drop_existing:
            rows.append((box(tile["minX"] + building.u0, tile["minZ"] + building.w0,
                             tile["maxX"] + building.u0, tile["maxZ"] + building.w0), kind))
    outline = _outline(site)
    _lot_shape, inset = _lot(site)
    yard = None
    if outline is not None:
        yard = outline.intersection(inset) if inset is not None else outline
        yard = Polygon([_to_plan(building.bearing, x, z) for x, z in yard.exterior.coords]) \
            if yard.geom_type == "Polygon" and not yard.is_empty else None
    bounds = [shape.bounds for shape, _ in rows] + ([yard.bounds] if yard is not None else [])
    min_u, min_w = min(b[0] for b in bounds), min(b[1] for b in bounds)
    max_u, max_w = max(b[2] for b in bounds), max(b[3] for b in bounds)
    edges_u = {round(v, 3) for shape, _ in rows for v in (c[0] for c in shape.exterior.coords)}
    edges_w = {round(v, 3) for shape, _ in rows for v in (c[1] for c in shape.exterior.coords)}
    us = np.array(sorted({round(v, 3) for v in np.arange(min_u, max_u, PAVING_GRID_METERS)} | {round(max_u, 3)} | edges_u))
    ws = np.array(sorted({round(v, 3) for v in np.arange(min_w, max_w, PAVING_GRID_METERS)} | {round(max_w, 3)} | edges_w))
    cu, cw = np.meshgrid((us[:-1] + us[1:]) / 2, (ws[:-1] + ws[1:]) / 2)
    material = np.full(cu.shape, -1)
    for shape, kind in reversed(rows):  # earlier rows win
        material[contains_xy(shape, cu, cw)] = kinds.index(kind)
    if yard is not None:
        material[(material == -1) & contains_xy(yard, cu, cw)] = kinds.index("yard")
    floor = float((layout.get("coordinateFrame") or {}).get("floorElevation", 0))
    tiles = []
    for index, kind in enumerate(kinds):
        free = material == index
        while free.any() and len(tiles) < MAX_GROUND_TILES:
            found = _largest_rectangle(free)
            if not found:
                break
            row, col, nrows, ncols = found
            rect = (us[col], ws[row], us[col + ncols], ws[row + nrows])
            free[row:row + nrows, col:col + ncols] = False
            if kind == "yard" and ((rect[2] - rect[0]) * (rect[3] - rect[1]) < MIN_PAVING_TILE_SQUARE_METERS
                                   or min(rect[2] - rect[0], rect[3] - rect[1]) < MIN_PAVING_TILE_SIDE_METERS):
                break
            tiles.append({"surfaceId": f"gr-{kind}-{len(tiles) + 1}",
                          "minX": round(float(rect[0] - building.u0), 3), "maxX": round(float(rect[2] - building.u0), 3),
                          "minZ": round(float(rect[1] - building.w0), 3), "maxZ": round(float(rect[3] - building.w0), 3),
                          "startElevation": floor, "endElevation": floor, "slopeAxis": "x",
                          "color": PAVING_COLORS["asphalt" if kind == "yard" else kind]})
    result = {"schemaVersion": 1, "surfaces": tiles}
    if ground.get("marks"):
        result["marks"] = ground["marks"]  # the paint step's target stays where it was
    return {"op": "set_ground", "ground": result}


def _drive_features(drive: dict, width: float, bearing: float) -> list[tuple]:
    """A drive's legs as turned-frame rectangles, paved on across the verge to the street (site_plan._drive_rects)."""
    from shapely.geometry import box
    from .site_plan import _drive_rects
    return [(box(*rect), kind) for rect, kind in _drive_rects(drive, width / 2, bearing)]


def _closed_doors_deleted(layout: dict) -> list[dict]:
    walls = ((layout.get("extensions") or {}).get("facilityInteriorWalls") or {}).get("walls") or []
    return [{"op": "delete_interior_wall", "wallId": w["wallId"]} for w in walls
            if str(w.get("wallId", "")).startswith(CLOSED_DOOR_PREFIX)]


def _clear_all(layout: dict, site: dict) -> list[dict]:
    """Everything the later steps built, so a new building starts clean."""
    ops = _delete(layout, zones=ZONE_IDS.values(), marking_prefixes=MARKING_PREFIXES, route_prefixes=ROUTE_PREFIXES,
                  placement_prefixes=PLACEMENT_PREFIXES, arrays=True) + _closed_doors_deleted(layout)
    ops += [{"op": "delete_site_area", "areaId": a["areaId"]} for a in site.get("areas") or [] if a["areaId"] in SITE_AREAS]
    entrances = (site.get("property") or {}).get("entrances") or []
    if any(e["entranceId"] in STEP_ENTRANCES for e in entrances):
        kept = [e for e in entrances if e["entranceId"] not in STEP_ENTRANCES]
        context = _site_context_with(site, kept, [])
        context["siteContext"]["areas"] = [a for a in site.get("areas") or [] if a["areaId"] not in SITE_AREAS]
        ops.append(context)
    return ops


# ---------------------------------------------------------------- step 2: the building

def plan_building(layout: dict, args: dict) -> dict:
    """The user's building: size, height, which way its long side runs, where it stands and its dock wall."""
    from shapely.geometry import Point, Polygon, box
    from shapely.prepared import prep
    site = _site(layout)
    length = _number(args, "lengthMeters", 20, 600)
    width = _number(args, "widthMeters", 20, 600)
    height = _number(args, "heightMeters", 4, 30)
    outline = _outline(site, args.get("areaId"))
    lot, inset = _lot(site)
    region = outline if outline is not None else lot
    if region is None:
        raise StepError("Trace the lot (or set the property line) first, so the building has a place to stand.")
    # Which way the long side runs: along a named street, else the traced lot's long axis.
    align = args.get("alignWith")
    if align and _key(align) not in ("outline", "lot", "lotaxis"):
        road = _road_named(site, align)
        (ax, az), (bx, bz) = _segment_near(road, (region.centroid.x, region.centroid.y))
        direction, aligned = _compass_of(bx - ax, bz - az), f"along {road['label']}"
    else:
        corners = list(region.minimum_rotated_rectangle.exterior.coords)[:4]
        a, b = max(((corners[i], corners[(i + 1) % 4]) for i in range(4)), key=lambda s: math.dist(*s))
        direction, aligned, road = _compass_of(b[0] - a[0], b[1] - a[1]), "along the traced lot's long side", None
    bearing = _bearing_for_long_side(direction)
    turned = Polygon([_to_plan(bearing, x, z) for x, z in region.exterior.coords])
    if args.get("centre"):
        cu, cw = _to_plan(bearing, float(args["centre"]["x"]), float(args["centre"]["z"]))
        placed = "centred where asked"
    else:
        min_u, min_w, max_u, max_w = turned.bounds
        cu, cw = (min_u + max_u) / 2, (min_w + max_w) / 2
        placed = "centred on the traced lot" if outline is not None else "centred on the lot"
    u0, w0 = cu - length / 2, cw - width / 2
    from_street = None
    if args.get("fromStreetMeters") is not None:
        gap = _number(args, "fromStreetMeters", 0, 400)
        street = road or _nearest_street(site, region)
        line_w, reference = _street_line_w(site, street, bearing, lot)
        if line_w < cw:
            w0 = line_w + gap
        else:
            w0 = line_w - gap - width
        from_street = {"street": street["label"], "meters": gap, "measuredFrom": reference}
        placed = f"{gap:g} m back from {street['label']} ({reference})" + (", centred along it" if not args.get("centre") else "")
    building = box(u0, w0, u0 + length, w0 + width)
    footprint = Polygon([_to_property(bearing, u, w) for u, w in building.exterior.coords])
    if inset is not None and not inset.buffer(0.01).covers(footprint):
        raise StepError(_does_not_fit(footprint, inset, lot, bearing, building, length, width))
    if lot is not None and not lot.buffer(0.01).covers(footprint):
        raise StepError("The building would cross the property line.")
    origin = _to_property(bearing, u0, w0)
    plan = dict((layout.get("extensions") or {}).get("facilityPlan") or {})
    ops = _clear_all(layout, site)
    if (layout.get("extensions") or {}).get("facilityPerimeterWalls"):
        ops.append({"op": "set_perimeter_walls", "wallSettings": None})  # a smaller plan cannot hold old openings
    if (layout.get("extensions") or {}).get("facilityGround"):
        ops.append({"op": "set_ground", "ground": None})  # paved ground blocks a new plan size until cleared
    ops += [
        {"op": "set_plan_settings", "planSettings": {"widthMeters": length, "depthMeters": width,
                                                     "gridSpacingMeters": float(plan.get("gridSpacingMeters", 1.0)),
                                                     "majorGridSpacingMeters": float(plan.get("majorGridSpacingMeters", 5.0))}},
        {"op": "set_building_pose", "buildingPose": {"x": round(origin[0], 3), "z": round(origin[1], 3),
                                                     "bearingDegrees": round(bearing, 3)}},
        # Plain walls: their colours, band and logo come with the paint step.
        {"op": "set_perimeter_walls", "wallSettings": {"boundarySource": "plan", "heightMeters": height,
                                                       "thicknessMeters": 0.3, "openings": []}},
        *_slab(layout, length, width),
    ]
    staged_site = dict(site, buildingPose={"x": origin[0], "z": origin[1], "bearingDegrees": bearing})
    staged_plan = {"coordinateFrame": layout.get("coordinateFrame") or {},
                   "extensions": {**(layout.get("extensions") or {}), "facilityPlan": {"widthMeters": length, "depthMeters": width},
                                  "facilityPerimeterWalls": {"settings": {"heightMeters": height, "openings": []}},
                                  "facilityGround": {}}}
    ops.append(_ground(staged_plan, Building(staged_plan, staged_site), staged_site, []))
    dock = None
    staged = Building(staged_plan, staged_site)
    if args.get("dockWall"):
        side = staged.side_for(args["dockWall"])
        room = _room_beyond(staged, side, inset if inset is not None else lot)
        dock = {"wall": args["dockWall"], "planEdge": side, "lengthMeters": round(staged.wall_length(side), 1),
                "maxDoors": max_doors(staged.wall_length(side)), "roomBeyondItMeters": room}
        if room is not None and room < STEP_DEFAULTS["truckCourtDepthMeters"]:
            dock["warning"] = (f"Only {room:.0f} m of the lot lies beyond the whole {args['dockWall']} wall: a "
                               f"{STEP_DEFAULTS['truckCourtDepthMeters']:.0f} m truck court will not fit there"
                               + (" (20 m is the least for straight trucks)" if room < 20 else "")
                               + ". Tell the user now; moving or turning the building, or another dock wall, gives more room.")
    covered = round(footprint.intersection(outline).area / footprint.area * 100) if outline is not None else None
    return {"available": True, "step": "building", "operations": ops, "summary": {
        "building": {"lengthMeters": length, "widthMeters": width, "heightMeters": height,
                     "areaSquareMeters": round(length * width, 1), "longSide": aligned,
                     "longSideBearingDegrees": round((bearing + 90) % 180, 1), "placed": placed,
                     **({"fromStreet": from_street} if from_street else {}),
                     "clearanceToLotEdgesMeters": _clearances(staged, lot) if lot is not None else None,
                     **({"onTracedPavementPercent": covered} if covered is not None else {})},
        "dockWall": dock,
        "walls": "plain; colours, the white band and the logo come with the paint step",
        "paving": "the traced lot paved inside the setbacks, the slab under the building",
        "next": ("Pass dockWall: " + args["dockWall"] + " to the zones, markings, layout and docks steps.")
                if args.get("dockWall") else "Say which wall the docks go on before the zones step.",
        "defaultsUsed": {key: STEP_DEFAULTS[key] for key in ("heightMeters",) if key not in args}}}


def _nearest_street(site: dict, region) -> dict:
    roads = _roads(site)
    if not roads:
        raise StepError("No mapped street to measure from; give centre instead.")
    from shapely.geometry import LineString
    return min(roads, key=lambda r: LineString([(p["x"], p["z"]) for p in r["line"]]).distance(region.centroid))


def _street_line_w(site: dict, street: dict, bearing: float, lot) -> tuple[float, str]:
    """Where `street` runs in the turned frame (a w): its lot line when the property has one along it, else
    its centre line. A county parcel marks no street edges: then a property edge of 10 m or more within 30 m of
    the street and running along it (within 20 degrees) is its lot line, as a user means "back from the street"."""
    from shapely.geometry import LineString, Point
    line = LineString([(p["x"], p["z"]) for p in street["line"]])
    prop = site.get("property")
    if prop and lot is not None:
        ring = [(p["x"], p["z"]) for p in prop["boundary"]]
        edges = [(i, (ring[i], ring[(i + 1) % len(ring)])) for i in range(len(ring))]
        near = [(i, e) for i, e in edges if i in prop["streetEdges"] and LineString(e).distance(line) < 30]

        def along_street(edge) -> bool:
            (ax, az), (bx, bz) = edge
            at = line.project(Point((ax + bx) / 2, (az + bz) / 2))
            (sx, sz), (tx, tz) = (line.interpolate(max(0.0, at - 5.0)).coords[0],
                                  line.interpolate(min(line.length, at + 5.0)).coords[0])
            turn = abs(math.degrees(math.atan2(bz - az, bx - ax) - math.atan2(tz - sz, tx - sx))) % 180
            return min(turn, 180 - turn) <= 20

        if not near and not prop.get("streetEdges"):
            near = [(i, e) for i, e in edges if math.dist(*e) >= 10 and LineString(e).distance(line) < 30
                    and along_street(e)]
        if near:
            _i, (a, b) = max(near, key=lambda item: math.dist(*item[1]))
            return (_to_plan(bearing, *a)[1] + _to_plan(bearing, *b)[1]) / 2, "its lot line"
    points = [_to_plan(bearing, x, z) for x, z in line.coords]
    return sum(w for _, w in points) / len(points), "its centre line"


def _does_not_fit(footprint, inset, lot, bearing, building, length, width) -> str:
    """Why the building does not fit inside the setbacks, and the nearest place it would."""
    import numpy as np
    from shapely.affinity import translate
    from shapely.prepared import prep
    over = footprint.difference(inset)
    turned_over = [_to_plan(bearing, x, z) for part in getattr(over, "geoms", [over]) if part.geom_type == "Polygon"
                   for x, z in part.exterior.coords]
    u0, w0, u1, w1 = building.bounds
    worst = max((max(u0 - u, u - u1, w0 - w, w - w1, 0.0) for u, w in turned_over), default=0.0)
    allowed = prep(inset.buffer(0.01))
    best = None
    for radius in np.arange(1.0, 80.0, 1.0):
        for angle in range(0, 360, 10):
            du, dw = radius * math.cos(math.radians(angle)), radius * math.sin(math.radians(angle))
            dx, dz = _to_property(bearing, du, dw)
            if allowed.covers(translate(footprint, dx, dz)):
                best = (radius, dx, dz)
                break
        if best:
            break
    text = f"A {length:g} x {width:g} m building does not fit there inside the lot's setbacks ({over.area:.0f} m2 over the line)."
    if best:
        text += (f" It fits {best[0]:.0f} m to the {_compass_word(best[1], best[2])}: give fromStreetMeters or centre "
                 "to move it, or make it smaller.")
    else:
        from shapely.geometry import Polygon
        turned = Polygon([_to_plan(bearing, x, z) for x, z in inset.exterior.coords]) if inset.geom_type == "Polygon" else None
        if turned is not None:
            cells = _grid(turned)
            if cells:
                text += f" At this angle the largest building that fits is about {cells[0]:.0f} x {cells[1]:.0f} m."
    return text


def _grid(turned) -> tuple[float, float] | None:
    import numpy as np
    from shapely import contains_xy
    min_u, min_w, max_u, max_w = turned.bounds
    us, ws = np.arange(min_u + 0.5, max_u, 1.0), np.arange(min_w + 0.5, max_w, 1.0)
    if not len(us) or not len(ws):
        return None
    gu, gw = np.meshgrid(us, ws)
    found = _largest_rectangle(contains_xy(turned, gu, gw))
    return (found[3] * 1.0, found[2] * 1.0) if found else None


def _compass_word(dx: float, dz: float) -> str:
    from .site_plan import COMPASS
    return COMPASS[round(_compass_of(dx, dz) / 45) % 8]


def _clearances(building: "Building", lot) -> dict:
    """How deep the open lot reaches straight out from each whole wall (compass names): a crooked lot line can
    come close at one end of a wall while its middle has room, so the whole wall counts."""
    return {_compass_name(building, side): _room_beyond(building, side, lot) for side in SIDES}


def _room_beyond(building: Building, side: str, space) -> float | None:
    """How deep the free space beyond `side` reaches inside `space` (the setbacks), along the whole wall."""
    if space is None:
        return None
    from shapely.geometry import box
    u0, w0, u1, w1 = building.rect()
    depth = 0.0
    for step in range(1, 301):
        d = float(step)
        rect = {"south": (u0, w0 - d, u1, w0), "north": (u0, w1, u1, w1 + d),
                "west": (u0 - d, w0, u0, w1), "east": (u1, w0, u1 + d, w1)}[side]
        from shapely.geometry import Polygon
        shape = Polygon([_to_property(building.bearing, u, w) for u, w in box(*rect).exterior.coords])
        if not space.buffer(0.01).covers(shape):
            break
        depth = d
    return depth


# ---------------------------------------------------------------- step 3: zones

def plan_zones(layout: dict, args: dict) -> dict:
    site = _site(layout)
    building = Building(layout, site)
    side = _dock_side(layout, building, args.get("dockWall"))
    at, wall, deep, _a_dir, _d_dir = building.frame(side)
    stage = _number(args, "stagingDepthMeters", 4, deep / 2)
    share = float(args.get("receivingShare", 0.5))
    if not 0.1 <= share <= 0.9:
        raise StepError("receivingShare is between 0.1 and 0.9 of the dock wall.")
    charge_depth = _number(args, "chargingDepthMeters", 0, deep / 4)
    charge_length = min(_number(args, "chargingLengthMeters", 0, 300), wall)
    split = wall * share
    zones = [("receiving", "receiving", "Receiving", [(0, 0), (split, 0), (split, stage), (0, stage)]),
             ("shipping", "shipping", "Shipping", [(split, 0), (wall, 0), (wall, stage), (split, stage)])]
    storage = [(0, stage), (wall, stage), (wall, deep)]
    if charge_depth > 0 and charge_length > 0:
        storage += [(charge_length, deep), (charge_length, deep - charge_depth), (0, deep - charge_depth)]
        zones.append(("charging", "charging", "Forklift charging",
                      [(0, deep - charge_depth), (charge_length, deep - charge_depth), (charge_length, deep), (0, deep)]))
    else:
        storage += [(0, deep)]
    zones.insert(2, ("storage", "storage", "Storage", storage))
    ops = _delete(layout, zones=[ZONE_IDS[name] for name in ("receiving", "shipping", "storage", "charging")])
    for name, zone_type, label, points in zones:
        ops.append(_zone(ZONE_IDS[name], zone_type, label, [at(a, d) for a, d in points]))
    areas = {name: round(_area([at(a, d) for a, d in points]), 1) for name, _t, _l, points in zones}
    return {"available": True, "step": "zones", "operations": ops, "summary": {
        "dockWall": _compass_name(building, side), "stagingDepthMeters": stage,
        "receiving": f"{split:.1f} x {stage:g} m", "shipping": f"{wall - split:.1f} x {stage:g} m",
        "charging": f"{charge_length:g} x {charge_depth:g} m along the back wall" if charge_depth > 0 else None,
        "areasSquareMeters": areas,
        "defaultsUsed": {key: STEP_DEFAULTS[key] for key in ("stagingDepthMeters", "chargingDepthMeters",
                                                             "chargingLengthMeters") if key not in args}}}


def _area(points) -> float:
    from shapely.geometry import Polygon
    return Polygon(points).area


def _staging_depth(layout: dict, building: Building, side: str) -> float:
    """How deep the receiving zone reaches from the dock wall (the zones step), else the default."""
    zone = _zone_rows(layout).get(ZONE_IDS["receiving"])
    if not zone:
        return STEP_DEFAULTS["stagingDepthMeters"]
    xs, zs = [p["x"] for p in zone["boundary"]], [p["z"] for p in zone["boundary"]]
    return round({"south": max(zs), "north": building.depth - min(zs), "west": max(xs),
                  "east": building.width - min(xs)}[side], 3)


def _charging(layout: dict, building: Building, side: str) -> tuple[float, float]:
    """The charging bay's (length along the back wall, depth), from the zones step; (0, 0) without one."""
    zone = _zone_rows(layout).get(ZONE_IDS["charging"])
    if not zone:
        return 0.0, 0.0
    xs, zs = [p["x"] for p in zone["boundary"]], [p["z"] for p in zone["boundary"]]
    if side in ("south", "north"):
        return max(xs) - min(xs), max(zs) - min(zs)
    return max(zs) - min(zs), max(xs) - min(xs)


# ---------------------------------------------------------------- step 4: floor markings

def plan_markings(layout: dict, args: dict) -> dict:
    site = _site(layout)
    building = Building(layout, site)
    side = _dock_side(layout, building, args.get("dockWall"))
    at, wall, deep, a_dir, d_dir = building.frame(side)
    stage = _staging_depth(layout, building, side)
    lanes = int(args.get("stagingLanes", max_doors(wall)))
    slots = door_slots(wall, lanes) if lanes else []
    walkway = _number(args, "walkwayWidthMeters", 0, 5)
    aisle = STEP_DEFAULTS["aisleWidthMeters"]
    ops = _delete(layout, marking_prefixes=(LANE_PREFIX, "fm-interior-cross-", "fm-interior-walkway"))
    lane_depth = max(2.0, stage - 2.0)
    for number, (start, end) in enumerate(slots, start=1):
        x, z = at((start + end) / 2, lane_depth / 2 + 0.5)
        ops.append(_marking(f"{LANE_PREFIX}{number:02}", "parking_box", x, z, end - start + 0.4, lane_depth,
                            _yaw(d_dir), WHITE, "staging", f"DOOR {number}", label=f"Staging lane {number}"))
    span = (0.5, wall - 0.5)
    if args.get("aisleEdgeLines", True):
        for key, d in (("cross-aisle-edge-staging", stage), ("cross-aisle-edge-racks", stage + aisle)):
            x, z = at(sum(span) / 2, d)
            ops.append(_marking("fm-interior-" + key, "solid_line", x, z, 0.1, span[1] - span[0], _yaw(a_dir),
                                YELLOW, "forklift_lane", label=key.replace("-", " ").capitalize()))
    if walkway > 0:
        x, z = at(sum(span) / 2, stage + aisle + walkway / 2)
        ops.append(_marking("fm-interior-walkway", "solid_line", x, z, walkway, span[1] - span[0], _yaw(a_dir), GREEN,
                            "pedestrian_lane", opacity=0.75, label="Walkway"))
    return {"available": True, "step": "markings", "operations": ops, "summary": {
        "dockWall": _compass_name(building, side), "stagingLanes": len(slots),
        "laneCentresMeters": [round((s + e) / 2, 2) for s, e in slots],
        "crossAisle": f"{aisle:g} m between the staging area and storage, yellow edge lines",
        "walkwayWidthMeters": walkway,
        "doors": "The docks step puts its doors on these lanes when it is given the same count.",
        "defaultsUsed": {**({"stagingLanes": len(slots)} if "stagingLanes" not in args else {}),
                         **({"walkwayWidthMeters": walkway} if "walkwayWidthMeters" not in args else {})}}}


def _lanes(layout: dict) -> list[dict]:
    return sorted((m for m in layout.get("floorMarkings") or [] if str(m.get("markingId", "")).startswith(LANE_PREFIX)),
                  key=lambda m: m["markingId"])


# ---------------------------------------------------------------- step 5: rack rows and aisles

AISLE_EDGE = 0.01  # metres between a rack face and the aisle's edge


def plan_layout(layout: dict, args: dict, catalog: dict | None = None) -> dict:
    from .site_interior import FLUE, MIDDLE_AISLE_OVER, RACK_ASSET, WALL_GAP
    site = _site(layout)
    building = Building(layout, site)
    side = _dock_side(layout, building, args.get("dockWall"))
    at, wall, deep, a_dir, d_dir = building.frame(side)
    stage = _staging_depth(layout, building, side)
    aisle = _number(args, "aisleWidthMeters", 2.5, 6)
    # The rows stand AISLE_EDGE clear of each aisle's edges: an aisle exactly the asked width touching the rack faces
    # counts as obstructed (live 2026-10-24), and the aisle keeps the width asked for (the PDF labels it).
    space = aisle + 2 * AISLE_EDGE
    walkway = next((m["width"] for m in layout.get("floorMarkings") or [] if m.get("markingId") == "fm-interior-walkway"),
                   STEP_DEFAULTS["walkwayWidthMeters"])
    charge_length, charge_depth = _charging(layout, building, side)
    across = (args.get("rowDirection") or "across") in ("across", "perpendicular", "square")
    bay, rack_depth, _turn = _rack_size((catalog or {}).get(RACK_ASSET))
    pitch = bay + BAY_GAP
    double = 2 * rack_depth + FLUE
    start, end = stage + space + walkway, deep - charge_depth - space  # rows between the walkway and the back aisle
    if end - start < 2 * bay:
        raise StepError("There is no room for rack rows between the staging area and the back wall.")
    ops = _delete(layout, marking_prefixes=(ROW_PREFIX,), route_prefixes=("rt-interior-",))
    span = (WALL_GAP, wall - WALL_GAP)

    def route(key, label, points):
        ops.append({"op": "add_aisle", "routeId": "rt-interior-" + key, "aisle": {
            "label": label, "centerline": [{"x": round(x, 3), "y": 0, "z": round(z, 3)} for x, z in (at(a, d) for a, d in points)],
            "corridorWidth": aisle, "aisleKind": "forklift", "direction": "two_way", "color": "#d9a514",
            "clearanceEvidenceStatus": "unverified"}})
    route("cross-aisle", "Cross aisle", [(span[0], stage + space / 2), (span[1], stage + space / 2)])
    route("back-aisle", "Back aisle", [(span[0], end + space / 2), (span[1], end + space / 2)])
    rows = []  # (label, a centre, d centre, length along a, length along d)
    if across:  # double rows run inward, aisles between them
        blocks = [(start, end)]
        if end - start > MIDDLE_AISLE_OVER and args.get("crossAisle", "auto") != "none":
            middle = (start + end) / 2
            blocks = [(start, middle - space / 2), (middle + space / 2, end)]
            route("middle-aisle", "Middle cross aisle", [(span[0], middle), (span[1], middle)])
        count = int((wall - 2 * WALL_GAP - space) // (double + space))
        a = WALL_GAP + (wall - 2 * WALL_GAP - space - count * (double + space)) / 2
        centres = [a + space / 2]
        for number in range(1, count + 1):
            middle_of_double = a + space + double / 2
            for face, offset in (("a", -(rack_depth + FLUE) / 2), ("b", (rack_depth + FLUE) / 2)):
                for block, (d0, d1) in enumerate(blocks, start=1):
                    bays = int((d1 - d0 + BAY_GAP) // pitch)
                    if bays:
                        rows.append((f"{number:02}{face}-{block}", middle_of_double + offset, (d0 + d1) / 2, rack_depth,
                                     bays * pitch - BAY_GAP, bays))
            a += space + double
            centres.append(a + space / 2)
        for index, centre in enumerate(centres, start=1):
            route(f"rack-aisle-{index:02}", f"Rack aisle {index}", [(centre, start - walkway), (centre, end + space / 2)])
    else:  # double rows run along the dock wall, aisles between them
        blocks = [span]
        if span[1] - span[0] > MIDDLE_AISLE_OVER and args.get("crossAisle", "auto") != "none":
            middle = sum(span) / 2
            blocks = [(span[0], middle - space / 2), (middle + space / 2, span[1])]
            route("middle-aisle", "Middle aisle", [(middle, start - walkway), (middle, end + space / 2)])
        count = int((end - start - space) // (double + space)) if end - start > space + double else 0
        d = start + (end - start - space - count * (double + space)) / 2
        for number in range(1, count + 1):
            middle_of_double = d + space + double / 2
            for face, offset in (("a", -(rack_depth + FLUE) / 2), ("b", (rack_depth + FLUE) / 2)):
                for block, (a0, a1) in enumerate(blocks, start=1):
                    bays = int((a1 - a0 + BAY_GAP) // pitch)
                    if bays:
                        rows.append((f"{number:02}{face}-{block}", (a0 + a1) / 2, middle_of_double + offset,
                                     bays * pitch - BAY_GAP, rack_depth, bays))
            route(f"rack-aisle-{number:02}", f"Rack aisle {number}", [(span[0], d + space / 2), (span[1], d + space / 2)])
            d += space + double
    for key, a, d, along_a, along_d, bays in rows:
        x, z = at(a, d)
        # A marking's depth runs along its local z, turned by rotationDegrees like a yaw: the row's length.
        rotation, wide, long = (_yaw(d_dir), along_a, along_d) if along_d >= along_a else (_yaw(a_dir), along_d, along_a)
        # A rack footprint to keep clear until the racks arrive: never a parking bay (parking_box would put the
        # storage zone under the car-park review and print PARKING on the plan).
        ops.append(_marking(ROW_PREFIX + key, "keep_clear", x, z, wide, long, rotation, YELLOW, "decorative", "RACKS",
                            label=f"Rack row {key.upper()} ({bays} bays)", opacity=0.9))
    return {"available": True, "step": "layout", "operations": ops, "summary": {
        "dockWall": _compass_name(building, side), "rowDirection": "across the building, square to the dock wall" if across
        else "along the dock wall", "rackRows": len(rows), "rackBays": sum(r[5] for r in rows),
        "aisleWidthMeters": aisle, "rackBay": f"{bay:.2f} x {rack_depth:.2f} m pallet rack, back to back with a {FLUE} m flue",
        "rackRowOutlines": "yellow outlines on the floor where the racks will stand",
        "racks": "outlined only; the contents step fills the rows with rack models",
        "defaultsUsed": {**({"aisleWidthMeters": aisle} if "aisleWidthMeters" not in args else {}),
                         **({"rowDirection": "across"} if "rowDirection" not in args else {})}}}


# ---------------------------------------------------------------- step 6: docks

def _site_geometry(site: dict, layout: dict):
    """The saved truck court and drives as shapely polygons (property frame), when the steps made them."""
    from shapely.geometry import Polygon
    return {a["areaId"]: Polygon([(p["x"], p["z"]) for p in a["boundary"]]) for a in site.get("areas") or []
            if a["areaId"] in SITE_AREAS}


def plan_docks(layout: dict, args: dict) -> dict:
    from shapely.geometry import LineString, Polygon, box
    site = _site(layout)
    building = Building(layout, site)
    side = _dock_side(layout, building, args.get("dockWall"))
    wall = building.wall_length(side)
    lanes = _lanes(layout)
    count = int(args.get("doors", len(lanes) or max_doors(wall)))
    slots = door_slots(wall, count)
    lined_up = bool(lanes) and len(lanes) == count
    court = _number(args, "truckCourtDepthMeters", 20, 60)
    drive_width = STEP_DEFAULTS["driveWidthMeters"]
    lot, inset = _lot(site)
    u0, w0, u1, w1 = building.rect()
    court_box = {"south": (u0, w0 - court, u1, w0), "north": (u0, w1, u1, w1 + court),
                 "west": (u0 - court, w0, u0, w1), "east": (u1, w0, u1 + court, w1)}[side]
    court_property = Polygon([_to_property(building.bearing, u, w) for u, w in box(*court_box).exterior.coords])
    space = inset if inset is not None else lot
    if space is not None and not space.buffer(0.01).covers(court_property):
        room = _room_beyond(building, side, space)
        raise StepError(f"A {court:g} m truck court does not fit beyond the {_compass_name(building, side)} wall: the lot "
                        f"allows {room:.0f} m there inside its setbacks. Ask for a shallower court (20 m is the "
                        "least for straight trucks), or move or shrink the building.")
    built = _site_geometry(site, layout)
    roads = _roads(site)
    rails = [LineString([(p["x"], p["z"]) for p in r["line"]]) for r in (site.get("roads") or {}).get("items", [])
             if r.get("kind") == "railroad"]
    street = _road_named(site, args["entranceStreet"]) if args.get("entranceStreet") else None
    if lot is not None:
        frontages = _frontages(site, [street] if street else roads, rails, drive_width)
        drive = _drive_to_frontage(court_property, building.polygon(), frontages, rails, building.bearing, lot,
                                   drive_width) if frontages else None
    else:
        drive = _drive_to_road(court_box, side, building.bearing, building.polygon(), [street] if street else roads, rails)
    if drive is None:
        raise StepError("No truck drive reaches " + (street["label"] if street else "a street") + " from the court "
                        "without crossing the building, a railway or the lot line"
                        + (", or within the street's corner and rail-crossing clearances" if lot is not None else "")
                        + ". Try another street, or move the building.")
    # Walls: the dock doors on the dock wall; other openings (the employee door) stay.
    edge = SIDES.index(side)
    openings = [o for o in building.walls.get("openings") or []
                if not (o["edge"] == edge and abs(o["endMeters"] - o["startMeters"] - DOOR_WIDTH) < 0.05)]
    openings += [{"edge": edge, "startMeters": s, "endMeters": e, "heightMeters": DOOR_HEIGHT_METERS} for s, e in slots]
    ops = _delete(layout, zones=[ZONE_IDS["court"]], marking_prefixes=("fm-truck-court-",),
                  placement_prefixes=("pl-truck-court-",)) + _closed_doors_deleted(layout)
    ops.append({"op": "edit_perimeter_walls", "patch": {"openings": sorted(openings, key=lambda o: (o["edge"], o["startMeters"]))}})
    # The court's zone (trucks stand in it) and the counter-clockwise arrows (site_trucks.py, without trucks).
    from .site_trucks import operations as court_operations
    ops += court_operations({"size": (building.width, building.depth), "side": side, "doors": slots}, {"truckCourtDepthMeters": court}, None)
    strip = LineString(drive["line"]).buffer(drive_width / 2, cap_style=2, join_style=2)
    strip = strip.difference(court_property.buffer(0.02, join_style=2)).difference(building.polygon().buffer(0.02, join_style=2))
    if lot is not None:
        strip = strip.intersection(lot.buffer(-0.02, join_style=2))
    if strip.geom_type != "Polygon":
        strip = max(getattr(strip, "geoms", []), key=lambda part: part.area, default=strip)
    entrances = (site.get("property") or {}).get("entrances") or []
    if drive.get("entrance") and site.get("property"):
        kept = [e for e in entrances if e["entranceId"] != "entrance-truck"]
        ops.append(_site_context_with(site, kept, [{"entranceId": "entrance-truck", **drive["entrance"], "use": "trucks",
                                                    "widthMeters": drive_width}]))
    ops.append({"op": "upsert_site_area", "area": {"areaId": "area-truck-court", "label": "Truck court", "kind": "truck_court",
                "surface": "concrete", "boundary": _ring(court_property.difference(building.polygon().buffer(0.02, join_style=2)))}})
    ops.append({"op": "upsert_site_area", "area": {"areaId": "area-truck-drive", "label": f"Truck drive to {drive['road']}",
                "kind": "drive", "surface": "asphalt", "boundary": _ring(strip)}})
    apron = min(APRON_METERS, court)
    rects = {"south": [((u0, w0 - apron, u1, w0), "apron"), ((u0, w0 - court, u1, w0 - apron), "asphalt")],
             "north": [((u0, w1, u1, w1 + apron), "apron"), ((u0, w1 + apron, u1, w1 + court), "asphalt")],
             "west": [((u0 - apron, w0, u0, w1), "apron"), ((u0 - court, w0, u0 - apron, w1), "asphalt")],
             "east": [((u1, w0, u1 + apron, w1), "apron"), ((u1 + apron, w0, u1 + court, w1), "asphalt")]}[side]
    features = [(box(*rect), kind) for rect, kind in rects] + _drive_features(drive, drive_width, building.bearing)
    ops.append(_ground(layout, building, site, features,
                       drop_existing=_tiles_under(layout, building, [built.get(a) for a in ("area-truck-court", "area-truck-drive")])))
    routes = _routes(site, ops)
    return {"available": True, "step": "docks", "operations": ops, "summary": {
        "dockWall": _compass_name(building, side), "doors": len(slots),
        "doorsLinedUpWithStagingLanes": lined_up if lanes else None,
        **({"note": f"The floor has {len(lanes)} staging lanes for {len(slots)} doors: redo the markings step with "
                    f"stagingLanes: {len(slots)} to line them up."} if lanes and not lined_up else {}),
        "truckCourtDepthMeters": court, "apronMeters": apron,
        "truckDrive": {key: value for key, value in drive.items() if key != "line"},
        "routesToMainRoad": routes,
        "circulation": "counter-clockwise: in along the outside of the court, back along the dock wall",
        "defaultsUsed": {**({"doors": count} if "doors" not in args else {}),
                         **({"truckCourtDepthMeters": court} if "truckCourtDepthMeters" not in args else {})}}}


def _tiles_under(layout: dict, building: Building, shapes) -> set:
    """Earlier apron and asphalt tiles under the saved areas a step replaces (its old court and drive, or its old
    car park and drive), so running the step again repaves only its own ground."""
    from shapely.geometry import Polygon, box
    turned = [Polygon([building.plan_point(x, z) for x, z in shape.exterior.coords]) for shape in shapes
              if shape is not None and shape.geom_type == "Polygon"]
    ground = (layout.get("extensions") or {}).get("facilityGround") or {}
    return {t["surfaceId"] for t in ground.get("surfaces") or []
            if str(t.get("surfaceId", "")).startswith(("gr-apron-", "gr-asphalt-"))
            and any(box(t["minX"], t["minZ"], t["maxX"], t["maxZ"]).intersection(shape).area > 1.0 for shape in turned)}


def _routes(site: dict, ops: list[dict]) -> list[dict]:
    from .site_access import vehicle_routes
    staged = next((op["siteContext"]["property"] for op in ops if op["op"] == "set_site_context"), site.get("property"))
    if not staged:
        return []
    routes = vehicle_routes({"property": staged, "roads": site.get("roads")})
    return [{key: route[key] for key in ("use", "mainRoad", "roads", "lengthMeters", "localStreetMeters",
                                         "railCrossingsAtGrade")} for route in routes]


# ---------------------------------------------------------------- step 7: parking

def plan_parking(layout: dict, args: dict) -> dict:
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import unary_union
    from .site_parking import (AISLE, CAR_DRIVE_WIDTH, STALL_DEPTH, door_opening, operations as car_park_operations,
                               plan_car_park, stalls_needed)
    site = _site(layout)
    building = Building(layout, site)
    lot, inset = _lot(site)
    if lot is None:
        raise StepError("The car park needs the property line, so its entrance can be placed on the street edge.")
    stalls = int(args.get("stalls", stalls_needed(building.width * building.depth)))
    if not 1 <= stalls <= 400:
        raise StepError("Ask for 1 to 400 stalls.")
    built = _site_geometry(site, layout)
    court, truck_drive = built.get("area-truck-court"), built.get("area-truck-drive")
    truck_entrance = next(((e["x"], e["z"]) for e in (site.get("property") or {}).get("entrances") or []
                           if e["entranceId"] == "entrance-truck"), None)
    trucks = [shape for shape in (court, truck_drive) if shape is not None]
    # Keep clear of the trucks: their court and drive, and everything between the truck entrance and the court.
    keep_out = []
    if trucks:
        keep_out.append(unary_union(trucks).convex_hull.buffer(CAR_CLEARANCE_METERS, join_style=2))
    region = inset.difference(unary_union(keep_out)) if keep_out else inset
    side = None
    if args.get("side"):
        side = building.side_for(args["side"])
        u0, w0, u1, w1 = building.rect()
        far = 5000.0
        beyond = {"south": (u0 - far, w0 - far, u1 + far, w0), "north": (u0 - far, w1, u1 + far, w1 + far),
                  "west": (u0 - far, w0 - far, u0, w1 + far), "east": (u1, w0 - far, u1 + far, w1 + far)}[side]
        half = Polygon([_to_property(building.bearing, u, w) for u, w in box(*beyond).exterior.coords])
        region = region.intersection(half)
    if region.is_empty or region.area < 100:
        raise StepError(_parking_refusal(building, side, args, "there is no room there clear of the truck court and drive"))
    if region.geom_type != "Polygon":
        region = max(region.geoms, key=lambda part: part.area)
    roads = _roads(site)
    rails = [LineString([(p["x"], p["z"]) for p in r["line"]]) for r in (site.get("roads") or {}).get("items", [])
             if r.get("kind") == "railroad"]
    street = _road_named(site, args["entranceStreet"]) if args.get("entranceStreet") else None
    frontages = _frontages(site, [street] if street else roads, rails, CAR_DRIVE_WIDTH)
    if truck_entrance is not None:  # its own entrance, well apart from the trucks'
        disc = circle_around(Point(truck_entrance), CAR_ENTRANCE_GAP_METERS)
        frontages = [(road, line, [(index, part) for index, piece in pieces
                                   for part in getattr(piece.difference(disc), "geoms", [piece.difference(disc)])
                                   if part.geom_type == "LineString" and part.length > 0.5])
                     for road, line, pieces in frontages]
        frontages = [item for item in frontages if item[2]]
    if not frontages:
        raise StepError(_parking_refusal(building, side, args, f"no stretch of {street['label'] if street else 'street'} "
                                         f"is left for a car entrance {CAR_ENTRANCE_GAP_METERS:g} m from the truck entrance"))
    truck_strip = unary_union(trucks) if trucks else None
    parking = plan_car_park(region, building.polygon(), court if court is not None else building.polygon().buffer(0.0),
                            truck_strip.buffer(CAR_CLEARANCE_METERS - 2.0) if truck_strip is not None else None,
                            truck_entrance, frontages, rails, lot, building.bearing, stalls)
    if parking is None:
        reason = "no rectangle there takes a row of stalls with its aisle and its own drive to the street"
        if keep_out and _fits_without_trucks(building, side, inset, frontages, rails, lot, stalls):
            reason = ("the only room there is in the trucks' way: within "
                      f"{CAR_CLEARANCE_METERS:g} m of the truck court and drive, or between the truck entrance and the court")
        raise StepError(_parking_refusal(building, side, args, reason))
    origin = (building.u0, building.w0)
    car_drive = LineString(parking["drive"]["line"]).buffer(CAR_DRIVE_WIDTH / 2, cap_style=2, join_style=2)
    if truck_strip is not None and car_drive.distance(truck_strip) < CAR_CLEARANCE_METERS - 0.01:
        raise StepError(_parking_refusal(building, side, args, "its drive would pass within "
                                         f"{CAR_CLEARANCE_METERS:g} m of the truck court or drive"))
    ops = _delete(layout, zones=[ZONE_IDS["parking"]], marking_prefixes=("fm-car-park-",), route_prefixes=("rt-car-park-",),
                  placement_prefixes=("pl-car-park-",))
    door = {**door_opening(parking, origin, building.width, building.depth), "heightMeters": EMPLOYEE_DOOR_HEIGHT_METERS}
    openings = [o for o in building.walls.get("openings") or [] if abs(o["endMeters"] - o["startMeters"] - 1.8) >= 0.05]
    if not any(o["edge"] == door["edge"] and o["startMeters"] < door["endMeters"] and o["endMeters"] > door["startMeters"]
               for o in openings):
        openings.append(door)
    ops.append({"op": "edit_perimeter_walls", "patch": {"openings": sorted(openings, key=lambda o: (o["edge"], o["startMeters"]))}})
    ops += car_park_operations(parking, origin, None)  # zone, stall paint, aisle, walk; cars come with the contents step
    # The two-way centre line runs on along the drive, out to the street edge like its paving.
    from .site_plan import _drive_legs
    for number, ((au, aw), (bu, bw)) in enumerate(_drive_legs(parking["drive"], building.bearing), start=1):
        length = math.hypot(bu - au, bw - aw)
        if length < 0.5:
            continue
        ops.append(_marking(f"fm-car-park-drive-center-{number:02}", "dashed_line", (au + bu) / 2 - origin[0],
                            (aw + bw) / 2 - origin[1], 0.12, length, 90.0 if abs(aw - bw) < 0.5 else 0.0, YELLOW,
                            "decorative", label=f"Car drive centre line {number}"))
    entrances = (site.get("property") or {}).get("entrances") or []
    if parking["drive"].get("entrance"):
        kept = [e for e in entrances if e["entranceId"] != "entrance-cars"]
        ops.append(_site_context_with(site, kept, [{"entranceId": "entrance-cars", **parking["drive"]["entrance"],
                                                    "use": "cars", "widthMeters": CAR_DRIVE_WIDTH}]))
    park = parking["park"]
    ops.append({"op": "upsert_site_area", "area": {"areaId": "area-employee-parking", "label": "Employee parking",
                "kind": "parking", "surface": "asphalt", "boundary": _ring(park)}})
    car = car_drive
    for keep_clear in [park, building.polygon()] + trucks:
        car = car.difference(keep_clear.buffer(0.02, join_style=2))
    car = car.intersection(lot.buffer(-0.02, join_style=2))
    if car.geom_type != "Polygon":
        car = max(getattr(car, "geoms", []), key=lambda part: part.area, default=car)
    if car.geom_type == "Polygon" and not car.is_empty:
        ops.append({"op": "upsert_site_area", "area": {"areaId": "area-car-drive",
                    "label": f"Car drive to {parking['drive']['road']}", "kind": "drive", "surface": "asphalt",
                    "boundary": _ring(car)}})
    features = [(box(*parking["rect"]), "asphalt")] + _drive_features(parking["drive"], CAR_DRIVE_WIDTH, building.bearing)
    ops.append(_ground(layout, building, site, features,
                       drop_existing=_tiles_under(layout, building, [built.get(a) for a in ("area-employee-parking", "area-car-drive")])))
    entrance = parking["drive"].get("entrance")
    gap = round(math.dist((entrance["x"], entrance["z"]), truck_entrance), 1) if entrance and truck_entrance else None
    clearance = round(min(park.distance(shape) for shape in trucks), 1) if trucks else None
    return {"available": True, "step": "parking", "operations": ops, "summary": {
        "stallsRequested": stalls, "stallsPlaced": len(parking["stalls"]),
        "accessibleStalls": sum(1 for s in parking["stalls"] if s["kind"] != "standard"),
        "rows": parking["rows"], "side": args.get("side") or "where it fits best",
        "carDrive": {key: value for key, value in parking["drive"].items() if key != "line"},
        "carEntranceFromTruckEntranceMeters": gap, "clearOfTrucksMeters": clearance,
        "rules": f"own entrance at least {CAR_ENTRANCE_GAP_METERS:g} m from the truck entrance; never between the "
                 f"truck entrance and the court; at least {CAR_CLEARANCE_METERS:g} m from the court and the truck drive",
        "employeeDoor": door, "routesToMainRoad": _routes(site, ops),
        **({"note": f"Only {len(parking['stalls'])} of {stalls} stalls fit there."} if len(parking["stalls"]) < stalls else {}),
        "defaultsUsed": {**({"stalls": stalls} if "stalls" not in args else {})}}}


def _fits_without_trucks(building: Building, side: str | None, inset, frontages, rails, lot, stalls: int) -> bool:
    """Whether a car park would fit on that side if the trucks were not there: then they are the reason."""
    from shapely.geometry import Polygon, box
    from .site_parking import plan_car_park
    region = inset
    if side:
        u0, w0, u1, w1 = building.rect()
        far = 5000.0
        beyond = {"south": (u0 - far, w0 - far, u1 + far, w0), "north": (u0 - far, w1, u1 + far, w1 + far),
                  "west": (u0 - far, w0 - far, u0, w1 + far), "east": (u1, w0 - far, u1 + far, w1 + far)}[side]
        region = region.intersection(Polygon([_to_property(building.bearing, u, w) for u, w in box(*beyond).exterior.coords]))
    if region.is_empty:
        return False
    if region.geom_type != "Polygon":
        region = max(region.geoms, key=lambda part: part.area)
    return plan_car_park(region, building.polygon(), building.polygon(), None, None, frontages, rails, lot,
                         building.bearing, stalls) is not None


def _parking_refusal(building: Building, side: str | None, args: dict, reason: str) -> str:
    where = f" {args['side']} of the building" if side else ""
    return (f"No car park for {args.get('stalls', 'the')} stalls fits{where}: {reason}. Try another side or street, or "
            "fewer stalls.")


# ---------------------------------------------------------------- step 8: contents

def plan_contents(layout: dict, args: dict, catalog: dict | None) -> dict:
    from .site_interior import RACK_ASSET, FORKLIFT_ASSET, _size
    from .site_parking import CAR_ASSETS
    from .site_trucks import REAR_GAP_METERS, TRUCK_ASSET, TRUCK_HALF_LENGTH
    site = _site(layout)
    building = Building(layout, site)
    catalog = catalog or {}
    ops = _delete(layout, placement_prefixes=PLACEMENT_PREFIXES, arrays=True) + _closed_doors_deleted(layout)
    counts = Counter()
    notes = []
    docked = set()  # (edge, start) of the doors a truck stands at
    # Racks fill every outlined row (the layout step).
    rows = [m for m in layout.get("floorMarkings") or [] if str(m.get("markingId", "")).startswith(ROW_PREFIX)]
    rack = catalog.get(RACK_ASSET)
    if args.get("racks", True):
        if not rows:
            notes.append("No rack rows are outlined yet: run the layout step first.")
        elif not rack:
            notes.append("The library has no pallet rack.")
        else:
            bay, _depth, turn = _rack_size(rack)
            pitch = bay + BAY_GAP
            for row in rows:
                length, rotation = float(row["depth"]), float(row["transform"]["rotationDegrees"])
                bays = int(round((length + BAY_GAP) / pitch))  # the outline is bays x pitch - gap, to the millimetre
                if bays < 1:
                    continue
                direction = (math.sin(math.radians(rotation)), math.cos(math.radians(rotation)))
                cx, cz = row["transform"]["position"]["x"], row["transform"]["position"]["z"]
                first = (cx - direction[0] * pitch * (bays - 1) / 2, cz - direction[1] * pitch * (bays - 1) / 2)
                key = str(row["markingId"])[len(ROW_PREFIX):]
                ops.append({"op": "place_asset_array", "arrayId": f"racks-{key}", "placement": {
                    "assetId": RACK_ASSET, "assetDefinitionRevision": rack["assetDefinitionRevision"],
                    "transform": {"position": {"x": round(first[0], 3), "y": 0, "z": round(first[1], 3)},
                                  "quaternion": _quaternion(rotation + turn), "scale": 1},
                    "positionMode": "manual", "snapRelationship": None,
                    "metadata": {"instanceLabel": f"Rack {key.upper()} bay", "inputMethod": "site-steps-contents"}},
                    "step": {"x": round(direction[0] * pitch, 6), "y": 0, "z": round(direction[1] * pitch, 6)}, "count": bays})
                # The racks now show the row: its yellow outline would paint the floor under them. It stays, faded
                # out, so the contents can be planned again.
                ops.append({"op": "edit_floor_marking", "markingId": row["markingId"], "patch": {"opacity": 0.0}})
                counts["rackBays"] += bays
                counts["rackRows"] += 1
    # Forklifts side by side in the charging bay (the zones step).
    zones = _zone_rows(layout)
    forklift = catalog.get(FORKLIFT_ASSET)
    wanted = int(args.get("forklifts", 4))
    if wanted:
        bay_zone = zones.get(ZONE_IDS["charging"])
        if not bay_zone:
            notes.append("No charging bay to park forklifts in: run the zones step with a charging bay.")
        elif not forklift:
            notes.append("The library has no forklift.")
        else:
            width, length = _size(forklift, (1.13, 1.96))
            xs, zs = [p["x"] for p in bay_zone["boundary"]], [p["z"] for p in bay_zone["boundary"]]
            along_x = max(xs) - min(xs) >= max(zs) - min(zs)
            run, across = (max(xs) - min(xs), max(zs) - min(zs)) if along_x else (max(zs) - min(zs), max(xs) - min(xs))
            spacing = width + 1.0
            fit = int(run // spacing)
            if across < length + 0.2:
                notes.append("The charging bay is too shallow for a forklift.")
                fit = 0
            for number in range(min(wanted, fit)):
                offset = (run - min(wanted, fit) * spacing) / 2 + spacing * (number + 0.5)
                x, z = (min(xs) + offset, (min(zs) + max(zs)) / 2) if along_x else ((min(xs) + max(xs)) / 2, min(zs) + offset)
                yaw = 0.0 if along_x else 90.0
                ops.append(_placement(f"pl-forklift-{number + 1:02}", forklift, x, z, yaw, f"Forklift {number + 1}",
                                      "site-steps-contents"))
                counts["forklifts"] += 1
            if wanted > fit:
                notes.append(f"Only {fit} forklifts fit in the charging bay.")
    # Trucks backed up to dock doors, spread along the dock wall (the docks step).
    truck = catalog.get(TRUCK_ASSET)
    wanted = int(args.get("trucks", 0) or 0)
    door_rows = [o for o in building.walls.get("openings") or [] if abs(o["endMeters"] - o["startMeters"] - DOOR_WIDTH) < 0.05]
    if wanted:
        if not door_rows:
            notes.append("No dock doors yet: run the docks step first.")
        elif not truck:
            notes.append("The library has no truck.")
        else:
            from .site_trucks import _wall
            edge = Counter(o["edge"] for o in door_rows).most_common(1)[0][0]
            side = SIDES[edge]
            doors = sorted([(o["startMeters"], o["endMeters"]) for o in door_rows if o["edge"] == edge])
            chosen = _spread(doors, min(wanted, len(doors)))
            at, out, _along = _wall(side, building.width, building.depth)
            aabb = ((truck.get("definition") or {}).get("geometry") or {}).get("aabb") or {}
            half = -float((aabb.get("minimum") or {}).get("z", -TRUCK_HALF_LENGTH))
            yaw = _yaw(out)
            for number, (start, end) in enumerate(chosen, start=1):
                docked.add((edge, start))
                x, z = at((start + end) / 2)
                ops.append(_placement(f"pl-truck-court-{number:02}", truck, x + out[0] * (REAR_GAP_METERS + half),
                                      z + out[1] * (REAR_GAP_METERS + half), yaw, f"Truck at door {doors.index((start, end)) + 1}",
                                      "site-steps-contents"))
                counts["trucks"] += 1
            if wanted > len(doors):
                notes.append(f"There are only {len(doors)} doors.")
    # Cars in the car park's standard stalls, nose in toward the aisle (the parking step).
    cars = [catalog[a] for a in CAR_ASSETS if a in catalog]
    wanted = int(args.get("cars", 0) or 0)
    if wanted:
        stalls = [m for m in layout.get("floorMarkings") or [] if str(m.get("markingId", "")).startswith("fm-car-park-stall-")
                  and not m.get("text")]
        aisle = next((r for r in layout.get("routes") or [] if r.get("routeId") == "rt-car-park-aisle"), None)
        walk = next((r for r in layout.get("routes") or [] if r.get("routeId") == "rt-car-park-walk"), None)
        if not stalls or aisle is None:
            notes.append("No car park yet: run the parking step first.")
        elif not cars:
            notes.append("The library has no car.")
        else:
            from shapely.geometry import LineString, Point, box
            line = LineString([(p["x"], p["z"]) for p in (aisle.get("geometry") or aisle.get("aisle") or aisle).get("centerline", [])]) \
                if (aisle.get("geometry") or aisle.get("aisle") or aisle).get("centerline") else None
            walkway = LineString([(p["x"], p["z"]) for p in (walk.get("geometry") or walk.get("aisle") or walk)["centerline"]]).buffer(1.0, cap_style=2) \
                if walk is not None and (walk.get("geometry") or walk.get("aisle") or walk).get("centerline") else None
            free = []
            for stall in sorted(stalls, key=lambda m: m["markingId"]):
                x, z = stall["transform"]["position"]["x"], stall["transform"]["position"]["z"]
                w, d = float(stall["width"]), float(stall["depth"])
                if walkway is not None and walkway.intersects(box(x - w / 2, z - d / 2, x + w / 2, z + d / 2)):
                    continue
                free.append((x, z))
            for number, (x, z) in enumerate(_spread(free, min(wanted, len(free))), start=1):
                if line is not None:
                    near = line.interpolate(line.project(Point(x, z)))
                    yaw = _yaw((near.x - x, near.y - z))
                else:
                    yaw = 0.0
                ops.append(_placement(f"pl-car-park-{number:03}", cars[0], x, z, yaw, f"Parked car {number}",
                                      "site-steps-contents"))
                counts["cars"] += 1
            if wanted > len(free):
                notes.append(f"Only {len(free)} stalls are free for cars.")
    # A dock door with no truck at it is closed: a door panel just inside the opening (an interior wall piece).
    floor = float((layout.get("coordinateFrame") or {}).get("floorElevation", 0))
    for opening in door_rows:
        if (opening["edge"], opening["startMeters"]) in docked:
            continue
        frame = building.frame(SIDES[opening["edge"]])[0]
        (sx, sz), (ex, ez) = frame(opening["startMeters"], 0.1), frame(opening["endMeters"], 0.1)
        number = counts["closedDoors"] + 1
        ops.append({"op": "upsert_interior_wall", "wall": {
            "wallId": f"{CLOSED_DOOR_PREFIX}{opening['edge']}-{round(opening['startMeters'] * 100):05d}",
            "label": f"Closed dock door {number}", "start": {"x": round(sx, 3), "z": round(sz, 3)},
            "end": {"x": round(ex, 3), "z": round(ez, 3)}, "heightMeters": opening.get("heightMeters", DOOR_HEIGHT_METERS),
            "thicknessMeters": 0.1, "baseElevation": floor, "color": CLOSED_DOOR_COLOR, "openings": []}})
        counts["closedDoors"] += 1
    if not counts:
        raise StepError(" ".join(notes) or "Nothing to place.")
    return {"available": True, "step": "contents", "operations": ops, "summary": {
        **dict(counts), "unpainted": "the models arrive in their plain colours; the paint step colours them",
        **({"notes": notes} if notes else {})}}


def _spread(items: list, count: int) -> list:
    """`count` of `items`, spread evenly from one end to the other."""
    if count <= 0 or not items:
        return []
    if count >= len(items):
        return list(items)
    step = len(items) / count
    return [items[int(i * step + step / 2)] for i in range(count)]


PLANNERS = {"building": plan_building, "zones": plan_zones, "markings": plan_markings, "docks": plan_docks,
            "parking": plan_parking}
